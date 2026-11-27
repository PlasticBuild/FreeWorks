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
from PySide import QtCore, QtWidgets

PREFIX = "SWStyle_TF_"

# ---------------------------------------------------------------- what each button needs
SKETCH = "sketch"
SKETCH_KEYS = (
    "HorizontalDimension", "VerticalDimension", "AngularDimension", "RadiusDimension", "BaselineDimension",
    "ChainDimension", "OrdinateDimension", "HorizontalOrdinateDimension", "VerticalOrdinateDimension",
    "AngularRunningDimension", "ChamferDimension", "PathLengthDimension", "SymmetricLinearDiameterDimension",
    "SketchFillet", "Join", "CarbonCopy", "LinearSketchPattern", "CircularSketchPattern", "MirrorEntities",
    "MoveEntities", "CopyEntities", "RotateEntities", "ScaleEntities", "StretchEntities", "Relations", "AddRelation",
    "FullyDefineSketch", "ScanEqual", "Horizontal", "Vertical", "Parallel", "Perpendicular", "Tangent", "Equal",
    "Symmetric", "Fix", "ConflictingRelations", "RedundantRelations", "DeleteAllRelations", "QuickSnaps", "QSPoint",
    "QSCenterPoint", "QSMidpoint", "QSQuadrant", "QSIntersection", "QSNearest", "QSTangent", "QSPerpendicular",
    "QSParallel", "QSHV", "QSHVPoint", "QSLength", "QSGrid", "QSAngle", "ShadedSketchContours", "MakeBlock",
    "EditBlock", "InsertBlock", "AddRemoveBlockEntities", "SaveBlock", "ExplodeBlock",
)
# (hint, kind of pick that fits or None for a condition, [(button text, command)])
_VIEW = ("Select a drawing view.", "view", [])
_VIEWGEO = ("Select edges, points or dimensions of a drawing view.", "viewgeo", [])
_STUDY = ("Create a study first.", None, [("New Study", "SWStyle_SimNewStudy"), ("Empty Study", "FEM_Analysis")])
_FLOW = ("Create a flow project first.", None, [("New Project", "SWStyle_FlowNewProject")])
_CAM = ("Set up a machining job first.", None, [("Setup", "CAM_Job")])
_SHEET = ("Show the drawing sheet in front first.", None, [])
_PART = ("Open a part or an assembly to run this on: it works on a model, not on a drawing.", None, [])
_INK = ("Start a sketch ink first.", None, [("Sketch Ink", "SWStyle_SketchInk"), ("Pen Sketch", "FreeWorks_PenSketch")])
_3D = ("Open a 3D sketch first.", None, [("3D Sketch", "FreeWorks_Sketch3D")])
_WELD = ("Start a structure system first.", None, [("Structure System", "SWStyle_WEStructureSystem")])
_BLOCK = ("Select a block on the sheet.", "any", [])
_SHEETMETAL = ("Make a sheet metal body first.", None,
               [("Base Flange/Tab", "SWStyle_SMBaseFlange"), ("Convert to Sheet Metal", "SWStyle_SMConvert")])
