"""PrusaSlicer's command line, for Quick Slice: PrusaSlicer lists its own presets (the printers, then the print and
filament presets made for a printer) as JSON and slices by preset name, so the add-on reads no preset files of its own
(PrusaSlicer 3.0 keeps them as YAML with conditions only it evaluates; 2.6 and newer take the same options).

  --query-printer-models                                 {"printer_models": [{"variants": [{"printer_profiles": ...}]}]}
  --query-print-tool-filament-profiles --printer-profile  {"print_profiles": [{"name", "filament_profiles"}]}
  --printer-profile P --print-profile Q --material-profile M [...] --export-gcode --output F  model.stl ...

Nothing here starts a window; every call runs the add-on's own copy (slicer.SLICERS["prusa"].exe())."""
import json
import os
import subprocess
import tempfile
from pathlib import Path

TIMEOUT = 120


# inside FreeCAD's Linux AppImage these point into FreeCAD's bundle, which another program must not see (as the
# panel's slices: slicerui.clean_env)
_BUNDLE_VARS = ("LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH",
                "QT_QPA_PLATFORM_PLUGIN_PATH", "APPDIR", "APPIMAGE", "ARGV0", "OWD", "GDK_PIXBUF_MODULE_FILE",
                "GSETTINGS_SCHEMA_DIR", "FONTCONFIG_FILE", "FONTCONFIG_PATH", "XDG_DATA_DIRS", "SSL_CERT_FILE")


def _env():
    env = dict(os.environ)
    if os.name != "nt" and env.get("APPDIR"):
        for var in _BUNDLE_VARS:
            env.pop(var, None)
    return env


