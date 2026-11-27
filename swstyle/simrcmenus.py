# SPDX-License-Identifier: LGPL-2.1-or-later
""








import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    Gui = None

_SEEN = set()
WINDOWS = []


def _log(site, err):
    if site not in _SEEN:
        _SEEN.add(site)
        try:
            App.Console.PrintLog("FreeCAD Simulation menus %s: %s\n" % (site, err))
        except Exception:
            return


S = "-"
_FOLDER_TAIL = [S, "Copy", "Paste", S, "Create New Folder", "Collapse Tree Items"]

ORDER = {
    "study": ["Run", "Update All Components", "Export...", S, "Trend Tracker", "Create Submodeling Study",
              "Load Case Manager", "Copy Study", "Paste", "Shell Manager", "Simulation Evaluator...", S, "Details...",
              "Properties...", "Mass Properties...", S, "Define Function Curves...", S, "Rename", "Delete"],
    "part": ["Apply/Edit Material...", "Apply Favorite Material", S, "Apply Draft Quality Mesh", "Apply High Quality Mesh", S, "Shell Manager",
             "Define Shell By Selected Faces...", S, "Create Mesh...", "Treat as Beam...", "Treat as Remote Mass...",
             S, "Make Rigid", "Fix", "Exclude from Analysis", S, "Details...", S, "Copy", S, "Add to New Folder",
             "Collapse Tree Items"],
    "body": ["Apply/Edit Material...", S, "Hide", "Show", S, "Details..."],
    "connections": ["Connections Advisor...", S, "Local Interaction...", "Component Interaction...", S,
                    "Interaction Viewer...", "Underconstrained Bodies...", S, "Spring...", "Pin...", "Bolt...",
                    "Bearing...", S, "Hide All", "Show All"] + _FOLDER_TAIL,
    "fixtures": ["Fixtures Advisor...", S, "Fixed Geometry...", "Roller/Slider...", "Fixed Hinge...",
                 "Elastic Support...", "Bearing Fixture...", "Foundation Bolt...", "Advanced Fixtures...", S,
                 "Hide All", "Show All"] + _FOLDER_TAIL,
    "loads": ["External Loads Advisor...", S, "Force...", "Torque...", "Pressure...", "Gravity...", "Centrifugal...",
              "Bearing Load...", "Temperature...", "Prescribed Displacement...", S, "Flow Effects...",
              "Thermal Effects...", S, "Remote Load/Mass...", "Distributed Mass...", S, "Copy", "Paste", S, "Hide All",
              "Show All", S, "Create New Folder", "Collapse Tree Items"],
    "item": ["Edit Definition...", "Add to Library", "Details...", S, "Hide", "Show", "Suppress", "Unsuppress", S,
             "Delete...", "Copy"],
    "mesh": ["Mesh Advisor...", S, "Simplify Model for Meshing", "Create Mesh...", "Mesh and Run", S,
             "Apply Mesh Control...", "Failure Diagnostics...", S, "Details...", "Summary...", S,
             "Create Mesh Quality Plot...", "Mesh Quality Diagnostics...", S, "Hide All Mesh Control Symbols",
             "Show All Mesh Control Symbols", S, "Copy", S, "Collapse Tree Items"],
    "results": ["Results Advisor...", "Solver Messages...", "Define Convergence Diagnostic Plot...",
                "Stress Hot Spot Diagnostics...", S, "Define Factor Of Safety Plot...", "Define Stress Plot...",
                "Define Displacement Plot...", "Define Strain Plot...", "Define Design Insight Plot...",
                "Define Fatigue Check Plot...", "Results Equations...", S, "List Stress, Displacement, Strain",
                "List Result Force...", S, "Compare Results...", S, "Create Body from Deformed Shape...", S,
                "Save All Plots as JPEG Files", "Save All Plots as eDrawings", S, "Copy", S, "Create New Folder",
                "Collapse Tree Items"],
    "plot": ["Show", "Hide", S, "Edit Definition...", "Chart Options...", "Settings...", S, "Animate...",
             "Section Clipping...", "Iso Clipping...", "Mesh Sectioning...", "Probe", "List Selected",
             "Deformed Result", "Compare Results...", S, "Print...", "Save As...", "Add to New Folder", S,
             "Delete...", "Copy"],
}


