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
from PySide import QtCore, QtGui, QtWidgets

from . import extrudepm, pmboxes
from . import pmfields

DONE = "freeworks_sweeploftpm"
PIPES = ("PartDesign::AdditivePipe", "PartDesign::SubtractivePipe")
LOFTS = ("PartDesign::AdditiveLoft", "PartDesign::SubtractiveLoft")
PINK = "#ffd6e7"
BLUE = "#cfe3ff"
WHITE = "#ffffff"

_alive = extrudepm._alive


def _box_style(box, colour):
    ""
    pmboxes.mark(box, colour == BLUE, need=(colour == PINK))


def _set_items(box, names):
    if [box.item(i).text() for i in range(box.count())] != names:
        box.clear()
        for n in names:
            box.addItem(n)


def _press(button, on=True):
    """Put FreeCAD's selection button in the state wanted (it toggles on click)."""
    if button is not None and _alive(button) and button.isCheckable() and button.isChecked() != on:
        button.click()


def _hide_row(widget):
    """Hide widget and the label/buttons on its row."""
    if widget is None:
        return
    widget.hide()
    lay, index = extrudepm._grid_of(widget)
    if isinstance(lay, QtWidgets.QFormLayout):
        label = lay.labelForField(widget)
        if label is not None:
            label.hide()
    if isinstance(lay, QtWidgets.QBoxLayout):
        for i in range(lay.count()):
            w = pmfields.sub_widget(lay, i)
            if w is not None:
                w.hide()


def _hide_empty_groups(widgets):
    """A group box left with nothing showing goes too (FreeCAD's "Profile" frame)."""
    for w in widgets:
        if w is None or not _alive(w):
            continue
        g = w.parentWidget()
        while g is not None and not isinstance(g, QtWidgets.QGroupBox):
            g = g.parentWidget()
        if g is None or g.isHidden():
            continue
        if not any(not c.isHidden() for c in g.findChildren(QtWidgets.QWidget) if c.parentWidget() is g):
            g.hide()


def _title(parent, text):
    label = QtWidgets.QLabel(text, parent)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    return label


def _list(parent, name, rows, tip):
    box = QtWidgets.QListWidget(parent)
    box.setObjectName(name)
    box.setFixedHeight(8 + 18 * rows)
    box.setToolTip(tip)
    return box


def _form(panel, name):
    top = panel
    while top.parentWidget() is not None and not top.inherits("QSint::ActionGroup"):
        top = top.parentWidget()
    top = top.parentWidget() or top
    return top.findChild(QtWidgets.QWidget, name)


def _retitle(widget, old, new):
    """Rename the QSint box header holding widget."""
    group = widget
    while group is not None and not group.inherits("QSint::ActionGroup"):
        group = group.parentWidget()
    if group is None:
        return False
    for header in group.findChildren(QtWidgets.QWidget):
        if header.inherits("QSint::TaskHeader"):
            for l in header.findChildren(QtWidgets.QWidget):
                if hasattr(l, "text") and callable(l.text) and l.text() == old:
                    l.setText(new)
                    return True
    return False


def _hide_group(widget):
    group = widget
    while group is not None and not group.inherits("QSint::ActionGroup"):
        group = group.parentWidget()
    if group is not None:
        group.hide()


def _combo(parent, name, items, tip=""):
    c = QtWidgets.QComboBox(parent)
    c.setObjectName(name)
    c.addItems(items)

    c.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
    c.setMinimumContentsLength(12)
    c.setToolTip(tip)
    return c


class _Click(QtCore.QObject):
    def __init__(self, box, then):
        super().__init__(box)
        self.then = then
        box.viewport().installEventFilter(self)

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() == QtCore.QEvent.MouseButtonPress:
            try:
                try:
                    self.then(event)
                except TypeError:
                    self.then()
            except Exception as _fw_err:
                _fw_log("sweeploftpm.py:177", _fw_err)
        return False


