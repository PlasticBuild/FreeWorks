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

try:
    import FreeCADGui as Gui
    from PySide import QtCore
except ImportError:
    Gui = None

from . import paths

COLOR_KEY = "DanglingColor"           # Options > Colors > Dimensions, Dangling
BROWN = (0.55, 0.33, 0.10)
SKETCH = "Sketcher::SketchObject"


# ------------------------------------------------------------------ dangling
def _ext_flag(geo, flag):
    try:
        import Sketcher
        return bool(Sketcher.ExternalGeometryFacade(geo).testFlag(flag))
    except Exception:
        return None


_cache = {}


def dangling_ids(sketch):
    """The external geometry ids (-3, -4 ...) whose model edge is gone (asked on every tree
    paint, so kept for half a second)."""
    import time
    try:
        key = (sketch.Document.Name, sketch.Name)
    except Exception:
        return []
    hit = _cache.get(key)
    now = time.monotonic()
    if hit is not None and now - hit[0] < 0.5:
        return list(hit[1])
    out = _dangling_ids(sketch)
    if len(_cache) > 500:
        _cache.clear()
    _cache[key] = (now, out)
    return list(out)


def _dangling_ids(sketch):
    try:
        if sketch is None or sketch.TypeId != SKETCH:
            return []
        geos = list(sketch.ExternalGeo)[2:]       # [0], [1] are the H and V axes (-1, -2)
        linked = sum(len(subs) if isinstance(subs, (list, tuple)) else 1
                     for _obj, subs in sketch.ExternalGeometry)
    except Exception:
        return []
    out = []
    for k, geo in enumerate(geos):
        if _ext_flag(geo, "Missing"):
            out.append(-3 - k)
    if not out and len(geos) > linked:
        # no flag to tell which: FreeCAD keeps the lost ones after the linked ones
        out = [-3 - k for k in range(linked, len(geos))]
    # a broken link (object or element gone) is dangling too
    try:
        from .relationspm import external_references
        out += [i for i, ref in external_references(sketch).items() if not ref[2] and i not in out]
    except Exception as _fw_err:
        _fw_log("rebuilderrors.py:91", _fw_err)
    return sorted(set(out), reverse=True)


def _constraint_geos(c):
    out = []
    for attr in ("First", "Second", "Third"):
        g = getattr(c, attr, -2000)
        if g is not None and g > -2000:
            out.append(g)
    return out


def dangling_relations(sketch):
    """[(constraint index, name)] for the relations and dimensions that use a lost model edge."""
    ids = set(dangling_ids(sketch))
    if not ids:
        return []
    out = []
    for i, c in enumerate(sketch.Constraints):
        if ids.intersection(_constraint_geos(c)):
            out.append((i, c.Name or "%s%d" % (c.Type, i + 1)))
    return out


def dangling(sketch):
    return bool(dangling_ids(sketch))


def dangling_text(sketch):
    rels = dangling_relations(sketch)
    if rels:
        return ("The sketch has %d dangling relation(s) or dimension(s): the model edge they use is "
                "gone. Repair them in the Display/Delete Relations panel." % len(rels))
    return "The sketch has dangling geometry: the model edge it was converted from is gone."


def color():
    try:
        u = paths.params().GetUnsigned(COLOR_KEY, 0)
    except Exception:
        u = 0
    if not u:
        return BROWN
    return (((u >> 24) & 255) / 255.0, ((u >> 16) & 255) / 255.0, ((u >> 8) & 255) / 255.0)


