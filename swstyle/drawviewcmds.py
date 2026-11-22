
"""Lock View Position, Alignment (Align Horizontal/Vertical to Origin or by Center, Break and Default Alignment),
Tangent Edge (Visible / With Font / Removed), Hide / Show, Open the model, and the view's Properties dialog.
They act on the views picked on the sheet; the right-click thread puts them in the menu."""

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

from . import drawings as D
from . import drawviews as DV

V = App.Vector


def picked_views():
    out = []
    for sel in Gui.Selection.getSelectionEx("", 0):
        o = sel.Object
        if o.isDerivedFrom("TechDraw::DrawView") and o not in out:
            out.append(o)
    v, _ = D.picked_view_and_edge()
    if v is not None and v not in out:
        out.append(v)
    return [o for o in out if o.isDerivedFrom("TechDraw::DrawViewPart")]


def _prop(o, name, kind="App::PropertyString", doc=""):
    if name not in o.PropertiesList:
        o.addProperty(kind, name, "FreeCAD", doc)


def model_centre_on_sheet(v):
    """Where the model origin of view v is on the sheet."""
    x0, y0 = D.view_position(v)
    k = DV.view_scale(v)
    d, x, y = D.view_frame(v)
    c = DV.model_centre(v)
    return x0 - c.dot(x) * k, y0 - c.dot(y) * k


def view_centre(v):
    a, b, c, d = DV.view_box(v)
    return (a + c) / 2, (b + d) / 2


def align(view, target, axis, by="Center"):
    """Moves view so it lines up with target: axis Horizontal (same y) or Vertical (same x), by Center or Origin."""
    if by == "Origin":
        p, q = model_centre_on_sheet(view), model_centre_on_sheet(target)
    else:
        p, q = view_centre(view), view_centre(target)
    if axis == "Horizontal":
        view.Y = float(view.Y) + (q[1] - p[1])
    else:
        view.X = float(view.X) + (q[0] - p[0])
    install_alignment()
    _prop(view, "SWAlignedTo", doc="the view this one is aligned with")
    _prop(view, "SWAlignment", doc="Horizontal/Vertical by Center/Origin")
    view.SWAlignedTo = target.Name
    view.SWAlignment = "%s %s" % (axis, by)
    if "SWAlignmentBroken" in view.PropertiesList:
        view.SWAlignmentBroken = False
    view.Document.recompute()


def default_parent(view):
    ""
    for o in view.InList:
        if o.TypeId == "TechDraw::DrawProjGroup":
            anchor = getattr(o, "Anchor", None)
            return anchor if anchor is not None and anchor != view else None
    for name in ("BaseView", "SWParent"):
        p = getattr(view, name, None)
        if isinstance(p, str):
            try:
                p = view.Document.getObject(p)
            except Exception:
                p = None
        if p is not None:
            return p
    return None


def default_alignment(view):
    parent = default_parent(view)
    if parent is None:
        return False
    px, py = D.view_position(parent)
    x, y = D.view_position(view)
    axis = "Horizontal" if abs(x - px) >= abs(y - py) else "Vertical"
    align(view, parent, axis, "Origin")
    return True


def break_alignment(view):
    for name in ("SWAlignedTo", "SWAlignment"):
        if name in view.PropertiesList:
            setattr(view, name, "")
    _prop(view, "SWAlignmentBroken", "App::PropertyBool", "alignment broken by the user")
    view.SWAlignmentBroken = True



# follows the view it is aligned with, and dragging it slides it along the alignment only, until Break Alignment.
def alignment_of(view):
    """(target, axis, by) the view is kept in line with, else None: an Align command's own alignment, else the
    default alignment of a projected / section view with its parent (by Origin, along the projection)."""
    doc = view.Document
    name = getattr(view, "SWAlignedTo", "") or ""
    if name:
        t = doc.getObject(name)
        axis, _, by = (getattr(view, "SWAlignment", "") or "Horizontal Center").partition(" ")
        return (t, axis, by or "Center") if t is not None and t is not view else None
    if getattr(view, "SWAlignmentBroken", False) or not view.isDerivedFrom("TechDraw::DrawViewPart"):
        return None
    if any(o.TypeId == "TechDraw::DrawProjGroup" for o in view.InList):
        return None                                 # TechDraw keeps its own projection groups in line
    if getattr(view, "SWFlatPattern", False) or view.TypeId == "TechDraw::DrawViewDetail":
        return None
    parent = default_parent(view)
    if parent is None or not parent.isDerivedFrom("TechDraw::DrawViewPart"):
        return None
    if getattr(view, "SWAuxiliary", ""):

        # edge), slides only that way, and follows the parent
        return (parent, "Along", "Origin") if _along(view, parent) is not None else None
    try:
        dv = App.Vector(view.Direction)
        pd, px, py = D.view_frame(parent)
        dv.normalize()
        if abs(dv.dot(pd)) > 1e-6:
            return None                             # not looking across the parent (an iso, a detail...)
        if abs(dv.dot(px)) > 0.999:
            return parent, "Horizontal", "Origin"  # right / left (or a section cut by a vertical line)
        if abs(dv.dot(py)) > 0.999:
            return parent, "Vertical", "Origin"    # top / bottom
    except Exception as _fw_err:
        _fw_log("drawviewcmds.py:147", _fw_err)
    return None