# --------------------------------------------------------------------------- Sweep
class SweepBoxes(QtCore.QObject):
    def __init__(self, view, panel, feature):
        super().__init__(panel)
        self.view, self.panel, self.feature = view, panel, feature
        self.profile_button = panel.findChild(QtWidgets.QAbstractButton, "buttonProfileBase")
        self.path_button = panel.findChild(QtWidgets.QAbstractButton, "buttonSpineBase")
        self.profile_edit = panel.findChild(QtWidgets.QLineEdit, "profileBaseEdit")
        self.path_edit = panel.findChild(QtWidgets.QLineEdit, "spineBaseEdit")
        lay = panel.layout()
        self.title = _title(panel, "Profile and Path")
        self.profile = _list(panel, "SWStyle_SweepProfile", 1, "Profile: click the sketch to sweep")
        self.path = _list(panel, "SWStyle_SweepPath", 1, "Path: click the path sketch or edge")
        for i, w in enumerate((self.title, self.profile, self.path)):
            lay.insertWidget(i, w)
        _Click(self.profile, lambda: self.activate("profile"))
        _Click(self.path, lambda: self.activate("path"))
        pmboxes.bind(self.profile, lambda row: self.take_out("profile"), lambda: self.take_out("profile"))
        pmboxes.bind(self.path, lambda row: self.take_out("path"), lambda: self.take_out("path"))
        for w in (self.profile_edit, self.path_edit):
            _hide_row(w)
        for name in ("buttonRefAdd", "buttonRefRemove", "listWidgetReferences"):
            w = panel.findChild(QtWidgets.QWidget, name)
            if w is not None:
                w.hide()
        _hide_empty_groups([self.profile_edit, self.path_edit, self.profile_button, self.path_button,
                            panel.findChild(QtWidgets.QWidget, "listWidgetReferences")])
        if _retitle(panel, "Pipe Parameters", "Profile and Path"):
            self.title.hide()
        _hide_row(panel.findChild(QtWidgets.QComboBox, "comboBoxTransition"))
        self.options = self.guides = None
        try:
            self.options = SweepOptions(view, panel, feature)
            self.guides = GuideCurves(view, panel, feature, self)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: sweep boxes: %s\n" % error)
        self.active = None
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.sync)
        self.timer.start(150)
        QtCore.QTimer.singleShot(0, self.first)
        QtCore.QTimer.singleShot(400, self._kick)

    def _kick(self):
        if not _alive(self.panel) or self.active is None:
            return
        button = self.profile_button if self.active == "profile" else self.path_button
        _press(button, False)
        _press(button, True)

    def first(self):
        if not self._text(self.profile_edit):
            self.activate("profile")
        elif not self._text(self.path_edit):
            self.activate("path")
        self.sync()

    def _text(self, edit):
        return edit.text().strip() if edit is not None and _alive(edit) else ""

    def take_out(self, which):
        """Delete / Clear Selections: the profile or the path goes and its box takes the next pick."""
        try:
            if which == "profile":
                self.feature.Profile = None
            else:
                self.feature.Spine = None
            self.feature.Document.recompute()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: sweep box: %s\n" % error)

        edit = self.profile_edit if which == "profile" else self.path_edit
        if edit is not None and _alive(edit):
            edit.clear()
        self.activate(which)

    def activate(self, which):
        self.active = which
        if self.guides is not None:
            self.guides.active = False
        _press(self.profile_button, which == "profile")
        _press(self.path_button, which == "path")
        self.sync()

    def sync(self):
        if not _alive(self.panel) or not _alive(self.profile):
            self.timer.stop()
            return
        prof, path = self._text(self.profile_edit), self._text(self.path_edit)

        prof = _link_text(getattr(self.feature, "Profile", None)) or prof
        path = _group_text(getattr(self.feature, "Spine", None)) or _link_text(getattr(self.feature, "Spine", None)) or path
        _set_items(self.profile, [prof] if prof else [])
        _set_items(self.path, [path] if path else [])
        # FreeCAD lets go of its button after one pick: the next empty box takes over
        if self.active == "profile" and prof and not self.profile_button.isChecked():
            if not path:
                self.activate("path")
                return
            self.active = None
        elif self.active == "path" and path and not self.path_button.isChecked():
            self.active = None
        for box, which, value in ((self.profile, "profile", prof), (self.path, "path", path)):
            # active and still needed: blue and needed both (pmboxes gates OK on the need)
            pmboxes.mark(box, self.active == which, need=not value)
        extrudepm._hide_native_extras(self.view)


def _group_text(link):
    ""

    try:
        if not link or link[0] is None:
            return ""
        subs = [x for x in (link[1] or ()) if x]
        if len(subs) < 2:
            return ""
        from . import simplefeature
        rows = simplefeature.group_rows([(link[0], subs)])
        return rows[0][0] if len(rows) == 1 and rows[0][0].endswith(">") else ""
    except Exception:
        return ""


def _link_text(link):
    """'Label: Edge4, Edge7' for a link with sub-elements, else '' (the native text stands)."""
    try:
        if not link:
            return ""
        obj, subs = link[0], [x for x in (link[1] or ()) if x]
        if obj is None or not subs:
            return ""
        return "%s: %s" % (obj.Label, ", ".join(subs))
    except Exception:
        return ""


ORIENTATIONS = ("Follow Path", "Keep normal constant")
TWISTS = ("None", "Natural", "Specify direction vector")
# FreeCAD Mode for (orientation, twist)
MODE = {("Follow Path", "None"): 0, ("Follow Path", "Natural"): 2, ("Follow Path", "Specify direction vector"): 4,
        ("Keep normal constant", "None"): 1}
AUXILIARY = 3


