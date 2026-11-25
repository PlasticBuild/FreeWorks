# SPDX-License-Identifier: LGPL-2.1-or-later
""







import os

import FreeCAD as App
import Part

V = App.Vector
FOLDER = ("Design Library", "forming tools")


def folder():
    """The Design Library's forming tools folder (Tools > Options > File Locations > Design Library)."""
    try:
        from . import designlib
        path = designlib.marked_folder("forming")      # extapps95: the forming tools folder: the library's own, or the one marked in the Design Library
    except Exception:
        path = os.path.join(App.getUserAppDataDir(), "FreeWorks", *FOLDER)
    os.makedirs(path, exist_ok=True)
    return path


def _block():
    """The die block under the stopping face (z = 0, normal +z)."""
    return Part.makeBox(60, 30, 2, V(-30, -15, -2))


def _louver():
    # a ramp 30 x 6 rising to 3 mm at its open front (x = +15): the front face is removed
    pts = [V(-15, -3, 0), V(15, -3, 0), V(15, -3, 3), V(-15, -3, 0)]
    face = Part.Face(Part.makePolygon(pts))
    punch = face.extrude(V(0, 6, 0))
    return punch, [(V(15, 0, 1.5), V(1, 0, 0))]


def _lance():
    # a bridge lance 20 x 6 x 3: open on both long sides
    punch = Part.makeBox(20, 6, 3, V(-10, -3, 0))
    return punch, [(V(0, -3, 1.5), V(0, -1, 0)), (V(0, 3, 1.5), V(0, 1, 0))]


def _dimple():
    # a round emboss 12 mm across, 2 mm high
    return Part.makeCylinder(6, 2, V(0, 0, 0)), []


def _rib():
    # a stiffening rib 40 x 8 x 2.5 with round ends
    box = Part.makeBox(32, 8, 2.5, V(-16, -4, 0))
    ends = [Part.makeCylinder(4, 2.5, V(x, 0, 0)) for x in (-16, 16)]
    return box.fuse(ends).removeSplitter(), []


def _flange():
    # an extruded flange: a round collar 10 mm across, 5 mm high, open at its top
    return Part.makeCylinder(5, 5, V(0, 0, 0)), [(V(0, 0, 5), V(0, 0, 1))]


TOOLS = (("dimple", _dimple), ("flange", _flange), ("lance", _lance), ("louver", _louver), ("rib", _rib))

CATEGORY = {"dimple": "embosses", "flange": "extruded flanges", "lance": "lances", "louver": "louvers", "rib": "ribs"}


def tool_path(name):
    ""
    root = folder()
    dest = os.path.join(root, CATEGORY.get(name, ""), name + ".FCStd")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    old = os.path.join(root, name + ".FCStd")
    if os.path.exists(old) and not os.path.exists(dest):
        try:
            os.replace(old, dest)
        except OSError as _fw_err:
            App.Console.PrintLog("FreeCAD: forming tool %s not moved: %s\n" % (name, _fw_err))
            return old
    return dest


def build(name, maker, path):
    """Makes the tool part name (a Body whose base is the block and punch, marked as a forming tool)."""
    from . import smformingtool as ft
    doc = App.newDocument(name, hidden=True)
    try:
        punch, removed = maker()
        solid = _block().fuse(punch).removeSplitter()
        if len(solid.Solids) == 1:
            solid = solid.Solids[0]
        base = doc.addObject("Part::Feature", "Tool")
        base.Shape = solid
        body = doc.addObject("PartDesign::Body", "Body")
        body.Label = name
        body.BaseFeature = base
        doc.recompute()
        tool = ft.make(body, ft.SWFormingTool, "FormingTool", "Forming Tool")
        tool.StopPoint = V(-27, -12, 0)
        tool.StopNormal = V(0, 0, 1)
        tool.RemovePoints = [p for p, _n in removed]
        tool.RemoveNormals = [n for _p, n in removed]
        tool.InsertionPoint = V(0, 0, 0)
        tool.InsertionSet = True
        doc.recompute()
        doc.saveAs(path)
    except Exception:
        App.closeDocument(doc.Name)
        raise
    return doc


def ensure_files():
    ""

    made = []
    open_files = {_key(d.FileName) for d in App.listDocuments().values() if d.FileName}
    for name, maker in TOOLS:
        path = tool_path(name)
        if os.path.exists(path) or _key(path) in open_files:
            continue
        try:
            doc = build(name, maker, path)
            App.closeDocument(doc.Name)
            made.append(path)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: forming tool %s not available: %s\n" % (name, error))
    return made


def _key(path):
    """A file name as Windows and Linux both compare it (FreeCAD gives C:/..., os.path C:\\...)."""
    return os.path.normcase(os.path.normpath(path or ""))


def _usable(doc):
    from . import smformingtool as ft
    return any(ft.is_forming_tool(o) and "Invalid" not in o.State for o in doc.Objects)


def tools():
    """The library's forming tools, built and opened (hidden) as needed."""
    from . import smformingtool as ft
    out = []
    open_files = {_key(d.FileName): d for d in App.listDocuments().values() if d.FileName}
    for name, maker in TOOLS:
        try:
            path = tool_path(name)
            doc = open_files.get(_key(path))
            if doc is None:
                if os.path.exists(path):
                    doc = App.openDocument(path, hidden=True)
                    try:
                        from . import cleanfiles    # its classes back now (else the tool reads as broken
                        cleanfiles.restore(doc)     # and was built again, losing the user's changes)
                    except Exception as _fw_err:
                        App.Console.PrintLog("FreeCAD: forming tool classes: %s\n" % _fw_err)
                    if not _usable(doc):

                        App.Console.PrintLog("FreeCAD: forming tool %s rebuilt\n" % name)
                        App.closeDocument(doc.Name)
                        doc = build(name, maker, path)
                else:
                    doc = build(name, maker, path)
                open_files[_key(path)] = doc
            out += [o for o in doc.Objects if ft.is_forming_tool(o) and "Invalid" not in o.State]
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: forming tool %s not available: %s\n" % (name, error))
    return out
