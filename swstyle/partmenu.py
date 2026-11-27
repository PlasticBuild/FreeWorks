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

import math

import os
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import paths, rcmenus
from .widgets import alive

Qt = QtCore.Qt
PARAM = "PartMenu"

T_FACE, T_EDGE, T_VERTEX, T_BODY = "Face", "Edge", "Vertex", "Body"
T_PLANE_SCREEN = "Create Plane Parallel to Screen"
T_CHANGE_TRANSPARENCY = "Change Transparency"
T_ISOLATE = "Isolate"
T_EXPORT_DXF = "Export to DXF / DWG"
FEATURE_KEYS = ("Comment", "ParentChild", "Delete", "Favorites", "SaveSelection")
ROW_TOP = ("EditFeature", "EditFeatureSketch", "OpenDrawing", "Suppress", "Rollback", "EditAppearance",
           "CopyAppearance", "PasteAppearance")
ROW_SECOND = ("SelectOther", "Sketch", "HideSelection", "ZoomSelection", "NormalTo", "Fillet", "Chamfer")
ROW_TOP_SHEET_METAL = ("EditFeature", "OpenDrawing", "Suppress", "EditAppearance", "CopyAppearance", "PasteAppearance")
ROW_EDGE = ("SelectOther", "HideSelection", "ZoomSelection", "NormalTo", "Fillet", "Chamfer")
ROW_EMPTY = ("BoxSelect", "LassoSelect", "SelectionFilter", "SelectOther", "Select", "MagnifiedSelection")


def enabled():
    return paths.params().GetBool(PARAM, True)


# --------------------------------------------------------------------------- where we are
def _view():
    try:
        return Gui.ActiveDocument.ActiveView
    except Exception:
        return None


def _here():
    """A part in the active view, nothing in edit, no PropertyManager, no 3D sketch."""
    if not enabled():
        return False
    try:
        if Gui.ActiveDocument is None:
            return False
        edit = Gui.ActiveDocument.getInEdit()

        # plain assembly window, not an edit, so our menu shows (a task dialog still stops it below)
        if edit is not None and type(edit).__name__ != "ViewProviderAssembly":
            return False
        if Gui.Control.activeDialog():
            return False
    except Exception:
        return False
    try:
        from . import sketch3d
        if sketch3d.editing():
            return False
    except Exception as _fw_err:
        _fw_log("partmenu.py:99", _fw_err)
    return True


def in_assembly():
    """The document of the active 3D view is an assembly."""
    try:
        from . import asmcore
        doc = Gui.ActiveDocument.Document if Gui.ActiveDocument is not None else App.ActiveDocument
        return asmcore.assembly_of(doc) is not None
    except Exception:
        return False


def under_pointer(at=None):
    """(doc, object, element path, (x, y, z)) of the model under the pointer or at, else None."""
    view = _view()
    if view is None:
        return None
    try:
        where = at if at is not None else view.getCursorPos()
        if hasattr(where, "x"):
            where = (where.x(), where.y())
        info = view.getObjectInfo(where)
    except Exception:
        return None
    if not info or not info.get("Object"):
        return None
    _vertex_first(view, where, info)
    xyz = (info.get("x", 0.0), info.get("y", 0.0), info.get("z", 0.0))
    parent = info.get("ParentObject")
    if parent is not None and getattr(parent, "TypeId", "") == "Assembly::AssemblyObject" and info.get("SubName"):
        # an assembly: the pick from the assembly down (Component.Fillet.Face5), not the part's own
        return (parent.Document.Name, parent.Name, info["SubName"], xyz)
    return (info.get("Document"), info.get("Object"), info.get("Component", "") or "", xyz)


def _leaf(sub):
    return sub.split(".")[-1] if sub else ""


def _vertex_first(view, where, info):
    ""

    try:
        comp = info.get("Component", "") or ""
        if not comp.startswith(("Edge", "Face")):
            return
        import Part
        top = info.get("ParentObject") or App.getDocument(info["Document"]).getObject(info["Object"])
        path = info.get("SubName") if info.get("ParentObject") is not None else comp
        prefix = path[:-len(comp)] if path and path.endswith(comp) else ""
        owner = Part.getShape(top, prefix)
        element = owner.getElement(comp)
        if len(element.Vertexes) > 64:
            return
        radius = float(App.ParamGet("User parameter:BaseApp/Preferences/View").GetFloat("PickRadius", 5.0))
        best = None
        for v in element.Vertexes:
            x, y = view.getPointOnViewport(v.Point)
            d = ((x - where[0]) ** 2 + (y - where[1]) ** 2) ** 0.5
            if d <= radius and (best is None or d < best[0]):
                best = (d, v)
        if best is None:
            return
        index = next((i for i, v in enumerate(owner.Vertexes) if v.isSame(best[1])), None)
        if index is None:
            return
        name = "Vertex%d" % (index + 1)
        info["Component"] = name
        if info.get("SubName"):
            info["SubName"] = info["SubName"][:-len(comp)] + name
        p = best[1].Point
        info["x"], info["y"], info["z"] = p.x, p.y, p.z
    except Exception as _fw_err:
        _fw_log("partmenu.py:vertex-first", _fw_err)


def owner_feature(doc, name, sub):
    """The feature that made the picked face (PartDesign: the body's feature named in the path)."""
    try:
        d = App.getDocument(doc)
        obj = d.getObject(name)
        parts = [p for p in sub.split(".")[:-1] if p and not p.startswith(";")]
        for p in reversed(parts):
            o = d.getObject(p)
            if o is not None:
                obj = o
                break
        if obj.TypeId == "PartDesign::Body":
            obj = obj.Tip or obj
        try:
            from . import contextbar
            found = contextbar.owner_feature(obj, sub)
            if found is not None:
                return found
        except Exception as _fw_err:
            _fw_log("partmenu.py:158", _fw_err)
        return obj
    except Exception:
        return None


def body_of(obj):
    try:
        b = obj.getParentGeoFeatureGroup()
        return b if b is not None and b.TypeId == "PartDesign::Body" else None
    except Exception:
        return None


