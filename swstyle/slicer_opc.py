"""Orca Slicer 2.5's packed vendor profiles (resources/profiles/<Vendor>.opc).

From Orca Slicer 2.5 the Windows build ships each vendor's printer, filament and process presets only inside one
cache file per vendor (the <Vendor>.json index and the preset JSON files are pruned at build time). This reads that
file into the same shape the add-on reads the JSON profiles in: the vendor index (name, version, machine_model_list)
and one dict per preset with its settings as a JSON profile writes them (text, lists of text).

The format, from Orca Slicer v2.5.1 src/libslic3r/PresetCacheFormat.cpp (CACHE_VERSION 2):
  header: magic "ZCRO" (uint32 0x4F52435A little endian), version, body size (uint64), CRC-32 of the body
  body (cereal binary: little endian, sizes uint64, strings = size + bytes):
    cache version (uint32), vendor name, vendor version,
    option dictionary: keys [string], types [uint16], enum value names [string],
    vendors: map<string, VendorProfile>,
    process, filament, machine presets: uint32 count, then per preset
        name, sub_path, config (uint32 count of (uint16 key index, value)), inherits, includes [string],
        description, instantiation, setting_id, filament_id, renamed_from [string],
    parse errors (uint64).
Only the Python standard library."""
import struct
import zlib

MAGIC = 0x4F52435A
CACHE_VERSION = 2

# ConfigOptionType (Config.hpp)
VEC = 0x4000
FLOAT, INT, STRING, PERCENT, FLOAT_OR_PERCENT, POINT, POINT3, BOOL, ENUM = 1, 2, 3, 4, 5, 6, 7, 8, 9
POINTS_GROUPS, INTS_GROUPS = 10 + VEC, 11 + VEC
NIL_INT = -2147483648          # ConfigOptionIntsNullable::nil_value()


class OpcError(ValueError):
    pass


class _Reader:
    def __init__(self, data):
        self.b = memoryview(data)
        self.i = 0

    def take(self, n):
        if self.i + n > len(self.b):
            raise OpcError("cache ends early")
        out = self.b[self.i:self.i + n]
        self.i += n
        return out

    def u8(self):
        return self.take(1)[0]

    def u16(self):
        return struct.unpack_from("<H", self.take(2))[0]

    def u32(self):
        return struct.unpack_from("<I", self.take(4))[0]

    def i32(self):
        return struct.unpack_from("<i", self.take(4))[0]

    def u64(self):
        return struct.unpack_from("<Q", self.take(8))[0]

    def f64(self):
        return struct.unpack_from("<d", self.take(8))[0]

    def size(self, limit=50000000):
        n = self.u64()
        if n > limit:
            raise OpcError("size out of bounds")
        return n

    def string(self):
        return bytes(self.take(self.size())).decode("utf-8", "replace")

    def strings(self):
        return [self.string() for _ in range(self.size())]


def _num(v):
    """A number as Orca writes it in a profile (no trailing .0)."""
    if v != v or v in (float("inf"), float("-inf")):
        return str(v)
    return "%.15g" % v


def _float_or_percent(r):
    v, pct = r.f64(), r.u8()
    return _num(v) + ("%" if pct else "")


def _value(r, kind, enums):
    """One option's value as profile text: a string, or a list of strings for a vector option."""
    if kind in (ENUM, ENUM + VEC):
        n = r.u32()
        out = []
        for _ in range(n):
            idx = r.u16()
            if idx >= len(enums):
                raise OpcError("enum index out of range")
            if idx == 0:
                raw = r.i32()
                out.append("nil" if raw == NIL_INT else str(raw))
            else:
                out.append(enums[idx])
        return out[0] if kind == ENUM and out else out
    if kind == FLOAT or kind == PERCENT:
        v = _num(r.f64())
        return v + "%" if kind == PERCENT else v
    if kind == INT:
        return str(r.i32())
    if kind == STRING:
        return r.string()
    if kind == BOOL:
        return "1" if r.u8() else "0"
    if kind == FLOAT_OR_PERCENT:
        # ConfigOptionFloatOrPercent: the ConfigOptionPercent base (a double), then the percent flag
        return _float_or_percent(r)
    if kind == POINT:
        return "%sx%s" % (_num(r.f64()), _num(r.f64()))
    if kind == POINT3:
        return ",".join(_num(r.f64()) for _ in range(3))
    if kind in (FLOAT + VEC, PERCENT + VEC):
        vals = [r.f64() for _ in range(r.size())]
        # a nullable vector's nil is a NaN (ConfigOptionFloatsNullable)
        return ["nil" if v != v else (_num(v) + ("%" if kind == PERCENT + VEC else "")) for v in vals]
    if kind == INT + VEC:
        return ["nil" if v == NIL_INT else str(v) for v in (r.i32() for _ in range(r.size()))]
    if kind == STRING + VEC:
        return r.strings()
    if kind == BOOL + VEC:
        out = []
        for _ in range(r.size()):
            v = r.u8()
            out.append("nil" if v == 0xFF else ("1" if v else "0"))
        return out
    if kind == FLOAT_OR_PERCENT + VEC:
        return [_float_or_percent(r) for _ in range(r.size())]
    if kind == POINT + VEC:
        return ["%sx%s" % (_num(r.f64()), _num(r.f64())) for _ in range(r.size())]
    if kind == POINTS_GROUPS:
        groups = []
        for _ in range(r.size()):
            groups.append(",".join("%sx%s" % (_num(r.f64()), _num(r.f64())) for _ in range(r.size())))
        return groups
    if kind == INTS_GROUPS:
        groups = []
        for _ in range(r.size()):
            groups.append(",".join(str(r.i32()) for _ in range(r.size())))
        return groups
    raise OpcError("option type %d not known" % kind)