def _run(exe, args, timeout=TIMEOUT):
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x08000000      # CREATE_NO_WINDOW
    return subprocess.run([str(exe)] + [str(a) for a in args], capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace", env=_env(), **kw)


def _query(exe, args, datadir=None):
    """Run one query; PrusaSlicer writes its JSON to --output."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.json"
        extra = ["--datadir", str(datadir)] if datadir else []
        r = _run(exe, extra + args + ["--output", str(out)])
        if not out.is_file():
            raise RuntimeError((r.stderr or r.stdout or "PrusaSlicer gave no answer").strip()[-400:])
        return json.loads(out.read_text(encoding="utf-8"))


def printer_names(data):
    """Every printer preset in a --query-printer-models answer, in PrusaSlicer's order: [(model, printer)]."""
    rows = []
    for model in data.get("printer_models") or []:
        groups = model.get("variants") or [model]
        for v in groups:
            for key in ("printer_profiles", "user_printer_profiles"):
                for p in v.get(key) or []:
                    name = p.get("name") if isinstance(p, dict) else p
                    if name and (model.get("name"), name) not in rows:
                        rows.append((model.get("name") or "", name))
    return rows


def printer_info(data):
    """{printer: {"extruders", "bed": (width, depth, height)}} from the same answer."""
    out = {}
    for model in data.get("printer_models") or []:
        for v in model.get("variants") or [model]:
            for key in ("printer_profiles", "user_printer_profiles"):
                for p in v.get(key) or []:
                    if not isinstance(p, dict) or not p.get("name"):
                        continue
                    bed = p.get("bed") or {}
                    out[p["name"]] = {"extruders": int(p.get("extruders_cnt") or 1),
                                      "bed": (float(bed.get("width") or 0), float(bed.get("height") or 0),
                                              float(bed.get("max_print_height") or 0)),
                                      "model": model.get("name") or "", "variant": v.get("name") or ""}
    return out


def print_profiles(data):
    """[(print preset, [filament presets], [tool print presets])] from a --query-print-tool-filament-profiles answer."""
    rows = []
    for p in data.get("print_profiles") or []:
        rows.append((p.get("name") or "", list(p.get("filament_profiles") or p.get("sla_material_profiles") or []),
                     list(p.get("tool_print_profiles") or [])))
    return [r for r in rows if r[0]]


class Presets:
    """PrusaSlicer's presets as PrusaSlicer lists them, kept for the session (one query per printer)."""

    def __init__(self, exe, datadir=None):
        self.exe, self.datadir = exe, datadir
        self._models = None
        self._prints = {}

    def models(self):
        if self._models is None:
            self._models = _query(self.exe, ["--query-printer-models"], self.datadir)
        return self._models

    def printers(self):
        return [name for _model, name in printer_names(self.models())]

    def info(self, printer):
        return printer_info(self.models()).get(printer, {"extruders": 1, "bed": (0, 0, 0), "model": ""})

    def _for(self, printer):
        if printer not in self._prints:
            self._prints[printer] = print_profiles(_query(
                self.exe, ["--query-print-tool-filament-profiles", "--printer-profile", printer], self.datadir))
        return self._prints[printer]

    def processes(self, printer):
        return [name for name, _f, _t in self._for(printer)]

    def filaments(self, printer, process=None):
        """The filaments made for the printer (and the print preset, when given), in PrusaSlicer's order."""
        seen = []
        for name, fils, _t in self._for(printer):
            if process and name != process:
                continue
            for f in fils:
                if f not in seen:
                    seen.append(f)
        return seen


def slice_args(meshes, printer, process, filaments, out_file, datadir=None, arrange=True, config=None):
    """The command line that slices meshes with the named presets into out_file (G-code). filaments: one per
    extruder in use (PrusaSlicer fills the rest with the first). config: an .ini of changed settings, loaded on top."""
    args = ["--datadir", str(datadir)] if datadir else []
    args += ["--printer-profile", printer, "--print-profile", process]
    for f in filaments or []:
        args += ["--material-profile", f]
    if config:
        args += ["--load", str(config)]
    if not arrange:
        args += ["--dont-arrange"]
    args += ["--export-gcode", "--output", str(out_file)]
    return args + [str(m) for m in meshes]


def write_config(values, path):
    """Changed settings as an .ini PrusaSlicer --load reads ("key = value", lists comma separated)."""
    lines = []
    for k, v in sorted(values.items()):
        if isinstance(v, (list, tuple)):
            v = ",".join(str(x) for x in v)
        lines.append("%s = %s" % (k, v))
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return Path(path)


# ---------------------------------------------------------------------- the panel's PrusaSlicer
# PrusaSlicer behind the same panel as Orca Slicer and Bambu Studio: the panel asks a slicer for its printers, print
# ("process") and filament presets and their settings, and for the command line of a slice. PrusaSlicer answers all
# of it itself; its settings are read from what --save writes for the chosen presets (PrusaSlicer 3.0 cannot combine
# preset names with a settings file: a slice with changed settings loads that saved file, edited).
from . import slicer as backend            # noqa: E402  (slicer.py imports this module last)

CACHE_VERSION = 1
# the panel's printer keys PrusaSlicer has under other names (bed, height, nozzle)
ALIASES = {"bed_shape": "printable_area", "max_print_height": "printable_height"}
PREFERRED_PROCESS = ("0.20mm SPEED", "0.20mm QUALITY", "0.20mm STRUCTURAL", "0.20mm")
PREFERRED_FILAMENT = ("Prusament PLA", "Generic PLA", "PLA")


def boxes(node):
    """Every settings box in a --save answer: [dict of name -> value]. PrusaSlicer 3.0 writes
    {"preset": ..., "configuration": {"print_settings": {..}, "printer_settings": {..}, "filament_settings": {..},
    "project_settings": {..}, "toolprint_settings": {..}}} (a box of several, such as one per filament, a list of them);
    a setting is a plain value, a list, or {"value": .., "is_percent": ..} for a percentage."""
    conf = node.get("configuration", node) if isinstance(node, dict) else node
    out = []
    if isinstance(conf, dict):
        for v in conf.values():
            if isinstance(v, dict):
                out.append(v)
            elif isinstance(v, list):
                out += [x for x in v if isinstance(x, dict)]
    elif isinstance(conf, list):              # an older layout: a list of boxes, nested lists of several
        for v in conf:
            out += [v] if isinstance(v, dict) else [x for x in (v if isinstance(v, list) else []) if isinstance(x, dict)]
    return out


def plain(v):
    """A setting as the panel shows it: 15 % for {"value": 15.0, "is_percent": true}, else its value."""
    if isinstance(v, dict) and "value" in v:
        return ("%g%%" % v["value"]) if v.get("is_percent") and isinstance(v["value"], (int, float)) else v["value"]
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, list) and v and all(not isinstance(x, (list, dict)) for x in v):
        return ",".join(str(plain(x)) for x in v)     # [215] -> "215", one value per extruder
    return v


