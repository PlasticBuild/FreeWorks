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

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import FreeCAD as App

from . import slicer, slicerupdate

SKIP = ("unins", "uninstall", "vc_redist", "vcredist", "crashpad", "qtwebengineprocess", "updater", "setup")
SILENT = (("/S", "/D={dir}"), ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DIR={dir}"))


def registry():
    try:
        return json.loads(slicer.params().GetString("Apps", "[]"))
    except ValueError:
        return []


def save(apps):
    slicer.params().SetString("Apps", json.dumps(apps))


def apps_root():
    path = Path(App.getUserAppDataDir()) / "SolidWorksStyle" / "slicer-apps" / "added"
    path.mkdir(parents=True, exist_ok=True)
    return path


def key_for(name):
    return "app_" + "".join(c.lower() if c.isalnum() else "_" for c in Path(name).stem).strip("_")[:40]


def kind(path):
    """zip | exe | msi | other"""
    p = str(path).lower()
    if p.endswith(".zip"):
        return "zip" if zipfile.is_zipfile(path) else "other"
    if p.endswith(".msi"):
        return "msi"
    if p.endswith(".exe"):
        return "exe"
    return "other"


def signer(path):
    """Who signed the file (Windows Authenticode), or None."""
    if sys.platform != "win32":
        return None
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "$s=Get-AuthenticodeSignature -LiteralPath $args[0]; if($s.SignerCertificate){$s.Status; $s.SignerCertificate.Subject}",
             str(path)], capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip().splitlines()
        return " | ".join(out) if out else None
    except Exception as _fw_err:
        _fw_log("slicerapps.py:81", _fw_err)
        return None


def find_main_exe(folder):
    """The slicer's program in a folder: the biggest .exe that is not an uninstaller or helper, preferring
    the shallowest."""
    hits = []
    for p in Path(folder).rglob("*.exe"):
        if any(s in p.name.lower() for s in SKIP):
            continue
        hits.append((len(p.parts), -p.stat().st_size, p))
    hits.sort()
    return hits[0][2] if hits else None


def add_file(path, confirm=None, progress=None):
    """Add the slicer in path. confirm(text) -> bool is asked before an installer runs. Returns the registry
    entry {key, title, exe, source}; raises RuntimeError with a reason."""
    path = Path(path)
    k = kind(path)
    if k == "other":
        raise RuntimeError("Drop a slicer's installer (.exe, .msi) or a .zip.")
    key = key_for(path.name)
    title = path.stem.replace("_", " ").replace("-", " ")
    dest = apps_root() / key
    if k == "zip":
        slicerupdate.unpack(path, dest)
        exe = find_main_exe(dest)
    elif sys.platform != "win32":
        raise RuntimeError("Installers can only be added on Windows.")
    else:
        who = signer(path)
        text = "Run %s?\n\nSigned by: %s\n\nIt will be installed into FreeCAD's own folder, not Program Files." % (
            path.name, who or "NOT SIGNED - only continue if you trust where you got it")
        if confirm is not None and not confirm(text):
            raise RuntimeError("Cancelled.")
        dest.mkdir(parents=True, exist_ok=True)
        exe = None
        if k == "msi":
            subprocess.run(["msiexec", "/a", str(path), "/qn", "TARGETDIR=" + str(dest)], timeout=900)
            exe = find_main_exe(dest)
        else:
            for flags in SILENT:
                args = [str(path)] + [f.format(dir=dest) for f in flags]
                try:
                    subprocess.run(args, timeout=900)
                except (OSError, subprocess.SubprocessError):
                    continue
                exe = find_main_exe(dest)
                if exe:
                    break
            if exe is None:
                # silent flags not understood: let the user run it, then look in the usual place
                subprocess.run([str(path)], timeout=1800)
                exe = find_new_program(title)
    if exe is None:
        raise RuntimeError("Could not find the program after adding %s." % path.name)
    entry = {"key": key, "title": title, "exe": str(exe), "source": path.name}
    apps = [a for a in registry() if a["key"] != key]
    apps.append(entry)
    save(apps)
    return entry


