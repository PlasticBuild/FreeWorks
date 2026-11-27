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

COMMAND = "SWStyle_AddIns"
GENERAL = "User parameter:BaseApp/Preferences/General"
WORKBENCHES = "User parameter:BaseApp/Preferences/Workbenches"
AUTOLOAD = "BackgroundAutoloadModules"
_load_times = {}        # name -> seconds


# kind "workbench": a FreeCAD workbench; kind "module": a module of the add-on with install()
FREEWORKS = (
    ("FreeCAD Motion", "module", "asmmotion"),
    ("FreeCAD MBD", "module", "mbd"),
    ("FreeCAD Toolbox", "module", "toolbox"),
    ("FreeCAD Markup", "module", "markup"),
    ("FreeCAD Simulation", "workbench", "FemWorkbench"),
    ("FreeCAD CAM", "workbench", "CAMWorkbench"),
    ("FreeCAD Inspection (Measure)", "workbench", "MeasureWorkbench"),
    ("FreeCAD Routing (Draft)", "workbench", "DraftWorkbench"),
    ("FreeCAD Surfacing", "workbench", "SurfaceWorkbench"),
    ("FreeCAD Mesh", "workbench", "MeshWorkbench"),
)


APPS = (
    ("3D Slicer (Orca Slicer, Bambu Studio)", "tab", "3D Slicer"),
    ("ScanRuler", "extapp", "ScanRuler"),
    ("Diotopo", "extapp", "Diotopo"),
    ("Inspection (drawings)", "tab", "Inspection"),
)


def app_active(kind, target):
    try:
        if kind == "extapp":
            from . import extapps
            return extapps.tab_on(target)
        from . import cmtabs
        return target not in cmtabs.hidden()
    except Exception as _fw_err:
        _fw_log("addins.py:72", _fw_err)
        return False


def _app_installed(target):
    try:
        from . import extapps
        return bool(extapps.installed(target))
    except Exception as _fw_err:
        _fw_log("addins.py:installed", _fw_err)
        return True


def set_app_active(kind, target, on):
    t0 = time.perf_counter()
    if kind == "extapp":
        from . import extapps
        extapps.set_tab_on(target, on)
    else:
        from . import cmtabs
        off = [t for t in cmtabs.hidden() if t != target] + ([] if on else [target])
        cmtabs.set_hidden(off)
        cmtabs.apply()
    if on:
        _load_times[target] = time.perf_counter() - t0


def startup_pass():
    """Start Up unticked: the app's tab is off at this start (Active brings it back for the session)."""
    for _name, kind, target in APPS:
        if not module_startup(target) and app_active(kind, target):
            try:
                set_app_active(kind, target, False)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: %s left on: %s\n" % (target, error))


HIDDEN_WORKBENCHES = ("NoneWorkbench", "StartWorkbench")


def _p():
    return paths.params()


def workbench_names():
    try:
        return dict(Gui.listWorkbenches())
    except Exception:
        return {}


def workbench_label(name):
    try:
        wb = Gui.listWorkbenches()[name]
        return wb.MenuText if hasattr(wb, "MenuText") and wb.MenuText else name.replace("Workbench", "")
    except Exception:
        return name.replace("Workbench", "")


def workbench_loaded(name):
    try:
        wb = Gui.listWorkbenches()[name]
        return getattr(wb, "__Workbench__", None) is not None or name == Gui.activeWorkbench().name()
    except Exception as _fw_err:
        _fw_log("addins.py:127", _fw_err)
        return False


def workbench_enabled(name):
    ""
    try:
        disabled = App.ParamGet(WORKBENCHES).GetString("Disabled", "")
        enabled = App.ParamGet(WORKBENCHES).GetString("Enabled", "")
        if enabled and name not in enabled.split(","):
            return False
        return name not in disabled.split(",")
    except Exception as _fw_err:
        _fw_log("addins.py:140", _fw_err)
        return True


def set_workbench_enabled(name, on):
    grp = App.ParamGet(WORKBENCHES)
    disabled = [n for n in grp.GetString("Disabled", "").split(",") if n]
    enabled = [n for n in grp.GetString("Enabled", "").split(",") if n]
    if on:
        disabled = [n for n in disabled if n != name]
        if enabled and name not in enabled:
            enabled.append(name)
    else:
        if name not in disabled:
            disabled.append(name)
        enabled = [n for n in enabled if n != name]
    grp.SetString("Disabled", ",".join(disabled))
    if enabled:
        grp.SetString("Enabled", ",".join(enabled))


def autoload():
    return [n for n in App.ParamGet(GENERAL).GetString(AUTOLOAD, "").split(",") if n]


def set_autoload(name, on):
    names = autoload()
    if on and name not in names:
        names.append(name)
    if not on:
        names = [n for n in names if n != name]
    App.ParamGet(GENERAL).SetString(AUTOLOAD, ",".join(names))


