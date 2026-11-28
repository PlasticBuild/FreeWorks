# -*- coding: utf-8 -*-
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

from . import contextbar, convertentities as CE, sketchtoolpm

TITLE = "Intersection Curve"
COMMAND = "SWStyle_IntersectionCurve2D"
MESSAGE = "Select planes, faces, surfaces or bodies to sketch where they cross the sketch plane."


def intersect(sketch, obj, sub):
    """Add the curves where obj's element sub (or the whole object, sub "") crosses the sketch
    plane; returns how many external curves were added."""
    if not sub and _is_plane(obj):
        return len(_plane_section(sketch, obj))
    before = len(sketch.ExternalGeometry)
    n = len(sketch.ExternalGeo)
    subs = [sub] if sub else ["Face%d" % (i + 1) for i in range(len(obj.Shape.Faces))]
    plain = 0
    for s in subs:
        try:
            sketch.addExternal(obj.Name, s, True, True)    # defining, intersection (FreeCAD 1.1)
        except TypeError:
            sketch.addExternal(obj.Name, s)
        except ValueError:
            if CE.add_external_linked(sketch, obj, s, True, True) is None:
                plain += len(_plain_section(sketch, obj, s))   # outside the sketch's Body: plain curves
        except Exception as _fw_err:
            _fw_log("intersectioncurve.py:50", _fw_err)
            continue
    sketch.recompute()
    if plain:
        return plain
    return len(sketch.ExternalGeo) - n if len(sketch.ExternalGeometry) > before else 0


def _is_plane(obj):
    try:
        return obj.isDerivedFrom("App::Plane") or obj.isDerivedFrom("PartDesign::Plane")
    except Exception:
        return False


def _plane_section(sketch, plane):
    ""

    import Part
    try:
        pl = sketch.getGlobalPlacement()
        n1 = pl.Rotation.multVec(App.Vector(0, 0, 1))
        gp = plane.getGlobalPlacement()
        n2 = gp.Rotation.multVec(App.Vector(0, 0, 1))
        d = n1.cross(n2)
        if d.Length < 1e-9:
            return []
        d.normalize()
        # a point on both planes: solve along n1 x d (in the sketch plane, across the line)
        o1, o2 = pl.Base, gp.Base
        u = n1.cross(d)
        t = (o2 - o1).dot(n2) / u.dot(n2)
        p0 = o1 + u * t
        size = 20.0
        for o in sketch.Document.Objects:
            sh = getattr(o, "Shape", None)
            if o is not plane and o is not sketch and sh is not None and not sh.isNull() and o.isDerivedFrom("Part::Feature") \
                    and not _is_plane(o):
                try:
                    bb = sh.BoundBox
                    if bb.isValid():
                        size = max(size, bb.DiagonalLength)
                except Exception:
                    pass
        try:
            sb = sketch.Shape.BoundBox
            if sb.isValid():
                size = max(size, sb.DiagonalLength)
        except Exception:
            pass
        # centre the line on the model's middle, projected onto it
        mid = p0
        try:
            bbs = [o.Shape.BoundBox for o in sketch.Document.Objects if o.isDerivedFrom("Part::Feature") and not _is_plane(o)
                   and o is not sketch and not o.Shape.isNull() and o.Shape.BoundBox.isValid()]
            if bbs:
                c = bbs[0].Center
                mid = p0 + d * (c - p0).dot(d)
        except Exception:
            pass
        half = 0.6 * size
        edge = Part.LineSegment(mid - d * half, mid + d * half).toShape()
    except Exception as _fw_err:
        _fw_log("intersectioncurve.py:plane", _fw_err)
        return []
    return CE.add_plain(sketch, [edge], False)


def _plain_section(sketch, obj, sub):
    """Where obj's face crosses the sketch plane, as plain sketch entities (FreeCAD will not
    link a Body's sketch to an object outside the Body)."""
    import Part
    try:
        shape = obj.Shape.getElement(sub) if sub else obj.Shape
        pl = sketch.getGlobalPlacement()
        bb = shape.BoundBox
        size = 4 * max(bb.DiagonalLength, 1.0)
        plane = Part.makePlane(size, size, App.Vector(-size / 2, -size / 2, 0))
        plane.Placement = pl.multiply(plane.Placement)
        edges = shape.section(plane).Edges
    except Exception as _fw_err:
        _fw_log("intersectioncurve.py:71", _fw_err)
        return []
    return CE.add_plain(sketch, edges, False)