_FLATTENED = ("Flatten the sheet metal part first.", None, [("Flatten", "SWStyle_SMFlatten")])
NEEDS = {
    "FixComponent": ("Select a component.", "any", []),
    "FloatComponent": ("Select a component.", "any", []),
    "UpdateSpeedPak": ("Select a SpeedPak component.", "any", []),
    "MakePartFromBlock": ("Select a block in a layout sketch.", "any", []),
    "EditSketch": ("Select a sketch.", "sketch", []),
    "FS_EditMerge": ("Select a freeshape feature.", "any", []),
    "ExplodeCollapse": ("Make an exploded view first.", None, [("Exploded View", "SWStyle_ExplodedView")]),
    "MBD_DeleteAll": ("Add DimXpert dimensions first.", None, [("Auto Dimension Scheme", "SWStyle_MBDAutoScheme")]),
    "MBD_Stack": ("Add DimXpert dimensions first.", None, [("Auto Dimension Scheme", "SWStyle_MBDAutoScheme")]),
    "MBD_CopyScheme": ("Add DimXpert dimensions first.", None, [("Auto Dimension Scheme", "SWStyle_MBDAutoScheme")]),
    "FCA_Activate": ("Select a FreeCAD assembly.", "any", []),
    "FCA_Simulation": ("Activate a FreeCAD assembly first.", None, [("Activate Assembly", "Assembly_ActivateAssembly")]),
    "Sketch3DPlane": _3D, "RepairSketch": _3D, "SketchChamfer": _3D,
    "PenDraw": _INK, "PenEraser": _INK, "PenSelect": _INK, "PenPowerModify": _INK, "PenRuler": _INK,
    "PenProtractor": _INK,
    "WE_PrimaryMember": _WELD, "WE_SecondaryMember": _WELD, "WE_InsertConnection": _WELD,
    "WE_PatternConnection": _WELD, "WE_PiercePoint": _WELD, "WE_TrimExtend": _WELD,
    "WE_EndCap": ("Select an end face of a structural member.", "any", []),
    "WE_Gusset": ("Select two touching faces of structural members.", "any", []),
    "DrawProjectedView": _VIEW, "DrawAuxiliaryView": ("Select a straight edge of a drawing view.", "viewgeo", []),
    "DrawSectionView": _VIEW, "DrawRemovedSection": _VIEW, "DrawDetailView": _VIEW, "DrawBrokenOut": _VIEW,
    "DrawAlternatePosition": ("Select a drawing view of an assembly.", "view", []), "DrawUpdateView": _VIEW,
    "DrawReplaceModel": _VIEW, "DrawHoleTable": _VIEW, "DrawBOM": _VIEW, "DrawFamilyTable": _VIEW,
    "DrawWeldTable": _VIEW, "DrawBendTable": _VIEW, "DrawPunchTable": _VIEW,
    "DrawPathLengthDimension": _VIEWGEO, "DrawConvertEntities": _VIEWGEO,
    "DrawLinearNotePattern": ("Select a note.", "any", []), "DrawCircularNotePattern": ("Select a note.", "any", []),
    "DrawMoveEntities": ("Select sketch entities on the sheet.", "any", []),
    "DrawCopyEntities": ("Select sketch entities on the sheet.", "any", []),
    "DrawRotateEntities": ("Select sketch entities on the sheet.", "any", []),
    "DrawScaleEntities": ("Select sketch entities on the sheet.", "any", []),
    "DrawEditBlock": _BLOCK, "DrawSaveBlock": _BLOCK, "DrawExplodeBlock": _BLOCK,
    "DrawEditSheet": _SHEET, "DrawTitleBlockFields": _SHEET, "DrawAutomaticBorder": _SHEET, "DrawQuickSnaps": _SHEET,
    "EV_Simulation": _PART, "FloXpress": _PART, "EV_DFM": _PART, "EV_Sustainability": _PART, "EV_Costing": _PART,
    "EV_OnDemand": _PART,
}
for _k in ("SIM_Duplicate", "SIM_Fixed", "SIM_Roller", "SIM_Hinge", "SIM_Elastic", "SIM_Rigid", "SIM_Force",
           "SIM_Pressure", "SIM_Gravity", "SIM_Bearing", "SIM_Temperature", "SIM_Convection", "SIM_HeatFlux",
           "SIM_BodyHeat", "SIM_Radiation", "SIM_InitialTemp", "SIM_Contact", "SIM_Bonded", "SIM_Interaction",
           "SIM_SpringConnector", "SIM_Pin", "SIM_Bolt", "SIM_Mesh", "SIM_RunAll", "SIM_Results", "SIM_Plot",
           "SIM_Deform", "SIM_Compare", "SIM_IsoClip", "SIM_PlotTools", "SIM_Section", "SIM_Probe", "SIM_ListLine"):
    NEEDS[_k] = _STUDY