def _along(view, target):
    """The sheet direction (unit, y up) from target to its auxiliary view: the auxiliary view's line of sight in
    target's frame. None when it does not look across target."""
    try:
        dv = App.Vector(view.Direction)
        dv.normalize()
        pd, px, py = D.view_frame(target)
        if abs(dv.dot(pd)) > 1e-6:
            return None
        n = (dv.dot(px), dv.dot(py))
        L = (n[0] ** 2 + n[1] ** 2) ** 0.5
        return (n[0] / L, n[1] / L) if L > 1e-9 else None
    except Exception:
        return None


def _offset(view, target, axis, by):
    if by == "Origin":
        p, q = model_centre_on_sheet(view), model_centre_on_sheet(target)
    else:
        p, q = view_centre(view), view_centre(target)
    return (q[1] - p[1]) if axis == "Horizontal" else (q[0] - p[0])


def keep_aligned(view):
    """Puts view back in line with the view it is aligned with (only the aligned coordinate). True if moved."""
    a = alignment_of(view)
    if a is None:
        return False
    target, axis, by = a
    if axis == "Along":
        n = _along(view, target)
        if n is None:
            return False
        p, q = model_centre_on_sheet(view), model_centre_on_sheet(target)
        perp = (-n[1], n[0])
        t = (p[0] - q[0]) * perp[0] + (p[1] - q[1]) * perp[1]       # off the line through the parent's origin
        if abs(t) < 1e-7:
            return False
        view.X = float(view.X) - t * perp[0]
        view.Y = float(view.Y) - t * perp[1]
        return True
    try:
        delta = _offset(view, target, axis, by)
    except Exception:
        return False
    if abs(delta) < 1e-7:
        return False
    prop = "Y" if axis == "Horizontal" else "X"
    setattr(view, prop, float(getattr(view, prop)) + delta)
    return True


def aligned_to(target):
    """The views kept in line with target."""
    out = []
    page = None
    for o in target.InList:
        if o.isDerivedFrom("TechDraw::DrawPage"):
            page = o
    for v in (D.views_of(page) if page is not None else target.Document.Objects):
        if v is not target and hasattr(v, "X"):
            a = alignment_of(v)
            if a is not None and a[0] is target:
                out.append(v)
    return out


class _AlignObserver:
    """A view moved (dragged, typed, scripted): it slides along its alignment only, and the views in line with it
    follow. Done just after the change, from the event loop: moving a view from inside TechDraw's own drag (its
    item change) ended FreeCAD on the PC (handcheck-viewalign-b, 11-13)."""
    busy = False
    scheduled = False
    pending = {}            # doc name -> view names moved

    def slotChangedObject(self, obj, prop):
        if prop not in ("X", "Y") or _AlignObserver.busy:
            return
        try:
            doc = obj.Document
            if getattr(doc, "Restoring", False) or getattr(doc, "Transacting", False):   # loading, undo / redo
                return
            if obj.TypeId == "TechDraw::DrawProjGroupItem":
                return                          # TechDraw keeps a projection group's views in line itself
            if not (obj.isDerivedFrom("TechDraw::DrawViewPart") or getattr(obj, "SWAlignedTo", "")):
                return                          # dimensions, notes...: nothing is aligned with them
            _AlignObserver.pending.setdefault(doc.Name, set()).add(obj.Name)
        except Exception:
            return
        try:
            dragging = QtWidgets.QApplication.mouseButtons() != QtCore.Qt.NoButton
        except Exception:
            dragging = False
        if not dragging:
            _flush_alignment()          # typed or scripted: at once, in the same Undo step
            return
        if not _AlignObserver.scheduled:
            _AlignObserver.scheduled = True
            QtCore.QTimer.singleShot(0, _flush_alignment)