# ------------------------------------------------------------------ wording
KINDS = (
    # (words in FreeCAD's reason, feature types or None, plain description, help)
    (("BRep_API", "command not done", "Failed to make fillet", "fillet"), ("PartDesign::Fillet",),
     "Failed to create fillet due to the geometry. Try a smaller radius.",
     "The fillet could not be built on the picked edges: the radius is too big for the faces "
     "next to it, or an edge meets another at a corner the fillet cannot round. Make the radius "
     "smaller, pick fewer edges, or use FeatureXpert."),
    (("BRep_API", "command not done", "chamfer"), ("PartDesign::Chamfer",),
     "Failed to create chamfer due to the geometry. Try a smaller distance.",
     "The chamfer is bigger than the faces next to the edge allow. Make the distance smaller or "
     "use FeatureXpert."),
    (("draft",), ("PartDesign::Draft",),
     "Failed to create draft. Try a smaller angle or another neutral plane.",
     "The faces could not be tilted by the angle about the neutral plane. Try a smaller angle."),
    (("Linked shape object is empty", "No profile linked"), None,
     "The sketch this feature is made from is empty.",
     "The feature's sketch has no contour left to build from (it was emptied or its contour was "
     "deleted). Edit the sketch and draw the profile again, or delete the feature."),
    (("Invalid shape name", "not found", "Missing", "lost"), None,
     "A face, edge or plane this feature uses is missing.",
     "A model element the feature was built on is gone after a change earlier in the tree. Edit "
     "the feature and pick the face, edge or plane again."),
    (("not closed", "open wire", "Wire is not closed", "closed"), None,
     "The sketch is open: the feature needs a closed contour.",
     "Edit the sketch and close the contour (end points must meet), or remove the extra lines."),
    (("not coplanar", "Wires are not coplanar"), None,
     "The sketch's contours are not in one plane.",
     "Edit the sketch: every contour of the profile must lie in the sketch plane (use a 2D sketch, "
     "or one 3D sketch contour per feature)."),
    (("intersect", "Self-intersecting", "self intersecting"), None,
     "The sketch contour crosses itself.",
     "Edit the sketch: a contour may not cross itself or another contour."),
    (("Resulting shape is not a solid", "not a solid", "multiple solids", "Result has multiple solids"), None,
     "The result would be more than one body or no body at all.",
     "The feature splits the body or removes all of it. Change its depth or end condition, or "
     "turn Merge result off."),
    (("Up to face", "UpToFace"), None,
     "The end condition's face does not cut the whole profile.",
     "Pick a face the feature reaches all the way, or use another end condition."),
    (("over-constrained", "conflicting", "Conflicting"), (SKETCH,),
     "The sketch is over defined: some relations conflict.",
     "Delete or change the conflicting relations (listed in red) in the Display/Delete "
     "Relations panel."),
    (("redundant", "Redundant"), (SKETCH,),
     "The sketch is over defined: some relations are redundant.",
     "Some relations say again what others already say. Delete the redundant ones."),
    (("malformed", "Malformed"), (SKETCH,),
     "The sketch has relations to geometry that is gone.",
     "Delete the broken relations in the Display/Delete Relations panel."),
)
GENERIC_HELP = ("The feature could not be rebuilt. Edit it and check its inputs (sketch, faces, "
                "edges, depth). Earlier features in the tree may have changed the model it uses.")


SKETCH_PLANE = ("The sketch plane or face is missing.",
                "The face or plane this sketch was drawn on is gone after a change earlier in the tree. "
                "Right-click the sketch, Edit Sketch Plane, and pick a plane or face again.")


def missing_support(obj):
    """True when an attached sketch (or other attached feature) names a face or plane that is gone."""
    try:
        if getattr(obj, "MapMode", "Deactivated") == "Deactivated":
            return False
        for base, subs in obj.AttachmentSupport:
            for sub in subs or []:
                if not sub:
                    continue
                try:
                    if base.Shape.getElement(sub) is None:
                        return True
                except Exception:
                    return True
    except Exception:
        return False
    return False


def _kind(obj, text):
    low = (text or "").lower()
    type_id = getattr(obj, "TypeId", "")
    if type_id == SKETCH and missing_support(obj):
        return SKETCH_PLANE
    for words, types, plain, helptext in KINDS:
        if types is not None and type_id not in types:
            continue
        if any(w.lower() in low for w in words):
            return plain, helptext
    return None, GENERIC_HELP


def describe(obj, text):
    """The What's Wrong / tooltip wording: plain words, FreeCAD's own reason after them."""
    plain, _help = _kind(obj, text)
    if plain is None and text and any(w in text for w in RAW):

        if any(w in text for w in LOST):
            return "A face, edge or vertex this feature uses is missing. Edit the feature and pick it again."
        return "The feature could not be built with these settings. Edit the feature and change them."
    if plain is None or plain.lower() in (text or "").lower():
        return text
    relations = _sketch_relations(obj, text)
    if relations:
        return plain + " " + relations      # error check 417: FreeCAD's sentence said again in brackets read twice
    if text and any(w in text for w in RAW):
        return plain
    return "%s (%s)" % (plain, text) if text and text != "The feature could not be rebuilt." else plain


