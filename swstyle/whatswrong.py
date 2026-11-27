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


import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import paths
from .widgets import alive

Qt = QtCore.Qt
SETTING = "ShowErrorsEveryRebuild"
SHOW_ERRORS = "WhatsWrongShowErrors"
SHOW_WARNINGS = "WhatsWrongShowWarnings"
NOTE = "* Select FeatureXpert to attempt repair of the highlighted error(s)."
WARNING_YELLOW = "#f2b705"
ERROR_RED = "#d9261c"
_dialog = None


def show_every_rebuild():
    return paths.params().GetBool(SETTING, True)


def errors(doc):
    """(object, text) for every feature FreeCAD could not compute, in tree order."""
    found = []
    for obj in doc.Objects:
        try:
            if "Invalid" not in obj.State:
                continue
            if _redundant_only(obj):
                continue        # fh256: a Warning row (warnings()), as the Stop and Repair question says
            text = obj.getStatusString() or "Error"
        except Exception:
            continue
        if _all_suppressed(obj):
            continue
        if _rolled_back(obj):
            continue
        if _failed_inside(obj):
            continue
        found.append((obj, row_text(obj, text)))
    return found


def _rolled_back(obj):
    try:
        from . import editguard
        return bool(editguard.rolled_back(obj))
    except Exception:
        return False


def _lost_pick(obj):
    """True when one of obj's picked faces / edges is lost (FreeCAD writes it "?Edge3")."""
    for name in ("Base", "Profile", "Faces", "Edges"):
        try:
            value = getattr(obj, name, None)
        except Exception:
            continue
        links = value if isinstance(value, list) else [value]
        for link in links:
            if isinstance(link, tuple) and len(link) == 2 and isinstance(link[1], (list, tuple)):
                if any(isinstance(sub, str) and sub.startswith("?") for sub in link[1]):
                    return True
    return False


def row_text(obj, text=None):
    """The words of a failed feature's row (the tree's tooltip says the same)."""
    if text is None:
        text = obj.getStatusString() or "Error"
    if text in ("", "Error", "Invalid", "Touched", "Valid") and _lost_pick(obj):
        text = "Invalid edge link"      # FreeCAD marks a pick it lost with "?": say so, not just "Error"
    if text in ("", "Error", "Invalid", "Touched", "Valid"):
        text = python_reason(obj) or "The feature could not be rebuilt."
    if obj.TypeId == "PartDesign::Body" and "Tip shape is empty" in text:
        text = "The part has no solid: its last feature made nothing. Edit that feature."
    try:
        from .rebuilderrors import describe as plain
        return plain(obj, describe(text))
    except Exception:
        return describe(text)


_reasons = {}     # (document, feature) -> the message a Python feature gave last time


_asked = {}      # (document, feature) -> the rebuild count when the feature was last asked


def python_reason(obj):
    """_python_reason once per rebuild: the tree's tooltip and What's Wrong give the same words,
    and hovering a row does not rebuild the feature."""
    try:
        from .rebuildretry import RECOMPUTES
        stamp = RECOMPUTES[0]
    except Exception:
        stamp = None
    key = (obj.Document.Name, obj.Name)
    if stamp is not None and _asked.get(key) == stamp:
        return _reasons.get(key, "")
    message = _python_reason(obj)
    _asked[key] = stamp
    return message


def _python_reason(obj):
    ""


    proxy = getattr(obj, "Proxy", None)
    if proxy is None or not hasattr(proxy, "execute"):
        return ""
    key = (obj.Document.Name, obj.Name)
    try:
        old = obj.Shape.copy() if hasattr(obj, "Shape") else None
    except Exception:
        old = None
    try:
        proxy.execute(obj)
        message = ""
    except (AttributeError, TypeError, IndexError, KeyError, NameError) as error:
        # a reference of the wrong kind or gone (Python's own words say nothing to a person)
        message = "A face, edge or plane this feature uses is missing. Edit the feature and pick its sketch, face or edge again."
    except Exception as error:
        message = str(error).strip().splitlines()[-1] if str(error).strip() else ""
        if message.startswith("FreeCAD exception thrown (") and message.endswith(")"):
            message = message[len("FreeCAD exception thrown ("):-1]
    finally:
        try:
            if old is not None:
                obj.Shape = old
        except Exception as _fw_err:
            _fw_log("whatswrong.py:146", _fw_err)
    if message:
        _reasons[key] = message
    return message or _reasons.get(key, "")