def _flush_alignment():
    pending, _AlignObserver.pending = _AlignObserver.pending, {}
    _AlignObserver.scheduled = False
    _AlignObserver.busy = True
    try:
        for dname, names in pending.items():
            try:
                doc = App.getDocument(dname)
            except Exception:
                continue
            for name in names:
                obj = doc.getObject(name)
                if obj is None:
                    continue
                try:
                    keep_aligned(obj)
                    todo, seen = [obj], {obj.Name}
                    while todo:                 # the views in line with it follow (and theirs in turn)
                        t = todo.pop()
                        for v in aligned_to(t):
                            if v.Name not in seen:
                                seen.add(v.Name)
                                keep_aligned(v)
                                todo.append(v)
                except Exception as error:
                    App.Console.PrintLog("FreeCAD: view alignment: %s\n" % error)
    finally:
        _AlignObserver.busy = False


_ALIGN_OBS = []


def install_alignment():
    if not _ALIGN_OBS:
        _ALIGN_OBS.append(_AlignObserver())
        App.addDocumentObserver(_ALIGN_OBS[0])


class AlignPick(QtCore.QObject):
    """After an Align command: the next click on another view lines the picked views up with it."""
    current = None

    def __init__(self, page, views, axis, by):
        super().__init__()
        self.page, self.views, self.axis, self.by = page, views, axis, by
        self.clicks = D.SheetClicks(page, self)
        AlignPick.current = self
        _status("Select a view to align with.")

    def sheet_move(self, p):
        pass

    def sheet_click(self, p):
        target = DV.view_at(self.page, p)
        self.clicks.stop()
        AlignPick.current = None
        if target is None or target in self.views:
            _status("")
            return True
        self.page.Document.openTransaction("Align View")
        try:
            for v in self.views:
                align(v, target, self.axis, self.by)
        except BaseException:
            try:
                self.page.Document.abortTransaction()
            except Exception:
                pass
            raise
        self.page.Document.commitTransaction()
        _status("")
        return True


def _status(text):
    try:
        Gui.getMainWindow().statusBar().showMessage(text, 8000 if text else 1)
    except Exception as _fw_err:
        _fw_log("drawviewcmds.py:297", _fw_err)


TANGENT = ("Visible", "With Font", "Removed", "With Hidden Ends")


def tangent_mode(v):
    """The view's Tangent Edges row: Visible with Hide Ends on is With Hidden Ends (drawings-land285)."""
    mode = getattr(v, "SWTangentEdges", "") or ("Visible" if getattr(v, "SmoothVisible", False) else "Removed")
    if mode == "Visible" and getattr(v, "FWTangentHideEnds", False):
        return "With Hidden Ends"
    return mode


def set_tangent_edges(v, mode):
    ""


    # Hide Ends setting); the other three rows turn Hide Ends off (drawings-land285)
    ends = mode == "With Hidden Ends"
    if ends:
        mode = "Visible"
    try:
        if ends or getattr(v, "FWTangentHideEnds", False):
            _prop(v, "FWTangentHideEnds", "App::PropertyBool", "Tangent Edge Hide Ends")
            v.FWTangentHideEnds = ends
            v.ViewObject.IsoWidth = 0.09 if ends else 0.18      # as drawextras.toggle_tangent_hide_ends draws them
    except Exception as _fw_err:
        _fw_log("drawviewcmds.py:set_tangent_edges", _fw_err)
    _prop(v, "SWTangentEdges", doc="Visible / With Font / Removed")
    v.SWTangentEdges = mode
    v.SmoothVisible = mode == "Visible"          # With Font: TechDraw's own smooth lines give way to ours
    font_tangents(v, mode == "With Font")
    v.recompute()


TANGENT_STYLE = 5
TANGENT_WEIGHT = 0.18


