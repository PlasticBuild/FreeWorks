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
from PySide import QtCore, QtGui, QtWidgets

Qt = QtCore.Qt
QE = QtCore.QEvent
SEEN = 0.75                      # Ctrl+Shift+Alt: hidden faces drawn see-through, not gone
T_HIDDEN = "Face hidden. Shift+Alt+click picks hidden faces, Esc shows them again."

# (doc name, object name) -> {"orig": appearance tuple, "faces": set of 0-based face indices, "modified": bool}
_hidden = {}
_state = {"seen": False, "swallow": False, "timer": None, "eat_release": False}


def _sketch_edit():
    try:
        from . import contextbar
        return contextbar.sketch_in_edit() is not None
    except Exception:
        return False


def active():
    """Alt hides faces only while a command's PropertyManager (task dialog) is open, outside sketch edit."""
    try:
        return Gui.Control.activeDialog() and not _sketch_edit()
    except Exception:
        return False


def hidden():
    """[(doc name, object name, "FaceN")] of the faces hidden now."""
    return sorted((d, o, "Face%d" % (i + 1)) for (d, o), e in _hidden.items() for i in e["faces"])


def is_hidden(doc, obj, sub):
    e = _hidden.get((doc, obj))
    if not e or not sub:
        return False
    leaf = sub.split(".")[-1]
    return leaf.startswith("Face") and leaf[4:].isdigit() and int(leaf[4:]) - 1 in e["faces"]


def _faces(obj):
    try:
        return len(obj.Shape.Faces)
    except Exception:
        return 0


def _copy(m):
    c = App.Material()
    for k in ("AmbientColor", "DiffuseColor", "SpecularColor", "EmissiveColor", "Shininess", "Transparency"):
        try:
            setattr(c, k, getattr(m, k))
        except Exception as _fw_err:
            _fw_log("altface.py:78", _fw_err)
    return c


def _apply(doc, name):
    e = _hidden.get((doc, name))
    d = App.getDocument(doc) if doc in App.listDocuments() else None
    obj = d.getObject(name) if d is not None else None
    if e is None or obj is None or obj.ViewObject is None:
        return
    n = _faces(obj)
    orig = list(e["orig"])
    mats = [orig[i] if i < len(orig) else orig[-1] for i in range(n)] if orig else []
    out = []
    for i, m in enumerate(mats):
        if i in e["faces"]:
            m = _copy(m)
            m.Transparency = SEEN if _state["seen"] else 1.0
        out.append(m)
    gdoc = Gui.getDocument(doc)
    was = gdoc.Modified
    try:
        obj.ViewObject.ShapeAppearance = out if any(i in e["faces"] for i in range(n)) else e["orig"]
    finally:
        gdoc.Modified = was


def hide(doc, name, sub):
    """Hides face sub ("FaceN") of doc.name for now. True when it is hidden."""
    leaf = (sub or "").split(".")[-1]
    if not (leaf.startswith("Face") and leaf[4:].isdigit()):
        return False
    d = App.getDocument(doc) if doc in App.listDocuments() else None
    obj = d.getObject(name) if d is not None else None
    if obj is None or obj.ViewObject is None or not hasattr(obj.ViewObject, "ShapeAppearance"):
        return False
    i = int(leaf[4:]) - 1
    if not 0 <= i < _faces(obj):
        return False
    e = _hidden.setdefault((doc, name), {"orig": tuple(obj.ViewObject.ShapeAppearance), "faces": set()})
    e["faces"].add(i)
    _apply(doc, name)
    try:
        Gui.Selection.clearPreselection()
        Gui.getMainWindow().statusBar().showMessage(T_HIDDEN, 4000)
    except Exception as _fw_err:
        _fw_log("altface.py:124", _fw_err)
    return True


def show_all():
    """Brings every hidden face back. True when there were any."""
    if not _hidden:
        return False
    for (doc, name), e in list(_hidden.items()):
        try:
            d = App.getDocument(doc)
            obj = d.getObject(name)
            if obj is not None and obj.ViewObject is not None:
                gdoc = Gui.getDocument(doc)
                was = gdoc.Modified
                obj.ViewObject.ShapeAppearance = e["orig"]
                gdoc.Modified = was
        except Exception as _fw_err:
            _fw_log("altface.py:142", _fw_err)
    _hidden.clear()
    _state["seen"] = False
    return True


def _set_seen(on):
    if bool(on) == _state["seen"] or not _hidden:
        return
    _state["seen"] = bool(on)
    for doc, name in list(_hidden):
        _apply(doc, name)


def _view():
    try:
        v = Gui.ActiveDocument.ActiveView
        return v if hasattr(v, "getObjectsInfo") else None
    except Exception:
        return None


def picks(widget, pos):
    """Every pick under pos (Qt pixels of the 3D viewport), front first."""
    v = _view()
    if v is None:
        return []
    try:
        dpr = widget.devicePixelRatioF()
        return v.getObjectsInfo((int(pos.x() * dpr), int((widget.height() - pos.y()) * dpr))) or []
    except Exception:
        return []


def _is_viewport(obj):
    try:
        p = obj.parent()
        return p is not None and p.metaObject().className() == "Gui::View3DInventorViewer"
    except Exception:
        return False


def _select(info, add):
    if not add:
        Gui.Selection.clearSelection()
    doc = info.get("Document")
    obj = info.get("ParentObject") or info.get("Object")
    sub = info.get("SubName") or info.get("Component") or ""
    Gui.Selection.addSelection(doc, obj, sub, info.get("x", 0.0), info.get("y", 0.0), info.get("z", 0.0))