def find_new_program(title):
    """Look for a program in Program Files whose folder looks like the slicer's title."""
    word = title.split()[0].lower() if title.split() else ""
    for var in ("ProgramFiles", "ProgramW6432", "LOCALAPPDATA"):
        root = os.environ.get(var)
        if not root or not word:
            continue
        for folder in Path(root).glob("*"):
            if word in folder.name.lower() and folder.is_dir():
                exe = find_main_exe(folder)
                if exe:
                    return exe
    return None


def remove(key):
    save([a for a in registry() if a["key"] != key])
    drop_button(key)


def open_app(entry):
    from . import slicertab
    return slicertab.open_tab(entry["key"], entry["title"], entry["exe"])


# ---------------------------------------------------------------------- the box
def _dialog_class():
    from PySide import QtCore, QtWidgets

    class Drop(QtWidgets.QLabel):
        dropped = QtCore.Signal(str)

        def __init__(self):
            super().__init__("Drop a slicer's installer (.exe, .msi) or .zip here")
            self.setAlignment(QtCore.Qt.AlignCenter)
            self.setMinimumHeight(110)
            self.setAcceptDrops(True)
            self.setObjectName("SWStyle_SlicerDrop")
            self.setStyleSheet("QLabel#SWStyle_SlicerDrop{border:2px dashed #7fb2e5;}")

        def dragEnterEvent(self, e):
            if e.mimeData().hasUrls():
                e.acceptProposedAction()

        def dropEvent(self, e):
            for url in e.mimeData().urls():
                if url.isLocalFile():
                    self.dropped.emit(url.toLocalFile())

    class Box(QtWidgets.QDialog):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle("Slicer Apps")
            self.resize(460, 360)
            lay = QtWidgets.QVBoxLayout(self)
            self.drop = Drop()
            self.drop.dropped.connect(self.add)
            lay.addWidget(self.drop)
            row = QtWidgets.QHBoxLayout()
            browse = QtWidgets.QPushButton("Browse...")
            browse.clicked.connect(self.browse)
            row.addWidget(browse)
            row.addStretch(1)
            lay.addLayout(row)
            self.list = QtWidgets.QListWidget()
            self.list.itemDoubleClicked.connect(lambda *_: self.open())
            self.list.setToolTip("Double-click to open a slicer in its tab")
            lay.addWidget(self.list, 1)
            row = QtWidgets.QHBoxLayout()
            self.buttons = {}
            for text, fn in (("Open", self.open), ("Remove", self.remove), ("Close", self.close)):
                b = QtWidgets.QPushButton(text)
                b.setObjectName("SWStyle_SlicerApps" + text)
                b.clicked.connect(fn)
                row.addWidget(b)
                self.buttons[text] = b
            lay.addLayout(row)
            self.note = QtWidgets.QLabel("")
            self.note.setObjectName("SWStyle_SlicerAppsNote")
            self.note.setWordWrap(True)
            lay.addWidget(self.note)
            self.list.currentItemChanged.connect(lambda *_: self._follow())
            self.refresh()

        def refresh(self):
            self.list.clear()
            for a in registry():
                item = QtWidgets.QListWidgetItem("%s   (%s)" % (a["title"], a["exe"]))
                item.setData(QtCore.Qt.UserRole, a["key"])
                self.list.addItem(item)
            if self.list.count():
                self.list.setCurrentRow(0)
            elif not self.note.text():
                self.note.setText("No slicer added yet. Drop its installer or zip on the box above, or use Browse.")
            self._follow()

        def _follow(self):
            """sl174: Open and Remove act on the slicer picked in the list: greyed while none is (they did nothing)."""
            on = self.list.currentItem() is not None
            for text in ("Open", "Remove"):
                self.buttons[text].setEnabled(on)

        def browse(self):
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Slicer installer or zip", "",
                                                            "Installers (*.exe *.msi *.zip)")
            if path:
                self.add(path)

        def ask(self, text):
            return QtWidgets.QMessageBox.question(self, "Run installer", text) == QtWidgets.QMessageBox.Yes

        def add(self, path):
            self.note.setText("Adding %s ..." % Path(path).name)
            QtWidgets.QApplication.processEvents()
            try:
                entry = add_file(path, confirm=self.ask)
            except Exception as error:
                # extapps163: Add-Ins buttons, no tabs of their own
                self.note.setText(str(error))
                return
            self.note.setText("Added %s. It is in the 3D Slicer menu of the Add-Ins tab." % entry["title"])
            self.refresh()
            add_button(entry)
            open_app(entry)

        def _current(self):
            item = self.list.currentItem()
            key = item.data(QtCore.Qt.UserRole) if item else None
            return next((a for a in registry() if a["key"] == key), None)

        def open(self):
            a = self._current()
            if a:
                open_app(a)

        def remove(self):
            a = self._current()
            if a:
                remove(a["key"])
                self.note.setText("Removed %s from the list and the 3D Slicer menu. Its files stay where they are."
                                  % a["title"])
                self.refresh()
    return Box