def _number(text):
    try:
        f = float(str(text).strip().rstrip("%").strip())
    except ValueError:
        return None
    return int(f) if f.is_integer() and "." not in str(text) else f


def _typed(old, v):
    """The panel's value v (mostly text) in the shape PrusaSlicer saved the setting in (old)."""
    if isinstance(old, dict) and "value" in old:
        new = dict(old)
        text = str(v).strip()
        n = _number(text)
        if n is None:
            return old
        new["value"] = float(n)
        if "is_percent" in old:
            new["is_percent"] = text.endswith("%")
        return new
    if isinstance(old, list):
        items = v if isinstance(v, list) else ([x.strip() for x in v.split(",")] if isinstance(v, str) and old and
                                               not isinstance(old[0], str) else [v])
        proto = old[0] if old else None
        items = [_typed(proto, x) if proto is not None else x for x in items]
        return items if len(items) > 1 or not old else items * len(old)
    if isinstance(old, bool):
        return str(v).strip().lower() in ("1", "true", "yes", "on") if not isinstance(v, bool) else v
    if isinstance(old, (int, float)) and not isinstance(v, (int, float)):
        n = _number(v)
        return old if n is None else (float(n) if isinstance(old, float) else int(n))
    if isinstance(old, str) and not isinstance(v, str):
        return str(v)
    return v


def settings_of(saved, location_of):
    """{kind: {setting: value}} of a --save answer, each setting under the tab PrusaSlicer shows it on (the first box
    holding a setting wins: the print before a tool, the first filament before the others)."""
    out = {"process": {}, "filament": {}, "machine": {}}
    kind_of = {"process": "process", "print": "process", "filament": "filament", "printer": "machine"}
    for box in boxes(saved):
        for k, v in box.items():
            kind = kind_of.get((location_of(k) or "").lower(), "process")
            out[kind].setdefault(k, plain(v))
    return out


def edited(saved, values):
    """The --save answer with settings changed, each in the box and the shape PrusaSlicer keeps it in, for --load.
    A setting no box holds is left out (PrusaSlicer would not take it) and noted in the log."""
    doc = json.loads(json.dumps(saved))
    found = set()
    for box in boxes(doc):
        for k in list(box):
            if k in values:
                box[k] = _typed(box[k], values[k])
                found.add(k)
    rest = sorted(k for k in values if k not in found)
    if rest:
        backend._fw_log("slicerprusa edited", "not in PrusaSlicer's settings: %s" % ", ".join(rest[:20]))
    return doc