def _tangent_lines(v):
    """The view's visible tangent (smooth) edges in its own 2D frame (unscaled, centred, Y up): [[points]]."""
    import TechDraw
    shapes = []
    for o in DV.source_shapes(v):
        try:
            if not o.Shape.isNull():
                shapes.append(o.Shape)
        except Exception as _fw_err:
            _fw_log("drawviewcmds.py:326", _fw_err)
    if not shapes:
        return []
    import Part
    sh = Part.makeCompound(shapes) if len(shapes) > 1 else shapes[0].copy()
    d, x, y = D.view_frame(v)
    c = sh.BoundBox.Center
    m = App.Matrix(x.x, x.y, x.z, 0, y.x, y.y, y.z, 0, d.x, d.y, d.z, 0, 0, 0, 0, 1)
    sh = sh.copy()
    sh.translate(-c)
    sh = sh.transformGeometry(m)
    try:
        smooth = TechDraw.projectEx(sh, App.Vector(0, 0, 1))[1]
    except Exception as _fw_err:
        _fw_log("drawviewcmds.py:348", _fw_err)
        return []
    out = []
    for e in smooth.Edges:
        try:
            pts = e.discretize(Deflection=0.05) if not e.Curve.TypeId.endswith("Line") else \
                [e.Vertexes[0].Point, e.Vertexes[-1].Point]
        except Exception:
            pts = [e.Vertexes[0].Point, e.Vertexes[-1].Point]
        out.append([App.Vector(p.x, p.y, 0) for p in pts])
    return out


def font_tangents(v, on=True):
    """Tangent Edges With Font: the view's tangent edges as phantom cosmetic lines (kept in SWTangentCosmetics)."""
    from . import drawannot as DA
    _prop(v, "SWTangentCosmetics", "App::PropertyStringList", "the tangent edge lines (With Font)")
    for tag in list(v.SWTangentCosmetics or []):
        try:
            v.removeCosmeticEdge(tag)
        except Exception as _fw_err:
            _fw_log("drawviewcmds.py:360", _fw_err)
    tags = []
    if on:
        for pts in _tangent_lines(v):
            for a, b in zip(pts[:-1], pts[1:]):
                if (b - a).Length < 1e-6:
                    continue
                try:
                    tag = DA._styled(v, v.makeCosmeticLine(a, b), TANGENT_STYLE)
                    ce = v.getCosmeticEdge(tag)
                    fmt = ce.Format
                    if isinstance(fmt, dict):
                        fmt = dict(fmt)
                        fmt["weight"] = TANGENT_WEIGHT
                        ce.Format = fmt
                        if hasattr(v, "replaceCosmeticEdge"):
                            v.replaceCosmeticEdge(ce)
                    tags.append(tag)
                except Exception as _fw_err:
                    _fw_log("drawviewcmds.py:379", _fw_err)
    v.SWTangentCosmetics = tags
    return tags


def refresh_tangents(v):
    """Update View: the With Font tangent lines made again from the model."""
    if getattr(v, "SWTangentEdges", "") == "With Font":
        font_tangents(v, True)
    if getattr(v, "SWShowHiddenOf", []):
        show_hidden_edges(v, list(v.SWShowHiddenOf))      # Show Hidden Edges follows the model too


def open_model(v):
    ""
    srcs = DV.source_shapes(v)
    if not srcs:
        return None
    doc = srcs[0].Document
    mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    for sw in (mdi.subWindowList() if mdi else []):
        try:
            if doc.Label in sw.windowTitle() or doc.Name in sw.windowTitle():
                mdi.setActiveSubWindow(sw)
                App.setActiveDocument(doc.Name)
                return doc
        except Exception as _fw_err:
            _fw_log("drawviewcmds.py:415", _fw_err)
            continue
    try:
        App.setActiveDocument(doc.Name)
        Gui.activateDocument(doc.Name)
        gd = Gui.getDocument(doc.Name)
        if not gd.mdiViewsOfType("Gui::View3DInventor"):
            Gui.runCommand("Std_ViewCreate")
        else:
            gd.activeView()
    except Exception as _fw_err:
        _fw_log("drawviewcmds.py:416", _fw_err)
        from . import fwtell
        fwtell.tell("Could not open a window for the model.", _fw_err)
    return doc


HIDDEN_STYLE = 2


def _frame_shape(v, shapes):
    """Shapes moved into the view's own frame (centred on the view's model, view direction +Z)."""
    import Part
    d, x, y = D.view_frame(v)
    whole = Part.makeCompound(shapes) if len(shapes) > 1 else shapes[0]
    c = DV.model_centre(v)
    m = App.Matrix(x.x, x.y, x.z, 0, y.x, y.y, y.z, 0, d.x, d.y, d.z, 0, 0, 0, 0, 1)
    out = []
    for sh in shapes:
        s = sh.copy()
        s.translate(-c)
        out.append(s.transformGeometry(m))
    return out


