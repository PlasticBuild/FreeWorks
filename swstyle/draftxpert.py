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

DRAFT = "PartDesign::Draft"


def boxes(panel):
    """The DraftXpert boxes (hidden while Manual is the tab)."""
    bar_box = filletpm._box("DraftXpert")
    bar = QtWidgets.QTabBar(bar_box)
    bar.setObjectName("SWDraftXpertTabs")
    for t in ("Add", "Change"):
        bar.addTab(t)
    bar.setExpanding(False)
    bar.blockSignals(True)
    bar.setCurrentIndex(1 if filletpm.params().GetInt("DraftXpertTab", 0) == 1 else 0)
    bar.blockSignals(False)
    bar_box.layout().addWidget(bar)
    panel.dx_bar = bar


    # Manual page's own fields move in here while Add is the tab, so picks and values are shared
    items = filletpm._box("Items to Draft")
    panel.dx_rows = []
    for name in ("angle", "plane", "faces"):
        row = QtWidgets.QWidget(items)
        row.setObjectName("SWDraftXpertRow_" + name)
        lay = QtWidgets.QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        items.layout().addWidget(row)
        panel.dx_rows.append(row)
    apply = QtWidgets.QPushButton("Apply", items)
    apply.setObjectName("SWDraftXpertApply")
    apply.clicked.connect(lambda: apply_add(panel))
    items.layout().addWidget(apply)
    panel.dx_apply = apply
    panel.dx_items = items
    panel.dx_homes = None

    # Draft Analysis: Auto paint and the colour scale
    analysis = filletpm._box("Draft Analysis")
    panel.dx_paint = QtWidgets.QCheckBox("Auto paint", analysis)
    panel.dx_paint.setObjectName("SWDraftXpertAutoPaint")
    panel.dx_paint.setChecked(filletpm.params().GetBool("DraftXpertAutoPaint", False))
    panel.dx_paint.toggled.connect(lambda on: (filletpm.params().SetBool("DraftXpertAutoPaint", on), paint(panel)))
    analysis.layout().addWidget(panel.dx_paint)
    panel.dx_scale = Scale(panel, analysis)
    analysis.layout().addWidget(panel.dx_scale)
    panel.angle.valueChanged.connect(lambda v: panel.dx_scale.update())
    panel.dx_analysis = analysis

    change = filletpm._box("Drafts to Change")
    panel.dx_change_list = filletpm._ItemsList(panel, "SWDraftXpertChange")
    panel.dx_change_list.panel = _ChangeProxy(panel)
    change.layout().addWidget(panel.dx_change_list)
    row = QtWidgets.QHBoxLayout()
    row.addWidget(QtWidgets.QLabel("Draft angle", change))
    panel.dx_angle = filletpm._spin(change, "SWDraftXpertChangeAngle", "°", 0.01, 89.99)
    panel.dx_angle.setValue(panel.angle.value())
    row.addWidget(panel.dx_angle)
    change.layout().addLayout(row)
    buttons = QtWidgets.QHBoxLayout()
    for text, name, fn in (("Change", "SWDraftXpertChangeButton", change_drafts),
                           ("Remove", "SWDraftXpertRemove", remove_drafts)):
        b = QtWidgets.QPushButton(text, change)
        b.setObjectName(name)
        b.clicked.connect(lambda checked=False, fn=fn: fn(panel))
        buttons.addWidget(b)
    change.layout().addLayout(buttons)
    existing = filletpm._box("Existing Drafts")
    panel.dx_sort = QtWidgets.QCheckBox("Sort by angle", existing)
    panel.dx_sort.setObjectName("SWDraftXpertSort")
    panel.dx_sort.toggled.connect(lambda on: fill_existing(panel))
    existing.layout().addWidget(panel.dx_sort)
    panel.dx_existing = QtWidgets.QListWidget(existing)
    panel.dx_existing.setObjectName("SWDraftXpertExisting")
    panel.dx_existing.setFixedHeight(84)
    panel.dx_existing.itemClicked.connect(lambda item: _pick_existing(panel, item))
    existing.layout().addWidget(panel.dx_existing)
    panel.dx_changing = []
    panel.dx_bar_box = bar_box
    panel.dx_change_boxes = [change, existing]
    bar.currentChanged.connect(lambda i: show(panel))
    return [bar_box, items, analysis, change, existing]


