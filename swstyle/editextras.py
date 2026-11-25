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
    from PySide import QtGui, QtWidgets
except ImportError:
    Gui = None


# --------------------------------------------------------------------- rollback
def _body():
    """The body the commands act on: the active one, else the picked feature's, else the only one."""
    if Gui is None or Gui.ActiveDocument is None:
        return None
    try:
        body = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
        if body is not None:
            return body
    except Exception as _fw_err:
        _fw_log("editextras.py:42", _fw_err)
    from . import rollbackbar
    for sel in Gui.Selection.getSelectionEx("", 0):
        b = rollbackbar.body_of(sel.Object) if sel.Object.TypeId != "PartDesign::Body" else sel.Object
        if b is not None:
            return b
    bodies = [o for o in App.ActiveDocument.Objects if o.TypeId == "PartDesign::Body"]
    return bodies[0] if len(bodies) == 1 else None


def can_roll(name):
    body = _body()
    if body is None:
        return False
    from . import rollbackbar
    try:
        return bool(rollbackbar.ROLLS.can(body).get(name))
    except Exception:
        return False


def roll(name):
    body = _body()
    if body is None:
        return False
    from . import rollbackbar
    done = {"RollToPrevious": rollbackbar.ROLLS.to_previous, "RollToEnd": rollbackbar.ROLLS.to_end}[name](body)
    try:
        Gui.updateGui()
    except Exception as _fw_err:
        _fw_log("editextras.py:72", _fw_err)
    return done


# --------------------------------------------------------------------- suppress per configuration
def _with(objs, on, dependents):
    ""
    from . import suppress
    every = []
    for obj in objs:
        if on:
            every += [obj] + suppress.dependents(obj)
        else:
            every += suppress.parents(obj) + [obj] + (suppress.dependents(obj) if dependents else [])
    return suppress._unique(every)


def suppress_in(objs, on, scope, dependents=False):
    """scope: "this", "all" or a list of configuration names."""
    from . import configs, suppress
    targets = _with(objs, on, dependents)
    if scope == "this" and _configs_none(targets):

        if on:
            return suppress.suppress(objs)
        return suppress.unsuppress(objs, dependents)
    for obj in targets:
        configs.set_suppressed(obj, on, scope)
    return targets


def _configs_none(objs):
    try:
        from . import configmanager
        return not objs or configmanager.table(objs[0].Document) is None
    except Exception:
        return True


def specify(objs, on, dependents=False):
    from . import configs, configmanager
    doc = objs[0].Document
    if configmanager.table(doc) is None:
        configs.table(doc)          # the default configuration, so there is one to tick
    return configs.specify(doc, lambda names: suppress_in(objs, on, names, dependents))


def picked_features():
    from . import suppress
    return suppress._picked()


# --------------------------------------------------------------------- design table
def design_table(doc, create=False):
    """The part's design table: the configurations table, else a sheet labelled Design Table."""
    from . import configmanager
    t = configmanager.table(doc)
    if t is not None and getattr(t, "sheet", None) is not None:
        return t.sheet
    for obj in doc.Objects:
        if obj.TypeId == "Spreadsheet::Sheet" and "design" in obj.Label.lower():
            return obj
    if not create:
        return None
    sheet = doc.addObject("Spreadsheet::Sheet", "DesignTable")
    sheet.Label = "Design Table"
    doc.recompute()
    return sheet


def edit_table(new_window=False):
    doc = App.ActiveDocument
    from . import configmanager
    if configmanager.table(doc) is None and design_table(doc) is None:
        from . import cmflows, configs
        configs.table(doc)              # no table yet: a blank one, as Insert > Tables > Blank
        cmflows.restore_table(doc)
    t = configmanager.table(doc)
    if t is not None and getattr(t, "sheet", None) is not None:
        return configmanager.edit_table(t, new_window) and t.sheet
    sheet = design_table(doc, create=True)
    Gui.ActiveDocument.setEdit(sheet.Name)
    if new_window:
        try:
            Gui.runCommand("Std_ViewUndock", 0)
        except Exception as _fw_err:
            _fw_log("editextras.py:150", _fw_err)
    return sheet


# --------------------------------------------------------------------- flip normal
def _surface(obj):
    shape = getattr(obj, "Shape", None)
    return shape is not None and not shape.isNull() and shape.Faces and not shape.Solids


class FlipNormalFeature:
    """The Base surface with every face turned round."""

    def __init__(self, obj, base):
        obj.addProperty("App::PropertyLink", "Base", "Flip Normal", "The surface body to flip")
        obj.Base = base
        obj.Proxy = self

    def execute(self, obj):
        if obj.Base is not None:
            obj.Shape = obj.Base.Shape.reversed()

    def dumps(self):
        return None

    def loads(self, _state):
        return None