def hidden_lines_of(v, names):
    ""

    import Part
    import TechDraw
    comps = DV.components(DV.source_shapes(v))
    if not comps or not names:
        return []
    shapes = [c["shape"] for c in comps if c["shape"] is not None and not c["shape"].isNull()]
    if not shapes:
        return []
    framed = _frame_shape(v, shapes)
    whole = Part.makeCompound(framed)
    try:
        res = TechDraw.projectEx(whole, App.Vector(0, 0, 1))
    except Exception as _fw_err:
        _fw_log("drawviewcmds.py:466", _fw_err)
        return []
    hidden = [e for k in (5, 8) for e in (res[k].Edges if res[k] is not None and not res[k].isNull() else [])]
    mine = []
    for c, sh in zip([c for c in comps if c["shape"] is not None and not c["shape"].isNull()], framed):
        if c["name"] in names or c.get("label") in names:
            try:
                r = TechDraw.projectEx(sh, App.Vector(0, 0, 1))
                mine += [e for k in (0, 3, 5, 8) for e in (r[k].Edges if r[k] is not None and not r[k].isNull() else [])]
            except Exception as _fw_err:
                _fw_log("drawviewcmds.py:463", _fw_err)
    if not mine:
        return []
    foot = Part.makeCompound(mine)
    out = []
    for e in hidden:
        try:
            mid = e.valueAt((e.FirstParameter + e.LastParameter) / 2.0)
            if foot.distToShape(Part.Vertex(mid))[0] > 1e-4:
                continue
            pts = [e.Vertexes[0].Point, e.Vertexes[-1].Point] if e.Curve.TypeId.endswith("Line") else \
                e.discretize(Deflection=0.05)
        except Exception as _fw_err:
            _fw_log("drawviewcmds.py:489", _fw_err)
            continue
        out.append([App.Vector(p.x, p.y, 0) for p in pts])
    return out


def show_hidden_edges(v, names):
    """Drawing View Properties > Show Hidden Edges: the hidden lines of the components named drawn dashed in a
    view that removes hidden lines (cosmetic lines kept in SWHiddenOfCosmetics); [] takes them off."""
    from . import drawannot as DA
    _prop(v, "SWShowHiddenOf", "App::PropertyStringList", "Show Hidden Edges: the components")
    _prop(v, "SWHiddenOfCosmetics", "App::PropertyStringList", "the hidden lines shown (Show Hidden Edges)")
    for tag in list(v.SWHiddenOfCosmetics or []):
        try:
            v.removeCosmeticEdge(tag)
        except Exception as _fw_err:
            _fw_log("drawviewcmds.py:491", _fw_err)
    v.SWShowHiddenOf = list(names)
    tags = []
    seen = set()
    for pts in hidden_lines_of(v, names):
        for a, b in zip(pts[:-1], pts[1:]):
            if (b - a).Length < 1e-6:
                continue
            key = tuple(sorted([(round(a.x, 4), round(a.y, 4)), (round(b.x, 4), round(b.y, 4))]))
            if key in seen:
                continue            # front and back edges of a hidden face line up: one line
            seen.add(key)
            try:
                tags.append(DA._styled(v, v.makeCosmeticLine(a, b), HIDDEN_STYLE) or "")
            except Exception as _fw_err:
                _fw_log("drawviewcmds.py:506", _fw_err)
    v.SWHiddenOfCosmetics = [t for t in tags if t]
    v.Document.recompute()
    return v.SWHiddenOfCosmetics


