# SPDX-License-Identifier: LGPL-2.1-or-later
"""3D Slicer tab of the CommandManager: Orca Slicer and Bambu Studio in a PropertyManager.

The tab sits after Sketch. Orca Slicer and Bambu Studio open the slicer's
PropertyManager (FreeCAD's task panel, dressed by propertymanager.py): the
part to print, the slicer's own printer, filament and process presets, the
main process settings, then Slice (the slicer's engine, run on its command
line, on the part sent over as a STEP file) and Export G-code. A sliced part is
previewed in the 3D view, layer by layer, coloured by line type the way the
slicers colour them. Everything stays inside FreeCAD: the slicer's own window
is never opened (Ati, 2026-10-25).

Back end: slicer.py. register() runs from startup.init(), before the
CommandManager is built.
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

import json
import math
import os
import shutil
import time
from pathlib import Path

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import slicer as backend
from . import slicersettings
from . import slicerplate
from . import slicerdevice
from . import slicerfull
from . import slicerupdate
from . import slicerapps
from . import slicerobject
from . import slicerpaint
from . import slicerlayers
from . import slicercodes
from . import slicerflush
from . import slicertoolbar

try:
    from . import style
except Exception:
    style = None

Qt = QtCore.Qt
HERE = Path(__file__).resolve().parent / "resources" / "slicer"
TAB = "3D Slicer"

# Line colours by G-code feature, close to the slicers' own preview colours.
FEATURE_COLOURS = {
    "Outer wall": "#ff7d38", "Inner wall": "#ffe64c", "Overhang wall": "#2d5cd6",
    "Sparse infill": "#b03029", "Internal solid infill": "#9654cc", "Top surface": "#f04040",
    "Bottom surface": "#7a6ad8", "Bridge": "#4d80ba", "Gap infill": "#ffffff", "Skirt": "#00876e",
    "Brim": "#00876e", "Support": "#2ec42e", "Support interface": "#127312", "Support transition": "#5aa05a",
    "Ironing": "#ff8c69", "Prime tower": "#c0c0c0", "Custom": "#5ed7e0",
    # PrusaSlicer's names for the same lines (its preview colours)
    "External perimeter": "#ff7d38", "Perimeter": "#ffe64c", "Overhang perimeter": "#2d5cd6",
    "Internal infill": "#b03029", "Solid infill": "#9654cc", "Top solid infill": "#f04040",
    "Bridge infill": "#4d80ba", "Gap fill": "#ffffff", "Skirt/Brim": "#00876e", "Support material": "#2ec42e",
    "Support material interface": "#127312", "Wipe tower": "#c0c0c0",
}
NOT_PART = ("Skirt", "Brim", "Prime tower", "Custom", "Wipe tower", "Skirt/Brim")


def _icon(name):
    return str(HERE / (name + ".svg"))


def _tok(name, fallback):
    if style is not None:
        try:
            return style.T.hex(name)
        except Exception as _fw_err:
            _fw_log("slicerui.py:77", _fw_err)
    return fallback


def _dark():
    try:
        return bool(style.dark()) if style is not None else False
    except Exception:
        return False


def clean_env():
    """The environment for the slicer's program. Inside FreeCAD's Linux AppImage the library and
    Python paths point into FreeCAD's bundle, which another AppImage must not see."""
    env = QtCore.QProcessEnvironment.systemEnvironment()
    if os.name != "nt" and os.environ.get("APPDIR"):
        for var in ("LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH",
                    "QT_QPA_PLATFORM_PLUGIN_PATH", "APPDIR", "APPIMAGE", "ARGV0", "OWD", "GDK_PIXBUF_MODULE_FILE",
                    "GSETTINGS_SCHEMA_DIR", "FONTCONFIG_FILE", "FONTCONFIG_PATH", "XDG_DATA_DIRS",
                    "QTWEBENGINE_DISABLE_SANDBOX", "QT_SCALE_FACTOR", "SSL_CERT_FILE"):
            env.remove(var)
    return env


def last_slicer():
    key = backend.params().GetString("Active", "orca")
    return key if key in backend.SLICERS else "orca"