class IntersectionPage(sketchtoolpm.ToolPage):
    TITLE = TITLE
    ICON = "SKETCH_INTERSECTION_CURVE"
    PIXMAP = "Sketcher_Intersection"
    TRANSACTION = TITLE
    TAKES_MODEL_CLICKS = True     # a click on a face or body goes into Selections (fwsketch/modelpick.py)

    def build(self):
        self.picks = []
        g = self.group("Selections")
        self.list = QtWidgets.QListWidget(g.body)
        self.list.setObjectName("SWIntersectionSelections")
        self.list.setFixedHeight(90)
        self.list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._list_menu)
        g.content.addWidget(self.list)
        self.show_note(MESSAGE)
        self.picker = CE._Picker(self)
        self.picker.install()

    def _list_menu(self, pos):
        item = self.list.itemAt(pos)
        menu = QtWidgets.QMenu(self.list)
        drop = menu.addAction("Delete")
        drop.setEnabled(item is not None)
        clear = menu.addAction("Clear Selections")
        chosen = menu.exec(self.list.mapToGlobal(pos))
        if chosen is drop and item is not None:
            del self.picks[self.list.row(item)]
            self.changed()
        elif chosen is clear:
            self.picks = []
            self.changed()

    def source_of(self, sub):
        return None

    def picked(self, sub):
        pass

    def selection_changed(self):
        pass

    def picked_model(self, obj, sub):
        if sub.startswith("Vertex"):
            return                      # a point does not cross the plane in a curve
        if sub.startswith("Edge"):
            sub = ""
        if (obj, sub) in self.picks:
            self.picks.remove((obj, sub))
        else:
            self.picks.append((obj, sub))
        self.changed()

    def changed(self, *args):
        self.list.clear()
        for obj, sub in self.picks:
            self.list.addItem("%s@%s" % (sub, obj.Label) if sub else obj.Label)
        self.undo_work()
        if not self.picks:
            self.show_note(MESSAGE)
            return
        self.begin()
        made = 0
        for obj, sub in self.picks:
            made += intersect(self.sketch, obj, sub)
        sketchtoolpm._refresh(self.sketch)
        self.show_note("" if made else "The selections do not cross the sketch plane.", not made)

    def closing(self):
        self.picker.remove()


def _sub_owner(obj, name):
    try:
        return obj.getSubObject(name, 1)
    except Exception:
        return None


def _picks_before(sketch):
    out = []
    for s in Gui.Selection.getSelectionEx("", 0):
        obj = s.Object
        if obj == sketch:
            continue
        names = list(s.SubElementNames)
        if not names:
            out.append((obj, ""))       # a whole object picked in the tree
            continue
        for n in names:
            owner = _sub_owner(obj, n) if "." in n else obj
            if owner is None or owner == sketch:
                continue                # the sketch's own edges/points, seen through its Body
            leaf = n.split(".")[-1]
            if leaf.startswith("Vertex"):
                continue                # a point does not cross the plane in a curve
            local = owner is not obj and owner.Document == sketch.Document
            if leaf.startswith("Face"):
                out.append((owner, leaf) if local and owner.isDerivedFrom("Part::Feature") else (obj, n))
            elif leaf.startswith("Edge") or not leaf:
                # an edge picks its body (as the PM does); a plane or body seen through its Body is itself
                out.append((owner, "") if local else (obj, ""))
    seen = []
    for p in out:
        if p not in seen:
            seen.append(p)
    return seen


class IntersectionCommand:
    def GetResources(self):
        return {"Pixmap": "Sketcher_Intersection", "MenuText": TITLE,
                "ToolTip": "Sketches the curves where picked planes, faces or bodies cross the sketch plane",
                "CmdType": "ForEdit"}

    def IsActive(self):
        return contextbar.sketch_in_edit() is not None

    def Activated(self):
        sketch = contextbar.sketch_in_edit()
        if sketch is None:
            return
        picks = _picks_before(sketch)
        if picks:
            doc = sketch.Document
            doc.openTransaction(TITLE)
            try:
                made = sum(intersect(sketch, o, s) for o, s in picks)
            except BaseException:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
                raise
            if made:
                doc.commitTransaction()
                Gui.Selection.clearSelection()
                sketchtoolpm._refresh(sketch)
                return

            try:
                doc.abortTransaction()
                if App.getActiveTransaction():
                    App.closeActiveTransaction(True)
            except Exception:
                pass
            Gui.Selection.clearSelection()
        sketchtoolpm.open_page(IntersectionPage(sketch))


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, IntersectionCommand())