def flip_normal(obj):
    doc = obj.Document
    doc.openTransaction("Flip Normal")
    try:
        if obj.TypeId == "Part::Feature" and not obj.InList:
            obj.Shape = obj.Shape.reversed()          # a dumb surface flips in place
            result = obj
        elif obj.TypeId == "Part::FeaturePython" and isinstance(getattr(obj, "Proxy", None), FlipNormalFeature) \
                and obj.Base is not None:
            base = obj.Base                             # flipping a flip gives the surface back
            if Gui is not None:
                base.ViewObject.Visibility = True
            doc.removeObject(obj.Name)
            result = base
        else:
            result = doc.addObject("Part::FeaturePython", "FlipNormal")
            FlipNormalFeature(result, obj)
            result.Label = "Flip Normal"
            if Gui is not None:
                result.ViewObject.Proxy = 0
                obj.ViewObject.Visibility = False
                for prop in ("ShapeAppearance", "LineColor", "PointColor"):
                    try:
                        setattr(result.ViewObject, prop, getattr(obj.ViewObject, prop))
                    except Exception as _fw_err:
                        _fw_log("editextras.py:204", _fw_err)
        doc.recompute()
    finally:
        doc.commitTransaction()
    return result


def picked_surfaces():
    out = []
    for sel in Gui.Selection.getSelectionEx("", 0):
        obj = sel.Object
        for path in sel.SubElementNames or [""]:
            found = obj
            for part in path.split(".")[:-1]:
                child = obj.Document.getObject(part)
                if child is not None:
                    found = child
            if _surface(found) and found not in out:
                out.append(found)
    return out


# --------------------------------------------------------------------- sketch / curve colour
def _curve(obj):
    if obj.isDerivedFrom("Sketcher::SketchObject"):
        return True
    shape = getattr(obj, "Shape", None)
    return shape is not None and not shape.isNull() and shape.Edges and not shape.Faces


def picked_curves():
    out = []
    for sel in Gui.Selection.getSelectionEx("", 0):
        obj = sel.Object
        for path in sel.SubElementNames or [""]:
            found = obj
            for part in path.split(".")[:-1]:
                child = obj.Document.getObject(part)
                if child is not None:
                    found = child
            if _curve(found) and found not in out:
                out.append(found)
    return out


def set_line_colour(objs, rgb):
    if not objs:
        return
    doc = objs[0].Document
    doc.openTransaction("Sketch/Curve Color")
    try:
        for obj in objs:
            vo = obj.ViewObject
            for prop in ("LineColor", "PointColor"):
                if prop in vo.PropertiesList:
                    setattr(vo, prop, rgb)
    finally:
        doc.commitTransaction()


if Gui is not None:
    class _Cmd:
        def __init__(self, text, tip, active, run, edit=False):
            self.text, self.tip, self.active, self.run, self.edit = text, tip, active, run, edit

        def GetResources(self):
            out = {"MenuText": self.text, "ToolTip": self.tip}
            if self.edit:
                out["CmdType"] = "ForEdit"
            return out

        def IsActive(self):
            try:
                return App.ActiveDocument is not None and bool(self.active())
            except Exception:
                return False

        def Activated(self):
            self.run()

    def _colour():
        objs = picked_curves()
        first = objs[0].ViewObject.LineColor if objs else (0.0, 0.0, 0.0)
        colour = QtWidgets.QColorDialog.getColor(QtGui.QColor.fromRgbF(*first[:3]), Gui.getMainWindow(),
                                                 "Sketch/Curve Color")
        if colour.isValid():
            set_line_colour(objs, (colour.redF(), colour.greenF(), colour.blueF()))

    def _flip():
        for obj in picked_surfaces():
            flip_normal(obj)

    def _scoped(on, scope, dependents=False):
        objs = picked_features()
        if not objs:
            return
        if scope == "specify":
            specify(objs, on, dependents)
        else:
            suppress_in(objs, on, scope, dependents)

    COMMANDS = [
        ("SWStyle_RollToPrevious", "Roll to Previous", "Moves the rollback bar back to where it was.",
         lambda: can_roll("RollToPrevious"), lambda: roll("RollToPrevious")),
        ("SWStyle_RollToEnd", "Roll to End", "Moves the rollback bar to the end of the tree.",
         lambda: can_roll("RollToEnd"), lambda: roll("RollToEnd")),
        ("SWStyle_EditDesignTable", "Edit Table", "Opens the design table.",
         lambda: True, lambda: edit_table(False)),
        ("SWStyle_EditDesignTableWindow", "Edit Table in New Window", "Opens the design table in a window of its own.",
         lambda: True, lambda: edit_table(True)),
        ("SWStyle_FlipNormal", "Flip Normal", "Turns the picked surface bodies' faces round.",
         lambda: bool(picked_surfaces()), _flip),
        ("SWStyle_SketchCurveColor", "Sketch/Curve Color...", "Sets the colour of the picked sketches and curves.",
         lambda: bool(picked_curves()), _colour),
    ]
    for verb, on, deps in (("Suppress", True, False), ("Unsuppress", False, False),
                           ("UnsuppressWithDependents", False, True)):
        for key, text, scope in (("This", "This Configuration", "this"), ("All", "All Configurations", "all"),
                                 ("Specified", "Specified Configurations...", "specify")):
            COMMANDS.append(("SWStyle_%s%s" % (verb, key), text, "%s in %s" % (verb, text.rstrip(".").lower()),
                             lambda: bool(picked_features()),
                             lambda on=on, scope=scope, deps=deps: _scoped(on, scope, deps)))


def register():
    if Gui is None:
        return
    for name, text, tip, active, run in COMMANDS:
        try:
            if name not in Gui.listCommands():
                Gui.addCommand(name, _Cmd(text, tip, active, run, edit=name == "SWStyle_SketchCurveColor"))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s not added (%s)\n" % (text, error))