# ---------------------------------------------------------------------- plates in one 3MF
def plate_origins(count, bed_box):
    """Where each of count plates sits, as the slicers lay plates out (slicerplate.Bed.plate_origin)."""
    import math as _m
    x0, y0, x1, y1 = bed_box or (0.0, 0.0, 256.0, 256.0)
    w, d = x1 - x0, y1 - y0
    cols = max(1, int(_m.ceil(_m.sqrt(max(1, count)))))
    gap = slicerplate.Plate.GAP
    return [App.Vector((i % cols) * w * (1 + gap), -(i // cols) * d * (1 + gap), 0) for i in range(count)]


def moved(matrix, origin):
    """A placement (16 numbers or a Matrix) moved by origin."""
    m = matrix if isinstance(matrix, App.Matrix) else App.Matrix(*matrix)
    t = App.Matrix()
    t.move(origin)
    return t.multiply(m)


# ---------------------------------------------------------------------- saved choices
def saved(key):
    p = backend.params()
    try:
        overrides = json.loads(p.GetString(key + "Overrides", "{}") or "{}")
    except ValueError:
        overrides = {}
    extra = {}
    for name in ("filament_overrides", "printer_overrides"):
        try:
            extra[name] = json.loads(p.GetString(key + _camel(name), "{}") or "{}")
        except ValueError:
            extra[name] = {}
    try:
        slots = json.loads(p.GetString(key + "Slots", "[]") or "[]")
    except ValueError:
        slots = []
    extra["slots"] = slots if isinstance(slots, list) else []
    try:
        flush = json.loads(p.GetString(key + "Flush", "{}") or "{}")
    except ValueError:
        flush = {}
    if isinstance(flush, dict) and flush.get("matrix"):
        extra["flush"] = flush
    return dict({"printer": p.GetString(key + "Printer", ""), "filament": p.GetString(key + "Filament", ""),
                 "process": p.GetString(key + "Process", ""), "overrides": overrides,
                 "orient": p.GetBool(key + "Orient", False)}, **extra)


def _camel(name):
    return "".join(w.capitalize() for w in name.split("_"))


def save(key, choice):
    p = backend.params()
    p.SetString("Active", key)
    p.SetString(key + "Printer", choice["printer"])
    p.SetString(key + "Filament", choice["filament"])
    p.SetString(key + "Process", choice["process"])
    p.SetString(key + "Overrides", json.dumps(choice["overrides"]))
    for name in ("filament_overrides", "printer_overrides"):
        p.SetString(key + _camel(name), json.dumps(choice.get(name) or {}))
    p.SetString(key + "Slots", json.dumps(choice.get("slots") or []))
    p.SetString(key + "Flush", json.dumps(choice.get("flush") or {}))
    p.SetBool(key + "Orient", bool(choice["orient"]))


def default_choice(key):
    """Saved choice, else the slicer's own current presets, else the printer's defaults."""
    s = backend.get(key)
    choice = saved(key)
    if choice["printer"] and s.preset("machine", choice["printer"]) is not None:
        return choice
    cur = s.current_presets()
    printer = cur["machine"] if s.preset("machine", cur["machine"]) is not None else ""
    if not printer:
        printers = s.printers()
        bbl = [p for p in printers if p.name == "Bambu Lab X1 Carbon 0.4 nozzle"]
        printer = (bbl or printers or [None])[0]
        printer = printer.name if printer is not None else ""
    d = s.defaults(printer) if printer else {"print": "", "filament": ""}
    choice.update(printer=printer,
                  filament=cur["filament"] if s.preset("filament", cur["filament"]) else d["filament"],
                  process=cur["print"] if s.preset("process", cur["print"]) else d["print"], overrides={},
                  filament_overrides={}, printer_overrides={}, slots=[])
    return choice


# ---------------------------------------------------------------------- slicing job
class Job(QtCore.QObject):
    """One slice: mesh the part, run the slicer's command line, read the result."""

    progress = QtCore.Signal(int, str)
    finished = QtCore.Signal(dict)

    def __init__(self, key, objects, choice, parent=None):
        super().__init__(parent)
        self.key = key
        self.slicer = backend.get(key)
        self.objects = objects
        self.choice = choice
        self.proc = None
        self.out_dir = None
        self.started = 0.0
        self.cancelled = False

    def _meshing(self, k, n, name, j=0, m=1):
        """Before each part (k of n), and each body (j of m) of a many-body part, is meshed: says which (a 50-part
        assembly takes a while), keeps the window drawn and lets Cancel through."""
        if n > 1 and m > 1:
            text = "Meshing part %d of %d (%s), body %d of %d..." % (k + 1, n, name, j + 1, m)
        elif n > 1:
            text = "Meshing part %d of %d (%s)..." % (k + 1, n, name)
        elif m > 1:
            text = "Meshing %s, body %d of %d..." % (name, j + 1, m)
        else:
            text = ""
        if text:
            self.progress.emit(2 + int(3 * (k + float(j) / m) / n), text)
        QtWidgets.QApplication.processEvents()      # the window stays drawn and Cancel can be pressed
        return not self.cancelled

    def start(self):
        s = self.slicer
        engine = backend.engine(s.key) if slicerupdate.engine_current(s.key) else None
        if s.exe() is None and engine is None:
            self.finished.emit({"ok": False, "error": missing_text(s)})
            return
        engine_meshes = None
        name = backend.safe_name(self.objects[0].Label if len(self.objects) == 1 else
                                 (App.ActiveDocument.Label if App.ActiveDocument else "Part"))
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.out_dir = s.work_dir() / ("%s-%s" % (name, stamp))
        n = 1
        while self.out_dir.exists():
            # two slices in one second each get their own folder
            n += 1
            self.out_dir = s.work_dir() / ("%s-%s_%d" % (name, stamp, n))
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._tidy(s.work_dir())
        self.progress.emit(2, "Meshing the part...")
        if s.key == "prusa":
            self._prusa_start(name)
            return
        try:
            # The part goes over as STEP; the slicer's command line reads only meshes, so the STEP
            # file is meshed here exactly as the slicer meshes a STEP file it opens
            linear, angular = s.mesh_deflection()
            items = self.choice.get("items")
            slots = self.choice.get("slots") or []
            # more than one filament slot in use: the slicer's program slices it (the engine takes one filament)
            multi = len(slots) > 1 and bool(items) and any(k != 1 for k in (self.choice.get("slot_of") or []))
            # objects with settings of their own: the slicer's program slices them (the engine takes one setting set)
            multi = multi or any(self.choice.get("object_params") or []) or any(self.choice.get("object_ranges") or [])
            matrix = self.choice.get("matrix")
            assemble = None
            plate = self.choice.get("plate", 0)
            paints = self.choice.get("object_paint") or []
            profiles = self.choice.get("object_profile") or []
            codes_all = self.choice.get("layer_codes_all") or {}
            # paint, a layer height profile or layer codes on any plate: every plate goes as one 3MF (Slice all)
            parts_all = self.choice.get("object_parts") or []
            painted = items and (bool(self.choice.get("layer_codes")) or any(codes_all.values()) or any(parts_all)
                                 or any(slicerpaint.has_paint(paints[k]) for k in range(min(len(items), len(paints))))
                                 or any(profiles[k] for k in range(min(len(items), len(profiles)))))
            tower = None
            kept_plates = []
            if painted:
                # painted supports, seams or colours: the plates go to the slicer's program as one 3MF with the paint
                # (the plate list takes plain meshes only), every plate with its own paint, as the slicers' Slice all
                def at(key, k, default=None):
                    v = self.choice.get(key) or []
                    return v[k] if k < len(v) else default
                kept = sorted({it[3] for it in items})          # the slicer refuses an empty plate: left out
                origins = plate_origins(len(kept), self.choice.get("bed_box"))
                objs3, plate_of = [], []
                for k, it in enumerate(items):
                    n = kept.index(it[3])
                    objs3.append({"name": it[0], "shape": it[1], "matrix": moved(it[2], origins[n]),
                                  "paint": at("object_paint", k), "slot": at("slot_of", k, 1),
                                  "params": at("object_params", k), "ranges": at("object_ranges", k),
                                  "profile": at("object_profile", k), "parts": at("object_parts", k)})
                    plate_of.append(n)
                extra = {}
                by_plate = [(kept.index(p) + 1, lst) for p, lst in sorted(codes_all.items()) if lst and p in kept]
                if not by_plate and self.choice.get("layer_codes"):
                    by_plate = [(kept.index(plate) + 1 if plate in kept else 1, self.choice["layer_codes"])]
                if by_plate:
                    # color change, pause, filament change, custom G-code at a layer (the layer slider's right-click)
                    extra["Metadata/custom_gcode_per_layer.xml"] = slicercodes.xml_plates(by_plate, max(1, len(slots)))
                mesh, facets = slicerpaint.write_plate(objs3, self.out_dir / (name + ".3mf"), linear, angular,
                                                       extra=extra, plates=plate_of if len(kept) > 1 else None)
                mesh = [mesh]
                multi = True
                matrix = items[[k for k, it in enumerate(items) if it[3] == plate][0] if plate in kept else 0][2]
                self.choice["plate"] = kept.index(plate) if plate in kept else 0
                kept_plates = kept
                engine_meshes = None
                tower = [[backend.placed_box(it[1], it[2]) for it in items if it[3] == p] for p in kept]
            elif items:
                # every object on every plate, each where it stands on its plate
                objs, facets = backend.export_items(items, self.out_dir, linear, angular, step=self._meshing)
                mesh = [p for p, _ in objs]
                assemble = backend.write_assemble(objs, self.choice.get("plates") or [""],
                                                  self.out_dir / (name + ".json"), slots=self.choice.get("slot_of"),
                                                  params=self.choice.get("object_params"),
                                                  ranges=self.choice.get("object_ranges"))
                matrix = items[0][2]
                kept = backend.write_assemble.kept
                kept_plates = list(kept)
                self.choice["plate"] = kept.index(plate) if plate in kept else 0
                # the engine slices the plate on show (the command line slices every plate)
                engine_meshes = [p for p, k in objs if k == plate] or [p for p, k in objs if k == kept[0]]
            else:
                if any(backend.is_mesh(o) for o in self.objects):
                    # a mesh object (an imported STL): its triangles go as they are
                    mesh, facets = backend.export_mesh(self.objects, self.out_dir / (name + ".stl"), linear, angular,
                                                       matrix)
                else:
                    step = backend.export_step(self.objects, self.out_dir / (name + ".step"))
                    mesh, facets = backend.mesh_step(step, self.out_dir / (name + ".stl"), linear, angular, matrix,
                                                     tick=lambda j, m: self._meshing(0, 1, name, j, m))
                # placed on the plate: the engine can take it as it stands; else the command line arranges it
                engine_meshes = [mesh] if matrix is not None else None
            # the edited flushing volumes (slicerflush) go with the process, for the filaments sliced together
            process_over = slicerflush.overrides(self.choice, len(slots) if multi else 1)
            if any(p and (p.get("fuzzy") or (p.get("dabs") or {}).get("fuzzy")) for p in paints):
                # fuzzy skin paint prints only when Fuzzy Skin is not Disabled: as the slicers do, Painted only then
                fuzzy = process_over.get("fuzzy_skin", s.resolve("process", self.choice["process"]).get("fuzzy_skin"))
                if str(fuzzy[0] if isinstance(fuzzy, list) and fuzzy else fuzzy or "disabled_fuzzy") == "disabled_fuzzy":
                    process_over["fuzzy_skin"] = "none"
            spots = self.choice.get("tower_spots") or {}
            fixed = {kept_plates.index(p): xy for p, xy in spots.items() if p in kept_plates}
            args = s.slice_args(mesh, self.choice["printer"], self.choice["filament"], self.choice["process"],
                                process_over, self.out_dir, self.choice["orient"] and matrix is None,
                                arrange=matrix is None,
                                filament_overrides=self.choice.get("filament_overrides"),
                                printer_overrides=self.choice.get("printer_overrides"),
                                assemble=assemble if items else None,
                                more_filaments=s.slot_files(slots, self.choice["printer"], self.out_dir) if multi else None,
                                tower_boxes=tower, tower_fixed=fixed)
        except backend.Cancelled:
            return                      # Cancel already said so
        except Exception as error:
            if self.cancelled:
                return
            self.finished.emit({"ok": False, "error": "Could not prepare the part: %s" % error})
            return
        self.facets = facets
        self.args = args
        self.kept_plates = list(kept_plates) if len(kept_plates) > 1 else None
        if engine_meshes and not multi and engine is not None:
            # the slicer's own engine inside FreeCAD (the .gcode.3mf a Bambu Lab printer is sent is
            # made by the program when it is asked for: ensure_project)
            self._engine_start(engine_meshes)
            return
        self._start_exe()

    def _prusa_start(self, name):
        """PrusaSlicer: every plate with something on it, one command-line run each (plate_N.gcode, N counting the
        plates sliced), as the slicers' Slice all; the objects go where they stand on their plate."""
        s, choice = self.slicer, self.choice
        try:
            linear, angular = s.mesh_deflection()
            items = choice.get("items")
            plate = choice.get("plate", 0)
            slots = choice.get("slots") or []
            slot_of = list(choice.get("slot_of") or [])
            fils = None
            if items:
                objs, facets = backend.export_items(items, self.out_dir, linear, angular, step=self._meshing)
                kept = sorted({p for _m, p in objs})
                groups = [[m for m, p in objs if p == k] for k in kept]
                arrange = False
                if len(slots) > 1 and any(k != 1 for k in slot_of[:len(items)]):
                    # objects on other filaments: each plate goes as a 3MF with the extruder of each object, and
                    # every slot's filament preset is given in order (extruder N prints with slot N's filament)
                    from . import slicerprusa
                    used = max(slot_of[:len(items)] or [1])
                    fils = [sl.get("preset") or choice["filament"] for sl in slots[:used]]
                    groups = []
                    for n, k in enumerate(kept):
                        obs = [slicerprusa.mesh_object(m, items[i][0], slot_of[i] if i < len(slot_of) else 1)
                               for i, (m, p) in enumerate(objs) if p == k]
                        groups.append([slicerprusa.write_3mf(obs, self.out_dir / ("plate_%d.3mf" % (n + 1)))])
            else:
                matrix = choice.get("matrix")
                if any(backend.is_mesh(o) for o in self.objects):
                    # a mesh object (an imported STL): its triangles go as they are
                    mesh, facets = backend.export_mesh(self.objects, self.out_dir / (name + ".stl"), linear, angular,
                                                       matrix)
                else:
                    step = backend.export_step(self.objects, self.out_dir / (name + ".step"))
                    mesh, facets = backend.mesh_step(step, self.out_dir / (name + ".stl"), linear, angular, matrix,
                                                     tick=lambda j, m: self._meshing(0, 1, name, j, m))
                kept, groups, arrange = [plate], [[mesh]], matrix is None
            choice["plate"] = kept.index(plate) if plate in kept else 0
            over = slicerflush.overrides(choice, 1)
            self.queue = [s.slice_args(g, choice["printer"], choice["filament"], choice["process"], over, self.out_dir,
                                       arrange=arrange, filament_overrides=choice.get("filament_overrides"),
                                       printer_overrides=choice.get("printer_overrides"),
                                       more_filaments=fils[1:] if fils else None,
                                       output="plate_%d.gcode" % (i + 1)) for i, g in enumerate(groups)]
        except backend.Cancelled:
            return                      # Cancel already said so
        except Exception as error:
            if self.cancelled:
                return
            self.finished.emit({"ok": False, "error": "Could not prepare the part: %s" % error})
            return
        self.facets = facets
        self.args = self.queue.pop(0)
        self.kept_plates = list(kept) if len(kept) > 1 else None
        self.plates_total = len(groups)
        self._start_exe()

    def _engine_start(self, meshes):
        import threading
        if self.cancelled:
            return
        self.progress.emit(10, "Slicing with %s's engine..." % self.slicer.title)
        self.started = time.monotonic()
        self.engine_state = state = {"done": False, "error": None, "result": None}
        choice = self.choice
        gcode = "plate_%d.gcode" % (choice.get("plate", 0) + 1)

        def run():
            try:
                state["result"] = backend.engine_slice(self.slicer, meshes, choice["printer"], choice["filament"],
                                                       choice["process"], choice, self.out_dir, gcode)
            except Exception as error:
                state["error"] = str(error) or error.__class__.__name__
            state["done"] = True

        threading.Thread(target=run, name="SWStyleOrcaEngine", daemon=True).start()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._engine_poll)
        self.timer.start(40)

    def _engine_poll(self):
        state = self.engine_state
        if not state["done"]:
            return
        self.timer.stop()
        if state["error"] is not None:
            # the slicer's program tries it the usual way (and gives its own message if it fails too)
            App.Console.PrintWarning("3D Slicer: engine could not slice (%s); using %s\n"
                                     % (state["error"], self.slicer.title))
            self.engine_state = None
            if self.slicer.exe() is None:
                self.finished.emit({"ok": False, "error": state["error"]})
                return
            self._start_exe()
            return
        self.engine = True
        self._done(0, None)

    def _start_exe(self):
        if self.cancelled:
            return
        s, args = self.slicer, self.args
        exe = s.cli_exe() if hasattr(s, "cli_exe") else s.exe()
        if exe is None:
            self.finished.emit({"ok": False, "error": missing_text(s)})
            return
        self.proc = QtCore.QProcess(self)
        self.proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        self.proc.setWorkingDirectory(str(self.out_dir))
        self.proc.setProcessEnvironment(clean_env())
        self.proc.readyRead.connect(self._read)
        self.proc.finished.connect(self._done)
        self.proc.errorOccurred.connect(self._error)
        self.progress.emit(5, "Slicing with %s..." % s.title)
        self.started = time.monotonic()
        with open(self.out_dir / "command.txt", "w", encoding="utf-8") as f:
            f.write(json.dumps([str(exe)] + args, indent=1))
        self.proc.start(str(exe), args)

    def _tidy(self, root, keep=8):
        """Keep the last few slices only."""
        try:
            # (the engine's temporary folder stays)
            folders = sorted((p for p in root.iterdir() if p.is_dir() and p.name != "engine-tmp"),
                             key=lambda p: p.stat().st_mtime)
            for old in folders[:-keep]:
                shutil.rmtree(old, ignore_errors=True)
        except Exception as _fw_err:
            _fw_log("slicerui.py:315", _fw_err)

    def _read(self):
        text = bytes(self.proc.readAll()).decode("utf-8", "replace")
        pct = None
        for part in text.replace("\t", " ").split("("):
            if "%)" in part:
                try:
                    pct = int(part.split("%)")[0].strip())
                except ValueError as _fw_err:
                    _fw_log("slicerui.py:325", _fw_err)
        if pct is not None:
            self.progress.emit(5 + int(pct * 0.9), "Slicing with %s... %d%%" % (self.slicer.title, pct))
        try:
            with open(self.out_dir / "slicer.log", "a", encoding="utf-8") as f:
                f.write(text)
        except Exception as _fw_err:
            _fw_log("slicerui.py:332", _fw_err)

    def _error(self, err):
        if err == QtCore.QProcess.FailedToStart:
            exe = self.proc.program() if self.proc is not None else ""
            self.finished.emit({"ok": False, "error": "%s could not be started (%s). Check that the file is still there "
                                "and that security software lets it run; Slicer Updates can download it again."
                                % (self.slicer.title, exe or "no program")})

    def _done(self, code, status):
        if getattr(self, "queue", None) and code == 0:
            # PrusaSlicer: the next plate
            self.args = self.queue.pop(0)
            done = self.plates_total - len(self.queue) - 1
            self.progress.emit(5 + int(90 * done / max(1, self.plates_total)),
                               "Slicing plate %d of %d with %s..." % (done + 1, self.plates_total, self.slicer.title))
            self._start_exe()
            return
        result = backend.read_result(self.out_dir, self.slicer, self.choice["filament"], self.choice.get("plate", 0))
        result["seconds"] = time.monotonic() - self.started
        result["engine"] = bool(getattr(self, "engine", False))
        if result["engine"] and self.slicer.exe() is not None:
            # how the program makes the same slice with its .gcode.3mf, when one is wanted
            result["command"] = [str(self.slicer.exe())] + [str(a) for a in self.args]
        result["exit"] = code
        result["out_dir"] = self.out_dir
        result["facets"] = getattr(self, "facets", 0)
        # every plate sliced together (the slicers' Slice all): which plate each plate_N.gcode is, and which one shows
        result["kept_plates"] = getattr(self, "kept_plates", None)
        result["plate_index"] = self.choice.get("plate", 0)
        if not result["ok"]:
            said = ""
            try:
                lines = [l.strip() for l in (self.out_dir / "slicer.log").read_text("utf-8", "replace").splitlines()
                         if l.strip()]
                said = " ".join(lines[-3:])[-300:]
            except OSError:
                pass
            if not result["error"]:
                result["error"] = "%s stopped (exit code %s)." % (self.slicer.title, code)
            if said and said not in result["error"]:
                # the slicer's own last words: what it was missing
                result["error"] += " %s said: %s" % (self.slicer.title, said)
        self.progress.emit(100, "")
        self.finished.emit(result)

    def cancel(self):
        """Stop the slice: meshing stops at the next part, the slicer's command line is stopped, the engine's result
        (it finishes on its own thread) is dropped. Nothing more is emitted."""
        self.cancelled = True
        if getattr(self, "timer", None) is not None:
            self.timer.stop()
        self.queue = []
        if self.proc is not None:
            for sig, slot in ((self.proc.finished, self._done), (self.proc.readyRead, self._read),
                              (self.proc.errorOccurred, self._error)):
                try:
                    sig.disconnect(slot)
                except Exception as _fw_err:
                    _fw_log("slicerui cancel disconnect", _fw_err)
            if self.proc.state() != QtCore.QProcess.NotRunning:
                self.proc.kill()        # the slice's own command-line run, started by this job
                self.proc.waitForFinished(3000)


# ---------------------------------------------------------------------- toolpath preview
FILAMENT_AREA = math.pi * (1.75 / 2.0) ** 2      # mm2, 1.75 mm filament


_READ = {}      # G-code path -> {"thread", "layers", "marks"}: toolpaths read ahead after a slice


def read_ahead(gcode):
    """Read a slice's toolpaths and make them ready to draw on a thread, so Preview shows them at once (the slicers
    have them ready when the slice is done). Only the newest slice is kept."""
    import threading
    key = str(gcode)
    if key in _READ:
        return
    _READ.clear()
    entry = {"ready": None}

    def run():
        try:
            entry["ready"] = prepare(key)
        except Exception as _fw_err:
            _fw_log("slicerui read ahead", _fw_err)
    entry["thread"] = threading.Thread(target=run, name="SWStyleSlicerToolpaths", daemon=True)
    _READ[key] = entry
    entry["thread"].start()


def toolpaths(gcode):
    """The prepared toolpaths of a G-code (prepare()): the read-ahead result when there is one (waits for it to
    finish), else made now."""
    entry = _READ.get(str(gcode))
    if entry is not None:
        entry["thread"].join()
        if entry["ready"] is not None:
            return entry["ready"]
    return prepare(gcode)


def prepare(gcode):
    """Everything the preview draws, in the slicer's coordinates, with no Qt or Coin (it runs on a thread): per layer
    its line groups (line type, points, count, the values the views colour by) and its option marks (travel,
    retractions, seams), the line types' time and length, the value ranges, the part's extent."""
    marks = []
    layers = backend.read_toolpaths(gcode, with_feed=True, marks=marks)
    out = {"layers": layers, "nodes": [], "stats": {}, "features": [], "xmin": None}
    if not layers:
        return out
    hyp, log10 = math.hypot, math.log10
    xmin = ymin = float("inf")
    xmax = ymax = float("-inf")
    for _z, segs in layers:
        part = [g for g in segs if g[0] not in NOT_PART]
        if part:
            xs = [g[1] for g in part] + [g[3] for g in part]
            ys = [g[2] for g in part] + [g[4] for g in part]
            xmin, xmax = min(xmin, min(xs)), max(xmax, max(xs))
            ymin, ymax = min(ymin, min(ys)), max(ymax, max(ys))
    if xmin == float("inf"):
        return out
    out.update(xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax)
    feeds = [g[5] for _z, segs in layers for g in segs if g[5] > 0]
    out["speed_range"] = (min(feeds), max(feeds)) if feeds else (0.0, 0.0)
    stats, features = {}, []
    series = {"speed": [], "height": [], "time": [], "fan": [], "temp": [], "width": [], "flow": [], "tool": [],
              "timelog": []}
    filament = 0.0
    layer_values = []
    below = 0.0
    counts = {"travel": 0, "retract": 0, "seam": 0}
    for index, (z, segs) in enumerate(layers):
        height = max(0.0, z - below)
        below = z
        ltime = sum([hyp(g[3] - g[1], g[4] - g[2]) * 60.0 / g[5] for g in segs if g[5] > 0])
        layer_values.append((height, ltime))
        by_feature = {}
        for g in segs:
            by_feature.setdefault(g[0], []).append(g)
        groups = []
        for f, group in by_feature.items():
            n = len(group)
            series_group = {"speed": [g[5] for g in group], "fan": [g[6] for g in group],
                            "temp": [g[7] for g in group], "height": [height] * n, "time": [ltime] * n,
                            "width": [g[8] for g in group], "flow": [g[9] for g in group],
                            "tool": [g[10] for g in group], "timelog": [log10(max(ltime, 0.1))] * n}
            if f not in stats:
                stats[f] = [0.0, 0.0]
                features.append(f)
            stat = stats[f]
            pts = [p for g in group for p in ((g[1], g[2], z), (g[3], g[4], z))]
            runs = [hyp(g[3] - g[1], g[4] - g[2]) for g in group]
            secs = [r * 60.0 / g[5] if g[5] > 0 else 0.0 for r, g in zip(runs, group)]
            stat[1] += sum(runs)
            stat[0] += sum(secs)
            # filament length = volume / filament cross-section (the flow is in mm3/s)
            filament += sum([g[9] * t for g, t in zip(group, secs)]) / FILAMENT_AREA
            groups.append((f, pts, n, series_group))
            for k, v in series_group.items():
                series[k].extend(v)
        mark = marks[index] if index < len(marks) else {}
        options = {"travel": [p for (ax, ay, bx, by) in mark.get("travel") or [] for p in ((ax, ay, z), (bx, by, z))],
                   "retract": [(px, py, z + 0.05) for px, py in mark.get("retract") or []],
                   "seam": [(px, py, z + 0.05) for px, py in mark.get("seam") or []]}
        for k in counts:
            counts[k] += len(mark.get(k) or [])
        out["nodes"].append((groups, options))
    # Line Width and Flow: the moves before the first width comment carry none, they do not set the low end
    series["width"] = [v for v in series["width"] if v > 0] or series["width"]
    series["flow"] = [v for v in series["flow"] if v > 0] or series["flow"]
    out.update(stats=stats, features=features, filament_mm=filament, layer_values=layer_values,
               option_counts=counts, ranges={k: (min(v), max(v)) for k, v in series.items() if v})
    return out


class _LayerMoves:
    """Per layer: its moves in G-code order [(x0, y0, z, x1, y1, seg)], made when first asked for (the moves slider
    and the G-code window look at one layer at a time)."""

    def __init__(self, layers, dx, dy, dz):
        self._layers, self._d, self._made = layers, (dx, dy, dz), {}

    def __len__(self):
        return len(self._layers)

    def __getitem__(self, i):
        if i < 0:
            i += len(self._layers)
        if i not in self._made:
            dx, dy, dz = self._d
            z, segs = self._layers[i]
            self._made[i] = [(s[1] + dx, s[2] + dy, z + dz, s[3] + dx, s[4] + dy, s) for s in segs]
        return self._made[i]

    def __iter__(self):
        return (self[i] for i in range(len(self._layers)))


class Preview:
    """The sliced part's lines in the 3D view, one switch per layer, the part hidden meanwhile."""

    def __init__(self):
        self.root = None
        self.switches = []
        self.view = None
        self.hidden = []
        self.layers = []
        self.objects = []
        self.feature_switches = {}     # line type -> the switches that draw it, one per layer
        self.stats = {}                # line type -> [seconds, millimetres of extrusion]
        self.view_mode = "type"        # "type" or one of VIEW_UNITS
        self.speed_range = (0.0, 0.0)
        self.ranges = {}               # view -> (low, high)
        self._paint = []               # (material, [feature], [feed]) per layer and line type
        self.shown_features = set()
        self.tool_colours = []         # the filament slots' colours ("#rrggbb"), for the Filament view
        self.option_switches = {}      # "travel" | "retract" | "seam" -> one switch per layer
        self.options_on = set()        # the options shown (the slicers start with none)
        self.filament_mm = 0.0         # filament used, by the G-code's extrusion
        self.layer_moves = []          # per layer: its moves in G-code order [(x0, y0, z, x1, y1, seg)] (the moves slider)
        self.layer_values = []         # per layer: (height, time) for the Layer Height / Layer Time views
        self.lower = 1                 # the layer range shown (the slicers' two-handle layer slider)
        self.upper = 0
        self.scrub_node = None         # the top layer drawn up to a move, and the tool head there
        self.gcode_path = None         # the G-code shown (the G-code window's lines)
        self._line_starts = None

    def show(self, gcode, objects, align=True):
        """align: move the lines onto the FreeCAD part; off when the plate shows (bed coordinates)."""
        from pivy import coin
        self.clear()
        P = toolpaths(gcode)
        if not P or not P["layers"] or P["xmin"] is None:
            return 0
        layers = P["layers"]
        self.gcode_path, self._line_starts = gcode, None
        # Where the part sits on the slicer's plate: the part's lines without skirt and brim
        box = App.BoundBox()
        for obj in objects:
            box.add(backend.object_box(obj))
        dx = (box.XMin + box.XMax) / 2.0 - (P["xmin"] + P["xmax"]) / 2.0
        dy = (box.YMin + box.YMax) / 2.0 - (P["ymin"] + P["ymax"]) / 2.0
        dz = box.ZMin
        if not align:
            dx = dy = dz = 0.0
        root = coin.SoSeparator()
        root.setName("SWStyle_SlicerPreview")
        # the layers keep their own render caches; the whole preview must not, or each move of the layer slider
        # makes Coin rebuild a cache of every toolpath (a slow drag on a big print)
        root.renderCaching = coin.SoSeparator.OFF
        style_node = coin.SoDrawStyle()
        style_node.lineWidth = 2.0
        root.addChild(style_node)
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        root.addChild(light)
        # the toolpaths were made ready off the main thread in the slicer's coordinates (toolpaths(), read
        # ahead after the slice): one move puts them onto the part
        body = coin.SoSeparator()
        body.renderCaching = coin.SoSeparator.OFF
        move = coin.SoTranslation()
        move.translation = (dx, dy, dz)
        body.addChild(move)
        root.addChild(body)
        palette = {}
        for f in P["features"]:
            c = QtGui.QColor(FEATURE_COLOURS.get(f, "#d0d0d0"))
            palette[f] = (c.redF(), c.greenF(), c.blueF())
        self.switches = []
        self.feature_switches, self._paint, self._binds = {}, [], []
        self.stats = {f: list(v) for f, v in P["stats"].items()}
        self.speed_range = P["speed_range"]
        self.option_switches = {"travel": [], "retract": [], "seam": []}
        option_style = {"travel": ((0.22, 0.45, 0.95), 1.0), "retract": ((0.85, 0.2, 0.85), 6.0),
                        "seam": ((0.95, 0.95, 0.95), 6.0)}
        self.filament_mm = P["filament_mm"]
        self.layer_moves = _LayerMoves(layers, dx, dy, dz)     # made per layer when the moves slider asks
        self.layer_values = P["layer_values"]
        self.scrub_node = None
        for index, (groups, options) in enumerate(P["nodes"]):
            sw = coin.SoSwitch()
            sw.whichChild = coin.SO_SWITCH_ALL
            outer = coin.SoSeparator()
            for f, pts, n, series_group in groups:
                inner = coin.SoSwitch()
                inner.whichChild = coin.SO_SWITCH_ALL
                sep = coin.SoSeparator()
                coords = coin.SoCoordinate3()
                coords.point.setValues(0, len(pts), pts)
                # the Line Type view: one colour for the group (OVERALL), which draws far faster than a colour per
                # line; the value views colour each line (PER_PART, set_view)
                mat = coin.SoMaterial()
                mat.diffuseColor = palette[f]
                bind = coin.SoMaterialBinding()
                bind.value = coin.SoMaterialBinding.OVERALL
                lines = coin.SoLineSet()
                lines.numVertices.setValues(0, n, [2] * n)
                for node in (coords, mat, bind, lines):
                    sep.addChild(node)
                inner.addChild(sep)
                outer.addChild(inner)
                self.feature_switches.setdefault(f, []).append(inner)
                self._paint.append((mat, f, series_group))
                self._binds.append(bind)
            for name, (rgb, size) in option_style.items():
                inner = coin.SoSwitch()
                inner.whichChild = coin.SO_SWITCH_ALL if name in self.options_on else coin.SO_SWITCH_NONE
                sep = coin.SoSeparator()
                pts = options.get(name) or []
                if pts:
                    mat = coin.SoMaterial()
                    mat.diffuseColor = rgb
                    sep.addChild(mat)
                    coords = coin.SoCoordinate3()
                    coords.point.setValues(0, len(pts), pts)
                    sep.addChild(coords)
                    if name == "travel":
                        lines = coin.SoLineSet()
                        lines.numVertices.setValues(0, len(pts) // 2, [2] * (len(pts) // 2))
                        sep.addChild(lines)
                    else:
                        ds = coin.SoDrawStyle()
                        ds.pointSize = size
                        sep.addChild(ds)
                        sep.addChild(coin.SoPointSet())
                inner.addChild(sep)
                outer.addChild(inner)
                self.option_switches[name].append(inner)
            sw.addChild(outer)
            body.addChild(sw)
            self.switches.append(sw)
        self.option_counts = dict(P["option_counts"])
        self.palette = palette
        self.ranges = dict(P["ranges"])
        self.shown_features = set(self.stats)
        self.view_mode = "type"
        self.layers = [z + dz for z, _ in layers]
        self.raw_layers = [z for z, _ in layers]          # the slicer's own print heights (codes at a layer)
        self.lower, self.upper = 1, len(self.switches)
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        if view is None:
            return 0
        view.getSceneGraph().addChild(root)
        self.root, self.view = root, view
        self.objects = list(objects)
        for obj in objects:
            vobj = getattr(obj, "ViewObject", None)
            if vobj is not None and vobj.Visibility:
                vobj.Visibility = False
                self.hidden.append((obj.Document.Name, obj.Name))
        return len(self.switches)

    def show_option(self, name, on):
        """The slicers' Options: Travel, Retractions, Seams."""
        from pivy import coin
        for inner in self.option_switches.get(name, []):
            inner.whichChild = coin.SO_SWITCH_ALL if on else coin.SO_SWITCH_NONE
        (self.options_on.add if on else self.options_on.discard)(name)

    def tool_colour(self, tool):
        colours = self.tool_colours or []
        if 0 <= int(tool) < len(colours):
            c = QtGui.QColor(colours[int(tool)])
        else:
            c = QtGui.QColor.fromHsvF((int(tool) * 0.17) % 1.0, 0.75, 0.95)
        return (c.redF(), c.greenF(), c.blueF())

    def gradient_colour(self, mode, value):
        """Low = blue, high = red, as the slicers' Speed / Fan Speed / Temperature / Layer Height / Layer Time views."""
        lo, hi = self.ranges.get(mode, (0.0, 0.0))
        t = 0.0 if hi <= lo else max(0.0, min(1.0, (value - lo) / (hi - lo)))
        c = QtGui.QColor.fromHsvF((1.0 - t) * 0.66, 0.9, 0.95)
        return (c.redF(), c.greenF(), c.blueF())

    def speed_colour(self, feed):
        return self.gradient_colour("speed", feed)

    def set_view(self, mode):
        """"type" colours the lines by line type, the others by their value: speed, height, time, fan, temp."""
        self.view_mode = mode
        from pivy import coin
        binds = getattr(self, "_binds", [])
        for k, (mat, f, series) in enumerate(self._paint):
            bind = binds[k:k + 1]
            n = len(series["speed"])
            if mode == "type":
                cols = [self.palette[f]]
            elif mode == "tool":
                cols = [self.tool_colour(v) for v in series["tool"]]
            else:
                cols = [self.gradient_colour(mode, v) for v in series[mode]]
            if bind:
                bind[0].value = coin.SoMaterialBinding.OVERALL if len(cols) == 1 else coin.SoMaterialBinding.PER_PART
            mat.diffuseColor.setNum(len(cols))
            mat.diffuseColor.setValues(0, len(cols), cols)

    def show_feature(self, feature, on):
        from pivy import coin
        for inner in self.feature_switches.get(feature, []):
            inner.whichChild = coin.SO_SWITCH_ALL if on else coin.SO_SWITCH_NONE
        (self.shown_features.add if on else self.shown_features.discard)(feature)

    def upto(self, n):
        self.show_range(self.lower, n)

    def show_range(self, lower, upper):
        """Layers lower..upper (1-based) show, as the slicers' layer slider with its two handles."""
        from pivy import coin
        upper = max(1, min(int(upper), len(self.switches)))
        lower = max(1, min(int(lower), upper))
        self.lower, self.upper = lower, upper
        self.scrub(None)
        # only the layers that change: setting a switch (even to its own value) tells the whole scene to redraw
        # and drop its caches; a drag of the layer slider changes a few layers at a time
        ALL, NONE = coin.SO_SWITCH_ALL, coin.SO_SWITCH_NONE
        for i, sw in enumerate(self.switches):
            want = ALL if lower - 1 <= i < upper else NONE
            if sw.whichChild.getValue() != want:
                sw.whichChild = want

    def move_colour(self, seg, layer):
        """A move's colour in the current view."""
        mode = self.view_mode
        if mode == "type":
            return self.palette.get(seg[0], (0.8, 0.8, 0.8))
        if mode == "tool":
            return self.tool_colour(seg[10] if len(seg) > 10 else 0)
        h, t = self.layer_values[layer] if layer < len(self.layer_values) else (0.0, 0.0)
        value = {"speed": seg[5], "fan": seg[6] if len(seg) > 6 else 0, "temp": seg[7] if len(seg) > 7 else 0,
                 "width": seg[8] if len(seg) > 8 else 0, "flow": seg[9] if len(seg) > 9 else 0, "height": h, "time": t,
                 "timelog": math.log10(max(t, 0.1))}.get(mode, 0.0)
        return self.gradient_colour(mode, value)

    def moves_in_top(self):
        return len(self.layer_moves[self.upper - 1]) if 0 < self.upper <= len(self.layer_moves) else 0

    def move_line(self, k):
        """The G-code line number (1-based) of the top layer's k-th move (k 1-based; 0: its first), or 0."""
        if not (0 < self.upper <= len(self.layer_moves)):
            return 0
        moves = self.layer_moves[self.upper - 1]
        if not moves:
            return 0
        seg = moves[max(0, min(len(moves), int(k)) - 1)]
        return seg[5][11] if len(seg[5]) > 11 else 0

    def gcode_lines(self, centre, count=9):
        """[(line number, text)] of the shown G-code around line centre (the slicers' G-code window)."""
        if not self.gcode_path or centre <= 0:
            return []
        try:
            if self._line_starts is None:
                from array import array
                starts, pos = array("q", [0]), 0
                with open(self.gcode_path, "rb") as f:
                    for raw in f:
                        pos += len(raw)
                        starts.append(pos)
                self._line_starts = starts
            starts = self._line_starts
            last = len(starts) - 1
            first = max(1, min(centre - count // 2, last - count + 1))
            out = []
            with open(self.gcode_path, "rb") as f:
                f.seek(starts[first - 1])
                for n in range(first, min(last, first + count - 1) + 1):
                    out.append((n, f.readline().decode("utf-8", "replace").rstrip("\r\n")))
            return out
        except OSError:
            return []

    def scrub(self, k):
        """The top layer shown up to its k-th move, with the tool head there (the slicers' horizontal slider);
        None or k >= all its moves: the whole layer."""
        from pivy import coin
        if self.scrub_node is not None and self.root is not None:
            self.root.removeChild(self.scrub_node)
        self.scrub_node = None
        if self.root is None or not (0 < self.upper <= len(self.switches)):
            return
        top = self.switches[self.upper - 1]
        moves = self.layer_moves[self.upper - 1]
        if k is None or k >= len(moves):
            top.whichChild = coin.SO_SWITCH_ALL
            return
        top.whichChild = coin.SO_SWITCH_NONE
        k = max(0, int(k))
        sep = coin.SoSeparator()
        sep.setName("SWStyle_SlicerScrub")
        shown = [m for m in moves[:k] if m[5][0] in self.shown_features]
        if shown:
            coords = coin.SoCoordinate3()
            pts = [p for (x0, y0, z, x1, y1, _s) in shown for p in ((x0, y0, z), (x1, y1, z))]
            coords.point.setValues(0, len(pts), pts)
            mat = coin.SoMaterial()
            cols = [self.move_colour(m[5], self.upper - 1) for m in shown]
            mat.diffuseColor.setValues(0, len(cols), cols)
            bind = coin.SoMaterialBinding()
            bind.value = coin.SoMaterialBinding.PER_PART
            lines = coin.SoLineSet()
            lines.numVertices.setValues(0, len(shown), [2] * len(shown))
            for node in (coords, mat, bind, lines):
                sep.addChild(node)
        # the tool head: where the k-th move ends
        x0, y0, z, x1, y1, _s = moves[k - 1] if k > 0 else moves[0]
        hx, hy = (x1, y1) if k > 0 else (x0, y0)
        head = coin.SoSeparator()
        hm = coin.SoMaterial()
        hm.diffuseColor = (1.0, 1.0, 1.0)
        head.addChild(hm)
        ht = coin.SoTranslation()
        ht.translation = (hx, hy, z + 1.5)
        head.addChild(ht)
        rot = coin.SoRotationXYZ()
        rot.axis = coin.SoRotationXYZ.X
        rot.angle = 3.14159265 / 2.0
        head.addChild(rot)
        cone = coin.SoCone()
        cone.bottomRadius = 0.8
        cone.height = 3.0
        flip = coin.SoRotationXYZ()
        flip.axis = coin.SoRotationXYZ.X
        flip.angle = 3.14159265
        head.addChild(flip)
        head.addChild(cone)
        sep.addChild(head)
        self.root.addChild(sep)
        self.scrub_node = sep
        self.head = (hx, hy, z)

    def clear(self):
        if self.root is not None and self.view is not None:
            try:
                self.view.getSceneGraph().removeChild(self.root)
            except Exception as _fw_err:
                _fw_log("slicerui.py:506", _fw_err)
        self.root, self.view, self.switches, self.layers, self.objects = None, None, [], [], []
        self.layer_moves, self.layer_values, self.scrub_node, self.lower, self.upper = [], [], None, 1, 0
        self.gcode_path, self._line_starts = None, None
        self.feature_switches, self.stats, self._paint, self.shown_features = {}, {}, [], set()
        self.option_switches = {}
        for docname, name in self.hidden:
            try:
                obj = App.getDocument(docname).getObject(name)
                if obj is not None and obj.ViewObject is not None:
                    obj.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("slicerui.py:515", _fw_err)
        self.hidden = []

    @property
    def shown(self):
        return self.root is not None


# ---------------------------------------------------------------------- the PropertyManager
MESSAGE_QSS = """
QLabel#SWStyle_SlicerMessage {
    background: ${bg}; color: ${fg}; border: 1px solid ${line}; padding: 6px; border-radius: 1px;
}
"""


LABEL_W = 80        # the label column of the panel's "label  field" rows, as the PropertyManager's field rows


def _label(text):
    """A row label in the PropertyManager's label column (every row's field starts at the same place)."""
    lab = QtWidgets.QLabel(text)
    lab.setMinimumWidth(LABEL_W)
    return lab


def _same_height(field, *buttons):
    """Small buttons beside a field as tall as the field (the PropertyManager's buttons beside a list)."""
    h = field.sizeHint().height()
    for b in buttons:
        b.setFixedHeight(h)
        b.setMinimumWidth(max(h, b.sizeHint().width()))      # a worded button keeps its word ("Name...", not "...")


def _group(title, objname):
    w = QtWidgets.QWidget()
    w.setWindowTitle(title)
    w.setObjectName(objname)
    return w


class SlicerPanel:
    """FreeCAD task panel; propertymanager.py gives it the PropertyManager look."""

    current = None
    dialog = None      # the All Settings window while it is open

    def __init__(self, key):
        self.key = key
        self.slicer = backend.get(key)
        self.slicer.load()
        self.choice = default_choice(key)
        self.result = None
        self.job = None
        self.preview = Preview()
        self.bed = slicerplate.Plate()
        self.bed.paint_colours = lambda: slicerpaint.colours_of(self)
        self.bed.on_change = self._plate_changed
        self.bed.on_select = self._selected
        self.bed.on_plate_icon = self._plate_icon
        from . import slicertower
        self.bed.tower = slicertower.Tower(self)
        self.toolbar = None
        self.overlay = None
        self._filling = False
        self.widgets = {}
        # laid out as the slicers' sidebar: Prepare / Preview / Device, Printer, Filament, Process
        # with its setting tabs; then the objects on the plate and Slice
        self.all_buttons = {}
        self.form = [self._message_box(), self._mode_box(), self._printer_box(), self._filament_box(),
                     self._process_box(), self._part_box(), self._slice_box()]
        self.form[0].setProperty("swstyle_pm_title", self.slicer.title)
        slicersettings.guard_wheel(*self.form)
        self._pm_width()
        self._fill_printers()
        self._refresh_part()
        self._plate_changed()
        self.timer = QtCore.QTimer()
        self.timer.setInterval(600)
        self.timer.timeout.connect(self._refresh_part)
        self.timer.start()
        # the task panel can go without accept/reject (Gui.Control.closeDialog from outside, the document
        # closed): the timer must stop with it, or it keeps touching deleted widgets ("Internal C++
        # object (QListWidget) already deleted" on every later command; interface land277)
        self.form[0].destroyed.connect(lambda *_a: self._gone())
        self._limit_to_slicer()
        self._settings_list_shown()
        SlicerPanel.current = self

    def _pm_width(self):
        """As narrow as the other PropertyManager pages: a list sized by its longest name (a preset name runs to 40
        letters) widened the whole panel; the list opens as wide as its names instead."""
        for form in self.form:
            for combo in form.findChildren(QtWidgets.QComboBox):
                combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
                combo.setMinimumContentsLength(8)
                combo.view().setMinimumWidth(0)
                combo.view().setTextElideMode(Qt.ElideNone)
                if combo.toolTip() == "":
                    combo.currentIndexChanged.connect(lambda _i, c=combo: c.setToolTip(c.currentText()))
                    combo.setToolTip(combo.currentText())

    def _limit_to_slicer(self):
        """PrusaSlicer gets meshes with the extruder of each object and its own presets: what only Orca Slicer's and
        Bambu Studio's project files carry (per-object settings, project files, the AMS, the Bambu Lab account) is not
        shown for it, rather than shown and doing nothing. Filament slots stay, one per extruder of the printer."""
        if self.key != "prusa":
            return
        if self.slots is not None:
            self.slots.ams_button.hide()
            self.slots._count_changed()
        save = self.project_buttons.get("save")
        if save is not None:
            save.setToolTip("Save the plates' parts, with their names and extruders, as 3MF files PrusaSlicer opens "
                            "(one per plate)")
        for w in (self.account, self.project_buttons.get("open"),
                  self.all_printers):         # every printer PrusaSlicer has set up is listed
            if w is not None:
                w.hide()
        self.part_list.setContextMenuPolicy(Qt.NoContextMenu)
        table = getattr(self, "settings_table", None)
        if table is not None:
            table.hide()

    def _alive(self):
        from .widgets import alive
        return alive(self.part_list) and alive(self.preview_check)

    def _gone(self):
        """The panel's widgets were deleted under us: stop and let go."""
        try:
            self.timer.stop()
        except Exception as _fw_err:
            _fw_log("slicerui.py:588", _fw_err)
        if self.job is not None:
            try:
                self.job.cancel()
            except Exception as _fw_err:
                _fw_log("slicerui.py:593", _fw_err)
            self.job = None
        try:
            self.preview.clear()
            self._hide_toolbar()
            self.bed.hide()
        except Exception as _fw_err:
            _fw_log("slicerui.py:600", _fw_err)
        if SlicerPanel.current is self:
            SlicerPanel.current = None

    # ------------------------------------------------------------------ groups
    def _message_box(self):
        w = _group("Message", "SWStyle_SlicerMessageBox")
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        self.message = QtWidgets.QLabel()
        self.message.setObjectName("SWStyle_SlicerMessage")
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.RichText)
        lay.addWidget(self.message)
        self.get_button = QtWidgets.QPushButton("Download %s..." % self.slicer.title)
        self.get_button.setObjectName("SWStyle_SlicerGet_" + self.key)
        self.get_button.setToolTip("Opens Slicer Updates, which downloads %s from its release page." % self.slicer.title)
        self.get_button.clicked.connect(self._get_slicer)
        lay.addWidget(self.get_button)
        self.retheme()
        self._say()
        return w

    def retheme(self):
        if _dark():
            colours = {"bg": _tok("field", "#ffffe1"), "fg": _tok("field_text", "#000000"), "line": "#b8a94a"}
        else:
            colours = {"bg": "#ffffe1", "fg": "#000000", "line": "#c9bc6a"}
        qss = MESSAGE_QSS
        for k, v in colours.items():
            qss = qss.replace("${%s}" % k, v)
        self.message.setStyleSheet(qss)

    def _say(self, extra=""):
        s = self.slicer
        if not s.installed():
            # fr147: the add-on slices with its own downloaded copy only (handoff108), so there is no Find for a copy
            # installed on this computer
            text = ("<b>%s is not on this computer yet.</b><br>It is not part of the add-on: Download gets it from its "
                    "release page into the add-on's own folder (Slicer Updates). A copy installed on this computer "
                    "is not used or changed." % s.title)
            self.get_button.show()
        else:
            text = ("Slices the part here with %s's own engine and presets. The part goes to the "
                    "slicer as a STEP file. For every tool of the program itself use %s (full)." % (s.title, s.title))
            self.get_button.hide()
        if extra:
            text += "<br><br>" + extra
        self.message.setText(text)

    def _get_slicer(self):
        """Slicer Updates, where the slicer is downloaded; the panel fills in when the box closes with a copy there."""
        box = slicerupdate.open_box(Gui.getMainWindow())
        self._get_box = box
        try:
            box.finished.connect(lambda *_a: self._slicer_arrived())
        except Exception:
            pass

    def _slicer_arrived(self):
        if not self._alive() or not self.slicer.installed():
            return
        self.slicer._index = None
        self.slicer.load()
        self._say()
        self._fill_printers()

    def _part_box(self):
        """The plate: the part on the printer's bed, and the tools to place it (the slicers' Prepare)."""
        w = _group("Objects", "SWStyle_SlicerPart")
        lay = QtWidgets.QVBoxLayout(w)
        self.part_list = QtWidgets.QListWidget()
        self.part_list.setFixedHeight(84)
        # a selection box of the PropertyManager (picks in the graphics area land in it): the same light blue fill,
        # order strip and size grip as Fillet's Items To Fillet
        self.part_list.setObjectName("SWStyle_SlicerObjects")
        self.part_list.setProperty("swpickbox", True)
        self.part_list.setProperty("swActive", "true")
        self.part_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.part_list.itemSelectionChanged.connect(self._list_picked)
        self.part_list.setToolTip("The objects on the plate: pick one to select it (Ctrl adds), as clicking it "
                                  "in the graphics area does. Bodies picked in the FeatureManager tree choose "
                                  "what goes on the plate; with nothing picked: the active body, else every "
                                  "visible solid.")
        lay.addWidget(self.part_list)
        slicerobject.install(self)
        # plates (the slicers' plate tabs) and the project file, as the slicers' File menu has it
        prow = QtWidgets.QHBoxLayout()
        self.plate_pick = QtWidgets.QComboBox()
        self.plate_pick.setToolTip("The build plate the tools and Add act on; Slice shows this plate's result")
        self.plate_pick.activated.connect(lambda i: self.bed.set_current(i))
        prow.addWidget(self.plate_pick, 1)
        self.plate_buttons = {}
        for key, text, tip, slot in (
                ("add", "+", "Add a build plate", lambda: self.bed.add_plate()),
                ("delete", "\u2212", "Delete this build plate and the objects on it", self._delete_plate),
                ("rename", "Name...", "Name this build plate", self._rename_plate)):
            b = QtWidgets.QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)     # never squeezed to "..."
            b.clicked.connect(slot)
            self.plate_buttons[key] = b
            prow.addWidget(b)
            _same_height(self.plate_pick, b)
        lay.addLayout(prow)
        frow = QtWidgets.QHBoxLayout()
        self.project_buttons = {}
        for key, text, tip, slot in (
                ("add_part", "Add...", "Put a part from any open FreeCAD document on this plate", self._add_part),
                ("open", "Open 3MF...", "Open a 3MF project of Bambu Studio or Orca Slicer: its plates, "
                 "objects and settings", self.open_project),
                ("save", "Save 3MF...", "Save the plates, objects and settings as a 3MF project that "
                 "Bambu Studio and Orca Slicer open and edit", self.save_project)):
            b = QtWidgets.QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            self.project_buttons[key] = b
            frow.addWidget(b)
        lay.addLayout(frow)
        self.project_path = None

        def tool(text, tip, slot, icon=None):
            b = QtWidgets.QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setToolButtonStyle(Qt.ToolButtonTextOnly)
            b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            b.clicked.connect(slot)
            return b

        grid = QtWidgets.QGridLayout()
        grid.setSpacing(3)
        self.rot_buttons = {}
        for i, axis in enumerate("xyz"):
            b = tool("%s 90°" % axis.upper(), "Rotate the part 90° about the plate's %s axis" % axis.upper(),
                     lambda _=False, a=axis: self.bed.rotate(a, 90))
            self.rot_buttons[axis] = b
            grid.addWidget(b, 0, i)
        self.lay_button = tool("Lay on Face", "Click a face of the part in the graphics area: it goes down "
                               "onto the plate", self._lay_on_face)
        self.lay_button.setCheckable(True)
        self.auto_button = tool("Auto Orient", "Turn the part to need the least support (the slicers' "
                                "Auto orient)", lambda: self.bed.auto_orient())
        self.arrange_button = tool("Arrange", "Centre the part on the plate", lambda: self.bed.arrange())
        self.reset_place = tool("Reset", "As modelled, Z up, centred", lambda: self.bed.reset())
        grid.addWidget(self.lay_button, 1, 0, 1, 2)
        grid.addWidget(self.auto_button, 1, 2)
        grid.addWidget(self.arrange_button, 2, 0, 1, 2)
        grid.addWidget(self.reset_place, 2, 2)
        # the plate tools are on the toolbar over the graphics area now; these stay for scripts
        holder = QtWidgets.QWidget()
        holder.setLayout(grid)
        holder.hide()
        lay.addWidget(holder)
        pos = QtWidgets.QHBoxLayout()
        self.pos_x = QtWidgets.QDoubleSpinBox()
        self.pos_y = QtWidgets.QDoubleSpinBox()
        for label, box in (("X", self.pos_x), ("Y", self.pos_y)):
            box.setRange(-10000, 10000)
            box.setDecimals(1)
            box.setSuffix(" mm")
            box.setToolTip("Where the part's centre sits on the plate")
            box.editingFinished.connect(self._moved)
            pos.addWidget(QtWidgets.QLabel(label))
            pos.addWidget(box, 1)
        pos_holder = QtWidgets.QWidget()
        pos_holder.setLayout(pos)
        pos_holder.hide()
        lay.addWidget(pos_holder)
        self.fit_label = QtWidgets.QLabel()
        self.fit_label.setWordWrap(True)
        lay.addWidget(self.fit_label)
        self.orient = QtWidgets.QCheckBox()      # old "let the slicer orient": the plate does it now
        self.orient.hide()
        self.choice["orient"] = False
        return w

    def _lay_on_face(self, on=True):
        if on and self.bed.shown():
            self.bed.start_pick(lambda ok: self.lay_button.setChecked(False))
            self._say("Click the face of the part that should lie on the plate.")
        else:
            self.bed.stop_pick()
            self.lay_button.setChecked(False)
            self._say()

    def _moved(self):
        self.bed.move_to(self.pos_x.value(), self.pos_y.value())

    def _show_toolbar(self):
        """The slicers' toolbar above the plate, on the 3D view the plate is in."""
        self._hide_toolbar()
        view = self.bed.view
        host = None
        try:
            mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
            sub = mdi.activeSubWindow() if mdi is not None else None
            host = sub.widget() if sub is not None else None
        except Exception:
            host = None
        if host is None:
            return
        self.toolbar = slicertoolbar.PlateToolbar(self, host)
        from . import slicermodebar
        self.modebar = slicermodebar.ModeBar(self, host)

    def _hide_toolbar(self):
        if getattr(self, "modebar", None) is not None:
            try:
                self.modebar.remove()
            except Exception as _fw_err:
                _fw_log("slicerui.py:793", _fw_err)
            self.modebar = None
        if self.toolbar is not None:
            try:
                self.toolbar.remove()
            except Exception as _fw_err:
                _fw_log("slicerui.py:799", _fw_err)
            self.toolbar = None

    def _plate_changed(self, stale=True):
        if self.bed.tower is not None and self.bed.tower.drag is None:
            self.bed.tower.refresh()
        if self.toolbar is not None:
            self.toolbar.refresh()
        if getattr(self, "slots", None) is not None:
            self.slots.sync_selection()
        self._fill_plates()
        self._fill_part_list()
        if self.bed.mesh is None:
            self.fit_label.setText("")
            return
        box = self.bed.placed_mesh().BoundBox
        for b, v in ((self.pos_x, (box.XMin + box.XMax) / 2.0), (self.pos_y, (box.YMin + box.YMax) / 2.0)):
            b.blockSignals(True)
            b.setValue(v)
            b.blockSignals(False)
        flat, tall = self.bed.fits()
        size = "%.1f × %.1f × %.1f mm" % (box.XLength, box.YLength, box.ZLength)
        if flat and tall:
            self.fit_label.setText(size)
        else:
            self.fit_label.setText("%s  <span style='color:#c00000'>%s</span>"
                                   % (size, "Taller than the printer" if flat else "Outside the plate"))
        self._say() if not self.lay_button.isChecked() else None
        if stale:
            self._stale()

    def _selected(self):
        """An object or a plate was picked: nothing changed, the slice still holds (as in the slicers); with every plate
        sliced, the slice info and Preview follow the picked plate."""
        self._plate_changed(stale=False)
        self._show_plate_result()

    def _show_plate_result(self):
        r = self.result
        kept = (r or {}).get("kept_plates")
        if not (r and r.get("ok") and kept and r.get("out_dir")):
            return
        if self.bed.current not in kept:
            self.status.setText("Plate %d has nothing on it to slice." % (self.bed.current + 1))
            return
        k = kept.index(self.bed.current)
        if k == r.get("plate_index"):
            return
        try:
            new = backend.read_result(r["out_dir"], self.slicer, self.choice["filament"], k)
        except Exception as _fw_err:
            _fw_log("slicerui plate result", _fw_err)
            return
        if not new.get("ok"):
            return
        for key in ("seconds", "engine", "command", "exit", "out_dir", "facets", "kept_plates"):
            if key in r:
                new[key] = r[key]
        new["plate_index"] = k
        self.result = new
        global LAST_RESULT
        LAST_RESULT = (self.key, new)
        self.results.setText(slice_info_html(new, getattr(self.slots, "colours", None)))
        self.status.setText("Plate %d of the slice." % (self.bed.current + 1))
        if new.get("gcode"):
            read_ahead(new["gcode"])
        if self.preview.shown:
            self._preview_toggled(False)
            self._preview_toggled(True)

    def _printer_box(self):
        w = _group("Printer", "SWStyle_SlicerPrinter")
        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(self._setup_box())
        self.printer = QtWidgets.QComboBox()
        self.printer.setMaxVisibleItems(24)
        self.printer.currentIndexChanged.connect(self._printer_changed)
        lay.addWidget(self.printer)
        self.all_printers = QtWidgets.QCheckBox("Show all printers")
        self.all_printers.setChecked(backend.params().GetBool(self.key + "AllPrinters", False))
        self.all_printers.toggled.connect(self._all_toggled)
        lay.addWidget(self.all_printers)
        row = QtWidgets.QHBoxLayout()
        self.plate_label = _label("Plate type")
        self.plate = QtWidgets.QComboBox()
        for value, label in backend.PLATES:
            self.plate.addItem(label, value)
        self.plate.currentIndexChanged.connect(self._setting_edited)
        row.addWidget(self.plate_label)
        row.addWidget(self.plate, 1)
        lay.addLayout(row)
        lay.addLayout(self._all_button("printer"))
        # as beside the slicers' printer: the device the slice goes to, and the account login
        dev = QtWidgets.QHBoxLayout()
        dev.addWidget(_label("Device"))
        self.device = slicerdevice.DevicePicker()
        dev.addWidget(self.device, 1)
        try:
            _same_height(self.device.combo, self.device.add)
        except Exception as _fw_err:
            _fw_log("slicerui device row", _fw_err)
        lay.addLayout(dev)
        self.account = slicerdevice.AccountBar()
        lay.addWidget(self.account)
        return w

    def _filament_box(self):
        w = _group("Filament", "SWStyle_SlicerFilament")
        lay = QtWidgets.QVBoxLayout(w)
        self.filament = QtWidgets.QComboBox()
        self.filament.setMaxVisibleItems(24)
        self.filament.currentIndexChanged.connect(self._filament_changed)
        lay.addWidget(self.filament)
        self.filament_info = QtWidgets.QLabel()
        lay.addWidget(self.filament_info)
        from . import slicerslots
        self.slots = slicerslots.Slots(self)
        self.slots.changed.connect(self._slots_changed)
        lay.addWidget(self.slots)
        lay.addLayout(self._all_button("filament"))
        return w

    def _slots_changed(self):
        if self._filling:
            return
        self.choice["slots"] = self.slots.values()
        self._stale()

    def _process_box(self):
        w = _group("Process", "SWStyle_SlicerProcess")
        lay = QtWidgets.QVBoxLayout(w)
        self.process = QtWidgets.QComboBox()
        self.process.setMaxVisibleItems(24)
        self.process.currentIndexChanged.connect(self._process_changed)
        lay.addWidget(self.process)
        row = QtWidgets.QHBoxLayout()
        self.changed_label = QtWidgets.QLabel()
        self.reset = QtWidgets.QPushButton("Reset")
        self.reset.setToolTip("Back to the preset's values")
        self.reset.clicked.connect(self._reset)
        row.addWidget(self.changed_label, 1)
        row.addWidget(self.reset)
        lay.addLayout(row)
        self.tabs = slicersettings.ProcessTabs(self.key, on_change=self._tabs_edited)
        lay.addWidget(self.tabs)
        lay.addLayout(self._all_button("process"))
        return w

    def _all_button(self, tab):
        """The settings window of one preset, as the slicers' settings icon beside it."""
        row = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton("All %s Settings..." % slicersettings.TAB_TITLE[tab])
        b.setToolTip("All %d %s settings of %s, on its own pages, as in its %s settings window"
                     % (slicersettings.count(self.key, tab), slicersettings.TAB_TITLE[tab].lower(),
                        self.slicer.title, slicersettings.TAB_TITLE[tab]))
        b.clicked.connect(lambda _=False, t=tab: self.edit_all(t))
        n = QtWidgets.QLabel()
        row.addWidget(b, 1)             # full width, as the other buttons of the pane
        row.addWidget(n)
        self.all_buttons[tab] = (b, n)
        return row

    def _settings_list_shown(self):
        """PrusaSlicer's settings list comes from the user's PrusaSlicer: until there is one, no settings button and
        no empty tabs (never a control that does nothing); once it is there, the tabs are built from it."""
        tabs = getattr(self, "tabs", None)
        if tabs is not None and not tabs.pages and slicersettings.count(self.key, "process"):
            new = slicersettings.ProcessTabs(self.key, on_change=self._tabs_edited)
            holder = tabs.parentWidget()
            if holder is not None and holder.layout() is not None:
                holder.layout().replaceWidget(tabs, new)
                tabs.hide()
                tabs.deleteLater()
                slicersettings.guard_wheel(new)
                self.tabs = tabs = new
        if tabs is not None:
            tabs.setVisible(bool(tabs.pages))
        for tab, (b, n) in getattr(self, "all_buttons", {}).items():
            k = slicersettings.count(self.key, tab)
            b.setVisible(k > 0)
            b.setToolTip("All %d %s settings of %s, on its own pages, as in its %s settings window"
                         % (k, slicersettings.TAB_TITLE[tab].lower(), self.slicer.title, slicersettings.TAB_TITLE[tab]))

    def _mode_box(self):
        """The slicers' top tabs: Prepare (the plate), Preview (the toolpaths), Device (the printer)."""
        w = _group("Prepare / Preview / Device", "SWStyle_SlicerMode")
        lay = QtWidgets.QHBoxLayout(w)
        lay.setSpacing(0)
        self.mode_buttons = {}
        group = QtWidgets.QButtonGroup(w)
        group.setExclusive(True)
        for key, text, tip in (("prepare", "Prepare", "The plate: place the objects, choose the settings"),
                               ("preview", "Preview", "The sliced toolpaths, layer by layer"),
                               ("device", "Device", "The printer: live camera, state, temperatures, controls")):
            b = QtWidgets.QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setToolButtonStyle(Qt.ToolButtonTextOnly)
            b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            group.addButton(b)
            b.clicked.connect(lambda _=False, k=key: self._mode(k))
            lay.addWidget(b)
            self.mode_buttons[key] = b
        self.mode_buttons["prepare"].setChecked(True)
        return w

    def _mode(self, key):
        if key == "preview":
            if self.preview_check.isEnabled():
                self.preview_check.setChecked(True)
            else:
                self.mode_buttons["prepare"].setChecked(True)
                self.status.setText("Slice first: the preview shows the sliced toolpaths.")
        elif key == "prepare":
            self.preview_check.setChecked(False)
        elif key == "device":
            slicerdevice.DevicePanel.show_panel()
            self.mode_buttons["preview" if self.preview_check.isChecked() else "prepare"].setChecked(True)

    def _settings_box(self, title, rows):
        w = _group(title, "SWStyle_Slicer" + title)
        lay = QtWidgets.QFormLayout(w)
        lay.setLabelAlignment(Qt.AlignLeft)
        for row in rows:
            key, label, kind = row[0], row[1], row[2]
            if kind == "float":
                field = QtWidgets.QDoubleSpinBox()
                field.setDecimals(2)
                field.setRange(0.04, 1.2)
                field.setSingleStep(0.04)
                field.setSuffix(" mm")
                field.valueChanged.connect(self._setting_edited)
            elif kind in ("int", "percent"):
                field = QtWidgets.QSpinBox()
                field.setRange(0, 100 if kind == "percent" else 90 if key.endswith("angle") else 50)
                if kind == "percent":
                    field.setSuffix(" %")
                if key.endswith("angle"):
                    field.setSuffix(" °")
                field.valueChanged.connect(self._setting_edited)
            elif kind == "bool":
                field = QtWidgets.QCheckBox()
                field.toggled.connect(self._setting_edited)
            else:
                field = QtWidgets.QComboBox()
                for value, text in row[3]:
                    field.addItem(text, value)
                field.currentIndexChanged.connect(self._setting_edited)
            field.setProperty("swstyle_slicer_key", key)
            field.setProperty("swstyle_slicer_kind", kind)
            self.widgets[key] = field
            name = QtWidgets.QLabel(label)
            lay.addRow(name, field)
        return w

    def _tabs_box(self):
        """The process settings as the slicer shows them under the process preset: its tabs, every
        setting, the Advanced switch."""
        w = _group("Settings", "SWStyle_SlicerSettings")
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        self.tabs = slicersettings.ProcessTabs(self.key, on_change=self._tabs_edited)
        lay.addWidget(self.tabs)
        return w

    def _tabs_edited(self):
        if self._filling:
            return
        over = self.tabs.overrides()
        plate = self.choice["overrides"].get("curr_bed_type")
        if plate:
            over["curr_bed_type"] = plate
        self.choice["overrides"] = over
        self._changed_text()
        self._stale()

    def _all_box(self):
        """Every setting of the three presets, in the slicer's own pages."""
        w = _group("All Settings", "SWStyle_SlicerAll")
        lay = QtWidgets.QGridLayout(w)
        self.all_buttons = {}
        for i, tab in enumerate(("process", "filament", "printer")):
            b = QtWidgets.QPushButton("%s..." % slicersettings.TAB_TITLE[tab])
            b.setToolTip("All %d %s settings of %s, as in its own %s tab"
                         % (slicersettings.count(self.key, tab), slicersettings.TAB_TITLE[tab].lower(),
                            self.slicer.title, slicersettings.TAB_TITLE[tab]))
            b.clicked.connect(lambda _=False, t=tab: self.edit_all(t))
            n = QtWidgets.QLabel()
            lay.addWidget(b, i, 0)
            lay.addWidget(n, i, 1)
            self.all_buttons[tab] = (b, n)
        lay.setColumnStretch(1, 1)
        return w

    def _over_name(self, tab):
        return {"process": "overrides", "filament": "filament_overrides", "printer": "printer_overrides"}[tab]

    def _preset_of(self, tab):
        return {"process": self.choice["process"], "filament": self.choice["filament"],
                "printer": self.choice["printer"]}[tab]

    def edit_all(self, tab):
        name = self._preset_of(tab)
        if not name:
            return
        base = self.slicer.resolve(slicersettings.TAB_KIND[tab], name)
        over = dict(self.choice.get(self._over_name(tab)) or {})
        dlg = slicersettings.SettingsDialog(self.key, tab, name, base, over, Gui.getMainWindow(),
                                            title="%s: %s settings" % (self.slicer.title, slicersettings.TAB_TITLE[tab]))
        SlicerPanel.dialog = dlg
        try:
            if dlg.exec() != QtWidgets.QDialog.Accepted:
                return
            self.choice[self._over_name(tab)] = dlg.overrides()
        finally:
            SlicerPanel.dialog = None
        if tab == "process":
            self._show_values()
        self._all_counts()
        self._stale()

    def _all_counts(self):
        if not hasattr(self, "all_buttons"):
            return
        for tab, (b, n) in self.all_buttons.items():
            over = self.choice.get(self._over_name(tab)) or {}
            k = len([x for x in over if x != "curr_bed_type"])
            n.setText("<b>%d changed</b>" % k if k else "")
            n.setVisible(bool(k))           # no empty space beside the full-width button

    def _slice_box(self):
        w = _group("Slice", "SWStyle_SlicerSlice")
        lay = QtWidgets.QVBoxLayout(w)
        self.slice_button = QtWidgets.QPushButton(QtGui.QIcon(_icon("slice")), "Slice")
        self.slice_button.setToolTip("Slice the part with %s's engine" % self.slicer.title)
        self.slice_button.clicked.connect(self._slice_clicked)
        lay.addWidget(self.slice_button)
        self.export_button = QtWidgets.QPushButton(QtGui.QIcon(_icon("export")), "Export G-code...")
        self.export_button.clicked.connect(self.export)
        lay.addWidget(self.export_button)
        self.bar = QtWidgets.QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.hide()
        lay.addWidget(self.bar)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.results = QtWidgets.QLabel()
        self.results.setTextFormat(Qt.RichText)
        self.results.setWordWrap(True)
        lay.addWidget(self.results)
        self.preview_check = QtWidgets.QCheckBox("Preview")
        self.preview_check.toggled.connect(self._preview_toggled)
        lay.addWidget(self.preview_check)
        prow = QtWidgets.QHBoxLayout()
        self.layer_slider = QtWidgets.QSlider(Qt.Horizontal)
        self.layer_slider.valueChanged.connect(self._layer_moved)
        self.layer_label = QtWidgets.QLabel()
        self.layer_label.setMinimumWidth(70)
        prow.addWidget(self.layer_slider, 1)
        prow.addWidget(self.layer_label)
        lay.addLayout(prow)
        self._update_buttons()
        note = self.slicer.fallback_note()
        if note:
            self.status.setText(note)
        return w

    # ------------------------------------------------------------------ fill the lists
    def _printer_rows(self):
        s = self.slicer
        rows = s.printers()
        if self.all_printers.isChecked() or self.key == "prusa":
            return rows             # PrusaSlicer lists the printers it has set up itself
        # The vendors the slicer has set up (its data folder's system copy), else Bambu Lab's
        system = s.data_dir() / "system"
        vendors = set()
        if system.is_dir():
            vendors = {p.name for p in system.iterdir() if p.is_dir()} - {"Custom", "OrcaFilamentLibrary"}
        vendors = vendors or {"BBL"}
        keep = [p for p in rows if p.user or p.vendor in vendors or p.name == self.choice["printer"]]
        return keep or rows

    def _fill_combo(self, combo, presets, current):
        self._filling = True
        combo.blockSignals(True)
        combo.clear()
        user_done = False
        for p in presets:
            if p.user and not user_done:
                user_done = True
            combo.addItem(("★ " if p.user else "") + p.name, p.name)
            if p.user:
                combo.setItemData(combo.count() - 1, "User preset", Qt.ToolTipRole)
        i = combo.findData(current)
        combo.setCurrentIndex(i if i >= 0 else 0)
        combo.blockSignals(False)
        self._filling = False
        return combo.currentData()

    def _fill_printers(self):
        printer = self._fill_combo(self.printer, self._printer_rows(), self.choice["printer"])
        self.choice["printer"] = printer or ""
        self._fill_for_printer(keep=True)

    def _fill_for_printer(self, keep=False):
        s = self.slicer
        printer = self.choice["printer"]
        if not printer:
            return
        d = s.defaults(printer)
        fils = s.filaments(printer)
        procs = s.processes(printer)
        names_f = {p.name for p in fils}
        names_p = {p.name for p in procs}
        fil = self.choice["filament"] if keep and self.choice["filament"] in names_f else d["filament"]
        proc = self.choice["process"] if keep and self.choice["process"] in names_p else d["print"]
        self.choice["filament"] = self._fill_combo(self.filament, fils, fil) or ""
        if getattr(self, "slots", None) is not None:
            if not getattr(self, "_slots_loaded", False):
                self._slots_loaded = True
                self.slots.load(self.choice.get("slots"))
            self.slots.refill()
        self.choice["process"] = self._fill_combo(self.process, procs, proc) or ""
        self.bed.set_printer(s.resolve("machine", printer))
        bambu = s.is_bambu_printer(printer)
        self.plate_label.setVisible(bambu)
        self.plate.setVisible(bambu)
        if not keep:
            self.choice["overrides"] = {}
        self._show_values()
        self._filament_changed()

    def _show_values(self):
        """The process preset's values in the fields, the panel's changes on top."""
        s = self.slicer
        base = s.resolve("process", self.choice["process"]) if self.choice["process"] else {}
        values = dict(base)
        values.update(self.choice["overrides"])
        self._filling = True
        for key, field in self.widgets.items():
            kind = field.property("swstyle_slicer_kind")
            raw = backend._first(values.get(key, ""))
            raw = "" if raw is None else str(raw)
            field.blockSignals(True)
            try:
                if kind == "float":
                    field.setValue(float(raw or 0.2))
                elif kind == "percent":
                    field.setValue(int(round(float(raw.rstrip("%") or 15))))
                elif kind == "int":
                    field.setValue(int(round(float(raw or 0))))
                elif kind == "bool":
                    field.setChecked(raw in ("1", "true", "True"))
                else:
                    i = field.findData(raw or ("auto_brim" if key == "brim_type" else ""))
                    field.setCurrentIndex(max(0, i))
            except ValueError as _fw_err:
                _fw_log("slicerui.py:1191", _fw_err)
            field.blockSignals(False)
            self._mark(field, key in self.choice["overrides"])
        plate = self.choice["overrides"].get("curr_bed_type") or base.get("curr_bed_type") or \
            backend.params().GetString(self.key + "Plate", "Textured PEI Plate")
        self.plate.blockSignals(True)
        self.plate.setCurrentIndex(max(0, self.plate.findData(plate)))
        self.plate.blockSignals(False)
        self.bed.set_plate_type(plate)
        self._settings_list_shown()
        self.tabs.set_values(base, {k: v for k, v in self.choice["overrides"].items() if k != "curr_bed_type"})
        self._filling = False
        self._changed_text()

    def _mark(self, field, changed):
        f = field.font()
        f.setBold(changed)
        field.setFont(f)
        field.setToolTip("Changed from the preset" if changed else "")

    def _value(self, field):
        kind = field.property("swstyle_slicer_kind")
        if kind == "float":
            return "%g" % round(field.value(), 3)
        if kind == "percent":
            return "%d%%" % field.value()
        if kind == "int":
            return str(field.value())
        if kind == "bool":
            return "1" if field.isChecked() else "0"
        return field.currentData()

    def _changed_text(self):
        n = len([k for k in self.choice["overrides"] if k != "curr_bed_type"])
        self.changed_label.setText("%d setting%s changed" % (n, "" if n == 1 else "s") if n else "As the preset")
        self.reset.setVisible(n > 0)             # nothing to reset: no button (never a greyed one)
        self._all_counts()

    # ------------------------------------------------------------------ edits
    def _all_toggled(self, on):
        backend.params().SetBool(self.key + "AllPrinters", on)
        self._fill_printers()

    # ------------------------------------------------------------------ first run (the slicer's wizard, in short)
    def _needs_setup(self):
        """Orca Slicer and Bambu Studio with no printer set up yet (a new copy whose wizard never ran) and no printer
        picked in FreeCAD either. PrusaSlicer 3.0 lists every printer of its bundled vendors without a setup."""
        if self.key not in ("orca", "bambu") or saved(self.key).get("printer"):
            return False
        s = self.slicer
        try:
            return s.resources() is not None and s.first_run() and bool(s.vendors())
        except Exception as error:
            _fw_log("slicerui setup check", error)
            return False

    def _setup_box(self):
        box = QtWidgets.QFrame()
        box.setObjectName("SWStyle_SlicerSetup")
        box.setFrameShape(QtWidgets.QFrame.StyledPanel)
        v = QtWidgets.QVBoxLayout(box)
        head = QtWidgets.QLabel("<b>Set up your printer</b><br>%s has no printer set up yet. Pick yours: its printer, "
                                "filament and process settings are set up in %s as its Configuration Wizard does."
                                % (self.slicer.title, self.slicer.title))
        head.setWordWrap(True)
        v.addWidget(head)
        self.setup_vendor = QtWidgets.QComboBox()
        self.setup_vendor.setObjectName("SWStyle_SlicerSetupVendor")
        self.setup_vendor.setMaxVisibleItems(24)
        self.setup_model = QtWidgets.QComboBox()
        self.setup_model.setObjectName("SWStyle_SlicerSetupPrinter")
        self.setup_model.setMaxVisibleItems(24)
        form = QtWidgets.QFormLayout()
        form.addRow("Vendor", self.setup_vendor)
        form.addRow("Printer", self.setup_model)
        v.addLayout(form)
        row = QtWidgets.QHBoxLayout()
        self.setup_use = QtWidgets.QPushButton("Use This Printer")
        self.setup_use.clicked.connect(self._setup_use)
        self.setup_full = QtWidgets.QPushButton("Wizard in %s..." % self.slicer.title)
        self.setup_full.setToolTip("Open %s (full) in the 3D Slicer tab: its own Configuration Wizard sets up "
                                   "several printers at once" % self.slicer.title)
        self.setup_full.clicked.connect(lambda: Gui.runCommand("SWStyle_SlicerFull" + self.key.capitalize()))
        row.addWidget(self.setup_use)
        row.addWidget(self.setup_full)
        row.addStretch(1)
        v.addLayout(row)
        self.setup_box = box
        box.setVisible(False)
        if self._needs_setup():
            for folder, name in self.slicer.vendors():
                self.setup_vendor.addItem(name, folder)
            self.setup_vendor.currentIndexChanged.connect(self._setup_vendor_changed)
            self.setup_model.currentIndexChanged.connect(lambda *_: self.setup_use.setToolTip(
                "Set up %s in %s and use it here" % (self.setup_model.currentText(), self.slicer.title)))
            self._setup_vendor_changed()
            box.setVisible(self.setup_model.count() > 0)
        return box

    def _setup_vendor_changed(self, *_):
        self.setup_model.clear()
        for p in self.slicer.vendor_printers(self.setup_vendor.currentData() or ""):
            self.setup_model.addItem(p.name, p.name)

    def _setup_use(self):
        printer = self.setup_model.currentData()
        if not printer:
            return
        try:
            got = self.slicer.set_up_printer(printer)
        except Exception as error:
            self.status.setText("<span style='color:#c00000'>Could not set up %s: %s. Use the wizard in %s "
                                "instead.</span>" % (printer, error, self.slicer.title))
            return
        self.choice["printer"] = got["machine"]
        self.choice["filament"] = got["filament"]
        self.choice["process"] = got["print"]
        self._fill_printers()
        self.setup_box.hide()
        self.status.setText("%s is set up in %s, with its filament %s and process %s." % (
            got["machine"], self.slicer.title, got["filament"] or "-", got["print"] or "-"))

    def _printer_changed(self, _i=None):
        if self._filling:
            return
        self.choice["printer"] = self.printer.currentData() or ""
        self.choice["printer_overrides"] = {}
        self.choice["filament_overrides"] = {}
        self._fill_for_printer(keep=False)
        if self.key == "prusa" and self.slots is not None:
            # a printer with fewer extruders: the slots past them go (their objects back to filament 1)
            while self.slots.count() > self.slots.limit() and self.slots.rows:
                self.slots.remove(self.slots.rows[-1][2])
            self.slots._count_changed()
        self._stale()

    def _filament_changed(self, _i=None):
        if not self._filling:
            self.choice["filament"] = self.filament.currentData() or ""
            self.choice["filament_overrides"] = {}
            self._all_counts()
            self._stale()
        data = self.slicer.resolve("filament", self.choice["filament"]) if self.choice["filament"] else {}
        kind = backend._first(data.get("filament_type", "")) or ""
        temp = backend._first(data.get("nozzle_temperature", "")) or ""
        self.filament_info.setText("%s%s" % (kind, ("  ·  nozzle %s °C" % temp) if temp else ""))

    def _process_changed(self, _i=None):
        if self._filling:
            return
        self.choice["process"] = self.process.currentData() or ""
        self.choice["overrides"] = {}
        self._show_values()
        self._stale()

    def _setting_edited(self, *_):
        if self._filling:
            return
        base = self.slicer.resolve("process", self.choice["process"]) if self.choice["process"] else {}
        # changes made in All Settings to settings without a field here stay
        over = {k: v for k, v in self.choice["overrides"].items() if k not in self.widgets and k != "curr_bed_type"}
        for key, field in self.widgets.items():
            value = self._value(field)
            preset = str(backend._first(base.get(key, "")) or ("auto_brim" if key == "brim_type" else ""))
            if not _same(value, preset):
                over[key] = value
            self._mark(field, key in over)
        if self.plate.isVisible():
            self.bed.set_plate_type(self.plate.currentData())
            plate = self.plate.currentData()
            backend.params().SetString(self.key + "Plate", plate)
            if plate != (base.get("curr_bed_type") or ""):
                over["curr_bed_type"] = plate
        self.choice["overrides"] = over
        self._changed_text()
        self._stale()

    def _reset(self):
        plate = self.choice["overrides"].get("curr_bed_type")
        self.choice["overrides"] = {"curr_bed_type": plate} if plate else {}
        self._show_values()
        self._stale()

    def _flush_changed(self):
        """The Flushing volumes dialog was closed with OK."""
        self._stale()

    def _stale(self):
        """Settings changed since the last slice: its results no longer apply."""
        tower = getattr(self.bed, "tower", None)
        if tower is not None and tower.drag is None:
            tower.refresh()
        if self.result is not None:
            self.status.setText("Settings changed: slice again for new results.")

    # ------------------------------------------------------------------ the part
    def objects(self):
        # while the preview shows, the part is hidden: keep printing what was sliced
        if self.preview.shown:
            return [o for o in self.preview.objects if slicerplate.alive_object(o)]
        if self.bed.shown():
            # the model is hidden behind the plate: bodies picked in the tree still choose
            sel = [x.Object for x in Gui.Selection.getSelectionEx("", 0)]
            picked = backend.printable(selection=sel) if sel else []
            # (the plate's own objects; their document closed: what is printable now)
            return picked or [o for o in self.bed.objects if slicerplate.alive_object(o)] or backend.printable()
        return backend.printable()

    def _refresh_part(self):
        if not self._alive():
            self._gone()
            return
        objs = self.objects()
        if not objs and getattr(self.bed, "_deleted_sources", None):
            self.bed._deleted_sources.clear()  # deselecting the old source permits a later reselect
        if objs and self.project_path is None:      # an opened project keeps its own objects
            changed = self.bed.set_objects(objs)
            if not self.bed.shown() and self.bed.show():
                self.bed.fit()
                self._show_toolbar()
            elif changed:
                self._plate_changed()
        self._fill_part_list(objs)
        self._update_buttons()

    def _fill_plates(self):
        # "Plate 2 Second": the list says what it is, so no label beside it (the PropertyManager's width)
        names = ["Plate %d%s" % (i + 1, (" " + n) if n else "") for i, n in enumerate(self.bed.plates)]
        if [self.plate_pick.itemText(i) for i in range(self.plate_pick.count())] != names:
            self.plate_pick.blockSignals(True)
            self.plate_pick.clear()
            self.plate_pick.addItems(names)
            self.plate_pick.blockSignals(False)
        self.plate_pick.setCurrentIndex(self.bed.current)
        self.plate_buttons["delete"].setVisible(len(self.bed.plates) > 1)    # the last plate stays: no button

    def _plate_icon(self, i, key):
        """The icons beside each plate: Remove plate and Edit plate name ask first (after the click is over); the
        plate does the others itself."""
        if key not in ("delete", "name"):
            return False
        self.bed.set_current(i)
        QtCore.QTimer.singleShot(0, self._delete_plate if key == "delete" else self._rename_plate)
        return True

    def _delete_plate(self):
        i = self.bed.current
        n = len(self.bed.plate_items(i))
        if n and QtWidgets.QMessageBox.question(
                Gui.getMainWindow(), "Delete Plate",
                "Delete plate %d and the %d object(s) on it?" % (i + 1, n)) != QtWidgets.QMessageBox.Yes:
            return
        self.bed.delete_plate(i)

    def _rename_plate(self):
        i = self.bed.current
        name, ok = QtWidgets.QInputDialog.getText(Gui.getMainWindow(), "Plate Name", "Name of plate %d:" % (i + 1),
                                                  text=self.bed.plates[i])
        if ok:
            self.bed.plates[i] = name.strip()
            self.bed._redraw()          # the name shows beside the plate too
            self._plate_changed()

    def _add_part(self):
        """Pick a solid from any open document; it goes on the current plate."""
        rows = []
        # sl179: a part already on a plate is hidden in the graphics area while the plate shows it; it was left
        # out, so with one part open Add... said "No solid parts are open" (another copy is what Add... is for)
        placed = {tuple(it.source) for it in self.bed.items if isinstance(getattr(it, "source", None), (tuple, list))}
        for doc in App.listDocuments().values():
            for obj in doc.Objects:
                if (backend._solid(obj) and (getattr(obj, "Visibility", False) or (doc.Name, obj.Name) in placed)
                        and (obj.TypeId == "PartDesign::Body" or backend._body_of(obj) is None)):
                    rows.append(("%s  (%s)" % (obj.Label, doc.Label), obj))
        if not rows:
            self._say("No solid parts are open in FreeCAD.")
            return
        label, ok = QtWidgets.QInputDialog.getItem(Gui.getMainWindow(), "Add Part",
                                                   "Part to put on plate %d:" % (self.bed.current + 1),
                                                   [r[0] for r in rows], 0, False)
        if ok:
            self.bed.add_part(dict(rows)[label])

    def project_filter(self):
        return "3MF project (*.3mf)"

    def open_project(self, path=None):
        """A Bambu Studio / Orca Slicer project onto the plates, with its printer, filament and process."""
        from . import slicerproject
        if not path:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(Gui.getMainWindow(), "Open Project", "",
                                                            self.project_filter())
        if not path:
            return False
        QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            project = slicerproject.read_project(path)
            choice = slicerproject.choice_from_settings(self.slicer, project["settings"])
            if choice.get("printer"):
                for k in ("printer", "filament", "process"):
                    if choice.get(k):
                        self.choice[k] = choice[k]
                self._fill_printers()
                plate = self.choice["overrides"].get("curr_bed_type")
                for k in ("overrides", "filament_overrides", "printer_overrides"):
                    self.choice[k] = dict(choice.get(k) or {})
                if plate is not None and "curr_bed_type" not in self.choice["overrides"]:
                    self.choice["overrides"]["curr_bed_type"] = plate
                self._show_values()
                self._filament_changed()
            self.project_path = str(path)
            if not self.bed.shown() and self.bed.show():
                self.bed.fit()
                self._show_toolbar()
            slicerproject.apply_to_plate(self.bed, project)
        except Exception as e:
            self._say("Could not open the project: %s" % e)
            return False
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self._say("Opened %s: %d plate(s), %d object(s)." % (os.path.basename(str(path)), len(project["plates"]),
                                                          len(project["objects"])))
        self._stale()
        return True

    def save_project(self, path=None):
        """Plates, objects and settings as the slicers' own 3MF project (written by the slicer); for PrusaSlicer, the
        3MF it reads (one per plate)."""
        if not self.bed.items:
            self._say("Nothing on the plates to save.")
            return False
        if not path:
            start = self.project_path or (backend.safe_name(App.ActiveDocument.Label) + ".3mf"
                                          if App.ActiveDocument else "Project.3mf")
            path, _ = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Save Project", start,
                                                            self.project_filter())
        if not path:
            return False
        if not str(path).lower().endswith(".3mf"):
            path = str(path) + ".3mf"
        env = clean_env()
        QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
        try:

            from . import slicer3mf
            ok, msg, written = slicer3mf.write(self.key, path, env=env)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        if ok:
            self.project_path = str(path)
            if self.key == "prusa":
                self._say("Saved %s (opens in PrusaSlicer%s)." % (msg, ", one file per plate" if len(written) > 1
                                                                  else ""))
            else:
                self._say("Saved %s (opens in Bambu Studio and Orca Slicer)." % os.path.basename(str(path)))
        else:
            self._say("Could not save the project: %s" % msg)
        return ok

    def _fill_part_list(self, objs=None):
        """The objects on the plate (the slicers' object list); picking a row selects it on the plate."""
        if self.bed.items:
            many = len(self.bed.plates) > 1
            rows = [(("%d: " % (it.plate + 1) if many else "") + it.name + slicerobject.summary(it), it.source)
                    for it in self.bed.items]
        else:
            rows = [(o.Label, (o.Document.Name, o.Name)) for o in (objs if objs is not None else self.objects())]
        current = [self.part_list.item(i).text() for i in range(self.part_list.count())]
        self.part_list.blockSignals(True)
        if [r[0] for r in rows] != current:
            self.part_list.clear()
            for name, source in rows:
                item = QtWidgets.QListWidgetItem(name)
                try:
                    if isinstance(source, tuple):
                        item.setIcon(App.getDocument(source[0]).getObject(source[1]).ViewObject.Icon)
                except Exception as _fw_err:
                    _fw_log("slicerui.py:1455", _fw_err)
                self.part_list.addItem(item)
        for i in range(self.part_list.count()):
            self.part_list.item(i).setSelected(i in self.bed.selected)
        self.part_list.blockSignals(False)

    def _object_changed(self, changed):
        """An object's own settings or height ranges were edited: the list says so and the slice is stale."""
        if changed:
            self._fill_part_list()
            self._stale()

    def _list_picked(self):
        rows = {self.part_list.row(i) for i in self.part_list.selectedItems()}
        self.bed.selected = set(rows)
        self.bed._colour()
        if self.toolbar is not None:
            self.toolbar.refresh()

    def _update_buttons(self):
        if not self._alive():
            return
        # never greyed: with nothing to slice, no slicer program or no slice yet, the button says so, offers the
        # download or slices first (as the commands on the tab do); only a running slice holds them
        # the slicers' way: while slicing, the Slice button is the Cancel button; Export G-code and Preview follow the
        # running slice (after_slice)
        running = self.job is not None
        if running:
            self.slice_button.setText("Cancel")
            self.slice_button.setIcon(self.slice_button.style().standardIcon(QtWidgets.QStyle.SP_BrowserStop))
            self.slice_button.setToolTip("Stop this slice")
        else:
            self.slice_button.setText("Slice")
            self.slice_button.setIcon(QtGui.QIcon(_icon("slice")))
            self.slice_button.setToolTip("Slice the part with %s's engine" % self.slicer.title)
        # the layer slider is there while the preview shows
        self.layer_slider.setVisible(self.preview.shown)
        self.layer_label.setVisible(self.preview.shown)

    # ------------------------------------------------------------------ actions
    def _slice_clicked(self):
        if self.job is not None:
            self.cancel_slice()
        else:
            self.slice()

    def cancel_slice(self):
        """Cancel (the Slice button while a slice runs): the slice stops and nothing that waited on it follows."""
        job = self.job
        if job is None:
            return
        try:
            job.cancel()
        except Exception as _fw_err:
            _fw_log("slicerui cancel", _fw_err)
        self.after_slice = None
        self._sliced({"ok": False, "cancelled": True, "error": "Slicing was cancelled."}, job)

    def _tick(self):
        """While slicing: how long it has run, so a long slice shows it is still going (there is no time limit;
        Cancel stops it)."""
        job = self.job
        if job is None or not self._alive():
            self._busy.stop()
            return
        secs = time.monotonic() - self._busy_since
        if secs >= 2:
            self.status.setText("%s  %s" % (self._busy_text, backend.fmt_duration(secs)))

    def slice(self):
        if not self._alive():
            self._gone()
            return
        objs = self.objects()
        if self.job is not None:
            return
        if not objs and not self.bed.items:
            # never a silent button: say what is missing
            self._say_why("Nothing to slice yet: open or select a part, or use Add on the plate toolbar to put an STL, "
                          "3MF or STEP file on the plate.")
            return
        if missing_program(self.key):
            self._say_why(missing_text(self.slicer))
            if ask_download("Slice", self.key):
                Gui.runCommand("SWStyle_SlicerUpdate")
            return
        missing = [name for key, name in (("printer", "printer"), ("filament", "filament"), ("process", "process"))
                   if not self.choice.get(key)]
        if missing:
            # never a silent Slice: the slicer lists no preset of that kind (a slicer never set up yet has none)
            text = "No %s preset to slice with." % " or ".join(missing)
            if self.key == "prusa":
                text += (" PrusaSlicer lists none for this printer yet: open PrusaSlicer (full) once and pick your "
                         "printer in its Configuration Wizard, which installs the printer, print and filament "
                         "settings; they show here after that.")
            else:
                text += " Pick one in the Printer, Filament and Process boxes above."
            self._say_why(text)
            return
        self.preview_check.setChecked(False)
        self.result = None
        self.results.setText("")
        self.bar.setValue(0)
        self.bar.show()
        choice = dict(self.choice)
        if self.bed.items:
            choice["items"] = self.bed.slice_items()
            choice["plates"] = list(self.bed.plates)
            choice["plate"] = self.bed.current
            choice["slot_of"] = self.slots.slot_of()
            choice["object_params"] = [dict(it.settings) for it in self.bed.items]
            choice["object_ranges"] = [list(it.ranges) for it in self.bed.items]
            choice["object_parts"] = [([dict(p) for p in it.parts] if it.parts else None) for it in self.bed.items]
            choice["object_profile"] = [slicerlayers.profile_of(it) for it in self.bed.items]
            choice["layer_codes"] = [dict(c) for c in slicercodes.codes(self)]
            choice["layer_codes_all"] = {p: [dict(c) for c in lst] for p, lst in (getattr(self, "layer_codes", None)
                                                                                  or {}).items() if lst}
            choice["bed_box"] = self.bed.bed_box()
            choice["tower_spots"] = dict(self.bed.tower.spots) if self.bed.tower is not None else {}
            choice["object_paint"] = [({k: (dict(v) if isinstance(v, dict) else list(v)) for k, v in it.paint.items()}
                                       if it.paint else None)
                                      for it in self.bed.items]
        choice["slots"] = self.slots.values()
        # the colours of a slice with the slicer's own flushing volumes (an edited table is not the slicer's)
        self._slice_colours = list(self.slots.colours) if slicerflush.stored(self.choice, self.slots.count()) is None else None
        job = self.job = Job(self.key, objs, choice)
        job.progress.connect(self._progress)
        job.finished.connect(lambda result, job=job: self._sliced(result, job))
        self._busy_text, self._busy_since = "Slicing...", time.monotonic()
        if getattr(self, "_busy", None) is None:
            self._busy = QtCore.QTimer(self.slice_button)
            self._busy.timeout.connect(self._tick)
        self._busy.start(1000)
        self._update_buttons()
        job.start()

    def _say_why(self, text):
        """Why Slice did nothing: in the status line (in red) and the slice info box."""
        self.status.setText("<span style='color:#c00000'>%s</span>" % text)
        self.results.setText(text)

    def _progress(self, pct, text):
        if not self._alive():
            return
        self.bar.setValue(pct)
        if text:
            self._busy_text = text
            self.status.setText(text)

    def _sliced(self, result, job=None):
        if job is not None and job is not self.job:
            return                      # a cancelled slice's late word
        if not self._alive():
            self.job = None
            return
        self.job = None
        if getattr(self, "_busy", None) is not None:
            self._busy.stop()
        self.bar.hide()
        self.result = result
        global LAST_RESULT
        LAST_RESULT = (self.key, result)
        follow, self.after_slice = getattr(self, "after_slice", None), None
        if follow is not None and result.get("ok"):
            # Preview, Export G-code or Send to Printer asked for this slice: theirs follows
            QtCore.QTimer.singleShot(0, lambda: follow(self.key, result))
        if result.get("cancelled"):
            self.status.setText("Slicing was cancelled.")
            self.results.setText("")
        elif not result.get("ok"):
            text = result.get("error") or "Slicing failed."
            if len(self.slots.values()) > 1 and any(k != 1 for k in self.slots.slot_of()):
                text += (" Several filaments are used and the slicer's command line could not slice them together (some "
                         "printer profiles, Bambu Lab's among them, are refused or stop it). Use %s (full) for this "
                         "plate: Send Part, then set the filaments there." % self.slicer.title)
            self.status.setText("<span style='color:#c00000'>%s</span>" % text)
            self.results.setText("")
        else:
            # the colours the slicer worked its flushing volumes out for (the Flushing volumes dialog shows them)
            self._flush_colours = getattr(self, "_slice_colours", None)
            self.status.setText("Sliced in %.1f s%s." % (result.get("seconds", 0),
                                                         " (built-in engine)" if result.get("engine") else ""))
            self.results.setText(slice_info_html(result, getattr(self.slots, "colours", None)))
            if result.get("gcode"):
                read_ahead(result["gcode"])     # the preview's toolpaths, read while the results are looked at
        self._update_buttons()

    def export(self):
        if self.job is not None:
            # a slice is running: the export follows it
            self.after_slice = export_result
            self.results.setText("Export G-code follows when this slice is done.")
            return
        if self.result and self.result.get("ok"):
            export_result(self.key, self.result)
        else:
            after_slice("Export G-code", export_result)       # no slice yet: slice first, then export

    def _preview_toggled(self, on):
        if on and self.job is not None:
            # a slice is running: the preview shows when it is done
            self.preview_check.blockSignals(True)
            self.preview_check.setChecked(False)
            self.preview_check.blockSignals(False)
            self.after_slice = _preview_on
            self.results.setText("The preview shows when this slice is done.")
            return
        if on and not (self.result and self.result.get("ok")):
            # no slice yet: slice first, then the preview shows (the Preview tab's way)
            self.preview_check.blockSignals(True)
            self.preview_check.setChecked(False)
            self.preview_check.blockSignals(False)
            after_slice("Preview", _preview_on)
            return
        if on and self.result and self.result.get("ok"):
            QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                try:
                    self.preview.tool_colours = list(self.slots.colours)
                except Exception:
                    self.preview.tool_colours = []
                n = self.preview.show(self.result["gcode"], self.objects(), align=not self.bed.shown())
                self.bed.show_part(False)
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()
            self.layer_slider.blockSignals(True)
            self.layer_slider.setRange(1, max(1, n))
            self.layer_slider.setValue(n)
            self.layer_slider.blockSignals(False)
            self._layer_moved(n)
            self._show_overlay(n)
        else:
            self._hide_overlay()
            self.preview.clear()
            self.bed.show_part(True)
            self.layer_label.setText("")
        if self.toolbar is not None:
            # the slicers' Preview has no object toolbar (arrange, move, paint ... are Prepare's)
            if self.preview.shown:
                self.toolbar.close_tool()
            self.toolbar.setVisible(not self.preview.shown)
            for sc in self.toolbar.shortcuts:
                sc.setEnabled(not self.preview.shown)
        if getattr(self, "mode_buttons", None):        # the Prepare / Preview tabs follow
            self.mode_buttons["preview" if self.preview.shown else "prepare"].setChecked(True)
        self._update_buttons()

    def _layer_moved(self, n):
        if not self.preview.shown:
            return
        self.preview.upto(n)
        z = self.preview.layers[n - 1] if 0 < n <= len(self.preview.layers) else 0
        self.layer_label.setText("%d / %d" % (n, len(self.preview.layers)))
        self.layer_label.setToolTip("Z %.2f mm" % z)
        if self.overlay is not None:
            self.overlay.sync(n)

    def _show_overlay(self, n):
        """The slicers' legend and vertical layer slider over the 3D view."""
        self._hide_overlay()
        from . import slicerpreviewui
        host = slicerpreviewui.host_widget(Gui.getMainWindow())
        if host is None:
            return
        self.overlay = slicerpreviewui.PreviewOverlay(self, host)
        self.overlay.set_layers(len(self.preview.layers), n)

    def _hide_overlay(self):
        if self.overlay is not None:
            try:
                self.overlay.remove()
            except Exception as _fw_err:
                _fw_log("slicerui.py:1588", _fw_err)
            self.overlay = None

    # ------------------------------------------------------------------ FreeCAD task dialog
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            self.form[0].destroyed.disconnect()
        except Exception as _fw_err:
            _fw_log("slicerui.py:1599", _fw_err)
        self.timer.stop()
        if self.job is not None:
            self.job.cancel()
            self.job = None
        self._hide_overlay()
        self.preview.clear()
        self._hide_toolbar()
        self.bed.hide()
        if SlicerPanel.current is self:
            SlicerPanel.current = None

    def accept(self):
        save(self.key, self.choice)
        self._close()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self._close()
        Gui.Control.closeDialog()
        return True


def _same(a, b):
    try:
        return abs(float(str(a).rstrip("%")) - float(str(b).rstrip("%"))) < 1e-6
    except ValueError:
        return str(a) == str(b)


LAST_RESULT = None


# ---------------------------------------------------------------------- shared actions
def ensure_project(result):
    """The slice's .gcode.3mf (Bambu Lab printers are sent one): an engine slice has none, so the
    slicer's program makes it from the same files, once. Returns its path or None."""
    if result.get("project") or not result.get("command") or not result.get("out_dir"):
        return result.get("project")
    out = Path(result["out_dir"])
    QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
    try:
        proc = QtCore.QProcess()
        proc.setWorkingDirectory(str(out))
        proc.setProcessEnvironment(clean_env())
        proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        cmd = result["command"]
        proc.start(cmd[0], cmd[1:])
        proc.waitForFinished(300000)
    finally:
        QtWidgets.QApplication.restoreOverrideCursor()
    found = sorted(out.glob("*.gcode.3mf"))
    result["project"] = found[0] if found else None
    if result["project"] is None:
        App.Console.PrintWarning("3D Slicer: the slicer program made no .gcode.3mf\n")
    return result["project"]


def export_result(key, result):
    s = backend.get(key)
    project, gcode = result.get("project") or result.get("command"), result.get("gcode")
    base = backend.params().GetString("ExportFolder", str(Path.home()))
    stem = Path(result["project"]).name.replace(".gcode.3mf", "") if result.get("project") else \
        (Path(gcode).parent.name.rsplit("-", 2)[0] if gcode else "part")
    filters = []
    if project:
        filters.append("Sliced project for Bambu Lab printers (*.gcode.3mf)")
    filters.append("G-code (*.gcode)")
    path, chosen = QtWidgets.QFileDialog.getSaveFileName(
        Gui.getMainWindow(), "Export G-code", os.path.join(base, stem + (".gcode.3mf" if project else ".gcode")),
        ";;".join(filters))
    if not path:
        return None
    if path.endswith(".3mf") and project:
        project = ensure_project(result)
        if project is None:
            return None
        shutil.copy2(project, path)
    else:
        if not path.endswith(".gcode"):
            path += ".gcode"
        shutil.copy2(gcode, path)
    backend.params().SetString("ExportFolder", os.path.dirname(path))
    App.Console.PrintMessage("3D Slicer: %s G-code saved to %s\n" % (s.title, path))
    return path


def _close_print3d():
    """sl174: Print3D's PropertyManager gives way to a slicer's, as a slicer's gives way to Print3D's. True when no
    PropertyManager is open now."""
    try:
        from . import print3d
        panel = print3d.Print3DPanel.current
        if panel is not None:
            panel.reject()
            if Gui.Control.activeDialog():
                Gui.Control.closeDialog()
    except Exception as error:
        _fw_log("slicerui.py:close-print3d", error)
    return not Gui.Control.activeDialog()


def cancel_open_pm():
    """sl174: as every command since A510 (widgets pmlive): the open PropertyManager is cancelled (its Cancel) and
    the command starts. True when no PropertyManager is open now."""
    try:
        from . import pmconfirm
        pmconfirm.cancel()
        for _i in range(20):
            if not Gui.Control.activeDialog():
                break
            QtWidgets.QApplication.processEvents()
    except Exception as error:
        _fw_log("slicerui.py:cancel-pm", error)
    return not Gui.Control.activeDialog()


def busy_box(title):
    """sl174: a PropertyManager that would not close (its Cancel refused): say so in a box."""
    try:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), title, "Close the open PropertyManager first (OK or "
                                          "Cancel at its top), then click %s again." % title)
    except Exception as error:
        _fw_log("slicerui.py:busy-box", error)