def _sketch_relations(obj, text):
    """'Relation 5.' / 'Relations 3, 5.' for a sketch FreeCAD failed for redundant or conflicting
    relations (FreeCAD: '... Remove the following redundant constraint: 5'), else ''."""
    import re
    if getattr(obj, "TypeId", "") != SKETCH or not text:
        return ""
    low = text.lower()
    if not any(w in low for w in ("redundant", "conflict", "over-constrained")):
        return ""
    tail = text.rsplit(":", 1)[-1] if ":" in text else ""
    numbers = re.findall(r"\d+", tail)
    if not numbers:
        return ""
    return "%s %s." % ("Relation" if len(numbers) == 1 else "Relations", ", ".join(numbers))


# the geometry kernel's own words: they say nothing to a person
RAW = ("BRep_API", "command not done", "Standard_", "StdFail", "TopoDS", "Fillet not possible",
       "Invalid edge link", "Invalid face link", "Invalid shape name", ";#", "TopoShape is invalid",
       "Linked shape object is empty")
LOST = ("Invalid edge link", "Invalid face link", "Invalid vertex link", "Invalid shape name", ";#")


def help_text(obj, text):
    return _kind(obj, text)[1]


def reason(obj):
    """FreeCAD's reason the feature failed, on one line, or ''."""
    try:
        if "Invalid" not in obj.State:
            return ""
        text = obj.getStatusString() or ""
    except Exception:
        return ""
    from .whatswrong import row_text
    return row_text(obj, text)          # What's Wrong's words


def tooltip(obj):
    """The tree tooltip of a feature with an error or a warning, else ''."""
    if obj is None:
        return ""
    try:
        from .whatswrong import _failed_inside
        if _failed_inside(obj):
            return ""       # the part's row names the feature that failed (the tree asks the rows under it)
    except Exception as _fw_err:
        _fw_log("rebuilderrors.py:272", _fw_err)
    text = reason(obj)
    if text:
        return "Rebuild error: %s" % text
    try:
        if obj.TypeId == SKETCH and "Invalid" not in obj.State:
            if dangling(obj):
                return "Warning: " + dangling_text(obj)
            if obj.RedundantConstraints:
                return "Warning: The sketch has redundant relations."
    except Exception as _fw_err:
        _fw_log("rebuilderrors.py:283", _fw_err)
    return ""