def load_workbench(name):
    """Loads a workbench the way the workbench list does, then comes back; returns the seconds taken."""
    current = None
    try:
        current = Gui.activeWorkbench().name()
    except Exception as _fw_err:
        _fw_log("addins.py:176", _fw_err)
    t0 = time.perf_counter()
    try:
        Gui.activateWorkbench(name)
    finally:
        if current and current != name:
            try:
                Gui.activateWorkbench(current)
            except Exception as _fw_err:
                _fw_log("addins.py:185", _fw_err)
    took = time.perf_counter() - t0
    _load_times[name] = took
    return took


def module_active(module):
    return _p().GetBool("AddIn." + module, True)


def set_module_active(module, on):
    _p().SetBool("AddIn." + module, bool(on))


def module_startup(module):
    return _p().GetBool("AddInStartup." + module, True)


def set_module_startup(module, on):
    _p().SetBool("AddInStartup." + module, bool(on))


def load_module(module):
    import importlib
    t0 = time.perf_counter()
    mod = importlib.import_module("." + module, __package__)
    for fn in ("install", "register"):
        f = getattr(mod, fn, None)
        if callable(f):
            try:
                f()
            except TypeError as _fw_err:
                _fw_log("addins.py:217", _fw_err)
            break
    took = time.perf_counter() - t0
    _load_times[module] = took
    return took


def _time_text(key):
    t = _load_times.get(key)
    if t is None:
        return ""
    return "< 1s" if t < 1 else "%ds" % round(t)


def _icon(kind, target):
    ""

    import os
    icon = None
    if kind == "workbench":
        try:
            raw = getattr(Gui.listWorkbenches().get(target), "Icon", "") or ""
            if raw and os.path.exists(raw):
                icon = QtGui.QIcon(raw)
            elif "XPM" in raw[:40]:
                icon = QtGui.QIcon(QtGui.QPixmap([l.strip().strip(",").strip('"') for l in raw.splitlines()
                                                  if l.strip().startswith('"')]))
            elif raw:
                icon = QtGui.QIcon(":/icons/" + raw if not raw.startswith(":") else raw)
        except Exception:
            icon = None
    elif kind in ("extapp", "tab"):
        try:
            if kind == "extapp":
                from . import extapps
                icon = QtGui.QIcon(extapps._icon(target))
            elif target == "3D Slicer":
                from . import slicerui
                icon = QtGui.QIcon(slicerui._icon("slice"))
        except Exception:
            icon = None
    if icon is None or icon.isNull():
        icon = QtWidgets.QApplication.windowIcon()
    return icon