def click(widget, pos, mods):
    """A left click on the viewport with faces hidden. True when it was handled here (the press is eaten)."""
    infos = picks(widget, pos)
    if not infos:
        return False
    top = infos[0]
    if not is_hidden(top.get("Document"), top.get("Object"), top.get("Component")):
        return False
    add = bool(mods & Qt.ControlModifier)
    if mods & Qt.ShiftModifier and mods & Qt.AltModifier:
        _select(top, add)                       # Shift+Alt+click: the hidden face itself
        return True
    for info in infos[1:]:
        if not is_hidden(info.get("Document"), info.get("Object"), info.get("Component")):
            _select(info, add)
            return True
    if not add:
        Gui.Selection.clearSelection()          # nothing behind it: a click on empty space
    return True


def _pointer_face():
    """(doc, object, sub) under the pointer, from FreeCAD's preselection (by name: its Object can be stale)."""
    try:
        pre = Gui.Selection.getPreselection()
        names = list(pre.SubElementNames) if pre is not None else []
        if not names or not pre.ObjectName:
            return None
        doc = App.getDocument(pre.DocumentName)
        obj = doc.getObject(pre.ObjectName)
        sub = names[0]
        if obj is None:
            return None
        if "." in sub:                           # a link or body path: hide on the leaf's own object
            try:
                leaf_obj = obj.getSubObject(sub, retType=1)
                if leaf_obj is not None:
                    obj = leaf_obj
            except Exception as _fw_err:
                _fw_log("altface.py:232", _fw_err)
        return obj.Document.Name, obj.Name, sub.split(".")[-1]
    except Exception:
        return None


def _cursor(widget):
    return widget.mapFromGlobal(QtGui.QCursor.pos())


def _face_at_pointer(widget):
    """The face under the pointer: FreeCAD's preselection, else a pick where the pointer is."""
    face = _pointer_face()
    if face is not None or widget is None:
        return face
    pos = _cursor(widget)
    if not widget.rect().contains(pos):
        return None
    for info in picks(widget, pos):
        comp = info.get("Component") or ""
        if comp.startswith("Face"):
            return info.get("Document"), info.get("Object"), comp
        break
    return None


def _viewport_now():
    try:
        from . import instant3d
        return instant3d._viewport()
    except Exception:
        return None


_KEY_MOD = {Qt.Key_Control: Qt.ControlModifier, Qt.Key_Shift: Qt.ShiftModifier, Qt.Key_Alt: Qt.AltModifier}


def _effective(event):
    """The modifiers held once this key event is through: some platforms leave the key's own modifier out
    of its press (and in on its release)."""
    mods = event.modifiers()
    own = _KEY_MOD.get(event.key())
    if own is not None:
        mods = mods | own if event.type() == QE.KeyPress else mods & ~own
    return mods


def _on_event(obj, event):
    t = event.type()
    if t in (QE.KeyPress, QE.KeyRelease):
        mods = event.modifiers()
        three = Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier
        if t == QE.KeyPress and event.key() == Qt.Key_Escape and _hidden:
            show_all()
            return True                          # this Esc only brings the faces back (the next one cancels)
        if _hidden:
            _set_seen((_effective(event) & three) == three)
        if t == QE.KeyPress and event.key() == Qt.Key_Alt and not event.isAutoRepeat() \
                and mods in (Qt.AltModifier, Qt.NoModifier) and active():
            face = _face_at_pointer(obj if _is_viewport(obj) else _viewport_now())
            if face is not None and hide(*face):
                _state["swallow"] = True
                return True                      # no menu-bar focus for this Alt
        if t == QE.KeyRelease and event.key() == Qt.Key_Alt and _state["swallow"]:
            _state["swallow"] = False
            return True
        return False
    if t == QE.MouseButtonPress and _hidden and event.button() == Qt.LeftButton and _is_viewport(obj):
        _state["eat_release"] = click(obj, event.pos(), event.modifiers())
        return _state["eat_release"]
    if t == QE.MouseButtonRelease and event.button() == Qt.LeftButton and _state.get("eat_release"):
        _state["eat_release"] = False            # FreeCAD picks on the release: it must not see this one
        return True
    if t == QE.MouseMove and _hidden and _is_viewport(obj):
        QtCore.QTimer.singleShot(0, _drop_hidden_preselection)
    return False


def _drop_hidden_preselection():
    try:
        face = _pointer_face()
        if face is not None:
            if face is not None and is_hidden(*face):
                Gui.Selection.clearPreselection()
    except Exception as _fw_err:
        _fw_log("altface.py:317", _fw_err)


def _watch():
    if _hidden and not active():
        show_all()                               # the PropertyManager closed


def install():
    if _state["timer"] is not None:
        return
    from . import events
    events.register("altface", (QE.KeyPress, QE.KeyRelease, QE.MouseButtonPress, QE.MouseButtonRelease, QE.MouseMove), _on_event)
    for t in (QE.KeyPress, QE.KeyRelease):         # ahead of the PropertyManager's Esc = Cancel
        lst = events._BY_TYPE.get(t, [])
        mine = [h for h in lst if h[0] == "altface"]
        lst[:] = mine + [h for h in lst if h[0] != "altface"]
    t = QtCore.QTimer(QtWidgets.QApplication.instance())
    t.setObjectName("FW_AltFaceWatch")
    t.timeout.connect(_watch)
    t.start(300)
    _state["timer"] = t


def remove():
    show_all()
    try:
        from . import events
        events.unregister("altface")
    except Exception as _fw_err:
        _fw_log("altface.py:347", _fw_err)
    if _state["timer"] is not None:
        _state["timer"].stop()
        _state["timer"] = None
