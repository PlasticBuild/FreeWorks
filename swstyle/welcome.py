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

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import icons, paths

Qt = QtCore.Qt
PARAM = "WelcomeAtStartup"
SETUP_DONE = "WelcomeSetupDone"        # the first-start setup box on Home was closed with Done
START_WIDGET = "ThemeSelectorWidget"   # in FreeCAD's own first-start panel on the Start page
VIEW_PARAMS = "User parameter:BaseApp/Preferences/View"
NAVIGATION = (
    # welcomedark-1120: the add-on's own style shown as "Default" (no product name in the UI); same style class
    ("Default", "Gui::SolidWorksNavigationStyle"), ("Blender", "Gui::BlenderNavigationStyle"),
    ("CAD", "Gui::CADNavigationStyle"), ("Gesture", "Gui::GestureNavigationStyle"),
    ("Maya-Gesture", "Gui::MayaGestureNavigationStyle"), ("OpenCascade", "Gui::OpenCascadeNavigationStyle"),
    ("OpenInventor", "Gui::InventorNavigationStyle"), ("OpenSCAD", "Gui::OpenSCADNavigationStyle"),
    ("Revit", "Gui::RevitNavigationStyle"), ("Siemens NX", "Gui::SiemensNXNavigationStyle"),
    ("TinkerCAD", "Gui::TinkerCADNavigationStyle"), ("Touchpad", "Gui::TouchpadNavigationStyle"),
)
FOLDERS = "WelcomeRecentFolders"       # "|" joined, most recent first
COMMAND = "SWStyle_Welcome"
THUMB = 96
LINKS = (
    ("What's New", "whatsnew"),
    ("Documentation", "https://wiki.freecad.org/"),
    ("Forum", "https://forum.freecad.org/"),
    ("User Groups", "https://forum.freecad.org/viewforum.php?f=42"),
    ("Get Support", "https://forum.freecad.org/viewforum.php?f=3"),
    ("Sample Models", "samples"),
)
LEARN = (
    ("Tutorials", "tutorials", "Step-by-step lessons inside the help window."),
    ("Sample Models", "samples", "The example models that come with the program."),
    ("Online Training", "https://wiki.freecad.org/Tutorials", "The tutorials on the documentation site."),
    ("Videos", "https://www.youtube.com/@FreeCADNews", "Video lessons."),
    ("Manual", "https://wiki.freecad.org/Manual:Introduction", "The user manual."),
)
_open = []


def at_startup():
    return paths.params().GetBool(PARAM, True)


def set_at_startup(on):
    paths.params().SetBool(PARAM, bool(on))
    sync_start_page()


START_HIDDEN = "StartPageHiddenByWelcome"    # startup-1120 N2


def sync_start_page():
    ""


    try:
        start = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Start")
        hidden = paths.params().GetBool(START_HIDDEN, False)
        from . import startswitch      # startswitch-1127: the Start page picked: FreeCAD opens it
        if at_startup() and startswitch.screen() == "welcome":
            if not hidden and start.GetBool("ShowOnStartup", True):
                start.SetBool("ShowOnStartup", False)
                paths.params().SetBool(START_HIDDEN, True)
        elif hidden:
            start.SetBool("ShowOnStartup", True)
            paths.params().SetBool(START_HIDDEN, False)
    except Exception as _fw_err:
        _fw_log("welcome.py:sync_start_page", _fw_err)


def recent_files():
    from . import taskpane
    return taskpane.recent_files()


def recent_folders():
    text = paths.params().GetString(FOLDERS, "")
    out = [f for f in text.split("|") if f]
    for f in recent_files():
        d = os.path.dirname(f)
        if d and d not in out:
            out.append(d)
    return [d for d in out if os.path.isdir(d)][:12]


def remember_folder(folder):
    out = [folder] + [f for f in recent_folders() if f != folder]
    paths.params().SetString(FOLDERS, "|".join(out[:12]))


def forget_recent_file(path):
    """Takes one document off the recent list (and off the pinned ones); FreeCAD's list keeps the rest in order."""
    try:
        from . import recentdocs
        recentdocs.set_pinned([p for p in recentdocs.pinned(recentdocs.PIN_DOCS) if p != path], recentdocs.PIN_DOCS)
    except Exception as _fw_err:
        _fw_log("welcome.py:forget pin", _fw_err)
    p = App.ParamGet("User parameter:BaseApp/Preferences/RecentFiles")
    keep = [f for f in recent_files() if f != path]
    for i in range(max(p.GetInt("RecentFiles", 12) or 12, len(keep) + 1)):
        p.RemString("MRU%d" % i)
    for i, f in enumerate(keep):
        p.SetString("MRU%d" % i, f)


def pinned_files():
    try:
        from . import recentdocs
        return recentdocs.pinned(recentdocs.PIN_DOCS)
    except Exception:
        return []


def toggle_pin(path):
    from . import recentdocs
    return recentdocs.toggle_pin(path, recentdocs.PIN_DOCS)


def _scale():
    """The screens' largest device pixel ratio (1.75 at 175 %): pictures are made with that many pixels."""
    try:
        return max([1.0] + [float(s.devicePixelRatio()) for s in QtGui.QGuiApplication.screens()])
    except Exception:
        return 1.0


def clear_recent_files():
    p = App.ParamGet("User parameter:BaseApp/Preferences/RecentFiles")
    for i in range(p.GetInt("RecentFiles", 12) or 12):
        p.RemString("MRU%d" % i)


def clear_recent_folders():
    paths.params().SetString(FOLDERS, "")


def samples_dir():
    from . import taskpane
    return taskpane._samples_dir()


def open_file(path):
    from . import taskpane
    taskpane.open_file(path)



GROUPS = "WelcomeDocumentGroups"       # JSON {name: [paths]}, in the order they were made


def document_groups():
    """[(name, [paths])] of the saved document groups."""
    import json
    try:
        data = json.loads(paths.params().GetString(GROUPS, "") or "[]")
    except Exception:
        data = []
    if isinstance(data, dict):
        data = list(data.items())
    return [(str(n), [str(p) for p in ps]) for n, ps in data if n]


def _write_groups(groups):
    import json
    paths.params().SetString(GROUPS, json.dumps([[n, ps] for n, ps in groups]))


def open_documents():
    """The paths of the open documents that are saved (what a new group keeps)."""
    out = []
    for d in App.listDocuments().values():
        f = getattr(d, "FileName", "")
        if f and os.path.isfile(f) and f not in out:
            out.append(f)
    return out


def save_document_group(name, files=None):
    """Create Document Group: the open documents (or files) under name; a group of that name is replaced."""
    name = (name or "").strip()
    files = list(files) if files is not None else open_documents()
    if not name or not files:
        return False
    groups = [(n, ps) for n, ps in document_groups() if n != name]
    groups.append((name, files))
    _write_groups(groups)
    return True


