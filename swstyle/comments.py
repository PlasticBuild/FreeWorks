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

import datetime
import getpass
import os
import tempfile

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

FOLDER_NAME = "Comments"
STATUSES = ("Description", "High Priority", "Low Priority", "Complete", "Reminder")
_windows = {}


def _mw():
    return Gui.getMainWindow()


# --------------------------------------------------------------------------- the text on the item
def text_of(obj):
    return str(getattr(obj, "Comment", "") or "")


def html_of(obj):
    return str(getattr(obj, "CommentHtml", "") or "")


def status_of(obj):
    s = str(getattr(obj, "CommentStatus", "") or "")
    return s if s in STATUSES else "Description"


def has_comment(obj):
    return bool(text_of(obj).strip()) or "<img" in html_of(obj)


def set_comment(obj, text, html="", status=None):
    """Keep the comment on the item (and the Comments folder in step)."""
    from . import parttools
    parttools.set_comment(obj, text)
    if "CommentHtml" not in obj.PropertiesList:
        obj.addProperty("App::PropertyString", "CommentHtml", "Comment", "The comment with its pictures")
    obj.CommentHtml = html or ""
    if status is not None:
        from . import featurerc
        featurerc.set_comment_status(obj, status)
    sync(obj.Document)


def delete_comment(obj):
    from . import parttools
    parttools.set_comment(obj, "")
    if "CommentHtml" in obj.PropertiesList:
        obj.CommentHtml = ""
    if "CommentStatus" in obj.PropertiesList:
        obj.CommentStatus = ""
    sync(obj.Document)


def commented(doc):
    return [o for o in doc.Objects if not is_entry(o) and not is_folder(o) and has_comment(o)]


# --------------------------------------------------------------------------- the Comments folder
class _Folder:
    Type = "FreeWorksComments"

    def __init__(self, obj):
        obj.Proxy = self

    def dumps(self):
        return None

    def loads(self, state):
        return None


class _Entry:
    Type = "FreeWorksComment"

    def __init__(self, obj):
        obj.Proxy = self
        obj.addProperty("App::PropertyLink", "Target", "Comment", "The item this comment is on")

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _note_icon(colour="#FFFFC0"):
    pix = QtGui.QPixmap(32, 32)
    pix.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(QtGui.QPen(QtGui.QColor("#8a6d00"), 2))
    p.setBrush(QtGui.QColor(colour))
    p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(5, 4), QtCore.QPointF(27, 4), QtCore.QPointF(27, 21),
                                   QtCore.QPointF(20, 28), QtCore.QPointF(5, 28)]))
    for y in (10, 15, 20):
        p.drawLine(QtCore.QPointF(9, y), QtCore.QPointF(23 if y < 20 else 17, y))
    p.end()
    return pix


def _folder_icon():
    pix = QtGui.QPixmap(32, 32)
    pix.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(QtGui.QPen(QtGui.QColor("#9a7b00"), 2))
    p.setBrush(QtGui.QColor("#f5d76e"))
    p.drawRect(QtCore.QRectF(3, 9, 26, 18))
    p.drawRect(QtCore.QRectF(3, 6, 11, 4))
    p.setBrush(QtGui.QColor("#FFFFC0"))
    p.drawRect(QtCore.QRectF(12, 13, 13, 11))
    p.end()
    return pix


def _icon_file(key, make):
    """FreeCAD wants an icon file (or XPM text) from getIcon: draw it once into the cache folder."""
    folder = os.path.join(App.getUserCachePath(), "FreeWorks")
    path = os.path.join(folder, "comment-%s.png" % key)
    if not os.path.exists(path):
        try:
            os.makedirs(folder, exist_ok=True)
            make().save(path, "PNG")
        except Exception as error:
            App.Console.PrintLog("FreeCAD: comment icon: %s\n" % error)
            return ""
    return path


class _FolderView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return _icon_file("folder", _folder_icon)

    def setupContextMenu(self, vobj, menu):
        doc = vobj.Object.Document
        menu.addAction("Show All Comments").triggered.connect(lambda: _later(lambda: show_all(doc)))
        a = menu.addAction("Delete All Comments")
        a.triggered.connect(lambda: _later(lambda: delete_all(doc, ask=True)))
        return True

    def onDelete(self, vobj, subs):
        _later(lambda d=vobj.Object.Document: delete_all(d, ask=False))
        return False

    def dumps(self):
        return None

    def loads(self, state):
        return None