def show_panel(key):
    """The slicer's PropertyManager; another slicer's panel gives way, other dialogs win."""
    backend.params().SetString("Active", key)
    panel = SlicerPanel.current
    if panel is not None:
        if panel.key == key:
            return panel
        panel.reject()
    elif Gui.Control.activeDialog():
        if not _close_print3d() and not cancel_open_pm():
            # sl174: it said so only in the Report view, so the button seemed to do nothing
            App.Console.PrintWarning("3D Slicer: close the open PropertyManager first.\n")
            busy_box(backend.get(key).title)
            return None
    panel = SlicerPanel(key)
    Gui.Control.showDialog(panel)
    return panel


# ---------------------------------------------------------------------- commands
class SlicerCommand:
    def __init__(self, key):
        self.key = key

    def GetResources(self):
        s = backend.get(self.key)
        return {"MenuText": s.title, "Pixmap": _icon(self.key),         # our own drawing, never the program's
                "ToolTip": "%s: printer, filament and process settings, slicing and sending the part "
                           "to %s." % (s.title, s.title)}

    def Activated(self):
        show_panel(self.key)

    def IsActive(self):
        return True


class SliceCommand:
    def GetResources(self):
        return {"MenuText": "Slice", "Pixmap": _icon("slice"),
                "ToolTip": "Slices the part with the chosen slicer's engine and shows print time and filament."}

    def Activated(self):
        panel = show_panel(SlicerPanel.current.key if SlicerPanel.current else last_slicer())
        if panel is not None:
            panel.slice()

    def IsActive(self):
        # never greyed (a greyed button is a dead one): with nothing to print it says so in the panel
        panel = SlicerPanel.current
        return panel is None or panel.job is None


