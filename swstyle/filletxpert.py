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

from . import filletpm

FILLET = "PartDesign::Fillet"


def boxes(panel):
    """The FilletXpert boxes for panel (hidden while Manual is the tab)."""
    tabs_box = filletpm._box("FilletXpert")
    bar = QtWidgets.QTabBar(tabs_box)
    bar.setObjectName("SWFilletXpertTabs")
    for t in ("Add", "Change", "Corner"):
        bar.addTab(t)
    bar.setExpanding(False)
    tabs_box.layout().addWidget(bar)
    panel.xpert_bar = bar

    add = filletpm._box("Items To Fillet")
    panel.xpert_list = filletpm._ItemsList(panel, "SWFilletXpertItems")
    add.layout().addWidget(panel.xpert_list)
    row = QtWidgets.QHBoxLayout()
    row.addWidget(QtWidgets.QLabel("R", add))
    panel.xpert_radius = filletpm._spin(add, "SWFilletXpertRadius", "mm", 0.001, 1e6)
    panel.xpert_radius.setValue(panel.radius.value())
    panel.xpert_radius.valueChanged.connect(lambda v: panel.radius.setValue(v))
    row.addWidget(panel.xpert_radius)
    add.layout().addLayout(row)
    apply = QtWidgets.QPushButton("Apply", add)
    apply.setObjectName("SWFilletXpertApply")
    apply.clicked.connect(lambda: apply_add(panel))
    add.layout().addWidget(apply)

    # same settings as the Manual tab's (each pair kept in step)
    add_options = filletpm._box("Options")
    for name, text, manual in (("SWFilletXpertThrough", "Select through faces", getattr(panel, "through", None)),
                               ("SWFilletXpertTangent", "Tangent propagation", getattr(panel, "tangent", None))):
        if manual is None:
            continue
        twin = QtWidgets.QCheckBox(text, add_options)
        twin.setObjectName(name)
        twin.setToolTip(manual.toolTip() or text)
        twin.setChecked(manual.isChecked())
        twin.toggled.connect(lambda on, m=manual: m.isChecked() != on and m.setChecked(on))
        manual.toggled.connect(lambda on, t=twin: t.isChecked() != on and t.setChecked(on))
        add_options.layout().addWidget(twin)

    change = filletpm._box("Change")
    panel.change_list = filletpm._ItemsList(panel, "SWFilletXpertChange")
    panel.change_list.panel = _ChangeProxy(panel)
    change.layout().addWidget(QtWidgets.QLabel("Fillets to change:", change))
    change.layout().addWidget(panel.change_list)
    row = QtWidgets.QHBoxLayout()
    row.addWidget(QtWidgets.QLabel("R", change))
    panel.change_radius = filletpm._spin(change, "SWFilletXpertChangeRadius", "mm", 0.001, 1e6)
    panel.change_radius.setValue(panel.radius.value())
    row.addWidget(panel.change_radius)
    change.layout().addLayout(row)
    buttons = QtWidgets.QHBoxLayout()
    resize = QtWidgets.QPushButton("Resize", change)
    resize.setObjectName("SWFilletXpertResize")
    resize.clicked.connect(lambda: resize_fillets(panel))
    remove = QtWidgets.QPushButton("Remove", change)
    remove.setObjectName("SWFilletXpertRemove")
    remove.clicked.connect(lambda: remove_fillets(panel))
    buttons.addWidget(resize)
    buttons.addWidget(remove)
    change.layout().addLayout(buttons)
    existing = filletpm._box("Existing Fillets")
    panel.sort_by_size = QtWidgets.QCheckBox("Sort by size", existing)
    panel.sort_by_size.setObjectName("SWFilletXpertSort")
    panel.sort_by_size.toggled.connect(lambda on: fill_existing(panel))
    existing.layout().addWidget(panel.sort_by_size)
    panel.existing = QtWidgets.QListWidget(existing)
    panel.existing.setObjectName("SWFilletXpertExisting")
    panel.existing.setFixedHeight(84)
    panel.existing.itemClicked.connect(lambda item: _pick_existing(panel, item))
    existing.layout().addWidget(panel.existing)

    corner = filletpm._box("Corner Faces")
    panel.corner_list = filletpm._ItemsList(panel, "SWFilletXpertCornerFaces")
    panel.corner_list.panel = _CornerProxy(panel, "corners")
    panel.corner_list.installEventFilter(filletpm._Activate(_CornerActive(panel), "corners", panel.corner_list))
    corner.layout().addWidget(panel.corner_list)
    show = QtWidgets.QPushButton("Show Alternatives", corner)
    show.setObjectName("SWFilletXpertShowAlternatives")
    show.clicked.connect(lambda: show_alternatives(panel, show))
    corner.layout().addWidget(show)
    panel.show_alternatives = show
    targets = filletpm._box("Copy Targets")
    panel.target_list = filletpm._ItemsList(panel, "SWFilletXpertCopyTargets")
    panel.target_list.panel = _CornerProxy(panel, "targets")
    panel.target_list.installEventFilter(filletpm._Activate(_CornerActive(panel), "targets", panel.target_list))
    targets.layout().addWidget(panel.target_list)
    copy = QtWidgets.QPushButton("Copy to", targets)
    copy.setObjectName("SWFilletXpertCopyTo")
    copy.clicked.connect(lambda: copy_to(panel))
    targets.layout().addWidget(copy)
    options = filletpm._box("Options")
    panel.corner_highlight = QtWidgets.QCheckBox("Enable highlighting", options)
    panel.corner_highlight.setObjectName("SWFilletXpertHighlight")
    panel.corner_highlight.setToolTip("Show the fillet corners that have other shapes to choose from")
    panel.corner_highlight.setChecked(True)
    panel.corner_highlight.toggled.connect(lambda on: _fill_corners(panel))
    options.layout().addWidget(panel.corner_highlight)
    panel.corners = []          # [(fillet feature's Name, vertex name in its base)] Corner Faces
    panel.targets = []          # the same, Copy Targets
    panel.corner_active = "corners"
    panel.corner_choice = None  # (feature, vertex name, key) last applied

    panel.xpert_add = [add, add_options]
    panel.xpert_change = [change, existing]
    panel.xpert_corner = [corner, targets, options]
    panel.changing = []         # fillet features picked in Change
    bar.currentChanged.connect(lambda i: _subtab(panel, i))
    return [tabs_box, add, add_options, change, existing, corner, targets, options]