class _EntryView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def _target(self, vobj):
        return getattr(vobj.Object, "Target", None)

    def getIcon(self):
        obj = getattr(self, "Object", None)
        target = getattr(obj, "Target", None) if obj is not None else None
        colour = "#FFFFC0"
        if target is not None:
            try:
                from . import fmtree
                colour = fmtree.comment_color(target) or colour
            except Exception as _fw_err:
                _fw_log("comments.py:217", _fw_err)
        return _icon_file(colour.strip("#").lower(), lambda: _note_icon(colour))

    def doubleClicked(self, vobj):
        t = self._target(vobj)
        if t is not None:
            _later(lambda: edit(t))
        return True

    def setupContextMenu(self, vobj, menu):
        t = self._target(vobj)
        if t is None:
            return False
        menu.addAction("Edit Comment...").triggered.connect(lambda: _later(lambda: edit(t)))

        def status():
            from . import featurerc
            featurerc.comment_status(t)
            sync(t.Document)
        menu.addAction("Comment Status...").triggered.connect(lambda: _later(status))
        menu.addAction("Go to Feature").triggered.connect(lambda: _later(lambda: _select(t)))
        menu.addAction("Delete Comment").triggered.connect(lambda: _later(lambda: _delete_one(t)))
        return True

    def onDelete(self, vobj, subs):
        t = self._target(vobj)
        if t is not None:
            _later(lambda: _delete_one(t))
        return False

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_folder(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None) == _Folder.Type


def is_entry(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None) == _Entry.Type


def folder(doc):
    return next((o for o in doc.Objects if is_folder(o)), None)


def _later(fn):
    QtCore.QTimer.singleShot(0, fn)


def _select(obj):
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(obj.Document.Name, obj.Name)


def sync(doc):
    """The Comments folder lists exactly the items that have a comment; it goes when none has."""
    if doc is None:
        return None
    items = commented(doc)
    fold = folder(doc)
    if not items:
        if fold is not None:
            for e in list(fold.Group):
                doc.removeObject(e.Name)
            doc.removeObject(fold.Name)
        return None
    if fold is None:
        fold = doc.addObject("App::DocumentObjectGroupPython", "Comments")
        _Folder(fold)
        fold.Label = FOLDER_NAME
        if App.GuiUp:
            _FolderView(fold.ViewObject)
    have = {}
    for e in list(fold.Group):
        t = getattr(e, "Target", None)
        if t is None or t not in items or t.Name in have:
            doc.removeObject(e.Name)
        else:
            have[t.Name] = e
    for t in items:
        e = have.get(t.Name)
        if e is None:
            e = doc.addObject("App::FeaturePython", "Comment")
            _Entry(e)
            e.Target = t
            if App.GuiUp:
                _EntryView(e.ViewObject)
            fold.addObject(e)
        label = entry_label(t)
        if e.Label != label:
            e.Label = label
        tip = text_of(t).strip()
        if e.Label2 != tip:
            e.Label2 = tip
    return fold


def entry_label(target):
    """The folder's row: the item's name and the comment's first line (labels must be unique)."""
    lines = [l.strip() for l in text_of(target).splitlines() if l.strip()]
    first = lines[0] if lines else "(picture)"
    if len(first) > 32:
        first = first[:31] + "..."
    return "%s: %s" % (target.Label, first)


def _delete_one(obj):
    doc = obj.Document
    doc.openTransaction("Delete Comment")
    try:
        delete_comment(obj)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()


def delete_all(doc, ask=True):
    items = commented(doc)
    if not items:
        sync(doc)
        return 0
    if ask and QtWidgets.QMessageBox.question(
            _mw(), "Delete All Comments", "Delete all %d comments?" % len(items),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No) != QtWidgets.QMessageBox.Yes:
        return 0
    doc.openTransaction("Delete All Comments")
    try:
        for o in items:
            from . import parttools
            parttools.set_comment(o, "")
            if "CommentHtml" in o.PropertiesList:
                o.CommentHtml = ""
            if "CommentStatus" in o.PropertiesList:
                o.CommentStatus = ""
        sync(doc)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    return len(items)


# --------------------------------------------------------------------------- the Comment window
def stamp():
    ""
    try:
        user = getpass.getuser()
    except Exception:
        user = ""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    return "%s %s" % (now, user) if user else now