class ViewPropertiesDialog(QtWidgets.QDialog):
    ""

    def __init__(self, view, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.view = view
        self.setObjectName("SWViewPropertiesDialog")
        self.setWindowTitle("Drawing View Properties")
        lay = QtWidgets.QVBoxLayout(self)
        tabs = QtWidgets.QTabWidget(self)
        lay.addWidget(tabs)
        page = QtWidgets.QWidget()
        tabs.addTab(page, "View Properties")
        g = QtWidgets.QGridLayout(page)
        self.name = QtWidgets.QLineEdit(view.Label, page)
        self.name.setObjectName("SWViewName")
        srcs = DV.source_shapes(view)
        model = QtWidgets.QLabel(", ".join("%s (%s)" % (o.Label, o.Document.Label) for o in srcs) or "-", page)
        model.setObjectName("SWViewModel")
        self.scale = QtWidgets.QLineEdit("%g" % DV.view_scale(view), page)
        self.scale.setObjectName("SWViewScale")
        self.style = QtWidgets.QComboBox(page)
        self.style.setObjectName("SWViewDisplayStyle")
        self.style.addItems(D.DISPLAY_STYLES)
        self.style.setCurrentText(getattr(view, "SWDisplayStyle", "") or "Hidden Lines Removed")
        self.tangent = QtWidgets.QComboBox(page)
        self.tangent.setObjectName("SWViewTangentEdges")
        self.tangent.addItems(TANGENT)
        self.tangent.setCurrentText(tangent_mode(view))      # OK writes it back: keep Hide Ends
        self.lock = QtWidgets.QCheckBox("Lock view position", page)
        self.lock.setObjectName("SWViewLock")
        self.lock.setChecked(bool(view.LockPosition))
        for n, (lab, w) in enumerate((("View name:", self.name), ("Model:", model), ("Scale:", self.scale),
                                      ("Display style:", self.style), ("Tangent edges:", self.tangent))):
            g.addWidget(QtWidgets.QLabel(lab, page), n, 0)
            g.addWidget(w, n, 1)
        g.addWidget(self.lock, 5, 0, 1, 2)
        self.config_group(page, g, 6)
        # Show Hidden Edges: the components (or bodies) whose hidden lines the view shows
        hp = QtWidgets.QWidget()
        tabs.addTab(hp, "Show Hidden Edges")
        hl = QtWidgets.QVBoxLayout(hp)
        hl.addWidget(QtWidgets.QLabel("Show the hidden edges of:", hp))
        self.hidden_list = QtWidgets.QListWidget(hp)
        self.hidden_list.setObjectName("SWViewShowHiddenEdges")
        on = set(getattr(view, "SWShowHiddenOf", []) or [])
        try:
            comps = DV.components(srcs)
        except Exception:
            comps = []
        for c in comps:
            it = QtWidgets.QListWidgetItem(c.get("label") or c["name"])
            it.setData(QtCore.Qt.UserRole, c["name"])
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked if c["name"] in on else QtCore.Qt.Unchecked)
            self.hidden_list.addItem(it)
        hl.addWidget(self.hidden_list)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.setObjectName("SWViewPropertiesButtons")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def config_group(self, page, g, row):
        ""

        self.cfg_names, self.cfg_doc = [], None
        try:
            from . import drawpartcfg as PC
            doc, cur = PC.view_configuration(self.view)
            names, active = PC.configurations(doc)
        except Exception:
            doc, cur, names, active = None, "", [], None
        if not names:
            return
        self.cfg_names, self.cfg_doc = names, doc
        box = QtWidgets.QGroupBox("Configuration information", page)
        box.setObjectName("SWViewConfigInfo")
        bl = QtWidgets.QVBoxLayout(box)
        self.cfg_in_use = QtWidgets.QRadioButton('Use model\'s "in-use" or last saved configuration', box)
        self.cfg_in_use.setObjectName("SWViewConfigInUse")
        self.cfg_named = QtWidgets.QRadioButton("Use named configuration:", box)
        self.cfg_named.setObjectName("SWViewConfigNamed")
        self.cfg_list = QtWidgets.QComboBox(box)
        self.cfg_list.setObjectName("SWViewConfigList")
        self.cfg_list.addItems(names)
        named = bool(cur) and cur != active
        self.cfg_list.setCurrentText(cur if named else active)
        (self.cfg_named if named else self.cfg_in_use).setChecked(True)
        from . import drawlive as DL
        DL.sets(self.cfg_named, True, self.cfg_list)  # a configuration picked: Use named configuration (never greyed)
        for w in (self.cfg_in_use, self.cfg_named, self.cfg_list):
            bl.addWidget(w)
        g.addWidget(box, row, 0, 1, 2)

    def accept(self):
        v = self.view
        doc = v.Document
        doc.openTransaction("Drawing View Properties")
        try:
            try:
                if self.cfg_names:
                    from . import drawpartcfg as PC
                    want = self.cfg_list.currentText() if self.cfg_named.isChecked() else ""
                    _d, cur = PC.view_configuration(v)
                    if (want or "") != (cur if cur != PC.configurations(self.cfg_doc)[1] else ""):
                        PC.apply_view(v, want)
                if self.name.text().strip():
                    v.Label = self.name.text().strip()
                text = self.scale.text().replace(" ", "")
                if ":" in text:
                    a, b = text.split(":", 1)
                    k = float(a) / float(b)
                else:
                    k = float(text)
                if k > 0 and abs(k - DV.view_scale(v)) > 1e-9:
                    v.ScaleType = "Custom"
                    v.Scale = k
                D.set_display_style(v, self.style.currentText())
                set_tangent_edges(v, self.tangent.currentText())
                v.LockPosition = self.lock.isChecked()
                names = [self.hidden_list.item(i).data(QtCore.Qt.UserRole) for i in range(self.hidden_list.count())
                         if self.hidden_list.item(i).checkState() == QtCore.Qt.Checked]
                if names or getattr(v, "SWShowHiddenOf", []):
                    show_hidden_edges(v, names)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: View Properties: %s\n" % error)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        doc.recompute()
        super().accept()