def pick(item):
    ""
    doc, name, sub, xyz = item
    for s in Gui.Selection.getSelectionEx("", 0):
        if s.DocumentName != doc or s.ObjectName != name:
            continue
        subs = list(s.SubElementNames) or [""]
        # the same element, or a whole object/component that holds it (a picked component, then a

        if any(p == sub or (p.endswith(".") and sub.startswith(p)) for p in subs):
            return
    try:
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc, name, sub, *xyz)
    except Exception as _fw_err:
        _fw_log("partmenu.py:187", _fw_err)


# --------------------------------------------------------------------------- the items
def create_plane_parallel_to_screen(item):
    """A plane through the right-clicked point, facing the screen."""
    view = _view()
    feature = owner_feature(*item[:3])
    body = body_of(feature) if feature is not None else None
    doc = App.getDocument(item[0])
    if view is None or doc is None:
        return None
    at = App.Vector(*item[3])
    rot = view.getCameraOrientation()
    doc.openTransaction(T_PLANE_SCREEN)
    try:
        if body is not None:
            plane = body.newObject("PartDesign::Plane", "DatumPlane")
            plane.MapMode = "Deactivated"
            inv = body.getGlobalPlacement().inverse()
            plane.Placement = inv.multiply(App.Placement(at, rot))
        else:
            plane = doc.addObject("Part::Plane", "Plane")
            plane.Length = plane.Width = 50
            plane.Placement = App.Placement(at, rot).multiply(App.Placement(App.Vector(-25, -25, 0), App.Rotation()))
        n = 1 + sum(1 for o in doc.Objects if o.Label.startswith("Plane") and o is not plane)
        plane.Label = "Plane%d" % n
        doc.commitTransaction()
    except Exception as error:
        doc.abortTransaction()
        App.Console.PrintWarning("FreeCAD: %s: %s\n" % (T_PLANE_SCREEN, error))
        return None
    doc.recompute()
    return plane


def export_dxf(item):
    """Export to DXF / DWG: the picked face (or the face of the picked edge) as a DXF file."""
    try:
        d = App.getDocument(item[0])
        obj = d.getObject(item[1])
        shape = obj.getSubObject(item[2]) if item[2] else obj.Shape
    except Exception:
        shape = None
    if shape is None or shape.isNull():
        return None

    folder = os.path.dirname(d.FileName) if d.FileName else os.path.expanduser("~")
    stem = os.path.splitext(os.path.basename(d.FileName))[0] if d.FileName else d.Label
    path, _f = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), T_EXPORT_DXF,
                                                     os.path.join(folder, stem + ".dxf"), "DXF (*.dxf)")
    if not path:
        return None
    if not path.lower().endswith(".dxf"):
        path += ".dxf"
    planar = item[2].startswith("Face") and shape.ShapeType == "Face" and shape.Surface.__class__.__name__ == "Plane"
    if planar:

        try:
            from . import smdxf
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(d.Name, obj.Name, item[2])
            body = obj if obj.TypeId == "PartDesign::Body" else next(
                (b for b in obj.InList if b.TypeId == "PartDesign::Body"), obj)
            if smdxf.start_part(d, path, [body]) is not None:
                return path
        except Exception as _fw_err:
            _fw_log("partmenu.py:export_dxf panel", _fw_err)
    tmp = d.addObject("Part::Feature", "FWExportDXF")
    try:
        tmp.Shape = shape
        import importDXF
        importDXF.export([tmp], path)
    except Exception as error:
        App.Console.PrintError("FreeCAD: %s: %s\n" % (T_EXPORT_DXF, error))
        path = None
    finally:
        d.removeObject(tmp.Name)
    return path


def isolate(feature):
    body = body_of(feature) or feature
    try:
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(body)
    except Exception as _fw_err:
        _fw_log("partmenu.py:257", _fw_err)
    rcmenus.run_key("Isolate")


def _feature_items(feature, sheet_metal=False, flat=False):
    """Comment >, Parent/Child..., [Go To Feature (in Tree)], Configure Feature, Delete...,
    Add to Favorites, Save Selection > under "Feature (name)" (screen read 2, D1, B3, B4a). A
    folded sheet metal face has no Delete...; the Flat-Pattern adds Insert bend notes and
    Reorder Bends."""
    from . import partextras as px
    try:
        from . import fmmenu
        rows = {r[0]: r for r in fmmenu.entries(rcmenus.shell(), feature) if r[0]}
    except Exception:
        rows = {}
    out = [rcmenus.header("Feature (%s)" % feature.Label, "HeaderFeature")]

    def tree(key):
        r = rows.get(key)
        if r is None:
            return None
        _k, label, run, ok = r
        if hasattr(run, "fill"):
            return rcmenus.dynamic(key, label, run.fill)
        return rcmenus.action(key, label, run, enabled=ok)

    out += [tree("HideAllDimensions"), tree("Comment"), tree("ParentChild"),
            rcmenus.action("GoToFeature", px.T_GO_TO_FEATURE, lambda: px.go_to_feature(feature), more=True),
            rcmenus.action("ConfigureFeature", px.T_CONFIGURE, lambda: px.configure_feature(feature))]
    if not sheet_metal or flat:
        out.append(tree("Delete"))
    out += [tree("Favorites"), tree("SaveSelection")]
    if flat:
        out += [rcmenus.action("BendNotes", px.T_BEND_NOTES, lambda: px.insert_bend_notes(feature)),
                rcmenus.action("ReorderBends", px.T_REORDER_BENDS, lambda: px.reorder_bends(feature))]
    out += library_items(feature)
    return out


def library_items(feature):
    """A face of a library feature's member: the instance's own section, "Library Feature (name)" with Edit,
    Update and Dissolve Library Feature (libfeature, the features thread's)."""
    try:
        from . import libfeature
        row = libfeature.row_of(feature)
        if row is None:
            return []
        rows = libfeature.rc_entries(feature)
    except Exception:
        return []
    out = [rcmenus.header("Library Feature (%s)" % row.Label, "HeaderLibraryFeature")]
    for key, label, run, ok in rows:
        out.append(rcmenus.action(key, label, run, enabled=ok))
    return out


def _change_transparency(feature):
    try:
        from . import fmmenu
        fmmenu.change_transparency(feature)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s: %s\n" % (T_CHANGE_TRANSPARENCY, error))