_CAN_PRINT = []     # [(key, answer)]: FreeCAD asks IsActive on every toolbar refresh


def _can_print():
    """Something to print (the Slice button's state). backend.printable() looks at every object's
    shape, 1.9 s in a 300-component assembly asked on each refresh: the answer is kept while the
    document (asmgen's change count), the picks and the active body stay the same."""
    doc = App.ActiveDocument
    if doc is None:
        return False
    try:
        from . import asmgen
        gen = asmgen.gen(doc)
    except Exception:
        gen = -1
    try:
        picks = tuple(x.ObjectName for x in Gui.Selection.getSelectionEx("", 0))
    except Exception:
        picks = None
    try:
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        body = view.getActiveObject("pdbody") if view is not None else None
        body = body.Name if body is not None else None
    except Exception:
        body = None
    key = (doc.Name, gen, len(doc.Objects), picks, body)
    if gen != -1 and _CAN_PRINT and _CAN_PRINT[0][0] == key:
        return _CAN_PRINT[0][1]
    answer = bool(backend.printable())
    _CAN_PRINT[:] = [(key, answer)]
    return answer


def missing_text(s):
    """Why a slicer cannot slice here, in plain words: not downloaded yet, or switched off for a test run."""
    if os.environ.get("SWSTYLE_NO_SLICER") == "1":
        return "%s is switched off for this test run (SWSTYLE_NO_SLICER=1)." % s.title
    return ("%s is not on this computer yet. It is not part of the add-on: Slicer Updates (3D Slicer tab) downloads "
            "it." % s.title)


