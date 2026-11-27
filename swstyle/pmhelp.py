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
from PySide import QtWidgets


HELP = {
    "Boss-Extrude": ("Extrudes a sketch or selected sketch contours in one or two directions to add material.",
                     ["Pick a sketch, a plane, or a flat face. With a plane or face the sketch opens first; "
                      "close it and the page follows.",
                      "Direction 1: the End Condition (Blind, Through All, Up To Next, Up To Vertex, Up To "
                      "Surface, Offset From Surface, Up To Body, Mid Plane) and the depth D1. The arrow in the "
                      "view flips the direction; drag the arrow to change the depth.",
                      "Draft: the angle the walls lean while extruding; Draft outward turns it the other way.",
                      "Direction 2: a second depth the other way, with its own End Condition.",
                      "Thin Feature: a wall of the given thickness along the sketch instead of a filled profile.",
                      "Selected Contours: with more than one closed loop in the sketch, the loops to use.",
                      "Merge result (second feature on): join the new material to the part."]),
    "Cut-Extrude": ("Extrudes a sketch or selected sketch contours to remove material.",
                    ["As Boss-Extrude, taking material away. Flip side to cut removes everything outside the "
                     "profile instead of inside it.",
                     "Feature Scope (several bodies): the bodies the cut applies to, or Auto-select."]),
    "Revolve": ("Revolves a sketch about an axis to add material.",
                ["Axis of Revolution: a sketch line, a centerline, an edge or an axis.",
                 "Direction 1: Blind with the angle, Up To Vertex / Surface, Mid Plane, or Two Directions.",
                 "Thin Feature: a wall instead of a filled profile."]),
    "Cut-Revolve": ("Revolves a sketch about an axis to remove material.",
                    ["As Revolve, taking material away."]),
    "Sweep": ("Sweeps a profile along a path to add material.",
              ["Profile and Path: the profile sketch (or a circle made on the path), then the path.",
               "Guide Curves: curves the profile follows as it sweeps.",
               "Options: profile orientation and twist; Merge result.",
               "Start and End Tangency: how the sweep leaves and arrives.",
               "Thin Feature: a wall of the given thickness."]),
    "Cut-Sweep": ("Sweeps a profile along a path to remove material.", ["As Sweep, taking material away."]),
    "Loft": ("Lofts between two or more profiles to add material.",
             ["Profiles: the sketches or faces to loft through, in order. Click them near the same corner "
              "so the loft does not twist.",
              "Start/End Constraints: how the loft leaves the first profile and meets the last.",
              "Guide Curves and Centerline Parameters: curves that shape the loft between profiles.",
              "Options: Close loft, Ruled surface, Merge result.",
              "Thin Feature: a wall of the given thickness."]),
    "Cut-Loft": ("Lofts between profiles to remove material.", ["As Loft, taking material away."]),
    "Boundary Boss/Base": ("Adds material between profiles in two directions.",
                           ["Direction 1 and Direction 2: the curves or sketches in each direction."]),
    "Boundary Cut": ("Removes material between profiles in two directions.", ["As Boundary Boss/Base."]),
    "Hole Specification": ("The Hole Wizard: a standard hole, counterbore, countersink, tap, pipe tap or slot.",
                           ["Type tab: the hole type, Standard, Type and Size, the End Condition and the Options "
                            "(near and far side countersinks, cosmetic thread). Favorites keep a set of choices.",
                            "Positions tab: the face the holes go on, then one click per hole; the sketch closes "
                            "with the feature. With a sketch of points picked first, OK makes the holes on them.",
                            "Edit Feature on a hole opens the same page with its values."]),
    "Fillet": ("Rounds edges or faces with a constant, variable, face or full round fillet.",
               ["Fillet Type: Constant Size, Variable Size, Face Fillet, Full Round Fillet.",
                "Items To Fillet: edges, faces, features or loops; Tangent propagation follows the edge "
                "round tangent neighbors.",
                "Fillet Parameters: the radius (symmetric or asymmetric); Multiple radius fillet gives each "
                "edge its own value.",
                "Setback Parameters and Fillet Options: how fillets meet at a vertex, Keep features, overflow."]),
    "Chamfer": ("Bevels edges or a vertex with a distance, a distance and angle, or two distances.",
                ["Chamfer Type: Angle Distance, Distance Distance, Vertex, Offset Face, Face Face.",
                 "Items To Chamfer: the edges, faces or vertex; Chamfer Parameters: the distance and angle "
                 "(Flip direction swaps the sides)."]),
    "Linear Pattern": ("Repeats features, faces or bodies along one or two directions.",
                       ["Direction 1: an edge, axis or dimension, the spacing (or the total length with "
                        "Up to reference) and the number of instances.",
                        "Direction 2: a second direction; Pattern seed only repeats the seed, not Direction 1.",
                        "Features and Faces / Bodies: what is repeated.",
                        "Instances to Skip: click the instances in the view to leave out. Instances to Vary: "
                        "increments per instance."]),
    "Circular Pattern": ("Repeats features, faces or bodies round an axis.",
                         ["Direction 1: the axis (an edge, a cylindrical face, an axis), Equal spacing over "
                          "the total angle or a spacing per instance, and the number of instances.",
                          "Symmetric: the same instances the other way; Direction 2 for a second set.",
                          "Instances to Skip: click the instances to leave out."]),
    "Mirror": ("Mirrors features, faces or bodies about a plane or a flat face.",
               ["Mirror Face/Plane: the plane or flat face. Features to Mirror / Faces to Mirror / Bodies to "
                "Mirror: what is mirrored. Merge solids joins a mirrored body to the original."]),
    "Shell": ("Hollows the part, leaving walls of the given thickness; removed faces open it.",
              ["Parameters: the thickness; Faces to Remove: the faces that are opened; Shell outward "
               "adds the walls outside. Multi-thickness Settings: faces with their own thickness."]),
    "Draft": ("Tapers faces by an angle for mold release.",
              ["Type of Draft: Neutral Plane, Parting Line, Step Draft. Draft Angle, the Neutral Plane (the "
               "face or plane that stays) and the Faces to Draft; Reverse Direction flips the taper."]),
    "Rib": ("Adds a thin wall from an open sketch line to the part.",
            ["Parameters: thickness on one or both sides of the sketch line, the extrusion direction "
             "(parallel or normal to the sketch), Flip material side, Draft."]),
    "Plane": ("A reference plane from up to three references.",
              ["First, Second, Third Reference: a face, plane, edge, axis, vertex or sketch point; each "
               "shows its constraints (Parallel, Perpendicular, Coincident, Distance, Angle, Mid Plane). "
               "Flip offset puts the plane on the other side."]),
    "Axis": ("A reference axis from edges, faces, planes or points.",
             ["Selections: One Line/Edge/Axis, Two Planes, Two Points/Vertices, Cylindrical/Conical Face, "
              "Point and Face/Plane."]),
    "Point": ("A reference point.", ["Selections: Arc Center, Center of Face, Intersection, Projection, "
                                     "On point, Along curve distance or multiple reference point."]),
    "Coordinate System": ("A reference coordinate system.",
                          ["Selections: the origin, then the X, Y or Z axis direction; flip each axis."]),
    "Wrap": ("Wraps a sketch onto a face as embossed, debossed or scribed material.",
             ["Wrap Type: Emboss, Deboss, Scribe. Wrap Method: Analytical or Spline Surface. "
              "Wrap Parameters: the sketch, the face, the thickness; Reverse direction."]),
    "Scale": ("Scales the part about its centroid, the origin or a coordinate system.",
              ["Scale Parameters: Scale about, Uniform scaling (one factor) or X, Y, Z factors."]),
    "Slicing": ("Section sketches of the model at evenly spaced planes.",
                ["Slicing Plane: a plane or flat face to start from; Reverse direction. Slicing Parameters: "
                 "the number of slices and the spacing. Options: one 3D sketch, or a 2D sketch per slice."]),
    "Intersect": ("Intersects solids, surfaces and planes to make new bodies.",
                  ["Selections: the bodies, surfaces and planes; Create intersecting regions / internal "
                   "regions / both; Regions to Exclude; Merge result; Consume surfaces."]),
    "Delete Face": ("Deletes faces of the part: leave it open, patch the gap, or fill it.",
                    ["Selections: the faces. Options: Delete, Delete and Patch, Delete and Fill (Tangent fill)."]),
    "Thread": ("A cosmetic or cut thread on a cylindrical edge.",
               ["Thread Location: the circular edge, the start offset. Specification: type, size, pitch; "
                "Thread method: Cut thread or Extrude thread; right or left hand."]),
}


