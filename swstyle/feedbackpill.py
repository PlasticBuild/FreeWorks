# SPDX-License-Identifier: LGPL-2.1-or-later
"""Donate | Feedback: a small pill-shaped split button on the status bar, bottom right, just left of the "?"
(Ati, 11-27; pillbar-1127: on the bar instead of floating above it).
Donate opens the donation page (the Ko-fi link at the top of the project's GitHub page), Feedback opens the
project's GitHub Issues page so users can leave feedback and report bugs; both in the default web browser.
Tools > Options > System Options > General > "Show Donate and Feedback button" turns it off (on at first)."""

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    Gui = None

DONATE_URL = "https://ko-fi.com/plasticbuild"
FEEDBACK_URL = "https://github.com/PlasticBuild/FreeWorks/issues"
KEY = "FeedbackButton"
NAME = "SWFeedbackPill"

_state = {"pill": None, "session_hidden": False}    # pillsession-1127; pillbar-1127
_FW_SEEN = set()


def _fw_log(site, err):
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            App.Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return


def _params():
    from . import paths
    return paths.params()


def enabled():
    try:
        return _params().GetBool(KEY, True)
    except Exception:
        return True


def set_enabled(on):
    """The Options row's write: kept, and the button shows or goes at once (turned on there, it also comes
    back from a right-click hide)."""
    _params().SetBool(KEY, bool(on))
    if on:
        _state["session_hidden"] = False
    apply()


def hide_for_session():
    """pillsession-1127: right-click > Hide this button: gone until FreeCAD restarts; the Options row stays on."""
    _state["session_hidden"] = True
    apply()


def open_url(url):
    """In the user's default web browser."""
    try:
        return QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))
    except Exception as _fw_err:
        _fw_log("feedbackpill.py:open", _fw_err)
        return False


def _dark():
    try:
        from . import style
        return bool(style.dark())
    except Exception:
        return False


def _sheet():
    if _dark():
        bg, hover, down, fg, edge = "#3a3d41", "#4a4e53", "#2c2e31", "#f0f0f0", "#5a5e63"
    else:
        bg, hover, down, fg, edge = "#ffffff", "#e8f0fb", "#d3e2f7", "#1f1f1f", "#b9bec5"
    return ("QFrame#%s { background: transparent; border: none; }"
            "QFrame#%s QPushButton { background: %s; color: %s; border: 1px solid %s; padding: 0px 10px;"
            " font-weight: 600; min-height: 16px; max-height: 18px; }"
            "QFrame#%s QPushButton:hover { background: %s; }"
            "QFrame#%s QPushButton:pressed { background: %s; }"
            "QFrame#%s QPushButton#SWFeedbackPillDonate { border-top-left-radius: 9px;"
            " border-bottom-left-radius: 9px; border-right: none; color: #d9480f; }"
            "QFrame#%s QPushButton#SWFeedbackPillFeedback { border-top-right-radius: 9px;"
            " border-bottom-right-radius: 9px; }"
            % (NAME, NAME, bg, fg, edge, NAME, hover, NAME, down, NAME, NAME))


