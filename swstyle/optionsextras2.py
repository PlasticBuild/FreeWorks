# SPDX-License-Identifier: LGPL-2.1-or-later
""

































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
import os
import re

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

MASS_META = "FreeWorks:SavedMassProperties"
IMPORT_MODULES = ("ImportGui", "Import", "Mesh")
MESH_EXTS = (".stl", ".obj", ".off", ".ply", ".3mf", ".amf", ".bms", ".smf", ".nas", ".bdf")
MESH_LIMIT = 50000
log = []                    # what was done, for checks


def _kept(page, text, default):
    try:
        from . import optionspages
        return optionspages.stored(page, text, default)
    except Exception as _fw_err:
        _fw_log("optionsextras2.py:63", _fw_err)
        return default


# --------------------------------------------------------------------------- import check
KNIT_LIMIT = 5000           # fh183: more loose faces than this are left as they came (sewing takes too long)


def _pieces(doc, new):
    """fh183: the loose surface pieces of an import, by the group they came in ([(group or None, [objects])]):
    new Part features with faces and no solid. A group (the reader's LinkGroup) counts only when all it holds
    is such pieces and it sits at the top of the tree; pieces at the top count when there is more than one, or
    the one holds faces that are not joined."""
    loose = [o for o in new if not o.Shape.isNull() and o.Shape.Faces and not o.Shape.Solids]
    out = []
    groups = {}
    top = []
    for o in loose:
        parents = [x for x in o.InList if x.TypeId in ("App::LinkGroup", "App::Part", "App::DocumentObjectGroup")]
        if not parents:
            top.append(o)
        elif len(parents) == 1:
            groups.setdefault(parents[0].Name, (parents[0], []))[1].append(o)
    for g, objs in groups.values():
        held = list(getattr(g, "ElementList", None) or getattr(g, "Group", None) or [])
        if g.InList or sorted(x.Name for x in held) != sorted(x.Name for x in objs):
            continue
        out.append((g, objs))
    if len(top) > 1:
        out.append((None, top))
    elif top:
        sh = top[0].Shape
        if len(sh.Faces) > sum(len(x.Faces) for x in sh.Shells):
            out.append((None, top))     # one body of faces the reader did not join
    return out


def _knit(faces, solid):
    """The faces sewn together; with solid, each closed shell made a solid. None when nothing joined."""
    import Part
    shape = Part.Compound(faces)
    try:
        shape.sewShape()
    except Exception as _fw_err:
        _fw_log("optionsextras2.py:knit", _fw_err)
        return None
    shells = shape.Shells
    if not shells or len(shells) >= len(faces):
        return None             # nothing joined
    if not solid:
        return shape
    parts = []
    for sh in shells:
        made = None
        if sh.isClosed():
            try:
                made = Part.Solid(sh)
                if made.Volume < 0:
                    made.complement()
                if not made.isValid():
                    made = None
            except Exception:
                made = None
        parts.append(made if made is not None else sh)
    loose = [f for f in shape.Faces if not any(f.isSame(g) for sh in shells for g in sh.Faces)]
    parts += loose
    return parts[0] if len(parts) == 1 else Part.Compound(parts)


def knit_imported(doc, new):
    ""



    mode = _kept("Import", "Solid and Surface", "Try forming solid(s)")
    if mode not in ("Try forming solid(s)", "Knit surface(s)"):
        return new
    for group, objs in _pieces(doc, new):
        faces = [f for o in objs for f in o.Shape.Faces]
        if len(faces) > KNIT_LIMIT:
            App.Console.PrintMessage("Import: %d surface pieces were left unknit (more than %d).\n" % (len(faces), KNIT_LIMIT))
            continue
        shape = _knit(faces, mode == "Try forming solid(s)")
        if shape is None:
            continue
        if group is None and len(objs) == 1:
            objs[0].Shape = shape       # one body: knit in place
            kind = "solid" if shape.Solids else "surface body"
            log.append(("knit", len(faces), kind))
            App.Console.PrintMessage("Import: %d surface pieces were knit into one %s.\n" % (len(faces), kind))
            continue
        body = doc.addObject("Part::Feature", "Imported")
        body.Shape = shape
        body.Label = "Imported"
        try:
            src = objs[0].ViewObject if App.GuiUp else None
            if src is not None and body.ViewObject is not None:
                body.ViewObject.ShapeColor = src.ShapeColor
        except Exception as _fw_err:
            _fw_log("optionsextras2.py:knit colour", _fw_err)
        gone = {o.Name for o in objs}
        if group is not None:
            gone.add(group.Name)
        new = [o for o in new if o.Name not in gone]
        for o in objs:
            try:
                doc.removeObject(o.Name)
            except Exception as _fw_err:
                _fw_log("optionsextras2.py:knit remove", _fw_err)
        if group is not None:
            try:
                doc.removeObject(group.Name)
            except Exception as _fw_err:
                _fw_log("optionsextras2.py:knit group", _fw_err)
        new.append(body)
        kind = "solid" if body.Shape.Solids else "surface body"
        log.append(("knit", len(faces), kind))
        App.Console.PrintMessage("Import: %d surface pieces were knit into one %s.\n" % (len(faces), kind))
    if any(o.Label == "Imported" for o in new):
        used = {o.Label for o in doc.Objects if o.Label != "Imported"}
        n = 1
        for o in new:
            if o.Label == "Imported":
                while "Imported%d" % n in used:
                    n += 1
                o.Label = "Imported%d" % n
                used.add(o.Label)
    doc.recompute()
    return new