MORE = {
    "Helix Boss": ("Sweeps a profile sketch along a helix to add material (FreeCAD's Additive Helix).",
                   ["Pick the profile sketch, or a plane / flat face to sketch it on. Helix Parameters: the axis, "
                    "pitch (or height and turns), angle, left or right hand; Reverse flips the direction."]),
    "Helix Cut": ("Sweeps a profile along a helix to remove material.", ["As Helix Boss, taking material away."]),
    "Combine": ("Combines bodies: Add, Subtract or Common (FreeCAD's Boolean).",
                ["Operation Type: Add, Subtract, Common. Bodies to Combine: the other bodies; the active body "
                 "is the main one."]),
    "Pattern": ("A combined pattern of several transformations (FreeCAD's MultiTransform).",
                ["Transformations: add a Mirrored, Linear, Polar or Scaled step; each has its own values. "
                 "Features: what is patterned."]),
    "Sketch": ("The sketch being edited.",
               ["Draw with the Sketch tab tools; add relations and Smart Dimensions until the sketch turns "
                "black (fully defined). Exit Sketch (the corner check) keeps it; the cross discards changes."]),
    "Edit Sketch": ("Starts a sketch on a plane or a flat face.",
                    ["Click one of the three planes shown in the view, a reference plane, or a flat face of the "
                     "part; the sketch opens looking straight at it. Esc leaves without a sketch."]),
    "Advanced Hole": ("A hole built from near-side and far-side elements (counterbore, countersink, straight, tap).",
                      ["Near Side / Far Side Faces: the faces the hole starts from each side. Elements: add one "
                       "per step with its type, standard, size and depth; the flyout shows the stack."]),
    "Thread": None,
    "3D Texture": ("Turns a texture image on a face into displaced geometry (a mesh body).",
                   ["Body: the body to texture. Texture Settings: the appearance with the texture, offset "
                    "distance, maximum element size, refinement; Dynamic Help shows the mesh density."]),
    "Bounding Box": ("The smallest box round the part, as a reference feature.",
                     ["Options: Best fit or Custom plane (pick a face or plane); Include hidden bodies, surfaces. "
                      "The box's size goes to Custom Properties."]),
    "Grid System": ("A grid of reference planes and sketches for a structure.",
                    ["Draw the grid sketch; Levels: the height of each level, how many; Grid Components: the "
                     "balloon labels. Finishes with a folder of levels and grid planes."]),
    "Gusset": ("A triangular or polygonal web between two faces.",
               ["Selections: the two faces (or a corner). Profile: the distances along each face or a polygonal "
                "profile; Thickness: one or both sides; Location: where along the corner; Fillet the corners."]),
    "Rib": None,
    "Intersect": None,
    "Delete Hole": ("Removes a hole from a surface body by deleting its inner loop.",
                    ["Pick the edge of the hole on a surface; the surface is untrimmed across it."]),
    "Composite Curve": ("Joins curves, sketch segments and edges into one curve.",
                        ["Entities to Join: the curves, sketches and model edges, end to end."]),
    "Curve Through Reference Points": ("A curve through sketch points, vertices or reference points.",
                                       ["Through Points: the points in order; Closed curve joins the ends."]),
    "Projected Curve": ("Projects a sketch onto a face, or intersects two sketches' projections.",
                        ["Projection Type: Sketch on faces (the sketch and the faces) or Sketch on sketch (two "
                         "sketches on different planes). Reverse projection flips the direction; Bi-directional."]),
    "Split Line": ("Splits faces with a projected sketch, a silhouette or an intersection.",
                   ["Type of Split: Silhouette (a direction and the faces), Projection (a sketch and the faces to "
                    "split; Single direction, Reverse direction), Intersection (a plane or surface and the faces)."]),
    "Helix/Spiral": ("A helix or spiral curve from a circle sketch.",
                     ["Pick a circle sketch. Defined By: Pitch and Revolution, Height and Revolution, Height and "
                      "Pitch, or Spiral. Parameters: Constant or Variable pitch, the values, Reverse direction, "
                      "Start angle, Clockwise / Counterclockwise, Taper Helix."]),
    "Curve Driven Pattern": ("Repeats features along a curve.",
                             ["Direction 1: the curve (a sketch, an edge), the number of instances and spacing (or "
                              "Equal spacing), Curve method (Transform curve / Offset curve), Alignment method "
                              "(Tangent to curve / Align to seed). Direction 2 for a second curve. Features and "
                              "Faces / Bodies: what is repeated; Instances to Skip."]),
    "Sketch Driven Pattern": ("Repeats features at the points of a sketch.",
                              ["Selections: the point sketch; Reference point: Centroid or Selected point of the "
                               "seed. Features and Faces / Bodies: what is repeated."]),
    "Table Driven Pattern": ("Repeats features at X-Y positions from a table.",
                             ["Coordinate system: the origin of the table; Points: the X, Y of each instance "
                              "(Browse to load, Save to keep). Geometry pattern; Features / Bodies to Copy."]),
    "Fill Pattern": ("Fills a face or sketch region with instances.",
                     ["Fill Boundary: the face or sketch region. Pattern Layout: Perforation, Circular, Square or "
                      "Polygon with its spacing, margins and angle. Features and Faces / Seed Cut: the seed, or a "
                      "generated circle, square, diamond or polygon with its size."]),
    "Variable Pattern": ("Repeats a feature with dimensions that change per instance.",
                         ["Features to Pattern: the feature. Create Pattern Table: a row per instance, a column per "
                          "dimension; type the values, Update Preview to see them. Instances to Skip."]),
    "Variable Size Fillet": ("A fillet whose radius changes along the edge.",
                             ["Items To Fillet: the edges; Variable Radius Parameters: a radius at each control "
                              "point (click the callouts in the view), Set All / Set Unassigned, the transition "
                              "(Smooth or Straight); add control points along the edge with the instances count."]),
    "Face Fillet": ("A fillet between two sets of faces that need not share an edge.",
                    ["Face Set 1 and Face Set 2; Fillet Parameters: the radius or Hold line (a width defined by "
                     "an edge), Curvature continuous, Constant width; Help point when the fillet is ambiguous."]),
    "Full Round Fillet": ("A fillet that replaces a middle face with a tangent round.",
                          ["Face Set 1 (a side), Center Face Set (the face removed), Face Set 2 (the other side)."]),
    "Wrap": None, "Scale": None, "Slicing": None, "Delete Face": None,
    "Surface-Extrude": ("Extrudes a sketch as a surface.",
                        ["Direction 1: End Condition and depth; Direction 2; Cap ends when the profile is closed."]),
    "Surface-Revolve": ("Revolves a sketch as a surface.", ["Axis of Revolution; Direction1: the angle."]),
    "Surface-Sweep": ("Sweeps a profile along a path as a surface.",
                      ["Profile and Path; Guide Curves; Options (orientation, twist); Start and End Tangency."]),
    "Surface-Loft": ("Lofts between profiles as a surface.",
                     ["Profiles in order; Start/End Constraints; Guide Curves; Centerline Parameters; Options."]),
    "Boundary-Surface": ("A surface between curves in two directions.",
                         ["Direction 1 and Direction 2: the curves; the tangency type at each; Options and Preview."]),
    "Filled Surface": ("A surface patch that fills a boundary of edges or curves.",
                       ["Patch Boundary: the edges, sketch segments or curves; Edge settings: Contact, Tangent or "
                        "Curvature to the faces round them; Constraint Curves; Options: Fix up boundary, Merge "
                        "result, Create solid, Reverse direction."]),
    "Planar Surface": ("A flat surface from a closed sketch or a set of coplanar edges.",
                       ["Bounding Entities: a closed sketch, a planar set of edges or a planar curve."]),
    "Surface-Offset": ("A surface offset from faces by a distance.",
                       ["Offset Parameters: the faces or surfaces and the distance; Flip Offset Direction; "
                        "a distance of 0 copies the faces."]),
    "Mid-Surface": ("A surface midway between pairs of faces.",
                    ["Face Pairs: Find Face Pairs at a recognition threshold, or pick each pair; Position "
                     "(0 to 100 per cent between the faces); Knit surfaces."]),
    "Ruled Surface": ("A ruled surface from edges, in a chosen direction.",
                      ["Type: Tangent to Surface, Normal to Surface, Tapered to Vector, Perpendicular to Vector, "
                       "Sweep. Distance/Direction: the distance, the vector, the angle; Edge Selection: the edges; "
                       "Alternate Side, Trim and knit, Connecting surface."]),
    "Radiate Surface": ("A surface that radiates from edges parallel to a plane.",
                        ["Radiate Parameters: the reference plane (direction), the edges, the distance; "
                         "Propagate to tangent faces; Flip."]),
    "Surface-Knit": ("Joins surfaces into one surface body, or a solid when closed.",
                     ["Selections: the surfaces and faces; Create solid when the result is closed; Merge entities; "
                      "Gap Control: the gaps to close."]),
    "Extend Surface": ("Extends a surface at its edges.",
                       ["Edges/Faces to Extend; End Condition: Distance, Up to point, Up to surface; Extension "
                        "Type: Same surface or Linear."]),
    "Trim Surface": ("Trims a surface with a sketch, plane or another surface.",
                     ["Trim Type: Standard (a trim tool, then Keep or Remove selections) or Mutual (the surfaces "
                      "trim each other). Surface Split Options: Split all, Natural, Linear."]),
    "Untrim Surface": ("Puts back the trimmed-away part of a face.",
                       ["Selections: the faces or edges; Untrim the whole face or Extend edges; Merge with original."]),
    "Thicken": ("Turns a surface into a solid of the given thickness.",
                ["Thicken Parameters: the surface, the side (Side 1, Both sides, Side 2), the thickness; "
                 "Merge result; Create solid from enclosed volume when the surface is closed."]),
    "Thickened Cut": ("Removes a thickened surface from the part.", ["As Thicken, cutting material; Feature Scope."]),
    "Cut with Surface": ("Cuts the part with a surface or plane.",
                         ["Surface Cut Parameters: the surface or plane; the arrow (Flip cut) shows the side removed; "
                          "Feature Scope for several bodies."]),
    "Replace Face": ("Replaces faces of the part with a surface.",
                     ["Replace Parameters: Target faces for replacement, then the Replacement surface(s)."]),
    "Markup": ("Draws ink and notes over the model view.",
               ["Draw with the pen, pick a color and width, erase; the markup is kept with the view."]),
    "Insert Component": ("Inserts a part or assembly into the assembly.",
                         ["Part/Assembly to Insert: Browse or pick an open document; click in the view to place it "
                          "(the first component is fixed at the origin). Options: Start command when creating new "
                          "assembly, Graphics preview, Make virtual, Envelope."]),
}