class _CornerActive:
    """The Corner tab's two boxes: a click makes one of them the one taking picks."""

    def __init__(self, panel):
        self.panel = panel

    @property
    def active(self):
        return self.panel.corner_active

    @active.setter
    def active(self, key):
        self.panel.corner_active = key

    def _fill(self):
        _fill_corners(self.panel)


class _CornerProxy:
    """A Corner tab list's right-click menu acts on its corners."""

    def __init__(self, panel, key):
        self.panel, self.key = panel, key

    def clear_items(self):
        setattr(self.panel, self.key, [])
        _fill_corners(self.panel)

    def remove_item(self, row):
        rows = getattr(self.panel, self.key)
        if 0 <= row < len(rows):
            del rows[row]
            _fill_corners(self.panel)


class _ChangeProxy:
    """The Change list's right-click menu acts on the fillets to change."""

    def __init__(self, panel):
        self.panel = panel

    def clear_items(self):
        self.panel.changing = []
        _fill_change(self.panel)

    def remove_item(self, row):
        if 0 <= row < len(self.panel.changing):
            del self.panel.changing[row]
            _fill_change(self.panel)


def mode(panel):
    if panel.tabs.currentIndex() != 1:
        return "manual"
    return ("add", "change", "corner")[panel.xpert_bar.currentIndex()]


def tab_changed(panel, index):
    panel.list_backup = getattr(panel, "list_backup", None)
    if index == 1:
        _subtab(panel, panel.xpert_bar.currentIndex())
    else:
        panel.list = panel.manual_list if hasattr(panel, "manual_list") else panel.list
        panel._show_base()
        panel.update()


def _subtab(panel, index):
    if not hasattr(panel, "manual_list"):
        panel.manual_list = panel.list
    for w in panel.xpert_add:
        filletpm.box_visible(w, index == 0)
    for w in panel.xpert_change:
        filletpm.box_visible(w, index == 1)
    for w in getattr(panel, "xpert_corner", []):
        filletpm.box_visible(w, index == 2)
    if index == 0:
        panel.list = panel.xpert_list
        panel._show_base()
        panel.update()
    else:
        # Change and Corner work on the finished part: show it as it is, without the new fillet.
        panel.items = []
        panel.update()
        panel.list = panel.manual_list
        _show_tip(panel)
        fill_existing(panel)
        _fill_change(panel)
        _fill_corners(panel)