def delete_document_group(name):
    groups = document_groups()
    keep = [(n, ps) for n, ps in groups if n != name]
    _write_groups(keep)
    return len(keep) != len(groups)


def open_document_group(name):
    """Opens every document of the group (those already open come to the front); returns the ones opened."""
    files = dict(document_groups()).get(name, [])
    done = []
    for f in files:
        if not os.path.isfile(f):
            App.Console.PrintWarning("FreeCAD: document group %s: %s is not there\n" % (name, f))
            continue
        try:
            open_file(f)
            done.append(f)
        except Exception as error:
            App.Console.PrintError("FreeCAD: %s not opened: %s\n" % (f, error))
    return done


def _thumb(path, pinned=False):
    """The document's own thumbnail at the screen's scale, else our drawn page; a pin in the corner when pinned."""
    scale = _scale()
    side = int(round(THUMB * scale))
    pix = QtGui.QPixmap()
    try:
        if os.path.isfile(path):
            from . import fcstdinfo
            data = fcstdinfo.thumbnail(path)
            if data and pix.loadFromData(data):
                pix = pix.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    except Exception as _fw_err:
        _fw_log("welcome.py:187", _fw_err)
        pix = QtGui.QPixmap()
    if pix.isNull():
        pix = _page_art(path, side)
    out = QtGui.QPixmap(side, side)
    out.fill(Qt.transparent)
    p = QtGui.QPainter(out)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.drawPixmap((side - pix.width()) // 2, (side - pix.height()) // 2, pix)
    if pinned:
        _draw_pin(p, side - int(20 * scale), int(2 * scale), int(18 * scale))
    p.end()
    out.setDevicePixelRatio(scale)
    return out


def _page_art(path, side):
    """Our drawn picture for a document without a thumbnail: a page with a folded corner and a block on it;
    grey with a question mark when the file is gone."""
    gone = not os.path.isfile(path)
    pix = QtGui.QPixmap(side, side)
    pix.fill(Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    u = side / 96.0
    page = QtGui.QPolygonF([QtCore.QPointF(22 * u, 6 * u), QtCore.QPointF(62 * u, 6 * u), QtCore.QPointF(76 * u, 20 * u),
                            QtCore.QPointF(76 * u, 90 * u), QtCore.QPointF(22 * u, 90 * u)])
    p.setPen(QtGui.QPen(QtGui.QColor(150, 155, 165), 1.2 * u))
    p.setBrush(QtGui.QColor(246, 247, 249))
    p.drawPolygon(page)
    p.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(62 * u, 6 * u), QtCore.QPointF(62 * u, 20 * u),
                                    QtCore.QPointF(76 * u, 20 * u)]))
    if gone:
        p.setPen(QtGui.QColor(150, 150, 150))
        font = p.font()
        font.setPixelSize(int(34 * u))
        font.setBold(True)
        p.setFont(font)
        p.drawText(QtCore.QRectF(22 * u, 20 * u, 54 * u, 60 * u), Qt.AlignCenter, "?")
    else:
        top = QtGui.QColor(170, 200, 235)
        left = QtGui.QColor(120, 160, 210)
        right = QtGui.QColor(90, 130, 185)
        cx, cy, a = 49 * u, 54 * u, 16 * u
        P = QtCore.QPointF
        p.setPen(QtGui.QPen(QtGui.QColor(60, 90, 140), 1 * u))
        for colour, poly in ((top, [P(cx, cy - a), P(cx + a, cy - a / 2), P(cx, cy), P(cx - a, cy - a / 2)]),
                             (left, [P(cx - a, cy - a / 2), P(cx, cy), P(cx, cy + a), P(cx - a, cy + a / 2)]),
                             (right, [P(cx, cy), P(cx + a, cy - a / 2), P(cx + a, cy + a / 2), P(cx, cy + a)])):
            p.setBrush(colour)
            p.drawPolygon(QtGui.QPolygonF(poly))
    p.end()
    return pix


def _draw_pin(p, x, y, size):
    """A small drawn push pin (our own art), as a pinned recent document shows it."""
    p.save()
    p.translate(x, y)
    s = size / 18.0
    p.setPen(QtGui.QPen(QtGui.QColor(90, 90, 90), 1.2 * s))
    p.setBrush(QtGui.QColor(255, 255, 255, 230))
    p.drawEllipse(QtCore.QRectF(0, 0, 18 * s, 18 * s))
    p.setBrush(QtGui.QColor(40, 110, 220))
    p.drawRoundedRect(QtCore.QRectF(6 * s, 3 * s, 6 * s, 7 * s), 1.5 * s, 1.5 * s)
    p.drawLine(QtCore.QPointF(4.5 * s, 10 * s), QtCore.QPointF(13.5 * s, 10 * s))
    p.drawLine(QtCore.QPointF(9 * s, 10 * s), QtCore.QPointF(9 * s, 15.5 * s))
    p.restore()


def _button(text, icon=None, run=None, name=""):
    b = QtWidgets.QToolButton()
    b.setText(text)
    b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    b.setAutoRaise(True)
    b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
    if icon:
        b.setIcon(icons.family(icon))
        b.fw_family = icon
    if run is not None:
        b.clicked.connect(lambda checked=False: run())
    if name:
        b.setObjectName(name)
    return b


def _tile(b):
    ""
    b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
    b.setIconSize(QtCore.QSize(48, 48))
    b.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
    b.setMinimumWidth(84)
    family = getattr(b, "fw_family", None)
    if family:      # welcomefit-1120: the pack's large sizes, also in a dark theme (48 px needs 72-84 px at 150-175 %)
        b.setIcon(icons.family(family, large=True))
    return b


def _new_icon(kind):
    """welcomefit-1120: the picture File > New shows for a kind (the pack has no ASSEMBLY or DRAWING family;
    New uses ASSEMBLY_TAB and FreeCAD's own drawing page), so no New tile is left without a picture."""
    try:
        from . import newdoc
        spec = next(k for k in newdoc.KINDS if k[0] == kind)
        return newdoc._icon(spec[2], spec[3])
    except Exception as _fw_err:
        _fw_log("welcome.py:newicon", _fw_err)
    return QtGui.QIcon()


class _ArtLink(QtWidgets.QCommandLinkButton):
    """A link button that keeps our picture: Qt puts its own arrow back when the button is polished or shown."""
    art = None

    def event(self, event):
        done = super().event(event)
        if self.art is not None and event.type() in (QtCore.QEvent.Polish, QtCore.QEvent.Show,
                                                     QtCore.QEvent.StyleChange):
            if self.icon().cacheKey() != self.art.cacheKey():
                self.setIcon(self.art)
        return done