class SweepOptions(QtCore.QObject):
    ""

    def __init__(self, view, panel, feature):
        super().__init__(panel)
        self.view, self.feature = view, feature
        form = _form(panel, "PartDesignGui__TaskPipeOrientation")
        self.form = form
        self.mode = form.findChild(QtWidgets.QComboBox, "comboBoxMode")
        self.stack = form.findChild(QtWidgets.QStackedWidget, "stackedWidget")
        _retitle(form, "Section Orientation", "Options")
        label = form.findChild(QtWidgets.QLabel, "label_2")
        if label is not None:
            label.setText("Profile orientation:")
        self.orientation = _combo(form, "SWStyle_ProfileOrientation", ORIENTATIONS,
                                  "Follow Path: the profile stays square to the path. "
                                  "Keep normal constant: the profile keeps its own plane.")
        self.twist_label = QtWidgets.QLabel("Profile twist:", form)
        self.twist_label.setObjectName("SWStyle_ProfileTwistLabel")
        self.twist = _combo(form, "SWStyle_ProfileTwist", TWISTS,
                            "None: no twist along the path. Natural: the profile turns with the path's curvature. "
                            "Specify direction vector: the profile keeps the vector below as its up direction.")
        lay, index = extrudepm._grid_of(self.mode)
        out = form.layout()
        stacked = False
        if label is not None and isinstance(lay, QtWidgets.QBoxLayout) and isinstance(out, QtWidgets.QBoxLayout) \
                and lay is not out and lay.indexOf(label) >= 0:

            lay.removeWidget(label)
            top = max(0, out.indexOf(lay)) if out.indexOf(lay) >= 0 else 0
            out.insertWidget(top, label)
            out.insertWidget(top + 1, self.orientation)
            stacked = True
        if not stacked and isinstance(lay, QtWidgets.QBoxLayout):
            lay.insertWidget(index + 1, self.orientation)
        self.mode.hide()
        pos = out.indexOf(self.stack) if out is not None else -1
        if out is not None and pos >= 0:
            out.insertWidget(pos, self.twist_label)
            out.insertWidget(pos + 1, self.twist)
        for name in ("curvilinear", "groupBox"):   # FreeCAD's Auxiliary page: the Guide Curves box does this
            w = form.findChild(QtWidgets.QWidget, name)
            if w is not None:
                w.hide()
        hint = form.findChild(QtWidgets.QLabel, "label_5")
        if hint is not None:
            hint.setText("Direction vector:")
        self._read()
        self.orientation.currentIndexChanged.connect(self.changed)
        self.twist.currentIndexChanged.connect(self.changed)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(150)

    def _read(self):
        i = self.mode.currentIndex()
        for (o, t), m in MODE.items():
            if m == i:
                self.orientation.setCurrentIndex(ORIENTATIONS.index(o))
                self.twist.setCurrentIndex(TWISTS.index(t))

    def wanted(self):
        o = self.orientation.currentText()
        t = self.twist.currentText() if o == "Follow Path" else "None"
        return MODE[(o, t)]

    def changed(self, *args):
        if not _alive(self.form):
            return
        follow = self.orientation.currentText() == "Follow Path"
        self.twist_label.setVisible(follow)
        self.twist.setVisible(follow)
        if self.mode.currentIndex() != AUXILIARY and self.mode.currentIndex() != self.wanted():
            self.mode.setCurrentIndex(self.wanted())
        self._tick()

    def _tick(self):
        if not _alive(self.form):
            self.timer.stop()
            return
        page = self.stack.currentWidget()
        vector = page is not None and page.objectName() == "binormal"
        if self.stack.isVisible() != vector:
            self.stack.setVisible(vector)


def _links_set(f, prop):
    try:
        v = getattr(f, prop)
        return bool(v) and v[0] is not None
    except Exception:
        return False


