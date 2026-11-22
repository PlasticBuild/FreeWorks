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

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

Qt = QtCore.Qt
KINDS = ("PartDesign::Pad", "PartDesign::Pocket", "PartDesign::Revolution", "PartDesign::Groove",
         "PartDesign::Hole")
SKIP = {"Profile", "BaseFeature", "Placement", "Shape", "Label", "Label2", "ExpressionEngine", "Visibility",
        "AddSubShape", "SuppressedShape", "_Body", "UpToFace", "UpToShape", "ReferenceAxis", "Offset",
        "AllowMultiFace", "Refine", "PreviewShape", "ShapeMaterial"}
CLIP = {"doc": None, "names": []}
GEO_EXTERNAL = -3           # sketch geometry ids at or below this are external (-1, -2: the axes)
UNDEF = -2000


def _feature(obj):
    return obj is not None and obj.TypeId in KINDS and getattr(obj, "Profile", None) is not None


def copyable_selection():
    sel = Gui.Selection.getSelectionEx("", 0)
    out = []
    for s in sel:
        obj = s.Object
        sub = s.SubElementNames[0] if s.SubElementNames else ""
        if "." in sub:                       # Body.Pad. from the tree
            for name in sub.split(".")[:-1]:
                child = obj.Document.getObject(name)
                if child is not None:
                    obj = child
            sub = sub.split(".")[-1]
        if sub:
            return []
        if not _feature(obj):
            return []
        out.append(obj)
    return out


def copy():
    feats = copyable_selection()
    if not feats:
        return False
    CLIP["doc"], CLIP["names"] = feats[0].Document.Name, [f.Name for f in feats]
    return True


def clip_features():
    try:
        doc = App.getDocument(CLIP["doc"]) if CLIP["doc"] else None
    except Exception:
        doc = None
    if doc is None:
        return []
    return [o for o in (doc.getObject(n) for n in CLIP["names"]) if _feature(o)]


def picked_face():
    """(holder object, "FaceN", feature, picked point) of one planar face picked, else None."""
    sel = Gui.Selection.getSelectionEx("", 0)
    if len(sel) != 1 or len(sel[0].SubElementNames) != 1:
        return None
    s = sel[0]
    sub = s.SubElementNames[0]
    obj = s.Object
    for name in sub.split(".")[:-1]:
        child = obj.Document.getObject(name)
        if child is not None:
            obj = child
    face_name = sub.split(".")[-1]
    if not face_name.startswith("Face"):
        return None
    point = s.PickedPoints[0] if s.PickedPoints else None
    return obj, face_name, point


def _plane(face):
    import Part
    return isinstance(face.Surface, Part.Plane)


def _body_of(obj):
    try:
        b = obj.getParentGeoFeatureGroup()
    except Exception:
        b = None
    return b if b is not None and b.TypeId == "PartDesign::Body" else None


def _keep(con):
    for k in ("First", "Second", "Third"):
        v = getattr(con, k, UNDEF)
        if UNDEF < v <= GEO_EXTERNAL:
            return False
    return True


def copy_sketch(src, body, holder, face_name, point):
    sk = body.newObject("Sketcher::SketchObject", "Sketch")
    sk.AttachmentSupport = [(holder, face_name)]
    sk.MapMode = "FlatFace"
    geos = [g.copy() for g in src.Geometry]
    sk.addGeometry(geos, False)
    for i, g in enumerate(src.Geometry):
        try:
            if src.getConstruction(i):
                sk.setConstruction(i, True)
        except Exception as _fw_err:
            _fw_log("featurecopy.py:134", _fw_err)
    cons = [c for c in src.Constraints if _keep(c)]
    if cons:
        sk.addConstraint(cons)
    doc = body.Document
    doc.recompute()
    if point is not None:
        # the profile's middle goes where the face was clicked
        try:
            bb = src.Shape.BoundBox
            local = src.getGlobalPlacement().inverse().multVec(bb.Center)
            here = sk.getGlobalPlacement().inverse().multVec(App.Vector(point))
            sk.AttachmentOffset = App.Placement(App.Vector(here.x - local.x, here.y - local.y, 0), App.Rotation())
        except Exception as error:
            App.Console.PrintLog("FreeCAD: paste position: %s\n" % error)
    return sk


def copy_feature(src, body, sketch):
    new = body.newObject(src.TypeId, src.Name.rstrip("0123456789") or "Feature")
    for p in src.PropertiesList:
        if p in SKIP or "Link" in src.getTypeIdOfProperty(p):
            continue
        if src.getEditorMode(p) and "ReadOnly" in src.getEditorMode(p):
            continue
        try:
            setattr(new, p, getattr(src, p))
        except Exception as _fw_err:
            _fw_log("featurecopy.py:162", _fw_err)
    new.Profile = sketch
    if App.GuiUp:
        try:
            sketch.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("featurecopy.py:168", _fw_err)
    return new