def check_imported(doc, before):
    """The new objects of an import: knit loose surfaces, repair invalid shapes, offer Import Diagnostics."""
    new = [o for o in doc.Objects if o.Name not in before and hasattr(o, "Shape") and o.TypeId == "Part::Feature"]
    try:
        new = knit_imported(doc, new)
    except Exception as error:
        App.Console.PrintWarning("Import: the surfaces were not knit: %s\n" % error)
    _name_imported(doc, new)
    faulty = []
    for obj in new:
        shape = obj.Shape
        if shape.isNull():
            continue
        if _kept("Import", "Perform full entity check and repair errors", True) and not shape.isValid():
            fixed = shape.copy()
            try:
                fixed.fix(1e-7, 1e-7, 1e-3)
            except Exception as _fw_err:
                _fw_log("optionsextras2.py:79", _fw_err)
            if fixed.isValid():
                obj.Shape = fixed
                log.append(("repaired", obj.Label))
                App.Console.PrintMessage("Import: %s had errors and was repaired.\n" % obj.Label)
        try:
            from . import importdiag
            if importdiag.problems(obj.Shape):
                faulty.append(obj)
        except Exception as _fw_err:
            _fw_log("optionsextras2.py:89", _fw_err)
    if faulty and _kept("Import", "Automatically run Import Diagnostics - healing", True):
        log.append(("diagnostics", faulty[0].Label))
        if App.GuiUp and not os.environ.get("FREEWORKS_QUIET"):
            QtCore.QTimer.singleShot(300, lambda o=faulty[0]: _ask_diagnostics(o))
    return new


_READER_NAME = re.compile(r"^((Open CASCADE|OpenCASCADE|Open Cascade).*(translator|STEP|IGES).*|(Compound|Solid|Shell|Shape)\d*)$", re.I)


def _name_imported(doc, objs):
    ""


    used = {o.Label for o in doc.Objects}
    n = 1
    for obj in objs:
        try:
            if not _READER_NAME.match(obj.Label or ""):
                continue
            while "Imported%d" % n in used:
                n += 1
            obj.Label = "Imported%d" % n
            used.add(obj.Label)
        except Exception as _fw_err:
            _fw_log("optionsextras2.py:name_imported", _fw_err)


def mesh_to_body(mesh, solid, tolerance=0.05):
    """A Part shape from a mesh: one planar face per triangle, sewn; a solid when solid and the faces close."""
    import Part
    shape = Part.Shape()
    shape.makeShapeFromMesh(mesh.Topology, tolerance, True)
    try:
        shape.sewShape()
    except Exception as _fw_err:
        _fw_log("optionsextras2.py:sew", _fw_err)
    if solid:
        try:
            body = Part.Solid(Part.Shell(shape.Faces))
            if body.isValid() and body.Volume < 0:
                body.reverse()
            if body.isValid():
                return body
        except Exception as _fw_err:
            _fw_log("optionsextras2.py:mesh_solid", _fw_err)
    try:
        return Part.Shell(shape.Faces)
    except Exception:
        return shape


MESH_UNIT_MM = {"Millimeters": 1.0, "Centimeters": 10.0, "Meters": 1000.0, "Inches": 25.4, "Feet": 304.8}
UNITLESS_MESH = (".stl", ".obj", ".off", ".ply")


def _scale_mesh_import(doc, before, ext=None):
    ""

    factor = MESH_UNIT_MM.get(str(_kept("Import", "Unit (STL, OBJ, OFF, PLY)", "Millimeters")), 1.0)
    if factor == 1.0 or (ext is not None and ext not in UNITLESS_MESH):
        return 0
    n = 0
    for obj in [o for o in doc.Objects if o.Name not in before and o.TypeId == "Mesh::Feature"]:
        try:
            m = obj.Mesh.copy()
            mat = App.Matrix()
            mat.scale(factor, factor, factor)
            m.transform(mat)
            obj.Mesh = m
            n += 1
        except Exception as _fw_err:
            _fw_log("optionsextras2.py:mesh_unit", _fw_err)
    if n:
        App.Console.PrintMessage("Import: read in %s (Options > Import > Mesh body options > Unit).\n"
                                 % _kept("Import", "Unit (STL, OBJ, OFF, PLY)", "Millimeters"))
    return n