class GuideCurves(QtCore.QObject):
    ""


    def __init__(self, view, panel, feature, boxes):
        super().__init__(panel)
        self.view, self.feature, self.boxes = view, feature, boxes
        form = _form(panel, "PartDesignGui__TaskPipeScaling")
        self.form = form
        _retitle(form, "Section Transformation", "Guide Curves")
        for name in ("label_2", "comboBoxScaling", "stackedWidget"):   # FreeCAD-only Transform mode
            w = form.findChild(QtWidgets.QWidget, name)
            if w is not None:
                w.hide()
        self.box = _list(form, "SWStyle_SweepGuides", 2, "Guide curves: click a sketch or edge the profile follows; "
                                                         "click it in the list to take it out")
        form.layout().insertWidget(0, self.box)
        form.layout().addStretch(1)
        self.box.setStyleSheet("")
        pmboxes.bind(self.box, lambda row: self._set(None), lambda: self._set(None))
        _Click(self.box, self._clicked)
        self.active = False
        self.sync()
        Gui.Selection.addObserver(self)
        self.view.destroyed.connect(self.stop)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.sync)
        self.timer.start(200)

    def stop(self, *args):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("sweeploftpm.py:453", _fw_err)
        try:
            self.timer.stop()
        except Exception as _fw_err:
            _fw_log("sweeploftpm.py:457", _fw_err)

    def _clicked(self, event):
        pos = event.pos() if hasattr(event, "pos") else self.box.viewport().mapFromGlobal(QtGui.QCursor.pos())
        item = self.box.itemAt(pos.toPoint() if hasattr(pos, "toPoint") else pos)
        if item is not None:
            self._set(None)
            return
        self.activate(not self.active)

    def activate(self, on):
        self.active = on
        if on:
            self.boxes.active = None
            _press(self.boxes.profile_button, False)
            _press(self.boxes.path_button, False)
        self.sync()

    def _next_pick(self, obj, sub=""):
        ""

        f = self.feature
        if self.boxes.active is not None or not _links_set(f, "Profile") or not _links_set(f, "Spine"):
            return False
        if _links_set(f, "AuxiliarySpine"):
            return False
        try:
            taken = {f.Profile[0].Name, f.Spine[0].Name}
        except Exception:
            taken = set()
        curve = (sub or "").startswith("Edge") or (not sub and obj.isDerivedFrom("Part::Part2DObject"))
        return curve and obj.Name not in taken

    def _open_group(self):
        """Unfold the Guide Curves group so its box shows the pick."""
        try:
            from . import pmlayout
            w = self.box
            while w is not None and not w.inherits("QSint::ActionGroup"):
                w = w.parentWidget()
            if w is not None and not pmlayout._group_open(w):
                pmlayout._show_hide(w)
        except Exception as _fw_err:
            _fw_log("sweeploftpm.py:guide-open", _fw_err)

    def addSelection(self, doc, name, sub, pnt):
        if not _alive(self.form):
            return
        d = App.getDocument(doc)
        obj = d.getObject(name) if d else None
        if obj is None or obj is self.feature:
            return
        if not self.active:
            if not self._next_pick(obj, sub):
                return
            self._open_group()
        self._set((obj, [sub] if sub else []))
        self.active = False
        QtCore.QTimer.singleShot(0, lambda: Gui.Selection.clearSelection())

    def _set(self, link):
        f = self.feature
        mode = self.boxes.options.mode if self.boxes.options else None
        try:
            if link is None:
                f.AuxiliarySpine = None
                want = self.boxes.options.wanted() if self.boxes.options else 0
            else:
                f.AuxiliarySpine = link
                want = AUXILIARY



                try:
                    from . import loftsweep
                    if f.TypeId in ("PartDesign::AdditivePipe", "PartDesign::SubtractivePipe") and _links_set(f, "Spine"):
                        loftsweep._later(f)
                        return
                except Exception as error:
                    App.Console.PrintLog("FreeCAD: guide curve to Sweep: %s\n" % error)
            if mode is not None and mode.currentIndex() != want:
                mode.setCurrentIndex(want)     # FreeCAD sets Mode and recomputes
            else:
                f.Mode = want
                f.Document.recompute()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: guide curve: %s\n" % error)
        self.sync()

    def names(self):
        try:
            link = self.feature.AuxiliarySpine
        except Exception:
            link = None
        if not link or link[0] is None:
            return []
        obj, subs = link
        return [obj.Label + (":" + subs[0] if subs and subs[0] else "")]

    def sync(self):
        if not _alive(self.form) or not _alive(self.box):
            self.stop()
            return
        _set_items(self.box, self.names())
        _box_style(self.box, BLUE if self.active else WHITE)


