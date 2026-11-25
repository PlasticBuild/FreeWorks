# SPDX-License-Identifier: LGPL-2.1-or-later
"""System Options rows that had nothing behind them (Options audit, features/151):

- Sketch > Auto-rotate view normal to sketch plane on sketch creation and sketch edit: off, the view
  stays where it was when a sketch opens (FreeCAD always turns it);
- Sketch > Display plane when shaded: on, the sketch plane shows as a see-through face while a sketch
  is edited;
- Display > Projection type for four view viewport: Window > Viewport > Four View lays out the views
  as First Angle (Front, Left / Top, Trimetric) or Third Angle (Top, Trimetric / Front, Right).
"""

_FW_SEEN = set()



def _alive(obj):
    """False for None or an object deleted under its wrapper (teardown.alive, review 1119)."""
    from . import teardown
    return teardown.alive(obj)


def _doc_alive(doc):
    from . import teardown
    return teardown.doc_alive(doc)


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

AUTO_ROTATE = ("Fixed", "Auto-rotate view normal to sketch plane on sketch creation and sketch edit", True)
SHADED_PLANE = ("Fixed", "Display plane when shaded", False)
FOUR_VIEW = ("Display", "Projection type for four view viewport", "First Angle")

# Four View windows in the order windowmenu tiles them (top left, top right, bottom left, bottom right)
FOUR = {"First Angle": ("viewFront", "viewLeft", "viewTop", "viewIsometric"),
        "Third Angle": ("viewTop", "viewIsometric", "viewFront", "viewRight")}

_state = {"cameras": {}, "plane": None, "timer": None, "observer": None}


def _kept(row):
    from . import optionspages
    return optionspages.stored(row[0], row[1], row[2])


AUTO_SHOW_PM = ("Fixed", "Auto-show PropertyManager", True)


def auto_show_pm():
    """System Options > General > Auto-show PropertyManager: off, a command's PropertyManager waits
    behind its tab and the FeatureManager tree stays up."""
    try:
        return bool(_kept(AUTO_SHOW_PM))
    except Exception:
        return True


def four_turns():
    return FOUR.get(str(_kept(FOUR_VIEW)), FOUR["First Angle"])


# ---------------------------------------------------------------- the camera before a sketch opens
def _views():
    out = []
    try:
        for doc in App.listDocuments().values():
            gdoc = Gui.getDocument(doc.Name)
            if gdoc is not None and gdoc.getInEdit() is None:
                out.append(gdoc)
    except Exception as _fw_err:
        _fw_log("optionsextras3.py:72", _fw_err)
    return out


def _remember():
    """The camera of each document not being edited, so a sketch can open where the view was."""
    for gdoc in _views():
        if not _alive(gdoc) or getattr(gdoc, "ActiveView", None) is None:
            continue
        try:
            _state["cameras"][gdoc.Document.Name] = gdoc.ActiveView.getCamera()
        except Exception as _fw_err:
            _fw_log("optionsextras3.py:82", _fw_err)


def _is_sketch(vp):
    try:
        return vp.Object.isDerivedFrom("Sketcher::SketchObject")
    except Exception:
        return False


def _restore(doc_name, camera):
    try:
        gdoc = Gui.getDocument(doc_name)
        if gdoc is not None and gdoc.getInEdit() is not None:
            gdoc.ActiveView.setCamera(camera)
    except Exception as _fw_err:
        _fw_log("optionsextras3.py:98", _fw_err)