def open_box(parent=None):
    box = _dialog_class()(parent)
    box.show()
    return box


class AppsCommand:
    def GetResources(self):
        from . import slicerui
        return {"MenuText": "Slicer Apps", "ToolTip": "Add another slicer by dropping its installer",
                "Pixmap": slicerui._icon("apps")}

    def Activated(self):
        import FreeCADGui as Gui
        open_box(Gui.getMainWindow())

    def IsActive(self):
        return True


# ---------------------------------------------------------------------- a button per added slicer
def command_name(key):
    return "SWStyle_SlicerApp_" + key


def button_key(key):
    return "SlicerApp_" + key


class AppCommand:
    """Opens one added slicer in its tab (the button the 3D Slicer tab gets for it)."""

    def __init__(self, key):
        self.key = key

    def _entry(self):
        return next((a for a in registry() if a["key"] == self.key), None)

    def GetResources(self):
        from . import slicerui
        a = self._entry() or {"title": self.key}
        return {"MenuText": a["title"], "ToolTip": "%s inside FreeCAD, in its own tab (added with Slicer Apps)." % a["title"],
                "Pixmap": slicerui._icon("other_slicer")}

    def Activated(self):
        a = self._entry()
        if a is None:
            App.Console.PrintMessage("This slicer was removed in Slicer Apps.\n")
            return
        if not Path(a["exe"]).is_file():
            App.Console.PrintWarning("%s: its program is gone (%s). Add it again in Slicer Apps.\n" % (a["title"], a["exe"]))
            return
        open_app(a)

    def IsActive(self):
        return self._entry() is not None


def _caption(title):
    """Two short lines for a large button, as 'Orca\\nFull'."""
    words = title.split()
    if len(words) <= 1:
        return title[:14]
    return words[0][:14] + "\n" + " ".join(words[1:])[:14]


def catalog_entry(entry, icon):
    """The catalog command for an added slicer's button (made once per key)."""
    from . import catalog
    key = button_key(entry["key"])
    if key not in catalog.BY_KEY:
        catalog.BY_KEY[key] = catalog.c(key, entry["title"], (command_name(entry["key"]),), icon,
                                        "%s inside FreeCAD, in its own tab (added with Slicer Apps)." % entry["title"],
                                        caption=_caption(entry["title"]))
        catalog.ALL = tuple(catalog._ALL)
    return key


def register_command(entry):
    import FreeCADGui as Gui
    name = command_name(entry["key"])
    if name not in Gui.listCommands():
        Gui.addCommand(name, AppCommand(entry["key"]))
    return name


def layout_items(icon):
    """("large", key, None) for every added slicer, registering its command and catalog entry (FreeCAD start,
    before the CommandManager is built)."""
    items = []
    for entry in registry():
        try:
            register_command(entry)
            items.append(("large", catalog_entry(entry, icon), None))
        except Exception as error:
            App.Console.PrintWarning("Slicer Apps: no button for %s: %s\n" % (entry.get("title"), error))
    return items


def add_button(entry):
    """A slicer just added: its command and catalog entry now. The 3D Slicer menu of the Add-Ins tab is made when it
    is opened, so the new slicer is in it at once (no restart, no tab to rebuild)."""
    try:
        from . import slicerui
        register_command(entry)
        catalog_entry(entry, slicerui._icon("other_slicer"))
        return True
    except Exception as error:
        App.Console.PrintWarning("Slicer Apps: could not add the button: %s\n" % error)
        return False


def drop_button(key):
    """A removed slicer is out of the 3D Slicer menu of the Add-Ins tab the next time it is opened (its FreeCAD command
    stays, greyed)."""
    return True


COMMANDS = (("SWStyle_SlicerApps", AppsCommand),)