for _k in ("SM_CrossBreak", "SM_SweptFlange", "SM_Corners", "SM_ClosedCorner", "SM_WeldedCorner", "SM_CornerRelief",
           "SM_FormingTool", "SM_Gusset", "SM_Stamp", "SM_Vent", "SM_NormalCut", "SM_BendNotch", "SM_Unfold", "SM_Fold",
           "SM_Flatten", "SM_NoBends", "SM_UnfoldUpdate"):
    NEEDS[_k] = _SHEETMETAL
NEEDS["SM_CornerTrim"] = _FLATTENED
NEEDS["SM_BendTableNew"] = NEEDS["SM_BendTableFile"] = _SHEETMETAL     # bendtable-1126 (Edit/Insert > Bend Table)

NEEDS["SM_SweptFlange"] = ("Select an open profile sketch and a path.", "sketch", [])
NEEDS["SM_FormingTool"] = ("Select the stopping face of the forming tool.", "any", [])
NEEDS["SM_Convert"] = ("Select a face of a solid to stay fixed.", "any", [])
NEEDS["SM_LoftedBend"] = ("Select two open profile sketches.", "sketch", [])
NEEDS["SM_Rip"] = ("Select the edges of a shelled solid to rip.", "any", [])
NEEDS["SM_InsertBends"] = ("Select a face of a thin-walled solid to stay fixed.", "any", [])
for _k in ("FLOW_Clone", "FLOW_Pressure", "FLOW_BatchRun", "FLOW_Results"):
    NEEDS[_k] = _FLOW
for _k in ("CAM_Inspect", "CAM_Sanity", "CAM_Post"):
    NEEDS[_k] = _CAM
# case 1625: two Drawing Tools work on objects of the drawing's own document picked in the tree, not on a view's
# edges; FreeCAD's own command is live with nothing picked and only says "Wrong selection", so the page waits for the
# right pick first (FreeCAD links these views inside one document only)
NEEDS["TDX_ArchView"] = ("Select a BIM section plane of this document in the tree: its cut goes on the sheet.",
                         "bimsection", [])
NEEDS["TDX_DraftView"] = ("Select Draft or BIM objects of this document in the tree to show them on the sheet.",
                          "model", [])
TDX_PREFIX = "TDX_"         # TechDraw's extension tools on the drawing tabs: picks of a view's edges / points
TDX_SHEET = ("TDX_FillTemplate", "TDX_Redraw")
LEFT_ALONE = ("DrawMarkupEraser", "DrawMarkupSelect", "DrawZoomToMarkup")     # hidden until a markup (pkg332)


# Once the part has a sheet metal body these three still wait for something else: each says what (look audit T4)
SHEET_STATE = {
    "SM_Fold": ("Unfold some bends first: Fold folds back the bends that Unfold flattened.", None,
                [("Unfold", "SWStyle_SMUnfold")]),
    "SM_NoBends": ("No Bends works on a part made with Insert Bends, and this part has none.", None,
                   [("Insert Bends", "SWStyle_SMInsertBends")]),
    "SM_UnfoldUpdate": ("Unfold the part with the sheet metal add-on's Unfold first: Update Unfold makes that "
                        "unfolded pattern again.", None, []),
}


def _has_sheet_body():
    try:
        from . import smflatview
        doc = App.ActiveDocument
        return doc is not None and smflatview.sheet_body(doc) is not None
    except Exception as _fw_err:
        _fw_log("toolfirst:sheet_body", _fw_err)
        return False


def needs(key):
    """(kind, hint, pick, actions) for a catalog key, or None when the button is not wrapped here."""
    if key in LEFT_ALONE:
        return None
    if key in SKETCH_KEYS:
        return SKETCH, "", None, []
    if key in SHEET_STATE and _has_sheet_body():
        hint, pick, actions = SHEET_STATE[key]
        return "wait", hint, pick, actions
    if key in NEEDS:
        hint, pick, actions = NEEDS[key]
        return "wait", hint, pick, actions
    if key.startswith(TDX_PREFIX):
        if key in TDX_SHEET:
            return "wait", _SHEET[0], None, []
        return "wait", _VIEWGEO[0], "viewgeo", []
    return None