def check_mesh_imported(doc, before, ext=None):
    ""

    _scale_mesh_import(doc, before, ext)
    mode = str(_kept("Import", "Import as", "Graphics Body"))
    if mode not in ("Solid Body", "Surface Body"):
        return []
    made = []
    for obj in [o for o in doc.Objects if o.Name not in before and o.TypeId == "Mesh::Feature"]:
        mesh = obj.Mesh
        if mesh.CountFacets > MESH_LIMIT:
            log.append(("mesh kept", obj.Label))
            App.Console.PrintWarning("Import: %s has %d triangles, more than %d: it stays a graphics body.\n"
                                     % (obj.Label, mesh.CountFacets, MESH_LIMIT))
            continue
        shape = mesh_to_body(mesh, mode == "Solid Body")
        body = doc.addObject("Part::Feature", obj.Name + "Body")
        body.Shape = shape
        label = obj.Label
        try:
            colour = obj.ViewObject.ShapeColor if obj.ViewObject is not None else None
        except Exception:
            colour = None
        doc.removeObject(obj.Name)
        body.Label = label
        if colour is not None and body.ViewObject is not None:
            body.ViewObject.ShapeColor = colour
        kind = "solid" if shape.ShapeType == "Solid" else "surface"
        log.append(("mesh " + kind, label))
        if mode == "Solid Body" and kind != "solid":
            App.Console.PrintWarning("Import: %s is not closed, so it was made a surface body.\n" % label)
        made.append(body)
    if made:
        doc.recompute()
    return made


def _file_name(obj):
    """The imported body as the question names it: the file's name (the body's own when it has one)."""
    try:
        if obj.Label.startswith("Imported") and obj.Document.Label:
            return "%s (%s)" % (obj.Document.Label, obj.Label)
    except Exception as _fw_err:
        _fw_log("optionsextras2.py:file_name", _fw_err)
    return obj.Label