POSITIVE, REQUIRES, NEGATIVE = (0.2, 0.75, 0.25), (1.0, 0.85, 0.1), (0.9, 0.2, 0.2)


def _qcolor(rgb):
    from PySide import QtGui
    return QtGui.QColor.fromRgbF(*rgb)


class Scale(QtWidgets.QWidget):
    ""


    def __init__(self, panel, parent):
        super().__init__(parent)
        self.panel = panel
        self.setObjectName("SWDraftXpertScale")
        self.setMinimumHeight(96)

    def rows(self):
        a = filletpm._number(self.panel.angle.value())
        return [(POSITIVE, "%s°" % a, "Positive draft"), (REQUIRES, "", "Requires draft"),
                (NEGATIVE, "-%s°" % a, "Negative draft")]

    def paintEvent(self, event):
        from PySide import QtGui
        p = QtGui.QPainter(self)
        h = self.height() - 8
        bar = QtCore.QRect(4, 4, 16, h)
        grad = QtGui.QLinearGradient(0, bar.top(), 0, bar.bottom())
        grad.setColorAt(0.0, _qcolor(POSITIVE))
        grad.setColorAt(0.33, _qcolor(POSITIVE))
        grad.setColorAt(0.34, _qcolor(REQUIRES))
        grad.setColorAt(0.66, _qcolor(REQUIRES))
        grad.setColorAt(0.67, _qcolor(NEGATIVE))
        grad.setColorAt(1.0, _qcolor(NEGATIVE))
        p.fillRect(bar, grad)
        p.setPen(self.palette().color(QtGui.QPalette.WindowText))
        p.drawRect(bar)
        for i, (_, value, text) in enumerate(self.rows()):
            y = bar.top() + int(h * (i + 0.5) / 3.0)
            if value:
                edge = bar.top() + int(h * (1 if i == 0 else 2) / 3.0)
                p.drawLine(bar.right(), edge, bar.right() + 5, edge)
                p.drawText(bar.right() + 8, edge + 4, value)
            p.drawText(bar.right() + 52, y + 4, text)
        p.end()


def _pull(panel):
    """The direction of pull: the neutral plane's normal (Reverse turns it)."""
    shape = panel._plane_shape()
    if shape is None:
        return None
    try:
        if panel.plane[1].startswith("Face"):
            u0, u1, v0, v1 = shape.ParameterRange
            n = shape.normalAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
        else:
            n = panel.plane[0].Placement.Rotation.multVec(App.Vector(0, 0, 1))
    except Exception:
        return None
    if panel.reverse.isChecked():
        n = n.negative()
    return n


def face_draft(face, pull, samples=3):
    """(lowest, highest) draft angle in degrees over the face, against the pull direction."""
    import math
    u0, u1, v0, v1 = face.ParameterRange
    angles = []
    for i in range(samples):
        for j in range(samples):
            u = u0 + (u1 - u0) * (i + 0.5) / samples
            v = v0 + (v1 - v0) * (j + 0.5) / samples
            try:
                if not face.isPartOfDomain(u, v):
                    continue
                n = face.normalAt(u, v)
            except Exception:
                continue
            c = max(-1.0, min(1.0, n.dot(pull) / max(n.Length * pull.Length, 1e-12)))
            angles.append(math.degrees(math.asin(c)))
    if not angles:
        return None
    return min(angles), max(angles)


def colour_of(lowest, highest, angle):
    tol = 1e-4
    if lowest >= angle - tol:
        return POSITIVE
    if highest <= -angle + tol:
        return NEGATIVE
    return REQUIRES


def paint(panel):
    """Auto paint: every face of the part in its Draft Analysis colour, live, while Add is the tab."""
    overlay = getattr(panel, "overlay", None)
    if overlay is None:
        return
    painted = []
    if mode(panel) == "add" and panel.dx_paint.isChecked():
        pull = _pull(panel)
        f = panel.feature
        shape = f.Shape if (f is not None and panel.ok and not f.Shape.isNull()) else \
            (panel.base.Shape if panel.base is not None else None)
        if pull is not None and shape is not None:
            angle = panel.angle.value()
            for face in shape.Faces:
                span = face_draft(face, pull)
                if span is not None:
                    painted.append((face, colour_of(span[0], span[1], angle)))
    overlay.show_paint(painted)


def _find(layout, widget):
    """(layout, index) of the widget in the layout or one of its sub-layouts."""
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item.widget() is widget:
            return layout, i
        if item.layout() is not None:
            hit = _find(item.layout(), widget)
            if hit is not None:
                return hit
    return None