# ---------------------------------------------------------------- state
def _active(native):
    try:
        cmd = Gui.Command.get(native)
        return bool(cmd is not None and cmd.isActive())
    except Exception:
        return False


def _run_native(native):
    try:
        from . import featureflow
        if featureflow.run(native):
            return True
    except Exception as _fw_err:
        _fw_log("toolfirst:featureflow", _fw_err)
    try:
        Gui.runCommand(native, 0)
        return True
    except Exception as error:
        App.Console.PrintError("FreeCAD: %s failed: %s\n" % (native, error))
        return False


def _in_sketch():
    try:
        gdoc = Gui.ActiveDocument
        vp = gdoc.getInEdit() if gdoc is not None else None
        obj = getattr(vp, "Object", None)
        return obj is not None and obj.isDerivedFrom("Sketcher::SketchObject")
    except Exception:
        return False


GROUP_TITLES = {"SM_Corners": "Closed Corner"}     # a flyout's own button runs its first tool: that tool's title


def _label(native, key=""):
    if key in GROUP_TITLES:
        return GROUP_TITLES[key]
    try:
        from . import catalog
        c = catalog.BY_KEY.get(key)
        if c is not None and c.label:
            return c.label.replace("\n", " ")
    except Exception as _fw_err:
        _fw_log("toolfirst:label", _fw_err)
    try:
        return (Gui.Command.get(native).getInfo().get("menuText") or native).replace("&", "")
    except Exception:
        return native


def fits(pick, sel=None):
    """The current selection fits what the page waits for."""
    if pick is None:
        return False
    try:
        sel = sel if sel is not None else Gui.Selection.getSelectionEx("", 0)
    except Exception:
        try:
            sel = Gui.Selection.getSelectionEx()
        except Exception:
            sel = []
    if not sel:
        return False
    if pick == "any":
        return True
    if pick.startswith(("sub:", "dims:")) or pick == "viewprofile":
        return _counts_fit(pick, sel)
    for s in sel:
        obj = s.Object
        if pick == "sketch" and obj.isDerivedFrom("Sketcher::SketchObject"):
            return True
        if pick == "view" and obj.isDerivedFrom("TechDraw::DrawView") and not obj.isDerivedFrom("TechDraw::DrawViewDimension"):
            return True
        if pick == "bimsection" and getattr(getattr(obj, "Proxy", None), "Type", "") == "SectionPlane":
            return True
        if pick == "model" and not obj.TypeId.startswith(("TechDraw::", "App::Origin", "App::Line", "App::Plane")):
            return True
        if pick == "viewgeo" and (obj.isDerivedFrom("TechDraw::DrawViewDimension")
                                  or (obj.isDerivedFrom("TechDraw::DrawView") and any(s.SubElementNames))):
            return True
    return False


def _counts_fit(pick, sel):
    """Drawing tools that need a number of things picked: "sub:Edge:2" (two edges of drawing views), "sub:Vertex:1",
    "sub:Any:1" (edges or points), "dims:2" (two dimensions), "viewprofile" (a view and a sketch or wire)."""
    edges = verts = dims = views = other = 0
    for s in sel:
        obj = s.Object
        if obj.isDerivedFrom("TechDraw::DrawViewDimension"):
            dims += 1
        elif obj.isDerivedFrom("TechDraw::DrawViewPart"):
            views += 1
            for n in s.SubElementNames:
                n = str(n).split(".")[-1]
                edges += n.startswith("Edge")
                verts += n.startswith("Vertex")
        elif not obj.TypeId.startswith("TechDraw::"):
            other += 1
    if pick == "viewprofile":
        return views > 0 and other > 0
    if pick.startswith("dims:"):
        return dims >= int(pick[5:])
    _, kind, n = pick.split(":")
    have = {"Edge": edges, "Vertex": verts, "Any": edges + verts}[kind]
    return have >= int(n)


