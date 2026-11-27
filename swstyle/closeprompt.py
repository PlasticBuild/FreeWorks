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


import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

SAVE, DONT_SAVE, CANCEL = "save", "dont", "cancel"

_filter = None
# checks set this to a callable(docs) -> (answer, ticked docs) instead of showing the box
answer_hook = None


def _modified(docs=None):
    out = []
    for doc in (docs if docs is not None else App.listDocuments().values()):
        try:
            gdoc = Gui.getDocument(doc.Name)
        except Exception:
            continue
        if gdoc is not None and gdoc.Modified:
            out.append(doc)
    return out


def _name(doc):
    return os.path.basename(doc.FileName) if doc.FileName else doc.Label


def _link_blue():

    try:
        from . import style
        if style.dark():
            return "#a8c7fa"
    except Exception as _fw_err:
        _fw_log("closeprompt.py:link_blue", _fw_err)
    return "#1c5aa6"


class SaveModifiedBox(QtWidgets.QDialog):
    ""






    def __init__(self, docs, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("FW_SaveModified")
        self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint)
        self.answer = CANCEL
        self.docs = list(docs)
        self.buttons = {}
        self.list = None
        if len(self.docs) == 1:
            self._task_box()
        else:
            self._list_box()

    # one document: the Windows task box
    def _task_box(self):
        self.setWindowTitle("FreeCAD")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        body = QtWidgets.QWidget()
        body.setObjectName("FW_SaveModifiedBody")
        top = QtWidgets.QHBoxLayout(body)
        top.setContentsMargins(12, 12, 12, 12)
        icon = QtWidgets.QLabel()
        from . import msgicons
        icon.setPixmap(msgicons.pixmap("warning", 32))
        icon.setAlignment(QtCore.Qt.AlignTop)
        top.addWidget(icon)
        text = QtWidgets.QVBoxLayout()
        head = QtWidgets.QLabel("Save modified documents")
        head.setObjectName("FW_SaveModifiedHead")
        font = head.font()
        font.setPointSizeF(font.pointSizeF() * 1.3)
        head.setFont(font)
        head.setStyleSheet("color: %s;" % _link_blue())
        text.addWidget(head)
        note = QtWidgets.QLabel("One or more documents being closed as a result of this operation have been modified.")
        note.setWordWrap(True)
        text.addWidget(note)
        for key, label, sub in ((SAVE, "&Save all", "All modified documents will be saved."),
                                (DONT_SAVE, "Do&n't Save", "All changes to unsaved documents will be lost.")):
            button = QtWidgets.QCommandLinkButton(label, sub)
            button.setStyleSheet("QCommandLinkButton { color: %s; }" % _link_blue())
            button.setObjectName("FW_SaveModified_" + key)
            button.clicked.connect(lambda checked=False, k=key: self._pick(k))
            text.addWidget(button)
            self.buttons[key] = button
        top.addLayout(text, 1)
        lay.addWidget(body)
        foot = QtWidgets.QWidget()
        foot.setObjectName("FW_SaveModifiedFooter")
        foot.setAutoFillBackground(True)
        pal = foot.palette()
        pal.setColor(QtGui.QPalette.Window, pal.color(QtGui.QPalette.Window).darker(108))
        foot.setPalette(pal)
        row = QtWidgets.QHBoxLayout(foot)
        row.setContentsMargins(12, 8, 12, 8)
        row.addStretch(1)
        cancel = QtWidgets.QPushButton("Cancel")
        cancel.setObjectName("FW_SaveModified_" + CANCEL)
        cancel.clicked.connect(lambda checked=False: self._pick(CANCEL))
        row.addWidget(cancel)
        self.buttons[CANCEL] = cancel
        lay.addWidget(foot)
        self.buttons[SAVE].setFocus()
        self.setMinimumWidth(420)

    # closefit-1120: the wrapped note and the command links' sub-lines are height-for-width; Qt does not
    # pass that up to a window, so with Windows' taller command links or a large font the box opened
    # shorter than its contents and Don't Save and Cancel were cut off (PC test, 433 x 318 box)
    def _fit_height(self):
        lay = self.layout()
        if lay is None or getattr(self, "_fitting", False):
            return
        self._fitting = True
        try:
            need = max(lay.totalHeightForWidth(self.width()) if lay.hasHeightForWidth() else 0,
                       lay.totalMinimumSize().height())
            if need > 0:
                self.setMinimumHeight(need)
                if self.height() < need:
                    self.resize(self.width(), need)
        finally:
            self._fitting = False

    def _place(self):
        """closefit-1120: centred on the main window and wholly on that window's screen (PC test: the box opened
        at the lower right of a 1440 x 900 monitor with Don't Save half off and Cancel off the screen)."""
        try:
            owner = self.parentWidget().window() if self.parentWidget() is not None else None
            screen = (owner.screen() if owner is not None else None) or self.screen()                 or QtGui.QGuiApplication.primaryScreen()
            room = screen.availableGeometry()
            frame = self.frameGeometry()
            extra_w, extra_h = frame.width() - self.width(), frame.height() - self.height()
            w = min(self.width(), room.width() - extra_w)
            h = min(self.height(), room.height() - extra_h)
            if (w, h) != (self.width(), self.height()):
                self.resize(w, h)
                frame = self.frameGeometry()
            centre = owner.frameGeometry().center() if owner is not None and owner.isVisible() else room.center()
            if not room.contains(centre):
                centre = room.center()
            x = centre.x() - frame.width() // 2
            y = centre.y() - frame.height() // 2
            x = max(room.left(), min(x, room.left() + room.width() - frame.width()))
            y = max(room.top(), min(y, room.top() + room.height() - frame.height()))
            self.move(x, y)          # a window's move() places its frame
        except Exception as _fw_err:
            _fw_log("closeprompt.py:place", _fw_err)

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_height()
        self._place()
        QtCore.QTimer.singleShot(0, self._place)        # again once the window manager has given the frame

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QtCore.QTimer.singleShot(0, self._fit_height)

    # several documents: the list
    def _list_box(self):
        self.setWindowTitle("Save Modified Documents")
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("The following documents have been modified."))
        self.list = QtWidgets.QTreeWidget()
        self.list.setObjectName("FW_SaveModifiedList")
        self.list.setRootIsDecorated(False)
        self.list.setColumnCount(4)
        self.list.setHeaderLabels(["", "Filename", "Read-only", "In Use By"])
        self.list.headerItem().setIcon(0, QtGui.QIcon(":/icons/document-save.svg"))
        for doc in self.docs:
            item = QtWidgets.QTreeWidgetItem(["", _file_name(doc), "Yes" if _read_only(doc) else "", ""])
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(0, QtCore.Qt.Checked)
            item.setIcon(1, _doc_icon())
            item.setToolTip(1, doc.FileName or "Not saved yet")
            self.list.addTopLevelItem(item)
        head = self.list.header()
        head.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        head.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        head.setDefaultAlignment(QtCore.Qt.AlignCenter)
        lay.addWidget(self.list, 1)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        for key, label in ((SAVE, "Save All"), (DONT_SAVE, "Don't Save"), (CANCEL, "Cancel"), ("help", "Help")):
            button = QtWidgets.QPushButton(label)
            button.setObjectName("FW_SaveModified_" + key)
            if key == "help":
                button.clicked.connect(self._help)
            else:
                button.clicked.connect(lambda checked=False, k=key: self._pick(k))
            row.addWidget(button)
            self.buttons[key] = button
        self.buttons[SAVE].setDefault(True)
        lay.addLayout(row)
        self.list.itemChanged.connect(self._ticks)
        self.resize(560, 340)

    def _help(self):
        QtWidgets.QMessageBox.information(
            self, "Save Modified Documents",
            "Save All saves every ticked document, then closes.\n"
            "Untick a document to close it without saving (the button reads Save Selected).\n"
            "Don't Save closes every document without saving.\n"
            "Cancel keeps everything open.")

    def _ticks(self, *args):
        ticked = len(self.ticked())
        self.buttons[SAVE].setText("Save All" if ticked == len(self.docs) else "Save Selected")
        self.buttons[SAVE].setEnabled(ticked > 0)

    def ticked(self):
        if self.list is None:
            return list(self.docs)
        return [d for i, d in enumerate(self.docs)
                if self.list.topLevelItem(i).checkState(0) == QtCore.Qt.Checked]

    def _pick(self, key):
        self.answer = key
        self.chosen = self.ticked()     # read now: the box can be gone by the time exec() returns
        self.accept() if key != CANCEL else self.reject()