def capture_view(width=480):
    """Capture Screen Image: the graphics area as a picture (a data: URL for the comment's HTML)."""
    if Gui.ActiveDocument is None or Gui.ActiveDocument.ActiveView is None:
        return None
    view = Gui.ActiveDocument.ActiveView
    path = os.path.join(tempfile.gettempdir(), "freeworks-comment-capture-%d.png" % os.getpid())     # pkg321: per session
    try:
        w, h = view.getSize()
        height = max(1, int(width * h / float(max(w, 1))))
        view.saveImage(path, width, height, "Current")
        data = QtCore.QFile(path)
        if not data.open(QtCore.QIODevice.ReadOnly):
            return None
        raw = bytes(data.readAll())
        data.close()
        import base64
        return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    except Exception as error:
        App.Console.PrintLog("FreeCAD: comment capture: %s\n" % error)
        return None
    finally:
        try:
            os.remove(path)
        except Exception as _fw_err:
            _fw_log("comments.py:391", _fw_err)


class CommentWindow(QtWidgets.QDialog):
    def __init__(self, obj):
        super().__init__(_mw())
        self.obj = obj
        self.setObjectName("SWCommentWindow")
        self.setWindowTitle("Comment - %s" % obj.Label)
        self.resize(460, 320)
        lay = QtWidgets.QVBoxLayout(self)
        bar = QtWidgets.QToolBar(self)
        bar.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        from . import simicons
        self.save_action = bar.addAction(simicons.picture("FW_Save"), "Save and Close")
        self.save_action.setObjectName("SWCommentSave")
        self.save_action.triggered.connect(self.save_and_close)
        bar.addSeparator()
        self.stamp_action = bar.addAction(simicons.picture("FW_Stamp"),
                                          "Date/Time Stamp")
        self.stamp_action.setObjectName("SWCommentStamp")
        self.stamp_action.triggered.connect(self.add_stamp)
        self.capture_action = bar.addAction(simicons.picture("FW_Capture"),
                                            "Capture Screen Image")
        self.capture_action.setObjectName("SWCommentCapture")
        self.capture_action.triggered.connect(self.add_capture)
        lay.addWidget(bar)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Status:"))
        self.status = QtWidgets.QComboBox()
        self.status.setObjectName("SWCommentStatus")
        self.status.addItems(list(STATUSES))
        self.status.setCurrentText(status_of(obj))
        row.addWidget(self.status, 1)
        lay.addLayout(row)
        self.text = QtWidgets.QTextEdit()
        self.text.setObjectName("SWCommentText")
        if html_of(obj):
            self.text.setHtml(html_of(obj))
        else:
            self.text.setPlainText(text_of(obj))
        lay.addWidget(self.text, 1)
        self._saved = (self.text.toPlainText(), self.status.currentText())
        self._done = False

    def add_stamp(self):
        self.text.textCursor().insertText(stamp() + "\n")

    def add_capture(self):
        url = capture_view()
        if url is None:
            return False
        self.text.textCursor().insertHtml('<img src="%s" width="320"/><br/>' % url)
        return True

    def _html(self):
        html = self.text.toHtml()
        return html if "<img" in html else ""

    def changed(self):
        return (self.text.toPlainText(), self.status.currentText()) != self._saved or bool(self._html()) != bool(html_of(self.obj))

    def save(self):
        doc = self.obj.Document
        doc.openTransaction("Comment")
        try:
            text = self.text.toPlainText().rstrip()
            if not text and "<img" in self._html():
                text = "(picture)"
            if text or self._html():
                set_comment(self.obj, text, self._html(), self.status.currentText())
            else:
                delete_comment(self.obj)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        self._saved = (self.text.toPlainText(), self.status.currentText())

    def save_and_close(self):
        self.save()
        self._done = True
        self.close()

    def closeEvent(self, event):
        if not self._done and self.changed():
            answer = QtWidgets.QMessageBox.question(
                self, "Comment", "Save the changes to the comment on %s?" % self.obj.Label,
                QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Discard | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.Save)
            if answer == QtWidgets.QMessageBox.Cancel:
                event.ignore()
                return
            if answer == QtWidgets.QMessageBox.Save:
                self.save()
        _windows.pop(id(self.obj), None)
        super().closeEvent(event)


def edit(obj):
    """Add Comment / Edit Comment: the Comment window for the item (one window per item)."""
    w = _windows.get(id(obj))
    try:
        if w is not None and w.isVisible():
            w.raise_()
            w.activateWindow()
            return w
    except RuntimeError as _fw_err:
        _fw_log("comments.py:495", _fw_err)
    w = CommentWindow(obj)
    _windows[id(obj)] = w
    w.show()
    return w


def add_comment():
    """The Add Comment command: on the one item picked (the part's own comment with none)."""
    picked = [s.Object for s in Gui.Selection.getSelectionEx()]
    if len(picked) != 1:
        QtWidgets.QMessageBox.information(_mw(), "Add Comment", "Select one feature, then click Add Comment.")
        return None
    return edit(picked[0])