def _show_tip(panel):
    try:
        tip = panel.body.Tip
        for f in filletpm._features(panel.body):
            f.ViewObject.Visibility = f is tip
    except Exception as _fw_err:
        _fw_log("filletxpert.py:224", _fw_err)


def picked(panel, obj, sub):
    """A pick while Change is the tab: the fillet feature that made the picked face."""
    if mode(panel) == "corner":
        return corner_picked(panel, obj, sub)
    if mode(panel) != "change":
        return False
    from . import refplane
    obj, sub = refplane.resolve(obj, sub or "")
    feature = None
    if _is_fillet(obj) and not sub:
        feature = obj
    elif sub.startswith("Face"):
        try:
            from . import contextbar
            owner = contextbar.owner_feature(obj, sub)
        except Exception:
            owner = None
        if _is_fillet(owner):
            feature = owner
    if feature is not None:
        if feature in panel.changing:
            panel.changing.remove(feature)
        else:
            panel.changing.append(feature)
            panel.change_radius.setValue(feature.Radius.Value)
        _fill_change(panel)
    return True


def _fill_change(panel):
    panel.change_list.clear()
    for f in panel.changing:
        panel.change_list.addItem("%s (R %smm)" % (f.Label, filletpm._number(f.Radius.Value)))
    edges = []
    for f in panel.changing:
        try:
            edges += [e for face in filletpm.new_faces(f.Base[0].Shape, f.Shape) for e in face.Edges]
        except Exception as _fw_err:
            _fw_log("filletxpert.py:265", _fw_err)
    panel.overlay.show_picks(edges)
    panel.overlay.show_preview([])


def fill_existing(panel):
    ""

    fillets = [f for f in filletpm._features(panel.body) if _is_fillet(f) and f is not panel.feature]
    sizes = []
    for f in fillets:
        r = round(f.Radius.Value, 6)
        if r not in sizes:
            sizes.append(r)
    if panel.sort_by_size.isChecked():
        sizes.sort()
    panel.existing.clear()
    for r in sizes:
        names = [f.Name for f in fillets if abs(round(f.Radius.Value, 6) - r) < 1e-9]
        item = QtWidgets.QListWidgetItem("%smm (%d)" % (filletpm._number(r), len(names)))
        item.setToolTip("Put every %smm fillet in Fillets to change" % filletpm._number(r))
        item.setData(QtCore.Qt.UserRole, names)
        panel.existing.addItem(item)


def _pick_existing(panel, item):
    names = item.data(QtCore.Qt.UserRole) or []
    if isinstance(names, str):
        names = [names]
    found = [panel.doc.getObject(n) for n in names]
    found = [f for f in found if f is not None]
    for f in found:
        if f not in panel.changing:
            panel.changing.append(f)
    if found:
        panel.change_radius.setValue(found[0].Radius.Value)
    _fill_change(panel)


def apply_add(panel):
    """Apply (Add): keep this fillet as its own Undo step and start the next one."""
    if not panel.items or not panel.ok:
        return
    panel.remember()
    panel.doc.commitTransaction()
    try:
        panel.feature.ViewObject.Visibility = True
    except Exception as _fw_err:
        _fw_log("filletxpert.py:296", _fw_err)
    panel.feature = None
    panel.items = []
    panel.base = panel.body.Tip
    panel.before_tip = panel.body.Tip
    panel.doc.openTransaction("Fillet")
    panel._show_base()
    panel.update()


def _commit_and_reopen(panel, text, work):
    panel.doc.commitTransaction()       # the open page has nothing pending in Change
    panel.doc.openTransaction(text)
    try:
        work()
        panel.doc.recompute()
        panel.doc.commitTransaction()
    except Exception as error:
        panel.doc.abortTransaction()
        App.Console.PrintError("FreeCAD: FilletXpert: %s\n" % error)
    panel.doc.openTransaction("Fillet")
    panel.changing = []
    panel.base = panel.body.Tip
    panel.before_tip = panel.body.Tip
    _show_tip(panel)
    fill_existing(panel)
    _fill_change(panel)