def _command(name, key, text):
    ""
    try:
        if name not in Gui.listCommands():
            return None
    except Exception:
        return None
    return rcmenus.action(key, text, lambda: Gui.runCommand(name, 0), command=name)


def edit_scene():
    """Edit Scene: the scene (background) picked from the Appearances pane's scenes."""
    from . import style
    order = list(style.SCENE_MENU) + list(style.SCENE_EXTRAS)
    labels = [style.SCENES[i][0] for i in order]
    choice, ok = QtWidgets.QInputDialog.getItem(Gui.getMainWindow(), "Edit Scene", "Scene:", labels, 0, False)
    if ok and choice in labels:
        style.apply_scene(order[labels.index(choice)])
        return choice
    return None


def selection_filter():
    """Selection Filter (F5): the Selection Filter toolbar on or off."""
    for name in ("SWStyle_SelectionFilterToolbar",):
        try:
            if name in Gui.listCommands():
                Gui.runCommand(name, 0)
                return True
        except Exception as _fw_err:
            _fw_log("partmenu.py:351", _fw_err)
    return False


T_FIND_SIMILAR = "Find Similar in Design Library"


def _find_similar():
    ""

    from . import taskpane
    taskpane.open_tab(1)


def _featureworks(feature):
    from . import partextras as px
    return rcmenus.submenu("FeatureWorks", px.T_FEATUREWORKS, [
        rcmenus.action("RecognizeFeatures", px.T_RECOGNIZE, lambda: px.recognize_features(feature)),
        rcmenus.action("FeatureWorksOptions", px.T_FW_OPTIONS, px.featureworks_options)])


def _exit_flatten(body):
    from . import partextras as px
    return rcmenus.action("ExitFlatten", px.T_EXIT_FLATTEN, lambda: px.flatten(body, False),
                          icon=_icon("SheetMetal_Unfold"))


def _icon(name):
    try:
        icon = QtGui.QIcon(Gui.getIcon(name))
        return None if icon.isNull() else icon
    except Exception:
        return None


def flat_body(doc=None):
    """The sheet metal body shown flat in the active document, else None."""
    try:
        from . import smflatten
        body = smflatten._body(doc)
        return body if body is not None and smflatten.is_flat(doc) else None
    except Exception:
        return None


def is_curve(feature):
    """True for a feature whose shape is only curves (no faces, no solid)."""
    try:
        shape = feature.Shape
        return not shape.isNull() and bool(shape.Edges) and not shape.Faces
    except Exception:
        return False


def dimxpert_items(obj):
    ""




    try:
        from . import mbd
        if obj is None or not mbd.is_pmi(obj):
            return None
    except Exception:
        return None
    import types
    from . import rcextras, dimmenu
    try:
        at = App.Vector(obj.TextPosition)
    except Exception:
        at = App.Vector()
    d = types.SimpleNamespace(obj=obj, prop="PMI", point=at, index=None)
    mark, opts, view = dimmenu._feature_flag_items(d)
    value = getattr(obj, "Text", "") or ""

    def hide():
        if obj.ViewObject is not None:
            obj.ViewObject.Visibility = False
    out = [rcmenus.action("SelectOther", rcmenus.T_SELECT_OTHER, rcmenus.select_other),
           rcmenus.selection_tools_menu(), rcmenus.zoom_menu(), rcextras.set_view_menu(True), rcmenus.recent_menu(),
           rcmenus.header("Dimension (%s(%s))" % (obj.Label, value), "HeaderDimension"),
           mark, opts, rcmenus.entry("SmartDimension", "Smart Dimension"), dimmenu._annotations(d),
           rcmenus.header(rcmenus.T_SELECTED_N, "HeaderSelected"),
           rcmenus.action("Hide", rcmenus.T_HIDE, hide), view]
    return [i for i in out if i is not None]