# ------------------------------------------------------------------ brown in the sketch
class _Overlay:
    """The lost curves of the sketch being edited, in brown, with their relations' names."""

    def __init__(self):
        self.root = None
        self.view = None
        self.sketch = None

    def show(self, sketch):
        self.hide()
        ids = dangling_ids(sketch)
        if not ids:
            return False
        try:
            from pivy import coin
            view = Gui.getDocument(sketch.Document.Name).ActiveView
            graph = view.getSceneGraph()
        except Exception:
            return False
        rels = dangling_relations(sketch)
        by_geo = {}
        for i, name in rels:
            for g in _constraint_geos(sketch.Constraints[i]):
                by_geo.setdefault(g, []).append(name)
        root = coin.SoSeparator()
        root.setName("FreeWorksDangling")
        pl = sketch.getGlobalPlacement()
        xf = coin.SoTransform()
        xf.translation.setValue(*pl.Base)
        q = pl.Rotation.Q
        xf.rotation.setValue(q[0], q[1], q[2], q[3])
        root.addChild(xf)
        r, g, b = color()
        mat = coin.SoBaseColor()
        mat.rgb.setValue(r, g, b)
        root.addChild(mat)
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        root.addChild(light)
        style = coin.SoDrawStyle()
        style.lineWidth = 4
        root.addChild(style)
        font = coin.SoFont()
        font.size = 13
        root.addChild(font)
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        root.addChild(pick)
        geos = list(sketch.ExternalGeo)
        for gid in ids:
            k = -gid - 1
            if k >= len(geos):
                continue
            try:
                edge = geos[k].toShape()
                pts = edge.discretize(48)
            except Exception:
                continue
            coords = coin.SoCoordinate3()
            coords.point.setValues(0, len(pts), [(p.x, p.y, p.z + 0.02) for p in pts])
            line = coin.SoLineSet()
            line.numVertices.setValue(len(pts))
            root.addChild(coords)
            root.addChild(line)
            names = by_geo.get(gid)
            mid = pts[len(pts) // 2]
            sep = coin.SoSeparator()
            at = coin.SoTranslation()
            at.translation.setValue(mid.x, mid.y + 1.5, mid.z + 0.02)
            text = coin.SoText2()
            text.string.setValues(0, 1, [", ".join(names) + " (dangling)" if names else "dangling"])
            sep.addChild(at)
            sep.addChild(text)
            root.addChild(sep)
        graph.addChild(root)
        self.root, self.view, self.sketch = root, view, sketch.Name
        return True

    def hide(self):
        if self.root is not None:
            try:
                self.view.getSceneGraph().removeChild(self.root)
            except Exception as _fw_err:
                _fw_log("rebuilderrors.py:371", _fw_err)
        self.root = self.view = self.sketch = None

    def shown(self):
        return self.root is not None


OVERLAY = _Overlay()


class _EditWatch:
    """Gui document observer: the overlay while a sketch with dangling relations is edited."""

    def slotInEdit(self, vp):
        try:
            obj = vp.Object
        except Exception:
            return
        if getattr(obj, "TypeId", "") == SKETCH:
            QtCore.QTimer.singleShot(0, lambda n=obj.Name, d=obj.Document.Name: _show_later(d, n))

    def slotResetEdit(self, vp):
        OVERLAY.hide()


def _show_later(doc_name, name):
    try:
        doc = App.getDocument(doc_name)
    except Exception:
        return
    obj = doc.getObject(name)
    if obj is not None:
        OVERLAY.show(obj)


_watch = None


def install():
    global _watch
    if Gui is None or _watch is not None:
        return
    _watch = _EditWatch()
    Gui.addDocumentObserver(_watch)
    _patch()
    try:
        from . import rebuildretry       # a second rebuild where FreeCAD lost an element name
        rebuildretry.install()
        from . import sketchmemory       # a sketch dimension changed and back gives the sketch it had
        sketchmemory.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: rebuild retry not installed (%s)\n" % error)
    try:
        from . import editguard
        editguard.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: edit guard not installed (%s)\n" % error)
    try:
        from . import persistrefs
        persistrefs.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: persistent references not installed (%s)\n" % error)


def _patch():
    """The yellow mark, the What's Wrong warning row and Stop and Repair know dangling sketches."""
    from . import fmtree, stoprepair, whatswrong
    if not getattr(fmtree._warned, "_fw_dangling", False):
        old_warned = fmtree._warned

        def warned(obj, _old=old_warned):
            if _old(obj):
                return True
            try:
                return obj is not None and obj.TypeId == SKETCH and "Invalid" not in obj.State and dangling(obj)
            except Exception:
                return False
        warned._fw_dangling = True
        fmtree._warned = warned
    if not getattr(whatswrong.warnings, "_fw_dangling", False):
        old_warnings = whatswrong.warnings

        def warnings(doc, _old=old_warnings):
            found = list(_old(doc))
            have = {o.Name for o, _t in found}
            for obj in doc.Objects:
                try:
                    if obj.TypeId == SKETCH and obj.Name not in have and "Invalid" not in obj.State and dangling(obj):
                        found.append((obj, dangling_text(obj)))
                except Exception as _fw_err:
                    _fw_log("rebuilderrors.py:461", _fw_err)
            order = {o.Name: i for i, o in enumerate(doc.Objects)}
            found.sort(key=lambda r: order.get(r[0].Name, 0))
            return found
        warnings._fw_dangling = True
        whatswrong.warnings = warnings
    if not getattr(stoprepair.problem, "_fw_dangling", False):
        old_problem = stoprepair.problem

        def problem(sketch, _old=old_problem):
            kind = _old(sketch)
            if kind is None and dangling(sketch):
                return "a warning"
            return kind
        problem._fw_dangling = True
        stoprepair.problem = problem