# --------------------------------------------------------------------------- Loft
class LoftBoxes(QtCore.QObject):
    def __init__(self, view, panel, feature):
        super().__init__(panel)
        self.view, self.panel, self.feature = view, panel, feature
        self.base_button = panel.findChild(QtWidgets.QAbstractButton, "buttonProfileBase")
        self.add_button = panel.findChild(QtWidgets.QAbstractButton, "buttonRefAdd")
        self.remove_button = panel.findChild(QtWidgets.QAbstractButton, "buttonRefRemove")
        self.base_edit = panel.findChild(QtWidgets.QLineEdit, "profileBaseEdit")
        self.sections = panel.findChild(QtWidgets.QListWidget, "listWidgetReferences")
        lay = panel.layout()
        self.title = _title(panel, "Profiles")
        self.profiles = _list(panel, "SWStyle_LoftProfiles", 4, "Profiles: click each sketch in order; click one again to take it out")
        lay.insertWidget(0, self.title)
        lay.insertWidget(1, self.profiles)

        self.order_row = QtWidgets.QWidget(panel)
        row = QtWidgets.QHBoxLayout(self.order_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.up = QtWidgets.QPushButton("Move Up", self.order_row)
        self.up.setObjectName("SWStyle_LoftMoveUp")
        self.down = QtWidgets.QPushButton("Move Down", self.order_row)
        self.down.setObjectName("SWStyle_LoftMoveDown")
        for b_, step in ((self.up, -1), (self.down, 1)):
            b_.setToolTip("%s the profile picked in the box" % b_.text())
            b_.clicked.connect(lambda checked=False, k=step: self.move(k))
            row.addWidget(b_)
        row.addStretch(1)
        lay.insertWidget(2, self.order_row)
        _Click(self.profiles, lambda: self.activate(True))
        pmboxes.bind(self.profiles, self.take_out, self.clear_items)
        _hide_row(self.base_edit)
        for w in (self.add_button, self.remove_button, self.sections):
            if w is not None:
                w.hide()
        _hide_empty_groups([self.base_edit, self.base_button, self.sections, self.add_button])
        if _retitle(panel, "Loft Parameters", "Profiles"):
            self.title.hide()
        try:
            _loft_options(panel)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: loft options: %s\n" % error)
        self.active = True
        self.removing = False
        self.known = set()
        Gui.Selection.addObserver(self)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.sync)
        self.timer.start(150)
        panel.destroyed.connect(self.stop)
        QtCore.QTimer.singleShot(0, self.sync)
        # FreeCAD resets its selection mode while the panel finishes opening: press again after
        QtCore.QTimer.singleShot(400, self._kick)

    def _kick(self):
        if not _alive(self.panel) or not self.active:
            return
        button = self.base_button if self.base_edit is not None and not self.base_edit.text().strip() else self.add_button
        _press(button, False)
        _press(button, True)

    def stop(self, *args):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("sweeploftpm.py:584", _fw_err)
        try:
            self.timer.stop()
        except Exception as _fw_err:
            _fw_log("sweeploftpm.py:588", _fw_err)

    def _order(self):
        """[(object, subs)]: the profile, then the sections, as the feature has them."""
        out = []
        prof = getattr(self.feature, "Profile", None)
        if prof and prof[0] is not None:
            out.append((prof[0], list(prof[1]) if len(prof) > 1 else []))
        for x in (self.feature.Sections or []):
            out.append((x[0], list(x[1])) if isinstance(x, (list, tuple)) else (x, []))
        return out

    def move(self, step):
        """Move Up / Move Down: the picked profile changes places with its neighbour (the first one is
        the loft's Profile, the rest its Sections)."""
        try:
            row = self.profiles.currentRow()
            order = self._order()
            if row < 0 or len(order) != self.profiles.count():
                return
            to = row + step
            if not (0 <= to < len(order)):
                return
            order[row], order[to] = order[to], order[row]
            f = self.feature
            # inside the page's own transaction: Cancel puts the order back with everything else
            f.Profile = (order[0][0], [x for x in order[0][1] if x])
            # a whole sketch is (sketch, [""]): (sketch, []) drops the section altogether
            f.Sections = [(o, [x for x in subs if x] or [""]) for o, subs in order[1:]]
            if self.base_edit is not None and _alive(self.base_edit):
                self.base_edit.setText(order[0][0].Label)
            f.Document.recompute()
            self.reordered = True
            self.sync()
            self.profiles.setCurrentRow(to)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: loft profile order: %s\n" % error)

    def names(self):
        if getattr(self, "reordered", False):
            # FreeCAD's own (hidden) list keeps the order it was picked in: the feature has the real one
            return [o.Label for o, _subs in self._order()]
        out = []
        if self.base_edit is not None and _alive(self.base_edit) and self.base_edit.text().strip():
            out.append(self.base_edit.text().strip())
        if self.sections is not None and _alive(self.sections):
            out += [self.sections.item(i).text() for i in range(self.sections.count())]
        return out

    def activate(self, on):
        self.active = on
        self.sync()

    def addSelection(self, doc, name, sub, pnt):
        ""
        if not self.active or self.removing or not _alive(self.panel):
            return
        obj = App.getDocument(doc).getObject(name) if doc in App.listDocuments() else None
        if obj is None:
            return
        # FreeCAD may already have added it by now: judge by the list as it was before the click
        if obj.Name in self.known:
            self.removing = True
            QtCore.QTimer.singleShot(0, lambda: self._remove(doc, name, sub))
            return
        if obj.TypeId == "Sketcher::SketchObject" and pnt is not None and any(pnt):

            QtCore.QTimer.singleShot(250, lambda o=obj, p=App.Vector(*pnt): connector_at_click(o, p))

    def take_out(self, row):
        """Delete: profile row goes (row 0 is the first profile, the rest the sections, through
        FreeCAD's own Remove so its list follows)."""
        try:
            has_base = self.base_edit is not None and bool(self.base_edit.text().strip())
            if row == 0 and has_base:
                self.feature.Profile = None
                self.base_edit.setText("")
                self.feature.Document.recompute()
                self.activate(True)
                return
            k = row - (1 if has_base else 0)
            sections = [x[0] if isinstance(x, (list, tuple)) else x for x in (self.feature.Sections or [])]
            if 0 <= k < len(sections) and not self.removing:
                obj = sections[k]
                self.removing = True
                self._remove(obj.Document.Name, obj.Name, "")
        except Exception as error:
            App.Console.PrintLog("FreeCAD: loft box: %s\n" % error)
        self.sync()

    def clear_items(self):
        """Clear Selections: the sections go one by one (FreeCAD removes one per pick), then the profile."""
        try:
            if self.feature.Sections and not self.removing:
                self.take_out(1 if (self.base_edit is not None and self.base_edit.text().strip()) else 0)
                QtCore.QTimer.singleShot(350, self.clear_items)
                return
            self.feature.Profile = None
            if self.base_edit is not None:
                self.base_edit.setText("")
            self.feature.Document.recompute()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: loft box: %s\n" % error)
        self.activate(True)

    def _remove(self, doc, name, sub):
        try:
            _press(self.add_button, False)
            Gui.Selection.clearSelection()
            _press(self.remove_button, True)
            Gui.Selection.addSelection(doc, name, sub)
        finally:
            QtCore.QTimer.singleShot(200, self._removed)

    def _removed(self):
        self.removing = False
        _press(self.remove_button, False)
        self.sync()

    def sync(self):
        if not _alive(self.panel) or not _alive(self.profiles):
            self.stop()
            return
        _set_items(self.profiles, self.names())
        try:
            self.known = {(x[0] if isinstance(x, (list, tuple)) else x).Name for x in self.feature.Sections}
        except Exception:
            self.known = set()
        if self.active and not self.removing:
            if self.base_edit is not None and not self.base_edit.text().strip():
                _press(self.base_button, True)
            else:
                # FreeCAD lets go of Add Section after each pick: keep it pressed
                _press(self.add_button, True)
        pmboxes.mark(self.profiles, bool(self.active), need=len(self.names()) < 2)
        extrudepm._hide_native_extras(self.view)