def _failed_inside(obj):
    """A body whose own error only says one of its features failed."""
    if obj.TypeId != "PartDesign::Body":
        return False
    try:
        return any("Invalid" in o.State for o in obj.Group if o is not obj)
    except Exception:
        return False


def _all_suppressed(obj):
    """A body whose solid features are all suppressed (FreeCAD: 'Tip shape is empty')."""
    if obj.TypeId != "PartDesign::Body":
        return False
    feats = [o for o in obj.Group if "Suppressed" in o.PropertiesList and o.isDerivedFrom("PartDesign::Feature")]
    return bool(feats) and all(o.Suppressed for o in feats)


def describe(text):
    ""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return text
    joined = lines[0]
    for line in lines[1:]:
        joined += (" " if joined.endswith(":") else ". ") + line
    return joined.replace("constraints", "relations").replace("constraint", "relation")


def _redundant_only(obj):
    ""

    try:
        return obj.TypeId == "Sketcher::SketchObject" and bool(obj.RedundantConstraints) and \
            not obj.ConflictingConstraints and not obj.MalformedConstraints
    except Exception:
        return False


def warnings(doc):
    """(object, text) for every sketch that solves but has redundant relations, in tree order."""
    found = []
    for obj in doc.Objects:
        try:
            if obj.TypeId == "Sketcher::SketchObject" and obj.RedundantConstraints and \
                    ("Invalid" not in obj.State or _redundant_only(obj)):
                found.append((obj, "The sketch has redundant relations."))
        except Exception as _fw_err:
            _fw_log("whatswrong.py:191", _fw_err)
    return found


def _page_open():
    try:
        if Gui.Control.activeDialog():
            return True
    except Exception:
        return False
    try:
        # a feature its PropertyManager has just made, its page not shown yet (Flex, Dome... build a
        # first preview before the page opens): its message goes on that page, not in this box
        from . import simplefeature
        docs = App.listDocuments()
        if any(d in docs and docs[d].getObject(n) is not None for d, n in list(simplefeature._made)):
            return True
    except Exception:
        return False
    try:
        # the Fillet / Chamfer / Shell / Draft page builds its first preview before it shows: a preview

        from . import filletpm
        page = filletpm.current()
        return page is not None and not getattr(page, "closing", False)
    except Exception:
        return False


def _hands_busy():
    """A drag is going on (Instant3D, the rollback bar, a dimension), or a menu or a question is up."""
    try:
        app = QtWidgets.QApplication
        return (app.mouseButtons() != Qt.NoButton or app.activeModalWidget() is not None
                or app.activePopupWidget() is not None)
    except Exception:
        return False


_waiting = []


def _after_page(name, auto=False):
    """Look again once the open PropertyManager (or sketch) is closed, once per page."""
    if _waiting:
        return
    _waiting.append(name)

    def poll():
        if _page_open() or (auto and _hands_busy()):
            QtCore.QTimer.singleShot(300, poll)
            return
        del _waiting[:]
        try:
            d = App.getDocument(name)
        except Exception:
            return
        (after_recompute if auto else after_rebuild)(d)
    QtCore.QTimer.singleShot(300, poll)


_known = {}      # document -> the errors the box was last asked about: (feature, its words)
_touched = {}    # document -> when the box was last opened or closed (time.monotonic)
_auto = [False]
QUIET = 1.0
OPENED = [0]     # how often the box opened by itself (for the checks)


def forget(name):
    _known.pop(name, None)
    _touched.pop(name, None)


def after_recompute(doc):
    ""




    _auto[0] = True
    try:
        return after_rebuild(doc)
    finally:
        _auto[0] = False


