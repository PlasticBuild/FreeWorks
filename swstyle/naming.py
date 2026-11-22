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

import re

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore
except ImportError:    # FreeCAD without its interface
    Gui = QtCore = None


FEATURE_NAMES = {
    "Sketcher::SketchObject": "Sketch",
    "PartDesign::Pad": "Boss-Extrude",
    "PartDesign::Pocket": "Cut-Extrude",
    "PartDesign::Revolution": "Revolve",
    "PartDesign::Groove": "Cut-Revolve",
    "PartDesign::AdditivePipe": "Sweep",
    "PartDesign::SubtractivePipe": "Cut-Sweep",
    "PartDesign::AdditiveLoft": "Loft",
    "PartDesign::SubtractiveLoft": "Cut-Loft",
    "PartDesign::AdditiveHelix": "Helix-Boss",
    "PartDesign::SubtractiveHelix": "Helix-Cut",
    "PartDesign::Hole": "Hole",
    "PartDesign::Fillet": "Fillet",
    "PartDesign::Chamfer": "Chamfer",
    "PartDesign::Draft": "Draft",
    "PartDesign::Thickness": "Shell",
    "PartDesign::Mirrored": "Mirror",
    "PartDesign::LinearPattern": "LPattern",
    "PartDesign::PolarPattern": "CirPattern",
    "PartDesign::MultiTransform": "Pattern",
    "PartDesign::Scaled": "Scale",
    "PartDesign::Boolean": "Combine",
    "PartDesign::Plane": "Plane",
    "PartDesign::Line": "Axis",
    "PartDesign::Point": "Point",
    "PartDesign::CoordinateSystem": "Coordinate System",
    # an assembly's reference geometry (body-less datums, asmrefgeom.py): Plane1, Axis1 as in a part
    "Part::DatumPlane": "Plane",
    "Part::DatumLine": "Axis",
    "Part::DatumPoint": "Point",
    "Part::LocalCoordinateSystem": "Coordinate System",
}



PLANE_NAMES = {
    "XY_Plane": "Top Plane",
    "XZ_Plane": "Front Plane",
    "YZ_Plane": "Right Plane",
}

_observer = None


def install():
    """Start naming new features. Safe to call more than once."""
    global _observer
    if _observer is None:
        _observer = _Observer()
        App.addDocumentObserver(_observer)
        for doc in App.listDocuments().values():
            rename_defaults(doc)


def uninstall():
    global _observer
    if _observer is not None:
        try:
            App.removeDocumentObserver(_observer)
        except Exception as _fw_err:
            _fw_log("naming.py:99", _fw_err)
        _observer = None


def next_label(doc, prefix):
    """prefix + one more than the highest number already used in doc."""
    pattern = re.compile(r"^%s(\d+)$" % re.escape(prefix))
    used = 0
    for obj in doc.Objects:
        match = pattern.match(obj.Label)
        if match:
            used = max(used, int(match.group(1)))
    return "%s%d" % (prefix, used + 1)


def _default_label(obj):
    """True when obj still carries the label FreeCAD gave it."""
    if obj.TypeId == "App::Plane":
        role = getattr(obj, "Role", "")
        return obj.Label in (role, role.replace("_Plane", "-plane"))
    base = re.sub(r"\d+$", "", obj.Name)
    return re.fullmatch(r"%s\d*" % re.escape(base), obj.Label) is not None


def _numbered(label, prefix):
    return re.fullmatch(r"%s[1-9]\d*" % re.escape(prefix), label) is not None


def _tree_order(doc):
    """Objects of doc, each body's features in their tree order."""
    seen, out = set(), []
    for obj in doc.Objects:
        group = obj.Group if obj.TypeId == "PartDesign::Body" else [obj]
        for item in group:
            if item.Name not in seen:
                seen.add(item.Name)
                out.append(item)
    return out


def rename_defaults(doc):
    ""

    if _observer is None or _restoring(doc):
        return
    renames = []
    for obj in _tree_order(doc):
        if obj.TypeId == "App::Plane":
            name = PLANE_NAMES.get(getattr(obj, "Role", ""))
            if name is not None and obj.Label != name and _default_label(obj):
                renames.append((obj, name))
            continue
        name = FEATURE_NAMES.get(obj.TypeId)

        if name is not None and not _numbered(obj.Label, name) and _default_label(obj):
            renames.append((obj, name))
    pending = {obj.Name for obj, _ in renames}
    used = {}
    for obj in doc.Objects:
        for prefix in set(name for _, name in renames):
            if obj.Name not in pending and _numbered(obj.Label, prefix):
                used[prefix] = max(used.get(prefix, 0), int(obj.Label[len(prefix):]))
    if not renames:
        return
    gui = None
    try:
        gui = Gui.getDocument(doc.Name) if Gui is not None else None
        clean = gui is not None and not gui.Modified
    except Exception:
        clean = False
    for obj, name in renames:
        if obj.TypeId != "App::Plane":
            used[name] = used.get(name, 0) + 1
            name = "%s%d" % (name, used[name])
        _observer._set(obj, name)
    if clean:
        try:
            gui.Modified = False
        except Exception as _fw_err:
            _fw_log("naming.py:178", _fw_err)


def _restoring(doc):
    try:
        return bool(doc.Restoring)
    except Exception:
        return True  # Unknown state: leave names alone.


class _Observer:
    def __init__(self):
        self.busy = False

    def slotCreatedObject(self, obj):
        prefix = FEATURE_NAMES.get(obj.TypeId)
        if prefix is None or self.busy:
            return
        doc = obj.Document
        # A fresh object carries its Name as Label; anything else came from a
        # file, a paste or an undo and keeps what it has.
        if _restoring(doc) or obj.Label != obj.Name:
            return
        self._set(obj, next_label(doc, prefix))

    def slotActivateDocument(self, doc):
        # FreeCAD 1.1 tells Python observers nothing when a file finishes opening; an opened
        # file becomes the active one. Wait for its view providers so its clean state is kept.
        name = doc.Name
        if QtCore is None:
            return
        QtCore.QTimer.singleShot(0, lambda: _later(name))

    def slotChangedObject(self, obj, prop):
        # FreeCAD gives a new origin's planes their label ("XY-plane") and then
        # their Role right after creating them; rename once both are set.
        if prop not in ("Label", "Role") or self.busy or obj.TypeId != "App::Plane":
            return
        name = PLANE_NAMES.get(getattr(obj, "Role", ""))
        if name is None or _restoring(obj.Document):
            return
        if obj.Label == obj.Role.replace("_Plane", "-plane"):
            self._set(obj, name)

    def _set(self, obj, label):
        self.busy = True
        try:
            obj.Label = label
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: could not name %s (%s)\n" % (obj.Name, error))
        finally:
            self.busy = False


def _later(name):
    doc = App.listDocuments().get(name)
    if doc is not None:
        rename_defaults(doc)