def _file_name(doc):
    ""
    return os.path.basename(doc.FileName) if doc.FileName else doc.Label + ".FCStd"


def _read_only(doc):
    try:
        from . import filecmds
        if filecmds.is_read_only(doc):        # open110: opened read-only
            return True
    except Exception as _fw_err:
        _fw_log("closeprompt.py:_read_only", _fw_err)
    try:
        return bool(doc.FileName) and os.path.exists(doc.FileName) and not os.access(doc.FileName, os.W_OK)
    except Exception:
        return False


def _doc_icon():
    try:
        return QtGui.QIcon(Gui.getIcon("PartDesign_Body")) if hasattr(Gui, "getIcon") else QtGui.QIcon()
    except Exception:
        return QtGui.QIcon()


def ask(docs):
    """(answer, docs to save) for these changed documents."""
    if answer_hook is not None:
        return answer_hook(docs)
    from . import teardown
    box = SaveModifiedBox(docs)
    box.chosen = None
    box.exec()
    # FreeCAD going down while the box was up (a closing script, Windows logging off) deletes it
    # with the main window: its tick list is gone then, reading it crashed (PC exit crash, review 1119)
    answer, chosen = box.answer, box.chosen
    if teardown.alive(box):
        if chosen is None:
            chosen = box.ticked()
        box.deleteLater()
    return answer, (chosen if chosen is not None else ([] if answer != SAVE else list(docs)))


