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

TITLE = "Convert to 3D Sketch"


def _key(v):
    return (round(v.x, 6), round(v.y, 6), round(v.z, 6))


def convert(sketch):
    """Makes the 3D sketch; returns it (None when the sketch has nothing to convert)."""
    import Part
    from .. import sketch3d
    from .. import sketch3dsolve as S
    pl = sketch.getGlobalPlacement()
    n = pl.Rotation.multVec(App.Vector(0, 0, 1))
    normal = [n.x, n.y, n.z]
    pts, ents, rels, index = [], [], [], {}

    def point(v2d):
        v = pl.multVec(App.Vector(v2d.x, v2d.y, 0))
        k = _key(v)
        if k not in index:
            pts.append((v.x, v.y, v.z))
            index[k] = len(pts) - 1
        return index[k]

    def fresh(v2d):
        v = pl.multVec(App.Vector(v2d.x, v2d.y, 0))
        pts.append((v.x, v.y, v.z))
        return len(pts) - 1

    for g, geo in enumerate(sketch.Geometry):
        try:
            cons = bool(sketch.getConstruction(g))
        except Exception:
            cons = False
        kind = type(geo).__name__
        if kind == "LineSegment":
            if (geo.EndPoint - geo.StartPoint).Length < 1e-9:
                continue
            ents.append(S.Entity("L", [point(geo.StartPoint), point(geo.EndPoint)], cons))
        elif kind == "Circle":
            c = point(geo.Center)
            a = fresh(geo.Center + App.Vector(geo.Radius, 0, 0))
            ents.append(S.Entity("C", [c, a], cons))
            rels.append(S.Relation("ArcPlane", [c, a, a], normal))
        elif kind == "ArcOfCircle":
            c = point(geo.Center)
            a, b = point(geo.StartPoint), point(geo.EndPoint)
            # FreeCAD's arcs run anticlockwise about the sketch normal, as 3D sketch arcs do about theirs
            axis = getattr(geo, "Axis", App.Vector(0, 0, 1))
            side = 1.0 if axis.z >= 0 else -1.0
            ents.append(S.Entity("A", [c, a, b], cons))
            rels.append(S.Relation("ArcPlane", [c, a, b], [x * side for x in normal]))
        elif kind == "Point":
            if cons:
                continue
            ents.append(S.Entity("P", [point(App.Vector(geo.X, geo.Y, 0))], False))
        else:
            try:
                edge = geo.toShape()
                through = edge.discretize(Number=max(8, min(64, len(getattr(geo, "getPoles", lambda: [])()) * 2)))
            except Exception:
                continue
            if len(through) < 2:
                continue
            closed = edge.isClosed()
            idx = [point(through[0])] + [fresh(p) for p in through[1:-1]]
            idx.append(idx[0] if closed else point(through[-1]))
            ents.append(S.Entity("S", idx, cons))
    if not ents:
        return None
    doc = sketch.Document
    body = None
    try:
        body = sketch.getParentGeoFeatureGroup()
        if body is not None and body.TypeId != "PartDesign::Body":
            body = None
    except Exception:
        body = None
    obj = sketch3d.make(doc, body)
    sketch3d.store(obj, pts, ents, rels)
    try:
        obj.Label = "%s (3D)" % sketch.Label
    except Exception as _fw_err:
        _fw_log("fwsketch/to3d.py:104", _fw_err)
    doc.recompute()
    try:
        sketch.Visibility = False
    except Exception as _fw_err:
        _fw_log("fwsketch/to3d.py:109", _fw_err)
    return obj


def run(sketch):
    """The menu entry: one Undo step, the new 3D sketch picked."""
    doc = sketch.Document
    doc.openTransaction(TITLE)
    try:
        obj = convert(sketch)
    except Exception as error:
        doc.abortTransaction()
        App.Console.PrintWarning("FreeCAD: %s: %s\n" % (TITLE, error))
        return None
    doc.commitTransaction()
    if obj is None:
        App.Console.PrintMessage("FreeCAD: %s: the sketch has no entities\n" % TITLE)
        return None
    try:
        import FreeCADGui as Gui
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, obj.Name)
    except Exception as _fw_err:
        _fw_log("fwsketch/to3d.py:132", _fw_err)
    return obj