def after_rebuild(doc):
    ""


    auto = _auto[0]
    if _page_open() or (auto and _hands_busy()):

        # Vertex before the vertex is picked...); the box waits for OK or Cancel. Opening it here took
        # the keyboard from the page, so typed values never reached the feature.
        _after_page(doc.Name, auto)
        return None
    found = errors(doc)
    before = _known.get(doc.Name, frozenset())
    now = frozenset((obj.Name, text) for obj, text in found)
    new = bool(now - before)
    _known[doc.Name] = now
    if not found or not (new or show_every_rebuild()):
        return None
    if all(_lost_pick(obj) or _lost_link_text(text) for obj, text in found) and not getattr(after_rebuild, "_waited", False):


        name = doc.Name
        _known[name] = before       # not shown yet: still new when looked at again

        def again():
            try:
                d = App.getDocument(name)
            except Exception:
                return
            after_rebuild._waited = True
            try:
                (after_recompute if auto else after_rebuild)(d)
            finally:
                after_rebuild._waited = False
        QtCore.QTimer.singleShot(400, again)
        return None
    if auto and not new:
        box = dialog()
        if box is not None and box.isVisible() and box.doc_name == doc.Name:
            box.fill(doc, found)        # already open: the rows follow, the keyboard stays where it is
            return box
        if time.monotonic() - _touched.get(doc.Name, -1e9) < QUIET:
            return None
    if auto:
        OPENED[0] += 1
    return show(doc, found)


def _lost_link_text(text):
    t = (text or "").lower()
    return "edge link" in t or "face link" in t


def show(doc=None, found=None):
    global _dialog
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    if found is None:
        found = errors(doc)
    if _dialog is None or not alive(_dialog):
        _dialog = WhatsWrongDialog(Gui.getMainWindow())
    _dialog.fill(doc, found)
    _touched[doc.Name] = time.monotonic()
    _dialog.show()
    _dialog.raise_()
    _dialog.activateWindow()
    return _dialog


def dialog():
    return _dialog if _dialog is not None and alive(_dialog) else None


def error_icon(size=16):
    ""
    dpr = 2
    pm = QtGui.QPixmap(size * dpr, size * dpr)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QColor(ERROR_RED))
    p.drawEllipse(QtCore.QRectF(1, 1, size - 2, size - 2))
    pen = QtGui.QPen(QtGui.QColor("#ffffff"), 1.8)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    m = size * 0.31
    p.drawLine(QtCore.QPointF(m, m), QtCore.QPointF(size - m, size - m))
    p.drawLine(QtCore.QPointF(size - m, m), QtCore.QPointF(m, size - m))
    p.end()
    return QtGui.QIcon(pm)


def warning_icon(size=16):
    ""
    dpr = 2
    pm = QtGui.QPixmap(size * dpr, size * dpr)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    # strokes scale with the mark: at the tree's 9 px corner mark fixed 1 px edge and 1.8 px "!" covered the

    p.setPen(QtGui.QPen(QtGui.QColor("#8a6a00"), min(1.0, size / 16.0)))
    p.setBrush(QtGui.QColor(WARNING_YELLOW))
    p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(size / 2, 0.5), QtCore.QPointF(size - 0.5, size - 0.5),
                                   QtCore.QPointF(0.5, size - 0.5)]))
    pen = QtGui.QPen(QtGui.QColor("#202020"), max(0.8, size * 0.11))
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.drawLine(QtCore.QPointF(size / 2, size * 0.38), QtCore.QPointF(size / 2, size * 0.66))
    p.drawPoint(QtCore.QPointF(size / 2, size * 0.8))
    p.end()
    return QtGui.QIcon(pm)


_eyes = {}