class PrusaSlicer(backend.Slicer):
    """PrusaSlicer for the panel (presets by its own command line; no fast engine)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._q = None
        self._choice = {}
        self._saved = {}
        self.load_error = ""

    def cli_exe(self):
        """The program for command-line runs: on Windows PrusaSlicer's console build beside it (the window build
        prints nothing to a pipe), else the program itself."""
        exe = self.exe()
        if exe is None:
            return None
        for name in ("prusa-slicer-console.exe", "prusa-slicer-console"):
            p = Path(exe).with_name(name)
            if p.is_file():
                return p
        return exe

    # ------------------------------------------------------------------ presets
    def _queries(self):
        exe = self.cli_exe()
        if exe is None:
            return None
        if self._q is None or self._q.exe != exe:
            self._q = Presets(exe, self.own_data_dir())
            cache = self._cache_file()
            stamp = self._stamp(exe)
            try:
                data = json.loads(cache.read_text(encoding="utf-8"))
                if data.get("stamp") == stamp and data.get("version") == CACHE_VERSION:
                    self._q._models = data.get("models")
                    self._q._prints = {k: [tuple(r) for r in v] for k, v in (data.get("prints") or {}).items()}
            except (OSError, ValueError):
                pass
        return self._q

    def _stamp(self, exe):
        try:
            st = Path(exe).stat()
            return [str(exe), st.st_size, int(st.st_mtime), str(self.own_data_dir() or "")]
        except OSError:
            return [str(exe)]

    def _cache_file(self):
        return self.work_dir() / "presets-cache.json"

    def _save_cache(self):
        q = self._q
        if q is None or q._models is None:
            return
        try:
            self._cache_file().write_text(json.dumps({"version": CACHE_VERSION, "stamp": self._stamp(q.exe),
                                                      "models": q._models, "prints": q._prints}), encoding="utf-8")
        except OSError as error:
            backend._fw_log("slicerprusa cache", error)

    def load(self, force=False):
        with self._lock:
            if self._index is not None and not force:
                return
            index = {}
            self.load_error = ""
            q = self._queries()
            if q is not None:
                if force:
                    q._models, q._prints = None, {}
                try:
                    for name in q.printers():
                        info = q.info(name)
                        index[("machine", name)] = backend.Preset(name, "machine", None, self._machine(name, info),
                                                                  info.get("model") or "PrusaResearch")
                    self._save_cache()
                    runtime_layout(self)        # the settings list too, while the presets load (once per program)
                except Exception as error:
                    self.load_error = str(error) or error.__class__.__name__
                    backend._fw_log("slicerprusa printers", error)
            self._index = index
            self._scoped = {}
            self._resolved = {}

    def _machine(self, name, info):
        w, d, h = info.get("bed") or (0, 0, 0)
        data = {"name": name, "instantiation": "true", "printer_model": info.get("model") or "",
                "printable_area": ["0x0", "%gx0" % w, "%gx%g" % (w, d), "0x%g" % d], "printable_height": str(h),
                "extruders_count": str(info.get("extruders") or 1)}
        # the nozzle size is in the preset or variant name ("Prusa XL+ 0.4 HF", "... HF0.6", "... 0.6 nozzle");
        # PrusaSlicer 3.0's own presets for the 0.4 nozzle carry none ("Original Prusa MK4S")
        import re as _re
        m = None
        for text in (name, info.get("variant") or ""):
            m = m or _re.search(r"(?<![\d.])(0\.\d+|1\.\d+)(?:\s*mm)?(?:\s*(?:nozzle|HF))?(?![\d.])", text)
        data["nozzle_diameter"] = [m.group(1) if m else "0.4"] * int(info.get("extruders") or 1)
        return data

    def _ensure(self, printer):
        """The print and filament presets made for the printer, in the index."""
        q = self._queries()
        if q is None or not printer:
            return []
        try:
            rows = q._for(printer)
        except Exception as error:
            backend._fw_log("slicerprusa prints", error)
            return []
        self._save_cache()
        for name, fils, _tools in rows:
            self._index.setdefault(("process", name), backend.Preset(
                name, "process", None, {"name": name, "instantiation": "true", "compatible_printers": [printer]},
                "PrusaResearch"))
            for f in fils:
                self._index.setdefault(("filament", f), backend.Preset(
                    f, "filament", None, {"name": f, "instantiation": "true"}, "PrusaResearch"))
        return rows

    def printers(self):
        self.load()
        return [p for (kind, _n), p in self._index.items() if kind == "machine"]

    def processes(self, printer):
        self.load()
        return [self._index[("process", name)] for name, _f, _t in self._ensure(printer)]

    def filaments(self, printer):
        self.load()
        rows = self._ensure(printer)
        process = self._choice.get("process")
        names = []
        for name, fils, _t in rows:
            if process and name != process and any(r[0] == process for r in rows):
                continue
            for f in fils:
                if f not in names:
                    names.append(f)
        return [self._index[("filament", f)] for f in names]

    def _compatible(self, kind, name, printer):
        if kind == "machine":
            return ("machine", name) in self._index
        rows = self._ensure(printer)
        if kind == "process":
            return any(r[0] == name for r in rows)
        return any(name in r[1] for r in rows)

    def defaults(self, printer):
        rows = self._ensure(printer)
        names = [r[0] for r in rows]
        proc = next((n for want in PREFERRED_PROCESS for n in names if n.startswith(want)), names[0] if names else "")
        fils = next((r[1] for r in rows if r[0] == proc), [])
        fil = next((f for want in PREFERRED_FILAMENT for f in fils if want in f), fils[0] if fils else "")
        return {"print": proc, "filament": fil}

    def is_bambu_printer(self, printer):
        return False

    # ------------------------------------------------------------------ settings
    def set_choice(self, choice):
        """The panel's printer, print and filament presets: a preset's settings are PrusaSlicer's for that set."""
        self._choice = {k: choice.get(k) for k in ("printer", "process", "filament")}
        self._resolved = {}

    def _panel_choice(self):
        """The open PrusaSlicer panel's printer, print and filament presets (else the last set given)."""
        try:
            from . import slicerui
            panel = slicerui.SlicerPanel.current
            if panel is not None and panel.key == self.key:
                return {k: panel.choice.get(k) for k in ("printer", "process", "filament")}
        except Exception as error:
            backend._fw_log("slicerprusa choice", error)
        return dict(self._choice)

    def _location(self, key):
        from . import slicersettings
        return (slicersettings.layout("prusa")["options"].get(key) or {}).get("location", "")

    def saved(self, printer, process, filaments):
        """PrusaSlicer's --save answer for a preset set (cached), or None."""
        key = (printer, process, tuple(filaments))
        if key in self._saved:
            return self._saved[key]
        exe = self.cli_exe()
        if exe is None or not (printer and process and filaments):
            return None
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "config.json"
            args = self.datadir_args() + ["--printer-profile", printer, "--print-profile", process]
            for f in filaments:
                args += ["--material-profile", f]
            try:
                r = _run(exe, args + ["--save", str(out)])      # --save takes the file (PrusaSlicer 3.0 ReadCLI.cpp)
                doc = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else None
                if doc is None:
                    backend._fw_log("slicerprusa save", (r.stderr or r.stdout or "")[-300:])
            except Exception as error:
                backend._fw_log("slicerprusa save", error)
                doc = None
        self._saved[key] = doc
        return doc

    def resolve(self, kind, name):
        self.load()
        ctx = self._panel_choice()
        key = (kind, name, ctx.get("printer"), ctx.get("process") if kind != "process" else None,
               ctx.get("filament") if kind != "filament" else None)
        if key in self._resolved:
            return self._resolved[key]
        preset = self._index.get((kind, name))
        data = dict(preset.data) if preset is not None else {}
        c = self._panel_choice()
        c[{"machine": "printer", "process": "process", "filament": "filament"}.get(kind, kind)] = name
        if not c.get("printer") and kind != "machine":
            c["printer"] = next(iter(n for (k, n) in self._index if k == "machine"), "")
        if c.get("printer") and not (c.get("process") and c.get("filament")):
            d = self.defaults(c["printer"])
            c["process"] = c.get("process") or d["print"]
            c["filament"] = c.get("filament") or d["filament"]
        saved = self.saved(c.get("printer"), c.get("process"), [c.get("filament")] if c.get("filament") else [])
        if saved:
            values = settings_of(saved, self._location).get(kind, {})
            for k, v in values.items():
                data.setdefault(k, v if not isinstance(v, (int, float, bool)) else ("1" if v is True else "0" if v is False else str(v)))
            if kind == "filament":
                for k, alias in (("temperature", "nozzle_temperature"),):
                    if k in values and alias not in data:
                        data[alias] = str(plain(values[k]))
            if kind == "machine":
                for k, alias in ALIASES.items():
                    if k in values and alias not in ("printable_area",):
                        data[alias] = str(plain(values[k]))
        if preset is not None:
            self._resolved[key] = data
        return data

    def write_flat(self, kind, name, overrides, folder, printer="", tag=""):
        raise NotImplementedError("PrusaSlicer slices by preset name")

    def slot_files(self, slots, printer, out_dir):
        return [slot["preset"] for slot in slots[1:]]

    def slot_limit(self, printer):
        """Filament slots the printer can print with: one per extruder (Original Prusa XL 5T: 5)."""
        self.load()
        try:
            data = self.resolve("machine", printer) if printer else {}
            if not data:
                # a printer this PrusaSlicer does not list (another version names it otherwise): the colours are not
                # folded onto one extruder for want of knowing better (PC p3d_prusa: all parts on extruder 1)
                return 16
            nozzles = data.get("nozzle_diameter") or ""
            if isinstance(nozzles, list):
                nozzles = ",".join(str(n) for n in nozzles)
            count = len([n for n in str(nozzles).split(",") if n.strip()])
            return max(1, int(str(data.get("extruders_count") or 0) or 0), count)
        except Exception as error:
            backend._fw_log("slicerprusa slot_limit", error)
            return 1

    # ------------------------------------------------------------------ the slice
    def slice_args(self, mesh, printer, filament, process, overrides, out_dir, orient=False, filament_overrides=None,
                   printer_overrides=None, arrange=True, assemble=None, more_filaments=None, tower_boxes=None,
                   tower_fixed=None, output="plate_1.gcode", **_rest):
        """One plate: its meshes (in plate coordinates) to out_dir/output. With changed settings the preset set's
        saved settings, edited, are loaded instead of the preset names (PrusaSlicer takes one or the other)."""
        meshes = mesh if isinstance(mesh, (list, tuple)) else [mesh]
        fils = [filament] + [f for f in (more_filaments or []) if f]
        changed = {}
        for part in (printer_overrides, filament_overrides, overrides):
            changed.update(part or {})
        changed = {k: v for k, v in changed.items() if k in backend_options()}
        place = ["--merge"] + ([] if arrange else ["--dont-arrange"])
        if changed:
            saved = self.saved(printer, process, fils)
            if saved is None:
                raise RuntimeError("PrusaSlicer did not give the settings of the chosen presets")
            path = Path(out_dir) / "settings.json"
            path.write_text(json.dumps(edited(saved, changed), indent=1), encoding="utf-8")
            head = self.datadir_args() + ["--load", str(path)]
        else:
            head = self.datadir_args() + ["--printer-profile", printer, "--print-profile", process]
            for f in fils:
                head += ["--material-profile", f]
        return head + place + ["--export-gcode", "--output", str(Path(out_dir) / output)] + [str(m) for m in meshes]