def connector_at_click(sketch, point):
    """The loft profile's start (its connector) moves to the sketch vertex nearest point (global).
    A profile with no corners (a circle) keeps its own. True when the sketch changed."""
    try:
        shape = sketch.Shape
        if shape.isNull() or len(shape.Wires) != 1 or len(shape.Vertexes) < 2:
            return False
        vertex = min(shape.Vertexes, key=lambda v: (v.Point - point).Length)
        from . import pmhandles
        return bool(pmhandles.rotate_wire_start(sketch, vertex.Point))
    except Exception as error:
        App.Console.PrintLog("FreeCAD: loft connector at the click: %s\n" % error)
        return False


def _loft_options(panel):
    ""
    ruled = panel.findChild(QtWidgets.QCheckBox, "checkBoxRuled")
    closed = panel.findChild(QtWidgets.QCheckBox, "checkBoxClosed")
    merge = panel.findChild(QtWidgets.QCheckBox, "SWStyle_MergeResult")
    lay = panel.layout()
    if closed is None or ruled is None:
        return
    closed.setText("Close loft")
    closed.setToolTip("Join the last profile back to the first")
    ruled.setToolTip("Straight sides between the profiles instead of a smooth surface")
    title = _title(panel, "Options")
    title.setObjectName("SWStyle_LoftOptionsTitle")
    line = panel.findChild(QtWidgets.QFrame, "line")
    if line is not None:
        line.hide()
    for w in (closed, ruled, merge):
        if w is not None:
            lay.removeWidget(w)
    for w in (title, closed, ruled, merge):
        if w is not None:
            lay.addWidget(w)
            w.show()
    extrudepm.section_header(title)
    # the stretch goes last, after anything added later (Merge result is re-added by extrudepm)
    for delay in (0, 500, 1500):
        QtCore.QTimer.singleShot(delay, lambda: _alive(panel) and _stretch_last(lay))


def _stretch_last(lay):
    for i in range(lay.count() - 1, -1, -1):
        item = lay.itemAt(i)
        spacer = item is not None and item.spacerItem() is not None
        pmfields._forget(item)
        del item
        if spacer:
            pmfields.take_item(lay, i)
    lay.addStretch(1)


def install(view):
    feat = extrudepm._edited()
    if feat is None or feat.TypeId not in PIPES + LOFTS:
        return
    if feat.TypeId in PIPES:
        edit = view.findChild(QtWidgets.QLineEdit, "spineBaseEdit")
        cls = SweepBoxes
    else:
        edit = view.findChild(QtWidgets.QListWidget, "listWidgetReferences")
        cls = LoftBoxes
    if edit is None or edit.property(DONE):
        return
    edit.setProperty(DONE, True)
    panel = edit.parentWidget()
    while panel is not None and not panel.objectName().startswith("PartDesignGui__"):
        panel = panel.parentWidget()
    if panel is None or not isinstance(panel.layout(), QtWidgets.QBoxLayout):
        return
    cls(view, panel, feat)
    try:


        from . import loftsweep
        (loftsweep.add_sweep_boxes if feat.TypeId in PIPES else loftsweep.add_loft_boxes)(panel, feat)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: loft/sweep extra boxes: %s\n" % error)
    if feat.TypeId in PIPES:

        _put_before(view, "Guide Curves", "Options")


