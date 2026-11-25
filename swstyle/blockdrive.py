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

import FreeCAD as App

ON_BLOCK, PROJECT = "On Block", "Project"
_PROPS = (("App::PropertyString", "FwBlockLayout", "The layout sketch of the block that drives this part"),
          ("App::PropertyString", "FwBlockName", "The block that drives this part"),
          ("App::PropertyString", "FwBlockMode", "Block to Part Constraint: On Block or Project"),
          ("App::PropertyString", "FwBlockPose0", "The block's insertion point and angle when the part was made"))


def pose(sketch, name):
    """(x, y, angle in degrees) of the block's insertion point, or None."""
    from . import blocks
    rec = next((r for r in blocks.records(sketch) if r.get("name") == name), None)
    if rec is None:
        return None
    _geos, base = blocks.indices(sketch, rec)
    if base is None:
        return None
    b = sketch.Geometry[base]
    return (b.X, b.Y, float(rec.get("angle", 0.0)))


def block_geometry(sketch, name):
    from . import blocks
    rec = next((r for r in blocks.records(sketch) if r.get("name") == name), None)
    if rec is None:
        return []
    idx = [i for i in blocks.indices(sketch, rec)[0] if i >= 0]
    return [sketch.Geometry[i].copy() for i in idx if not sketch.getConstruction(i)]


def moved(p0, p1):
    """The move (in sketch coordinates) that takes the block from pose p0 to pose p1."""
    x0, y0, a0 = p0
    x1, y1, a1 = p1
    back = App.Placement(App.Vector(-x0, -y0, 0), App.Rotation())
    turn = App.Placement(App.Vector(), App.Rotation(App.Vector(0, 0, 1), a1 - a0))
    to = App.Placement(App.Vector(x1, y1, 0), App.Rotation())
    return to.multiply(turn).multiply(back)


def link(comp, sketch, name, mode=ON_BLOCK):
    """Ties the component made from block name of layout sketch to it."""
    p0 = pose(sketch, name)
    if comp is None or p0 is None:
        return False
    for kind, prop, tip in _PROPS:
        if not hasattr(comp, prop):
            comp.addProperty(kind, prop, "FreeCAD", tip)
    comp.FwBlockLayout = sketch.Name
    comp.FwBlockName = name
    comp.FwBlockMode = mode if mode in (ON_BLOCK, PROJECT) else ON_BLOCK
    comp.FwBlockPose0 = json.dumps(list(p0))
    for prop in ("FwBlockLayout", "FwBlockName", "FwBlockPose0"):
        try:
            comp.setEditorMode(prop, 1)
        except Exception as _fw_err:
            _fw_log("blockdrive.py:92", _fw_err)
    install()
    sync_component(comp)
    return True


def part_sketch(comp):
    body = getattr(comp, "LinkedObject", None)
    for o in (getattr(body, "Group", None) or []):
        if hasattr(o, "FwFromBlock"):
            return o
    return None


def _same(a, b):
    if len(a) != len(b):
        return False
    for g, h in zip(a, b):
        if type(g) is not type(h):
            return False
        sa, sb = g.toShape(), h.toShape()
        if abs(sa.Length - sb.Length) > 1e-7:
            return False
        if any((v.Point - w.Point).Length > 1e-7 for v, w in zip(sa.Vertexes, sb.Vertexes)):
            return False
        if hasattr(g, "Center") and (g.Center - h.Center).Length > 1e-7:
            return False
    return True


def sync_component(comp):
    """Puts the component (On Block) and its part's sketch in step with the block. True when
    something changed."""
    doc = comp.Document
    sketch = doc.getObject(getattr(comp, "FwBlockLayout", "") or "")
    name = getattr(comp, "FwBlockName", "")
    if sketch is None or not name:
        return False
    p1 = pose(sketch, name)
    if p1 is None:
        return False
    try:
        p0 = tuple(json.loads(comp.FwBlockPose0))
    except Exception:
        return False
    d = moved(p0, p1)
    changed = False
    if comp.FwBlockMode != PROJECT:
        want = sketch.getGlobalPlacement().multiply(d)
        if not want.isSame(comp.Placement, 1e-9):
            comp.Placement = want
            changed = True
    psk = part_sketch(comp)
    if psk is not None:
        inv = d.inverse()
        geos = []
        for g in block_geometry(sketch, name):
            g.transform(inv.toMatrix())
            geos.append(g)
        have = list(psk.Geometry)
        if geos and len(have) == len(geos) and not _same(have, geos):
            psk.Geometry = geos
            try:
                psk.Document.recompute()
            except Exception as _fw_err:
                _fw_log("blockdrive.py:157", _fw_err)
            changed = True
    return changed


def _in_edit(sketch):
    try:
        import FreeCADGui as Gui
        gdoc = Gui.getDocument(sketch.Document.Name)
        vp = gdoc.getInEdit() if gdoc is not None else None
        return getattr(vp, "Object", None) is sketch
    except Exception:
        return False


def sync_document(doc):
    if doc is None:
        return 0
    n = 0
    comps = [o for o in doc.Objects if getattr(o, "FwBlockName", "")]
    for comp in comps:
        sketch = doc.getObject(getattr(comp, "FwBlockLayout", "") or "")
        if sketch is not None and _in_edit(sketch):
            # while the layout is edited the block follows the pointer: the part follows too
            pass
        try:
            if sync_component(comp):
                n += 1
        except Exception as error:
            App.Console.PrintLog("FreeCAD: block-driven part %s: %s\n" % (comp.Name, error))
    if n:
        try:
            doc.recompute()
        except Exception as _fw_err:
            _fw_log("blockdrive.py:191", _fw_err)
    return n


_TIMER = []


def _tick():
    try:
        sync_document(App.ActiveDocument)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: block-driven parts: %s\n" % error)


def install():
    if _TIMER or not App.GuiUp:
        return
    from PySide import QtCore
    t = QtCore.QTimer()
    t.setInterval(500)
    t.timeout.connect(_tick)
    t.start()
    _TIMER.append(t)
