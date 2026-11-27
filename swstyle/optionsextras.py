# SPDX-License-Identifier: LGPL-2.1-or-later
""

















_FW_SEEN = set()



def _alive(obj):
    """False for None or an object deleted under its wrapper (teardown.alive, review 1119)."""
    from . import teardown
    return teardown.alive(obj)


def _doc_alive(doc):
    from . import teardown
    return teardown.doc_alive(doc)


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return

import json
import os
import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import paths

Qt = QtCore.Qt


SPIN_METRIC, SPIN_ENGLISH, SPIN_ANGLE = "SpinLengthMetric", "SpinLengthEnglish", "SpinAngle"
DEFAULTS = {SPIN_METRIC: 10.0, SPIN_ENGLISH: 0.1, SPIN_ANGLE: 1.0}
REMIND, REMIND_MINUTES = "SaveReminder", "SaveReminderMinutes"
OPEN_LAST, LAST_FILES = "OpenLastDocuments", "LastDocuments"
SKETCH_ON_NEW = "SketchOnNewPart"

ENGLISH_UNITS = {"in", "inch", "\"", "ft", "'", "thou", "mil", "yd", "mi"}
ANGLE_UNITS = {"°", "deg"}
MM_PER_INCH = 25.4


def _p():
    return paths.params()


# ---------------------------------------------------------------- spin box increments
def increment(kind):
    ""

    key = {"metric": SPIN_METRIC, "english": SPIN_ENGLISH, "angle": SPIN_ANGLE}[kind]
    step = _p().GetFloat(key, DEFAULTS[key])
    return step * MM_PER_INCH if kind == "english" else step


def kind_of(box):
    """'metric', 'english', 'angle' or None for a spin box."""
    if quantity_box(box):
        q = box.property("value")
        unit = getattr(q, "Unit", None)
        shown = (box.property("unit") or "").strip()
        if unit == App.Units.Angle:
            return "angle"
        if unit == App.Units.Length:
            return "english" if shown in ENGLISH_UNITS else "metric"
        return None
    if not isinstance(box, QtWidgets.QDoubleSpinBox):
        return None
    if _mm_valued(box):
        return "english" if box._unit()[1] in ENGLISH_UNITS else "metric"
    unit = box.suffix().strip()
    if unit == "mm":
        return "metric"
    if unit in ("in", "\""):
        return "english"
    if unit in ANGLE_UNITS:
        return "angle"
    return None


def _mm_valued(box):
    """A length box shown in the document's unit with its value kept in mm (filletpm's)."""
    return hasattr(box, "text_of") and hasattr(box, "parse") and hasattr(box, "_unit")


def apply_step(box):
    ""

    kind = kind_of(box)
    if kind is None:
        return None
    base = box.property("swStepBase")
    if base is None:
        base = float(box.property("singleStep") or 0.0)
        box.setProperty("swStepBase", base)
    if abs(base - 1.0) > 1e-9 and not (kind == "angle" and abs(base - 10.0) < 1e-9):

        return None
    step = increment(kind)
    if quantity_box(box):
        box.setProperty("singleStep", step)
    else:
        want = step / MM_PER_INCH if kind == "english" and not _mm_valued(box) else step
        if abs(box.singleStep() - want) > 1e-9:    # pkg106: setSingleStep re-renders the edit,
            box.setSingleStep(want)                # which throws away a value being typed
    return step


def quantity_box(box):
    """FreeCAD's quantity box, or one made from it (the task panels' PrefQuantitySpinBox)."""
    return box.inherits("Gui::QuantitySpinBox")


def _spin_box_of(widget):
    # sweep-1121: focusChanged can hand a stale wrapper (a QSpacerItem) for a widget just deleted: not a widget
    while isinstance(widget, QtWidgets.QWidget):
        if isinstance(widget, QtWidgets.QAbstractSpinBox):
            return widget
        widget = widget.parentWidget()
    return None


def _focus_changed(_old, now):
    box = _spin_box_of(now)
    if box is None:
        return
    _apply_quietly(box)
    # a task panel gives its first box the focus before it sets the box's value and unit
    QtCore.QTimer.singleShot(100, lambda: _apply_quietly(box))


def _apply_quietly(box):
    try:
        apply_step(box)
    except (RuntimeError, AttributeError, TypeError) as _fw_err:
        _fw_log("optionsextras.py:139", _fw_err)


