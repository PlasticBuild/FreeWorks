# SPDX-License-Identifier: LGPL-2.1-or-later
""


















_FW_SEEN = set()


def _fw_log(site, err):
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return


import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

# feature pages that take no picks while none of their pick buttons is pressed
SAFE = ("PartDesign::Pad", "PartDesign::Pocket", "PartDesign::Revolution", "PartDesign::Groove",
        "PartDesign::LinearPattern", "PartDesign::PolarPattern", "PartDesign::Mirrored",
        "PartDesign::Hole")
COMMANDS = ("SWStyle_RefPlane", "SWStyle_RefAxis", "SWStyle_RefPoint", "SWStyle_RefCoordinateSystem")
TITLES = {"SWStyle_RefPlane": "Plane", "SWStyle_RefAxis": "Axis", "SWStyle_RefPoint": "Point",
          "SWStyle_RefCoordinateSystem": "Coordinate System"}
_host = []          # the nested page, while open


class _Doc:
    """The document as the reference page sees it while nested: everything but its own transactions."""

    def __init__(self, doc):
        object.__setattr__(self, "_d", doc)

    @property
    def __class__(self):            # isinstance(x, App.Document) holds (pickguard, refplane)
        return App.Document

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_d"), name)

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, "_d"), name, value)

    def __eq__(self, other):
        d = object.__getattribute__(self, "_d")
        return other is d or other is self or (isinstance(other, _Doc) and object.__getattribute__(other, "_d") is d)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(object.__getattribute__(self, "_d").Name)

    def openTransaction(self, *args):
        return None

    def commitTransaction(self, *args):
        return None

    def abortTransaction(self, *args):
        return None


class _Control:
    def __init__(self, host):
        self._host = host

    def closeDialog(self):
        self._host.closed()

    def activeDialog(self):
        return self._host.alive

    def showDialog(self, *args):
        return None             # one page over the feature's is enough

    def __getattr__(self, name):
        return getattr(Gui.Control, name)


class _Gui:
    def __init__(self, host):
        self.Control = _Control(host)

    def __getattr__(self, name):
        return getattr(Gui, name)


def _modules():
    from . import refplane, refaxis, refgeom2
    return (refplane, refaxis, refgeom2)


def _task_view():
    try:
        for w in Gui.getMainWindow().findChildren(QtWidgets.QWidget):
            if w.inherits("Gui::TaskView::TaskView") and w.isVisible():
                return w
    except Exception as _fw_err:
        _fw_log("refnest.py:taskview", _fw_err)
    return None


def _feature():
    try:
        edit = Gui.ActiveDocument.getInEdit() if Gui.ActiveDocument is not None else None
        return edit.Object if edit is not None else None
    except Exception:
        return None


def _pick_mode_on(view):
    """A pressed (checked) button on the feature's page: a pick mode (Select, Add, Face...) is on."""
    for b in view.findChildren(QtWidgets.QAbstractButton):
        try:
            if b.isCheckable() and b.isChecked() and b.isVisible() and not isinstance(
                    b, (QtWidgets.QCheckBox, QtWidgets.QRadioButton)):
                return True
        except Exception:
            continue
    return False


def can_nest(native):
    if native not in COMMANDS or _host or not Gui.Control.activeDialog():
        return False
    feat = _feature()
    if feat is None or feat.TypeId not in SAFE:
        return False
    view = _task_view()
    return view is not None and not _pick_mode_on(view)


def nest(native):
    """Run the reference command over the open feature page. True when it did (else the caller
    closes the page first, as before)."""
    try:
        if not can_nest(native):
            return False
        return _Host(native).alive
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: reference geometry over the open page: %s\n" % error)
        while _host:
            try:
                _host[-1].finish(False)
            except Exception:
                _host[:] = []
        return True


def _panel(native, doc, body):
    from . import refplane, refaxis, refgeom2
    if native == "SWStyle_RefPlane":
        return refplane.PlanePanel(doc, body, ())
    if native == "SWStyle_RefAxis":
        return refaxis.AxisPanel(doc, body, ())
    if native == "SWStyle_RefPoint":
        return refgeom2.PointPM(doc, ())
    return refgeom2.CoordinateSystemPM(doc, ())


def _frame(widget):
    ""
    title = widget.windowTitle()
    box = QtWidgets.QGroupBox(title if title and title != "Message" else "")
    box.setObjectName("SWNestGroup")
    lay = QtWidgets.QVBoxLayout(box)
    lay.setContentsMargins(6, 6, 6, 6)
    lay.addWidget(widget)
    widget.show()
    return box