def items(item):
    """The menu for item (from under_pointer), or the empty-space menu for None (screen read 2:
    D1 face, D2 edge, D3 vertex, D4 empty space; B3 sheet metal bend face, B4 Flatten on).
    [..] = only in the long form."""
    from . import partextras as px, rcextras
    flat = flat_body()
    if item is None:
        out = [_exit_flatten(flat) if flat is not None else None,
               rcmenus.entry("ZoomFit", "Zoom to Fit"), rcmenus.entry("ZoomArea", "Zoom to Area"),
               rcmenus.action("ZoomInOut", "Zoom In/Out", lambda: start_mode("zoom")),
               rcmenus.action("RotateView", "Rotate View", lambda: start_mode("rotate")),
               rcmenus.action("Pan", "Pan", lambda: start_mode("pan")),
               rcmenus.action("RollView", "Roll View", lambda: start_mode("roll")),
               rcmenus.entry("RotateAboutSceneFloor", "Rotate About Scene Floor"),
               rcextras.set_view_menu(True),
               rcmenus.entry("ViewOrientation", "View Orientation..."),
               rcmenus.action("EditScene", "Edit Scene", edit_scene),
               _command("SWStyle_OpenDrawing", "OpenDrawing", "Open Drawing"),
               rcmenus.recent_menu(),
               rcmenus.action("ContourSelect", rcmenus.T_CONTOUR_SELECT, px.contour_select_tool, more=True)]
        return [i for i in out if i is not None]
    feature = owner_feature(*item[:3])
    leaf = _leaf(item[2])
    pmi = dimxpert_items(feature)
    if pmi is not None:
        return pmi
    try:
        from . import featurerc
        if feature is not None and featurerc.is_reference(feature):
            # a plane, axis or point in the view: its Feature items, no Body section
            return [i for i in [rcmenus.selection_tools_menu(), rcmenus.zoom_menu(), rcmenus.recent_menu()]
                    + featurerc.reference_items(feature) if i is not None]
    except Exception as error:
        App.Console.PrintLog("FreeCAD: reference menu: %s\n" % error)
    sm_body = px.sheet_metal_body(feature) if feature is not None else None
    on_flat = sm_body is not None and px.flat_on(sm_body)
    out = []
    if leaf.startswith("Face"):
        if on_flat:
            out.append(_exit_flatten(sm_body))
        elif px.has_tangent(item):
            out.append(rcmenus.action("SelectTangency", rcmenus.T_SELECT_TANGENCY, lambda: px.select_face_tangency(item)))
        out += [rcmenus.action("SelectConnected", px.T_SELECT_CONNECTED, lambda: px.select_connected_faces(item), more=True),
                rcmenus.action("ContourSelect", rcmenus.T_CONTOUR_SELECT, lambda: px.contour_select_tool(item), more=True)]
    elif leaf.startswith("Edge"):
        edge = item[:3]
        out += [rcmenus.action("SelectMidpoint", rcmenus.T_SELECT_MIDPOINT, lambda: rcmenus.select_edge_midpoint(edge)),
                rcmenus.action("SelectLoop", rcmenus.T_SELECT_LOOP, lambda: rcmenus.select_loop(edge))]
        if px.edge_has_tangent(item):
            out.append(rcmenus.action("SelectTangency", rcmenus.T_SELECT_TANGENCY, lambda: px.select_edge_tangency(item)))
        if rcmenus.can_select_partial_loop():

            out.append(rcmenus.action("SelectPartialLoop", rcmenus.T_SELECT_PARTIAL_LOOP, rcmenus.select_partial_loop))
        out += [rcmenus.action("ContourSelect", rcmenus.T_CONTOUR_SELECT, lambda: px.contour_select_tool(item), more=True)]
    elif leaf.startswith("Vertex"):

        out += [rcmenus.action("SelectOther", rcmenus.T_SELECT_OTHER, rcmenus.select_other),
                rcmenus.action("ContourSelect", rcmenus.T_CONTOUR_SELECT, lambda: px.contour_select_tool(item), more=True)]
    out += [rcmenus.selection_tools_menu(), rcmenus.zoom_menu(), rcextras.set_view_menu(True)]
    out.append(rcmenus.recent_menu())
    if leaf.startswith("Face"):
        out += [rcmenus.header(T_FACE, "HeaderFace"),
                rcmenus.entry("Sketch3DOnPlane", "3D Sketch On Plane", more=True),
                rcmenus.entry("LiveSection", "Live Section Plane", more=True),
                rcmenus.entry("Curvature", "Curvature", more=True),
                rcmenus.entry("Zebra", "Zebra Stripes...", more=True),
                rcmenus.entry("SurfaceCurvatureCombs", "Surface Curvature Combs...", more=True),
                rcmenus.entry("DeleteFace", "Delete...", more=True),
                rcmenus.entry("MoveFace", "Move...", more=True),
                rcmenus.action("FaceProperties", px.T_FACE_PROPERTIES, lambda: px.entity_properties(item, "Face"), more=True),
                rcmenus.action("ChangeTransparency", T_CHANGE_TRANSPARENCY, lambda: _change_transparency(feature),
                               enabled=feature is not None),
                rcmenus.action("PlaneParallelToScreen", T_PLANE_SCREEN, lambda: create_plane_parallel_to_screen(item))]
        if feature is not None:
            out += _feature_items(feature, sheet_metal=sm_body is not None, flat=on_flat)
    elif leaf.startswith("Edge"):
        out += [rcmenus.header(T_EDGE, "HeaderEdge"),
                rcmenus.action("EdgeProperties", px.T_EDGE_PROPERTIES, lambda: px.entity_properties(item, "Edge"), more=True),
                rcmenus.action("PlaneParallelToScreen", T_PLANE_SCREEN, lambda: create_plane_parallel_to_screen(item))]
    if feature is None:
        return [i for i in out if i is not None]
    if is_curve(feature):

        # curve is not a body)
        out += _feature_items(feature)
        return [i for i in out if i is not None]
    out.append(rcmenus.header(T_BODY, "HeaderBody"))
    if leaf.startswith("Vertex"):
        out.append(rcmenus.action("HideBody", "Hide", lambda: px.hide_body(feature)))
        return [i for i in out if i is not None]
    out += [rcmenus.action("DeleteBody", "Delete...", lambda: px.delete_body(item), more=True),
            rcmenus.action("Isolate", T_ISOLATE, lambda: isolate(feature))]
    if leaf.startswith("Face") and sm_body is not None and not on_flat:
        out += [rcmenus.action("Flatten", px.T_FLATTEN, lambda: px.flatten(sm_body, True)),
                rcmenus.action("ToggleFlatDisplay", px.T_TOGGLE_FLAT, lambda: px.toggle_flat_display(sm_body))]
    out.append(rcmenus.action("BodyProperties", px.T_BODY_PROPERTIES, lambda: px.body_properties(feature), more=True))
    if leaf.startswith("Face"):
        out += [rcmenus.action("ExportDXF", T_EXPORT_DXF, lambda: export_dxf(item)), _featureworks(feature)]
        if sm_body is None:     # pkg232: a sheet metal body's face menu has no Find Similar (reads B3, B4a)
            out.append(rcmenus.action("FindSimilarPartSupply", T_FIND_SIMILAR, _find_similar))
    return [i for i in out if i is not None]


T_NORMAL_TO = "Normal To"


def edge_normal(obj, sub):
    """The view direction for Normal To on an edge: a circle's or arc's axis, else the normal of a
    flat face the edge bounds, else the normal of the plane the edge lies in. None when there is none."""
    try:
        edge = obj.getSubObject(sub)       # in global coordinates
        owner = sub.rsplit(".", 1)[0] + "." if "." in sub else ""
        shape = obj.getSubObject(owner) if owner else obj.Shape
        if not owner:
            shape = shape.copy()
            shape.transformShape(obj.getGlobalPlacement().toMatrix())
    except Exception:
        return None
    if edge is None or not hasattr(edge, "Curve"):
        return None
    axis = getattr(edge.Curve, "Axis", None)
    if axis is not None and edge.Curve.__class__.__name__ in ("Circle", "Ellipse"):
        return axis
    try:
        for face in shape.ancestorsOfType(edge, __import__("Part").Face):
            if face.Surface.__class__.__name__ == "Plane":
                u, v = face.Surface.parameter(edge.CenterOfMass)
                return face.normalAt(u, v)
    except Exception as _fw_err:
        _fw_log("partmenu.py:567", _fw_err)
    try:
        mid = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2.0)
        for face in shape.Faces:
            if face.Surface.__class__.__name__ == "Plane" and face.distToShape(edge)[0] < 1e-6 \
                    and abs(face.Surface.projectPoint(mid).distanceToPoint(mid)) < 1e-6:
                u, v = face.Surface.parameter(mid)
                return face.normalAt(u, v)
    except Exception as _fw_err:
        _fw_log("partmenu.py:576", _fw_err)
    try:
        plane = edge.findPlane()
        if plane is not None:
            return plane.Axis
    except Exception as _fw_err:
        _fw_log("partmenu.py:582", _fw_err)
    return None