def _link(text, target, run_target, art=None):
    b = _ArtLink(text)
    if art is not None:
        b.art = art
        b.setIcon(art)
    b.setObjectName("SWWelcomeLink_" + text.replace(" ", "").replace("'", ""))
    b.clicked.connect(lambda checked=False: run_target(target))
    return b


class DocumentGrid(QtWidgets.QListWidget):
    """Recent Documents as thumbnails; a double-click opens one."""

    def __init__(self, parent=None, name="SWWelcomeDocuments"):
        super().__init__(parent)
        self.setObjectName(name)
        self.setViewMode(QtWidgets.QListView.IconMode)
        self.setIconSize(QtCore.QSize(THUMB, THUMB))
        self.setResizeMode(QtWidgets.QListView.Adjust)
        self.setMovement(QtWidgets.QListView.Static)
        self.setSpacing(8)
        self.setWordWrap(True)
        self.itemDoubleClicked.connect(lambda item: self.open_item(item))
        self.empty_text = ""
        self.setContextMenuPolicy(Qt.CustomContextMenu)          # Open, Pin, Remove from List, File Location
        self.customContextMenuRequested.connect(lambda pos: self.menu(pos))

    def paintEvent(self, event):
        super().paintEvent(event)
        _paint_empty(self)

    def fill(self):
        """Pinned documents first (they stay listed), then the recent ones, newest first."""
        self.clear()
        pins = pinned_files()
        for f in pins + [f for f in recent_files() if f not in pins]:
            item = QtWidgets.QListWidgetItem(QtGui.QIcon(_thumb(f, f in pins)), os.path.basename(f))
            item.setToolTip(f if os.path.isfile(f) else f + "\n(not found)")
            item.setData(Qt.UserRole, f)
            self.addItem(item)

    def menu(self, pos, run=True):
        """Right-click on a document: the actions that apply to it (a missing file offers no Open)."""
        item = self.itemAt(pos)
        if item is None:
            return None
        path = item.data(Qt.UserRole)
        m = QtWidgets.QMenu(self)
        m.setObjectName("SWWelcomeDocumentMenu")
        if os.path.isfile(path):
            m.addAction("Open", lambda: self.open_item(item))
        m.addAction("Unpin" if path in pinned_files() else "Pin", lambda: self.pin(path))
        m.addAction("Remove from List", lambda: self.forget(path))
        if os.path.isdir(os.path.dirname(path)):
            m.addAction("Open File Location",
                        lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(os.path.dirname(path))))
        if run:
            m.exec(self.viewport().mapToGlobal(pos))
        return m

    def _refill(self):
        top = self.window()
        if isinstance(top, WelcomeDialog):
            top._fill_recent()
            top._fill_home()
        else:
            self.fill()

    def pin(self, path):
        toggle_pin(path)
        self._refill()

    def forget(self, path):
        forget_recent_file(path)
        self._refill()

    def open_item(self, item):
        path = item.data(Qt.UserRole)
        if path:
            top = self.window()
            open_file(path)
            if isinstance(top, WelcomeDialog):
                top.accept()


def _heading(text, parent):
    ""
    label = QtWidgets.QLabel(text, parent)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    return label


class _LinkLabel(QtWidgets.QLabel):
    """welcomedark-1120 (AC2): a link whose colour is the current theme's Link colour. A plain QLabel keeps
    the link colour of the palette its text was set under, so after Set Up's Dark it stayed dark blue."""

    def __init__(self, href, label, parent=None):
        super().__init__(parent)
        self._href, self._label = href, label
        self._set_link_text()

    def _set_link_text(self):
        # welcomeview-1120: the theme's own Link colour (Dark #6ea8ff), not the palette the label happens to hold:
        # in Dark it came out pure blue #0000ff on #494949 (File handling, 1366 run)
        try:
            from . import style
            colour = style.theme_palette().color(QtGui.QPalette.Link).name()
        except Exception as _fw_err:
            _fw_log("welcome.py:link colour", _fw_err)
            colour = self.palette().color(QtGui.QPalette.Link).name()
        self.setText('<a href="%s" style="color:%s">%s</a>' % (self._href, colour, self._label))
        self.setMinimumWidth(self.sizeHint().width())

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QtCore.QEvent.PaletteChange, QtCore.QEvent.StyleChange,
                            QtCore.QEvent.ApplicationPaletteChange):
            self._set_link_text()


def _heading_row(text, parent, view_all):
    """Heading with a "View all" link at the right (it opens the Recent tab)."""
    row = QtWidgets.QHBoxLayout()
    row.addWidget(_heading(text, parent))
    row.addStretch(1)
    link = _LinkLabel("all", "View all", parent)    # welcomedark-1120 (AC2)
    link.setObjectName("SWWelcomeViewAll" + text.replace(" ", ""))
    link.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
    link.linkActivated.connect(lambda *_: view_all())
    row.addWidget(link)
    return row


def _divider(parent, vertical=False):
    line = QtWidgets.QFrame(parent)
    line.setFrameShape(QtWidgets.QFrame.VLine if vertical else QtWidgets.QFrame.HLine)
    line.setFrameShadow(QtWidgets.QFrame.Sunken)
    return line


# Resources are a list of small links with an icon each, two to a row (not big buttons)
LINK_STYLE = ("QCommandLinkButton { background: transparent; border: none; padding: 3px 4px; text-align: left;"
              " font-weight: normal; min-height: 0px; }"
              "QCommandLinkButton:hover { text-decoration: underline; }")


def _resource_icon(target):
    """Our own drawn pictures (resources/simicons), not the system's stock dialog icons."""
    from . import simicons
    pick = {"whatsnew": "FW_WhatsNew", "samples": "FW_FolderOpen"}
    if target in pick:
        return simicons.picture(pick[target])
    if "f=3" in target:
        return simicons.picture("FW_Help")
    if "forum" in target:
        return simicons.picture("FW_Forum")
    return simicons.picture("FW_Document")


class _EmptyList(QtWidgets.QListWidget):
    """A list that says so in grey in its middle while it has nothing in it."""

    def __init__(self, parent=None, empty_text=""):
        super().__init__(parent)
        self.empty_text = empty_text

    def paintEvent(self, event):
        super().paintEvent(event)
        _paint_empty(self)


def _paint_empty(view):
    text = getattr(view, "empty_text", "")
    if not text or view.count():
        return
    painter = QtGui.QPainter(view.viewport())
    painter.setPen(view.palette().color(QtGui.QPalette.Disabled, QtGui.QPalette.Text))
    painter.drawText(view.viewport().rect(), Qt.AlignCenter, text)
    painter.end()



