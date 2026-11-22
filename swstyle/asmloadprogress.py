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

import os
import time

import FreeCAD as App

PARAM = "User parameter:BaseApp/Preferences/Mod/SWStyle/LoadProgress"
SHOW_AFTER = 0.5        # seconds: a quick open shows nothing
PAINT_EVERY = 0.1
KEEP_MS = 2500          # the finished window stays this long
STAGES = ("Reading", "Loading components", "Rebuilding and display")

S = {"on": None}        # the open going on now
last = {}               # the last finished open: name, total, stages, files (for the checks)
OPENS = {}              # document name -> its open (as last): Performance Evaluation's open time


def _p():
    return App.ParamGet(PARAM)


def enabled():
    return _p().GetBool("Show", True)


def _expected(path):
    try:
        return _p().GetInt("Files_" + str(abs(hash(os.path.normcase(path))) % 10 ** 9), 0)
    except Exception as _fw_err:
        _fw_log("asmloadprogress.py:55", _fw_err)
        return 0


def _remember(path, files):
    try:
        _p().SetInt("Files_" + str(abs(hash(os.path.normcase(path))) % 10 ** 9), files)
    except Exception as _fw_err:
        _fw_log("asmloadprogress.py:61", _fw_err)


class _Session:
    def __init__(self, doc):
        self.doc = doc.Name
        self.label = doc.Label or doc.Name
        self.path = doc.FileName        # set a moment later on an open; empty on a new document
        self.t0 = time.time()
        self.stage = 0
        self.marks = [self.t0]          # start time of each stage
        self.objects = 0
        self.files = 0
        self.expect = 0
        self.assembly = False
        self.win = None
        self.painted = 0.0
        try:
            from PySide import QtCore
            QtCore.QTimer.singleShot(0, finish)     # runs once FreeCAD is done and the screen gets a turn
        except Exception as _fw_err:
            _fw_log("asmloadprogress.py:82", _fw_err)

    def opening(self):
        """True for a file being opened (a new document has no file name)."""
        if not self.path:
            try:
                self.path = App.getDocument(self.doc).FileName
            except Exception as _fw_err:
                _fw_log("asmloadprogress.py:92", _fw_err)
                return False
            if self.path:
                self.expect = _expected(self.path)
                self.label = os.path.splitext(os.path.basename(self.path))[0]
        return bool(self.path)

    def go(self, stage):
        while self.stage < stage:
            self.stage += 1
            self.marks.append(time.time())

    def times(self, end=None):
        end = end or time.time()
        marks = self.marks + [end]
        return [marks[i + 1] - marks[i] for i in range(len(self.marks))]

    def lines(self, done=False):
        now = time.time()
        rows = []
        t = self.times(now)
        for i in range(self.stage + 1):
            name = STAGES[i]
            if i == 0:
                name = "Reading %s: %d objects" % (os.path.basename(self.path) or self.label, self.objects)
            elif i == 1:
                name = "Loading components: %d%s files" % (self.files, (" of %d" % self.expect) if self.expect else "")
            state = "%.1f s" % t[i] if (i < self.stage or done) else "..."
            rows.append((name, state))
        return rows

    def paint(self, force=False, done=False):
        now = time.time()
        if not self.assembly or not enabled() or not self.opening():
            return
        if self.win is None and now - self.t0 < SHOW_AFTER and not force:
            return
        if not force and now - self.painted < PAINT_EVERY:
            return
        self.painted = now
        try:
            if self.win is None:
                self.win = _Window(os.path.basename(self.path))
            self.win.show_rows(self.lines(done), now - self.t0, done)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: open progress: %s\n" % error)


