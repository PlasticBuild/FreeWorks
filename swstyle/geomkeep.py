# SPDX-License-Identifier: LGPL-2.1-or-later
"""Reading a sketch's geometry for a later `sketch.Geometry = ...`.

FreeCAD's Python `sketch.Geometry` hands out each sketch point (Part.Point) without its sketch
state: assigned back, every construction point becomes a real point (PartDesign Hole then drills a
hole at it) and a spline's knot points stop being the spline's own. Lines, arcs, circles and curves
keep theirs. read() returns the same list with that state put back on the points, so whatever is
done with the items (changed in place, copied, reordered, some dropped) each point keeps it.

    geos = geomkeep.read(sketch); ...; sketch.Geometry = geos
"""
import Part

EXTENSION = "Sketcher::SketchGeometryExtension"


def read(sketch):
    """sketch.Geometry (a new list, as FreeCAD gives it) with every point's construction flag,
    internal type, id and blocked state attached."""
    geos = sketch.Geometry
    if not any(isinstance(g, Part.Point) for g in geos):
        return geos
    try:
        import Sketcher
        facades = sketch.GeometryFacadeList
    except Exception:
        return geos
    for g, f in zip(geos, facades):
        if not isinstance(g, Part.Point) or g.hasExtensionOfType(EXTENSION):
            continue
        try:
            e = Sketcher.SketchGeometryExtension()
            e.Construction = f.Construction
            e.InternalType = f.InternalType
            e.Id = f.Id
            e.Blocked = f.Blocked
            g.setExtension(e)
        except Exception:
            pass
    return geos


def like(old, new):
    """new, carrying old's sketch state (construction flag, internal type, id): for an entity that
    is rebuilt from scratch in place of old."""
    try:
        if old.hasExtensionOfType(EXTENSION) and not new.hasExtensionOfType(EXTENSION):
            new.setExtension(old.getExtensionOfType(EXTENSION))
    except Exception:
        pass
    return new