def write_3mf(objects, path):
    """A plate's objects as one 3MF in the form PrusaSlicer reads its own 2.x project files: one object per mesh in
    plate coordinates (3D/3dmodel.model), each with the extruder that prints it in Metadata/Slic3r_PE_model.config
    (PrusaSlicer 3.0 reads that key into the object's settings). No print settings inside: the preset names or the
    --load settings given beside it decide them. objects: [{"name", "points" [(x, y, z)], "facets" [(a, b, c)],
    "extruder" (1-based)}]."""
    import zipfile
    from xml.sax.saxutils import quoteattr
    model = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"'
             ' xmlns:slic3rpe="http://schemas.slic3r.org/3mf/2017/06">',
             ' <metadata name="slic3rpe:Version3mf">1</metadata>', ' <resources>']
    config = ['<?xml version="1.0" encoding="UTF-8"?>', '<config>']
    build = []
    for i, ob in enumerate(objects, 1):
        model.append('  <object id="%d" type="model"><mesh><vertices>' % i)
        model += ['<vertex x="%.6g" y="%.6g" z="%.6g"/>' % tuple(v) for v in ob["points"]]
        model.append('</vertices><triangles>')
        model += ['<triangle v1="%d" v2="%d" v3="%d"/>' % tuple(f) for f in ob["facets"]]
        model.append('</triangles></mesh></object>')
        build.append('  <item objectid="%d" printable="1"/>' % i)
        n = len(ob["facets"])
        config += [' <object id="%d" instances_count="1">' % i,
                   '  <metadata type="object" key="name" value=%s/>' % quoteattr(str(ob.get("name") or "Object %d" % i)),
                   '  <metadata type="object" key="extruder" value="%d"/>' % int(ob.get("extruder") or 1),
                   '  <volume firstid="0" lastid="%d">' % max(0, n - 1),
                   '   <metadata type="volume" key="name" value=%s/>' % quoteattr(str(ob.get("name") or "Object %d" % i)),
                   '  </volume>', ' </object>']
    model += [' </resources>', ' <build>'] + build + [' </build>', '</model>']
    config.append('</config>')
    types = ('<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
             'content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
             'relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-'
             '3dmodel+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/'
            '2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/'
            '3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    with zipfile.ZipFile(str(path), "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", "\n".join(model) + "\n")
        z.writestr("Metadata/Slic3r_PE_model.config", "\n".join(config) + "\n")
    return Path(path)


def mesh_object(stl_path, name, extruder):
    """{"name", "points", "facets", "extruder"} of an STL file the add-on wrote (FreeCAD's Mesh reads it)."""
    import Mesh
    points, facets = Mesh.Mesh(str(stl_path)).Topology
    return {"name": name, "points": [(p.x, p.y, p.z) for p in points], "facets": [tuple(f) for f in facets],
            "extruder": extruder}


def backend_options():
    from . import slicersettings
    return slicersettings.layout("prusa")["options"]


# ---------------------------------------------------------------------- the settings window's list, from PrusaSlicer
# No settings list ships with the add-on: it is read from the user's own PrusaSlicer the first time it is needed
# (--export-config-schema: every setting with its type, choices, limits and default; --help-fff: the setting's
# description) and kept in the add-on's PrusaSlicer folder until that PrusaSlicer changes. Pages are the add-on's own.
LAYOUT_VERSION = 1
TYPES = {"Bool": "coBool", "Int": "coInt", "OptInt": "coInt", "Float": "coFloat", "String": "coString",
         "Vec2d": "coPoint", "FloatOrPercentage": "coFloatOrPercent", "Percentage": "coPercent", "Enum": "coEnum"}
TAB_OF = {"printer": "printer", "filament": "filament"}       # every other place (print, tool, object...): process
PAGES = {
    "process": (("Layers and perimeters", r"layer_height|perimeter|solid_layers|solid_min|shell|seam|top_|bottom_|"
                                          r"thin_walls|overhang|ensure_vertical|external_"),
                ("Infill", r"infill|fill_|bridge_angle|ironing"),
                ("Skirt and brim", r"skirt|brim"),
                ("Support material", r"support|raft"),
                ("Speed", r"speed|accel|jerk|pressure"),
                ("Extrusion width", r"extrusion_width|extrusion_spacing"),
                ("Multiple extruders", r"wipe_tower|ooze|extruder|wiping|interface_shells|mmu"),
                ("Output", r"output|gcode|label_objects|binary|complete_objects|extruder_clearance"),
                ("Other", r"")),
    "filament": (("Temperature", r"temperature|temp"),
                 ("Cooling", r"fan|cool|slowdown|min_print_speed"),
                 ("Retraction", r"retract|wipe|travel_ramping"),
                 ("Custom G-code", r"gcode"),
                 ("Filament", r"")),
    "printer": (("Bed and size", r"bed|print_height|z_offset|thumbnail|printable"),
                ("Machine limits", r"machine_"),
                ("Extruder", r"nozzle|extruder|retract|wipe|travel|lift|z_hop"),
                ("Custom G-code", r"gcode|template"),
                ("General", r"")),
}
WORDS = {"gcode": "G-code", "z": "Z", "xy": "XY", "mmu": "MMU", "id": "ID", "rpm": "RPM", "pa": "PA"}


def label_of(key):
    """layer_height -> "Layer height" (the add-on's own label: PrusaSlicer's labels are not in its command line)."""
    words = [WORDS.get(w, w) for w in key.split("_") if w]
    if not words:
        return key
    first = words[0] if words[0] in WORDS.values() else words[0].capitalize()
    return " ".join([first] + words[1:])


def help_text(text):
    """{setting: description} from PrusaSlicer's --help-fff (an option line "--layer-height FLOAT  Description...",
    wrapped onto lines further in)."""
    import re
    out, key = {}, None
    for line in text.splitlines():
        m = re.match(r"^\s{0,8}--([a-z0-9][a-z0-9-]*)(?:\s+(?:\S+))?(?:\s{2,}(.*))?$", line)
        if m:
            key = m.group(1).replace("-", "_")
            out[key] = (m.group(2) or "").strip()
        elif key and line.startswith(" " * 9) and line.strip() and not line.strip().startswith("-"):
            out[key] = (out[key] + " " + line.strip()).strip()
        elif not line.strip():
            key = None
    for k, v in out.items():
        out[k] = re.sub(r"\s*\(default: [^)]*\)\s*$", "", v)
    return out


def _value_text(v):
    if isinstance(v, list) and v and all(isinstance(x, (list, tuple)) and len(x) == 2 for x in v):
        return ",".join("%gx%g" % tuple(x) for x in v)
    if isinstance(v, dict) and "x" in v and "y" in v:
        return "%gx%g" % (v["x"], v["y"])
    v = plain(v)
    if isinstance(v, list):
        return ",".join(str(plain(x)) for x in v)
    return "" if v is None else v


def build_layout(schema, helps):
    """The settings window's {"pages", "options"} from --export-config-schema and --help-fff answers."""
    import re
    shown = set(helps) if len(helps) >= 50 else None        # what the command line hides is PrusaSlicer-internal
    options = {}
    for box_name, box in schema.items():
        if box_name.startswith("sla") or not isinstance(box, dict):
            continue
        for item in box.get("items") or []:
            key = item.get("name")
            if not key or key in options or (shown is not None and key not in shown):
                continue
            t = TYPES.get(item.get("element_type") if item.get("type") == "Array" else item.get("type"), "coString")
            if item.get("type") == "Array":
                t += "s"
            d = {"type": t, "label": label_of(key), "tooltip": helps.get(key, ""), "mode": "simple",
                 "location": str(item.get("location") or box_name).replace("tool_print", "Tool").capitalize(),
                 "default": _value_text(item.get("value"))}
            if item.get("enum_values"):
                d["enum_values"] = list(item["enum_values"])
                d["enum_labels"] = [label_of(str(v)) for v in item["enum_values"]]
            for lim in ("min", "max"):
                if lim in item:
                    d[lim] = item[lim]
            options[key] = d
    pages = {}
    for tab, rules in PAGES.items():
        keys = [k for k, d in options.items() if TAB_OF.get(d["location"].lower(), "process") == tab]
        taken = set()
        out = []
        for title, rule in rules:
            mine = [k for k in keys if k not in taken and (not rule or re.search(rule, k))]
            taken.update(mine)
            if mine:
                out.append({"title": title, "groups": [{"title": title, "options": mine}]})
        pages[tab] = out
    return {"source": "prusa-runtime", "version": LAYOUT_VERSION, "pages": pages, "options": options}


def read_layout(exe, datadir=None):
    """Ask this PrusaSlicer for its settings (two quick runs that open no window)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "schema.json"
        extra = ["--datadir", str(datadir)] if datadir else []
        r = _run(exe, extra + ["--export-config-schema", str(out)])
        if not out.is_file():
            raise RuntimeError((r.stderr or r.stdout or "PrusaSlicer wrote no settings list").strip()[-400:])
        schema = json.loads(out.read_text(encoding="utf-8"))
    helps = help_text(_run(exe, extra + ["--help-fff"]).stdout or "")
    return build_layout(schema, helps)


def runtime_layout(slicer_obj=None):
    """The settings list of the user's PrusaSlicer (cached in the add-on's PrusaSlicer folder per program), or
    {"pages": {}, "options": {}} when there is no PrusaSlicer yet."""
    s = slicer_obj or backend.get("prusa")
    exe = s.cli_exe() if s is not None else None
    if exe is None:
        return {"pages": {}, "options": {}}
    stamp = s._stamp(exe)
    cache = s.work_dir() / "settings-layout.json"
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("stamp") == stamp and data.get("version") == LAYOUT_VERSION and data.get("options"):
            return data
    except (OSError, ValueError):
        pass
    try:
        data = read_layout(exe, s.own_data_dir())
    except Exception as error:
        backend._fw_log("slicerprusa settings list", error)
        return {"pages": {}, "options": {}}
    data["stamp"] = stamp
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data), encoding="utf-8")
    except OSError as error:
        backend._fw_log("slicerprusa settings cache", error)
    return data