def _eye_icon(on):
    """The Preview column's eye: open while that row's trouble is shown."""
    if on not in _eyes:
        from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
        pm = _hidpi.canvas(16, 16)
        pm.fill(Qt.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        pen = QtGui.QPen(QtGui.QColor("#1f5fbf" if on else "#606060"), 1.4)
        p.setPen(pen)
        path = QtGui.QPainterPath()
        path.moveTo(1.5, 8)
        path.quadTo(8, 1, 14.5, 8)
        path.quadTo(8, 15, 1.5, 8)
        p.drawPath(path)
        p.setBrush(QtGui.QColor("#1f5fbf" if on else "#606060"))
        p.drawEllipse(QtCore.QPointF(8, 8), 2.4 if on else 1.6, 2.4 if on else 1.6)
        p.end()
        _eyes[on] = QtGui.QIcon(pm)
    return _eyes[on]


class WhatsWrongDialog(QtWidgets.QDialog):
    COLUMNS = ("Type", "Feature", "Preview", "Help", "Description")
    TYPE, FEATURE, PREVIEW, HELP, DESCRIPTION = range(5)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SWWhatsWrong")
        self.setWindowTitle("What's Wrong")
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        self.setMinimumSize(520, 220)
        self.resize(680, 260)
        self.doc_name = ""
        self.names = []
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        self.table = QtWidgets.QTreeWidget(self)
        self.table.setObjectName("SWWhatsWrongTable")
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHeaderLabels(list(self.COLUMNS))
        self.table.setRootIsDecorated(False)
        self.table.setUniformRowHeights(True)
        self.table.setAllColumnsShowFocus(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setIconSize(QtCore.QSize(16, 16))
        header = self.table.header()
        header.setStretchLastSection(True)
        header.resizeSection(0, 80)
        header.resizeSection(1, 170)
        header.resizeSection(2, 56)
        header.resizeSection(3, 40)
        self.table.itemDoubleClicked.connect(self._pick)
        self.table.itemClicked.connect(self._clicked)
        self.previewing = None
        lay.addWidget(self.table, 1)
        self.note = QtWidgets.QLabel(NOTE, self)
        self.note.setObjectName("SWWhatsWrongNote")
        lay.addWidget(self.note)
        row = QtWidgets.QHBoxLayout()
        boxes = QtWidgets.QVBoxLayout()
        boxes.setSpacing(2)
        self.show_errors = self._box("Show errors", SHOW_ERRORS, "SWWhatsWrongErrors", boxes)
        self.show_warnings = self._box("Show warnings", SHOW_WARNINGS, "SWWhatsWrongWarnings", boxes)
        self.every = self._box("Display What's Wrong during rebuild", SETTING, "SWWhatsWrongEvery", boxes)
        row.addLayout(boxes)
        row.addStretch(1)
        buttons = QtWidgets.QVBoxLayout()
        buttons.setSpacing(4)
        self.xpert = QtWidgets.QPushButton("FeatureXpert", self)
        self.xpert.setObjectName("SWWhatsWrongXpert")
        self.xpert.setVisible(False)     # msgbox-1119: shown only when it can repair (no greyed button)
        self.xpert.setToolTip("Repair failed fillets, chamfers and drafts")
        self.xpert.clicked.connect(self.feature_xpert)
        self.last_repair = []
        self.close_button = QtWidgets.QPushButton("Close", self)
        self.close_button.setObjectName("SWWhatsWrongClose")
        self.close_button.setDefault(True)
        self.close_button.clicked.connect(self.close)
        self.help_button = QtWidgets.QPushButton("Help", self)
        self.help_button.setObjectName("SWWhatsWrongHelp")
        self.help_button.clicked.connect(self.general_help)
        for button in (self.xpert, self.close_button, self.help_button):
            button.setMinimumWidth(96)
            buttons.addWidget(button)
        row.addLayout(buttons)
        lay.addLayout(row)

    def hideEvent(self, event):
        _touched[self.doc_name] = time.monotonic()      # closed by hand: see after_rebuild
        super().hideEvent(event)

    def _box(self, text, key, name, layout):
        box = QtWidgets.QCheckBox(text, self)
        box.setObjectName(name)
        box.setChecked(paths.params().GetBool(key, True))
        box.toggled.connect(lambda on, k=key: self._set(k, on))
        layout.addWidget(box)
        return box

    def _set(self, key, on):
        paths.params().SetBool(key, bool(on))
        if key != SETTING:
            doc = App.getDocument(self.doc_name) if self.doc_name in App.listDocuments() else None
            if doc is not None:
                self.fill(doc, errors(doc))

    def fill(self, doc, found):
        self.doc_name = doc.Name
        self.names = []
        self.table.clear()
        for box, key in ((self.show_errors, SHOW_ERRORS), (self.show_warnings, SHOW_WARNINGS),
                         (self.every, SETTING)):
            box.blockSignals(True)
            box.setChecked(paths.params().GetBool(key, True))
            box.blockSignals(False)
        rows = []
        if self.show_errors.isChecked():
            rows += [("Error", error_icon(), obj, text) for obj, text in found]
        if self.show_warnings.isChecked():
            rows += [("Warning", warning_icon(), obj, text) for obj, text in warnings(doc)]
        for kind, mark, obj, text in rows:
            item = QtWidgets.QTreeWidgetItem([kind, obj.Label, "", "", text])
            item.setIcon(0, mark)
            item.setIcon(self.PREVIEW, _eye_icon(False))
            item.setToolTip(self.PREVIEW, "Preview: show where the trouble is in the graphics area")
            from . import msgicons
            item.setIcon(self.HELP, msgicons.icon("question"))
            item.setToolTip(self.HELP, "What this error means and how to repair it")
            try:
                icon = obj.ViewObject.Icon
            except Exception:
                icon = None
            if isinstance(icon, QtGui.QIcon) and not icon.isNull():
                item.setIcon(1, icon)
            item.setToolTip(self.DESCRIPTION, text)
            item.setData(0, Qt.UserRole, obj.Name)
            self.table.addTopLevelItem(item)
            self.names.append(obj.Name)
        if not rows:
            item = QtWidgets.QTreeWidgetItem(["", "", "", "", "No errors: every feature rebuilt."])
            item.setFlags(Qt.ItemIsEnabled)
            self.table.addTopLevelItem(item)
        self._fit_width([text for _k, _m, _o, text in rows])
        self._sync_xpert()

    def _fit_width(self, texts):
        """Wide enough for the longest description (error check 417: 'Try a smal...' was cut at the
        first size), up to nine tenths of the screen; never narrower than the user made it."""
        try:
            if not texts:
                return
            metrics = self.table.fontMetrics()
            longest = max(metrics.horizontalAdvance(t) for t in texts)
            header = self.table.header()
            fixed = sum(header.sectionSize(c) for c in range(self.DESCRIPTION))
            want = fixed + longest + 60       # cell padding, frame, the dialog's margins
            screen = self.screen().availableGeometry() if hasattr(self, "screen") and self.screen() else None
            cap = int(screen.width() * 0.9) if screen is not None else want
            want = min(want, cap)
            if want > self.width():
                self.resize(want, self.height())
        except Exception as _fw_err:
            _fw_log("whatswrong.py:fit", _fw_err)

    def _xpert_targets(self, selected=True):
        items = self.table.selectedItems() if selected else []
        if not items:
            items = [self.table.topLevelItem(i) for i in range(self.table.topLevelItemCount())]
        return [i.data(0, Qt.UserRole) for i in items if i.text(0) == "Error" and i.data(0, Qt.UserRole)]

    def _sync_xpert(self):
        from . import featurexpert
        doc = App.getDocument(self.doc_name) if self.doc_name in App.listDocuments() else None
        fixable = doc is not None and any(featurexpert.can_repair(doc.getObject(n))
                                          for n in self._xpert_targets(selected=False))
        self.xpert.setEnabled(True)
        self.xpert.setVisible(bool(featurexpert.enabled() and fixable))

    def feature_xpert(self, quiet=False):
        """FeatureXpert: repair the highlighted error rows (all of them when none is highlighted)."""
        from . import featurexpert
        doc = App.getDocument(self.doc_name) if self.doc_name in App.listDocuments() else None
        if doc is None:
            return []
        self.last_repair = featurexpert.repair(doc, self._xpert_targets())
        self.fill(doc, errors(doc))
        if not quiet and App.GuiUp:
            fixed = ["%s: %s" % (label, what) for label, what in self.last_repair if what]
            failed = [label for label, what in self.last_repair if not what]
            text = "\n".join(["FeatureXpert repaired:"] + fixed) if fixed else "FeatureXpert could not repair the errors."
            if fixed and failed:
                text += "\n\nNot repaired: " + ", ".join(failed)
            QtWidgets.QMessageBox.information(self, "FeatureXpert", text)
        return self.last_repair

    def rows(self):
        """(type, feature, description) per row, for checks."""
        out = []
        for i in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(i)
            out.append(tuple(item.text(c) for c in (self.TYPE, self.FEATURE, self.DESCRIPTION)))
        return out

    def _clicked(self, item, column):
        if column == self.PREVIEW:
            self.preview(item)
        elif column == self.HELP:
            self.help(item)

    def preview(self, item):
        ""

        name = item.data(0, Qt.UserRole)
        if not name or self.doc_name not in App.listDocuments():
            return None
        doc = App.getDocument(self.doc_name)
        obj = doc.getObject(name)
        Gui.Selection.clearSelection()
        for i in range(self.table.topLevelItemCount()):
            other = self.table.topLevelItem(i)
            if other.data(0, Qt.UserRole):
                other.setIcon(self.PREVIEW, _eye_icon(False))
        if obj is None or self.previewing == name:
            self.previewing = None
            return None
        self.previewing = name
        item.setIcon(self.PREVIEW, _eye_icon(True))
        picked = []
        for prop in ("Base", "Profile", "AttachmentSupport", "Support"):
            try:
                value = getattr(obj, prop)
            except Exception:
                continue
            links = value if isinstance(value, list) else [value]
            for link in links:
                if isinstance(link, tuple) and len(link) == 2 and hasattr(link[0], "Name"):
                    subs = link[1] if isinstance(link[1], (list, tuple)) else [link[1]]
                    for sub in subs:
                        try:
                            Gui.Selection.addSelection(doc.Name, link[0].Name, sub or "")
                            picked.append((link[0].Name, sub))
                        except Exception as _fw_err:
                            _fw_log("whatswrong.py:543", _fw_err)
        if not picked:
            try:
                Gui.Selection.addSelection(doc.Name, name)
                picked.append((name, ""))
            except Exception as _fw_err:
                _fw_log("whatswrong.py:549", _fw_err)
        return picked

    def help(self, item):
        name = item.data(0, Qt.UserRole)
        if not name or self.doc_name not in App.listDocuments():
            return ""
        obj = App.getDocument(self.doc_name).getObject(name)
        from . import rebuilderrors
        text = item.text(self.DESCRIPTION)
        if item.text(0) == "Warning" and obj is not None and rebuilderrors.dangling(obj):
            words = ("Relations and dimensions to a model edge that is gone are dangling: they are "
                     "drawn in brown while the sketch is edited. Delete them, or drag the end of each "
                     "onto an edge of the model, in the Display/Delete Relations panel.")
        else:
            words = rebuilderrors.help_text(obj, text)
        self.last_help = words
        if App.GuiUp and not getattr(self, "quiet_help", False):
            QtWidgets.QMessageBox.information(self, "What's Wrong: %s" % (obj.Label if obj else ""), words)
        return words

    def general_help(self):
        """Help: the help of the highlighted row (the first error when none is), else what the box is."""
        item = self.table.currentItem()
        if item is None or not item.data(0, Qt.UserRole):
            item = next((self.table.topLevelItem(i) for i in range(self.table.topLevelItemCount())
                         if self.table.topLevelItem(i).data(0, Qt.UserRole)), None)
        if item is not None:
            return self.help(item)
        words = ("What's Wrong lists the features that did not rebuild (errors) and the sketches with "
                 "redundant or dangling relations (warnings). Click the eye to see where a feature is, the "
                 "question mark for how to repair it, and double-click a row to pick the feature.")
        self.last_help = words
        if App.GuiUp and not getattr(self, "quiet_help", False):
            QtWidgets.QMessageBox.information(self, "What's Wrong", words)
        return words

    def _pick(self, item, column):
        name = item.data(0, Qt.UserRole)
        if not name:
            return
        try:
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(self.doc_name, name)
        except Exception as _fw_err:
            _fw_log("whatswrong.py:578", _fw_err)