class _Host(QtWidgets.QFrame):
    """The reference page over the feature's page: title, check and cross, the page's groups."""

    def __init__(self, native):
        view = _task_view()
        super().__init__(view.parentWidget())
        self.setObjectName("SWNestedPM")
        self.native = native
        self.alive = False
        self.view = view
        self.doc = App.ActiveDocument
        self.feature = _feature()
        self.before = {o.Name for o in self.doc.Objects}
        self.selection = Gui.Selection.getSelectionEx(self.doc.Name)
        self.setAutoFillBackground(True)
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel(TITLES[native])
        title.setObjectName("SWNestedTitle")
        f = title.font()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() * 1.15)
        title.setFont(f)
        head.addWidget(title, 1)
        lay.addLayout(head)
        row = QtWidgets.QHBoxLayout()
        self.ok = QtWidgets.QToolButton()
        self.ok.setObjectName("SWNestedOK")
        self.ok.setToolTip("OK: back to %s" % (self.feature.Label if self.feature else "the feature"))
        self.cancel = QtWidgets.QToolButton()
        self.cancel.setObjectName("SWNestedCancel")
        self.cancel.setToolTip("Cancel: back to %s" % (self.feature.Label if self.feature else "the feature"))
        for b, glyph, colour in ((self.ok, "✔", "#2e9e3e"), (self.cancel, "✖", "#c62828")):
            b.setText(glyph)
            b.setStyleSheet("QToolButton { color: %s; font-size: 16pt; border: none; padding: 0 4px; }" % colour)
            b.setAutoRaise(True)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        note = QtWidgets.QLabel("%s stays open underneath." % (self.feature.Label if self.feature else "The feature"))
        note.setObjectName("SWNestedNote")
        note.setWordWrap(True)
        lay.addWidget(note)
        area = QtWidgets.QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QtWidgets.QFrame.NoFrame)
        inner = QtWidgets.QWidget()
        self.inner = QtWidgets.QVBoxLayout(inner)
        area.setWidget(inner)
        lay.addWidget(area, 1)
        self.ok.clicked.connect(lambda *_a: self.press(True))
        self.cancel.clicked.connect(lambda *_a: self.press(False))
        # the reference page's module sees the document without transactions and this page as the dialog
        self.proxy = _Gui(self)
        self.saved = [(m, m.Gui) for m in _modules()]
        _host.append(self)
        self.alive = True
        for m in _modules():
            m.Gui = self.proxy
        try:
            from . import refplane
            body = refplane.body_of(self.doc)
            Gui.Selection.clearSelection()
            self.panel = _panel(native, _Doc(self.doc), body)
        except BaseException:
            self._restore()
            raise
        form = self.panel.form if isinstance(self.panel.form, (list, tuple)) else [self.panel.form]
        for w in form:
            self.inner.addWidget(_frame(w))
        self.inner.addStretch(1)
        view.installEventFilter(self)
        self.keys = _Keys(self)
        QtWidgets.QApplication.instance().installEventFilter(self.keys)
        self._place()
        self.show()
        self.raise_()
        QtCore.QTimer.singleShot(200, self._guard)

    def eventFilter(self, obj, event):
        if obj is self.view and event.type() in (QtCore.QEvent.Resize, QtCore.QEvent.Move, QtCore.QEvent.Show):
            self._place()
        return False

    def _place(self):
        try:
            self.setGeometry(self.view.geometry())
        except Exception as _fw_err:
            _fw_log("refnest.py:place", _fw_err)

    def press(self, ok):
        if not self.alive:
            return False
        self._ok_pressed = bool(ok)
        try:
            done = self.panel.accept() if ok else self.panel.reject()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s: %s\n" % (TITLES[self.native], error))
            self._ok_pressed, done = False, True
        if self.alive and (done or not ok):
            self.closed()           # the page did not close itself
        return bool(done)

    def closed(self):
        """The reference page closed (its _close calls closeDialog, here this): OK keeps what it made."""
        if not self.alive:
            return
        self.alive = False
        keep = bool(getattr(self, "_ok_pressed", False))
        QtCore.QTimer.singleShot(0, lambda: self.finish(keep))

    def _guard(self):
        """The feature's page closed under this one (its document closed): this one goes too."""
        if not self.alive:
            return
        try:
            gone = not Gui.Control.activeDialog() or self.doc.Name not in App.listDocuments()
        except Exception:
            gone = True
        if gone:
            self.alive = False
            self.finish(False)
            return
        QtCore.QTimer.singleShot(200, self._guard)

    def _new(self):
        try:
            return [o for o in self.doc.Objects if o.Name not in self.before]
        except Exception:
            return []

    def _restore(self):
        for m, g in self.saved:
            m.Gui = g
        try:
            QtWidgets.QApplication.instance().removeEventFilter(self.keys)
        except Exception:
            pass
        if self in _host:
            _host.remove(self)

    def finish(self, ok):
        self.alive = False
        self._restore()
        try:
            self.view.removeEventFilter(self)
        except Exception as _fw_err:
            _fw_log("refnest.py:filter", _fw_err)
        made = self._new()
        if not ok:
            for o in reversed(made):
                _remove(o)
            made = []
        else:
            _before_feature(made, self.feature)
            _watch(self.doc, self.feature, made)
        try:
            self.doc.recompute()
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("refnest.py:recompute", _fw_err)
        self.hide()
        self.deleteLater()
        return made