# ---------------------------------------------------------------- unsaved document reminder
def reminder_minutes():
    return max(1, _p().GetInt(REMIND_MINUTES, 20))


def dismiss_seconds():
    ""

    g = App.ParamGet("User parameter:BaseApp/Preferences/NotificationArea")
    if not g.GetBool("AutoRemoveUserNotifications", True):
        return 0
    return max(1, g.GetInt("NotificationTime", NOTE_SECONDS))


NOTE_SECONDS = 5


def default_note_seconds():
    ""
    g = App.ParamGet("User parameter:BaseApp/Preferences/NotificationArea")
    if g.GetInt("NotificationTime", -1) == -1:
        g.SetInt("NotificationTime", NOTE_SECONDS)
        return True
    return False


class _SavedWatch:
    """Save or Save As closes the note at once instead of at the next 30 s tick."""

    def __init__(self, reminder):
        self.reminder = reminder

    def slotFinishSaveDocument(self, doc, filename):
        name = doc.Name
        QtCore.QTimer.singleShot(0, lambda: self.reminder.saved(name))

    def slotDeletedDocument(self, doc):
        QtCore.QTimer.singleShot(0, self.reminder.tick)


class SaveReminder(QtCore.QObject):
    """Watches the open documents; a document changed and not saved for N minutes gets a note."""

    def __init__(self):
        super().__init__()
        self.since = {}     # document name -> when it was first seen changed and unsaved
        self.later = {}     # document name -> when Remind Me Later asked to be reminded again
        self.note = None
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(30000)
        self.timer.timeout.connect(self.tick)
        self.observer = _SavedWatch(self)
        try:
            App.addDocumentObserver(self.observer)
        except Exception as _fw_err:
            _fw_log("optionsextras.py:176", _fw_err)

    @staticmethod
    def _modified(name):
        gdoc = Gui.getDocument(name)
        return bool(gdoc is not None and gdoc.Modified)

    def due(self, now=None):
        """The names of the documents to remind about now."""
        now = time.time() if now is None else now
        if not _p().GetBool(REMIND, True):
            self.since.clear()
            self.later.clear()
            return []
        out = []
        names = set(App.listDocuments())
        for name in list(self.since):
            if name not in names:
                self.since.pop(name, None)
                self.later.pop(name, None)
        for name in sorted(names):
            if not self._modified(name):
                self.since.pop(name, None)
                self.later.pop(name, None)
                continue
            since = self.since.setdefault(name, now)
            if now >= self.later.get(name, since + reminder_minutes() * 60):
                out.append(name)
        return out

    def saved(self, name):
        """The document was just saved (Save, Save As, Save All): its note goes now, whatever the
        GUI's Modified flag says a moment later (EX6-R3: the note stayed after Save As)."""
        self.since.pop(name, None)
        self.later.pop(name, None)
        if self.note is not None and name in self.note.names:
            rest = [n for n in self.note.names if n != name and self._modified(n)]
            self.close_note()
            if rest:
                self.show_note(rest)

    def tick(self, now=None):
        names = self.due(now)
        if not names:
            if self.note is not None and not any(self._modified(n) for n in self.note.names):
                self.close_note()
            return
        if self.note is None:
            self.show_note(names)

    def show_note(self, names):
        mw = Gui.getMainWindow()
        self.note = ReminderNote(mw, names, self)
        self.note.show_at_corner()
        seconds = dismiss_seconds()
        if seconds:

            note = self.note
            QtCore.QTimer.singleShot(seconds * 1000, lambda n=note: self._dismiss(n))

    def _dismiss(self, note):
        if self.note is note:
            self.remind_later(list(note.names))

    def close_note(self):
        if self.note is not None:
            self.note.hide()
            self.note.deleteLater()
            self.note = None

    def remind_later(self, names, now=None):
        now = time.time() if now is None else now
        for name in names:
            self.later[name] = now + reminder_minutes() * 60
        self.close_note()

    def save(self, names):
        for name in names:
            save_document(name)
        self.close_note()

    def save_all(self):
        Gui.runCommand("Std_SaveAll", 0)
        self.close_note()