# icon (resources/simicons), ":/icons/x" one of FreeCAD's own.
ICONS = {
    "Run": "SIM_Run", "Mesh and Run": "SIM_Run", "Copy Study": "SIM_Duplicate", "Properties...": "SIM_Props",
    "Apply/Edit Material...": "SIM_ApplyMaterial", "Create Mesh...": "SIM_Mesh", "Make Rigid": "SIM_Rigid",
    "Mesh Advisor...": "SIM_Advisor", "Fixtures Advisor...": "SIM_Advisor", "External Loads Advisor...": "SIM_Advisor",
    "Connections Advisor...": "SIM_Advisor", "Results Advisor...": "SIM_Advisor",
    "Local Interaction...": "SIM_Contact", "Component Interaction...": "SIM_Interaction", "Spring...": "SIM_Spring",
    "Pin...": "SIM_Pin", "Bolt...": "SIM_Bolt", "Bearing...": "SIM_Bearing",
    "Fixed Geometry...": "SIM_Fixed", "Roller/Slider...": "SIM_Roller", "Fixed Hinge...": "SIM_Hinge",
    "Elastic Support...": "SIM_Elastic", "Bearing Fixture...": "SIM_Bearing",
    "Force...": "SIM_Force", "Torque...": "SIM_Torque", "Pressure...": "SIM_Pressure", "Gravity...": "SIM_Gravity",
    "Centrifugal...": "SIM_Centrifugal", "Temperature...": "SIM_Temperature", "Remote Load/Mass...": "SIM_RemoteLoad",
    "Distributed Mass...": "SIM_DistributedMass", "Apply Mesh Control...": "SIM_MeshControl",
    "Details...": "SIM_MeshInfo", "Create Mesh Quality Plot...": "SIM_MeshQuality",
    "Define Factor Of Safety Plot...": "SIM_Plot", "Define Stress Plot...": "SIM_Plot",
    "Define Displacement Plot...": "SIM_Plot", "Define Strain Plot...": "SIM_Plot", "Compare Results...": "SIM_Compare",
    "List Stress, Displacement, Strain": "SIM_ListLine", "List Selected": "SIM_ListLine",
    "Chart Options...": "SIM_PlotTools", "Settings...": "SIM_PlotTools", "Animate...": "SIM_Deform",
    "Deformed Result": "SIM_Deform", "Section Clipping...": "SIM_Section", "Iso Clipping...": "SIM_IsoClip",
    "Probe": "SIM_Probe", "Edit Definition...": ":/icons/edit-edit.svg", "Delete...": ":/icons/edit-delete.svg",
    "Delete": ":/icons/edit-delete.svg", "Copy": ":/icons/edit-copy.svg", "Show": ":/icons/Std_ShowSelection.svg",
    "Hide": ":/icons/Std_HideSelection.svg", "Print...": ":/icons/document-print.svg",
    "Save As...": ":/icons/document-save-as.svg",
}


def icon_for(text):
    """The menu row's icon, or None (a text-only row)."""
    key = ICONS.get(text)
    if not key or Gui is None:
        return None
    try:
        if key.startswith(":"):
            i = QtGui.QIcon(key) if QtCore.QFile.exists(key) else QtGui.QIcon()
        else:
            from . import simtree
            i = simtree.icon(key)
        return None if i.isNull() else i
    except Exception as _fw_err:
        _log("icon", _fw_err)
        return None



RENAME = {
    "connections": {"Contact Set...": "Local Interaction..."},
    "loads": {"Centrifugal Force...": "Centrifugal..."},
    "results": {"List Stress, Displacement, Strain...": "List Stress, Displacement, Strain"},
    "item": {"Delete": "Delete..."},
    "plot": {"Delete": "Delete..."},
}


DROP = {
    "study": ("Study Advisor...", "Report..."),

    # CommandManager (Fixtures Advisor and Connections Advisor flyouts)
    "connections": ("Rigid...", "Rigid Connection..."),
}


# --------------------------------------------------------------------------- the study tree item of a row
def _tree_item(what, obj):
    """(tree, item) of the study tree row the menu is for: the row under the pointer, else the first of its kind."""
    if Gui is None:
        return None, None
    try:
        from . import simtree
    except ImportError:
        return None, None
    for t in QtWidgets.QApplication.allWidgets():
        if t.objectName() not in ("SWStudyTree", "SWFlowTree") or not hasattr(t, "row_of"):
            continue
        try:
            it = t.itemAt(t.viewport().mapFromGlobal(QtGui.QCursor.pos()))
            row = t.row_of(it)
            if row is not None and row.what == what and (obj is None or row.obj is obj):
                return t, it
            for it in t._items():
                row = t.row_of(it)
                if row is not None and row.what == what and (obj is None or row.obj is obj):
                    return t, it
        except Exception as _fw_err:
            _log("tree_item", _fw_err)
    return None, None