for _k, _v in MORE.items():
    if _v is not None and _k not in HELP:
        HELP[_k] = _v


# the feature Surface-Knit1): both find the same help
for _title, _feature in (("Knit Surface", "Surface-Knit"), ("Offset Surface", "Surface-Offset"),
                         ("Fill Surface", "Filled Surface")):
    if _feature in HELP and _title not in HELP:
        HELP[_title] = HELP[_feature]

GENERIC = ("This PropertyManager sets up the feature named in its title.",
           ["Fill the groups from the top down: the selection boxes take what you click in the graphics "
            "area or the tree; the pink arrow in the view flips a direction; drag an arrow to change a value.",
            "OK (the check) makes the feature; Cancel (the cross) leaves the part as it was. Enter is OK and "
            "Esc is Cancel in the graphics area; right-click there for OK and Cancel too.",
            "Keep Visible (the pin) starts the same feature again after OK."])


def _esc(text):
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _tip(native, title):
    """The catalog's one-line description of the command, by its FreeCAD name or its label."""
    try:
        from . import catalog
        for cmd in catalog.ALL:
            if native and native in cmd.natives:
                return cmd.tip or ""
        for cmd in catalog.ALL:
            if cmd.label == title:
                return cmd.tip or ""
    except Exception as _fw_err:
        _fw_log("pmhelp.py:297", _fw_err)
    return ""