def save_document(name):
    """Saves one document; an untitled one gets FreeCAD's Save As box."""
    doc = App.getDocument(name)
    if doc.FileName:
        doc.save()
        gdoc = Gui.getDocument(name)
        if gdoc is not None:
            gdoc.Modified = False
        return True
    gdoc = Gui.getDocument(name)
    try:
        Gui.getMainWindow().setActiveWindow(gdoc.ActiveView.graphicsView().parent())
    except Exception as _fw_err:
        _fw_log("optionsextras.py:266", _fw_err)
    App.setActiveDocument(name)
    Gui.runCommand("Std_SaveAs", 0)
    return False


class ReminderNote(QtWidgets.QFrame):
    ""

    def __init__(self, parent, names, reminder):
        super().__init__(parent)
        self.names, self.reminder = list(names), reminder
        self.setObjectName("SWSaveReminder")
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setAutoFillBackground(True)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)

        # line of text, a Save button
        top = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("<b>Un-Saved document notification</b>")
        title.setObjectName("SWSaveReminderTitle")
        top.addWidget(title, 1)
        cross = QtWidgets.QToolButton()
        cross.setObjectName("SWRemindLater")
        cross.setText("\u2715")
        cross.setToolTip("Remind me later")
        cross.setAutoRaise(True)
        cross.setFocusPolicy(Qt.NoFocus)
        cross.clicked.connect(lambda _c=False: reminder.remind_later(self.names))
        top.addWidget(cross)
        lay.addLayout(top)
        minutes = reminder_minutes()
        one = len(self.names) == 1
        text = QtWidgets.QLabel("%s not been saved for at least %d minute%s." % (
            "This document has" if one else "These documents have", minutes, "" if minutes == 1 else "s"))
        text.setObjectName("SWSaveReminderText")
        text.setWordWrap(True)
        text.setToolTip(", ".join(App.getDocument(n).Label for n in self.names))
        lay.addWidget(text)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        buttons = [("Save", "SWSaveNow", lambda: reminder.save(self.names))]
        if not one:
            buttons.append(("Save All", "SWSaveAll", reminder.save_all))
        for caption, name, run in buttons:
            b = QtWidgets.QPushButton(caption)
            b.setObjectName(name)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _c=False, run=run: run())
            row.addWidget(b)
        lay.addLayout(row)
        self.setFixedWidth(360)

    def show_at_corner(self):
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None:
            bar = parent.statusBar().height() if hasattr(parent, "statusBar") else 0
            self.move(parent.width() - self.width() - 16, parent.height() - self.height() - bar - 16)
        self.show()
        self.raise_()


# ---------------------------------------------------------------- open last used documents
def open_files():
    """The saved files open now, in the order they were opened."""
    return [d.FileName for d in App.listDocuments().values() if d.FileName and not getattr(d, "Temporary", False)]


def remember_open_files():
    _p().SetString(LAST_FILES, json.dumps(open_files()))


def last_files():
    try:
        files = json.loads(_p().GetString(LAST_FILES, "[]"))
    except ValueError:
        files = []
    return [f for f in files if isinstance(f, str)]


def open_last(force=False):
    """At start: opens the files that were open when the window closed, when the setting is
    Always and nothing else was opened (a file named on the command line wins). Returns the
    files opened."""
    if _p().GetString(OPEN_LAST, "Never") != "Always" and not force:
        return []
    if App.listDocuments() and not force:
        return []
    opened = []
    for f in last_files():
        if os.path.isfile(f) and not any(d.FileName == f for d in App.listDocuments().values()):
            try:
                App.openDocument(f)
                opened.append(f)
            except Exception as error:
                App.Console.PrintWarning("Open last used documents: %s not opened: %s\n" % (f, error))
    return opened


class _CloseWatch(QtCore.QObject):
    """The main window is about to close: keep the list of open files."""

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() == QtCore.QEvent.Close:
            try:
                remember_open_files()
            except Exception as _fw_err:
                _fw_log("optionsextras.py:377", _fw_err)
        return False


# ---------------------------------------------------------------- sketch on a new part
def front_plane(body):
    origin = getattr(body, "Origin", None)
    for feature in getattr(origin, "OriginFeatures", []) or []:
        if getattr(feature, "Role", "") == "XZ_Plane" or feature.Name.startswith("XZ_Plane"):
            return feature
    return None