def _any_open(item):
    """The row or a row under it is open: otherwise Collapse Tree Items would fold nothing (NO DEAD CONTROLS)."""
    stack = [item]
    while stack:
        it = stack.pop()
        if it.isExpanded() and it.childCount():
            return True
        stack.extend(it.child(i) for i in range(it.childCount()))
    return False


def collapse(item):
    """Collapse Tree Items: the row and every row under it fold."""
    if item is None:
        return
    stack = [item]
    while stack:
        it = stack.pop()
        for i in range(it.childCount()):
            stack.append(it.child(i))
        it.setExpanded(False)


# --------------------------------------------------------------------------- Details...
def _q(v):
    try:
        return v.UserString
    except Exception:
        return str(v)


def _refs(o):
    out = []
    for obj, subs in list(getattr(o, "References", []) or []):
        subs = subs if isinstance(subs, (list, tuple)) else [subs]
        out += ["%s of %s" % (s, obj.Label) if s else obj.Label for s in subs]
    return out


ITEM_PROPS = (("Force", "Force"), ("Pressure", "Pressure"), ("Torque", "Torque"), ("Gravity", "GravityAcceleration"),
              ("Rotation frequency", "RotationFrequency"), ("Temperature", "Temperature"),
              ("Normal stiffness", "NormalStiffness"), ("Tangential stiffness", "TangentialStiffness"),
              ("Friction coefficient", "Friction"), ("Reverse direction", "Reversed"), ("Suppressed", "Suppressed"))


def item_details(o):
    rows = [("Name", o.Label)]
    try:
        from . import simnames
        kind = simnames.kind_name(o)
    except Exception:
        kind = None
    rows.append(("Type", kind or getattr(getattr(o, "Proxy", None), "Type", "") or o.TypeId))
    refs = _refs(o)
    if refs:
        rows.append(("Entities", "%d: %s" % (len(refs), ", ".join(refs))))
    for name, prop in ITEM_PROPS:
        if prop in getattr(o, "PropertiesList", ()):
            v = getattr(o, prop)
            rows.append((name, ("Yes" if v else "No") if isinstance(v, bool) else _q(v)))
    return rows


def _solid_of(a):
    try:
        from . import simtree
        s = simtree._solids(a)
        return s[0] if s else None
    except Exception:
        return None


def _density(a):
    """kg/m^3 of the study's material, else None."""
    try:
        from . import simtree
        for m in simtree._materials(a):
            d = (getattr(m, "Material", None) or {}).get("Density")
            if d:
                return App.Units.Quantity(d).getValueAs("kg/m^3").Value, simtree._material_name(m)
    except Exception as _fw_err:
        _log("density", _fw_err)
    return None


def part_details(a, body=None):
    s = body or _solid_of(a)
    rows = []
    if s is not None:
        rows.append(("Name", s.Label))
    d = _density(a)
    if d:
        rows.append(("Material", d[1]))
        rows.append(("Mass density", "%g kg/m^3" % d[0]))
    vol = None
    try:
        vol = s.Shape.Volume if s is not None else None
    except Exception:
        vol = None
    if vol:
        rows.append(("Volume", "%g mm^3" % vol))
        if d:
            mass = d[0] * vol * 1e-9
            rows.append(("Mass", "%g kg" % mass))
            rows.append(("Weight", "%g N" % (mass * 9.81)))
    return rows


def study_details(a):
    from . import simtree
    rows = [("Study name", a.Label)]
    try:
        rows.append(("Analysis type", str(simtree.kind(a)).capitalize()))
    except Exception as _fw_err:
        _log("kind", _fw_err)
    meshes = simtree._meshes(a)
    if meshes:
        try:
            from . import simmeshinfo
            fem = getattr(meshes[0], "FemMesh", None)
            t = simmeshinfo._mesh_type(fem) if fem is not None else None
            if t:
                rows.append(("Mesh type", t))
            if fem is not None and fem.NodeCount:
                rows.append(("Total Nodes", "%d" % fem.NodeCount))
                rows.append(("Total Elements", "%d" % (fem.VolumeCount or fem.FaceCount or fem.EdgeCount)))
        except Exception as _fw_err:
            _log("mesh", _fw_err)
    solvers = [o for o in a.Group if o.isDerivedFrom("Fem::FemSolverObject")]
    if solvers:
        rows.append(("Solver", getattr(getattr(solvers[0], "Proxy", None), "Type", solvers[0].Label).split("::")[-1]
                     .replace("SolverCcxTools", "CalculiX").replace("SolverCalculix", "CalculiX")))
    rows.append(("Results", "Yes" if simtree._results(a) else "No (the study has not run)"))
    return rows


