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

import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

PLANES = ("PartDesign::Plane", "App::Plane")
_state = {"observer": None, "swaps": 0, "press": 0.0}


def _on_press(obj, event):
    """A left click in a 3D view: picks in the next moment come from it (a pick from the tree is left alone)."""
    try:
        if event.button() == QtCore.Qt.LeftButton and obj.inherits("QOpenGLWidget"):
            _state["press"] = time.time()
    except Exception as _fw_err:
        _fw_log("pickprio:press", _fw_err)
    return False


def _in_view():
    return time.time() - _state["press"] < 1.0


def _resolve(doc, name, sub):
    """The object a selection names and its element (Body.Sketch.Edge1 -> Sketch, Edge1)."""
    try:
        d = App.getDocument(doc)
        obj = d.getObject(name)
        if obj is None:
            return None, ""
        if sub:
            got = obj.getSubObject(sub, retType=1)
            leaf = sub.split(".")[-1]
            if got is not None:
                return got, leaf
        return obj, sub or ""
    except Exception:
        return None, ""


def _is_whole_plane(obj, element):
    return obj is not None and getattr(obj, "TypeId", "") in PLANES and element in ("", "Plane", "Face1")


def _wanted(pre, plane, faces=False):
    """The preselection to take instead of the plane: an edge or vertex of another object (with faces, also a
    model face), else None."""
    if pre is None:
        return None
    doc, name, sub = pre
    obj, element = _resolve(doc, name, sub)
    if obj is None or obj is plane or getattr(obj, "TypeId", "") in PLANES:
        return None
    if element.startswith("Face"):
        if not (faces and _on_plane(obj, element, plane)):
            return None
    elif not (element.startswith("Edge") or element.startswith("Vertex")):
        return None
    return doc, name, sub


def _on_plane(obj, element, plane):
    """True when the face is flat and lies in the plane (a plane drawn on the model's face). A face behind the plane
    is not under it: there the plane is picked, as before."""
    try:
        face = obj.Shape.getElement(element)
        if face.Surface.TypeId != "Part::GeomPlane":
            return False
        where = plane.getGlobalPlacement()
        normal = where.Rotation.multVec(App.Vector(0, 0, 1))
        owner = obj.getParentGeoFeatureGroup()
        frame = owner.getGlobalPlacement() if owner is not None else App.Placement()
        tol = max(1e-6, 1e-7 * face.BoundBox.DiagonalLength)
        return all(abs((frame.multVec(v.Point) - where.Base).dot(normal)) <= tol for v in face.Vertexes)
    except Exception as _fw_err:
        _fw_log("pickprio:on plane", _fw_err)
        return False


BORDER_PX = 6       # how near the plane's outline a click picks the plane itself


def _outline(plane):
    """The four corners of the plane as it is drawn (its view's rectangle), in the document's coordinates."""
    try:
        from pivy import coin
        search = coin.SoSearchAction()
        search.setType(coin.SoCoordinate3.getClassTypeId())
        search.setInterest(coin.SoSearchAction.ALL)
        search.apply(plane.ViewObject.RootNode)
        where = plane.getGlobalPlacement()
        for i in range(search.getPaths().getLength()):
            node = search.getPaths().get(i).getTail()
            if len(node.point) >= 4:
                return [where.multVec(App.Vector(*node.point[j].getValue())) for j in range(4)]
    except Exception as _fw_err:
        _fw_log("pickprio:outline", _fw_err)
    return []


def _on_border(doc, plane, pnt):
    ""
    corners = _outline(plane)
    if len(corners) < 4 or pnt is None:
        return False
    try:
        view = Gui.getDocument(doc).ActiveView
        dpr = Gui.getMainWindow().devicePixelRatioF()
        at = view.getPointOnScreen(App.Vector(*pnt))
        pts = [view.getPointOnScreen(c) for c in corners]
    except Exception as _fw_err:
        _fw_log("pickprio:border", _fw_err)
        return False
    px, py = at[0], at[1]
    for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1]):
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        t = 0.0 if length == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
        if ((ax + t * dx - px) ** 2 + (ay + t * dy - py) ** 2) ** 0.5 <= BORDER_PX * dpr:
            return True
    return False


def _preselection():
    try:
        p = Gui.Selection.getPreselection()
        if p is None or not p.ObjectName:
            return None
        sub = p.SubElementNames[0] if p.SubElementNames else ""
        return p.DocumentName, p.ObjectName, sub
    except Exception:
        return None


def _under(doc, pnt):
    """What else lies under the click point, nearest first: (document, object, sub) for each pick there. The plane
    and a sketch on it are at the same depth, so which of them FreeCAD's click takes varies from spot to spot."""
    out = []
    try:
        gdoc = Gui.getDocument(doc)
        view = gdoc.ActiveView if gdoc is not None else None
        if view is None or pnt is None or not hasattr(view, "getObjectsInfo"):
            return out
        x, y = view.getPointOnScreen(App.Vector(*pnt))
        for r in (0, 2, -2, 4, -4):
            for dx, dy in ((r, 0), (0, r)) if r else ((0, 0),):
                for info in view.getObjectsInfo((int(x + dx), int(y + dy))) or ():
                    parent = info.get("ParentObject")
                    if parent is not None and info.get("SubName"):
                        out.append((info.get("Document", doc), parent.Name, info["SubName"]))
                    elif info.get("Object"):
                        out.append((info.get("Document", doc), info["Object"], info.get("Component", "")))
    except Exception as _fw_err:
        _fw_log("pickprio:under", _fw_err)
    return out


def _swap(doc, name, sub, want, pnt):
    try:
        Gui.Selection.removeSelection(doc, name, sub)
        wd, wn, ws = want
        if pnt is not None:
            Gui.Selection.addSelection(wd, wn, ws, pnt[0], pnt[1], pnt[2])
        else:
            Gui.Selection.addSelection(wd, wn, ws)
        _state["swaps"] += 1
    except Exception as _fw_err:
        _fw_log("pickprio:swap", _fw_err)


class _Observer:
    def addSelection(self, doc, name, sub, pnt):
        try:
            obj, element = _resolve(doc, name, sub)
            if not _is_whole_plane(obj, element) or not _in_view():
                return
            gdoc = Gui.getDocument(doc)
            if gdoc is not None and gdoc.getInEdit() is not None:
                return              # a sketch or feature in edit picks its own way

            faces = not _on_border(doc, obj, pnt)
            want = _wanted(_preselection(), obj, faces)
            if want is None:
                for cand in _under(doc, pnt):
                    want = _wanted(cand, obj, faces)
                    if want is not None:
                        break
            if want is None:
                return
            # not inside FreeCAD's own selection call: a moment later
            QtCore.QTimer.singleShot(0, lambda: _swap(doc, name, sub, want, pnt))
        except Exception as _fw_err:
            _fw_log("pickprio:add", _fw_err)


def install():
    if _state["observer"] is not None:
        return
    _state["observer"] = _Observer()
    Gui.Selection.addObserver(_state["observer"])
    from . import events
    events.register("pickprio", (QtCore.QEvent.MouseButtonPress,), _on_press)