def missing_program(key):
    """True when the slicer can slice nowhere here: no program (the add-on's own download or one on this computer)
    and no built-in engine."""
    return backend.get(key).exe() is None and backend.engine(key) is None


def slice_info_html(result, colours=None):
    """The slicers' slice info: the times (prepare, model printing, total) and every filament used, with its colour,
    length, weight and cost, then the totals and the layers."""
    fmt = backend.fmt_duration
    rows = []
    if result.get("model_time") and result.get("prepare_time"):
        rows.append(("Prepare time", fmt(result["prepare_time"])))
        rows.append(("Model printing time", fmt(result["model_time"])))
    rows.append(("Print time", "<b>%s</b>" % fmt(result["time"])))
    out = "".join("<tr><td>%s</td><td colspan=3 align=right>%s</td></tr>" % r for r in rows)
    fils = result.get("filaments") or []
    cost = any(f.get("cost") for f in fils)
    out += "<tr><td></td><td align=right><i>m</i></td><td align=right><i>g</i></td>%s</tr>" % (
        "<td align=right><i>cost</i></td>" if cost else "<td></td>")
    for f in fils:
        k = int(f["slot"])
        colour = colours[k - 1] if colours and 0 < k <= len(colours) and colours[k - 1] else "#cccccc"
        out += ("<tr><td><span style='color:%s'>&#9632;</span> Filament %d</td><td align=right>%.2f</td>"
                "<td align=right>%.2f</td><td align=right>%s</td></tr>" % (
                    colour, k, f["length_mm"] / 1000.0, f["weight_g"], "%.2f" % f["cost"] if cost else ""))
    if len(fils) != 1:
        out += ("<tr><td><b>Total</b></td><td align=right><b>%.2f</b></td><td align=right><b>%.2f</b></td>"
                "<td align=right><b>%s</b></td></tr>" % (result["length_mm"] / 1000.0, result["weight_g"],
                                                         "%.2f" % result["cost"] if cost else ""))
    out += "<tr><td>Layers</td><td colspan=3 align=right>%d</td></tr>" % int(result.get("layers") or 0)
    return "<table cellspacing=0 cellpadding=1 width='100%%'>%s</table>" % out


