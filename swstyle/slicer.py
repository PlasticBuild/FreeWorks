# SPDX-License-Identifier: LGPL-2.1-or-later
"""3D Slicer back end: Orca Slicer and Bambu Studio driven from FreeCAD.

Both slicers are open source (AGPL-3.0) and share one engine and one preset
format (Bambu Studio is the parent, Orca Slicer a fork), so one class drives
either. Nothing here copies their code: it reads their preset JSON files,
writes the same kind of files, and runs their own programs.

- Presets: the slicer's system presets (resources/profiles/<vendor> in its
  install folder, or the copy it keeps in its data folder under system/) and
  the user's own presets (data folder, user/<id>/). A preset names its parent
  with "inherits"; resolve() merges the chain.
- Slice: the slicer's command line. The part is written as a STEP file. The
  command line reads STL/OBJ/3MF but not STEP, so the STEP file is meshed in
  FreeCAD with the deflections the slicer itself uses when it opens a STEP file (its linear_defletion / angle_defletion settings, OCCT's
  BRepMesh like FreeCAD's MeshPart), then sliced with the chosen printer,
  filament and process (each preset written out whole, with its "inherits"
  chain merged, the process with the panel's changes on top).
The slicer's own window is never started: everything happens in FreeCAD.
"""

_FW_SEEN = set()


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return

import glob
import json
import math
import os
import re
import shutil
import sys
import threading
from pathlib import Path

import FreeCAD as App

from . import paths

PARAM = paths.PARAM_PATH + "/Slicer"

# Process settings the panel shows. key -> (label, kind, extra); kinds: float (mm), int, percent,
# bool, enum (extra = ((value, label), ...)). Values and labels as both slicers name them.
INFILL_PATTERNS = (
    ("crosshatch", "Cross Hatch"), ("gyroid", "Gyroid"), ("grid", "Grid"), ("zig-zag", "Rectilinear"),
    ("alignedrectilinear", "Aligned Rectilinear"), ("line", "Line"), ("cubic", "Cubic"),
    ("triangles", "Triangles"), ("tri-hexagon", "Tri-hexagon"), ("honeycomb", "Honeycomb"),
    ("adaptivecubic", "Adaptive Cubic"), ("3dhoneycomb", "3D Honeycomb"), ("lightning", "Lightning"),
    ("concentric", "Concentric"), ("hilbertcurve", "Hilbert Curve"),
    ("archimedeanchords", "Archimedean Chords"), ("octagramspiral", "Octagram Spiral"),
)
SUPPORT_TYPES = (("normal(auto)", "Normal (auto)"), ("tree(auto)", "Tree (auto)"),
                 ("normal(manual)", "Normal (manual)"), ("tree(manual)", "Tree (manual)"))
BRIM_TYPES = (("auto_brim", "Auto"), ("no_brim", "No brim"), ("outer_only", "Outer brim only"),
              ("inner_only", "Inner brim only"), ("outer_and_inner", "Outer and inner brim"),
              ("brim_ears", "Mouse ear"), ("painted", "Painted"))
SEAMS = (("aligned", "Aligned"), ("nearest", "Nearest"), ("back", "Back"), ("random", "Random"))
PLATES = (("Cool Plate", "Cool Plate"), ("Engineering Plate", "Engineering Plate"),
          ("High Temp Plate", "Smooth PEI Plate / High Temp Plate"),
          ("Textured PEI Plate", "Textured PEI Plate"), ("Supertack Plate", "Cool Plate (SuperTack)"))

QUALITY = (
    ("layer_height", "Layer height", "float"),
    ("initial_layer_print_height", "First layer height", "float"),
    ("seam_position", "Seam position", "enum", SEAMS),
)
STRENGTH = (
    ("wall_loops", "Wall loops", "int"),
    ("top_shell_layers", "Top shell layers", "int"),
    ("bottom_shell_layers", "Bottom shell layers", "int"),
    ("sparse_infill_density", "Sparse infill density", "percent"),
    ("sparse_infill_pattern", "Sparse infill pattern", "enum", INFILL_PATTERNS),
)
SUPPORT = (
    ("enable_support", "Enable support", "bool"),
    ("support_type", "Type", "enum", SUPPORT_TYPES),
    ("support_threshold_angle", "Threshold angle", "int"),
)
ADHESION = (
    ("brim_type", "Brim type", "enum", BRIM_TYPES),
)
GROUPS = (("Quality", QUALITY), ("Strength", STRENGTH), ("Support", SUPPORT), ("Adhesion", ADHESION))
SETTING_KEYS = tuple(row[0] for _, rows in GROUPS for row in rows)

# Typical densities (g/cm3) when a filament preset gives none.
DENSITY = {"PLA": 1.24, "PETG": 1.27, "ABS": 1.04, "ASA": 1.07, "TPU": 1.21, "PA": 1.14, "PC": 1.2}


def params():
    return App.ParamGet(PARAM)


def _first(value):
    if isinstance(value, list):
        return value[0] if value else ""
    return value


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


CACHE_VERSION = 2          # 2: Orca 2.5 packed vendor profiles (<Vendor>.opc, slicer_opc)


class Preset:
    __slots__ = ("name", "kind", "path", "data", "vendor", "user")

    def __init__(self, name, kind, path, data, vendor, user=False):
        self.name, self.kind, self.path, self.data, self.vendor, self.user = name, kind, path, data, vendor, user

    def __repr__(self):
        return "<Preset %s %s>" % (self.kind, self.name)


_OWN = {}