def _sig():
    try:
        return tuple((x.Object.Name, tuple(x.SubElementNames)) for x in Gui.Selection.getSelectionEx("", 0))
    except Exception:
        return ()


# ---------------------------------------------------------------- the waiting page
OPEN = []


class WaitPanel:
    ""


    def __init__(self, native, key, hint, pick, actions):
        self.native, self.key, self.hint, self.pick = native, key, hint, pick
        self.title = _label(native, key)
        self.form = QtWidgets.QWidget()
        self.form.setObjectName("SWToolFirst")

        # group named after the command holding a Message box (frame scan, PM thread 11-20)
        self.form.setWindowTitle("Message")
        self.form.setProperty("swstyle_pm_title", self.title)
        box = self.form
        bl = QtWidgets.QVBoxLayout(box)
        self.text = QtWidgets.QLabel(hint, box)
        self.text.setObjectName("SWToolFirstHint")
        self.text.setWordWrap(True)
        bl.addWidget(self.text)
        self.missing = QtWidgets.QLabel("", box)
        self.missing.setObjectName("SWToolFirstMissing")
        self.missing.setWordWrap(True)
        self.missing.setStyleSheet("color: #c00000; background: transparent;")
        self.missing.hide()
        bl.addWidget(self.missing)
        self.actions = []
        have = set(Gui.listCommands())
        for text, cmd in actions:
            if cmd not in have:
                continue                        # only steps this installation can take (no dead buttons)
            b = QtWidgets.QPushButton(text, box)
            b.setObjectName("SWToolFirstAction")
            b.clicked.connect(lambda checked=False, cmd=cmd: self.do(cmd))
            bl.addWidget(b)
            self.actions.append(b)
        self.timer = QtCore.QTimer(self.form)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self._poll)
        self.timer.start()
        self.tried = None                       # a pick the command already turned down: wait for another
        OPEN[:] = [self]

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            self.timer.stop()
        except RuntimeError:
            pass
        if self in OPEN:
            OPEN.remove(self)
        Gui.Control.closeDialog()

    def _poll(self):
        try:
            gone = not self.form.isVisible() and not Gui.Control.activeDialog()
        except RuntimeError:
            gone = True
        if gone:                                 # closed some other way (another command, document closed)
            self.timer.stop()
            if self in OPEN:
                OPEN.remove(self)
            return
        if (fits(self.pick) and _sig() != self.tried) or (self.pick is None and _active(self.native)):
            self.go()       # the pick came, or what it waited for was made some other way (a study from the tree)

    def say_missing(self, turned_down=False):
        if turned_down:
            text = "That selection cannot be used here. " + self.hint
        else:
            text = "Not yet: " + self.hint[:1].lower() + self.hint[1:]
        self.missing.setText(text)
        self.missing.show()

    def go(self):
        """The page goes and the command starts; if it still cannot, the page comes back saying so."""
        native, key, sig, picked = self.native, self.key, _sig(), fits(self.pick)
        hint, pick = self.hint, self.pick
        own = (pick or "").startswith(("sub:", "dims:", "viewprofile"))     # a page with its own hint keeps it
        self._close()

        def start():
            if _active(native):
                _run_native(native)
                return
            p = show_wait(native, key, *((hint, pick) if own else ()))
            if p is not None:
                p.tried = sig
                p.say_missing(turned_down=picked)
        QtCore.QTimer.singleShot(0, start)

    def do(self, cmd):
        """The step that makes the command possible (New Study...): this page goes, that one runs."""
        self._close()
        QtCore.QTimer.singleShot(0, lambda: Gui.runCommand(cmd, 0))

    def accept(self):
        if not _active(self.native) and (self.pick is None or not fits(self.pick)):
            self.say_missing()                  # the page stays: OK says in red what is still missing
            return False
        self.go()
        return True

    def reject(self):
        self._close()
        return True