class _Window:
    def __init__(self, label):
        from PySide import QtCore, QtWidgets
        import FreeCADGui as Gui
        mw = Gui.getMainWindow()
        w = self.w = QtWidgets.QFrame(mw, QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint)
        w.setObjectName("FW_OpenProgress")
        w.setFrameShape(QtWidgets.QFrame.StyledPanel)
        lay = QtWidgets.QVBoxLayout(w)
        self.title = QtWidgets.QLabel("Opening %s" % label)
        self.title.setObjectName("FW_OpenProgressTitle")
        f = self.title.font()
        f.setBold(True)
        self.title.setFont(f)
        lay.addWidget(self.title)
        self.grid = QtWidgets.QGridLayout()
        lay.addLayout(self.grid)
        self.rows = []
        self.elapsed = QtWidgets.QLabel("")
        self.elapsed.setObjectName("FW_OpenProgressElapsed")
        lay.addWidget(self.elapsed)
        w.setMinimumWidth(340)
        w.adjustSize()
        try:
            g = mw.geometry()
            w.move(g.center().x() - w.width() // 2, g.center().y() - w.height() // 2)
        except Exception as _fw_err:
            _fw_log("asmloadprogress.py:164", _fw_err)
        w.show()

    def show_rows(self, rows, elapsed, done):
        from PySide import QtWidgets
        while len(self.rows) < len(rows):
            a, b = QtWidgets.QLabel(""), QtWidgets.QLabel("")
            n = len(self.rows)
            self.grid.addWidget(a, n, 0)
            self.grid.addWidget(b, n, 1)
            self.rows.append((a, b))
        for (a, b), (name, state) in zip(self.rows, rows):
            a.setText(name)
            b.setText(state)
        self.elapsed.setText(("Opened in %.1f s" if done else "Time: %.1f s") % elapsed)
        self.w.adjustSize()
        self.w.repaint()

    def texts(self):
        return [(a.text(), b.text()) for a, b in self.rows] + [self.elapsed.text()]

    def close(self):
        try:
            self.w.close()
            self.w.deleteLater()
        except Exception as _fw_err:
            _fw_log("asmloadprogress.py:190", _fw_err)


_shown = []        # finished windows waiting to close


def _close_done():
    while _shown:
        _shown.pop(0).close()


def finish():
    s = S["on"]
    if s is None:
        return
    try:
        busy = any(d.Restoring for d in App.listDocuments().values())
    except Exception:
        busy = False
    if busy:
        # FreeCAD's own progress bar gives the screen turns while it reads: not done yet
        from PySide import QtCore
        QtCore.QTimer.singleShot(50, finish)
        return
    S["on"] = None
    try:
        App.getDocument(s.doc)
    except Exception:
        return          # the open failed
    if not s.opening():
        return          # a new document, not an open
    s.go(2)
    try:
        from PySide import QtWidgets
        QtWidgets.QApplication.processEvents()      # the first draw belongs to the open
    except Exception as _fw_err:
        _fw_log("asmloadprogress.py:226", _fw_err)
    end = time.time()
    t = s.times(end)
    total = end - s.t0
    _remember(s.path, s.files)
    last.clear()
    last.update(name=s.label, total=total, stages=dict(zip(("reading", "components", "display"), t)),
                files=s.files, objects=s.objects, assembly=s.assembly, window=s.win is not None)
    OPENS[s.doc] = dict(last)
    if not s.assembly:
        return
    msg = "Opened %s in %.1f s: reading %.1f s, components %.1f s (%d files), display %.1f s" % (
        s.label, total, t[0], t[1], s.files, t[2])
    last["message"] = msg
    if total >= SHOW_AFTER:
        App.Console.PrintMessage("FreeCAD: %s\n" % msg)
        try:
            import FreeCADGui as Gui
            Gui.getMainWindow().statusBar().showMessage(msg, 15000)
        except Exception as _fw_err:
            _fw_log("asmloadprogress.py:246", _fw_err)
    if s.win is not None:
        s.paint(force=True, done=True)
        last["texts"] = s.win.texts()
        try:
            from PySide import QtCore
            _shown.append(s.win)
            QtCore.QTimer.singleShot(KEEP_MS, _close_done)
        except Exception:
            s.win.close()


class _Watch:
    def slotCreatedDocument(self, doc):
        s = S["on"]
        if s is not None and time.time() - s.t0 > 600:
            S["on"] = s = None          # never finished (no screen turn came): start over
        try:
            if s is None or not s.opening():
                S["on"] = _Session(doc)     # (a new document before it was no open: this one may be)
            elif doc.Name != s.doc:
                s.go(1)
                s.files += 1
                s.paint()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: open progress: %s\n" % error)

    def slotCreatedObject(self, obj):
        s = S["on"]
        if s is None:
            return
        try:
            if obj.Document.Name == s.doc and s.stage == 0:
                s.objects += 1
                if obj.TypeId == "Assembly::AssemblyObject":
                    s.assembly = True
                s.paint()
        except Exception as _fw_err:
            _fw_log("asmloadprogress.py:284", _fw_err)


_watch = []


def install():
    if not _watch:
        _watch.append(_Watch())
        App.addDocumentObserver(_watch[0])