class Slicer:
    """One slicer program: where it is, its presets, its command line."""

    def __init__(self, key, title, exe_names, folder_names, data_name, icon_names):
        self.key = key                    # "orca" | "bambu"
        self.title = title                # "Orca Slicer" | "Bambu Studio"
        self.exe_names = exe_names
        self.folder_names = folder_names  # install folder names under Program Files
        self.data_name = data_name        # folder in %APPDATA% / ~/.config, and the .conf name
        self.icon_names = icon_names
        self.second_args = ()             # extra words for a second start that hands files to the open window
        self._index = None                # name -> Preset, for every kind
        self._lists = None
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ where things are
    def exe(self):
        ""



        if os.environ.get("SWSTYLE_NO_SLICER") == "1":
            return None
        found = [p for p in (self.own_exe(), self.env_exe()) if p is not None]
        for path in found:
            if path.is_file():
                return path
        return None

    def env_exe(self):
        env = os.environ.get("SWSTYLE_%s_EXE" % self.key.upper(), "")
        return Path(env) if env else None

    def own_exe(self):
        ""

        saved = params().GetString(self.key + "Exe", "")
        if saved and Path(saved).is_file():
            return Path(saved)
        root = Path(App.getUserAppDataDir()) / "SolidWorksStyle" / "slicer-apps" / self.key
        if not root.is_dir():
            return None             # nothing downloaded for this slicer yet: the usual state, not an error
        try:
            stamp = root.stat().st_mtime_ns
        except OSError as _fw_err:
            _fw_log("slicer.py:176", _fw_err)
            return None
        hit = _OWN.get(self.key)
        if hit and hit[0] == stamp and (hit[1] is None or hit[1].is_file()):
            return hit[1]
        names = {n.lower() + ".exe" for n in self.exe_names} | {n.lower() for n in self.exe_names}
        best = None
        for folder in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True):
            hits = [p for p in folder.rglob("*") if p.is_file() and p.name.lower() in names]
            if hits:
                hits.sort(key=lambda p: len(p.parts))
                best = hits[0]
                break
        _OWN[self.key] = (stamp, best)
        return best

    def installed_exes(self):
        """Copies installed on this computer (Program Files and the like). Only looked for (handoff108: never
        started); the add-on slices with its own downloaded copy."""
        found = []
        if sys.platform == "win32":
            roots = [os.environ.get(v, "") for v in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)")]
            local = os.environ.get("LOCALAPPDATA", "")
            if local:
                roots.append(os.path.join(local, "Programs"))
            for root in filter(None, roots):
                for folder in self.folder_names:
                    for name in self.exe_names:
                        found.append(Path(root) / folder / (name + ".exe"))
        else:
            for name in self.exe_names:
                hit = shutil.which(name)
                if hit:
                    found.append(Path(hit))
        return found

    def exe_source(self):
        ""
        exe = self.exe()
        if exe is None:
            return None
        own, env = self.own_exe(), self.env_exe()
        if own is not None and own == exe:
            return "freeworks"
        if env is not None and env == exe:
            return "env"
        return "installed"

    def fallback_note(self):
        ""
        if self.exe_source() != "installed":
            return ""
        return ("FreeCAD has no copy of %s of its own yet, so the one installed on this computer is used. "
                "Slicer Updates downloads a copy for FreeCAD." % self.title)

    def installed(self):
        return self.exe() is not None

    def resources(self):
        """resources/ of the install (Windows: beside the exe; AppImage: beside AppRun or bin/)."""
        exe = self.exe()
        if exe is None:
            return None
        for folder in (exe.parent / "resources", exe.parent.parent / "resources"):
            if (folder / "profiles").is_dir():
                return folder
        return None

    def own_data_dir(self):
        """A settings folder of the program's own, or None (the slicer's usual folder). SWSTYLE_<KEY>_DATADIR names
        one; else the add-on's own downloaded copy has one under the add-on's user data (slicer-data/<key>), unless
        the person chose "Use my installed slicer's settings" (<key>SharedSettings). Every start of the program gets
        --datadir there and the add-on reads the presets from there too, so the add-on's copy never reads or writes
        the settings, presets or sign-in of a copy installed on this computer."""
        env = os.environ.get("SWSTYLE_%s_DATADIR" % self.key.upper(), "")
        if env:
            return Path(env)
        if params().GetBool(self.key + "SharedSettings", False):
            return None
        own = self.own_exe()
        exe = self.exe() if own is not None else None
        if own is not None and exe is not None and Path(exe) == Path(own):
            return Path(App.getUserAppDataDir()) / "SolidWorksStyle" / "slicer-data" / self.key
        return None

    def set_shared_settings(self, on):
        """The add-on's own copy uses the installed slicer's settings folder (on) or a folder of its own (off)."""
        params().SetBool(self.key + "SharedSettings", bool(on))
        with self._lock:
            self._index = None              # the presets come from the other folder now
            self._lists = None

    def datadir_args(self):
        """["--datadir", folder] for a start of the program (the slicers' own option), or [] (their usual folder)."""
        own = self.own_data_dir()
        if own is None:
            return []
        try:
            own.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            _fw_log("slicer.py:datadir", error)
        return ["--datadir", str(own)]

    def data_dir(self):
        own = self.own_data_dir()
        if own is not None:
            return own
        saved = params().GetString(self.key + "DataDir", "")
        if saved:
            return Path(saved)
        if sys.platform == "win32":
            return Path(os.environ.get("APPDATA", str(Path.home()))) / self.data_name
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / self.data_name
        return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / self.data_name

    def conf_path(self):
        return self.data_dir() / (self.data_name + ".conf")

    def icon_path(self):
        res = self.resources()
        if res is None:
            return ""
        for name in self.icon_names:
            path = res / "images" / name
            if path.is_file():
                return str(path)
        return ""

    def work_dir(self):
        path = Path(App.getUserAppDataDir()) / "SolidWorksStyle" / "slicer" / self.key
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ------------------------------------------------------------------ settings file (.conf)
    def read_conf(self):
        """(data, checksum line or None, newline) of the slicer's settings file."""
        path = self.conf_path()
        try:
            raw = path.read_bytes().decode("utf-8")
        except Exception:
            return {}, None, "\n"
        newline = "\r\n" if "\r\n" in raw else "\n"
        checksum = None
        body = raw
        m = re.search(r"(?m)^# MD5 checksum ([0-9A-Fa-f]+)\s*$", raw)
        if m:
            checksum = m.group(1)
            body = raw[:m.start()]
        try:
            return json.loads(body), checksum, newline
        except Exception:
            return {}, checksum, newline

    def current_presets(self):
        """The printer, filament and process the slicer had last (its settings file)."""
        data = self.read_conf()[0]
        presets = data.get("presets") or {}
        filaments = presets.get("filaments") or []
        if isinstance(filaments, str):
            filaments = [filaments]
        return {"machine": presets.get("machine") or "", "filament": filaments[0] if filaments else "",
                "print": presets.get("print") or ""}

    # ------------------------------------------------------------------ first run (the slicers' setup wizard, in short)
    def first_run(self):
        """True when the slicer has no printer set up yet: its settings file names no printer model (a new copy whose
        Configuration Wizard never ran). The 3D Slicer panel then offers its own short setup."""
        data = self.read_conf()[0]
        return not (data.get("models") and (data.get("presets") or {}).get("machine"))

    def vendors(self):
        """[(vendor folder, vendor name)] of the slicer's own bundled printer profiles that have printers."""
        out = []
        res = self.resources()
        if res is None:
            return out
        for index in sorted((res / "profiles").glob("*.json")):
            try:
                data = json.loads(index.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("machine_model_list") and (res / "profiles" / index.stem).is_dir():
                out.append((index.stem, str(data.get("name") or index.stem)))
        have = {v for v, _n in out}
        for cache in sorted((res / "profiles").glob("*.opc")):
            # Orca Slicer 2.5: the vendor's index and presets are packed in <Vendor>.opc (no <Vendor>.json)
            if cache.stem in have:
                continue
            try:
                from . import slicer_opc
                data = slicer_opc.vendor_index(cache)
            except Exception as _fw_err:
                _fw_log("slicer.py:vendors opc", _fw_err)
                continue
            if data.get("machine_model_list"):
                out.append((cache.stem, str(data.get("name") or cache.stem)))
        return sorted(out, key=lambda v: (v[0] != "BBL", v[1].lower()))

    def vendor_printers(self, vendor):
        """The bundled printers (with their nozzle) of one vendor, as the setup lists them."""
        return [p for p in self.printers() if not p.user and p.vendor == vendor]

    def set_up_printer(self, printer):
        """The slicers' Configuration Wizard for one printer, through the slicer's own files: the vendor's bundled
        profiles copied into its data folder's system/ (as the wizard installs them), the printer model added to its
        settings file's "models", and the printer, its default filament and process made the current presets.
        Returns {"machine", "filament", "print"}."""
        import hashlib
        data = self.resolve("machine", printer)
        preset = self.preset("machine", printer)
        if not data or preset is None:
            raise ValueError("%s has no printer named %s" % (self.title, printer))
        vendor, model = preset.vendor, data.get("printer_model") or printer
        nozzle = _first(data.get("nozzle_diameter") or ["0.4"]) or "0.4"
        root = self.data_dir()
        res = self.resources()
        system = root / "system"
        system.mkdir(parents=True, exist_ok=True)
        if res is not None and not (system / vendor).is_dir():
            if (res / "profiles" / vendor).is_dir():
                shutil.copytree(str(res / "profiles" / vendor), str(system / vendor))
            else:
                (system / vendor).mkdir(parents=True, exist_ok=True)
            for name in (vendor + ".json", vendor + ".opc"):     # Orca 2.5 installs the vendor's cache
                if (res / "profiles" / name).is_file():
                    shutil.copy2(str(res / "profiles" / name), str(system / name))
        conf, _sum, newline = self.read_conf()
        models = [m for m in conf.get("models") or [] if isinstance(m, dict)]
        if not any(m.get("model") == model and str(m.get("nozzle_diameter")) == str(nozzle) for m in models):
            models.append({"model": model, "nozzle_diameter": str(nozzle), "vendor": vendor})
        conf["models"] = models
        d = self.defaults(printer)
        presets = dict(conf.get("presets") or {})
        presets["machine"] = printer
        if d["filament"]:
            presets["filaments"] = [d["filament"]]
        if d["print"]:
            presets["process"] = d["print"]
        conf["presets"] = presets
        if d["filament"]:
            fils = list(conf.get("filaments") or [])
            if d["filament"] not in fils:
                conf["filaments"] = fils + [d["filament"]]
        # written as the slicers write it: the JSON, then the MD5 checksum line of that text
        # Orca Slicer indents with tabs, Bambu Studio with four spaces: as the file already is, else as the slicer does
        try:
            old = self.conf_path().read_text(encoding="utf-8")
        except OSError:
            old = ""
        indent = "\t" if ("\n\t" in old or (not old and self.key == "orca")) else 4
        body = json.dumps(conf, indent=indent, ensure_ascii=False) + "\n"
        body = body.replace("\n", newline)
        if _sum is not None or sys.platform == "win32":
            # the slicers check it on Windows (a file that fails it is taken as damaged)
            body += "# MD5 checksum %s%s" % (hashlib.md5(body.encode("utf-8")).hexdigest().upper(), newline)
        root.mkdir(parents=True, exist_ok=True)
        tmp = self.conf_path().with_suffix(".conf.swstyle-tmp")
        tmp.write_bytes(body.encode("utf-8"))
        os.replace(str(tmp), str(self.conf_path()))
        with self._lock:
            self._index = None              # the system copy is new: read the presets again
            self._lists = None
        return {"machine": printer, "filament": d["filament"], "print": d["print"]}

    def mesh_deflection(self):
        app = self.read_conf()[0].get("app") or {}
        try:
            linear = float(app.get("linear_defletion", "0.003"))
            angular = float(app.get("angle_defletion", "0.5"))
        except ValueError:
            linear, angular = 0.003, 0.5
        return linear, angular

    # ------------------------------------------------------------------ presets
    def _vendor_dirs(self):
        """[(vendor, folder)]: the data folder's system copy wins over the install's."""
        dirs = {}
        res = self.resources()
        if res is not None:
            for folder in sorted((res / "profiles").iterdir()):
                if folder.is_dir():
                    dirs[folder.name] = folder
        system = self.data_dir() / "system"
        if system.is_dir():
            for folder in sorted(system.iterdir()):
                if folder.is_dir() and ((folder / "machine").is_dir() or (folder / "filament").is_dir()):
                    dirs[folder.name] = folder
        return sorted(dirs.items())

    def _vendor_caches(self):
        """[(vendor, <Vendor>.opc)]: Orca Slicer 2.5's packed vendor profiles; the data folder's system copy wins."""
        caches = {}
        res = self.resources()
        for folder in ([res / "profiles"] if res is not None else []) + [self.data_dir() / "system"]:
            if folder.is_dir():
                for cache in sorted(folder.glob("*.opc")):
                    caches[cache.stem] = cache
        return sorted(caches.items())

    def _user_dirs(self):
        user = self.data_dir() / "user"
        if not user.is_dir():
            return []
        return [folder for folder in sorted(user.iterdir()) if folder.is_dir()]

    def load(self, force=False):
        """Every preset, once. A few thousand small JSON files: under a second when Windows has
        them cached, but 25 s on a cold first read (seen on Ati's PC for Bambu Studio), so the
        system presets come from one cache file while the slicer's version and vendor files are
        unchanged; user presets are always read fresh (a handful)."""
        with self._lock:
            if self._index is not None and not force:
                return
            vendor_dirs = self._vendor_dirs()
            system = self._load_cached(vendor_dirs) if not force else None
            if system is None:
                system = []
                found = set()
                for vendor, folder in vendor_dirs:
                    for kind in ("machine", "filament", "process"):
                        for path in glob.glob(str(folder / kind / "**" / "*.json"), recursive=True):
                            data = _read_json(path)
                            if isinstance(data, dict) and "name" in data:
                                system.append((vendor, kind, path, data))
                                found.add(vendor)
                # Orca Slicer 2.5: vendors whose presets ship only packed in <Vendor>.opc
                for vendor, cache in self._vendor_caches():
                    if vendor in found:
                        continue
                    try:
                        from . import slicer_opc
                        for kind, sub, data in slicer_opc.profiles(cache):
                            system.append((vendor, kind, "%s|%s" % (cache, sub), data))
                    except Exception as _fw_err:
                        _fw_log("slicer.py:load opc", _fw_err)
                self._save_cached(vendor_dirs, system)
            index, scoped = {}, {}
            for vendor, kind, path, data in system:
                preset = Preset(data["name"], kind, path, data, vendor)
                scoped[(vendor, kind, data["name"])] = preset
                # the same base names (fdm_process_common...) are in every vendor: only
                # presets one can pick go in the shared index
                if self._selectable(preset) or (kind, data["name"]) not in index:
                    index[(kind, data["name"])] = preset
            for folder in self._user_dirs():
                for kind in ("machine", "filament", "process"):
                    for path in glob.glob(str(folder / kind / "*.json")):
                        data = _read_json(path)
                        if not isinstance(data, dict) or "name" not in data:
                            continue
                        index[(kind, data["name"])] = Preset(data["name"], kind, path, data, "User", True)
            self._index = index
            self._scoped = scoped
            self._resolved = {}

    def loaded(self):
        return self._index is not None

    def _cache_path(self):
        return Path(App.getUserAppDataDir()) / "SolidWorksStyle" / "slicer" / ("%s-presets.pickle" % self.key)

    def _signature(self, vendor_dirs):
        """What the system presets depend on: the program and each vendor's index file
        (<vendor>.json beside its folder, rewritten on every profile update)."""
        sig = [CACHE_VERSION, str(self.exe())]
        try:
            st = os.stat(str(self.exe()))
            sig.append((st.st_size, int(st.st_mtime)))
        except (OSError, TypeError) as _fw_err:
            _fw_log("slicer.py:381", _fw_err)
        for vendor, cache in self._vendor_caches():
            try:
                st = os.stat(str(cache))
                sig.append([vendor, str(cache), (st.st_size, int(st.st_mtime))])
            except OSError:
                sig.append([vendor, str(cache), None])
        for vendor, folder in vendor_dirs:
            entry = [vendor, str(folder)]
            for f in (folder.parent / (vendor + ".json"), folder):
                try:
                    st = os.stat(str(f))
                    entry.append((st.st_size, int(st.st_mtime)))
                except OSError:
                    entry.append(None)
            sig.append(entry)
        return sig

    def _load_cached(self, vendor_dirs):
        import pickle
        try:
            with open(str(self._cache_path()), "rb") as f:
                stored = pickle.load(f)
            if stored.get("signature") == self._signature(vendor_dirs):
                return stored["presets"]
        except Exception as _fw_err:
            _fw_log("slicer.py:401", _fw_err)
        return None

    def _save_cached(self, vendor_dirs, presets):
        import pickle
        path = self._cache_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            with open(str(tmp), "wb") as f:
                pickle.dump({"signature": self._signature(vendor_dirs), "presets": presets}, f,
                            protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(str(tmp), str(path))
        except Exception as _fw_err:
            _fw_log("slicer.py:415", _fw_err)

    def preset(self, kind, name):
        self.load()
        return self._index.get((kind, name))

    def resolve(self, kind, name):
        """The preset's settings with its "inherits" chain merged in."""
        self.load()
        key = (kind, name)
        if key in self._resolved:
            return self._resolved[key]
        chain, seen = [], set()
        preset = self._index.get(key)
        while preset is not None and preset.name not in seen:
            seen.add(preset.name)
            chain.append(preset.data)
            parent = preset.data.get("inherits") or ""
            if not parent:
                break
            # the parent from the same vendor first (a user preset's parent is a system one)
            preset = self._scoped.get((preset.vendor, kind, parent)) or self._index.get((kind, parent))
        merged = {}
        for data in reversed(chain):
            # Orca 2.5 "include": templates layered under the preset's own settings, in order
            for inc in data.get("include") or []:
                own = self._index.get(key)
                part = self._scoped.get((own.vendor if own else "", kind, inc)) or self._index.get((kind, inc))
                if part is not None and inc != key[1]:
                    merged.update({k: v for k, v in self.resolve(kind, inc).items()
                                   if k not in ("name", "inherits", "instantiation", "include")})
            merged.update(data)
        merged.pop("include", None)
        self._resolved[key] = merged
        return merged

    def _selectable(self, preset):
        if preset.user:
            return True
        return str(preset.data.get("instantiation", "false")).lower() == "true"

    def printers(self):
        self.load()
        rows = [p for (kind, _), p in self._index.items() if kind == "machine" and self._selectable(p)]
        return sorted(rows, key=lambda p: (not p.user, p.vendor != "BBL", p.vendor.lower(), p.name.lower()))

    def _compatible(self, kind, name, printer):
        if self._index.get((kind, name)) is None:
            return False
        data = self.resolve(kind, name)
        listed = data.get("compatible_printers")
        if isinstance(listed, list) and listed:
            return printer in listed or self._printer_parent(printer) in listed
        return True

    def _printer_parent(self, printer):
        preset = self._index.get(("machine", printer))
        if preset is not None and preset.user:
            return preset.data.get("inherits") or ""
        return printer

    def filaments(self, printer):
        self.load()
        rows = [p for (kind, name), p in self._index.items()
                if kind == "filament" and self._selectable(p) and self._compatible(kind, name, printer)]
        return sorted(rows, key=lambda p: (not p.user, p.name.lower()))

    def processes(self, printer):
        self.load()
        rows = [p for (kind, name), p in self._index.items()
                if kind == "process" and self._selectable(p) and self._compatible(kind, name, printer)]
        return sorted(rows, key=lambda p: (not p.user, _layer(p.name), p.name.lower()))

    def defaults(self, printer):
        data = self.resolve("machine", printer)
        fil = (data.get("default_filament_profile") or [""])
        return {"print": data.get("default_print_profile") or "", "filament": _first(fil)}

    def is_bambu_printer(self, printer):
        data = self.resolve("machine", printer)
        return "Bambu Lab" in (data.get("printer_model") or "") or self.preset("machine", printer) is not None \
            and self.preset("machine", printer).vendor == "BBL"

    # ------------------------------------------------------------------ the part
    def write_flat(self, kind, name, overrides, folder, printer="", tag=""):
        """The preset with its whole "inherits" chain merged, as one file: the command line does
        not follow "inherits" at all (a 0.16 mm process printed 0.2 mm layers, a PLA preset gave
        density 0, an X1 Carbon lost its auxiliary fan)."""
        data = dict(self.resolve(kind, name))
        if not data:
            raise ValueError("unknown %s preset %s" % (kind, name))
        for key, value in overrides.items():
            old = data.get(key)
            # a list setting (one value per extruder / filament) stays a list
            if isinstance(old, list) and not isinstance(value, list):
                value = [value] * max(1, len(old))
            data[key] = value
        data["inherits"] = ""
        # Orca Slicer 2.5's command line refuses a file with no "type" ("Preset type could not be resolved"); a merged
        # chain whose files never said it (user presets, the packed caches) has none
        data["type"] = kind
        if kind == "filament" and not data.get("filament_colour"):
            # the merged presets carry no filament colour; with two filaments or more the command line then sizes its
            # filament grouping by one colour and fails ("Grouping error: PLA can not be placed in the right nozzle")
            data["filament_colour"] = list(data.get("default_filament_colour") or ["#FFFFFF"])[:1]
        # a merged printer marked "User" fails the command line's printer check; "system" passes
        data["from"] = "system" if kind == "machine" else "User"
        if kind != "machine":
            # the panel lists only presets made for the printer; the command line wants the printer
            # named here (an empty list counts as "not compatible with the process preset")
            data["compatible_printers"] = [printer]
            data["compatible_printers_condition"] = ""
        if overrides and kind != "machine":
            # (a renamed printer no longer matches the process's compatible printer)
            data["name"] = name + " (FreeCAD)"
        # the merged base presets leave these empty; the command line matches printers by them
        data[{"machine": "printer_settings_id", "filament": "filament_settings_id",
              "process": "print_settings_id"}[kind]] = data["name"]
        path = Path(folder) / ("%s%s.json" % (kind, tag))
        path.write_text(json.dumps(data, indent=4), encoding="utf-8")
        return path

    def slot_files(self, slots, printer, out_dir):
        """The filament files of slots 2, 3, ... ([{"preset", "colour"}] as the panel lists them), each with its colour."""
        files = []
        for i, slot in enumerate(slots[1:], 2):
            over = {"default_filament_colour": [slot["colour"]], "filament_colour": [slot["colour"]]} if slot.get("colour") else {}
            files.append(self.write_flat("filament", slot["preset"], over, out_dir, printer, tag="_%d" % i))
        return files

    def slice_args(self, mesh, printer, filament, process, overrides, out_dir, orient=False,
                   filament_overrides=None, printer_overrides=None, arrange=True, assemble=None,
                   project=None, slice_plates=True, more_filaments=None, tower_boxes=None, tower_fixed=None):
        """Command line for one slice: G-code and a .gcode.3mf in out_dir, result.json beside them."""
        machine = self.write_flat("machine", printer, printer_overrides or {}, out_dir)
        fil = self.write_flat("filament", filament, filament_overrides or {}, out_dir, printer)
        if more_filaments and (assemble is not None or tower_boxes) and "wipe_tower_x" not in (overrides or {}):
            # the prime tower of a plate with several filaments: the command line puts it where the slicer's own plate
            # would (its default spot), which can be off a smaller bed or on the objects, and then refuses the G-code
            # ("G-code in unprintable area"); place it, as the slicer does, in a free corner of each plate
            spots = prime_tower_spots(assemble, self.resolve("machine", printer), self.resolve("process", process),
                                      overrides, boxes=tower_boxes)
            for i, xy in (tower_fixed or {}).items():
                if 0 <= i < len(spots):
                    spots[i] = tuple(xy)      # a tower dragged on the plate stays where it was put
            if spots:
                overrides = dict(overrides or {})
                overrides["wipe_tower_x"] = ["%g" % x for x, _y in spots]
                overrides["wipe_tower_y"] = ["%g" % y for _x, y in spots]
        proc = self.write_flat("process", process, overrides, out_dir, printer)
        fil_list = ";".join([str(fil)] + [str(f) for f in (more_filaments or [])])
        meshes = [str(m) for m in mesh] if isinstance(mesh, (list, tuple)) else [str(mesh)]
        name = Path(meshes[0]).stem
        if len(meshes) > 1:
            name = re.sub(r"_\d\d$", "", name)
        if assemble is not None:
            # the plates as the slicer's plate list (load_assemble_list): each object where it
            # stands on its plate; the slicer writes its own project 3MF
            args = self.datadir_args() + [
                "--load-settings", "%s;%s" % (machine, proc), "--load-filaments", fil_list,
                "--load-assemble-list", str(assemble), "--outputdir", str(out_dir)]
            if slice_plates:
                args += ["--slice", "0"]
            args += ["--export-3mf", project or (Path(assemble).stem + ".gcode.3mf")]
            return args
        return self.datadir_args() + [
            "--load-settings", "%s;%s" % (machine, proc),
            "--load-filaments", fil_list,
            "--arrange", "1" if arrange else "0",
            "--orient", "1" if orient else "0",
            "--slice", "0",
            "--outputdir", str(out_dir),
            "--export-3mf", name + ".gcode.3mf",
        ] + meshes


def _layer(name):
    m = re.match(r"\s*([0-9.]+)\s*mm", name)
    return float(m.group(1)) if m else 99.0


SLICERS = {
    "orca": Slicer("orca", "Orca Slicer", ("orca-slicer", "OrcaSlicer"), ("OrcaSlicer", "Orca Slicer"),
                   "OrcaSlicer", ("OrcaSlicer_192px_transparent.png", "OrcaSlicer_128px.png", "OrcaSlicer.png")),
    "bambu": Slicer("bambu", "Bambu Studio", ("bambu-studio", "BambuStudio"), ("Bambu Studio", "BambuStudio"),
                    "BambuStudio", ("BambuStudio_192px_transparent.png", "BambuStudio_128px.png", "BambuStudio.png")),
    # PrusaSlicer: opened in its own tab (Slicer (full)) and kept up to date by Slicer Updates; Quick Slice is Orca's and

    "prusa": Slicer("prusa", "PrusaSlicer", ("prusa-slicer", "PrusaSlicer"), ("PrusaSlicer", "Prusa3D\\PrusaSlicer"),
                    "PrusaSlicer", ()),
}


# PrusaSlicer answers the panel from its own command line (its presets, their settings, the slice): slicerprusa
from . import slicerprusa as _prusa     # noqa: E402  (it builds on Slicer above)
SLICERS["prusa"] = _prusa.PrusaSlicer("prusa", "PrusaSlicer", ("prusa-slicer", "PrusaSlicer"),
                                      ("PrusaSlicer", "Prusa3D\\PrusaSlicer"), "PrusaSlicer", ())
# PrusaSlicer hands files to its open window only when the second start is told to
SLICERS["prusa"].second_args = ("--single-instance",)


def get(key):
    return SLICERS[key]


# ---------------------------------------------------------------------- in-process engine
# The slicers' own engine (libslic3r, built from their source as the Python modules orcaengine and
# bambuengine, see tools/orcaengine): the same slicing as their programs, inside FreeCAD, without a
# program start. The command line stays the fallback.
ENGINES = {"orca": ("orcaengine", "slicer-engine"), "bambu": ("bambuengine", "slicer-engine-bambu")}
_ENGINE = {}


def engine_dirs(key="orca"):
    ""



    out = []
    for item in (params().GetString(key + "EngineDir", "") or
                 (params().GetString("OrcaEngineDir", "") if key == "orca" else ""),
                 os.environ.get("SWSTYLE_%s_ENGINE" % key.upper(), "")):
        if item:
            out.append(Path(item))
    out.append(Path(App.getUserAppDataDir()) / "SolidWorksStyle" / ENGINES[key][1] / "python")
    return out


def engine(key="orca"):
    ""

    if key not in ENGINES or not params().GetBool("UseEngine", True):
        return None
    if os.environ.get("SWSTYLE_NO_SLICER") == "1":
        return None             # a run that must not slice: no engine either, as no program
    state = _ENGINE.setdefault(key, {"module": None, "tried": False, "error": "", "dirs": False})
    if state["tried"]:
        return state["module"]
    state["tried"] = True
    name = ENGINES[key][0]
    tag = "cp%d%d" % sys.version_info[:2] if os.name == "nt" else "cpython-%d%d" % sys.version_info[:2]
    for folder in engine_dirs(key):
        if not folder.is_dir() or not any(p.name.startswith(name + ".") and tag in p.name
                                          for p in folder.iterdir()):
            continue
        try:
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(str(folder))
                lib = Path(sys.prefix) / "Library" / "bin"
                if lib.is_dir():
                    os.add_dll_directory(str(lib))
            if str(folder) not in sys.path:
                sys.path.insert(0, str(folder))
            import importlib
            module = importlib.import_module(name)
            state["module"] = module
            App.Console.PrintLog("3D Slicer: %s engine %s from %s\n" % (key, module.version, folder))
            return module
        except Exception as error:      # the command line takes over
            state["error"] = "%s: %s" % (folder, error)
            App.Console.PrintWarning("3D Slicer: %s engine not usable (%s)\n" % (key, state["error"]))
    return None


def engine_slice(slicer, meshes, printer, filament, process, choice, out_dir, gcode_name):
    """Slice meshes (already where they print) with the engine: writes the merged presets as the
    command line gets them, out_dir/<gcode_name> and result.json as the command line writes them.
    Returns the engine's numbers; raises when the engine cannot slice."""
    mod = engine(slicer.key)
    if mod is None:
        raise RuntimeError("no engine")
    state = _ENGINE[slicer.key]
    machine = slicer.write_flat("machine", printer, choice.get("printer_overrides") or {}, out_dir)
    fil = slicer.write_flat("filament", filament, choice.get("filament_overrides") or {}, out_dir, printer)
    proc = slicer.write_flat("process", process, choice.get("overrides") or {}, out_dir, printer)
    with _ENGINE_LOCK:
        if not state["dirs"]:
            res = slicer.resources()
            if res is not None:
                mod.set_resources_dir(str(res))
            tmp = slicer.work_dir() / "engine-tmp"
            tmp.mkdir(parents=True, exist_ok=True)
            mod.set_temporary_dir(str(tmp))
            state["dirs"] = True
        result = mod.slice([str(machine), str(proc), str(fil)], [str(m) for m in meshes],
                           str(Path(out_dir) / gcode_name))
    with open(Path(out_dir) / "result.json", "w", encoding="utf-8") as f:
        json.dump({"return_code": 0, "error_string": "", "engine": mod.version}, f)
    result.pop("gcode", None)
    return result


_ENGINE_LOCK = threading.Lock()


# ---------------------------------------------------------------------- the part from FreeCAD
def printable(doc=None, selection=None):
    """The objects to print: the picked bodies/solids, else the active body, else every visible
    solid that is not inside another one's history."""
    import FreeCADGui as Gui
    doc = doc or App.ActiveDocument
    if doc is None:
        return []
    picked = []
    for obj in (selection if selection is not None else [s.Object for s in Gui.Selection.getSelectionEx("", 0)]):
        body = obj if obj.TypeId == "PartDesign::Body" else _body_of(obj)
        target = body or obj
        if _solid(target) and target not in picked:
            picked.append(target)
    if picked:
        return picked
    try:
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        body = view.getActiveObject("pdbody") if view is not None else None
    except Exception:
        body = None
    if body is not None and _solid(body):
        return [body]
    out = []
    for obj in doc.Objects:
        if not _solid(obj) or not getattr(obj, "Visibility", False):
            continue
        if obj.TypeId != "PartDesign::Body" and _body_of(obj) is not None:
            continue
        # used up by a later feature (a Part Cut's tool, a fused shape): print the result only
        if any(_solid(p) and p.TypeId != "PartDesign::Body" for p in obj.InList):
            continue
        out.append(obj)
    return out


def _body_of(obj):
    try:
        for parent in obj.InList:
            if parent.TypeId == "PartDesign::Body":
                return parent
    except Exception as _fw_err:
        _fw_log("slicer.py:708", _fw_err)
    return None


def _solid(obj):
    """Something to print: a solid, or a mesh object (an imported STL, OBJ or 3MF) with triangles."""
    if is_mesh(obj):
        return True
    try:
        shape = obj.Shape
        return shape is not None and not shape.isNull() and len(shape.Solids) > 0
    except Exception:
        return False


def is_mesh(obj):
    """A mesh object with triangles (Mesh::Feature: an imported STL, OBJ, 3MF or PLY)."""
    try:
        return obj.isDerivedFrom("Mesh::Feature") and obj.Mesh.CountFacets > 0
    except Exception:
        return False


def mesh_object(obj):
    """A mesh object's triangles where they stand in FreeCAD, as a plain mesh (no placement of its own)."""
    import Mesh
    return Mesh.Mesh(obj.Mesh.Topology)


def object_mesh(obj, linear=0.003, angular=0.5):
    """The triangles of a body or solid (meshed as the slicer meshes STEP), or a mesh object's own."""
    import MeshPart
    if is_mesh(obj):
        return mesh_object(obj)
    return MeshPart.meshFromShape(Shape=obj.Shape, LinearDeflection=linear, AngularDeflection=angular,
                                  Relative=False)


def object_box(obj):
    return obj.Mesh.BoundBox if is_mesh(obj) else obj.Shape.BoundBox


def object_shape(obj):
    """A body's shape, or a solid made from a mesh object's triangles."""
    if not is_mesh(obj):
        return obj.Shape
    import Part
    sh = Part.Shape()
    sh.makeShapeFromMesh(mesh_object(obj).Topology, 0.05)
    try:
        solid = Part.makeSolid(sh)
        if solid.isValid():
            return solid
    except Exception as _fw_err:
        _fw_log("slicer.py object_shape", _fw_err)
    return sh


def safe_name(text):
    return re.sub(r"[^\w\-. ]+", "_", text).strip() or "Part"


def export_step(objects, path):
    """One STEP file with the objects' solids, in place (global placement).
    Not Import.export: FreeCAD 1.1.4 writes a moved object's Placement as a STEP assembly
    transform that reading the file back drops (a bracket at (100,100,50) turned 180 degrees came
    back at the origin, unturned)."""
    import Part
    shapes = [object_shape(obj).copy() for obj in objects]
    shape = shapes[0] if len(shapes) == 1 else Part.makeCompound(shapes)
    shape.exportStep(str(path))
    return Path(path)


def mesh_step(step, path, linear=0.003, angular=0.5, matrix=None, tick=None):
    """Mesh a STEP file the way the slicer meshes one it opens (see export_mesh). tick(j, m), when given, is told
    before each of the m bodies of a many-body file is meshed (a 50-part assembly takes seconds): it returning False
    stops with Cancelled."""
    import Part
    shape = Part.read(str(step))
    solids = shape.Solids
    if tick is not None and len(solids) > 1 and len(shape.Faces) == sum(len(x.Faces) for x in solids):
        # every face belongs to one of the bodies: each body is meshed on its own (the same triangles), with the window
        # drawn and Cancel heard in between
        import Mesh
        import MeshPart
        mesh = Mesh.Mesh()
        for j, solid in enumerate(solids):
            if tick(j, len(solids)) is False:
                raise Cancelled()
            mesh.addMesh(MeshPart.meshFromShape(Shape=solid, LinearDeflection=linear, AngularDeflection=angular,
                                                Relative=False))
        if matrix is not None:
            mesh.transform(App.Matrix(*matrix) if not isinstance(matrix, App.Matrix) else matrix)
        mesh.write(str(path))
        return Path(path), mesh.CountFacets
    return export_mesh([type("S", (), {"Shape": shape})()], path, linear, angular, matrix)


def export_mesh(objects, path, linear=0.003, angular=0.5, matrix=None):
    """The mesh the slicer would make of the STEP file: OCCT BRepMesh, absolute linear deflection
    (mm) and angular deflection (radians), as the slicer's own STEP import."""
    import Mesh
    import MeshPart
    mesh = Mesh.Mesh()
    for obj in objects:
        mesh.addMesh(object_mesh(obj, linear, angular) if is_mesh(obj) else
                     MeshPart.meshFromShape(Shape=obj.Shape, LinearDeflection=linear,
                                            AngularDeflection=angular, Relative=False))
    if matrix is not None:
        # placed on the plate (rotated, on the bed, at its spot): the slicer keeps it there
        mesh.transform(App.Matrix(*matrix) if not isinstance(matrix, App.Matrix) else matrix)
    mesh.write(str(path))
    return Path(path), mesh.CountFacets


# ---------------------------------------------------------------------- results
def _duration(text):
    total = 0
    for value, unit in re.findall(r"(\d+)\s*([dhms])", text):
        total += int(value) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[unit]
    return total


def fmt_duration(seconds):
    seconds = int(round(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    if h:
        return "%dh %02dm" % (h, m)
    if m:
        return "%dm %02ds" % (m, s)
    return "%ds" % s


def read_result(out_dir, slicer, filament, plate=0):
    """Print time, filament and layers from the G-code header and result.json."""
    out = {"ok": False, "error": "", "gcode": None, "project": None}
    out_dir = Path(out_dir)
    result = _read_json(out_dir / "result.json") or {}
    code = result.get("return_code", -1)
    out["error"] = result.get("error_string", "") if code != 0 else ""
    gcodes = sorted(out_dir.glob("plate_*.gcode"), key=lambda p: int(re.sub(r"\D", "", p.stem) or 0))
    projects = sorted(out_dir.glob("*.gcode.3mf"))
    out["project"] = projects[0] if projects else None
    if not gcodes:
        if not out["error"]:
            out["error"] = "The slicer made no G-code."
        return out
    pick = out_dir / ("plate_%d.gcode" % (plate + 1))
    pick = pick if pick.exists() else gcodes[0]
    out["gcode"] = pick
    out["gcodes"] = gcodes
    head = {}

    def take(line):
        if line.startswith(";"):
            m = re.match(r";\s*([^:=]+?)\s*[:=]\s*(.*)$", line.rstrip())
            if m and m.group(1) not in head:
                head[m.group(1)] = m.group(2)

    with open(pick, "r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            if i > 4000 or line.startswith("; CONFIG_BLOCK_START"):
                break
            take(line)
        # Orca Slicer writes the filament used after the moves, before its settings block
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - 400000))
        for line in f.read().splitlines():
            if line.startswith(("; filament used", "; total filament", "; estimated printing time", "; total layers count")):
                take(line)
    # Bambu Lab printers get the times in the header; other printers only at the end (Orca Slicer)
    total = head.get("total estimated time") or head.get("estimated printing time (normal mode)") or ""
    mt = head.get("model printing time", "")
    if ";" in mt:   # "10m 50s; total estimated time: 17m 24s" lands in one value
        mt, _, rest = mt.partition(";")
        total = total or rest.split(":", 1)[-1]
    out["time"] = _duration(total or mt)
    out["model_time"] = _duration(mt)
    length = head.get("filament used [mm]") or head.get("total filament length [mm]") or "0"
    try:
        out["length_mm"] = float(length.split(",")[0])
    except ValueError:
        out["length_mm"] = 0.0
    try:
        diameter = float(head.get("filament_diameter", "1.75").split(",")[0])
    except ValueError:
        diameter = 1.75
    fdata = slicer.resolve("filament", filament) if filament else {}
    try:
        density = float(_first(fdata.get("filament_density", 0)) or 0)
    except ValueError:
        density = 0.0
    if density <= 0:
        density = DENSITY.get(str(_first(fdata.get("filament_type", "PLA"))).upper(), 1.24)
    volume_cm3 = out["length_mm"] * math.pi * (diameter / 2.0) ** 2 / 1000.0
    out["volume_cm3"] = volume_cm3
    out["weight_g"] = volume_cm3 * density
    try:
        # Orca Slicer and Bambu Studio write "total layer number", PrusaSlicer "total layers count" at the end
        out["layers"] = int(head.get("total layer number") or head.get("total layers count") or "0")
    except ValueError:
        out["layers"] = 0
    if not out["layers"]:
        # some PrusaSlicer versions write no layer count: count its layer changes, as its preview does
        try:
            with open(pick, "r", encoding="utf-8", errors="replace") as f:
                out["layers"] = sum(1 for line in f if line.startswith(";LAYER_CHANGE"))
        except OSError:
            pass
    try:
        cost = float(_first(fdata.get("filament_cost", 0)) or 0)
    except ValueError:
        cost = 0.0
    out["cost"] = cost * out["weight_g"] / 1000.0
    # every filament, as the slicers' slice info lists them (the G-code's lists: one value per filament)
    def numbers(key):
        try:
            return [float(v) for v in (head.get(key) or "").split(",") if v.strip()]
        except ValueError:
            return []
    mm, grams, costs = numbers("filament used [mm]"), numbers("filament used [g]"), numbers("filament cost")
    if not mm:
        # Bambu Studio lists them in its header totals instead: "total filament length [mm] : 5603.39,3166.94"
        mm, grams = numbers("total filament length [mm]"), numbers("total filament weight [g]")
        if len(mm) < 2:
            mm, grams = [], []
    if len(mm) > 1 or grams:
        fil = []
        for i, length in enumerate(mm):
            g = grams[i] if i < len(grams) else length * math.pi * (diameter / 2.0) ** 2 / 1000.0 * density
            fil.append({"slot": i + 1, "length_mm": length, "weight_g": g,
                        "cost": costs[i] if i < len(costs) else cost * g / 1000.0})
        out["filaments"] = [f for f in fil if f["length_mm"] > 0]
        out["length_mm"] = sum(f["length_mm"] for f in fil)
        out["weight_g"] = sum(f["weight_g"] for f in fil)
        out["cost"] = sum(f["cost"] for f in fil)
        out["volume_cm3"] = sum(numbers("filament used [cm3]")) or out["volume_cm3"]
    else:
        out["filaments"] = [{"slot": 1, "length_mm": out["length_mm"], "weight_g": out["weight_g"],
                             "cost": out["cost"]}] if out["length_mm"] > 0 else []
    # the time before the model starts printing (heating, levelling, purging), as the slicers' Prepare time
    out["prepare_time"] = max(0.0, (out["time"] or 0) - (out["model_time"] or 0)) if out["model_time"] else 0.0
    out["ok"] = True
    return out


SEAM_FEATURES = ("Outer wall", "External perimeter", "Outer Wall")


def read_toolpaths(gcode, max_segments=4000000, with_feed=False, marks=None, filament_diameter=1.75):
    """Extrusion moves of a G-code file by layer: [(z, [(feature, x0, y0, x1, y1), ...]), ...].
    G2/G3 arcs are split into short segments; travel moves are skipped. with_feed adds the feed rate (mm/min)
    as a sixth item of each segment, then the part fan (percent), the nozzle temperature (deg C), the line width
    (mm), the volumetric flow (mm3/s), the tool (filament slot, 0-based) and the G-code line number (1-based).
    marks: a list that gets, per returned layer, {"travel": [(x0, y0, x1, y1)], "retract": [(x, y)],
    "seam": [(x, y)]} (the slicers' Travel, Retractions and Seams options)."""
    layers = []
    segs = None
    feature = ""
    x = y = z = 0.0
    absolute_e = False
    last_e = 0.0
    count = 0
    feed = 0.0
    fan = temp = 0.0
    width = 0.0
    tool = 0
    area = math.pi * (filament_diameter / 2.0) ** 2
    after_travel = True
    mark = None
    num = re.compile(r"([XYZEIJRF])(-?[0-9.]+)")
    with open(gcode, "r", encoding="utf-8", errors="replace") as f:
        for lineno, line in enumerate(f, 1):
            if line.startswith(";"):
                if line.startswith("; FEATURE:") or line.startswith(";TYPE:"):
                    feature = line.split(":", 1)[1].strip()
                    after_travel = True
                elif line.startswith(("; LINE_WIDTH:", ";WIDTH:")):
                    try:
                        width = float(line.split(":", 1)[1])
                    except ValueError:
                        pass
                elif line.startswith("; CHANGE_LAYER") or line.startswith(";LAYER_CHANGE"):
                    segs = []
                    mark = {"travel": [], "retract": [], "seam": []}
                    layers.append([z, segs, mark])
                elif line.startswith("; Z_HEIGHT:") and layers:
                    try:
                        layers[-1][0] = float(line.split(":", 1)[1])
                    except ValueError as _fw_err:
                        _fw_log("slicer.py:881", _fw_err)
                continue
            if line.startswith(("M106", "M107", "M104", "M109")):     # the part fan and the nozzle's temperature
                m = re.search(r"\bS([0-9.]+)", line)
                if line.startswith("M107"):
                    fan = 0.0
                elif line.startswith("M106") and m and not re.search(r"\bP[23]\b", line):
                    fan = float(m.group(1)) * 100.0 / 255.0
                elif line.startswith(("M104", "M109")) and m:
                    temp = float(m.group(1))
                continue
            if line[0] == "T" and line[1:2].isdigit():
                try:
                    n = int(line[1:].split()[0])
                    if n < 64:          # T255 / T1000 are the printers' own housekeeping, not a filament
                        tool = n
                except ValueError:
                    pass
                continue
            if line.startswith("M82"):
                absolute_e = True
                continue
            if line.startswith("M83"):
                absolute_e = False
                continue
            code = line[:3]
            if code not in ("G1 ", "G0 ", "G2 ", "G3 ") and not line.startswith("G92"):
                continue
            body = line.split(";", 1)[0]
            # the slicers write "G1 X1.2 Y3.4 E.05": split on spaces (several times faster than the pattern, which
            # stays for anything written another way)
            try:
                vals = {}
                for tok in body.split()[1:]:
                    if tok[0] in "XYZEIJRF":
                        vals[tok[0]] = float(tok[1:])
            except (ValueError, IndexError):
                vals = dict((k, float(v)) for k, v in num.findall(body) if v not in (".", "-", "-."))
            if line.startswith("G92"):
                if "E" in vals:
                    last_e = vals["E"]
                continue
            nx, ny = vals.get("X", x), vals.get("Y", y)
            z = vals.get("Z", z)
            feed = vals.get("F", feed)
            extruding = False
            de = 0.0
            if "E" in vals:
                e = vals["E"]
                de = (e - last_e) if absolute_e else e
                extruding = de > 0
                if absolute_e:
                    last_e = e
            moved = (nx, ny) != (x, y)
            if mark is not None and not extruding:
                if moved:
                    mark["travel"].append((x, y, nx, ny))
                    after_travel = True
                elif de < 0:
                    mark["retract"].append((x, y))
            more = ()
            if with_feed:
                run = math.hypot(nx - x, ny - y)
                if code in ("G2 ", "G3 ") and ("I" in vals or "J" in vals):
                    # an arc's length, not its chord (a nearly closed circle has almost no chord)
                    cx, cy = x + vals.get("I", 0.0), y + vals.get("J", 0.0)
                    r = math.hypot(x - cx, y - cy)
                    sweep = math.atan2(ny - cy, nx - cx) - math.atan2(y - cy, x - cx)
                    if code == "G2 " and sweep >= 0:
                        sweep -= 2 * math.pi
                    if code == "G3 " and sweep <= 0:
                        sweep += 2 * math.pi
                    run = abs(sweep) * r
                flow = de * area / (run / (feed / 60.0)) if (extruding and run > 0 and feed > 0) else 0.0
                more = (feed, fan, temp, width, flow, tool, lineno)
            if extruding and moved and mark is not None and after_travel:
                if feature in SEAM_FEATURES:
                    mark["seam"].append((x, y))
                after_travel = False
            if extruding and segs is not None and code != "G0 " and count < max_segments:
                if code in ("G2 ", "G3 ") and ("I" in vals or "J" in vals):
                    cx, cy = x + vals.get("I", 0.0), y + vals.get("J", 0.0)
                    a0 = math.atan2(y - cy, x - cx)
                    a1 = math.atan2(ny - cy, nx - cx)
                    r = math.hypot(x - cx, y - cy)
                    sweep = a1 - a0
                    if code == "G2 " and sweep >= 0:
                        sweep -= 2 * math.pi
                    if code == "G3 " and sweep <= 0:
                        sweep += 2 * math.pi
                    # pieces by how far a chord strays from the arc (0.03 mm, finer than a line's width), not one
                    # per half millimetre: a print of many holes stays whole within max_segments
                    step = 2.0 * math.acos(max(-1.0, 1.0 - 0.03 / r)) if r > 0.03 else math.pi
                    n = max(2, min(64, int(math.ceil(abs(sweep) / step))))
                    px, py = x, y
                    for i in range(1, n + 1):
                        a = a0 + sweep * i / n
                        qx, qy = (cx + r * math.cos(a), cy + r * math.sin(a)) if i < n else (nx, ny)
                        segs.append((feature, px, py, qx, qy) + more)
                        px, py = qx, qy
                    count += n
                else:
                    segs.append((feature, x, y, nx, ny) + more)
                    count += 1
            x, y = nx, ny
    kept = [layer for layer in layers if layer[1]]
    if marks is not None:
        marks.extend(layer[2] for layer in kept)
    return [(lz, s) for lz, s, _m in kept]


def warm_up():
    """Read both slicers' presets in the background (FreeCAD start), so a panel opens at once."""
    def run():
        for s in SLICERS.values():
            try:
                if s.key in ENGINES and s.exe() is not None:
                    s.load()
            except Exception as _fw_err:
                _fw_log("slicer.py:942", _fw_err)
    t = threading.Thread(target=run, name="swstyle-slicer-presets", daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------- plates for the slicer
def _number(value, default):
    try:
        if isinstance(value, list):
            value = value[0]
        return float(str(value).rstrip("%"))
    except Exception:
        return default


def placed_box(shape, matrix):
    """The bounding box of a shape (or mesh) placed by a matrix (16 numbers or a Matrix)."""
    m = matrix if isinstance(matrix, App.Matrix) else App.Matrix(*matrix)
    s = shape.copy()
    if hasattr(s, "Facets"):
        s.transform(m)
    else:
        s = s.transformGeometry(m)
    return s.BoundBox


def prime_tower_spots(assemble, machine, process, overrides=None, boxes=None):
    """[(x, y)] per plate of a plate list: the prime tower's front-left corner in a free corner of the bed, clear of the
    plate's objects (their meshes' boxes). The back right corner first, as the slicers' default spot."""
    import Mesh
    over = overrides or {}
    try:
        area = [tuple(float(v) for v in str(p).split("x")) for p in machine.get("printable_area") or []]
        x0, x1 = min(p[0] for p in area), max(p[0] for p in area)
        y0, y1 = min(p[1] for p in area), max(p[1] for p in area)
        data = json.loads(Path(assemble).read_text(encoding="utf-8")) if assemble is not None else {"plates": []}
    except Exception:
        return []
    if boxes is not None:
        data = {"plates": [{"boxes": b} for b in boxes]}
    width = _number(over.get("prime_tower_width", process.get("prime_tower_width")), 35.0)
    depth = max(width, 60.0)          # the tower's depth grows with the purge volume; leave room for it
    margin, gap = 10.0, 5.0
    corners = ((x1 - margin - width, y1 - margin - depth), (x0 + margin + 20.0, y1 - margin - depth),
               (x1 - margin - width, y0 + margin + 25.0), (x0 + margin + 20.0, y0 + margin + 25.0))
    spots = []
    for plate in data.get("plates", []):
        boxes = list(plate.get("boxes") or [])
        for o in plate.get("objects", []):
            try:
                boxes.append(Mesh.Mesh(str(o["path"])).BoundBox)
            except Exception:
                continue
        spot = corners[0]
        for cx, cy in corners:
            if all(cx + width + gap < b.XMin or cx - gap > b.XMax or cy + depth + gap < b.YMin or cy - gap > b.YMax
                   for b in boxes):
                spot = (cx, cy)
                break
        spots.append(spot)
    return spots


def write_assemble(objects, plates, path, slots=None, params=None, ranges=None):
    # slots: the filament slot of each object, 1 = the first (the slicers read "filaments" 1-based)
    """The slicers' plate list (their command line's load_assemble_list): objects = [(mesh path,
    plate index)], meshes already in plate coordinates; plates = names. No arranging: the slicer
    moves each plate's objects onto that plate as they are."""
    data = {"plates": []}
    kept = []       # the slicer refuses an empty plate: those are left out
    for i, name in enumerate(plates):
        objs = []
        for k, (p, plate) in enumerate(objects):
            if plate != i:
                continue
            o = {"path": str(p), "count": 1, "filaments": [(slots[k] if slots and k < len(slots) else 1)],
                 "pos_x": [0.0], "pos_y": [0.0], "pos_z": [0.0]}
            # the object's own settings and height ranges (the slicers' object list)
            if params and k < len(params) and params[k]:
                o["print_params"] = {str(a): str(b) for a, b in params[k].items()}
            if ranges and k < len(ranges) and ranges[k]:
                o["height_ranges"] = [{"min_z": float(r["min_z"]), "max_z": float(r["max_z"]),
                                       "range_params": {str(a): str(b) for a, b in (r.get("params") or {}).items()}}
                                      for r in ranges[k]]
            objs.append(o)
        if objs:
            data["plates"].append({"plate_name": name or "", "need_arrange": False, "objects": objs})
            kept.append(i)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    write_assemble.kept = kept
    return Path(path)


class Cancelled(Exception):
    """The slice was cancelled while the parts were meshed."""


def export_items(items, out_dir, linear, angular, step=None):
    """Each object as STEP (then meshed as the slicer meshes STEP) in plate coordinates.
    items = [(name, shape or mesh, matrix, plate)] -> ([(mesh path, plate)], facets). A mesh (an object
    read from a project 3MF, an imported STL) is written as it is. step(k, n, name), when given, is told before each
    object; it returning False stops with Cancelled."""
    paths, facets, used = [], 0, set()
    for idx, (name, shape, matrix, plate) in enumerate(items):
        if step is not None and step(idx, len(items), name) is False:
            raise Cancelled()
        stem = safe_name(name)
        k = 2
        base = stem
        while stem.lower() in used:
            stem = "%s %d" % (base, k)
            k += 1
        used.add(stem.lower())
        if hasattr(shape, "Facets"):
            m = shape.copy()
            m.transform(App.Matrix(*matrix) if not isinstance(matrix, App.Matrix) else matrix)
            mesh, n = Path(out_dir) / (stem + ".stl"), m.CountFacets
            m.write(str(mesh))
        else:
            step_path = export_step([type("S", (), {"Shape": shape})()], Path(out_dir) / (stem + ".step"))
            tick = None
            if step is not None:
                def tick(j, m, idx=idx, name=name):
                    return step(idx, len(items), name, j, m)
            mesh, n = mesh_step(step_path, Path(out_dir) / (stem + ".stl"), linear, angular, matrix, tick=tick)
        paths.append((mesh, plate))
        facets += n
    return paths, facets