def _need_picks(panel):
    try:
        Gui.getMainWindow().statusBar().showMessage("Pick the fillets to change first (a face of each, or a size under Existing Fillets)", 6000)
    except Exception as _fw_err:
        _fw_log("filletxpert.py:need picks", _fw_err)


def resize_fillets(panel):
    if not panel.changing:
        _need_picks(panel)
        return
    value = panel.change_radius.value()
    targets = list(panel.changing)

    def work():
        for f in targets:
            f.Radius = value
    _commit_and_reopen(panel, "Resize Fillets", work)


def remove_fillets(panel):
    if not panel.changing:
        _need_picks(panel)
        return
    targets = list(panel.changing)

    def work():
        for f in targets:
            delete_fillet(f)
    _commit_and_reopen(panel, "Remove Fillets", work)


def _carried(old_shape, name, new_shape):
    """The name in new_shape of old_shape's element name (an edge, face or vertex), by where it is."""
    import Part
    from . import multiradius
    try:
        old = old_shape.getElement(name)
    except Exception:
        return None
    if name.startswith("Vertex"):
        hits = [k for k, v in enumerate(new_shape.Vertexes, 1) if (v.Point - old.Point).Length < 1e-6]
        return "Vertex%d" % hits[0] if hits else None
    if name.startswith("Edge"):
        for k, e in enumerate(new_shape.Edges, 1):
            if multiradius._same_edge(e, old):
                return "Edge%d" % k
        mid = Part.Vertex(old.valueAt(0.5 * (old.FirstParameter + old.LastParameter)))
        near = [(e.Length, k) for k, e in enumerate(new_shape.Edges, 1) if e.distToShape(mid)[0] < 1e-6]
        return "Edge%d" % max(near)[1] if near else None
    if name.startswith("Face"):
        u0, u1, v0, v1 = old.ParameterRange
        p = Part.Vertex(old.valueAt(0.5 * (u0 + u1), 0.5 * (v0 + v1)))
        if not old.isInside(p.Point, 1e-6, True):
            p = Part.Vertex(old.CenterOfMass)
        near = [k for k, f in enumerate(new_shape.Faces, 1)
                if f.Surface.TypeId == old.Surface.TypeId and f.distToShape(p)[0] < 1e-6]
        return "Face%d" % near[0] if near else None
    return None


def _repoint(child, old, new):
    """A feature that picked old's edges or faces (child.Base = (old, subs)) picks the same ones on
    new: FreeCAD moves the link but keeps old's names, and they name other edges (or nothing) on
    new, so the next fillet failed when FilletXpert removed or remade the one before it."""
    base = getattr(child, "Base", None)
    if not base or not isinstance(base, tuple) or new is None or base[0] not in (old, new) or base[0] is new and old is new:
        return
    subs = []
    for sub in base[1]:
        name = sub.split(".")[-1].lstrip("?")
        got = _carried(old.Shape, name, new.Shape) if name else None
        subs.append(got or sub)
    try:
        child.Base = (new, subs)
    except Exception as _fw_err:
        _fw_log("filletxpert.py:_repoint", _fw_err)


def delete_fillet(f):
    body = f.getParentGeoFeatureGroup()
    base = f.BaseFeature
    for child in [o for o in f.InList]:
        _repoint(child, f, base)
        if getattr(child, "BaseFeature", None) is f:
            child.BaseFeature = base
    if body.Tip is f:
        body.Tip = base
    body.removeObject(f)
    f.Document.removeObject(f.Name)


# --------------------------------------------------------------------------- Corner
def _is_fillet(f):
    from . import multiradius, setbackfillet
    return f is not None and (f.TypeId == FILLET or multiradius.is_multi_radius(f)
                              or setbackfillet.is_setback_fillet(f))


def fillet_pairs(f):
    """(base shape, [(edge index in it, radius)]) of a fillet feature."""
    from . import multiradius
    base = f.BaseFeature.Shape
    source = f.Base[0].Shape if f.Base else base
    subs = list(f.Base[1]) if f.Base else []
    if getattr(f, "UseAllEdges", False) or (f.Base and not subs):
        subs = [""]
    radii = list(getattr(f, "ItemRadii", []) or [])
    return base, multiradius.edge_radii(base, source, subs, radii, f.Radius.Value)