def _ask_diagnostics(obj):
    try:
        from . import importdiag
        if obj.Shape.isNull() or not importdiag.problems(obj.Shape):
            return          # the reader's later pass (Part after ImportGui) left a good solid: no question
    except Exception:
        return
    answer = QtWidgets.QMessageBox.question(
        Gui.getMainWindow(), "Import Diagnostics",
        "%s has faulty faces or gaps. Do you want to run Import Diagnostics?" % _file_name(obj),
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
    if answer == QtWidgets.QMessageBox.Yes:
        from . import importdiag
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(obj)
        importdiag.run(obj)


def _wrap(module, name):
    fn = getattr(module, name, None)
    if fn is None or getattr(fn, "_freeworks", False):
        return

    def wrapped(filename, *args, **kw):
        docname = args[0] if args else kw.get("docname")
        doc = App.getDocument(docname) if docname and docname in App.listDocuments() else None
        before = {o.Name for o in doc.Objects} if doc is not None else set()
        out = fn(filename, *args, **kw)
        try:
            ext = os.path.splitext(str(filename))[1].lower()
            if ext in (".step", ".stp", ".iges", ".igs", ".brep", ".brp"):
                target = doc or App.ActiveDocument
                if target is not None:
                    check_imported(target, before)
            elif ext in MESH_EXTS:
                target = doc or App.ActiveDocument
                if target is not None:
                    check_mesh_imported(target, before, ext)
        except Exception as error:
            App.Console.PrintLog("FreeCAD import check: %s\n" % error)
        return out
    wrapped._freeworks = True
    setattr(module, name, wrapped)


def hook_imports():
    import importlib
    for mod in IMPORT_MODULES:
        try:
            m = importlib.import_module(mod)
        except Exception:
            continue
        _wrap(m, "insert")
        _wrap(m, "open")


# --------------------------------------------------------------------------- mass properties on save
def mass_properties(doc):
    bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"] or \
        [o for o in doc.Objects if o.TypeId == "Part::Feature" and o.InList == []]
    volume = area = 0.0
    moment = App.Vector()
    for b in bodies:
        s = b.Shape
        if s.isNull() or not s.Solids:
            continue
        volume += s.Volume
        area += s.Area
        moment += s.CenterOfMass * s.Volume
    density = 1000.0
    try:
        from . import material
        density = float(material.density(doc) or density)
    except Exception as _fw_err:
        _fw_log("optionsextras2.py:167", _fw_err)
    centre = moment * (1.0 / volume) if volume else App.Vector()
    return {"volume_mm3": volume, "area_mm2": area, "mass_kg": volume * 1e-9 * density,
            "centre_mm": [centre.x, centre.y, centre.z], "density_kg_m3": density}


def store_mass_properties(doc):
    if not _kept("Performance", "Update mass properties while saving document", False):
        return None
    props = mass_properties(doc)
    meta = dict(doc.Meta)
    meta[MASS_META] = json.dumps(props)
    doc.Meta = meta
    log.append(("mass", doc.Name))
    return props


def saved_mass_properties(doc):
    try:
        return json.loads(dict(doc.Meta).get(MASS_META, "") or "null")
    except Exception:
        return None


# --------------------------------------------------------------------------- graphics
def apply_graphics():
    on = bool(_kept("Performance", "Enhanced graphics performance", True))
    App.ParamGet("User parameter:BaseApp/Preferences/View").SetBool("UseVBO", on)
    return on


# --------------------------------------------------------------------------- multi-user
def read_only(path):
    """The file can't be written by you (or has its read-only attribute)."""
    import stat
    return not os.access(path, os.W_OK) or not (os.stat(path).st_mode & stat.S_IWUSR)


class ReadOnlyWatch(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.seen = {}
        self.asked = set()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.check)
        self.restart()

    def restart(self):
        minutes = max(1, int(_kept("Collaboration", "Check files every (minutes)", 20) or 20))
        self.timer.start(minutes * 60000)

    def active(self):
        return bool(_kept("Collaboration", "Enable multi-user environment", False)) and \
            bool(_kept("Collaboration", "Check if files opened read-only have been modified by other users", False))

    def changed(self):
        """Read-only documents whose file changed since it was first seen: [doc]."""
        out = []
        for name in App.listDocuments():
            doc = App.getDocument(name)
            path = doc.FileName
            if not path or not os.path.exists(path) or not read_only(path):
                continue
            mtime = os.path.getmtime(path)
            first = self.seen.setdefault(path, mtime)
            if mtime > first + 1e-6 and path not in self.asked:
                out.append(doc)
        return out

    def check(self):
        if not self.active():
            return []
        found = self.changed()
        for doc in found:
            self.asked.add(doc.FileName)
            log.append(("modified", doc.Label))
            if App.GuiUp and not os.environ.get("FREEWORKS_QUIET"):
                self._ask(doc)
        return found

    def _ask(self, doc):
        path = doc.FileName
        answer = QtWidgets.QMessageBox.question(
            Gui.getMainWindow(), "Modified by another user",
            "%s was changed by another user since you opened it.\nReload it now?" % os.path.basename(path),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if answer == QtWidgets.QMessageBox.Yes:
            App.closeDocument(doc.Name)
            App.openDocument(path)
            self.seen[path] = os.path.getmtime(path)
            self.asked.discard(path)


# --------------------------------------------------------------------------- backups
BACKUP_DAYS = 7


def backups_of(path):
    """FreeCAD's backup files of the document at path, in its folder."""
    import re
    folder, name = os.path.split(path)
    stem, ext = os.path.splitext(name)
    if not os.path.isdir(folder or "."):
        return []
    numbered = re.compile(re.escape(name) + r"\d+$", re.I)
    fcbak = re.compile(re.escape(stem) + r"(\.[0-9-]+)?\.FCBak$", re.I)
    out = []
    for n in os.listdir(folder or "."):
        if numbered.match(n) or fcbak.match(n):
            out.append(os.path.join(folder, n))
    return out


def remove_old_backups(path, days=BACKUP_DAYS, now=None):
    """Deletes path's backups older than days. The removed paths."""
    import time
    if not _kept("Backup/Recover", "Remove backups older than 7 days", False):
        return []
    now = now or time.time()
    gone = []
    for b in backups_of(path):
        try:
            if now - os.path.getmtime(b) > days * 86400:
                os.remove(b)
                gone.append(b)
        except OSError as error:
            App.Console.PrintLog("FreeCAD: backup %s: %s\n" % (b, error))
    if gone:
        log.append(("backups", len(gone)))
        App.Console.PrintMessage("Removed %d backup(s) older than %d days of %s\n"
                                 % (len(gone), days, os.path.basename(path)))
    return gone


# --------------------------------------------------------------------------- file associations
def _exe():
    import sys
    home = App.getHomePath()
    for p in (os.path.join(home, "bin", "freecad.exe"), os.path.join(home, "bin", "FreeCAD.exe"),
              os.path.join(home, "bin", "freecad"), os.path.join(home, "bin", "FreeCAD")):
        if os.path.exists(p):
            return p
    return sys.executable


def association_plan():
    """What Restore File Associations writes: [(where, value)]."""
    exe = _exe()
    if os.name == "nt":
        cls = r"Software\Classes"
        return [(cls + r"\.FCStd", "FreeCAD.Document"),
                (cls + r"\FreeCAD.Document", "FreeCAD Document"),
                (cls + r"\FreeCAD.Document\DefaultIcon", '"%s",0' % exe),
                (cls + r"\FreeCAD.Document\shell\open\command", '"%s" "%%1"' % exe)]
    return [("xdg-mime default", "org.freecad.FreeCAD.desktop application/x-extension-fcstd")]


def restore_file_associations(dialog=None, apply=True):
    plan = association_plan()
    ok = True
    if apply:
        try:
            if os.name == "nt":
                import winreg
                for key, value in plan:
                    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
                        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, value)
                try:
                    import ctypes
                    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
                except Exception as _fw_err:
                    _fw_log("optionsextras2.py:338", _fw_err)
            else:
                import subprocess
                subprocess.call(["xdg-mime", "default", "org.freecad.FreeCAD.desktop", "application/x-extension-fcstd"])
        except Exception as error:
            ok = False
            App.Console.PrintWarning("Restore File Associations: %s\n" % error)
    log.append(("associations", ok))
    if App.GuiUp and not os.environ.get("FREEWORKS_QUIET"):
        QtWidgets.QMessageBox.information(dialog or Gui.getMainWindow(), "Restore File Associations",
                                          ".FCStd files open in this FreeCAD again." if ok else
                                          "The file associations could not be changed (see the report view).")
    return ok, plan


# --------------------------------------------------------------------------- crash check
SESSION = "SessionOpen"


def _fw():
    return App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks")


def crashed_last_time():
    return _fw().GetBool(SESSION, False)


def start_session():
    was = crashed_last_time()
    _fw().SetBool(SESSION, True)
    app = QtWidgets.QApplication.instance()
    if app is not None:
        app.aboutToQuit.connect(_end_session)
    if was and _kept("General", "Check for solutions when the program crashes", True):
        log.append(("crash", True))
        if App.GuiUp and not os.environ.get("FREEWORKS_QUIET"):
            QtCore.QTimer.singleShot(4000, crash_box)
    return was


def _end_session():
    ""

    try:
        from . import stockrestore
        if stockrestore.uninstalled():
            return
    except Exception as _fw_err:
        _fw_log("optionsextras2.py:end_session", _fw_err)
    _fw().SetBool(SESSION, False)


def crash_box():
    box = QtWidgets.QMessageBox(Gui.getMainWindow())
    box.setWindowTitle("FreeCAD")
    box.setIcon(QtWidgets.QMessageBox.Information)
    box.setText("FreeCAD did not close normally last time.")
    box.setInformativeText("FreeCAD Rx gathers what support needs; the community may already have a solution.\n"
                           "Auto-recover offers your unsaved work when FreeCAD has it.")
    rx = box.addButton("FreeCAD Rx...", QtWidgets.QMessageBox.ActionRole)
    search = box.addButton("Search the Community...", QtWidgets.QMessageBox.ActionRole)
    box.addButton(QtWidgets.QMessageBox.Close)
    box.setModal(False)

    def done(_result=None):
        if box.clickedButton() is rx:
            Gui.runCommand("SWStyle_Rx", 0)
        elif box.clickedButton() is search:
            from . import helpmenu
            helpmenu.search_community("crash FreeCAD %s" % ".".join(App.Version()[:2]))
    box.finished.connect(done)
    box.show()
    _crash_box[:] = [box]
    return box


_crash_box = []


# --------------------------------------------------------------------------- multi-user menu items
def multiuser_menus():
    return bool(_kept("Collaboration", "Enable multi-user environment", False)) and \
        bool(_kept("Collaboration", "Add shortcut menu items for multi-user environment", False))


def make_read_only(doc=None, ask=True):
    import stat
    doc = doc or App.ActiveDocument
    if doc is None or not doc.FileName:
        return False
    if ask and doc.isTouched() and App.GuiUp and not os.environ.get("FREEWORKS_QUIET"):
        answer = QtWidgets.QMessageBox.question(Gui.getMainWindow(), "Make Read-Only",
                                                "Save the changes to %s first?" % doc.Label,
                                                QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Cancel)
        if answer != QtWidgets.QMessageBox.Save:
            return False
        doc.save()
    mode = os.stat(doc.FileName).st_mode
    os.chmod(doc.FileName, mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    log.append(("readonly", doc.Label))
    if App.GuiUp:
        try:        # Lock / Make Read-Only says so, as Get Write Access does
            Gui.getMainWindow().statusBar().showMessage("%s: read-only" % doc.Label, 5000)
        except Exception as _fw_err:
            _fw_log("optionsextras2.py:430", _fw_err)
    return True


def get_write_access(doc=None):
    import stat
    doc = doc or App.ActiveDocument
    if doc is None or not doc.FileName or not os.path.exists(doc.FileName):
        return False
    os.chmod(doc.FileName, os.stat(doc.FileName).st_mode | stat.S_IWUSR)
    log.append(("writable", doc.Label))
    if App.GuiUp:
        try:
            Gui.getMainWindow().statusBar().showMessage("%s: write access" % doc.Label, 5000)
        except Exception as _fw_err:
            _fw_log("optionsextras2.py:445", _fw_err)
    return not read_only(doc.FileName)


class _FileCmd:
    def __init__(self, text, tip, run, want_ro):
        self.text, self.tip, self.run, self.want_ro = text, tip, run, want_ro

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip, "CmdType": "ForEdit"}

    def IsActive(self):
        doc = App.ActiveDocument
        return bool(doc is not None and doc.FileName and os.path.exists(doc.FileName)
                    and read_only(doc.FileName) == self.want_ro)

    def Activated(self):
        self.run()


def register():
    if not App.GuiUp:
        return
    for name, cmd in (("SWStyle_MakeReadOnly", _FileCmd("Make Read-Only", "Gives up write access to this file",
                                                        make_read_only, False)),
                      ("SWStyle_GetWriteAccess", _FileCmd("Get Write Access", "Takes write access to this file",
                                                          get_write_access, True))):
        if Gui.Command.get(name) is None:
            Gui.addCommand(name, cmd)


# --------------------------------------------------------------------------- auto-dismiss
DISMISS_WORDS = ("reference", "update", "updating", "out of date", "out-of-date")


def dismissable(box):
    if not isinstance(box, QtWidgets.QMessageBox) or len(box.buttons()) > 1:
        return False
    text = (box.text() + " " + box.informativeText()).lower()
    return any(w in text for w in DISMISS_WORDS)


def _close_if_shown(box):
    """The box may be gone by now (answered, or its parent closed): shiboken raises on it then."""
    try:
        if box.isVisible():
            box.close()
    except RuntimeError as _fw_err:
        _fw_log("optionsextras2.py:493", _fw_err)


class Dismisser(QtCore.QObject):
    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() == QtCore.QEvent.Show and isinstance(obj, QtWidgets.QMessageBox):
            if _kept("Messages/Errors/Warnings",
                     "Automatically dismiss reference and update messages after 10 seconds", True) and dismissable(obj):
                log.append(("dismiss", obj.text()[:40]))
                QtCore.QTimer.singleShot(DISMISS_MS, lambda b=obj: _close_if_shown(b))
        return False


DISMISS_MS = 10000


# --------------------------------------------------------------------------- auto-recover folder
def recover_folder():
    text = str(_kept("Backup/Recover", "Auto-recover folder", "") or "")
    return text if text and os.path.isdir(text) else ""


def copy_recovery(folder=None):
    """Each open document's auto-recover data copied to folder/<document>/. The documents copied."""
    import shutil
    folder = folder or recover_folder()
    if not folder:
        return []
    done = []
    for name in App.listDocuments():
        doc = App.getDocument(name)
        src = getattr(doc, "TransientDir", "")
        if not src or not os.path.isdir(src):
            continue
        files = [f for f in os.listdir(src) if f.startswith("fc_recovery")]
        if not files:
            continue
        dst = os.path.join(folder, doc.Name)
        os.makedirs(dst, exist_ok=True)
        for f in files:
            p = os.path.join(src, f)
            if os.path.isdir(p):
                shutil.copytree(p, os.path.join(dst, f), dirs_exist_ok=True)
            else:
                shutil.copy2(p, os.path.join(dst, f))
        done.append(doc.Name)
    return done


# --------------------------------------------------------------------------- open edges
OPEN_EDGE_COLOR = (0.35, 0.65, 1.0)
_edge_colors = {}           # (doc, obj) -> the LineColorArray before we coloured it


def _open_edge_color():
    try:
        from . import optionspages
        return optionspages.kept_color("Surfaces, Open Edges", OPEN_EDGE_COLOR)
    except Exception:
        return OPEN_EDGE_COLOR


_SURF = {}          # (doc, obj) -> (shape key, is a surface body); a big drawing asks hundreds of times


def _shape_key(s):
    """The inner shape: obj.Shape gives a new copy on every read, but its hashCode is the same
    until the object is rebuilt."""
    try:
        return (s.hashCode(), s.ShapeType)
    except Exception:
        return None


_SOLID_ONLY = ("PartDesign::FeatureAddSub", "PartDesign::DressUp", "PartDesign::Transformed", "PartDesign::Boolean")


def _surface(obj):
    try:
        if any(obj.isDerivedFrom(t) for t in _SOLID_ONLY):
            return False    # extapps/70: always a solid; reading its Shape copies it (2 ms each on a big part)
        s = obj.Shape
        if s.isNull():
            return False
        key = (obj.Document.Name, obj.Name)
        k = _shape_key(s)
        hit = _SURF.get(key)
        if hit is not None and k is not None and hit[0] == k:
            return hit[1]
        if s.ShapeType == "Solid":
            result = False
        else:
            result = bool(s.Faces) and not s.Solids
        _SURF[key] = (k, result)
        return result
    except Exception:
        return False


_OPEN_DONE = {}     # (doc, obj) -> (shape key, line colour, open colour) last coloured


def apply_open_edges(doc):
    """Colours or restores open edges on doc's surface bodies. The objects coloured."""
    if not App.GuiUp or doc is None:
        return []
    on = bool(_kept("Display", "Show open edges of surfaces in different color", True))
    done = []
    from . import importdiag
    for obj in doc.Objects:
        key = (doc.Name, obj.Name)
        vo = getattr(obj, "ViewObject", None)
        if vo is None or "LineColorArray" not in vo.PropertiesList:
            continue
        if not on or not _surface(obj):
            if key in _edge_colors:
                _OPEN_DONE.pop(key, None)
                try:
                    vo.LineColorArray = _edge_colors.pop(key)
                except Exception as _fw_err:
                    _fw_log("optionsextras2.py:610", _fw_err)
            continue
        shape = obj.Shape
        base = tuple(vo.LineColor)[:3]
        colour = _open_edge_color()
        mark = (_shape_key(shape), base, tuple(colour)[:3])
        if _OPEN_DONE.get(key) == mark and key in _edge_colors:
            done.append(obj.Name)          # already coloured for this very shape
            continue
        opens = importdiag.open_edges(shape)
        if not opens:
            _OPEN_DONE.pop(key, None)
            continue
        if key not in _edge_colors:
            _edge_colors[key] = list(vo.LineColorArray)
        arr = []
        for e in shape.Edges:
            arr.append(colour if any(e.isSame(o) for o in opens) else base)
        vo.LineColorArray = arr
        _OPEN_DONE[key] = mark
        done.append(obj.Name)
    return done


# --------------------------------------------------------------------------- selection through transparency
THROUGH = 10                # percent
_through = set()            # (doc, obj) made unselectable here
PICKABLE = set()            # (doc, obj) a page shows see-through to be clicked (Trim Surface pieces)


def _shift():
    return bool(QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.ShiftModifier)


_rotor = [0]


def _tick_docs():
    """The 1.5 s check: the active document and one other in turn, so a build of hundreds of part
    documents costs one or two documents a tick, not all of them (Shift, save and Options still do all)."""
    names = list(App.listDocuments())
    if not names:
        return []
    out = []
    active = App.ActiveDocument
    if active is not None:
        out.append(active)
    _rotor[0] = (_rotor[0] + 1) % len(names)
    other = App.getDocument(names[_rotor[0]])
    if other is not None and other is not active:
        out.append(other)
    return out


def _body_like(obj):
    ""


    try:
        if obj.isDerivedFrom("Part::Part2DObject") or obj.isDerivedFrom("Part::Datum") \
                or obj.isDerivedFrom("App::OriginFeature") or obj.isDerivedFrom("App::Origin"):
            return False
        shape = getattr(obj, "Shape", None)
        return shape is None or bool(shape.Faces)
    except Exception:
        return True


def apply_through(doc=None, tick=False):
    """Transparent bodies let picks through (unselectable in the view) unless Shift is held."""
    if not App.GuiUp:
        return []
    on = bool(_kept("Selection", "Enable selection through transparency", True)) and not _shift()
    if doc is not None:
        docs = [doc]
    elif tick:
        docs = _tick_docs()
    else:
        docs = [App.getDocument(n) for n in App.listDocuments()]
    now = []
    for d in docs:
        for obj in d.Objects:
            vo = getattr(obj, "ViewObject", None)
            if vo is None or "Transparency" not in vo.PropertiesList or "Selectable" not in vo.PropertiesList:
                continue
            key = (d.Name, obj.Name)
            if key in PICKABLE:
                if key in _through:
                    vo.Selectable = True
                    _through.discard(key)
                continue
            want = on and vo.Visibility and vo.Transparency >= THROUGH and _body_like(obj)
            if want and vo.Selectable and key not in _through:
                vo.Selectable = False
                _through.add(key)
            elif not want and key in _through:
                vo.Selectable = True
                _through.discard(key)
            if key in _through:
                now.append(obj.Name)
    return now


def unmark(doc):
    """Our view-only marks off for doc (before a save)."""
    for key in [k for k in _through if k[0] == doc.Name]:
        obj = doc.getObject(key[1])
        if obj is not None and obj.ViewObject is not None:
            obj.ViewObject.Selectable = True
        _through.discard(key)
    for key in [k for k in _edge_colors if k[0] == doc.Name]:
        obj = doc.getObject(key[1])
        old = _edge_colors.pop(key)
        if obj is not None and obj.ViewObject is not None:
            try:
                obj.ViewObject.LineColorArray = old
            except Exception as _fw_err:
                _fw_log("optionsextras2.py:713", _fw_err)


class _ShiftWatch(QtCore.QObject):
    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease) and \
                event.key() == QtCore.Qt.Key_Shift and not event.isAutoRepeat():
            QtCore.QTimer.singleShot(0, lambda: _safe_through())
        return False