def _save(doc):
    ""
    try:
        try:
            from . import drawings
            holding = drawings.temp_path(doc)      # a new drawing in its holding file (drawings-land24)
        except Exception:
            holding = None
        if holding:
            return bool(drawings.save_as_first(doc))
        try:
            from . import filecmds
            read_only = bool(doc.FileName) and filecmds.is_read_only(doc)
        except Exception:
            read_only = False
        if read_only:
            # open110: a read-only document is not saved over (its row says Read-only: Yes); say so, keep closing
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Save", filecmds.read_only_message(doc))
            return True
        if doc.FileName:
            from . import filelock      # fh163: a file changed on disk after it was opened here: ask first
            if not filelock.save_over_ok(doc):
                return False
            doc.save()
            return True
        from . import saveas
        return saveas.save_as(doc) is not None
    except Exception as error:
        QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Save", "%s was not saved:\n%s" % (_name(doc), error))
        return False


def _cancel_button():
    ""
    mw = Gui.getMainWindow()
    for box in mw.findChildren(QtWidgets.QDialogButtonBox):
        button = box.button(QtWidgets.QDialogButtonBox.Cancel)
        if button is not None and button.isEnabled() and box.window() is mw:
            return button
    return None


def _leave_edit(docs):
    ""





    for doc in (docs if docs is not None else App.listDocuments().values()):
        try:
            gdoc = Gui.getDocument(doc.Name)
            vp = gdoc.getInEdit() if gdoc is not None else None
            if vp is None:
                continue
            obj = getattr(vp, "Object", None)
            if obj is not None and not obj.TypeId.startswith("Sketcher::"):
                button = _cancel_button()
                if button is not None:
                    button.click()
                    QtWidgets.QApplication.processEvents()
            if gdoc.getInEdit() is not None:
                gdoc.resetEdit()
        except Exception as _fw_err:
            _fw_log("closeprompt.py:271", _fw_err)