def corner_vertices(f):
    """[(vertex name in the base, vertex)] where two or more of f's filleted edges meet."""
    from . import setbackfillet
    base, pairs = fillet_pairs(f)
    radius = dict(pairs)
    out = []
    for n, v in enumerate(base.Vertexes, 1):
        edges = setbackfillet.vertex_edges(base, v)
        idx = [next((i for i, g in enumerate(base.Edges, 1) if g.isSame(e)), None) for e in edges]
        if len([i for i in idx if i in radius]) >= 2:
            out.append(("Vertex%d" % n, v))
    return out


def corner_picked(panel, obj, sub):
    """A face of a fillet, near a corner of its fillets: Corner Faces or Copy Targets."""
    from . import refplane
    obj, sub = refplane.resolve(obj, sub or "")
    if not sub.startswith("Face"):
        return True
    try:
        from . import contextbar
        owner = contextbar.owner_feature(obj, sub)
        face = obj.Shape.getElement(sub)
    except Exception:
        return True
    if not _is_fillet(owner):
        return True
    best = None
    for name, v in corner_vertices(owner):
        try:
            d = face.distToShape(v)[0]
        except Exception:
            continue
        if best is None or d < best[0]:
            best = (d, name)
    if best is None:
        return True
    rows = panel.targets if panel.corner_active == "targets" else panel.corners
    entry = (owner.Name, best[1])
    if entry in rows:
        rows.remove(entry)
    else:
        rows.append(entry)
    _fill_corners(panel)
    return True


def _fill_corners(panel):
    for widget, rows in ((panel.corner_list, panel.corners), (panel.target_list, panel.targets)):
        widget.clear()
        for name, vname in rows:
            f = panel.doc.getObject(name)
            widget.addItem("%s %s" % (f.Label if f is not None else name, vname.replace("Vertex", "Vertex<") + ">"))
    pick = filletpm.PICK_BLUE
    panel.corner_list.setStyleSheet("QListWidget { background: %s; }" % (pick if panel.corner_active == "corners" else "white"))
    panel.target_list.setStyleSheet("QListWidget { background: %s; }" % (pick if panel.corner_active == "targets" else "white"))
    edges = []
    for name, vname in panel.corners + panel.targets:
        try:
            base, pairs = fillet_pairs(panel.doc.getObject(name))
            v = base.getElement(vname)
            from . import setbackfillet
            edges += [e for e in setbackfillet.vertex_edges(base, v)]
        except Exception as _fw_err:
            _fw_log("filletxpert.py:444", _fw_err)
    panel.overlay.show_picks(edges)
    panel.overlay.show_preview(corner_faces(panel) if getattr(panel, "corner_highlight", None) is not None
                               and panel.corner_highlight.isChecked() and mode(panel) == "corner" else [])


def corner_faces(panel):
    """Enable highlighting: the fillet faces at each corner of the part that has other shapes to
    choose from (two or more fillets of one feature meet there)."""
    out = []
    for f in filletpm._features(panel.body):
        if not _is_fillet(f) or f is panel.feature:
            continue
        try:
            corners = corner_vertices(f)
            if not corners:
                continue
            new = filletpm.new_faces(f.BaseFeature.Shape, f.Shape)
            reach = max(f.Radius.Value, 1e-3) * 1.5
            for _name, v in corners:
                out += [face for face in new if face.distToShape(v)[0] < reach and not any(face.isSame(o) for o in out)]
        except Exception as _fw_err:
            _fw_log("filletxpert.py:corner faces", _fw_err)
    return out


def alternatives(panel):
    """[(label, key, shape)] for the first corner in Corner Faces."""
    if not panel.corners:
        return []
    from . import setbackfillet
    name, vname = panel.corners[0]
    try:
        base, pairs = fillet_pairs(panel.doc.getObject(name))
        v = base.getElement(vname)
    except Exception:
        return []
    return setbackfillet.corner_alternatives(base, pairs, v)