class AllComments(QtWidgets.QDialog):
    """Show All Comments: every comment of the part, the item and its status first."""

    def __init__(self, doc):
        super().__init__(_mw())
        self.setObjectName("SWAllComments")
        self.setWindowTitle("Comments - %s" % doc.Label)
        self.resize(520, 360)
        lay = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTreeWidget()
        self.table.setObjectName("SWAllCommentsTable")
        self.table.setHeaderLabels(["Item", "Status", "Comment"])
        self.table.setRootIsDecorated(False)
        for o in commented(doc):
            item = QtWidgets.QTreeWidgetItem([o.Label, status_of(o), text_of(o).replace("\n", "  ")])
            item.setData(0, QtCore.Qt.UserRole, o.Name)
            self.table.addTopLevelItem(item)
        self.table.itemDoubleClicked.connect(lambda it, col: edit(doc.getObject(it.data(0, QtCore.Qt.UserRole))))
        lay.addWidget(self.table, 1)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.close)
        lay.addWidget(close, 0, QtCore.Qt.AlignRight)


def show_all(doc):
    w = AllComments(doc)
    w.show()
    _windows["all"] = w
    return w


# --------------------------------------------------------------------------- hooks
def _comment_menu(menu, shell, target, doc):
    """The Comment submenu of the tree's right-click: Add Comment, or Edit/Status/Delete when there is one."""
    from . import fmmenu
    if target is None:
        def part_comment():
            text, ok = QtWidgets.QInputDialog.getMultiLineText(_mw(), "Comment", "Comment on %s" % doc.Label,
                                                               doc.Comment)
            if ok:
                doc.Comment = text
        menu.addAction("Add Comment").triggered.connect(lambda: fmmenu._later(part_comment))
        return
    if has_comment(target):
        menu.addAction("Edit Comment...").triggered.connect(lambda: fmmenu._later(lambda: edit(target)))

        def status():
            from . import featurerc
            featurerc.comment_status(target)
            sync(target.Document)
        menu.addAction("Comment Status...").triggered.connect(lambda: fmmenu._later(status))
        menu.addAction("Delete Comment").triggered.connect(lambda: fmmenu._later(lambda: _delete_one(target)))
    else:
        menu.addAction("Add Comment").triggered.connect(lambda: fmmenu._later(lambda: edit(target)))


class _DocWatch:
    ""


    def _soon(self, doc):
        name = getattr(doc, "Name", None)

        def run():
            d = App.listDocuments().get(name) if name else None
            if d is None or getattr(d, "Restoring", False):
                return
            try:
                f = folder(d)
                if f is None and not commented(d):
                    return
                if f is not None and all(getattr(e, "Target", None) is not None for e in f.Group) \
                        and len(f.Group) == len(commented(d)):
                    return
                sync(d)
            except Exception as error:
                App.Console.PrintLog("FreeCAD: comments folder after a change: %s\n" % error)
        QtCore.QTimer.singleShot(0, run)

    def slotDeletedObject(self, obj):
        try:
            if is_entry(obj) or is_folder(obj):
                return
            if has_comment(obj):
                self._soon(obj.Document)
        except Exception as _fw_err:
            _fw_log("comments.py:597", _fw_err)

    def slotUndoDocument(self, doc):
        self._soon(doc)

    def slotRedoDocument(self, doc):
        self._soon(doc)


_doc_watch = None


def install():
    global _doc_watch
    if _doc_watch is None:
        _doc_watch = _DocWatch()
        try:
            App.addDocumentObserver(_doc_watch)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: comments observer: %s\n" % error)
    try:
        from . import parttools
        entry = parttools.COMMANDS.get("SWStyle_AddComment")
        if entry is not None:
            parttools.COMMANDS["SWStyle_AddComment"] = (entry[0], entry[1], add_comment, entry[3])
        parttools.add_comment = add_comment
        plain = parttools.set_comment
        if not getattr(plain, "_freeworks_synced", False):
            def synced(obj, text):
                plain(obj, text)
                try:
                    sync(obj.Document)
                except Exception as error:
                    App.Console.PrintLog("FreeCAD: comments folder: %s\n" % error)
            synced._freeworks_synced = True
            parttools.set_comment = synced
    except Exception as error:
        App.Console.PrintLog("FreeCAD: comments parttools: %s\n" % error)
    try:
        from . import fmmenu
        fmmenu._comment_menu = _comment_menu
        fmmenu._fallback_comment = edit
    except Exception as error:
        App.Console.PrintLog("FreeCAD: comments fmmenu: %s\n" % error)