def _regroup(panel, add):
    """Add: the angle, neutral plane and faces fields move into Items to Draft; back otherwise."""
    moving = [(panel.angle, 0), (panel.reverse, 1), (panel.plane_list, 1), (panel.list, 2)]
    if add and panel.dx_homes is None:
        homes = []
        for w, _ in moving:
            parent = w.parentWidget()
            hit = _find(parent.layout(), w) if parent is not None and parent.layout() is not None else None
            if hit is None:
                return
            homes.append((w,) + hit)
        panel.dx_homes = homes
        for w, row in moving:
            panel.dx_rows[row].layout().addWidget(w)
    elif not add and panel.dx_homes is not None:
        for w, lay, index in sorted(panel.dx_homes, key=lambda h: h[2]):
            lay.insertWidget(index, w)
        panel.dx_homes = None


class _ChangeProxy:
    def __init__(self, panel):
        self.panel = panel

    def clear_items(self):
        self.panel.dx_changing = []
        _fill_change(self.panel)

    def remove_item(self, row):
        if 0 <= row < len(self.panel.dx_changing):
            del self.panel.dx_changing[row]
            _fill_change(self.panel)


def on(panel):
    return getattr(panel, "draft_tabs", None) is not None and panel.draft_tabs.currentIndex() == 1


def mode(panel):
    if not on(panel):
        return "manual"
    return "add" if panel.dx_bar.currentIndex() == 0 else "change"


def show(panel):
    """The boxes for the tab: Manual (all its own), DraftXpert Add (angle, neutral plane, faces,
    Apply) or Change (drafts to change, existing drafts)."""
    m = mode(panel)
    params = filletpm.params()
    params.SetInt("DraftTab", 0 if m == "manual" else 1)
    if m != "manual":
        params.SetInt("DraftXpertTab", 0 if m == "add" else 1)
    for r in panel.type_radios:
        r.setVisible(m == "manual")
    if getattr(panel, "kind_box", None) is not None:
        # the tabs are no longer in Type of Draft: on DraftXpert the box would be an empty title
        filletpm.box_visible(panel.kind_box, m == "manual")
    if getattr(panel, "reduced", None) is not None and m != "manual":
        panel.reduced.setVisible(False)
    filletpm.box_visible(panel.dx_bar_box, m != "manual")
    for w in panel.dx_change_boxes:
        filletpm.box_visible(w, m == "change")
    if m != "manual" and panel.parting():
        panel.type_radios[0].setChecked(True)      # DraftXpert makes neutral plane drafts
    _regroup(panel, m == "add")
    filletpm.box_visible(panel.dx_items, m == "add")
    filletpm.box_visible(panel.dx_analysis, m == "add")
    manual_neutral = m == "manual" and not panel.parting()
    filletpm.box_visible(panel.angle_box, m == "manual")
    for w in panel.neutral_boxes:
        filletpm.box_visible(w, manual_neutral)
    for w in panel.parting_boxes:
        filletpm.box_visible(w, m == "manual" and panel.parting())
    if m == "change":
        panel.items = []
        panel.update()
        _show_tip(panel)
        fill_existing(panel)
        _fill_change(panel)
    else:
        panel._show_base()
        panel.update()


def _show_tip(panel):
    try:
        tip = panel.body.Tip
        for f in filletpm._features(panel.body):
            f.ViewObject.Visibility = f is tip
    except Exception as _fw_err:
        _fw_log("draftxpert.py:329", _fw_err)


def _drafts(panel):
    return [f for f in filletpm._features(panel.body) if f.TypeId == DRAFT and f is not panel.feature]


def _same_surface(a, b):
    """True when two faces lie on the same plane (others: same area and centre)."""
    try:
        if a.Surface.__class__.__name__ == "Plane" and b.Surface.__class__.__name__ == "Plane":
            na, nb = a.normalAt(0, 0), b.normalAt(0, 0)
            return na.getAngle(nb) < 1e-6 and abs((a.Vertexes[0].Point - b.Vertexes[0].Point).dot(na)) < 1e-6
        return abs(a.Area - b.Area) < 1e-6 and (a.CenterOfMass - b.CenterOfMass).Length < 1e-6
    except Exception:
        return False