def _safe_through(tick=False):
    try:
        apply_through(tick=tick)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: selection through transparency: %s\n" % error)


class _Watch:
    def slotRecomputedDocument(self, doc):
        QtCore.QTimer.singleShot(0, lambda d=doc: _safe_open_edges(d))

    def slotStartSaveDocument(self, doc, filename):
        unmark(doc)
        try:
            from . import configmanager
            configmanager.save_display_data(doc)
        except Exception as _fw_err:
            _fw_log("optionsextras2.py:743", _fw_err)
        try:
            store_mass_properties(doc)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: mass properties on save: %s\n" % error)

    def slotFinishSaveDocument(self, doc, filename):
        QtCore.QTimer.singleShot(0, lambda d=doc: (_safe_through(), _safe_open_edges(d)))
        try:
            from . import tessave          # Image Quality > Save tessellation with part document
            tessave.after_save(doc, filename or doc.FileName)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: save tessellation: %s\n" % error)
        try:
            remove_old_backups(filename or doc.FileName)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: old backups: %s\n" % error)


_installed = []


def install():
    if _installed:
        return _installed[0]
    hook_imports()
    watch = _Watch()
    App.addDocumentObserver(watch)
    ro = ReadOnlyWatch()
    register()
    try:
        from . import docstyle         # part Document Properties applied to the part
        docstyle.install()
    except Exception as error:
        App.Console.PrintLog("FreeCAD docstyle: %s\n" % error)
    from . import events           # the add-on's one application filter (interface land263)
    dismiss = Dismisser()
    events.register("optionsextras2-dismiss", (QtCore.QEvent.Show,), dismiss.eventFilter)
    shift = _ShiftWatch()
    events.register("optionsextras2-shift", (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease), shift.eventFilter)
    through = QtCore.QTimer()
    through.timeout.connect(lambda: _safe_through(True))
    through.start(1500)
    recover = QtCore.QTimer()
    minutes = App.ParamGet("User parameter:BaseApp/Preferences/Document").GetInt("AutoSaveTimeout", 15) or 15
    recover.timeout.connect(lambda: _safe_copy())
    recover.start(max(1, minutes) * 60000 + 5000)
    try:
        start_session()
    except Exception as _fw_err:
        _fw_log("optionsextras2.py:793", _fw_err)
    try:
        apply_graphics()
    except Exception as _fw_err:
        _fw_log("optionsextras2.py:797", _fw_err)
    _installed.append({"watch": watch, "readonly": ro, "dismiss": dismiss, "recover": recover,
                       "shift": shift, "through": through})
    return _installed[0]


def _safe_open_edges(doc):
    try:
        name = doc.Name
    except Exception:
        return              # the document closed before the timer fired
    try:
        if name in App.listDocuments():
            apply_open_edges(doc)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: open edges: %s\n" % error)


def _safe_copy():
    try:
        copy_recovery()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: auto-recover folder: %s\n" % error)


def refresh():
    """After the Options box is saved."""
    try:
        apply_graphics()
        _safe_through()
        if App.ActiveDocument is not None:
            _safe_open_edges(App.ActiveDocument)
            from . import docstyle
            docstyle._safe(docstyle.apply_all, App.ActiveDocument)
        if _installed:
            _installed[0]["readonly"].restart()
    except Exception as error:
        App.Console.PrintLog("FreeCAD options2: %s\n" % error)