def show_wait(native, key, hint=None, pick=None):
    """The waiting page of key; hint and pick: what it waits for, when the caller knows better than needs()."""
    got = needs(key) if hint is None else ("wait", hint, pick, [])
    if got is None or Gui.Control.activeDialog():
        return None
    _kind, hint, pick, actions = got
    panel = WaitPanel(native, key, hint or "Select what this works on.", pick, actions)
    Gui.Control.showDialog(panel)
    return panel


_said = {"text": None}      # the last "can't start here" note this module wrote in the status bar


# ---------------------------------------------------------------- inside a sketch: wait for the pick
class _SketchWait(QtCore.QObject):
    """Inside a sketch, a tool that still waits for a pick: the status bar says so, the tool starts at the pick."""

    def __init__(self, native, label):
        super().__init__(Gui.getMainWindow())
        self.native, self.left = native, 50             # 15 s; Esc or another tool ends it sooner
        QtWidgets.QApplication.instance().installEventFilter(self)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self._poll)
        self.timer.start()
        self._say("%s: select the sketch entities it works on." % label)

    def _say(self, text):
        try:
            Gui.getMainWindow().statusBar().showMessage(text, 30000)
        except Exception as _fw_err:
            _fw_log("toolfirst:status", _fw_err)

    def stop(self):
        try:
            self.timer.stop()
            QtWidgets.QApplication.instance().removeEventFilter(self)
        except RuntimeError:
            pass

    def eventFilter(self, obj, event):
        try:
            if event.type() == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Escape:
                self.stop()
                Gui.getMainWindow().statusBar().clearMessage()
        except Exception as _fw_err:
            _fw_log("toolfirst:esc", _fw_err)
        return False

    def _poll(self):
        self.left -= 1
        if not _in_sketch() or self.left <= 0:
            self.stop()
            return
        if _active(self.native):
            self.stop()
            _run_native(self.native)


_WAITING = []


def stop_waiting():
    for w in _WAITING:
        w.stop()
    _WAITING[:] = []


def sketch_wait(native, key):
    stop_waiting()
    _WAITING[:] = [_SketchWait(native, _label(native, key))]