class _Keys(QtCore.QObject):
    """While the reference page is up, Enter and Esc are its OK and Cancel, not the feature's (the
    feature's page underneath must not be closed by them)."""

    def __init__(self, host):
        super().__init__()
        self.host = host

    def eventFilter(self, obj, event):
        try:
            if event.type() != QtCore.QEvent.KeyPress or not self.host.alive:
                return False
            key = event.key()
            if key == QtCore.Qt.Key_Escape:
                QtCore.QTimer.singleShot(0, lambda: self.host.press(False))
                return True
            if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
                focus = QtWidgets.QApplication.focusWidget()
                if isinstance(focus, (QtWidgets.QPlainTextEdit, QtWidgets.QTextEdit)):
                    return False
                QtCore.QTimer.singleShot(0, lambda: self.host.press(True))
                return True
        except Exception:
            return False
        return False


def busy():
    return any(h.alive for h in _host)


def cancel_nested():
    """Another command starts: the reference page over the feature's goes first (its Cancel)."""
    for h in list(_host):
        if h.alive:
            h.press(False)


def _remove(o):
    try:
        doc = o.Document
        for p in o.InList:
            if p.isDerivedFrom("PartDesign::Body"):
                p.removeObject(o)
        doc.removeObject(o.Name)
    except Exception as _fw_err:
        _fw_log("refnest.py:remove", _fw_err)


def _before_feature(made, feature):
    ""
    if feature is None:
        return
    body = next((p for p in feature.InList if p.isDerivedFrom("PartDesign::Body")), None)
    if body is None:
        return
    for o in made:
        try:
            if o in body.Group and body.Group.index(o) > body.Group.index(feature):
                body.removeObject(o)
                body.insertObject(o, feature, False)
        except Exception as _fw_err:
            _fw_log("refnest.py:order", _fw_err)


def _recipe(o):
    try:
        support = [(s.Name, list(subs)) for s, subs in (o.AttachmentSupport or [])]
    except Exception:
        support = []
    keep = {}
    for p in o.PropertiesList:
        if o.getGroupOfProperty(p) in ("FreeCAD references", "Coordinate System axes"):
            try:
                keep[p] = getattr(o, p)
            except Exception:
                pass
    return {"type": o.TypeId, "name": o.Name, "label": o.Label, "support": support, "mode": o.MapMode,
            "offset": App.Placement(o.AttachmentOffset), "placement": App.Placement(o.Placement), "keep": keep}


def _watch(doc, feature, made):
    ""

    if not made:
        return
    recipes = [_recipe(o) for o in made]
    body = next((p for p in made[0].InList if p.isDerivedFrom("PartDesign::Body")), None)
    body_name = body.Name if body is not None else None
    doc_name = doc.Name
    names = [r["name"] for r in recipes]

    def poll(tries=[0]):
        tries[0] += 1
        try:
            d = App.listDocuments().get(doc_name)
            if d is None:
                return
            if Gui.Control.activeDialog() and tries[0] < 72000:
                QtCore.QTimer.singleShot(100, poll)
                return
            if all(d.getObject(n) is not None for n in names):
                return              # the feature's OK kept them
            _remake(d, body_name, [r for r in recipes if d.getObject(r["name"]) is None])
        except Exception as error:
            App.Console.PrintLog("FreeCAD: reference geometry after the feature closed: %s\n" % error)
    QtCore.QTimer.singleShot(100, poll)


def _remake(doc, body_name, recipes):
    body = doc.getObject(body_name) if body_name else None
    if not recipes:
        return []
    title = TITLES.get({"PartDesign::Plane": "SWStyle_RefPlane", "PartDesign::Line": "SWStyle_RefAxis",
                        "PartDesign::Point": "SWStyle_RefPoint"}.get(recipes[0]["type"], ""), "Reference Geometry")
    out = []
    doc.openTransaction(title)
    try:
        for r in recipes:
            support = []
            for name, subs in r["support"]:
                o = doc.getObject(name)
                if o is None:
                    support = None
                    break
                support.append((o, subs))
            if support is None:
                continue                # it stood on the cancelled feature: it goes too
            obj = body.newObject(r["type"], r["name"]) if body is not None else doc.addObject(r["type"], r["name"])
            obj.Label = r["label"]
            if support:
                obj.AttachmentSupport = support
                obj.MapMode = r["mode"]
                obj.AttachmentOffset = r["offset"]
            else:
                obj.Placement = r["placement"]
            for p, v in r["keep"].items():
                try:
                    if p not in obj.PropertiesList:
                        continue
                    setattr(obj, p, v)
                except Exception as _fw_err:
                    _fw_log("refnest.py:keep", _fw_err)
            out.append(obj)
        doc.recompute()
    finally:
        doc.commitTransaction()
    return out
