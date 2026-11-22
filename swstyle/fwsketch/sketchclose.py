# SPDX-License-Identifier: LGPL-2.1-or-later
""







import FreeCAD as App
import FreeCADGui as Gui

from . import sysopts

TOL = 1e-6
FEATURES = ("PartDesign_Pad", "PartDesign_Pocket", "PartDesign_Revolution", "PartDesign_Groove")
TITLE = "Close sketch"
TEXT = ("The sketch is currently open. A non-closed sketch can be used to create a thin feature.\n\n"
        "Would you like the sketch automatically closed?")

REVOLVE_TEXT = ("The sketch is currently open. A non-thin revolution feature requires a closed sketch.\n\n"
                "Would you like the sketch to be automatically closed?")
REVOLVES = ("PartDesign_Revolution", "PartDesign_Groove")


def text_for(native):
    ""
    return REVOLVE_TEXT if native in REVOLVES else TEXT


def _ends(sketch):
    """[(geo, pos, (x, y))] of the curve ends of the sketch's (non-construction) profile."""
    out = []
    for i, g in enumerate(sketch.Geometry):
        if sketch.getConstruction(i):
            continue
        kind = type(g).__name__
        if kind in ("Point", "Circle", "Ellipse") or not hasattr(g, "StartPoint"):
            continue
        for pos, p in ((1, g.StartPoint), (2, g.EndPoint)):
            out.append((i, pos, (p.x, p.y)))
    return out


def _on_other_curve(sketch, geo, p):
    ""

    try:
        import Part
        v = Part.Vertex(App.Vector(p[0], p[1], 0))
        for i, g in enumerate(sketch.Geometry):
            if i == geo or sketch.getConstruction(i) or type(g).__name__ == "Point":
                continue
            if g.toShape().distToShape(v)[0] < 1e-6:
                return True
    except Exception:
        return False
    return False


def open_ends(sketch):
    """The free ends: those no other end sits on, and that lie on no other curve."""
    ends = _ends(sketch)
    free = []
    for k, (g, pos, p) in enumerate(ends):
        if not any(j != k and abs(p[0] - q[0]) < TOL and abs(p[1] - q[1]) < TOL
                   for j, (_g, _pos, q) in enumerate(ends)) and not _on_other_curve(sketch, g, p):
            free.append((g, pos, p))
    return free


def close(sketch):
    """Join the two free ends with a line; returns its geo id, else None."""
    import Part
    import Sketcher
    free = open_ends(sketch)
    if len(free) != 2:
        return None
    (g1, p1, a), (g2, p2, b) = free
    if abs(a[0] - b[0]) < TOL and abs(a[1] - b[1]) < TOL:
        return None
    doc = sketch.Document
    doc.openTransaction("Close sketch")
    try:
        line = sketch.addGeometry(Part.LineSegment(App.Vector(a[0], a[1], 0), App.Vector(b[0], b[1], 0)), False)
        sketch.addConstraint([Sketcher.Constraint("Coincident", line, 1, g1, p1),
                              Sketcher.Constraint("Coincident", line, 2, g2, p2)])
        doc.commitTransaction()
    except Exception:
        doc.abortTransaction()
        return None
    doc.recompute()
    return line


answer = None       # tests: True / False instead of the question box


def ask(native, sketches):
    """Before feature native: ask to close an open sketch. Returns False (go on) always; the
    sketch is closed first when the answer is Yes."""
    if native not in FEATURES or not sysopts.on(sysopts.PROMPT_CLOSE):
        return False
    for sketch in sketches:
        try:
            if sketch is None or len(open_ends(sketch)) != 2:
                continue
        except Exception:
            continue
        yes = answer
        if yes is None:
            from PySide import QtWidgets
            b = QtWidgets.QMessageBox.question(Gui.getMainWindow(), TITLE, text_for(native),
                                               QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                                               QtWidgets.QMessageBox.Yes)
            yes = b == QtWidgets.QMessageBox.Yes
        if yes:
            close(sketch)
    return False