def _groups(view):
    """[(group title, [field words])] read from the open page."""
    out = []
    if view is None:
        return out
    seen = set()
    for label in view.findChildren(QtWidgets.QWidget):
        try:
            if label.property("class") != "header" or not hasattr(label, "text") or not label.isVisible():
                continue
            title = label.text().strip()
        except RuntimeError:
            continue
        # the group: the header's ActionGroup (its frame's parent); else the header's parent
        group = label.parentWidget()
        while group is not None and group.parentWidget() is not None and \
                "ActionGroup" not in group.metaObject().className():
            group = group.parentWidget()
            if "ActionGroup" in group.metaObject().className():
                break
        if group is None or id(group) in seen or not title:
            continue
        seen.add(id(group))
        words = []
        for w in group.findChildren(QtWidgets.QWidget):
            try:
                if not w.isVisible():
                    continue
                text = ""
                if isinstance(w, (QtWidgets.QCheckBox, QtWidgets.QRadioButton)):
                    text = w.text()
                elif isinstance(w, QtWidgets.QLabel) and w.metaObject().className() == "QLabel":
                    text = w.text() or w.toolTip()
                elif isinstance(w, QtWidgets.QComboBox):
                    text = ", ".join(w.itemText(i) for i in range(min(w.count(), 8)))
                elif isinstance(w, QtWidgets.QToolButton) and w.toolTip() and not w.text():
                    text = w.toolTip()
                text = text.strip().rstrip(":")
                if text and "<" not in text and len(text) < 80 and text not in words:
                    words.append(text)
            except RuntimeError as _fw_err:
                _fw_log("pmhelp.py:342", _fw_err)
        if title:
            out.append((title, words))
    return out