def show_table(title, rows, name="SWSimDetails"):
    if Gui is None or not rows:
        return None
    w = QtWidgets.QDialog(Gui.getMainWindow())
    w.setObjectName(name)
    w.setWindowTitle(title)
    w.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
    lay = QtWidgets.QVBoxLayout(w)
    table = QtWidgets.QTableWidget(len(rows), 2, w)
    table.setObjectName(name + "Table")
    table.setHorizontalHeaderLabels(["Details", "Value"])
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    for r, (k, v) in enumerate(rows):
        table.setItem(r, 0, QtWidgets.QTableWidgetItem(k))
        table.setItem(r, 1, QtWidgets.QTableWidgetItem(v))
    table.resizeColumnsToContents()
    table.horizontalHeader().setStretchLastSection(True)
    lay.addWidget(table)
    w.resize(max(380, table.horizontalHeader().length() + 40), min(520, 60 + 26 * len(rows)))
    w.show()
    WINDOWS[:] = [x for x in WINDOWS if _alive(x)] + [w]
    return w


def _alive(w):
    try:
        w.isVisible()
        return True
    except RuntimeError:
        return False


def _mass_properties():
    from . import massprops
    return massprops.show()


def _mesh_controls(m):
    try:
        from . import simtree
        return [c for c in simtree.mesh_children(m) if getattr(c, "ViewObject", None) is not None
                and simtree.ftype(c) in ("Fem::MeshRegion", "Fem::MeshBoundaryLayer")]
    except Exception:
        return []


def _set_shown(objs, on):
    from . import simtree
    simtree.set_shown(objs, on)


# --------------------------------------------------------------------------- extra rows
def extras(what, obj, a):
    out = []
    if what in ("item",) and obj is not None:
        out.append(("Details...", lambda: show_table(obj.Label, item_details(obj))))
    elif what == "study" and a is not None:
        out.append(("Details...", lambda: show_table(a.Label, study_details(a))))
        try:
            from . import massprops  # noqa: F401
            out.append(("Mass Properties...", _mass_properties))
        except ImportError:
            pass
    elif what in ("part", "body") and a is not None:
        try:
            from . import simtree
            if what == "part" and simtree.has_key("SIM_Mesh"):
                out.append(("Create Mesh...", lambda: simtree.run_key("SIM_Mesh", a)))
        except Exception as _fw_err:
            _log("part mesh", _fw_err)
        rows = part_details(a, obj if what == "body" else None)
        if rows:
            out.append(("Details...", lambda: show_table(rows[0][1], part_details(a, obj if what == "body" else None))))
    if what == "mesh" and obj is not None:
        ctl = _mesh_controls(obj)
        if ctl:
            out.append(("Hide All Mesh Control Symbols", lambda: _set_shown(_mesh_controls(obj), False)))
            out.append(("Show All Mesh Control Symbols", lambda: _set_shown(_mesh_controls(obj), True)))
    if "Collapse Tree Items" in ORDER.get(what, ()):
        _t, it = _tree_item(what, obj)
        if it is not None and it.childCount() and _any_open(it):
            # the study tree can be rebuilt between the menu and the click: find the row again at the click
            out.append(("Collapse Tree Items", lambda w=what, o=obj: collapse(_tree_item(w, o)[1])))
    return out


def arrange(what, entries, obj=None, a=None):
    ""
    order = ORDER.get(what)
    if not order:
        return entries
    ren = RENAME.get(what, {})
    drop = DROP.get(what, ())
    rows = [(ren.get(t, t), f) for t, f in entries if t not in drop]
    have = {t for t, _f in rows}
    try:
        rows += [e for e in extras(what, obj, a) if e[0] not in have]
    except Exception as _fw_err:
        _log("extras", _fw_err)
    by = {}
    for t, f in rows:
        if t != S and t not in by:
            by[t] = (t, f)
    out, used = [], set()
    for t in order:
        if t == S:
            if out and out[-1][0] != S:
                out.append((S, None))
        elif t in by:
            out.append(by[t])
            used.add(t)
    rest = [(t, f) for t, f in rows if t != S and t not in used]
    if rest:
        out.append((S, None))
        out += rest
    while out and out[-1][0] == S:
        out.pop()
    return out