class AddInsDialog(QtWidgets.QDialog):
    COLUMNS = ("Active Add-ins", "Start Up", "Last Load Time")

    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWAddIns")
        self.setWindowTitle("Add-Ins")
        self.resize(520, 560)
        lay = QtWidgets.QVBoxLayout(self)
        self.tree = QtWidgets.QTreeWidget(self)
        self.tree.setObjectName("SWAddInsTree")
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(list(self.COLUMNS))
        self.tree.setRootIsDecorated(True)
        self.tree.setIconSize(QtCore.QSize(16, 16))
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        lay.addWidget(self.tree, 1)
        self.rows = []          # (item, kind, target)
        self._fill()
        self._apps_row(lay)
        row = QtWidgets.QHBoxLayout()
        store = QtWidgets.QPushButton("Addon Manager...", self)
        store.setObjectName("SWAddInsAddonManager")
        store.setToolTip("FreeCAD's Addon Manager: finds and installs more add-ins")
        store.clicked.connect(self._store)
        row.addWidget(store)
        row.addStretch(1)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.setObjectName("SWAddInsButtons")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        row.addWidget(bb)
        lay.addLayout(row)

    def _apps_row(self, lay):
        ""
        try:
            from . import extapps
        except Exception as _fw_err:
            _fw_log("addins.py:apps_row", _fw_err)
            return
        row = QtWidgets.QHBoxLayout()
        self.auto_update = QtWidgets.QCheckBox("Check for updates automatically (once a day)", self)
        self.auto_update.setObjectName("SWAddInsAutoUpdate")
        self.auto_update.setToolTip("ScanRuler: tells you when a new release is out. Diotopo: downloads the new version "
                                    "from the author's GitHub.")
        self.auto_update.setChecked(extapps.auto_update())
        row.addWidget(self.auto_update)
        row.addStretch(1)
        for app in extapps.APPS:
            # extapps163: Add-Ins buttons, no tabs of their own
            if not extapps.installed(app):
                b = QtWidgets.QPushButton("Download %s..." % app, self)
                b.setToolTip("%s is not part of this download. This fetches it from the author's GitHub; its button "
                             "appears in the Add-Ins tab when done." % app)
                b.clicked.connect(lambda _c=False, a=app: extapps.ask_download(a))
            elif extapps.APPS[app].get("mode") == "local":
                b = QtWidgets.QPushButton("Update %s now" % app, self)
                b.setToolTip("Downloads the newest version from the author's GitHub")
                b.clicked.connect(lambda _c=False, a=app: extapps.update_now(a))
            else:
                continue
            b.setObjectName("SWAddInsApp" + app)
            row.addWidget(b)
        lay.addLayout(row)

    def _store(self):
        try:
            Gui.Command.get("Std_AddonMgr").run()
        except Exception:
            try:
                import AddonManager
                AddonManager.CommandAddonManager().Activated()
            except Exception as error:
                QtWidgets.QMessageBox.information(self, "Add-Ins", "The Addon Manager is not installed (%s)." % error)

    def _group(self, title):
        item = QtWidgets.QTreeWidgetItem([title, "", ""])
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        item.setFlags(Qt_ItemIsEnabled())
        self.tree.addTopLevelItem(item)
        item.setExpanded(True)
        item.setFirstColumnSpanned(True)
        self._parent = item
        return item

    def _row(self, name, active, startup, key, kind, target):
        item = QtWidgets.QTreeWidgetItem([name, "", _time_text(key)])
        item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
        item.setCheckState(0, QtCore.Qt.Checked if active else QtCore.Qt.Unchecked)
        item.setCheckState(1, QtCore.Qt.Checked if startup else QtCore.Qt.Unchecked)
        item.setData(0, QtCore.Qt.UserRole, key)
        icon = _icon(kind, target)
        if icon is not None:
            item.setIcon(0, icon)
        parent = getattr(self, "_parent", None)
        if parent is not None:
            parent.addChild(item)
        else:
            self.tree.addTopLevelItem(item)
        self.rows.append((item, kind, target))
        return item

    def _fill(self):
        self.tree.clear()
        self.rows = []
        self._parent = None
        names = workbench_names()
        self._group("FreeCAD Add-ins")
        used = set()
        for name, kind, target in FREEWORKS:
            if kind == "workbench":
                if target not in names:
                    continue
                used.add(target)
                self._row(name, workbench_enabled(target), target in autoload(), target, kind, target)
            else:
                try:
                    __import__(__package__ + "." + target)
                except Exception:
                    continue
                self._row(name, module_active(target), module_startup(target), target, kind, target)
        self._group("Other Add-ins")
        for name, kind, target in APPS:
            if kind == "extapp" and not _app_installed(target):
                continue        # addins-1127: no row for an add-in that is not downloaded yet (the Download button is below); nothing ticked that shows nothing
            self._row(name, app_active(kind, target), module_startup(target), target, kind, target)
        for wb in sorted(names, key=lambda n: workbench_label(n).lower()):
            if wb in used or wb in HIDDEN_WORKBENCHES:
                continue
            self._row(workbench_label(wb), workbench_enabled(wb), wb in autoload(), wb, "workbench", wb)

    def apply(self):
        """The ticks: Active loads or unlists, Start Up keeps it for the next start."""
        for item, kind, target in self.rows:
            active = item.checkState(0) == QtCore.Qt.Checked
            startup = item.checkState(1) == QtCore.Qt.Checked
            if kind == "workbench":
                if active != workbench_enabled(target):
                    set_workbench_enabled(target, active)
                if active and not workbench_loaded(target):
                    try:
                        load_workbench(target)
                    except Exception as error:
                        App.Console.PrintWarning("FreeCAD: %s not loaded: %s\n" % (target, error))
                if startup != (target in autoload()):
                    set_autoload(target, startup)
            elif kind in ("extapp", "tab"):
                if active != app_active(kind, target):
                    try:
                        set_app_active(kind, target, active)
                    except Exception as error:
                        App.Console.PrintWarning("FreeCAD: %s not changed: %s\n" % (target, error))
                if startup != module_startup(target):
                    set_module_startup(target, startup)
            else:
                if active != module_active(target):
                    set_module_active(target, active)
                if active:
                    try:
                        load_module(target)
                    except Exception as error:
                        App.Console.PrintWarning("FreeCAD: %s not loaded: %s\n" % (target, error))
                if startup != module_startup(target):
                    set_module_startup(target, startup)
            item.setText(2, _time_text(target))
        try:
            from . import ribbon
            ribbon.refresh_workbench_list()
        except Exception as _fw_err:
            _fw_log("addins.py:402", _fw_err)
        try:
            from . import cmtabs            # an add-in unticked takes its CommandManager tabs with it
            cmtabs.apply()
        except Exception as _fw_err:
            _fw_log("addins.py:407", _fw_err)
        box = getattr(self, "auto_update", None)
        if box is not None:
            try:
                from . import extapps
                if box.isChecked() != extapps.auto_update():
                    extapps.set_auto_update(box.isChecked())
            except Exception as _fw_err:
                _fw_log("addins.py:auto_update", _fw_err)

    def accept(self):
        self.apply()
        super().accept()


def Qt_ItemIsEnabled():
    return QtCore.Qt.ItemIsEnabled


_open = []


def show():
    box = AddInsDialog()
    _open[:] = [box]
    box.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
    box.show()
    return box


class AddInsCommand:
    def GetResources(self):
        return {"MenuText": "Add-Ins...", "ToolTip": "Loads and unloads add-ins, and picks the ones loaded at start-up.",
                "Pixmap": ""}

    def Activated(self):
        show()

    def IsActive(self):
        return True


def register():
    if Gui.Command.get(COMMAND) is None:
        Gui.addCommand(COMMAND, AddInsCommand())
        QtCore.QTimer.singleShot(4000, startup_pass)     # once the tabs are built