def html(view, title, native=None):
    found = HELP.get(title) or HELP.get((title or "").rstrip("0123456789"))     # "Edge-Flange1" -> Edge-Flange
    if found is None:
        try:
            from . import cmdhelp
            found = cmdhelp.title_steps(title) or cmdhelp.title_steps((title or "").rstrip("0123456789"))     # the command of that name's own page text
        except Exception as _fw_err:
            _fw_log("pmhelp.py:cmdhelp", _fw_err)
    what, steps = found or GENERIC
    tip = _tip(native, title)
    parts = ["<h2>%s</h2>" % _esc(title)]
    if tip and tip != what:
        parts.append("<p><i>%s</i></p>" % _esc(tip))
    parts.append("<p>%s</p>" % _esc(what))
    parts.append("<ul>%s</ul>" % "".join("<li>%s</li>" % _esc(s) for s in steps))
    groups = _groups(view)
    if groups:
        parts.append("<h3>On this page</h3><dl>")
        for group, words in groups:
            parts.append("<dt><b>%s</b></dt><dd>%s</dd>" % (_esc(group), _esc(", ".join(words)) or "&nbsp;"))
        parts.append("</dl>")
    parts.append("<p><a href='page:commands'>All commands</a> | <a href='page:keys'>Keyboard shortcuts</a>")
    if native:
        parts.append(" | <a href='fchelp:%s'>FreeCAD's page for %s</a>" % (_esc(native), _esc(native)))
    parts.append("</p>")
    return "".join(parts)


_window = []


def show(view, title, native=None):
    ""
    try:
        from . import helpguide
        guide = helpguide.show_pm(title)
        if guide is not None:
            return guide
    except Exception as _fw_err:
        _fw_log("pmhelp.py:guide", _fw_err)
    from . import helpmenu
    win = _window[0] if _window and helpmenu.alive_window(_window[0]) else None
    if win is None:
        win = helpmenu.HelpWindow("home")
        _window[:] = [win]
    win.current = "pm:" + title
    win.view.setHtml(html(view, title, native))
    win.setWindowTitle("FreeCAD Help - %s" % title)
    win.show()
    win.raise_()
    return win