def normal_to_edge(obj, sub):
    n = edge_normal(obj, sub)
    if n is None:
        return
    view = Gui.ActiveDocument.ActiveView
    view.setCameraOrientation(App.Rotation(App.Vector(0, 0, 1), n))
    Gui.SendMsgToActiveView("ViewSelection")


def edge_normal_entry(shell, obj, sub):
    """Normal To on an edge (screen read 2 D2): the view turns to look straight at the edge's plane."""
    from . import contextbar
    if edge_normal(obj, sub) is None:
        return None
    try:
        icon = shell.binding("NormalTo").icon()
    except Exception:
        icon = QtGui.QIcon()
    return contextbar.Entry("NormalTo", T_NORMAL_TO, icon, contextbar._tip(T_NORMAL_TO, "Looks straight at the edge's plane"),
                            lambda o=obj, s=sub: normal_to_edge(o, s))


def kind_is_edge(sub):
    return bool(sub) and sub.split(".")[-1].startswith("Edge")


def _select_other_entry():
    from . import rcextras, contextbar
    return contextbar.Entry("SelectOther", rcmenus.T_SELECT_OTHER, rcextras._icon(rcmenus.T_SELECT_OTHER, "SELECT_OTHER"),
                            rcextras._tip(rcmenus.T_SELECT_OTHER, rcmenus.T_SELECT_OTHER_TIP), rcmenus.select_other)


def row(item):
    """The context toolbar over the menu (screen read 2): two lines on a face (sheet metal: no
    Edit Sketch, no Rollback), one line on an edge, none on a vertex, one line in empty space
    (Previous Selection once something was picked before)."""
    sh = rcmenus.shell()
    if sh is None:
        return None
    from . import rcextras, contextbar, partextras as px
    if item is None:
        line = []
        for k in ROW_EMPTY:
            if k == "SelectionFilter":
                line.append(contextbar.Entry(k, "Selection Filters", rcextras._icon("Selection Filter", "SELECTIONFILTER_FACES"),
                                             rcextras._tip("Selection Filters", "F5"), selection_filter))
                if px.has_previous():
                    line.append(contextbar.Entry("PreviousSelection", px.T_PREVIOUS,
                                                 rcextras._icon(px.T_PREVIOUS, "PREVIOUS_SELECTION", "FW_PreviousSelection"),
                                                 rcextras._tip(px.T_PREVIOUS), px.previous_selection))
                continue
            if k == "SelectOther":
                line.append(_select_other_entry())
                continue
            e = rcextras._entry(sh, k)
            if e is not None and getattr(e, "enabled", True):
                line.append(e)
        return (line, [], {"Select"})
    leaf = _leaf(item[2])
    if leaf.startswith("Vertex"):
        return None
    try:
        mode, picked = contextbar.entries_for_selection(sh)
    except Exception:
        picked = []
    have = {e.key: e for e in picked}

    def line(keys):
        out = []
        for key in keys:
            if key == "SelectOther":
                out.append(_select_other_entry())
                continue
            if key == "OpenDrawing":
                out.append(contextbar.Entry(key, "Open Drawing", rcextras._icon("Open Drawing", "FILE_OPEN_DRAWING", "OPEN_DRAWING", "FW_OpenDrawing"),
                                            rcextras._tip("Open Drawing", "Opens the drawing of the part"),
                                            lambda: Gui.runCommand("SWStyle_OpenDrawing", 0)))
                continue
            e = have.get(key) or rcextras._entry(sh, key)
            if e is not None and key == "EditAppearance":
                # screen read 2 D1: the icon's tip is "Appearances" (a drop-down), not the command's name
                e = contextbar.Entry(key, "Appearances", e.icon, rcextras._tip("Appearances"), e.run, e.enabled)
            if e is not None and getattr(e, "enabled", True):
                out.append(e)       # nothing greyed: e.g. Paste Appearance only once an appearance was copied (pkg210)
        return out
    if leaf.startswith("Edge"):
        return (line(ROW_EDGE), [], set())
    feature = owner_feature(*item[:3])
    top = ROW_TOP
    if feature is not None and px.sheet_metal_body(feature) is not None:
        top = ROW_TOP_SHEET_METAL
    return (line(top), line(ROW_SECOND), set())



BAR_PLANE = ("EditFeature", "Sketch", "Suppress", "HideSelection", "ZoomSelection", "NormalTo")

# Suppress] / [Hide, Zoom to Selection, Normal To, Appearance]; sketch [Edit Sketch, Rollback, Suppress] /
# [Hide, Zoom to Selection, Normal To]; plane [Sketch, Hide, Zoom to Selection, Normal To]
# (pkg246: the later tree read 11-19 and shots/15 show Suppress BEFORE Rollback, as the face bar ROW_TOP)
BAR_SKETCH = ("EditFeatureSketch", "EditSketchPlane", "Suppress", "Rollback", "HideSelection", "ZoomSelection", "NormalTo")
BAR_FEATURE = ("EditFeature", "EditFeatureSketch", "Suppress", "Rollback", "HideSelection", "ZoomSelection", "NormalTo",
               "EditAppearance")
BAR_BODY = ("HideSelection", "EditAppearance", "CopyAppearance", "Isolate", "ZoomSelection")


def _adoptable_solid(obj, sub):
    ""

    try:
        if obj is None or not sub or "." in sub or not obj.isDerivedFrom("Part::Feature"):
            return False
        tid = obj.TypeId
        if tid.startswith("PartDesign::") or tid.endswith("Python") or obj.InList:
            return False
        if obj.getParentGeoFeatureGroup() is not None or obj.getParentGroup() is not None:
            return False
        return bool(obj.Shape.Solids)
    except Exception:
        return False