ASKED = []      # the downloads offered in unattended runs (newest last; checks read it)


def ask_download(title, key):
    """Offers the in-app download of the slicer's program (Slicer Updates). True when the person takes it."""
    s = backend.get(key)
    if os.environ.get("SWSTYLE_NO_SLICER") == "1":
        # an unattended run: never a window to answer; checks read what would have been asked
        ASKED.append((title, s.title))
        del ASKED[:-10]
        return False
    box = QtWidgets.QMessageBox(Gui.getMainWindow())
    box.setObjectName("SWStyle_SlicerAskDownload")
    box.setWindowTitle(title)
    box.setIcon(QtWidgets.QMessageBox.Information)
    box.setText("%s needs %s's program to slice, and this computer doesn't have it yet." % (title, s.title))
    box.setInformativeText("Download it in Slicer Updates. The download stays with the add-on and doesn't change "
                           "any slicer installed on this computer.")
    go = box.addButton("Open Slicer Updates", QtWidgets.QMessageBox.AcceptRole)
    box.addButton(QtWidgets.QMessageBox.Cancel)
    box.setDefaultButton(go)
    box.exec()
    return box.clickedButton() is go


def last_ok():
    """(key, result) of the last good slice, or None."""
    panel = SlicerPanel.current
    if panel is not None and panel.result and panel.result.get("ok"):
        return panel.key, panel.result
    if panel is None and LAST_RESULT is not None and LAST_RESULT[1].get("ok"):
        return LAST_RESULT
    return None


