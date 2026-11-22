# SPDX-License-Identifier: LGPL-2.1-or-later
""




















import os
import re

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

Qt = QtCore.Qt
HERE = os.path.dirname(os.path.abspath(__file__))
GUIDE = os.path.join(HERE, "resources", "guide")
BROWSER = "GuideInBrowser"         # in the add-on's own preference group (paths.params())

CHAPTERS = (
    ("index.html", "Contents"),
    ("01-getting-started.html", "1. Getting started"),
    ("02-interface.html", "2. A tour of the window"),
    ("03-sketching.html", "3. Sketching"),
    ("04-features.html", "4. Features"),
    ("05-assemblies.html", "5. Assemblies"),
    ("06-drawings.html", "6. Drawings"),
    ("07-slicer.html", "7. 3D printing (Slicer tab)"),
    ("08-options.html", "8. Options"),
    ("09-shortcuts.html", "9. Keys and mouse"),
    ("10-install-troubleshooting.html", "10. Installing and troubleshooting"),
    ("11-simulation.html", "11. Simulation walkthrough"),
    ("12-whats-new.html", "12. What's new in this beta"),
    ("13-if-you-know-cad.html", "13. If you already know another CAD program"),
    ("14-tutorials.html", "14. Tutorials"),
    ("15-error-messages.html", "15. Error messages and what to do"),
    ("16-dialogs.html", "16. Dialog boxes"),
    ("17-reference-part.html", "17. Command reference: parts and sketches"),
    ("18-reference-assembly-drawing.html", "18. Command reference: assemblies and drawings"),
    ("19-reference-other.html", "19. Command reference: views, relations and the rest"),
)

opened = []         # (page, anchor, where) for every page opened, for checks


def params():
    from . import paths
    return paths.params()


def in_browser():
    return params().GetBool(BROWSER, False)


def set_in_browser(on):
    params().SetBool(BROWSER, bool(on))


def path(page):
    return os.path.join(GUIDE, page)


def available():
    """The chapter files that are there (all eleven in a normal install)."""
    return [p for p, _t in CHAPTERS if os.path.isfile(path(p))]


def url(page, anchor=""):
    u = QtCore.QUrl.fromLocalFile(path(page))
    if anchor:
        u.setFragment(anchor)
    return u


# --------------------------------------------------------------------------- what is on screen
def _visible_box(*titles):
    """The title of a visible top-level dialog whose title starts with one of the words, else ''."""
    try:
        for w in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(w, QtWidgets.QDialog) and w.isVisible():
                t = w.windowTitle() or ""
                for word in titles:
                    if t.startswith(word):
                        return word
    except Exception:
        pass
    return ""


def _editing_sketch():
    try:
        doc = Gui.ActiveDocument
        vp = doc.getInEdit() if doc is not None else None
        obj = getattr(vp, "Object", None)
        return obj is not None and obj.isDerivedFrom("Sketcher::SketchObject")
    except Exception:
        return False


def _drawing():
    try:
        from . import swmenus
        return bool(swmenus.drawing_in_front())
    except Exception:
        doc = App.ActiveDocument
        return doc is not None and any(o.isDerivedFrom("TechDraw::DrawPage") for o in doc.Objects)


def _assembly():
    try:
        from . import asmcore
        return bool(asmcore.is_assembly(App.ActiveDocument))
    except Exception:
        doc = App.ActiveDocument
        return doc is not None and any(o.TypeId == "Assembly::AssemblyObject" for o in doc.Objects)


def _panel_title():
    """The window title of the open task panel's first page ('' when none is open)."""
    try:
        dlg = Gui.Control.activeDialog()
    except Exception:
        dlg = False
    if not dlg:
        return ""
    try:
        mw = Gui.getMainWindow()
        for name in ("Combo View", "Tasks", "Model"):
            dock = mw.findChild(QtWidgets.QDockWidget, name)
            if dock is None or not dock.isVisible():
                continue
            for box in dock.findChildren(QtWidgets.QWidget):
                if box.isVisible() and box.windowTitle():
                    return box.windowTitle()
    except Exception:
        pass
    return "panel"


def context():
    """(page, anchor) of the guide page for what is on screen now."""
    box = _visible_box("Customize", "Options", "System Options", "Document Properties")
    if box == "Customize":
        return "08-options.html", "customize"
    if box:
        return "08-options.html", ""
    if _editing_sketch():
        return "03-sketching.html", ""
    if App.ActiveDocument is None:
        return "01-getting-started.html", ""
    if _drawing():
        return "06-drawings.html", ""
    if _assembly():
        return "05-assemblies.html", ""
    title = _panel_title()
    if title and "slic" in title.lower():
        return "07-slicer.html", ""
    return "04-features.html", ""