def _owner_face(holder, face_name, face):
    """A face picked on the Body itself belongs to its Tip. The new sketch is attached to the Tip's
    face, never to the Body: the Body's shape is the new feature's result, so a sketch on it is a
    loop, and FreeCAD then leaves the pasted feature Touched (about 2 runs in 3)."""
    if getattr(holder, "TypeId", "") != "PartDesign::Body" or holder.Tip is None:
        return holder, face_name
    tip = holder.Tip
    try:
        same = tip.Shape.getElement(face_name)
        if same.isSame(face) or (abs(same.Area - face.Area) < 1e-6
                                 and (same.CenterOfMass - face.CenterOfMass).Length < 1e-6):
            return tip, face_name
        for i, f in enumerate(tip.Shape.Faces):
            if abs(f.Area - face.Area) < 1e-6 and (f.CenterOfMass - face.CenterOfMass).Length < 1e-6:
                return tip, "Face%d" % (i + 1)
    except Exception as _fw_err:
        _fw_log("featurecopy.py:188", _fw_err)
    return holder, face_name


def paste_on(holder, face_name, point, feats=None):
    """The copied features on the face; returns the new features."""
    feats = feats if feats is not None else clip_features()
    if not feats:
        return []
    try:
        face = holder.Shape.getElement(face_name)
    except Exception:
        return []
    if not _plane(face):
        _tell("Pick a flat face for the copy.")
        return []
    holder, face_name = _owner_face(holder, face_name, face)
    body = _body_of(holder) or _body_of(feats[0])
    if body is None:
        return []
    doc = body.Document
    doc.openTransaction("Paste")
    made = []
    try:
        for i, f in enumerate(feats):
            pt = point if i == 0 else None
            sk = copy_sketch(f.Profile[0] if isinstance(f.Profile, tuple) else f.Profile, body, holder, face_name, pt)
            made.append(copy_feature(f, body, sk))
        doc.recompute()
        doc.commitTransaction()
    except Exception as error:
        doc.abortTransaction()
        _tell("The feature was not pasted: %s" % error)
        return []
    bad = [m for m in made if not m.isValid()]
    if bad:
        App.Console.PrintWarning("FreeCAD: pasted %s: %s\n" % (bad[0].Label, bad[0].getStatusString()))
    return made


def _tell(text):
    try:
        Gui.getMainWindow().statusBar().showMessage(text, 5000)
    except Exception as _fw_err:
        _fw_log("featurecopy.py:232", _fw_err)


def paste():
    got = picked_face()
    if got is None or not clip_features():
        return False
    return bool(paste_on(*got))


# --------------------------------------------------------------------------- keys and drops
def _in_part_view(obj):
    doc = App.ActiveDocument
    if doc is None or Gui.ActiveDocument is None or Gui.ActiveDocument.getInEdit() is not None:
        return False
    if isinstance(QtWidgets.QApplication.focusWidget(), (QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox,
                                                         QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit)):
        return False
    if any(o.TypeId in ("Assembly::AssemblyObject", "TechDraw::DrawPage") for o in doc.Objects):
        return False
    return True


def _key(event):
    if event.modifiers() & ~(Qt.ControlModifier | Qt.KeypadModifier) or not (event.modifiers() & Qt.ControlModifier):
        return None
    return {Qt.Key_C: "copy", Qt.Key_V: "paste"}.get(event.key())


def _tree_names(data):
    from . import fmtree
    mime = getattr(getattr(fmtree, "Model", None), "MIME", "application/x-freeworks-features")
    if not data.hasFormat(mime):
        return None
    return [n for n in bytes(data.data(mime)).decode().split("\n") if n]


def _handler(obj, event):
    t = event.type()
    if t in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress):
        what = _key(event)
        if what is None or not _in_part_view(obj):
            return False
        if what == "copy":
            if not copyable_selection():
                return False
            if t == QtCore.QEvent.ShortcutOverride:
                event.accept()
                return True
            copy()
            _tell("Copied %s: pick a flat face and press Ctrl+V." % ", ".join(f.Label for f in clip_features()))
            return True
        if picked_face() is None or not clip_features():
            return False
        if t == QtCore.QEvent.ShortcutOverride:
            event.accept()             # Ctrl+V comes here, not to FreeCAD's Paste
            return True
        paste()
        return True
    if t in (QtCore.QEvent.DragEnter, QtCore.QEvent.DragMove, QtCore.QEvent.Drop):
        if not obj.inherits("QOpenGLWidget"):
            return False
        names = _tree_names(event.mimeData())
        if not names:
            return False
        ctrl = bool(event.modifiers() & Qt.ControlModifier)
        doc = App.ActiveDocument
        feats = [o for o in (doc.getObject(n) for n in names) if _feature(o)] if doc is not None else []
        if not ctrl or not feats:
            return False
        if t == QtCore.QEvent.Drop:
            from . import designlib
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            pick, point = designlib.drop_target(obj, pos)
            if pick is not None and str(pick[1]).startswith("Face"):
                QtCore.QTimer.singleShot(0, lambda h=pick[0], f=pick[1], p=point, fs=feats: paste_on(h, f, p, fs))
        event.acceptProposedAction()
        return True
    return False


_DONE = []


def install():
    if _DONE or not App.GuiUp:
        return
    from . import events
    E = QtCore.QEvent
    events.register("featurecopy", (E.ShortcutOverride, E.KeyPress, E.DragEnter, E.DragMove, E.Drop), _handler)
    _DONE.append(True)
    try:
        for w in Gui.getMainWindow().findChildren(QtWidgets.QWidget):
            if w.inherits("QOpenGLWidget"):
                w.setAcceptDrops(True)
    except Exception as _fw_err:
        _fw_log("featurecopy.py:328", _fw_err)