class Pill(QtWidgets.QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName(NAME)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.donate = QtWidgets.QPushButton("Donate", self)
        self.donate.setObjectName("SWFeedbackPillDonate")
        self.donate.setToolTip("Support the project: opens the donation page in your web browser")
        self.feedback = QtWidgets.QPushButton("Feedback", self)
        self.feedback.setObjectName("SWFeedbackPillFeedback")
        self.feedback.setToolTip("Leave feedback or report a bug: opens the GitHub Issues page in your web browser")
        for b, url in ((self.donate, DONATE_URL), (self.feedback, FEEDBACK_URL)):
            b.setCursor(QtCore.Qt.PointingHandCursor)
            b.setFocusPolicy(QtCore.Qt.NoFocus)        # never takes the keyboard from the view or a PM
            b.clicked.connect(lambda checked=False, u=url: open_url(u))
            lay.addWidget(b)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.restyle()

    def restyle(self):
        self.setStyleSheet(_sheet())
        self.adjustSize()

    def _menu(self, pos):
        """Right-click: hide it (the same as the Options row)."""
        m = QtWidgets.QMenu(self)
        a = m.addAction("Hide this button")
        a.setToolTip("Hidden until FreeCAD restarts. To hide it for good: Tools > Options > General > "
                     "Show Donate and Feedback button")
        a.triggered.connect(hide_for_session)
        m.exec_(self.mapToGlobal(pos))
        m.deleteLater()

    def place(self):
        ""

        sb = _bar()
        if sb is None:
            return
        q = _quicktips()
        if self.parentWidget() is sb and not _between(sb, self, q):
            return
        if self.parentWidget() is sb:
            sb.removeWidget(self)
        k = None
        try:
            from . import dismissedicon
            k = dismissedicon._perm_index(sb, q) if q is not None else None
        except Exception as _fw_err:
            _fw_log("feedbackpill.py:index", _fw_err)
        if k is None:
            sb.addPermanentWidget(self)
        else:
            sb.insertPermanentWidget(k, self)
        self.show()                     # removeWidget hides it
        if not _state.get("bar_filter"):
            f = _state["bar_filter"] = _Keep(sb)
            sb.installEventFilter(f)


def _quicktips():
    try:
        from . import shell
        q = getattr(shell.shell(), "status_quicktips", None)
        return q if q is not None and q.parentWidget() is _bar() else None
    except Exception:
        return None


def _between(sb, pill, q):
    """A shown status-bar item between the pill and the ? (or the pill right of the ?)."""
    if q is None or not q.isVisible() or not pill.isVisible():
        return False
    a, b = pill.geometry().right(), q.geometry().left()
    if a > b:
        return True
    return any(w is not pill and w is not q and w.isVisible() and a < w.geometry().center().x() < b
               for w in sb.findChildren(QtWidgets.QWidget, options=QtCore.Qt.FindDirectChildrenOnly))


class _Keep(QtCore.QObject):
    """pillbar-1127: put the pill back next to the ? when the bar gets new items."""
    def eventFilter(self, obj, event):
        try:
            if event.type() in (QtCore.QEvent.ChildAdded, QtCore.QEvent.LayoutRequest, QtCore.QEvent.Resize):
                pill = _state.get("pill")
                if pill is not None and pill.isVisible() and not _state.get("placing"):
                    _state["placing"] = True
                    QtCore.QTimer.singleShot(0, _replace)
        except Exception as _fw_err:
            _fw_log("feedbackpill.py:keep", _fw_err)
        return False


def _replace():
    try:
        pill = _state.get("pill")
        if pill is not None and pill.isVisible():
            pill.place()
    except Exception as _fw_err:
        _fw_log("feedbackpill.py:replace", _fw_err)
    finally:
        QtCore.QTimer.singleShot(50, lambda: _state.update(placing=False))


def _bar():
    try:
        mw = Gui.getMainWindow()
        return mw.statusBar() if mw is not None else None
    except Exception:
        return None


def apply():
    """Show or hide the pill as the setting says; restyled for the current theme."""
    if Gui is None:
        return None
    try:
        mw = Gui.getMainWindow()
        if mw is None:
            return None
        pill = _state.get("pill")
        _dialog_pills()          # pilldialog-1127: the copies on open modal dialogs follow the main one
        if not enabled() or _state.get("session_hidden"):
            if pill is not None:
                pill.hide()
            return pill
        if pill is None:
            pill = _state["pill"] = Pill(mw)      # place() puts it on the bar
        pill.restyle()
        pill.place()
        pill.show()
        QtCore.QTimer.singleShot(0, _replace)
        return pill
    except Exception as _fw_err:
        _fw_log("feedbackpill.py:apply", _fw_err)
        return None


def install():
    """From startup: once the main window is up (after the look is applied)."""
    if Gui is None:
        return
    QtCore.QTimer.singleShot(1500, apply)
    try:
        f = _state["dialog_filter"] = _DialogWatch(QtWidgets.QApplication.instance())
        QtWidgets.QApplication.instance().installEventFilter(f)     # pilldialog-1127
    except Exception as _fw_err:
        _fw_log("feedbackpill.py:dialogs", _fw_err)
    try:
        from . import style
        style.signals.theme_changed.connect(lambda *_a: QtCore.QTimer.singleShot(0, apply))
    except Exception as _fw_err:
        _fw_log("feedbackpill.py:theme", _fw_err)


# --------------------------------------------------------------- pilldialog-1127: the pill on modal dialogs
# An application-modal dialog blocks every click on the main window, the status-bar pill too: these dialogs carry
# their own copy in their bottom row.
DIALOGS = {"SWNewDocument": "SWNewSwitch"}       # dialog objectName: the bottom-row button the pill sits right of


class DialogPill(Pill):
    def place(self):
        dlg = self.parentWidget()
        if dlg is None:
            return
        self.adjustSize()
        anchor = dlg.findChild(QtWidgets.QAbstractButton, DIALOGS.get(dlg.objectName(), ""))
        if anchor is not None and anchor.isVisible():
            g = anchor.geometry()
            x, y = g.right() + 12, g.center().y() - self.height() // 2
        else:
            x, y = 16, dlg.height() - self.height() - 14
        self.move(max(0, x), max(0, y))
        self.raise_()


def _dialog_pills():
    """Show, hide and restyle the dialog copies as the main pill is."""
    on = enabled() and not _state.get("session_hidden")
    for p in list(_state.setdefault("dialog_pills", [])):
        try:
            if not _alive(p):
                _state["dialog_pills"].remove(p)
                continue
            if on:
                p.restyle(); p.place(); p.show()
            else:
                p.hide()
        except Exception as _fw_err:
            _fw_log("feedbackpill.py:dialog pill", _fw_err)


def _alive(w):
    try:
        import shiboken6
        return shiboken6.isValid(w)
    except Exception:
        return True


def _on_dialog(dlg):
    if dlg.findChild(QtWidgets.QFrame, NAME) is None:
        p = DialogPill(dlg)
        _state.setdefault("dialog_pills", []).append(p)
        dlg.installEventFilter(_state["dialog_filter"])
    _dialog_pills()


class _DialogWatch(QtCore.QObject):
    def eventFilter(self, obj, event):
        try:
            t = event.type()
            if t in (QtCore.QEvent.Show, QtCore.QEvent.Resize) and isinstance(obj, QtWidgets.QDialog) \
                    and obj.objectName() in DIALOGS:
                QtCore.QTimer.singleShot(0, lambda d=obj: _alive(d) and _on_dialog(d))
        except Exception as _fw_err:
            _fw_log("feedbackpill.py:dialog watch", _fw_err)
        return False