def _group_titled(view, title):
    for group in view.findChildren(QtWidgets.QWidget):
        if not group.inherits("QSint::ActionGroup"):
            continue
        for header in group.findChildren(QtWidgets.QWidget):
            if header.inherits("QSint::TaskHeader") and any(
                    hasattr(l, "text") and callable(l.text) and l.text() == title
                    for l in header.findChildren(QtWidgets.QWidget)):
                return group
    return None


def _put_before(view, moving, anchor):
    """Moves the task box titled moving to just above the one titled anchor."""
    try:
        a, b = _group_titled(view, moving), _group_titled(view, anchor)
        if a is None or b is None or a.parentWidget() is not b.parentWidget():
            return False
        lay = b.parentWidget().layout()
        if lay is None or lay.indexOf(a) < 0 or lay.indexOf(b) < 0 or lay.indexOf(a) < lay.indexOf(b):
            return False
        lay.removeWidget(a)
        lay.insertWidget(lay.indexOf(b), a)
        return True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: sweep box order: %s\n" % error)
        return False


# --------------------------------------------------------------------------- tool first
FIRST = {
    "PartDesign_AdditivePipe": ("Sweep", "FEATURES_SWEPT_BOSS", "Profile and Path", "Profile"),
    "PartDesign_SubtractivePipe": ("Cut-Sweep", "FEATURES_SWEPT_CUT", "Profile and Path", "Profile"),
    "PartDesign_AdditiveLoft": ("Loft", "FEATURES_LOFTED_BOSS", "Profiles", "Profiles"),
    "PartDesign_SubtractiveLoft": ("Cut-Loft", "FEATURES_LOFTED_CUT", "Profiles", "Profiles"),
}
PINK = "#ffd6e7"


class ProfilePicker:
    ""



    def __init__(self, native):
        from . import sketchstart
        title, icon, box, label = FIRST[native]
        self.native = native
        self.done = False
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(box)
        self.form.setProperty("swstyle_pm_title", title)
        self.form.setProperty("swstyle_pm_icon", icon)
        lay = QtWidgets.QVBoxLayout(self.form)
        lay.setContentsMargins(4, 4, 4, 4)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label + ":"))
        self.box = QtWidgets.QListWidget()
        self.box.setObjectName("SWStyle_FirstProfile")
        self.box.setFixedHeight(44)
        pmboxes.mark(self.box, True)
        self.box.setToolTip("Pick the sketch for the %s" % label.lower())
        row.addWidget(self.box)
        lay.addLayout(row)
        if native in ("PartDesign_AdditivePipe", "PartDesign_SubtractivePipe"):
            row2 = QtWidgets.QHBoxLayout()
            row2.addWidget(QtWidgets.QLabel("Path:"))
            path = QtWidgets.QListWidget()
            path.setObjectName("SWStyle_FirstPath")
            path.setFixedHeight(44)
            path.setToolTip("The path comes after the profile")
            row2.addWidget(path)
            lay.addLayout(row2)
        self.error = QtWidgets.QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #c00000;")
        self.error.hide()
        lay.addWidget(self.error)
        lay.addStretch(1)
        self.observer = sketchstart._Observer(self)
        Gui.Selection.addObserver(self.observer)
        self._cleaned = False
        self.form.destroyed.connect(lambda *args: self._cleanup())

    def _alive(self):
        try:
            import shiboken6 as shiboken
        except ImportError:
            import shiboken2 as shiboken
        try:
            return shiboken.isValid(self.form)
        except Exception:
            return False

    def picked(self):
        if self.done:
            return
        if not self._alive():
            self.done = True
            self._cleanup()
            return
        try:
            selection = Gui.Selection.getSelectionEx()
        except Exception:
            return
        if not selection:
            return
        entry = selection[-1]
        obj = entry.Object
        subs = [s for s in entry.SubElementNames if s]
        if obj.TypeId == "Sketcher::SketchObject" and not (subs and subs[-1].startswith("Face")):
            native = self.native
            self.box.clear()
            self.box.addItem(obj.Label)

            def start():
                Gui.Selection.clearSelection()
                Gui.Selection.addSelection(obj.Document.Name, obj.Name)
                Gui.runCommand(native, 0)
            self._finish(start)
            return

        faces = [x for x in subs if x.startswith("Face")]
        edges = [x for x in subs if x.startswith("Edge")]
        if len(faces) == 1 and not edges or edges and len(edges) == len(subs):
            native = self.native
            chosen = faces or edges
            self.box.clear()
            self.box.addItem("%s: %s" % (obj.Label, ", ".join(chosen)))
            self._finish(lambda: start_on_elements(native, obj, chosen))
            return
        Gui.Selection.clearSelection()
        self.error.setText("Pick a sketch, a face or the edges of one face for the profile.")
        self.error.show()

    def _finish(self, then):
        self.done = True
        self._cleanup()
        Gui.Control.closeDialog()
        QtCore.QTimer.singleShot(0, then)

    def _cleanup(self):
        if self._cleaned:
            return
        self._cleaned = True
        try:
            Gui.Selection.removeObserver(self.observer)
        except Exception as _fw_err:
            _fw_log("sweeploftpm.py:921", _fw_err)

    def getStandardButtons(self):
        cancel = QtWidgets.QDialogButtonBox.Cancel
        try:
            return int(cancel)
        except TypeError:
            return cancel.value

    def reject(self):
        self.done = True
        self._cleanup()
        Gui.Control.closeDialog()
        return True

    def accept(self):
        return self.reject()