def _adopt_solid(obj, sub):
    ""

    doc = obj.Document
    doc.openTransaction("Convert to Body")
    try:
        body = doc.addObject("PartDesign::Body", "Body")
        body.BaseFeature = obj
        doc.recompute()
        base = next((o for o in body.Group if o.TypeId == "PartDesign::FeatureBase"), None)
        if base is None or base.Shape.isNull() or len(base.Shape.Edges) != len(obj.Shape.Edges):
            raise RuntimeError("no base feature")
        if obj.ViewObject is not None:
            obj.ViewObject.Visibility = False
        doc.commitTransaction()
    except Exception as error:
        doc.abortTransaction()
        App.Console.PrintLog("partmenu: convert to body: %s\n" % error)
        return None
    try:
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", body)
    except Exception:
        pass
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, body.Name, "%s.%s" % (base.Name, sub))
    return body, base


def _run_outside_body(native, obj=None, sub="", inside=None):
    ""




    if native == "Part_Chamfer":
        try:
            from . import wechamfer
            if wechamfer.run():
                return
        except Exception as error:
            App.Console.PrintLog("partmenu: weldment chamfer: %s\n" % error)
    try:
        from . import surfacefillet
        if obj is not None and surfacefillet._is_surface(obj):
            Gui.runCommand("SWStyle_SurfaceFillet" if native == "Part_Fillet" else "SWStyle_SurfaceChamfer", 0)
            return
    except Exception as error:
        App.Console.PrintLog("partmenu: surface fillet: %s\n" % error)
    if inside is not None and _adoptable_solid(obj, sub) and _adopt_solid(obj, sub) is not None:
        inside()
        return
    Gui.runCommand(native, 0)


def _bar_keys(obj, sub):
    ""


    from . import contextbar
    kind = contextbar.kind_of(obj, sub)
    if kind == "edge":
        keys = ROW_EDGE
    elif kind == "vertex":
        return []       # screen read 2 D3: no icons over a vertex's menu, so no bar either
    elif kind == "face":
        from . import partextras as px
        top = ROW_TOP
        try:
            if px.sheet_metal_body(obj) is not None:
                top = ROW_TOP_SHEET_METAL
        except Exception as _fw_err:
            _fw_log("partmenu.py:708", _fw_err)
        keys = top + ROW_SECOND
    elif kind == "plane":
        keys = BAR_PLANE if obj.TypeId != "App::Plane" else ("Sketch", "HideSelection", "ZoomSelection", "NormalTo")
    elif kind == "sketch":
        keys = BAR_SKETCH
    elif kind == "feature":
        keys = BAR_FEATURE
    elif kind == "body":
        keys = BAR_BODY
    elif not sub and _python_editable(obj):
        keys = BAR_FEATURE      # a Python feature (Trim/Extend...) the interface's bar does not know
    else:
        return None
    return [k for k in keys if k != "SelectOther"]


def _python_editable(obj):
    ""

    vp = getattr(getattr(obj, "ViewObject", None), "Proxy", None)
    return vp is not None and hasattr(vp, "setEdit") and not getattr(obj, "TypeId", "").startswith("PartDesign::")


def _edit_python(obj):
    try:
        Gui.ActiveDocument.setEdit(obj, 0)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Edit Feature %s: %s\n" % (obj.Label, error))


def bar_entries(shell, obj, sub, given):
    ""
    keys = _bar_keys(obj, sub or "")
    if keys is None:
        return given
    from . import rcextras, contextbar
    have = {e.key: e for e in given}
    out = []
    outside_body = body_of(obj) is None
    for key in keys:
        if key == "OpenDrawing":
            out.append(contextbar.Entry(key, "Open Drawing", rcextras._icon("Open Drawing", "FILE_OPEN_DRAWING", "OPEN_DRAWING", "FW_OpenDrawing"),
                                        rcextras._tip("Open Drawing", "Opens the drawing of the part"),
                                        lambda: Gui.runCommand("SWStyle_OpenDrawing", 0)))
            continue
        e = have.get(key)
        if key == "HideSelection" and e is None:

            e = have.get("ShowSelection")
            if e is None and not sub and not contextbar._visible(obj):
                e = contextbar._command_entry(shell, "ShowSelection")
        if e is None and key == "EditFeature" and not sub and _python_editable(obj):
            from . import freezebar
            e = contextbar.Entry(key, "Edit Feature", contextbar._feature_icon(obj), contextbar._tip("Edit Feature", obj.Label),
                                 lambda o=obj: _edit_python(o), freezebar.can_edit(obj))
        if e is None and key == "Rollback":
            from . import rollbackbar
            owner = contextbar.owner_feature(obj, sub) if sub else obj
            if owner is not None and owner.TypeId == "Sketcher::SketchObject":
                from . import fmmenu
                owner = fmmenu.sketch_owner(owner) or owner      # a sketch rolls back to before its feature
            if owner is not None and (contextbar._solid_feature(owner) or owner.TypeId == "Sketcher::SketchObject") and rollbackbar.can_roll_back(owner):
                e = contextbar.Entry(key, "Rollback", shell.binding(key).icon(),
                                     contextbar._tip("Rollback", "Roll back to before %s" % owner.Label),
                                     lambda owner=owner: rollbackbar.roll_back_to(owner))
            if e is None:
                continue
        if e is None and key == "Suppress" and not sub and "Suppressed" in getattr(obj, "PropertiesList", ()):
            from . import fmmenu
            on = bool(obj.Suppressed)
            label = "Unsuppress" if on else "Suppress"
            try:
                icon = shell.binding(label).icon()
            except Exception:
                icon = QtGui.QIcon()
            out.append(contextbar.Entry("Suppress", label, icon, contextbar._tip(label, obj.Label),
                                        lambda o=obj, on=on: fmmenu.set_suppressed(o, not on)))
            continue
        if e is None and key == "EditSketchPlane":
            if not sub and getattr(obj, "TypeId", "") == "Sketcher::SketchObject":
                from . import fmmenu
                e = fmmenu.edit_sketch_plane_entry(obj)
            else:
                continue
        if e is None and key == "NormalTo" and kind_is_edge(sub):
            e = edge_normal_entry(shell, obj, sub)
        if e is None and key in ("Sketch", "EditFeature", "EditFeatureSketch", "NormalTo"):
            continue        # the interface left it out because it does not apply to this pick
        if e is None:
            e = rcextras._entry(shell, key) if key in ROW_TOP + ROW_SECOND + ROW_EDGE else contextbar._command_entry(shell, key)
        if e is not None and outside_body and key in ("Fillet", "Chamfer"):
            native = "Part_Fillet" if key == "Fillet" else "Part_Chamfer"
            e = contextbar.Entry(e.key, e.label, e.icon, e.tip,
                                 lambda native=native, o=obj, s=sub, inside=e.run: _run_outside_body(native, o, s, inside),
                                 e.enabled)
        if e is not None and getattr(e, "enabled", True):
            out.append(e)       # nothing greyed, as over the shortcut menu (pkg210)
    from . import rcextras as _rx
    if sub and sub.split(".")[-1].startswith("Face"):
        out = [contextbar.Entry(e.key, "Appearances", e.icon, _rx._tip("Appearances"), e.run, e.enabled)
               if e.key == "EditAppearance" else e for e in out]
    return out