def _config(r, keys, types, enums):
    out = {}
    for _ in range(r.u32()):
        idx = r.u16()
        if idx >= len(keys):
            raise OpcError("option index out of range")
        out[keys[idx]] = _value(r, types[idx], enums)
    return out


def _variant(r):
    return r.string()


def _model(r):
    m = {}
    m["id"], m["name"], m["model_id"] = r.string(), r.string(), r.string()
    m["technology"] = r.u8()                     # PrinterTechnology : unsigned char
    m["family"] = r.string()
    m["variants"] = [_variant(r) for _ in range(r.size())]
    for key in ("default_materials", "not_support_bed_types"):
        m[key] = r.strings()
    for key in ("bed_model", "bed_texture", "image_bed_type", "bottom_texture_end_name",
                "use_double_extruder_default_texture", "bottom_texture_rect", "bottom_texture_rect_longer",
                "middle_texture_rect", "hotend_model"):
        m[key] = r.string()
    return m


def _vendor(r):
    v = {}
    v["name"], v["id"] = r.string(), r.string()
    v["version"] = r.string()                    # Semver, saved as its text (save_minimal)
    v["config_update_url"], v["changelog_url"] = r.string(), r.string()
    v["models"] = [_model(r) for _ in range(r.size())]
    v["default_filaments"] = r.strings()         # std::set<std::string>: size + items, like a vector
    v["default_sla_materials"] = r.strings()
    return v


def _presets(r, keys, types, enums):
    out = []
    for _ in range(r.u32()):
        p = {"name": r.string(), "sub_path": r.string()}
        p["config"] = _config(r, keys, types, enums)
        p["inherits"] = r.string()
        p["includes"] = r.strings()
        p["description"] = r.string()
        p["instantiation"] = r.string()
        p["setting_id"] = r.string()
        p["filament_id"] = r.string()
        p["renamed_from"] = r.strings()
        out.append(p)
    return out


def body(path):
    """The checked body of a cache file (magic, size, CRC), or OpcError."""
    with open(str(path), "rb") as f:
        raw = f.read()
    if len(raw) < 20:
        raise OpcError("not a preset cache")
    magic, _version, size, crc = struct.unpack_from("<IIQI", raw, 0)
    if magic != MAGIC:
        raise OpcError("not a preset cache")
    data = raw[20:]
    if size != len(data) or size == 0:
        raise OpcError("cache size does not match")
    if zlib.crc32(data) & 0xFFFFFFFF != crc:
        raise OpcError("cache CRC does not match")
    return data


def read(path, vendors_only=False):
    """{"vendor", "version", "vendors": {name: profile}, "process"/"filament"/"machine": [preset]}."""
    r = _Reader(body(path))
    if r.u32() != CACHE_VERSION:
        raise OpcError("cache version not known")
    vendor, version = r.string(), r.string()
    keys = r.strings()
    types = [r.u16() for _ in range(r.size())]
    enums = r.strings()
    if len(keys) != len(types) or not enums or enums[0] != "":
        raise OpcError("cache dictionary damaged")
    vendors = {}
    for _ in range(r.size()):
        name = r.string()
        vendors[name] = _vendor(r)
    out = {"vendor": vendor, "version": version, "vendors": vendors}
    if vendors_only:
        return out
    for kind in ("process", "filament", "machine"):
        out[kind] = _presets(r, keys, types, enums)
    out["parse_errors"] = r.u64()
    return out


def vendor_index(path):
    """The vendor's <Vendor>.json as the profile folder would have it: name, version, machine_model_list."""
    data = read(path, vendors_only=True)
    v = data["vendors"].get(data["vendor"]) or {}
    return {"name": v.get("name") or data["vendor"], "version": data["version"],
            "machine_model_list": [{"name": m["name"], "sub_path": ""} for m in v.get("models", [])],
            "models": v.get("models", [])}


def profiles(path):
    """[(kind, sub_path, data)] of every preset in the cache, data as a profile JSON file holds it."""
    data = read(path)
    out = []
    for kind in ("machine", "filament", "process"):
        for p in data[kind]:
            d = dict(p["config"])
            d["name"] = p["name"]
            d["type"] = kind
            if p["inherits"]:
                d["inherits"] = p["inherits"]
            if p["includes"]:
                d["include"] = list(p["includes"])
            if p["instantiation"]:
                d["instantiation"] = p["instantiation"]
            for key in ("setting_id", "filament_id", "description"):
                if p[key]:
                    d[key] = p[key]
            if p["renamed_from"]:
                d["renamed_from"] = list(p["renamed_from"])
            out.append((kind, p["sub_path"], d))
    return out