FEATURE_TYPES = {"PartDesign_AdditivePipe": ("PartDesign::AdditivePipe", "AdditivePipe"),
                 "PartDesign_SubtractivePipe": ("PartDesign::SubtractivePipe", "SubtractivePipe"),
                 "PartDesign_AdditiveLoft": ("PartDesign::AdditiveLoft", "AdditiveLoft"),
                 "PartDesign_SubtractiveLoft": ("PartDesign::SubtractiveLoft", "SubtractiveLoft")}


def start_on_elements(native, obj, subs):
    """The Sweep or Loft started on a face or edges as its profile (FreeCAD's Pipe and Loft take a
    (feature, sub-elements) Profile), then its page opens as the command would open it."""
    from . import sketchstart
    body = sketchstart._body()
    if body is None or native not in FEATURE_TYPES:
        return None
    type_id, name = FEATURE_TYPES[native]
    doc = body.Document
    doc.openTransaction(FIRST[native][0])
    try:
        feat = body.newObject(type_id, name)
        feat.Profile = (obj, list(subs))
        doc.recompute()
    except Exception as error:
        doc.abortTransaction()
        App.Console.PrintWarning("FreeCAD: %s on %s: %s\n" % (FIRST[native][0], obj.Label, error))
        return None
    # the transaction stays open, as the command leaves it: the page's check commits it and its
    # cross takes the feature away again
    try:
        Gui.Selection.clearSelection()
        Gui.ActiveDocument.setEdit(feat, 0)
    except Exception as error:
        doc.commitTransaction()
        App.Console.PrintLog("FreeCAD: sweep/loft edit: %s\n" % error)
    return feat


def run_first(native):
    """Sweep or Loft with nothing picked: open the page and wait for the profile sketch.
    Returns True when handled here."""
    if native not in FIRST or App.ActiveDocument is None:
        return False
    try:
        if Gui.Control.activeDialog():
            return False
        gdoc = Gui.ActiveDocument
        if gdoc is None or gdoc.getInEdit() is not None:
            return False
        selection = Gui.Selection.getSelectionEx()
    except Exception:
        return False
    from . import sketchstart
    if sketchstart._body() is None:
        return False
    if selection:

        # and opens its PropertyManager (FreeCAD opened its own page on the face)
        if len(selection) != 1:
            return False
        obj = selection[0].Object
        subs = [x for x in selection[0].SubElementNames if x]
        if obj.TypeId == "Sketcher::SketchObject" or not subs:
            return False
        faces = [x for x in subs if x.startswith("Face")]
        edges = [x for x in subs if x.startswith("Edge")]
        if not (len(faces) == 1 and not edges or edges and len(edges) == len(subs)):
            return False
        return start_on_elements(native, obj, faces or edges) is not None
    if start_empty(native) is None:
        Gui.Control.showDialog(ProfilePicker(native))     # the full page could not open: wait for the profile
    return True


def start_empty(native):
    ""


    from . import sketchstart
    body = sketchstart._body()
    if body is None or native not in FEATURE_TYPES:
        return None
    type_id, name = FEATURE_TYPES[native]
    doc = body.Document
    doc.openTransaction(FIRST[native][0])
    feat = None
    try:
        feat = body.newObject(type_id, name)
        Gui.Selection.clearSelection()
        Gui.ActiveDocument.setEdit(feat, 0)
        if not Gui.Control.activeDialog():
            raise RuntimeError("no page")
    except Exception as error:
        App.Console.PrintLog("FreeCAD: %s with nothing picked: %s\n" % (FIRST[native][0], error))
        doc.abortTransaction()
        return None
    return feat