def after_slice(title, action):
    """Runs action(key, result) on the last slice. With none yet, the plate is sliced first and the action follows,
    as the slicers' Preview tab and Print plate button do. With no slicer program, the download is offered."""
    have = last_ok()
    if have is not None:
        action(*have)
        return "done"
    panel = SlicerPanel.current
    key = panel.key if panel is not None else last_slicer()
    if panel is not None and panel.job is not None:
        panel.after_slice = action      # a slice is running: the action follows it
        return "queued"
    if missing_program(key):
        if ask_download(title, key):
            Gui.runCommand("SWStyle_SlicerUpdate")
        return "download"
    panel = show_panel(key)
    if panel is None:
        return None
    if not panel.objects() and not panel.bed.items:
        panel.status.setText("Select a part to slice, then %s." % title)
        return "nothing"
    panel.after_slice = action
    panel.slice()
    return "slicing"


def _preview_on(key, result):
    panel = SlicerPanel.current
    if panel is None:
        panel = show_panel(key)
        if panel is not None:
            panel.result = result
            panel._sliced(result)
    if panel is not None and panel.preview_check.isEnabled():
        panel.preview_check.setChecked(True)


class PreviewCommand:
    def GetResources(self):
        return {"MenuText": "Preview", "Pixmap": _icon("preview"),
                "ToolTip": "Shows the sliced toolpaths in the graphics area, layer by layer (the slicer's Preview). "
                           "With no slice yet, it slices first."}

    def Activated(self):
        panel = SlicerPanel.current
        if panel is not None and panel.preview_check.isChecked():
            panel.preview_check.setChecked(False)       # Preview again: back to the plate
            return
        after_slice("Preview", _preview_on)

    def IsActive(self):
        panel = SlicerPanel.current
        return panel is None or panel.job is None