# ---------------------------------------------------------------- the wrapper command
class _Wrapper:
    def __init__(self, native, key):
        self.native, self.key = native, key
        self._earlier = None
        self._looked = 0.0

    def _better(self):
        """The button's own command when it was added after this wrapper was made (Mirror Entities, Stretch
        Entities, Path Length Dimension are registered late): the wrapper then runs it, not FreeCAD's stand-in."""
        earlier = self._earlier
        if earlier is None:
            earlier = ()
            try:
                from . import catalog
                natives = [n for n in catalog.BY_KEY[self.key].natives if not n.startswith(PREFIX)]
                if self.native in natives:
                    earlier = tuple(n for n in natives[:natives.index(self.native)]
                                    if not n.startswith(("SWStyle_SF_", "SWStyle_EP_")))
            except Exception as _fw_err:
                _fw_log("toolfirst:earlier", _fw_err)
            self._earlier = earlier
        for n in earlier:
            try:
                if Gui.Command.get(n) is not None:
                    self.native, self._earlier = n, ()
                    break
            except Exception:
                continue
        return self.native

    def GetResources(self):
        info = {}
        try:
            cmd = Gui.Command.get(self.native)
            info = cmd.getInfo() if cmd is not None else {}
        except Exception:
            info = {}
        return {"Pixmap": info.get("pixmap", "") or "", "MenuText": info.get("menuText") or _label(self.native, self.key),
                "ToolTip": info.get("toolTip", "") or "", "CmdType": "ForEdit"}

    def IsActive(self):
        if self._earlier != ():
            import time
            now = time.monotonic()
            if now - self._looked > 3.0:        # a late command is looked for every few seconds, not per update
                self._looked = now
                self._better()
        if _active(self.native):
            return True
        if App.ActiveDocument is None:
            return False
        if _in_sketch():
            return True                          # waits for its pick in the status bar
        return not Gui.Control.activeDialog()

    def Activated(self):
        native, key = self._better(), self.key
        stop_waiting()                           # another tool clicked: an earlier wait for a pick ends
        if _active(native):
            _run_native(native)
            return
        got = needs(key)
        kind = got[0] if got else None
        if kind != SKETCH and _in_sketch():
            # inside a sketch the page cannot open (the sketch is the open page): the status bar says what it needs
            hint = (got[1] if got else "") or "Close the sketch first."
            try:
                _said["text"] = "%s: %s" % (_label(native, key), hint)     # fix293: the next sketch tool's prompt may replace it
                Gui.getMainWindow().statusBar().showMessage(_said["text"], 6000)
            except Exception as _fw_err:
                _fw_log("toolfirst:insketch", _fw_err)
            return
        if kind == SKETCH:
            if _in_sketch():
                sketch_wait(native, key)
                return
            try:
                from .fwsketch import sketchfirst
                if sketchfirst.can_start():
                    # sweep-1121: this wrapper's own registered name; wrapper(native) named a command never added when
                    # _better() swapped in the late button command (Mirror Entities: "No such command")
                    sketchfirst.start_sketch_then(getattr(self, "name", None) or wrapper(native))
                    return
            except Exception as _fw_err:
                _fw_log("toolfirst:sketchfirst", _fw_err)
            if not Gui.Control.activeDialog():
                # needs() answers SKETCH for these keys, so the page is given its words here
                Gui.Control.showDialog(WaitPanel(native, key, "Open a part, or edit one, to sketch in: this tool works "
                                                 "inside a sketch.", None, []))
            return
        show_wait(native, key)


def wrapper(native):
    return PREFIX + native


_done = []


def register():
    """Wrap every button that needs it and point the CommandManager's buttons at the wrappers."""
    try:
        from . import catalog
    except Exception as error:
        App.Console.PrintLog("FreeCAD: tool first not added: %s\n" % error)
        return 0
    have = set(Gui.listCommands())
    theirs = set(getattr(catalog, "SOLID_FIRST_KEYS", ())) | set(getattr(catalog, "SKETCH_FIRST_KEYS", ()))
    n = 0
    for key, cmd in list(catalog.BY_KEY.items()):
        if needs(key) is None or not cmd.natives or key in theirs:
            continue
        natives = tuple(cmd.natives)
        if any(x.startswith(PREFIX) for x in natives):
            continue
        native = next((x for x in natives if x in have), None)
        if native is None or native.startswith(("SWStyle_SF_", "SWStyle_EP_")):
            continue                        # sketchfirstlive / solidfirstlive already keep it live
        name = wrapper(native)
        if name not in have:
            try:
                w = _Wrapper(native, key)
                w.name = name
                Gui.addCommand(name, w)
                have.add(name)
            except Exception as error:
                App.Console.PrintLog("FreeCAD: %s not added: %s\n" % (name, error))
                continue
        cmd.natives = (name,) + natives
        n += 1
    _rebind()
    return n


def _rebind():
    """Bindings made before the wrappers take them now."""
    try:
        from . import shell
        sh = shell.shell()
        for key, b in list(getattr(sh, "bindings", {}).items()) if sh is not None else []:
            natives = getattr(b.cmd, "natives", ())
            if natives and natives[0].startswith(PREFIX) and b.native != natives[0]:
                b.action = None
                b.resolve()
                b.update_state()
    except Exception as _fw_err:
        _fw_log("toolfirst:rebind", _fw_err)


def install():
    if _done:
        return
    _done.append(True)
    register()
    # buttons added later (add-in tabs, Simulation...) are wrapped once they exist
    for ms in (1500, 6000):
        QtCore.QTimer.singleShot(ms, register)