def hook_context_bar():
    from . import contextbar
    if getattr(contextbar, "_fw_part_bar", False):
        return
    original = contextbar.part_entries

    def part_entries(shell, obj, sub, *more, **named):
        given = original(shell, obj, sub, *more, **named)
        try:
            from . import asmmenu
            if asmmenu.kind(obj) in ("component", "mate"):
                return given
        except Exception as _fw_err:
            _fw_log("partmenu.py:825", _fw_err)
        try:
            return bar_entries(shell, obj, sub, given)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: part context toolbar: %s\n" % error)
            return given

    contextbar.part_entries = part_entries
    contextbar._fw_part_bar = True


def show_menu(pos, at=None):
    try:
        from . import featuremenu       # a feature's own PM menu (Direction 1/2, Fillet, Shell...) comes first
        if featuremenu._menu and featuremenu._menu[0]._here():
            return featuremenu._menu[0].show_menu(pos)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: feature PM menu: %s\n" % error)
    try:
        from . import pmconfirm
        if pmconfirm.open():
            return pmconfirm.view_menu(pos)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: PropertyManager menu: %s\n" % error)
    if not _here():
        return None
    item = under_pointer(at)
    if item is not None:
        if not _leaf(item[2])[:4] in ("Face", "Edge", "Vert"):
            return None
    if in_assembly():
        from . import asmviewmenu
        return asmviewmenu.show_view_menu(pos, item)
    if item is not None:
        pick(item)
    name = "PartEmpty" if item is None else "Part" + _leaf(item[2]).rstrip("0123456789")
    _LAST_POS[:] = [QtCore.QPoint(pos)]
    # rmbparity-1127: a face's long menu has a line over Customize Menu (read 11-19 0(d)); the edge's has none
    return rcmenus.show(rcmenus.Builder(name, items(item) + [_freecad_item()], row=row(item), chevron=True,
                                        line_before_customize=(name == "PartFace")), pos)


_LAST_POS = []


def _freecad_item():
    """FreeCAD's own view menu (Draw Style, Standard Views, Navigation styles, Placement, Link
    Actions...), so nothing of FreeCAD's right-click is lost: last, behind the chevron."""
    return rcmenus.action("FreeCADViewMenu", "FreeCAD View Menu...",
                          lambda: QtCore.QTimer.singleShot(60, freecad_view_menu), more=True)


def freecad_view_menu(pos=None):
    """Opens FreeCAD's own graphics-area menu at pos (global; default: where our menu was asked
    for): our menu steps aside for this one right-click, then is back."""
    from . import instant3d
    vp = instant3d._viewport()
    if vp is None:
        return False
    if pos is None:
        pos = _LAST_POS[0] if _LAST_POS else QtGui.QCursor.pos()
    local = QtCore.QPointF(vp.mapFromGlobal(pos))
    g = QtCore.QPointF(pos)
    params = paths.params()
    was = params.GetBool(PARAM, True)
    params.SetBool(PARAM, False)
    try:
        app = QtWidgets.QApplication
        stamp = QtCore.QDateTime.currentMSecsSinceEpoch() & 0x7fffffff
        for kind, buttons, t in ((QtCore.QEvent.MouseButtonPress, Qt.RightButton, stamp),
                                 (QtCore.QEvent.MouseButtonRelease, Qt.NoButton, stamp + 40)):
            e = QtGui.QMouseEvent(kind, local, g, Qt.RightButton, buttons, Qt.NoModifier)
            e.setTimestamp(t)
            app.sendEvent(vp, e)
    finally:
        QtCore.QTimer.singleShot(400, lambda: params.SetBool(PARAM, was))
    return True


def _wants(item):
    """Our menu for faces, edges, vertices and empty space; planes, sketches, axes keep FreeCAD's."""
    if item is not None and in_assembly():
        from . import asmviewmenu
        if asmviewmenu.component_under(item) is None:
            return False
    return item is None or _leaf(item[2])[:4] in ("Face", "Edge", "Vert")


# --------------------------------------------------------------------------- view modes
class ViewMode(QtCore.QObject):
    ""


    def __init__(self, widget, kind):
        super().__init__(widget)
        self.widget, self.kind = widget, kind
        self.last = None
        widget.installEventFilter(self)
        widget.setCursor({"zoom": Qt.SizeVerCursor, "pan": Qt.SizeAllCursor}.get(kind, Qt.CrossCursor))

    def stop(self):
        if alive(self.widget):
            self.widget.removeEventFilter(self)
            self.widget.unsetCursor()
        if _mode and _mode[0] is self:
            _mode.clear()

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        t = event.type()
        if t == QtCore.QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.stop()
            return True
        if t == QtCore.QEvent.MouseButtonPress:
            if event.button() == Qt.RightButton:
                self.stop()
                return True
            if event.button() == Qt.LeftButton:
                self.last = event.position()
                return True
        if t == QtCore.QEvent.MouseMove and self.last is not None and event.buttons() & Qt.LeftButton:
            p = event.position()
            dx, dy = p.x() - self.last.x(), p.y() - self.last.y()
            self.last = p
            try:
                move(self.kind, dx, dy, self.widget.height())
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: view mode: %s\n" % error)
            return True
        if t == QtCore.QEvent.MouseButtonRelease and event.button() == Qt.LeftButton and self.last is not None:
            self.last = None
            return True
        return False