def show_alternatives(panel, button):
    """A popup of the corner's alternatives; picking one applies it to the corner."""
    alts = alternatives(panel)
    if not alts:
        try:
            Gui.getMainWindow().statusBar().showMessage(
                "Pick a face of a fillet at a corner first" if not panel.corners else "That corner has no other shape to choose", 6000)
        except Exception as _fw_err:
            _fw_log("filletxpert.py:no alternatives", _fw_err)
        return None
    menu = QtWidgets.QMenu(button)
    menu.setObjectName("SWFilletXpertAlternatives")
    for n, (label, key, shape) in enumerate(alts, 1):
        act = menu.addAction("Alternative %d: %s" % (n, label))
        act.setObjectName("SWFilletXpertAlternative%d" % n)
        act.triggered.connect(lambda checked=False, k=key: choose(panel, k))
    panel.alternatives_menu = menu
    menu.popup(button.mapToGlobal(QtCore.QPoint(0, button.height())))
    return menu


def choose(panel, key):
    """Apply alternative key ("" default, "EdgeN" first, "round") to the Corner Faces corner."""
    if not panel.corners:
        return
    name, vname = panel.corners[0]
    panel.corner_choice = (name, vname, key)
    _apply_corners(panel, [(name, vname, key)], "Fillet Corner")


def copy_to(panel):
    """Copy to: the last choice goes on every Copy Targets corner (an edge-first choice takes
    the target's edge that runs the same way)."""
    if panel.corner_choice is None or not panel.targets:
        return
    src_name, src_v, key = panel.corner_choice
    jobs = []
    direction = None
    if key.startswith("Edge"):
        try:
            from . import setbackfillet
            base = panel.doc.getObject(src_name).BaseFeature.Shape
            direction = setbackfillet._away(base.getElement(key), base.getElement(src_v))
        except Exception:
            direction = None
    for name, vname in panel.targets:
        k = key
        if direction is not None:
            try:
                from . import setbackfillet
                base, pairs = fillet_pairs(panel.doc.getObject(name))
                v = base.getElement(vname)
                radius = dict(pairs)
                best = None
                for e in setbackfillet.vertex_edges(base, v):
                    i = next((i for i, g in enumerate(base.Edges, 1) if g.isSame(e)), None)
                    if i not in radius:
                        continue
                    score = abs(setbackfillet._away(e, v).dot(direction))
                    if best is None or score > best[0]:
                        best = (score, "Edge%d" % i)
                k = best[1] if best else ""
            except Exception:
                k = ""
        jobs.append((name, vname, k))
    _apply_corners(panel, jobs, "Copy Fillet Corner")


def _to_own(f):
    ""
    from . import setbackfillet
    if setbackfillet.is_setback_fillet(f):
        return f
    doc = f.Document
    body = f.getParentGeoFeatureGroup()
    was_tip = body.Tip is f
    label = f.Label
    base, pairs = fillet_pairs(f)
    new = setbackfillet.setup_new(doc.addObject(setbackfillet.TYPE, "Fillet"))
    body.insertObject(new, f, True)
    subs = list(f.Base[1]) if f.Base else []
    new.Base = (f.Base[0] if f.Base else f.BaseFeature, subs)
    new.Radius = f.Radius.Value
    new.ItemRadii = list(getattr(f, "ItemRadii", []) or [])
    try:
        new.recompute()        # its shape, for the next feature's picks
    except Exception as _fw_err:
        _fw_log("filletxpert.py:_to_own", _fw_err)
    for child in [o for o in f.InList + new.InList if o is not new and o is not f]:
        _repoint(child, f, new)         # (the body's insert has already moved some of them to new)
        if getattr(child, "BaseFeature", None) is f:
            child.BaseFeature = new
    if was_tip:
        body.Tip = new
    body.removeObject(f)
    doc.removeObject(f.Name)
    new.Label = label
    return new


def _apply_corners(panel, jobs, text):
    ""

    from . import setbackfillet
    renamed = {}

    def work():
        for name, vname, key in jobs:
            f = panel.doc.getObject(renamed.get(name, name))
            if f is None:
                continue
            own = _to_own(f)
            renamed[name] = own.Name
            rows = [r for r in own.CornerFirst if not r.startswith(vname + setbackfillet.SEP)]
            if key:
                rows.append(vname + setbackfillet.SEP + key)
            own.CornerFirst = rows
            own.touch()
    _commit_and_reopen(panel, text, work)
    panel.corners = [(renamed.get(n, n), v) for n, v in panel.corners]
    panel.targets = [(renamed.get(n, n), v) for n, v in panel.targets]
    if panel.corner_choice is not None:
        n, v, k = panel.corner_choice
        panel.corner_choice = (renamed.get(n, n), v, k)
    _fill_corners(panel)
