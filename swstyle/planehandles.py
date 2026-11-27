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

from . import paths

PARAM = "PlaneHandles"
GRAB_PX = 7                  # how near the pointer must be to a handle
LEAST = 1.0                  # smallest half size a drag leaves, in mm
TITLE = "Resize Plane"

_watch = {}                  # view id -> (view, callback)
drag = None                  # the drag going on, for checks: dict(plane, u, v, ...)


def enabled():
    return paths.params().GetBool(PARAM, True)


def _is_origin_plane(obj):
    """Front, Top or Right Plane (an App::Plane of an Origin)."""
    from . import planes
    try:
        return obj.TypeId == "App::Plane" and bool(planes._origins(obj))
    except Exception:
        return False


def _set_box(plane, box):
    if "SWPlaneBox" not in plane.PropertiesList:
        plane.addProperty("App::PropertyFloatList", "SWPlaneBox", "Base",
                          "The plane's size once its handles were dragged (umin, umax, vmin, vmax)")
        try:
            plane.setEditorMode("SWPlaneBox", 2)
        except Exception as _fw_err:
            _fw_log("planehandles.py:hide-box", _fw_err)
    plane.SWPlaneBox = [float(x) for x in box]


def _picked_datums(doc):
    from . import planes
    out = []
    try:
        for obj in Gui.Selection.getSelection(doc.Name):
            if (planes.is_datum(obj) or _is_origin_plane(obj)) and obj not in out:
                out.append(obj)
    except Exception as _fw_err:
        _fw_log("planehandles.py:picked", _fw_err)
    return out


def handles(plane):
    """[(point, su, sv)]: the eight handles in model space; su/sv say which edges each one moves
    (-1 the low edge, 1 the high edge, 0 none) along the plane's X and Y."""
    from . import planes
    o, u, v, umin, umax, vmin, vmax = planes.extents(plane)
    um, vm = (umin + umax) / 2.0, (vmin + vmax) / 2.0
    out = []
    for su, a in ((-1, umin), (0, um), (1, umax)):
        for sv, b in ((-1, vmin), (0, vm), (1, vmax)):
            if su == 0 and sv == 0:
                continue
            out.append((o + u * a + v * b, su, sv))
    return out


def _screen(view, p):
    x, y = view.getPointOnScreen(p)
    return float(x), float(y)


def _ray_on_plane(view, pos, plane):
    """The model point under the screen position, on the plane (None when looking along it)."""
    pl = plane.getGlobalPlacement()
    n = pl.Rotation.multVec(App.Vector(0, 0, 1))
    a = view.getPoint(int(pos[0]), int(pos[1]))
    d = App.Vector(*view.getViewDirection())
    if not view.getCameraType() == "Perspective":
        pass
    else:
        try:
            eye = view.getCameraNode().position.getValue()
            d = a - App.Vector(eye[0], eye[1], eye[2])
        except Exception as _fw_err:
            _fw_log("planehandles.py:eye", _fw_err)
    den = d.dot(n)
    if abs(den) < 1e-9:
        return None
    t = (pl.Base - a).dot(n) / den
    return a + d * t


def hit(view, pos):
    """(plane, su, sv) for the handle under the screen position, else None."""
    doc = App.ActiveDocument
    if doc is None:
        return None
    best = None
    for plane in _picked_datums(doc):
        for p, su, sv in handles(plane):
            x, y = _screen(view, p)
            d = ((x - pos[0]) ** 2 + (y - pos[1]) ** 2) ** 0.5
            if d <= GRAB_PX and (best is None or d < best[0]):
                best = (d, plane, su, sv)
    return best[1:] if best else None


def begin(plane, su, sv):
    global drag
    from . import planes
    o, u, v, umin, umax, vmin, vmax = planes.extents(plane)
    plane.Document.openTransaction(TITLE)
    if _is_origin_plane(plane):

        drag = {"plane": plane, "su": su, "sv": sv, "o": o, "u": u, "v": v, "box": [umin, umax, vmin, vmax],
                "origin": True, "was_box": planes.manual_box(plane)}
        return
    drag = {"plane": plane, "su": su, "sv": sv, "o": o, "u": u, "v": v,
            "half": (max(abs(umin), abs(umax)), max(abs(vmin), abs(vmax))),
            "was": (plane.ResizeMode, float(plane.Length), float(plane.Width))}