TIPS = (
    "Arrow keys turn the model. Ctrl + Arrow keys pan it. Alt + Arrow keys turn it about the line of sight.",
    "Press Space for the Orientation box and the View Selector. Ctrl+Space shows the View Selector alone.",
    "Press F to fit the model in the window. Press Z to zoom out, Shift+Z to zoom in.",
    "Press S for a shortcut bar with the tools for what you are doing.",
    "Right-drag in the view for mouse gestures: a quick way to the standard views and common tools.",
    "Pick a face and drag the arrow on it to change the feature's depth (Instant3D).",
    "Press F5 for the Selection Filter toolbar. F6 turns the filters on and off.",
    "Ctrl+Q rebuilds everything; Ctrl+B rebuilds what changed.",
)


class TipStrip(QtWidgets.QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SWWelcomeTips")
        # welcomedark-1120 (AC1): no palette copied here; paintEvent fills from the live palette, so the strip
        # follows a theme picked in Set Up FreeCAD (the copy kept the Light colour under Dark's light text)
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(8, 4, 4, 4)
        bulb = QtWidgets.QLabel(self)
        bulb.setPixmap(_bulb(18))
        row.addWidget(bulb)
        self.text = QtWidgets.QLabel(self)
        self.text.setObjectName("SWWelcomeTipText")
        self.text.setWordWrap(True)
        row.addWidget(self.text, 1)
        for name, arrow, step in (("SWWelcomeTipBack", Qt.LeftArrow, -1), ("SWWelcomeTipNext", Qt.RightArrow, 1)):
            b = QtWidgets.QToolButton(self)
            b.setObjectName(name)
            b.setArrowType(arrow)
            b.setAutoRaise(True)
            b.setToolTip("Previous tip" if step < 0 else "Next tip")
            b.clicked.connect(lambda checked=False, k=step: self.turn(k))
            row.addWidget(b)
        self.index = 0
        self.turn(0)

    def turn(self, step):
        self.index = (self.index + step) % len(TIPS)
        self.text.setText(TIPS[self.index])

    def paintEvent(self, event):
        # welcomedark-1120 (AC1): the strip's band in the current theme's AlternateBase, read at every paint
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), self.palette().color(QtGui.QPalette.AlternateBase))
        p.end()
        super().paintEvent(event)