# --------------------------------------------------------------------------- the window
class GuideWindow(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("FWGuideWindow")
        self.setWindowTitle("FreeCAD User Guide")
        self.resize(940, 660)
        lay = QtWidgets.QVBoxLayout(self)
        bar = QtWidgets.QHBoxLayout()
        self.back = QtWidgets.QPushButton("Back")
        self.forward = QtWidgets.QPushButton("Forward")
        self.external = QtWidgets.QPushButton("Open in Browser")
        self.external.setObjectName("FWGuideBrowser")
        for b in (self.back, self.forward):
            b.setEnabled(False)
            bar.addWidget(b)
        bar.addStretch(1)
        bar.addWidget(self.external)
        lay.addLayout(bar)
        body = QtWidgets.QHBoxLayout()
        self.contents = QtWidgets.QListWidget()
        self.contents.setObjectName("FWGuideContents")
        self.contents.setMaximumWidth(240)
        for page, title in CHAPTERS:
            item = QtWidgets.QListWidgetItem(title)
            item.setData(Qt.UserRole, page)
            self.contents.addItem(item)
        body.addWidget(self.contents)
        self.view = QtWidgets.QTextBrowser()
        self.view.setObjectName("FWGuideView")
        self.view.setOpenLinks(False)
        self.view.setSearchPaths([GUIDE])
        body.addWidget(self.view, 1)
        lay.addLayout(body, 1)
        self.contents.itemClicked.connect(lambda item: self.show_page(item.data(Qt.UserRole)))
        self.view.anchorClicked.connect(self.link)
        self.view.backwardAvailable.connect(self.back.setEnabled)
        self.view.forwardAvailable.connect(self.forward.setEnabled)
        self.back.clicked.connect(self.view.backward)
        self.forward.clicked.connect(self.view.forward)
        self.view.sourceChanged.connect(self._mark)
        self.external.clicked.connect(lambda: open_external(self.page(), ""))

    def page(self):
        return os.path.basename(self.view.source().toLocalFile()) or "index.html"

    def show_page(self, page, anchor=""):
        self.view.setSource(url(page, anchor))
        if anchor:
            self.view.scrollToAnchor(anchor)
        self._mark()

    def link(self, u):
        if u.isRelative() or u.isLocalFile():
            target = u if u.isLocalFile() else self.view.source().resolved(u)
            name = os.path.basename(target.toLocalFile())
            if name and os.path.isfile(path(name)):
                self.show_page(name, target.fragment())
                return
            if not name and u.fragment():
                self.view.scrollToAnchor(u.fragment())
                return
        if u.scheme() in ("http", "https"):
            if not os.environ.get("FREEWORKS_NO_BROWSER"):
                QtGui.QDesktopServices.openUrl(u)
            opened.append((u.toString(), "", "web"))

    def _mark(self, _url=None):
        """The contents row of the page on show is the current row (also after Back and Forward)."""
        name = self.page()
        self.contents.blockSignals(True)
        try:
            for r in range(self.contents.count()):
                if self.contents.item(r).data(Qt.UserRole) == name:
                    self.contents.setCurrentRow(r)
                    break
        finally:
            self.contents.blockSignals(False)


_WINDOW = []


def window():
    """The guide window if one is open and alive."""
    try:
        if _WINDOW and _WINDOW[0].objectName() == "FWGuideWindow":
            return _WINDOW[0]
    except RuntimeError:
        pass
    _WINDOW[:] = []
    return None


def open_external(page, anchor=""):
    u = url(page, anchor)
    opened.append((page, anchor, "browser"))
    if not os.environ.get("FREEWORKS_NO_BROWSER"):
        QtGui.QDesktopServices.openUrl(u)
    return u


def show(page="index.html", anchor=""):
    """Open a guide page: in the guide window, or in the browser when GuideInBrowser is on."""
    if not os.path.isfile(path(page)):
        App.Console.PrintWarning("User Guide: the page %s is missing (%s)\n" % (page, GUIDE))
        page, anchor = "index.html", ""
        if not os.path.isfile(path(page)):
            return None
    if in_browser():
        return open_external(page, anchor)
    win = window()
    if win is None:
        win = GuideWindow()
        _WINDOW[:] = [win]
    win.show_page(page, anchor)
    win.show()
    win.raise_()
    win.activateWindow()
    opened.append((page, anchor, "window"))
    return win


MAP = "helpmap.json"          # resources/guide: {"cmd": {key: "page#anchor"}, "pm": {...}, "dlg": {...}, "native": {...}}
_MAP = []


def helpmap():
    """The command / PropertyManager / dialog -> guide entry tables ({} when the file is missing)."""
    if not _MAP:
        data = {}
        try:
            import json
            with open(path(MAP), encoding="utf-8") as f:
                data = json.load(f)
        except Exception as error:
            App.Console.PrintLog("User Guide: no %s (%s)\n" % (MAP, error))
        _MAP[:] = [data]
    return _MAP[0]


def _norm(text):
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def _live(ref):
    """(page, anchor) of a map entry whose page is there, else None."""
    if not ref:
        return None
    page, _sep, anchor = ref.partition("#")
    return (page, anchor) if os.path.isfile(path(page)) else None


def target_for_pm(title):
    """(page, anchor) for a PropertyManager title, else None: the title, then without its trailing number
    ("Edge-Flange1"), then without anything in brackets."""
    table = helpmap().get("pm", {})
    title = (title or "").strip()
    for name in (title, title.rstrip("0123456789"), re.sub(r"\s*[(\[].*?[)\]]", "", title)):
        found = _live(table.get(_norm(name)))
        if found:
            return found
    return None


def target_for_command(key):
    """(page, anchor) for a command's catalog key (or a FreeCAD command name), else None."""
    table = helpmap()
    return _live(table.get("cmd", {}).get(key) or table.get("cmd", {}).get(table.get("native", {}).get(key, "")))


def target_for_topic(name):
    """(page, anchor) for a dialog's name ("page setup", "pack and go"...), else None."""
    return _live(helpmap().get("dlg", {}).get((name or "").strip().lower()))


def _open(target):
    return show(target[0], target[1]) if target else None


def show_pm(title):
    """Open the guide entry of a PropertyManager. None (nothing opened) when it has none."""
    return _open(target_for_pm(title))


def show_command(key):
    """Open the guide entry of a command. None (nothing opened) when it has none."""
    return _open(target_for_command(key))


def show_topic(name):
    """Open the guide section of a dialog box. None (nothing opened) when it has none."""
    return _open(target_for_topic(name))


def command_under_pointer():
    """The catalog key of the command button (or open menu row) the pointer is on, else ''."""
    try:
        menu = QtWidgets.QApplication.activePopupWidget()
        action = menu.activeAction() if menu is not None and hasattr(menu, "activeAction") else None
        if action is not None and action.objectName():
            key = helpmap().get("native", {}).get(action.objectName(), "")
            if key:
                return key
    except Exception as error:
        App.Console.PrintLog("User Guide: menu row: %s\n" % error)
    try:
        widget = QtWidgets.QApplication.widgetAt(QtGui.QCursor.pos())
    except Exception:
        return ""
    while widget is not None:
        key = getattr(getattr(getattr(widget, "binding", None), "cmd", None), "key", "")
        if key and isinstance(key, str):
            return key
        widget = widget.parentWidget()
    return ""


def show_context():
    """F1: the command under the pointer, else the open PropertyManager's entry (as its "?"), else the guide
    page for what is on screen."""
    try:
        key = command_under_pointer()
        if key and show_command(key) is not None:
            return True
    except Exception as error:
        App.Console.PrintLog("FreeCAD help: F1 command: %s\n" % error)
    try:
        from . import cmdhelp
        if cmdhelp.open_pm_title():
            return cmdhelp.show_context()
    except Exception as error:
        App.Console.PrintLog("FreeCAD help: F1: %s\n" % error)
    page, anchor = context()
    return show(page, anchor)


# --------------------------------------------------------------------------- commands
class _Cmd:
    def __init__(self, menu, tip, run, checkable=False):
        self.menu, self.tip, self.run, self.checkable = menu, tip, run, checkable

    def GetResources(self):
        r = {"MenuText": self.menu, "ToolTip": self.tip}
        if self.checkable:
            r["Checkable"] = in_browser()
        return r

    def Activated(self, checked=None):
        if self.checkable:
            set_in_browser(bool(checked) if checked is not None else not in_browser())
            return
        self.run()

    def IsActive(self):
        return True


COMMANDS = {
    "FreeWorks_UserGuide": ("User Guide", "The User Guide, on this computer",
                            lambda: show("index.html")),
    "FreeWorks_ContextHelp": ("Help on This", "The User Guide page for what you are doing (F1)", show_context),
    "FreeWorks_GuideInBrowser": ("Open Guide in Browser", "Open User Guide pages in your web browser instead of "
                                 "the guide window", None),
}


def register():
    for name, (menu, tip, run) in COMMANDS.items():
        if Gui.Command.get(name) is None:
            Gui.addCommand(name, _Cmd(menu, tip, run, checkable=name == "FreeWorks_GuideInBrowser"))
    try:
        from . import checkstate
        checkstate.register("FreeWorks_GuideInBrowser", in_browser)
    except Exception:
        pass