def _feature_open(doc):
    """A feature (not a sketch) is being made or edited in this document."""
    try:
        vp = Gui.getDocument(doc.Name).getInEdit()
        obj = getattr(vp, "Object", None) if vp is not None else None
        return obj is not None and not obj.TypeId.startswith("Sketcher::")
    except Exception:
        return False


_SETTLING = [False]


def settle(docs):
    """Ask about the changed documents among docs and act on the answer; False = stop closing.
    A second close while the box is up (a script closing again) waits for the first: no box in a box."""
    if _SETTLING[0]:
        return False
    _SETTLING[0] = True
    try:
        return _settle(docs)
    finally:
        _SETTLING[0] = False


def _settle(docs):
    changed = _modified(docs)
    answer, chosen = (None, [])
    if changed:
        answer, chosen = ask(changed)
        if answer == CANCEL:
            return False
    _leave_edit(docs)
    late = [d for d in _modified(docs) if d not in changed]
    if late:
        # only leaving the edit changed these: ask about them now (or apply the answer already given)
        if answer is None:
            answer, chosen = ask(late)
            if answer == CANCEL:
                return False
        else:
            chosen = list(chosen) + late
        changed = changed + late
    if answer == SAVE:
        for doc in chosen:
            if not _save(doc):
                return False
    for doc in changed:
        try:
            gdoc = Gui.getDocument(doc.Name)
        except Exception:
            continue
        if gdoc is not None:
            gdoc.Modified = False
    return True


def _doc_of(sub):
    """The document whose 3D view sits in this MDI sub-window, and whether it is that document's last one."""
    for name, doc in App.listDocuments().items():
        try:
            gdoc = Gui.getDocument(name)
        except Exception:
            continue                 # closing already
        if gdoc is None:
            continue
        views = []
        for view in gdoc.mdiViewsOfType("Gui::View3DInventor"):
            try:
                views.append(view.graphicsView())
            except Exception as _fw_err:
                _fw_log("closeprompt.py:331", _fw_err)
        mine = [w for w in views if w is not None and sub.isAncestorOf(w)]
        if mine:
            return doc, len(views) == len(mine)
    return None, False


def close_all():
    """Window > Close All: one prompt for every changed document, then the windows close."""
    if settle(None):
        Gui.runCommand("Std_CloseAllWindows")


class _CloseFilter(QtCore.QObject):
    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() != QtCore.QEvent.Close:
            return False
        try:
            if obj is Gui.getMainWindow():
                if not settle(None):
                    event.ignore()
                    return True
                return False
            doc, last = _doc_of(obj)
            if doc is not None and _feature_open(doc):

                event.ignore()
                return True
            if doc is not None and last and not settle([doc]):
                event.ignore()
                return True
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: close prompt: %s\n" % error)
        return False


def _watch(*args):
    from . import windowmenu
    area = windowmenu.mdi()
    if area is None:
        return
    for sub in area.subWindowList():
        if not isinstance(sub, QtWidgets.QMdiSubWindow):
            continue        # mdiguard-1126: a stale wrapper PySide hands back while a drawing opens
        if not sub.property("fw_closeprompt"):
            sub.setProperty("fw_closeprompt", True)
            sub.installEventFilter(_filter)


def install():
    global _filter
    if _filter is not None:
        return
    mw = Gui.getMainWindow()
    _filter = _CloseFilter(mw)
    mw.installEventFilter(_filter)
    from . import windowmenu
    area = windowmenu.mdi()
    if area is not None:
        area.subWindowActivated.connect(_watch)
    _watch()