# --------------------------------------------------------------------------- commands
ALIGN = {
    "FreeWorks_DrawAlignHorizontalOrigin": ("Align Horizontal to Origin", "Horizontal", "Origin"),
    "FreeWorks_DrawAlignVerticalOrigin": ("Align Vertical to Origin", "Vertical", "Origin"),
    "FreeWorks_DrawAlignHorizontalCenter": ("Align Horizontal by Center", "Horizontal", "Center"),
    "FreeWorks_DrawAlignVerticalCenter": ("Align Vertical by Center", "Vertical", "Center"),
}
COMMANDS = {
    "FreeWorks_DrawLockViewPosition": ("Lock View Position", "TechDraw_View",
                                       "Locks (or unlocks) the picked view in place."),
    "FreeWorks_DrawBreakAlignment": ("Break Alignment", "TechDraw_View", "The picked view no longer follows its parent."),
    "FreeWorks_DrawDefaultAlignment": ("Default Alignment", "TechDraw_View",
                                       "Lines the picked view up with the view it was made from again."),
    "FreeWorks_DrawTangentVisible": ("Tangent Edges Visible", "TechDraw_View", "Shows tangent edges."),
    "FreeWorks_DrawTangentWithFont": ("Tangent Edges With Font", "TechDraw_View", "Shows tangent edges, thin."),
    "FreeWorks_DrawTangentRemoved": ("Tangent Edges Removed", "TechDraw_View", "Hides tangent edges."),
    "FreeWorks_DrawTangentWithHiddenEnds": ("Tangent Edges With Hidden Ends", "TechDraw_View",
                                            "Shows tangent edges with their ends cut back."),
    "FreeWorks_DrawHideView": ("Hide", "TechDraw_View", "Hides the picked view."),
    "FreeWorks_DrawShowHiddenViews": ("Show Hidden Views", "TechDraw_View", "Shows the sheet's hidden views."),
    "FreeWorks_DrawOpenModel": ("Open Model", "TechDraw_View", "Opens the model the picked view shows."),
    "FreeWorks_DrawViewProperties": ("Properties...", "TechDraw_View", "The picked view's properties."),
}
for _n, (_t, _a, _b) in ALIGN.items():
    COMMANDS[_n] = (_t, "TechDraw_View", "Click a view to line the picked view up with.")


class _Command:
    def __init__(self, name):
        self.name = name
        self.text, self.pixmap, self.tip = COMMANDS[name]

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": D.pixmap(self.pixmap)}

    def IsActive(self):
        page = D.active_page()
        if page is None:
            return False
        if self.name == "FreeWorks_DrawShowHiddenViews":
            return any(not v.ViewObject.Visibility for v in D.views_of(page) if v.ViewObject
                       and getattr(v, "SWPhantomOf", "") == "" and not getattr(v, "SWAlternateOf", ""))
        views = picked_views()
        if not views:
            return False
        if self.name == "FreeWorks_DrawDefaultAlignment":
            return any(default_parent(v) is not None for v in views)
        return True

    def Activated(self):
        page = D.active_page()
        views = picked_views()
        n = self.name
        if n == "FreeWorks_DrawShowHiddenViews":
            for v in D.views_of(page):
                if v.ViewObject and not v.ViewObject.Visibility and not getattr(v, "SWAlternateOf", ""):
                    v.ViewObject.Visibility = True
            return
        if not views:
            return
        doc = views[0].Document
        if n in ALIGN:
            _, axis, by = ALIGN[n]
            AlignPick(page, views, axis, by)
            return
        if n == "FreeWorks_DrawOpenModel":
            open_model(views[0])
            return
        if n == "FreeWorks_DrawViewProperties":
            ViewPropertiesDialog(views[0]).exec_()
            return
        doc.openTransaction(self.text)
        try:
            for v in views:
                if n == "FreeWorks_DrawLockViewPosition":
                    v.LockPosition = not v.LockPosition
                elif n == "FreeWorks_DrawBreakAlignment":
                    break_alignment(v)
                elif n == "FreeWorks_DrawDefaultAlignment":
                    default_alignment(v)
                elif n == "FreeWorks_DrawTangentVisible":
                    set_tangent_edges(v, "Visible")
                elif n == "FreeWorks_DrawTangentWithFont":
                    set_tangent_edges(v, "With Font")
                elif n == "FreeWorks_DrawTangentRemoved":
                    set_tangent_edges(v, "Removed")
                elif n == "FreeWorks_DrawTangentWithHiddenEnds":
                    set_tangent_edges(v, "With Hidden Ends")
                elif n == "FreeWorks_DrawHideView":
                    v.ViewObject.Visibility = False
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        doc.recompute()