def sketch_on_new_part(doc, body):
    """New part: with the setting on, a sketch opens on the Front Plane. Returns the sketch."""
    if not _p().GetBool(SKETCH_ON_NEW, False) or body is None:
        return None
    plane = front_plane(body)
    if plane is None:
        return None
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, plane.Name)
    before = {o.Name for o in doc.Objects}
    Gui.runCommand("PartDesign_NewSketch", 0)
    made = [o for o in doc.Objects if o.Name not in before and o.TypeId == "Sketcher::SketchObject"]
    return made[0] if made else None


def after_new_part(doc, body):
    """newdoc.make calls this; the sketch starts once the new view is up."""
    try:
        if apply_part_template(doc, body):
            body = next((o for o in doc.Objects if o.TypeId == "PartDesign::Body"), None)
            if body is None:
                return
    except Exception as error:
        App.Console.PrintWarning("Default part template: %s\n" % error)
    if _p().GetBool(SKETCH_ON_NEW, False):
        QtCore.QTimer.singleShot(300, lambda: _later_sketch(doc.Name, body.Name))


def _later_sketch(doc_name, body_name):
    try:
        doc = App.getDocument(doc_name)
        sketch_on_new_part(doc, doc.getObject(body_name))
    except Exception as error:
        App.Console.PrintWarning("Create sketch on new part: %s\n" % error)


# ---------------------------------------------------------------- the kept Options that change something
def _kept(page, text, default):
    from . import optionspages
    return optionspages.stored(page, text, default)


def _doc_kept(doc, page, text, default):
    from . import optionspages
    return optionspages.doc_value(doc, page, text, default)


# Detailing > Display filter row -> the mbd.py PMI kinds it shows
PMI_FILTER = {"Datums": ("Datum",), "Geometric tolerances": ("GTol",),
              "Datum targets": ("DatumTarget",), "Notes": ("Note",),
              "Reference dimensions": ("BasicLocation", "BasicSize"),
              "Surface finish": ("SurfaceFinish",), "Welds": ("Weld",)}



def _feature_dims(doc):
    from . import featuredims
    featuredims.refresh(doc)


def _feature_dims_install():
    from . import featuredims
    featuredims.install()


def pmi_shown(doc, kind):
    """Options > Document Properties > Detailing > Display filter, for a 3D annotation kind."""
    if _doc_kept(doc, "Detailing", "Display all types", False):
        return True
    if kind in ("Size", "Location", "Angle", "Pattern"):
        # DimXpert dimensions (the MBD Dimensions tab's size and location dimensions)
        return bool(_doc_kept(doc, "Detailing", "DimXpert dimensions", True))
    for row, kinds in PMI_FILTER.items():
        if kind in kinds:
            return bool(_doc_kept(doc, "Detailing", row, True))
    return True


def apply_detailing(doc=None):
    """Shows or hides the document's 3D annotations as the Detailing display filter says."""
    docs = [doc] if doc is not None else list(App.listDocuments().values())
    for d in docs:
        if not _doc_alive(d):
            continue        # closed before this deferred call ran (Quick View, a check closing its file)
        for o in d.Objects:
            if getattr(o, "SWStyleKind", "") != "PMI" or o.ViewObject is None:
                continue
            o.ViewObject.Visibility = pmi_shown(d, o.Kind)