_mode = []


def move(kind, dx, dy, height):
    """One step of a view mode for a drag of (dx, dy) pixels."""
    from pivy import coin
    view = _view()
    cam = view.getCameraNode()
    rot = cam.orientation.getValue()
    q = rot.getValue()
    r = App.Rotation(q[0], q[1], q[2], q[3])
    right, up, back = r.multVec(App.Vector(1, 0, 0)), r.multVec(App.Vector(0, 1, 0)), r.multVec(App.Vector(0, 0, 1))
    pos = App.Vector(*cam.position.getValue().getValue())
    fd = cam.focalDistance.getValue()
    focal = pos - back * fd
    ortho = cam.getTypeId() == coin.SoOrthographicCamera.getClassTypeId()
    size = cam.height.getValue() if ortho else 2.0 * fd * math.tan(cam.heightAngle.getValue() / 2.0)
    per_px = size / max(1, height)
    if kind == "pan":
        shift = right * (-dx * per_px) + up * (dy * per_px)
        cam.position.setValue(*(pos + shift))
        return
    if kind == "zoom":
        k = math.exp(dy * 0.01)
        if ortho:
            cam.height.setValue(cam.height.getValue() * k)
        else:
            cam.focalDistance.setValue(fd * k)
            cam.position.setValue(*(focal + back * fd * k))
        return
    if kind == "rotate":
        turn = App.Rotation(up, -dx * 0.5).multiply(App.Rotation(right, -dy * 0.5))
    else:   # roll: about the line of sight
        turn = App.Rotation(back, dx * 0.5)
    new = turn.multiply(r)
    nq = new.Q
    cam.orientation.setValue(nq[0], nq[1], nq[2], nq[3])
    nback = new.multVec(App.Vector(0, 0, 1))
    cam.position.setValue(*(focal + nback * fd))


def start_mode(kind):
    for m in list(_mode):
        m.stop()
    sh = rcmenus.shell()
    view = sh.view_widget() if sh is not None else None
    if view is None:
        return None
    widget = view.viewport() if hasattr(view, "viewport") else view
    m = ViewMode(widget, kind)
    _mode[:] = [m]
    return m


def mode():
    return _mode[0].kind if _mode else None


# --------------------------------------------------------------------------- the right-click
class PartMenu(QtCore.QObject):
    def __init__(self, shell):
        super().__init__(shell)
        self.shell = shell
        self._pending = False
        self._eat_menu = False
        self._watched = []
        self.mdi = shell.window.findChild(QtWidgets.QMdiArea)
        if self.mdi is not None:
            self.mdi.subWindowActivated.connect(self.attach)
        QtCore.QTimer.singleShot(0, self.attach)

    def attach(self, *args):
        self._watched = [w for w in self._watched if alive(w)]
        view = self.shell.view_widget()
        if view is None or not alive(view) or not hasattr(view, "viewport"):
            return
        widget = view.viewport()
        if widget is None or widget in self._watched:
            return
        widget.installEventFilter(self)
        self._watched.append(widget)

    def remove(self):
        for widget in self._watched:
            if alive(widget):
                widget.removeEventFilter(self)
        self._watched = []

    def _wanted(self, event):
        if event.button() != Qt.RightButton or event.modifiers() != Qt.NoModifier:
            return False
        if _mode or not getattr(self.shell, "enabled", True):
            return False
        try:
            from . import pmconfirm
            if pmconfirm.open():
                return True         # OK / Cancel menu while a PropertyManager is open (pkg93)
        except Exception as _fw_err:
            _fw_log("partmenu.py:1057", _fw_err)
        if not _here():
            return False
        return _wants(under_pointer())

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        t = event.type()
        try:
            if t == QtCore.QEvent.MouseButtonPress:
                if not self._wanted(event):
                    if event.button() == Qt.RightButton:
                        self._eat_menu = False
                    return False
                self._eat_menu = True
                g = getattr(self.shell, "gestures", None)
                if g is not None and not getattr(g, "_replaying", False):
                    try:
                        from .gestures import enabled_here
                        if enabled_here():
                            return False    # gestures holds the press; its replay comes back here
                    except Exception as _fw_err:
                        _fw_log("partmenu.py:1080", _fw_err)
                self._pending = True
                return True
            if t == QtCore.QEvent.MouseButtonRelease and event.button() == Qt.RightButton and self._pending:
                self._pending = False
                pos = event.globalPosition().toPoint()
                QtCore.QTimer.singleShot(0, lambda: show_menu(pos))
                return True
            if t == QtCore.QEvent.ContextMenu and self._eat_menu:
                self._eat_menu = False
                return True         # FreeCAD's view menu stays shut: ours opens
        except Exception:
            return False
        return False


_menu = []


def install(shell=None):
    if shell is None:
        shell = rcmenus.shell()
    if shell is None:
        return None
    if _menu and _menu[0].shell is shell:
        _menu[0].attach()
        return _menu[0]
    remove()
    try:
        from . import partextras
        partextras.HISTORY.watch()
        partextras.hook_tree_extras()
    except Exception as _fw_err:
        _fw_log("partmenu.py:1113", _fw_err)
    try:
        from . import views3d
        views3d.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: 3D Views: %s\n" % error)
    try:
        from . import panemenus
        panemenus.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Design Library menus: %s\n" % error)
    try:
        from . import pmlistmenu
        pmlistmenu.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: selection box menus: %s\n" % error)
    try:
        from . import rcpanes
        rcpanes.install()
        from . import rcaccel
        rcaccel.install_keys()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Display Pane / Design Checker menus: %s\n" % error)
    try:
        from . import chromemenus
        chromemenus.install(shell)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: chrome menus: %s\n" % error)
    try:
        hook_context_bar()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: part context toolbar: %s\n" % error)
    try:
        from . import drawmenu
        drawmenu.install(shell)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: drawing menus: %s\n" % error)
    try:
        from . import asmviewmenu
        asmviewmenu.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: assembly menus: %s\n" % error)
    _menu.append(PartMenu(shell))
    return _menu[0]


def remove():
    while _menu:
        _menu.pop().remove()
    try:
        from . import drawmenu
        drawmenu.remove()
    except Exception as _fw_err:
        _fw_log("partmenu.py:1166", _fw_err)