def _bulb(size):
    from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
    pix = _hidpi.canvas(size, size)
    pix.fill(Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(QtGui.QPen(QtGui.QColor(150, 120, 20), 1))
    p.setBrush(QtGui.QColor(255, 220, 90))
    r = size * 0.36
    p.drawEllipse(QtCore.QPointF(size / 2, size * 0.4), r, r)
    p.setBrush(QtGui.QColor(150, 150, 150))
    p.drawRect(QtCore.QRectF(size * 0.38, size * 0.72, size * 0.24, size * 0.2))
    p.end()
    return pix


def _learn_art(target):
    ""
    scale = _scale()
    pix = QtGui.QPixmap(int(round(40 * scale)), int(round(40 * scale)))
    pix.setDevicePixelRatio(scale)
    pix.fill(Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    blue, ink, paper = QtGui.QColor(40, 110, 220), QtGui.QColor(70, 70, 70), QtGui.QColor(250, 250, 250)
    P = QtCore.QPointF
    p.setPen(QtGui.QPen(ink, 1.4))
    if target == "tutorials":                       # an open book
        p.setBrush(paper)
        p.drawPolygon(QtGui.QPolygonF([P(4, 10), P(20, 13), P(20, 34), P(4, 31)]))
        p.drawPolygon(QtGui.QPolygonF([P(36, 10), P(20, 13), P(20, 34), P(36, 31)]))
        p.setPen(QtGui.QPen(blue, 1.4))
        for y in (17, 21, 25):
            p.drawLine(P(8, y), P(17, y + 1.5))
            p.drawLine(P(23, y + 1.5), P(32, y))
    elif target == "samples":                       # a block on a stand
        p.setBrush(QtGui.QColor(170, 200, 235))
        p.drawPolygon(QtGui.QPolygonF([P(20, 6), P(34, 13), P(20, 20), P(6, 13)]))
        p.setBrush(QtGui.QColor(120, 160, 210))
        p.drawPolygon(QtGui.QPolygonF([P(6, 13), P(20, 20), P(20, 34), P(6, 27)]))
        p.setBrush(QtGui.QColor(90, 130, 185))
        p.drawPolygon(QtGui.QPolygonF([P(20, 20), P(34, 13), P(34, 27), P(20, 34)]))
    elif "youtube" in target:                       # a screen with a play mark
        p.setBrush(paper)
        p.drawRoundedRect(QtCore.QRectF(4, 8, 32, 22), 3, 3)
        p.setPen(Qt.NoPen)
        p.setBrush(blue)
        p.drawPolygon(QtGui.QPolygonF([P(16, 13), P(26, 19), P(16, 25)]))
        p.setPen(QtGui.QPen(ink, 1.4))
        p.drawLine(P(14, 34), P(26, 34))
    elif "Manual" in target:                        # a closed book
        p.setBrush(blue)
        p.drawRoundedRect(QtCore.QRectF(9, 5, 22, 30), 2, 2)
        p.setBrush(paper)
        p.drawRect(QtCore.QRectF(13, 10, 14, 6))
    else:                                           # a globe: on the web
        p.setBrush(paper)
        p.drawEllipse(QtCore.QRectF(5, 5, 30, 30))
        p.setPen(QtGui.QPen(blue, 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QtCore.QRectF(13, 5, 14, 30))
        p.drawLine(P(5, 20), P(35, 20))
        p.drawLine(P(8, 12), P(32, 12))
        p.drawLine(P(8, 28), P(32, 28))
    p.end()
    return QtGui.QIcon(pix)


def _troubleshooting_html():
    """Troubleshooting on the Alerts tab: a crash report FreeCAD left behind, else that all is well."""
    try:
        folder = App.getUserAppDataDir()
    except Exception:
        folder = ""
    path = os.path.join(folder, "crash.log") if folder else ""
    if path and os.path.isfile(path):
        import time
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(path)))
        url = QtCore.QUrl.fromLocalFile(path).toString()
        return ("<p>FreeCAD stopped unexpectedly (%s). The report is in <a href='%s'>crash.log</a>.</p>"
                % (when, url))
    return "<p><i>No problems found.</i></p>"


def alerts_html(news):
    ""
    if not news:
        news = ("<h3>Technical Alerts and News</h3>"
                "<p><i>Technical Alerts and News are turned off in Options &gt; General.</i></p>")
    return ("<h3>Critical</h3><p><i>No critical alerts.</i></p>"
            "<h3>Troubleshooting</h3>" + _troubleshooting_html() + news)


class WelcomeDialog(QtWidgets.QDialog):
    TABS = ("Home", "Recent", "Learn", "Alerts")

    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWWelcome")
        self.setWindowTitle("Welcome - FreeCAD")
        self.resize(760, 520)
        lay = QtWidgets.QVBoxLayout(self)
        self.tabs = QtWidgets.QTabWidget(self)
        self.tabs.setObjectName("SWWelcomeTabs")
        self.tabs.addTab(_scrolled(self._home()), "Home")
        self.tabs.addTab(self._recent(), "Recent")
        self.tabs.addTab(self._learn(), "Learn")
        self.tabs.addTab(self._alerts(), "Alerts")
        lay.addWidget(self.tabs, 1)
        bottom = QtWidgets.QHBoxLayout()
        setup = QtWidgets.QPushButton("Setup...", self)
        setup.setObjectName("SWWelcomeSetupButton")
        setup.setToolTip("Theme, language, units and mouse navigation (FreeCAD's first-start settings).")
        setup.clicked.connect(self.show_setup)
        bottom.addWidget(setup)
        self.no_startup = QtWidgets.QCheckBox("Do not show at startup", self)
        self.no_startup.setObjectName("SWWelcomeNoStartup")
        self.no_startup.setChecked(not at_startup())
        self.no_startup.toggled.connect(lambda on: set_at_startup(not on))
        bottom.addWidget(self.no_startup)
        bottom.addStretch(1)
        close = QtWidgets.QPushButton("Close", self)
        close.setObjectName("SWWelcomeClose")
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        from . import startswitch      # startswitch-1127: the switch to the Start page, bottom right
        bottom.addWidget(startswitch.welcome_button(self))
        lay.addLayout(bottom)

    # ---- Home
    def _home(self):
        w = QtWidgets.QWidget()
        w.setObjectName("SWWelcomeHome")
        outer = QtWidgets.QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        self.setup_box = self._setup(w)
        outer.addWidget(self.setup_box)
        self.setup_box.setVisible(not paths.params().GetBool(SETUP_DONE, True))     # shown after a first start

        # Recent Documents across, Recent Folders and Resources side by side, a tip strip below
        outer.addWidget(_heading("New", w))
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)
        for kind, icon in (("Part", "PART"), ("Assembly", "ASSEMBLY"), ("Drawing", "DRAWING")):
            b = _tile(_button(kind, icon, lambda k=kind: self._new(k), "SWWelcomeNew" + kind))
            if b.icon().isNull():
                b.setIcon(_new_icon(kind))
            try:
                from . import newdoc
                b.setEnabled(bool(newdoc.available(kind)))
            except Exception as _fw_err:
                _fw_log("welcome.py:300", _fw_err)
            row.addWidget(b)
        advanced = QtWidgets.QPushButton("Advanced...", w)
        advanced.setObjectName("SWWelcomeAdvanced")
        advanced.setMinimumWidth(120)
        advanced.clicked.connect(lambda checked=False: self._advanced())
        row.addWidget(advanced, 0, Qt.AlignBottom)
        row.addSpacing(16)
        row.addWidget(_divider(w, vertical=True))
        row.addSpacing(16)
        opn = _tile(_button("Open", "STANDARD_OPEN", self._open, "SWWelcomeOpen"))
        opn.setToolTip("Open a document (Ctrl+O).")
        row.addWidget(opn)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addWidget(_divider(w))
        # Recent Documents
        outer.addLayout(_heading_row("Recent Documents", w, lambda: self.tabs.setCurrentIndex(1)))
        self.home_docs = DocumentGrid(w, "SWWelcomeHomeDocuments")
        self.home_docs.empty_text = "No recent documents"
        self.home_docs.setMinimumHeight(THUMB + 48)          # one full row: thumbnail and name
        outer.addWidget(self.home_docs, 2)
        outer.addWidget(_divider(w))
        # Recent Folders | Resources
        split = QtWidgets.QHBoxLayout()
        left = QtWidgets.QVBoxLayout()
        left.addLayout(_heading_row("Recent Folders", w, lambda: self.tabs.setCurrentIndex(1)))
        self.home_folders = _EmptyList(w, "No recent folders")
        self.home_folders.setObjectName("SWWelcomeHomeFolders")
        self.home_folders.itemDoubleClicked.connect(lambda item: self._open(item.data(Qt.UserRole) or item.text()))
        left.addWidget(self.home_folders, 1)
        split.addLayout(left, 1)
        split.addWidget(_divider(w, vertical=True))
        right = QtWidgets.QVBoxLayout()
        right.addWidget(_heading("Resources", w))
        res = QtWidgets.QGridLayout()
        for n, (text, target) in enumerate(LINKS):
            b = _link(text, target, self._resource, _resource_icon(target))
            b.setStyleSheet(LINK_STYLE)
            b.setIconSize(QtCore.QSize(16, 16))
            res.addWidget(b, n // 2, n % 2)
        right.addLayout(res)
        right.addStretch(1)
        split.addLayout(right, 1)
        outer.addLayout(split, 2)

        groups = QtWidgets.QGroupBox("Document Groups", w)
        groups.setObjectName("SWWelcomeDocumentGroups")
        gl = QtWidgets.QVBoxLayout(groups)
        self.home_groups = QtWidgets.QListWidget(groups)
        self.home_groups.setObjectName("SWWelcomeDocumentGroupList")
        self.home_groups.setMaximumHeight(90)
        self.home_groups.itemDoubleClicked.connect(lambda item: self._open_group(item.data(Qt.UserRole)))
        gl.addWidget(self.home_groups)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(_button("Create Document Group...", None, self._create_group, "SWWelcomeCreateDocumentGroup"))
        row.addWidget(_button("Open", "STANDARD_OPEN", lambda: self._open_group(self._picked_group()),
                              "SWWelcomeOpenDocumentGroup"))
        row.addWidget(_button("Delete", None, self._delete_group, "SWWelcomeDeleteDocumentGroup"))
        gl.addLayout(row)
        outer.addWidget(groups)
        self.tip_strip = TipStrip(w)
        outer.addWidget(self.tip_strip)
        self._fill_home()
        return w

    # ---- first-start setup (FreeCAD's first-start panel, in the one Welcome)
    def _setup(self, parent):
        box = QtWidgets.QGroupBox("Set Up FreeCAD", parent)
        box.setObjectName("SWWelcomeSetup")
        form = QtWidgets.QGridLayout(box)
        form.addWidget(QtWidgets.QLabel("Theme:"), 0, 0)
        self.theme = QtWidgets.QComboBox(box)
        self.theme.setObjectName("SWWelcomeTheme")
        from . import style
        for name in style.THEMES:
            self.theme.addItem("FreeCAD " + name, name)
        i = self.theme.findData(style.theme_name())
        self.theme.setCurrentIndex(max(i, 0))
        self.theme.activated.connect(lambda *_: self._apply_theme())
        form.addWidget(self.theme, 0, 1)
        # language
        self.language = QtWidgets.QComboBox(box)
        self.language.setObjectName("SWWelcomeLanguage")
        try:
            locales = Gui.supportedLocales()
            current = Gui.getLocale()
            for name, code in sorted(locales.items()):
                self.language.addItem(name, code)
            i = self.language.findData(current)
            if i < 0:
                i = self.language.findText(current)
            if i < 0:       # no language chosen yet (locale "C"): FreeCAD runs in English
                i = self.language.findData("en")
            self.language.setCurrentIndex(max(i, 0))
            self.language.activated.connect(lambda *_: self._apply_language())
            form.addWidget(QtWidgets.QLabel("Language:"), 1, 0)
            form.addWidget(self.language, 1, 1)
        except Exception:
            self.language.hide()

        self.units = QtWidgets.QComboBox(box)
        self.units.setObjectName("SWWelcomeUnits")
        try:
            names = _unit_schemas()
            now = App.ParamGet("User parameter:BaseApp/Preferences/Units").GetInt("UserSchema", 0)
            for text, index in _sw_unit_systems(names):
                self.units.addItem(text, index)
            if self.units.findData(now) < 0 and 0 <= now < len(names):
                self.units.addItem(names[now], now)          # a FreeCAD-only system someone picked before
            self.units.setCurrentIndex(max(self.units.findData(now), 0))
            self.units.activated.connect(lambda *_: self._apply_units())
            form.addWidget(QtWidgets.QLabel("Units:"), 2, 0)
            form.addWidget(self.units, 2, 1)
        except Exception:
            self.units.hide()
        self.standard = QtWidgets.QComboBox(box)
        self.standard.setObjectName("SWWelcomeStandard")
        try:
            from . import options
            for name in options.STANDARDS:
                self.standard.addItem(name, name)
            self.standard.setCurrentIndex(max(self.standard.findData(options._read_standard()), 0))
            self.standard.activated.connect(lambda *_: self._apply_standard())
            form.addWidget(QtWidgets.QLabel("Dimension standard:"), 3, 0)
            form.addWidget(self.standard, 3, 1)
        except Exception:
            self.standard.hide()
        # navigation style
        self.navigation = QtWidgets.QComboBox(box)
        self.navigation.setObjectName("SWWelcomeNavigation")
        for name, cls in NAVIGATION:
            self.navigation.addItem(name, cls)
        now = App.ParamGet(VIEW_PARAMS).GetString("NavigationStyle", NAVIGATION[0][1])
        self.navigation.setCurrentIndex(max(self.navigation.findData(now), 0))
        self.navigation.activated.connect(lambda *_: self._apply_navigation())
        form.addWidget(QtWidgets.QLabel("Mouse navigation:"), 4, 0)
        form.addWidget(self.navigation, 4, 1)
        done = QtWidgets.QPushButton("Done", box)
        done.setObjectName("SWWelcomeSetupDone")
        done.clicked.connect(self._setup_done)
        form.addWidget(done, 4, 2)
        form.setColumnStretch(1, 1)
        return box

    def show_setup(self):
        self.tabs.setCurrentIndex(0)
        self.setup_box.show()

    def _setup_done(self):
        paths.params().SetBool(SETUP_DONE, True)
        self.setup_box.hide()
        # welcomedark-1120 (AC3): back to the Welcome's own size once the first-start box is gone
        QtCore.QTimer.singleShot(0, self._fit_after_setup)

    def _fit_after_setup(self):
        try:
            height = max(520, self.minimumSizeHint().height(), self._home_height())
            if self.height() > height:
                self.resize(self.width(), height)
        except RuntimeError:        # the Welcome was closed in the meantime
            pass

    def _home_height(self):
        """welcomefit-1121: the dialog height that shows the whole Home page with no scroll bar."""
        try:
            area = self.tabs.widget(0)
            page = area.widget() if hasattr(area, "widget") else None
            if page is None:
                return 0
            self.layout().activate()
            chrome = self.height() - area.viewport().height()
            need = page.heightForWidth(area.viewport().width()) if page.hasHeightForWidth() else -1
            if need <= 0:
                need = page.minimumSizeHint().height()
            return need + max(chrome, 0) + 2
        except Exception as _fw_err:
            _fw_log("welcome.py:welcomefit-1121", _fw_err)
            return 0

    def _grow_to_home(self):
        ""
        height = self._home_height()
        try:    # welcomecap-1121: at most 85 % of the screen (the first-start settings then scroll a little)
            room = (self.screen() or QtGui.QGuiApplication.primaryScreen()).availableGeometry().height()
            height = min(height, int(room * 0.85))
        except Exception as _fw_err:
            _fw_log("welcome.py:welcomecap-1121", _fw_err)
        if height > self.height():
            self.resize(self.width(), height)

    def _apply_theme(self):
        from . import firststart
        firststart._picked(self.theme.currentData())

    def _apply_language(self):
        code = self.language.currentData()
        try:
            Gui.setLocale(code)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: language not changed: %s\n" % error)

    def _apply_units(self):
        i = int(self.units.currentData())
        App.ParamGet("User parameter:BaseApp/Preferences/Units").SetInt("UserSchema", i)
        try:
            App.Units.setSchema(i)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: unit system not changed: %s\n" % error)

    def _apply_standard(self):
        try:
            from . import options
            options._write_standard(self.standard.currentData())
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: dimension standard not changed: %s\n" % error)

    def _apply_navigation(self):
        cls = self.navigation.currentData()
        App.ParamGet(VIEW_PARAMS).SetString("NavigationStyle", cls)
        for doc in App.listDocuments().values():
            gdoc = Gui.getDocument(doc.Name)
            for view in (gdoc.mdiViewsOfType("Gui::View3DInventor") if gdoc else []):
                try:
                    view.setNavigationType(cls)
                except Exception as _fw_err:
                    _fw_log("welcome.py:470", _fw_err)

    def _fill_groups(self):
        lst = getattr(self, "home_groups", None)
        if lst is None:
            return
        lst.clear()
        for name, files in document_groups():
            item = QtWidgets.QListWidgetItem("%s (%d)" % (name, len(files)))
            item.setData(Qt.UserRole, name)
            item.setToolTip("\n".join(files))
            lst.addItem(item)

    def _picked_group(self):
        item = self.home_groups.currentItem() if getattr(self, "home_groups", None) is not None else None
        return item.data(Qt.UserRole) if item is not None else None

    def _create_group(self, name=None):
        files = open_documents()
        if not files:
            QtWidgets.QMessageBox.information(self, "Create Document Group",
                                              "Open and save the documents for the group first.")
            return False
        if name is None:
            name, ok = QtWidgets.QInputDialog.getText(self, "Create Document Group", "Group name:")
            if not ok:
                return False
        ok = save_document_group(name, files)
        self._fill_groups()
        return ok

    def _open_group(self, name):
        if not name:
            return []
        self.accept()
        return open_document_group(name)

    def _delete_group(self):
        name = self._picked_group()
        if name and delete_document_group(name):
            self._fill_groups()

    def _fill_home(self):
        self._fill_groups()
        self.home_docs.fill()
        self.home_folders.clear()
        from . import simicons
        folder_icon = simicons.picture("FW_Folder")
        for d in recent_folders():
            item = QtWidgets.QListWidgetItem(folder_icon, d)
            item.setData(Qt.UserRole, d)
            item.setToolTip(d)
            self.home_folders.addItem(item)

    def _new(self, kind):
        from . import newdoc
        self.accept()
        # made once the Welcome dialog's own event loop has ended (item 153: an assembly made
        # inside it, with its Insert Components dialog coming up, ended FreeCAD on Windows)
        QtCore.QTimer.singleShot(0, lambda: newdoc.make(kind))

    def _advanced(self):
        from . import newdoc
        self.accept()
        paths.params().SetString(newdoc.VIEW, "advanced")
        newdoc.ask()

    def _open(self, folder=None):
        from . import saveas
        box = saveas.open_dialog()
        if folder and os.path.isdir(folder):
            box.setDirectory(folder)
        self.hide()
        if box.exec():
            paths_ = box.selectedFiles()
            mode = box.mode.currentText()
            speedpak = box.speedpak.isEnabled() and box.speedpak.isChecked()
            skip = box.skip_hidden.isEnabled() and box.skip_hidden.isChecked()
            for p in paths_:
                remember_folder(os.path.dirname(p))
            if getattr(box, "previous_version", None):
                # open124: Show previous versions: the save picked (read-only), not the current file
                paths_ = [saveas._version_copy(box.previous_version)]
                saveas._PENDING.clear()
                saveas._PENDING[os.path.normcase(os.path.abspath(paths_[0]))] = (None, None, True)
            saveas.open_files(paths_, mode, speedpak, skip)     # open124: a file that does not open says why
            self.accept()
        else:
            self.show()

    def _resource(self, target):
        if target == "whatsnew":
            from . import helpmenu
            helpmenu.show("whatsnew")
        elif target == "tutorials":
            from . import helpmenu
            helpmenu.show("tutorials")
        elif target == "samples":
            self.tabs.setCurrentIndex(2)
            self.samples.setFocus()
        else:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(target))

    # ---- Recent
    def _recent(self):
        w = QtWidgets.QWidget()
        w.setObjectName("SWWelcomeRecent")
        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(QtWidgets.QLabel("<b>Documents</b>"))
        self.recent_docs = DocumentGrid(w, "SWWelcomeRecentDocuments")
        lay.addWidget(self.recent_docs, 2)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(_button("Browse...", "STANDARD_OPEN", self._open, "SWWelcomeBrowse"))
        row.addWidget(_button("Clear", None, self._clear_docs, "SWWelcomeClearDocuments"))
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(QtWidgets.QLabel("<b>Folders</b>"))
        self.recent_folders = QtWidgets.QListWidget(w)
        self.recent_folders.setObjectName("SWWelcomeRecentFolders")
        self.recent_folders.itemDoubleClicked.connect(lambda item: self._open(item.text()))
        lay.addWidget(self.recent_folders, 1)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(_button("Clear", None, self._clear_folders, "SWWelcomeClearFolders"))
        row.addStretch(1)
        lay.addLayout(row)
        self._fill_recent()
        return w

    def _fill_recent(self):
        self.recent_docs.fill()
        self.recent_folders.clear()
        for d in recent_folders():
            self.recent_folders.addItem(d)

    def _clear_docs(self):
        clear_recent_files()
        self._fill_recent()
        self._fill_home()

    def _clear_folders(self):
        clear_recent_folders()
        self._fill_recent()
        self._fill_home()

    # ---- Learn
    def _learn(self):
        w = QtWidgets.QWidget()
        w.setObjectName("SWWelcomeLearn")
        lay = QtWidgets.QHBoxLayout(w)
        col = QtWidgets.QVBoxLayout()
        grid = QtWidgets.QGridLayout()
        for n, (text, target, tip) in enumerate(LEARN):
            b = _link(text, target, self._resource, _learn_art(target))
            b.setDescription(tip)
            b.setIconSize(QtCore.QSize(40, 40))
            b.setMinimumWidth(170)
            grid.addWidget(b, n // 2, n % 2)
        col.addLayout(grid)
        col.addStretch(1)
        lay.addLayout(col)
        box = QtWidgets.QGroupBox("Sample Models", w)
        bl = QtWidgets.QVBoxLayout(box)
        self.samples = QtWidgets.QListWidget(box)
        self.samples.setObjectName("SWWelcomeSamples")
        self.samples.itemDoubleClicked.connect(lambda item: (open_file(item.data(Qt.UserRole)), self.accept()))
        folder = samples_dir()
        if folder:
            for name in sorted(os.listdir(folder)):
                if name.lower().endswith(".fcstd"):
                    item = QtWidgets.QListWidgetItem(name)
                    item.setData(Qt.UserRole, os.path.join(folder, name))
                    self.samples.addItem(item)
        bl.addWidget(self.samples)
        bl.addWidget(QtWidgets.QLabel("Double-click a model to open it."))
        lay.addWidget(box, 1)
        return w

    # ---- Alerts
    def _alerts(self):
        w = QtWidgets.QWidget()
        w.setObjectName("SWWelcomeAlerts")
        lay = QtWidgets.QVBoxLayout(w)
        self.alerts = QtWidgets.QTextBrowser(w)
        self.alerts.setObjectName("SWWelcomeAlertsText")
        self.alerts.setOpenExternalLinks(True)
        lay.addWidget(self.alerts, 1)
        self._fill_alerts()
        return w

    def _fill_alerts(self):
        try:
            from . import helpmenu
            if not helpmenu.news_wanted():
                self.alerts.setHtml(alerts_html(""))
                return
            self.alerts.setHtml(alerts_html(helpmenu.news_html()))
            if helpmenu._NEWS["items"] is None:
                from .widgets import alive
                # the dialog may be closed (and deleted) before the news arrives
                helpmenu.fetch_news(lambda: self.alerts.setHtml(alerts_html(helpmenu.news_html()))
                                    if alive(self) and self.isVisible() else None)
        except Exception as error:
            self.alerts.setHtml("<p><i>%s</i></p>" % error)


class _CloseOnDocument:
    ""


    def __init__(self):
        self.on = False

    def start(self):
        if not self.on:
            App.addDocumentObserver(self)
            self.on = True

    def stop(self):
        if self.on:
            self.on = False
            try:
                App.removeDocumentObserver(self)
            except Exception as _fw_err:
                _fw_log("welcome.py:682", _fw_err)

    def slotCreatedDocument(self, doc):
        QtCore.QTimer.singleShot(0, close_for_document)


_closer = _CloseOnDocument()


def close_for_document():
    """Closes the open Welcome dialog (a document has opened)."""
    _closer.stop()
    from .widgets import alive
    box = _open[0] if _open else None
    if box is not None and alive(box) and box.isVisible():
        box.close()


def show(tab=0):
    """Opens the Welcome dialog (one at a time) on the tab index given; returns it."""
    from .widgets import alive
    box = _open[0] if _open and alive(_open[0]) and _open[0].isVisible() else None
    fresh = box is None
    if box is None:
        box = WelcomeDialog()
        box.setAttribute(Qt.WA_DeleteOnClose, True)
        box.destroyed.connect(lambda *_: _closer.stop())
        _open[:] = [box]
    _closer.start()
    box.tabs.setCurrentIndex(tab)
    box.show()
    if fresh:
        box._grow_to_home()         # welcomefit-1121 (then _fit_screen keeps it on the screen)
    _fit_screen(box)
    box.raise_()
    box.activateWindow()
    return box


def _scrolled(page):
    """welcomefit-1120: the Home page in a frameless scroll area: on a small screen (1366 x 768, or 150 % scaling) the
    first-start settings, New, Recent and Document Groups are taller than the screen, so the page
    scrolls inside the dialog instead of pushing the dialog's bottom (tips, Close) off the screen."""
    area = QtWidgets.QScrollArea()
    area.setObjectName(page.objectName() + "Scroll")
    area.setWidgetResizable(True)
    area.setFrameShape(QtWidgets.QFrame.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    lay = page.layout()
    if lay is not None:     # welcomeview-1120: a gap before the scroll bar, so "View all" is not cut against it
        m = lay.contentsMargins()
        lay.setContentsMargins(m.left(), m.top(), max(m.right(), 10), m.bottom())
    area.setWidget(page)
    return area


def _fit_screen(box):
    """Keeps the whole dialog, frame included, on the screen it opens on."""
    try:
        screen = box.screen() or QtGui.QGuiApplication.primaryScreen()
        room = screen.availableGeometry()
        frame = box.frameGeometry()
        fw, fh = frame.width() - box.width(), frame.height() - box.height()
        w, h = min(box.width(), room.width() - fw), min(box.height(), room.height() - fh)
        if (w, h) != (box.width(), box.height()):
            box.resize(max(w, 200), max(h, 200))
        frame = box.frameGeometry()
        x = min(max(frame.x(), room.x()), room.x() + room.width() - frame.width())
        y = min(max(frame.y(), room.y()), room.y() + room.height() - frame.height())
        if (x, y) != (frame.x(), frame.y()):
            box.move(x, y)
    except Exception as _fw_err:
        _fw_log("welcome.py:fit", _fw_err)


def _unit_schemas():
    """The unit systems' names, in FreeCAD's order (the UserSchema index)."""
    listed = App.Units.listSchemas()
    if isinstance(listed, int):
        return [App.Units.listSchemas(i) for i in range(listed)]
    return [str(x) for x in listed]


def _sw_unit_systems(names):
    ""
    from .chrome import UnitsButton
    out = []
    for _label, text, wanted in UnitsButton.SYSTEMS:
        index = next((names.index(n) for n in wanted if n in names), -1)
        if index >= 0:
            out.append((text, index))
    return out


def stock_first_start():
    """FreeCAD's own first-start panel on the Start page (theme row, settings, Done), when it is up."""
    mw = Gui.getMainWindow()
    for widget in (mw.findChildren(QtWidgets.QWidget, START_WIDGET) if mw else []):
        try:
            if not widget.isVisible():
                continue
            panel = widget.parentWidget()
            while panel is not None:
                names = ("Done", QtWidgets.QApplication.translate("StartGui::StartView", "Done"))
                done = [b for b in panel.findChildren(QtWidgets.QPushButton)
                        if b.isVisible() and b.text().replace("&", "") in names]
                if done:
                    return done[-1]
                panel = panel.parentWidget()
        except RuntimeError:
            continue
    return None


def merge_first_start():
    ""



    button = stock_first_start()
    if button is None:
        return False
    paths.params().SetBool(SETUP_DONE, False)      # a first start: the Welcome shows the setup box
    try:
        button.click()
    except RuntimeError:
        # cleaninstall-1120: the Start page rebuilt its panel between finding Done and pressing it (its
        # C++ button already deleted): press the live one; none left means the panel is closed already
        again = stock_first_start()
        if again is not None:
            try:
                again.click()
            except RuntimeError as _fw_err:
                _fw_log("welcome.py:first_start", _fw_err)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: first-start panel: %s\n" % error)
        return False
    return True


def show_at_startup():
    ""
    from . import startswitch      # startswitch-1127: the Start page picked last: no Welcome
    if startswitch.screen() == "start":
        hidden = paths.params().GetBool(START_HIDDEN, False)
        sync_start_page()
        startswitch.at_startup(hidden)
        return None
    first = merge_first_start()
    if (not at_startup() and not first) or App.listDocuments():
        return None
    box = show()
    if first:
        box.show_setup()
    else:
        sync_start_page()       # startup-1120 N2b: from the next start-up on, no Start page behind the Welcome
    App.Console.PrintLog("FreeCAD: Welcome at start-up\n")
    # later, not now: FreeCAD's Start page has its own timers just after start-up and after its
    # first-start Done (a close at once crashed FreeCAD in StartGui's timer slot)
    QtCore.QTimer.singleShot(START_CLOSE_DELAY, _close_start_if_welcome)
    return box


START_CLOSE_DELAY = 3000


def _close_start_if_welcome():
    """The Welcome came up at start-up: close the Start page behind it (the Welcome may have been
    closed or opened again since, so its object is not looked at)."""
    try:
        App.Console.PrintLog("FreeCAD: Start page closed behind the Welcome: %d\n" % close_start_page())
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Start page close: %r\n" % error)


def close_start_page():
    ""

    mw = Gui.getMainWindow()
    area = mw.findChild(QtWidgets.QMdiArea) if mw else None
    if area is None:
        return 0
    closed = 0
    for sub in area.subWindowList():
        try:
            view = sub.widget()
            if view is not None and view.metaObject().className() == "StartGui::StartView":
                sub.close()
                closed += 1
        except RuntimeError:
            continue
    return closed


class WelcomeCommand:
    def GetResources(self):
        return {"MenuText": "Welcome to FreeCAD", "ToolTip": "Opens the Welcome dialog (Ctrl+F2).",
                "Pixmap": "", "Accel": "Ctrl+F2"}

    def Activated(self):
        show()

    def IsActive(self):
        return True


def register():
    if Gui.Command.get(COMMAND) is None:
        Gui.addCommand(COMMAND, WelcomeCommand())
    from . import startswitch      # startswitch-1127: theme and switch on every Start page
    QtCore.QTimer.singleShot(2000, startswitch.start)