def _hex(text, default):
    t = str(text or "").strip().lstrip("#")
    try:
        return tuple(int(t[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return default


def apply_plane_display(doc=None):
    """Document Properties > Plane Display: the colour and transparency of the reference planes."""
    docs = [doc] if doc is not None else list(App.listDocuments().values())
    for d in docs:
        if not _doc_alive(d):
            continue        # closed before this deferred call ran
        # only what the user set: the look's own plane colours stay otherwise
        colour = _hex(_doc_kept(d, "Plane Display", "Front Face Color", ""), None)
        clear = _doc_kept(d, "Plane Display", "Transparency (%)", -1)
        clear = int(clear) if clear is not None and int(clear) >= 0 else None
        if not _kept("Fixed", "Display shaded planes", True):
            clear = 100                     # System Options > Display: planes without their face
        if colour is None and clear is None:
            continue
        for o in d.Objects:
            if o.TypeId not in ("App::Plane", "PartDesign::Plane") or o.ViewObject is None:
                continue
            vo = o.ViewObject
            if clear is not None and "Transparency" in vo.PropertiesList:
                vo.Transparency = clear
            if colour is None:
                continue
            if "ShapeAppearance" in vo.PropertiesList:
                mats = []
                for m in vo.ShapeAppearance:
                    m.DiffuseColor = colour
                    mats.append(m)
                vo.ShapeAppearance = mats
            elif "ShapeColor" in vo.PropertiesList:
                vo.ShapeColor = colour


DISPLAY_STYLES = {"Wireframe": (True, True), "Hidden lines visible": (True, True),
                  "Hidden lines removed": (False, False), "Shaded with edges": (False, False),
                  "Shaded": (False, False)}


def new_drawing_view(view):
    """System Options > Drawings > Display Style and Area Hatch/Fill, on a new drawing view."""
    style = _kept("Display Style", "Display style", "Hidden lines removed")
    hard, smooth_hidden = DISPLAY_STYLES.get(style, (False, False))
    tangent = _kept("Display Style", "Tangent edges", "Visible")
    chosen = bool(getattr(view, "SWDisplayStyle", ""))
    for prop, value in (("HardHidden", hard), ("SmoothHidden", smooth_hidden and tangent != "Removed"),
                        ("SmoothVisible", tangent != "Removed"),
                        ("CoarseView", _kept("Display Style", "Edge quality for new views", "High quality")
                         == "Draft quality")):
        if chosen:
            # the view was made with a Display Style of its own (Model View, Standard 3 View, Projected View
            # PMs: drawings.set_display_style, with these options): it keeps it; the defaults here came later and
            # took the hidden lines off a Hidden Lines Visible view (vd113, 11-20)
            break
        if prop in view.PropertiesList:
            try:
                setattr(view, prop, value)
            except Exception as _fw_err:
                _fw_log("optionsextras.py:534", _fw_err)
    if view.TypeId == "TechDraw::DrawViewSection":
        hatch = _kept("Area Hatch/Fill", "Hatch", "Hatch")
        if not getattr(view, "SWAutoHatch", False):     # Auto hatching set the view's own (drawings)
            view.CutSurfaceDisplay = {"None": "Hide", "Solid": "Color", "Hatch": "PatHatch"}.get(hatch, "PatHatch")
        pattern = str(_kept("Area Hatch/Fill", "Pattern", "ANSI31 (Iron BrickStone)")).split(" ")[0].lower()
        try:
            view.NameGeomPattern = pattern
        except Exception as _fw_err:
            _fw_log("optionsextras.py:543", _fw_err)
        for prop, text, default in (("HatchScale", "Scale", 1.0), ("HatchRotation", "Angle", 0.0)):
            try:
                setattr(view, prop, float(str(_kept("Area Hatch/Fill", text, default)).rstrip("deg") or default))
            except Exception as _fw_err:
                _fw_log("optionsextras.py:548", _fw_err)


def _new_feature(obj):
    """FeatureManager > Name feature on creation: the new feature's name opens for editing."""
    if not _kept("FeatureManager", "Name feature on creation", False):
        return
    if not obj.TypeId.startswith(("PartDesign::", "Sketcher::")) or obj.TypeId == "PartDesign::Body":
        return
    name, doc = obj.Name, obj.Document.Name

    def edit():
        d = App.getDocument(doc) if doc in App.listDocuments() else None
        o = d.getObject(name) if d is not None else None
        if o is None or Gui.Control.activeDialog():
            return
        for tree in Gui.getMainWindow().findChildren(QtWidgets.QTreeWidget):
            if not tree.isVisible():
                continue
            hits = tree.findItems(o.Label, QtCore.Qt.MatchExactly | QtCore.Qt.MatchRecursive, 0)
            if hits:
                tree.setCurrentItem(hits[0])
                tree.editItem(hits[0], 0)
                return
    _after_dialog(edit)


def _after_dialog(fn, tries=60):
    """Runs fn once no task dialog is open (a feature is named after its PropertyManager closes)."""
    def tick(n=tries):
        if Gui.Control.activeDialog() and n > 0:
            QtCore.QTimer.singleShot(500, lambda: tick(n - 1))
        else:
            fn()
    QtCore.QTimer.singleShot(300, tick)


def _comment_stamp(obj, prop):
    """FeatureManager > Comments > Automatically add timestamp to comments."""
    if prop != "Comment" or not _kept("FeatureManager", "Automatically add timestamp to comments", True):
        return
    text = str(getattr(obj, "Comment", "") or "")
    if not text.strip() or text.startswith("["):
        return
    import time
    stamp = time.strftime("[%Y-%m-%d %H:%M] ")
    _Watch.busy = True
    try:
        obj.Comment = stamp + text
    finally:
        _Watch.busy = False


def _rebuild_errors(doc):
    return [o for o in doc.Objects if "Invalid" in (o.State or []) or "Error" in (o.State or [])]


class _Watch:
    """App observer for the kept Options that act when the model changes (an App observer only: a Gui
    observer with slotChangedObject breaks FreeCAD's FEM mesh objects)."""
    busy = False

    def slotCreatedObject(self, obj):
        if _Watch.busy:
            return
        tid = obj.TypeId
        if tid in ("TechDraw::DrawViewPart", "TechDraw::DrawViewSection", "TechDraw::DrawProjGroupItem"):
            if getattr(obj.Document, "Restoring", False):
                return      # extapps/69: a view read from the file keeps its own settings (not a new view)
            QtCore.QTimer.singleShot(0, lambda o=obj: _safe(new_drawing_view, o))
        elif tid in ("App::Plane", "PartDesign::Plane"):
            QtCore.QTimer.singleShot(0, lambda d=obj.Document: _safe(apply_plane_display, d))
        else:
            _safe(_new_feature, obj)

    def slotChangedObject(self, obj, prop):
        if _Watch.busy:
            return
        if prop == "Comment":
            _safe(_comment_stamp, obj, prop)
        elif prop == "Kind" and getattr(obj, "SWStyleKind", "") == "PMI":
            QtCore.QTimer.singleShot(0, lambda d=obj.Document: _safe(apply_detailing, d))

    def slotRecomputedDocument(self, doc):
        if _rebuild_errors(doc) and _kept("General", "Enable sounds for events", True):
            QtWidgets.QApplication.beep()

    def slotStartSaveDocument(self, doc, filename):
        if _kept("Messages/Errors/Warnings", "Warn me when saving documents with rebuild errors", True):
            bad = _rebuild_errors(doc)
            if bad:
                App.Console.PrintWarning("%s is saved with rebuild errors: %s\n"
                                         % (doc.Label, ", ".join(o.Label for o in bad[:8])))
                try:
                    Gui.getMainWindow().statusBar().showMessage(
                        "Saved with rebuild errors: %s" % ", ".join(o.Label for o in bad[:4]), 8000)
                except Exception as _fw_err:
                    _fw_log("optionsextras.py:643", _fw_err)

    def slotFinishSaveDocument(self, doc, filename):
        # the ConfigurationManager's Rebuild/Save Mark: the marked configurations are rebuilt on save
        def marked(name=doc.Name):
            d = App.getDocument(name) if name in App.listDocuments() else None
            if d is not None:
                from . import configmanager
                configmanager.rebuild_marked(d)
        QtCore.QTimer.singleShot(0, lambda: _safe(marked))

    def slotCreatedDocument(self, doc):
        QtCore.QTimer.singleShot(800, lambda: _safe(apply_background_image))

    def slotFinishRestoreDocument(self, doc):
        QtCore.QTimer.singleShot(800, lambda: _safe(apply_background_image))
        QtCore.QTimer.singleShot(500, lambda: (_safe(apply_detailing, doc), _safe(apply_plane_display, doc)))


def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception as error:
        App.Console.PrintLog("FreeCAD options: %s: %s\n" % (getattr(fn, "__name__", fn), error))


def apply_part_template(doc, body):
    """System Options > Default Templates > Parts: a new part starts as a copy of that document."""
    path = _p().GetString("PartTemplate", "")
    if not path or not os.path.isfile(path):
        return False
    try:
        from . import newdoc
        if doc.Name in newdoc.FROM_TEMPLATE:
            return True         # New made the part as a copy of the template already
    except Exception as _fw_err:
        _fw_log("optionsextras.py:679", _fw_err)
    before = {o.Name for o in doc.Objects}
    doc.mergeProject(path)
    new = [o for o in doc.Objects if o.Name not in before]
    bodies = [o for o in new if o.TypeId == "PartDesign::Body"]
    if bodies and body is not None and not body.Group:
        doc.removeObject(body.Name)
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", bodies[0])
    doc.recompute()
    return True


# ---------------------------------------------------------------- rows FreeCAD did one way (page "Fixed")
class _TreeKeys(QtCore.QObject):
    """FeatureManager > Arrow key navigation off: Up/Down/Left/Right do not move through the tree."""

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() == QtCore.QEvent.KeyPress and event.key() in (
                QtCore.Qt.Key_Up, QtCore.Qt.Key_Down, QtCore.Qt.Key_Left, QtCore.Qt.Key_Right) \
                and not _kept("Fixed", "Arrow key navigation", False):
            return True
        return False


_tree_keys = []


def _model_trees():
    mw = Gui.getMainWindow()
    out = []
    for tree in mw.findChildren(QtWidgets.QTreeView):
        if tree.metaObject().className() == "Gui::TreeWidget" or tree.objectName() == "SWFeatureTree":
            out.append(tree)
    return out


def apply_fixed():
    """What the rows FreeCAD always did one way change, once they are set otherwise."""
    mw = Gui.getMainWindow()
    for box in mw.findChildren(QtWidgets.QLineEdit, "SWSearchBox"):
        box.setVisible(bool(_kept("Fixed", "Show search box", True)))
    slow = bool(_kept("Fixed", "Edit name with slow double click", True))
    if not _tree_keys:
        _tree_keys.append(_TreeKeys(mw))
    for tree in _model_trees():
        trig = QtWidgets.QAbstractItemView.EditKeyPressed
        if slow:
            trig |= QtWidgets.QAbstractItemView.SelectedClicked
        tree.setEditTriggers(trig)
        if not tree.property("swTreeKeys"):
            tree.installEventFilter(_tree_keys[0])
            tree.setProperty("swTreeKeys", True)
    for d in App.listDocuments().values():
        _safe(apply_plane_display, d)


# ---------------------------------------------------------------- background image (Colors page)
_BG = "FreeWorksBackgroundImage"


def apply_background_image(view=None):
    """System Options > Colors > Background appearance > Image file: the picture behind the model."""
    from pivy import coin
    path = _p().GetString("BackgroundImage", "")
    on = _p().GetBool("BackgroundIsImage", False) and os.path.isfile(path)
    views = [view] if view is not None else []
    if view is None:
        for d in App.listDocuments().values():
            g = Gui.getDocument(d.Name)
            for v in (g.mdiViewsOfType("Gui::View3DInventor") if g else []):
                views.append(v)
    for v in views:
        root = v.getSceneGraph()
        for i in range(root.getNumChildren() - 1, -1, -1):
            if root.getChild(i).getName() == _BG:
                root.removeChild(i)
        if not on:
            continue
        sep = coin.SoSeparator()
        sep.setName(_BG)
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        cam = coin.SoOrthographicCamera()
        cam.height = 2.0
        cam.position = (0, 0, 1)
        depth = coin.SoDepthBuffer()
        depth.test = False
        depth.write = False
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        tex = coin.SoTexture2()
        _texture_from_file(tex, path)
        coords = coin.SoCoordinate3()
        w = 1.0
        try:
            size = v.getSize()
            w = float(size[0]) / max(1.0, float(size[1]))
        except Exception as _fw_err:
            _fw_log("optionsextras.py:779", _fw_err)
        coords.point.setValues(0, 4, [(-w, -1, 0), (w, -1, 0), (w, 1, 0), (-w, 1, 0)])
        tc = coin.SoTextureCoordinate2()
        tc.point.setValues(0, 4, [(0, 0), (1, 0), (1, 1), (0, 1)])
        face = coin.SoFaceSet()
        face.numVertices.setValue(4)
        for n in (pick, cam, depth, light, tex, coords, tc, face):
            sep.addChild(n)
        root.insertChild(sep, 0)


def _texture_from_file(tex, path):
    """The picture put in the texture as pixels read with Qt, as decalpm and scenebg do: Coin reads a file
    named in SoTexture2.filename only through simage, which FreeCAD's Windows build may lack, and the
    texture then draws nothing (the Options background picture showed nothing). Falls back to the file name."""
    from pivy import coin
    from PySide import QtGui
    image = QtGui.QImage(path)
    if image.isNull():
        tex.filename.setValue(path)
        return False
    image = image.convertToFormat(QtGui.QImage.Format_RGBA8888).mirrored(False, True)     # Coin: bottom row first
    w, h = image.width(), image.height()
    stride = image.bytesPerLine()
    raw = bytes(image.constBits())[:stride * h]
    tex.filename.setValue("")
    tex.image.setValue(coin.SbVec2s(w, h), 4, b"".join(raw[y * stride:y * stride + 4 * w] for y in range(h)))
    return True


# ---------------------------------------------------------------- install
_installed = []
_refresh = []


def refresh_options():
    """After the Options box is saved: what the kept settings change, done again (once per save)."""
    if _refresh:
        return
    _refresh.append(1)

    def run():
        _refresh[:] = []
        doc = App.ActiveDocument
        if doc is not None:
            _safe(apply_detailing, doc)
            _safe(apply_plane_display, doc)
            _safe(_feature_dims, doc)
        _safe(apply_background_image)
        _safe(apply_fixed)
        try:
            from . import optionsextras2
            optionsextras2.refresh()
        except Exception as _fw_err:
            _fw_log("optionsextras.py:814", _fw_err)
        try:
            from . import optionsextras3
            optionsextras3.refresh()
        except Exception as _fw_err:
            _fw_log("optionsextras.py:819", _fw_err)
        try:                    # extapps84: System Options > Drawings > sketch points on every open drawing
            from . import drawsketch
            drawsketch.refresh_points()
            from . import drawsketchopts        # extapps85: sketch hatches restacked, sketch pictures shown or not
            drawsketchopts.refresh()
        except Exception as _fw_err:
            _fw_log("optionsextras.py:sketch-points", _fw_err)
        try:                    # extapps86: thin parts, drawing scroll bars, bend table folder
            from . import optionswire
            optionswire.refresh()
        except Exception as _fw_err:
            _fw_log("optionsextras.py:options-wire-refresh", _fw_err)
        try:                    # Document Properties > Sheet Metal on the flat patterns shown
            from . import smflatdisplay
            smflatdisplay.refresh(doc)
        except Exception as _fw_err:
            _fw_log("optionsextras.py:824", _fw_err)
    QtCore.QTimer.singleShot(0, run)


def install():
    if _installed:
        return _installed[0]
    app = QtWidgets.QApplication.instance()
    mw = Gui.getMainWindow()
    try:
        default_note_seconds()
    except Exception as _fw_err:
        _fw_log("optionsextras.py:note-seconds", _fw_err)
    close, reminder = _CloseWatch(mw), SaveReminder()
    app.focusChanged.connect(_focus_changed)    # a box gets the focus before its arrows, wheel or keys step it
    mw.installEventFilter(close)
    reminder.timer.start()
    watch = _Watch()
    App.addDocumentObserver(watch)
    from . import restorehook       # FreeCAD 1.1 sends no restore signals: the hook reports opened files
    restorehook.on_restored(watch.slotFinishRestoreDocument)
    _safe(_feature_dims_install)
    try:                # extapps85: sketch pictures in drawings follow their views and pictures
        from . import drawsketchopts
        drawsketchopts.register()
    except Exception as _fw_err:
        _fw_log("optionsextras.py:sketch-opts", _fw_err)
    try:                # extapps86: System Options rows that act through other parts of FreeCAD
        from . import optionswire
        optionswire.install()
    except Exception as _fw_err:
        _fw_log("optionsextras.py:options-wire", _fw_err)
    _installed.append({"close": close, "reminder": reminder, "watch": watch})
    QtCore.QTimer.singleShot(1500, _open_last_at_start)
    QtCore.QTimer.singleShot(2500, lambda: _safe(apply_fixed))
    try:
        from . import optionsextras2      # import check, mass properties on save, graphics, multi-user
        optionsextras2.install()
    except Exception as error:
        App.Console.PrintLog("FreeCAD options2: %s\n" % error)
    try:
        from . import optionsextras3      # sketch auto-rotate, shaded sketch plane, four view projection
        optionsextras3.install()
    except Exception as error:
        App.Console.PrintLog("FreeCAD options3: %s\n" % error)
    try:
        from . import pmunits             # the Units > pop-up under PropertyManager length boxes
        pmunits.install()
    except Exception as error:
        App.Console.PrintLog("FreeCAD pmunits: %s\n" % error)
    try:
        from . import crossref
        crossref.install()
    except Exception as error:
        App.Console.PrintLog("FreeCAD crossref: %s\n" % error)
    return _installed[0]


def _open_last_at_start():
    try:
        open_last()
    except Exception as error:
        App.Console.PrintWarning("Open last used documents: %s\n" % error)


def reminder():
    return _installed[0]["reminder"] if _installed else None