# --------------------------------------------------------------------------- Hide/Show Edges
def hidden_edges(v):
    return list(getattr(v, "SWHiddenEdges", []) or [])


def set_edge_hidden(v, index, hidden=True):
    ""
    if "SWHiddenEdges" not in v.PropertiesList:
        v.addProperty("App::PropertyIntegerList", "SWHiddenEdges", "FreeCAD", "Hide/Show Edges: hidden edges")
    keep = [i for i in hidden_edges(v) if i != index]
    if hidden:
        keep.append(index)
    v.SWHiddenEdges = keep
    try:
        from . import drawlineformat          # the edge keeps its Line Format colour, thickness and style
        drawlineformat.apply_edge(v, index)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Hide/Show Edges: %s\n" % error)
    v.touch()


class HideShowEdgesPanel(D._Panel):
    TITLE = "Hide/Show Edges"
    PIXMAP = "TechDraw_View"

    def build(self):
        self.say("Click edges in a view to hide them. Pick a hidden edge in the list and Show to bring it back.")
        box, lay = D._group("Hidden Edges", self.form)
        self.list = QtWidgets.QListWidget(box)
        self.list.setObjectName("SWHiddenEdgesList")
        lay.addWidget(self.list)
        self.show_btn = QtWidgets.QPushButton("Show", box)
        self.show_btn.setObjectName("SWHiddenEdgesShow")
        self.show_btn.clicked.connect(self.show_picked)
        lay.addWidget(self.show_btn)
        self.lay.addWidget(box)
        self.changed = []
        self.fill()

    def fill(self):
        self.list.clear()
        for v in D.views_of(self.page):
            for i in hidden_edges(v):
                it = QtWidgets.QListWidgetItem("Edge%d@%s" % (i + 1, v.Label))
                it.setData(QtCore.Qt.UserRole, (v.Name, i))
                self.list.addItem(it)

    def sheet_click(self, p):
        from . import drawviews as DV, drawannot as DA
        v = DV.view_at(self.page, p)
        if v is None:
            self.say("Click an edge inside a drawing view.")
            return True
        hit = DA.edge_at(v, DV.to_geometry(v, p), 2.0 / DV.view_scale(v))
        if hit is None:
            self.say("Click on an edge.")
            return True
        set_edge_hidden(v, hit[0], True)
        self.changed.append((v.Name, hit[0]))
        self.doc.recompute()
        self.fill()
        return True

    def show_picked(self):
        for it in self.list.selectedItems():
            name, i = it.data(QtCore.Qt.UserRole)
            v = self.doc.getObject(name)
            if v is not None:
                set_edge_hidden(v, i, False)
        self.doc.recompute()
        self.fill()

    def reject(self):
        for name, i in self.changed:
            v = self.doc.getObject(name)
            if v is not None:
                set_edge_hidden(v, i, False)
        self.doc.recompute()
        return D._Panel.reject(self) if hasattr(D._Panel, "reject") else True


class _HideShowCommand:
    def GetResources(self):
        return {"MenuText": "Hide/Show Edges", "ToolTip": "Hides the model edges you click in a drawing view, or "
                "shows hidden ones again.", "Pixmap": D.pixmap("TechDraw_View")}

    def IsActive(self):
        page = D.active_page()
        return page is not None and bool(D.views_of(page)) and not D.busy()

    def Activated(self):
        page = D.active_page()
        if page is not None:
            D._show(HideShowEdgesPanel(page))


def register():
    install_alignment()
    if "FreeWorks_DrawHideShowEdges" not in Gui.listCommands():
        Gui.addCommand("FreeWorks_DrawHideShowEdges", _HideShowCommand())
    for name in COMMANDS:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Command(name))