class ExportCommand:
    def GetResources(self):
        return {"MenuText": "Export G-code", "Pixmap": _icon("export"),
                "ToolTip": "Saves the last slice as G-code, or as a sliced project for Bambu Lab printers. "
                           "With no slice yet, it slices first."}

    def Activated(self):
        after_slice("Export G-code", export_result)

    def IsActive(self):
        panel = SlicerPanel.current
        return panel is None or panel.job is None


COMMANDS = (
    ("SWStyle_SlicerOrca", lambda: SlicerCommand("orca")),
    ("SWStyle_SlicerBambu", lambda: SlicerCommand("bambu")),
    ("SWStyle_SlicerPrusa", lambda: SlicerCommand("prusa")),
    ("SWStyle_SlicerSlice", SliceCommand),
    ("SWStyle_SlicerPreview", PreviewCommand),
    ("SWStyle_SlicerExport", ExportCommand),
) + slicerdevice.COMMANDS + slicerfull.COMMANDS + slicerupdate.COMMANDS + slicerapps.COMMANDS

# catalog key, label, FreeCAD command, tip, caption
BUTTONS = (
    ("SlicerOrca", "Orca Slicer", "SWStyle_SlicerOrca",
     "Orca Slicer's printers, filaments and process settings for this part.", "Orca\nSlicer"),
    ("SlicerBambu", "Bambu Studio", "SWStyle_SlicerBambu",
     "Bambu Studio's printers, filaments and process settings for this part.", "Bambu\nStudio"),
    ("SlicerPrusa", "PrusaSlicer", "SWStyle_SlicerPrusa",
     "PrusaSlicer's printers, filaments and print settings for this part.", "Prusa\nSlicer"),
    ("SlicerSlice", "Slice", "SWStyle_SlicerSlice",
     "Slices the part with the chosen slicer's engine.", "Slice"),
    ("SlicerPreview", "Preview", "SWStyle_SlicerPreview",
     "Shows the sliced toolpaths in the graphics area, layer by layer (slices first when there is no slice yet).",
     "Preview"),
    ("SlicerExport", "Export G-code", "SWStyle_SlicerExport",
     "Saves the last slice as G-code or a sliced 3MF (slices first when there is no slice yet).", "Export\nG-code"),
)

LAYOUT = (
    ("large", "SlicerOrca", None),
    ("large", "SlicerBambu", None),
    ("large", "SlicerPrusa", None),
    ("sep",),
    ("large", "SlicerSlice", None),
    ("large", "SlicerPreview", None),
    ("large", "SlicerExport", None),
    ("sep",),
    ("large", "SlicerSend", None),
    ("large", "SlicerDevice", None),
    ("large", "SlicerAddPrinter", None),
    ("large", "SlicerLogin", None),
    ("sep",),
    ("large", "SlicerFullOrca", None),
    ("large", "SlicerFullBambu", None),
    ("large", "SlicerFullPrusa", None),
    ("large", "SlicerUpdate", None),
    ("large", "SlicerApps", None),
)


def extend_catalog():
    ""
    from . import catalog
    # our own drawings for every button (never a slicer program's own icon)
    pictures = {"SlicerOrca": _icon("orca"), "SlicerBambu": _icon("bambu"), "SlicerPrusa": _icon("prusa"),
                "SlicerSlice": _icon("slice"), "SlicerPreview": _icon("preview"), "SlicerExport": _icon("export")}
    for key, label, native, tip, caption in BUTTONS:
        if key not in catalog.BY_KEY:
            catalog.BY_KEY[key] = catalog.c(key, label, (native,), pictures[key], tip, caption=caption)
    layout = list(LAYOUT)
    added = slicerapps.layout_items(_icon("other_slicer"))           # slicers added with Slicer Apps: a button each
    if added:
        at = next((i for i, item in enumerate(layout) if len(item) > 1 and item[1] == "SlicerUpdate"), len(layout))
        layout[at:at] = added
    for key, label, native, tip, caption, picture in (slicerdevice.BUTTONS + slicerfull.BUTTONS + slicerupdate.BUTTONS
                                                       + (("SlicerApps", "Slicer Apps", "SWStyle_SlicerApps",
                                                           "Add another slicer by dropping its installer.",
                                                           "Slicer\nApps", "apps"),)):
        if key not in catalog.BY_KEY:
            catalog.BY_KEY[key] = catalog.c(key, label, (native,), _icon(picture), tip, caption=caption)
    catalog.ALL = tuple(catalog._ALL)
    tabs = [t for t in catalog.TABS if t[0] != TAB]
    at = next((i + 1 for i, t in enumerate(tabs) if t[0] == "Add-Ins"), len(tabs))
    tabs.insert(at, (TAB, tuple(layout)))
    catalog.TABS = tuple(tabs)


def register():
    have = set(Gui.listCommands())
    for name, make in COMMANDS:
        if name not in have:
            Gui.addCommand(name, make())
    extend_catalog()
    backend.warm_up()


def _on_quit():
    """FreeCAD is quitting (exit1's teardown.on_quit, before the windows go): the open slicer panel stops its timer
    and its slice, takes its mouse callbacks and nodes off the 3D view, and connected printers stop polling."""
    panel = SlicerPanel.current
    if panel is not None:
        try:
            panel._gone()
        except Exception as _fw_err:
            _fw_log("slicerui quit", _fw_err)
    try:
        import sys
        slicerprinters = sys.modules.get(__package__ + ".slicerprinters")      # extapps140: never loaded, nothing to close
        if slicerprinters is not None:
            slicerprinters.close_all()
    except Exception as _fw_err:
        _fw_log("slicerui quit printers", _fw_err)


try:
    from . import teardown as _teardown
    _teardown.on_quit(_on_quit)
except ImportError:
    pass            # without exit1's teardown module there is nothing to hook into