# ---------------------------------------------------------------- the shaded sketch plane
def _plane_node(sketch):
    from pivy import coin
    bb = sketch.Shape.BoundBox if not sketch.Shape.isNull() and sketch.Shape.Edges else None
    inv = sketch.getGlobalPlacement().inverse()
    if bb is not None:
        pts = [inv.multVec(App.Vector(x, y, z)) for x in (bb.XMin, bb.XMax) for y in (bb.YMin, bb.YMax)
               for z in (bb.ZMin, bb.ZMax)]
        x0, x1 = min(p.x for p in pts), max(p.x for p in pts)
        y0, y1 = min(p.y for p in pts), max(p.y for p in pts)
        m = max(x1 - x0, y1 - y0, 20.0) * 0.25
        x0, x1, y0, y1 = x0 - m, x1 + m, y0 - m, y1 + m
    else:
        x0, x1, y0, y1 = -50.0, 50.0, -50.0, 50.0
    g = sketch.getGlobalPlacement()
    corners = [g.multVec(App.Vector(x, y, 0)) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    sep = coin.SoSeparator()
    mat = coin.SoMaterial()
    mat.diffuseColor = (0.55, 0.7, 0.9)
    mat.transparency = 0.8
    sep.addChild(mat)
    hints = coin.SoShapeHints()
    hints.vertexOrdering = coin.SoShapeHints.UNKNOWN_ORDERING
    sep.addChild(hints)
    pick = coin.SoPickStyle()
    pick.style = coin.SoPickStyle.UNPICKABLE
    sep.addChild(pick)
    co = coin.SoCoordinate3()
    co.point.setValues(0, 4, [tuple(c) for c in corners])
    sep.addChild(co)
    face = coin.SoFaceSet()
    face.numVertices.setValue(4)
    sep.addChild(face)
    return sep


def _show_plane(gdoc, sketch):
    _hide_plane()
    try:
        node = _plane_node(sketch)
        root = gdoc.ActiveView.getSceneGraph()
        root.addChild(node)
        _state["plane"] = (root, node)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: shaded sketch plane: %s\n" % error)


def _hide_plane():
    got = _state.get("plane")
    _state["plane"] = None
    if got is not None:
        try:
            got[0].removeChild(got[1])
        except Exception as _fw_err:
            _fw_log("optionsextras3.py:155", _fw_err)


class _Observer:
    def slotInEdit(self, vp):
        if not _is_sketch(vp):
            return
        try:
            doc_name = vp.Object.Document.Name
        except Exception:
            return
        if not _kept(AUTO_ROTATE):
            camera = _state["cameras"].get(doc_name)
            if camera:
                # FreeCAD turns the view as the sketch opens; put it back (again after any animation)
                for delay in (0, 120, 600, 1100):
                    QtCore.QTimer.singleShot(delay, lambda d=doc_name, c=camera: _restore(d, c))
        if _kept(SHADED_PLANE):
            gdoc = Gui.getDocument(doc_name)
            sketch = vp.Object
            QtCore.QTimer.singleShot(0, lambda: _show_plane(gdoc, sketch))

    def slotResetEdit(self, vp):
        if _is_sketch(vp):
            _hide_plane()


TREE_WARNINGS = ("Messages/Errors/Warnings", "Display FeatureManager tree warnings", "Always")
REBUILD_ERROR = ("Messages/Errors/Warnings", "When rebuild error occurs", "Prompt")


def _wrap():
    """Messages/Errors/Warnings rows: the tree's yellow warning marks and the What's Wrong box after a
    rebuild follow them (wrapped once, after the other add-on wrappers)."""
    try:
        from . import fmtree
        if not getattr(fmtree._warned, "_fw_opt3", False):
            old = fmtree._warned

            def warned(obj, _old=old):
                if str(_kept(TREE_WARNINGS)) == "Never":
                    return False
                return _old(obj)
            warned._fw_opt3 = True
            fmtree._warned = warned
            old_any = fmtree._any_warned

            def any_warned(doc, _old=old_any):
                # All but top level: the features keep their marks, the part's own row does not
                if str(_kept(TREE_WARNINGS)) != "Always":
                    return False
                return _old(doc)
            fmtree._any_warned = any_warned
    except Exception as error:
        App.Console.PrintLog("FreeCAD: tree warnings option: %s\n" % error)
    try:
        from . import whatswrong
        if not getattr(whatswrong.after_rebuild, "_fw_opt3", False):
            old_after = whatswrong.after_rebuild

            def after_rebuild(doc, _old=old_after):
                if str(_kept(REBUILD_ERROR)) == "Continue":
                    return None
                return _old(doc)
            after_rebuild._fw_opt3 = True
            whatswrong.after_rebuild = after_rebuild
    except Exception as error:
        App.Console.PrintLog("FreeCAD: rebuild error option: %s\n" % error)


def install():
    if Gui is None or _state["observer"] is not None:
        return
    obs = _Observer()
    Gui.addDocumentObserver(obs)
    _state["observer"] = obs
    t = QtCore.QTimer()
    t.setInterval(400)
    t.timeout.connect(_remember)
    t.start()
    _state["timer"] = t
    QtCore.QTimer.singleShot(4000, _wrap)
    try:
        from . import optionsextras4      # colours, macros, backups, import, search, mouse (features/153)
        optionsextras4.install()
    except Exception as error:
        App.Console.PrintLog("FreeCAD options4: %s\n" % error)
    try:
        from . import optionsextras5      # selection rows, feature edges, touch, time step, equations (154)
        optionsextras5.install()
    except Exception as error:
        App.Console.PrintLog("FreeCAD options5: %s\n" % error)
    try:
        from . import optionsextras6      # DimXpert on top, facet fins, sheet metal self-intersection check
        optionsextras6.install()
    except Exception as error:
        App.Console.PrintLog("FreeCAD options6: %s\n" % error)


def refresh():
    """After the Options box is saved (optionsextras.refresh_options)."""
    try:
        from . import optionsextras4
        optionsextras4.refresh()
    except Exception as error:
        App.Console.PrintLog("FreeCAD options4 refresh: %s\n" % error)
    try:
        from . import optionsextras6
        optionsextras6.refresh()
    except Exception as error:
        App.Console.PrintLog("FreeCAD options6 refresh: %s\n" % error)