def move_to(point):
    """The dragged edge follows the point (the plane stays centred on its origin)."""
    if drag is None or point is None:
        return
    plane = drag["plane"]
    d = point - drag["o"]
    if drag.get("origin"):
        umin, umax, vmin, vmax = drag["box"]
        a, b = d.dot(drag["u"]), d.dot(drag["v"])
        if drag["su"] > 0:
            umax = max(umin + 2 * LEAST, a)
        elif drag["su"] < 0:
            umin = min(umax - 2 * LEAST, a)
        if drag["sv"] > 0:
            vmax = max(vmin + 2 * LEAST, b)
        elif drag["sv"] < 0:
            vmin = min(vmax - 2 * LEAST, b)
        drag["box"] = [umin, umax, vmin, vmax]
        _set_box(plane, drag["box"])
        try:
            from . import shell
            sh = shell.shell()
            if sh is not None and getattr(sh, "planes", None) is not None:
                sh.planes.soon()
        except Exception as _fw_err:
            _fw_log("planehandles.py:origin-redraw", _fw_err)
        return
    hu, hv = drag["half"]
    if drag["su"]:
        hu = max(LEAST, abs(d.dot(drag["u"])))
    if drag["sv"]:
        hv = max(LEAST, abs(d.dot(drag["v"])))
    if plane.ResizeMode != "Manual":
        plane.ResizeMode = "Manual"
    plane.Length = 2.0 * hu
    plane.Width = 2.0 * hv
    plane.recompute()


def end(keep=True):
    global drag
    if drag is None:
        return
    doc = drag["plane"].Document
    if not keep and drag.get("origin") and "SWPlaneBox" in drag["plane"].PropertiesList:
        try:        # Esc: the size it had (none: sized to the part again)
            drag["plane"].SWPlaneBox = list(drag["was_box"] or [])
        except Exception as _fw_err:
            _fw_log("planehandles.py:origin-esc", _fw_err)
    if keep:
        doc.commitTransaction()
    else:
        doc.abortTransaction()
    drag = None
    try:
        from . import shell
        sh = shell.shell()
        if sh is not None and getattr(sh, "planes", None) is not None:
            sh.planes.soon()
    except Exception as _fw_err:
        _fw_log("planehandles.py:redraw", _fw_err)


def _callback(view):
    from pivy import coin

    def cb(node):
        try:
            if not enabled():
                return
            ev = node.getEvent()
            pos = ev.getPosition().getValue()
            if ev.isOfType(coin.SoMouseButtonEvent.getClassTypeId()) and ev.getButton() == coin.SoMouseButtonEvent.BUTTON1:
                if ev.getState() == coin.SoButtonEvent.DOWN and drag is None:
                    h = hit(view, pos)
                    if h is not None:
                        begin(*h)
                        node.setHandled()
                elif ev.getState() == coin.SoButtonEvent.UP and drag is not None:
                    end(True)
                    node.setHandled()
            elif ev.isOfType(coin.SoLocation2Event.getClassTypeId()) and drag is not None:
                move_to(_ray_on_plane(view, pos, drag["plane"]))
                node.setHandled()
            elif ev.isOfType(coin.SoKeyboardEvent.getClassTypeId()) and drag is not None \
                    and ev.getKey() == coin.SoKeyboardEvent.ESCAPE:
                end(False)                  # Esc puts the plane back as it was
                node.setHandled()
        except Exception as _fw_err:
            _fw_log("planehandles.py:event", _fw_err)
    return cb


def watch(doc_name):
    """Listens on the document's 3D view (once)."""
    try:
        view = Gui.getDocument(doc_name).ActiveView
    except Exception:
        return
    if not hasattr(view, "addEventCallbackPivy"):
        return
    key = id(view)
    if key in _watch:
        return
    try:
        from pivy import coin
        cb = _callback(view)
        view.addEventCallbackPivy(coin.SoEvent.getClassTypeId(), cb)
        _watch[key] = (view, cb)
    except Exception as _fw_err:
        _fw_log("planehandles.py:watch", _fw_err)


def forget(doc_name=None):
    from pivy import coin
    for key, (view, cb) in list(_watch.items()):
        try:
            view.removeEventCallbackPivy(coin.SoEvent.getClassTypeId(), cb)
        except Exception:
            pass
        _watch.pop(key, None)