def turned_faces(f):
    """The faces a draft turned: on a surface its base did not have (a face it only trimmed,
    next to a turned one, stays on its old plane and is not one)."""
    base = f.BaseFeature.Shape if f.BaseFeature is not None else None
    if base is None:
        return []
    return [g for g in f.Shape.Faces if not any(_same_surface(g, b) for b in base.Faces)]


def draft_of_face(panel, obj, sub):
    """The Draft feature that turned the picked face, else None."""
    try:
        face = obj.Shape.getElement(sub)
    except Exception:
        return None
    for f in reversed(_drafts(panel)):
        try:
            if any(_same_surface(face, g) for g in turned_faces(f)):
                return f
        except Exception:
            continue
    return None


def picked(panel, obj, sub):
    """A pick while Change is the tab: the draft that turned the picked face."""
    if mode(panel) != "change":
        return False
    from . import refplane
    obj, sub = refplane.resolve(obj, sub or "")
    feature = None
    if obj.TypeId == DRAFT and not sub:
        feature = obj
    elif sub.startswith("Face"):
        feature = draft_of_face(panel, obj, sub)
    if feature is not None:
        if feature in panel.dx_changing:
            panel.dx_changing.remove(feature)
        else:
            panel.dx_changing.append(feature)
            panel.dx_angle.setValue(feature.Angle.Value)
        _fill_change(panel)
    return True


def _fill_change(panel):
    panel.dx_change_list.clear()
    for f in panel.dx_changing:
        panel.dx_change_list.addItem("%s (%s°)" % (f.Label, filletpm._number(f.Angle.Value)))
    edges = []
    for f in panel.dx_changing:
        try:
            edges += [e for face in turned_faces(f) for e in face.Edges]
        except Exception as _fw_err:
            _fw_log("draftxpert.py:401", _fw_err)
    panel.overlay.show_picks(edges)
    panel.overlay.show_preview([])


def fill_existing(panel):
    drafts = _drafts(panel)
    if panel.dx_sort.isChecked():
        drafts.sort(key=lambda f: f.Angle.Value)
    panel.dx_existing.clear()
    for f in drafts:
        item = QtWidgets.QListWidgetItem("%s°  %s" % (filletpm._number(f.Angle.Value), f.Label))
        item.setData(QtCore.Qt.UserRole, f.Name)
        panel.dx_existing.addItem(item)


def _pick_existing(panel, item):
    f = panel.doc.getObject(item.data(QtCore.Qt.UserRole))
    if f is not None:
        picked(panel, f, "")


def apply_add(panel):
    """Apply (Add): keep this draft as its own Undo step and start the next one."""
    if not panel.items or not panel.ok:
        return
    panel.remember()
    panel.doc.commitTransaction()
    try:
        panel.feature.ViewObject.Visibility = True
    except Exception as _fw_err:
        _fw_log("draftxpert.py:432", _fw_err)
    plane = panel.plane
    panel.feature = None
    panel.items = []
    panel.base = panel.body.Tip
    panel.before_tip = panel.body.Tip
    if plane is not None and plane[1]:
        # the neutral face, named on the new tip (the draft may have renumbered it)
        name = filletpm.to_base(panel.base, plane[0], plane[1])
        panel.plane = (panel.base, name) if name else None
    panel.active = "items" if panel.plane is not None else "plane"
    panel.doc.openTransaction("Draft")
    panel._show_base()
    panel.update()


def _commit_and_reopen(panel, text, work):
    panel.doc.commitTransaction()
    panel.doc.openTransaction(text)
    try:
        work()
        panel.doc.recompute()
        panel.doc.commitTransaction()
    except Exception as error:
        panel.doc.abortTransaction()
        App.Console.PrintError("FreeCAD: DraftXpert: %s\n" % error)
    panel.doc.openTransaction("Draft")
    panel.dx_changing = []
    panel.base = panel.body.Tip
    panel.before_tip = panel.body.Tip
    _show_tip(panel)
    fill_existing(panel)
    _fill_change(panel)


def change_drafts(panel):
    if not panel.dx_changing:
        return
    value = panel.dx_angle.value()
    targets = list(panel.dx_changing)

    def work():
        for f in targets:
            f.Angle = value
    _commit_and_reopen(panel, "Change Drafts", work)


def remove_drafts(panel):
    if not panel.dx_changing:
        return
    targets = list(panel.dx_changing)

    def work():
        from . import filletxpert
        for f in targets:
            filletxpert.delete_fillet(f)
    _commit_and_reopen(panel, "Remove Drafts", work)
