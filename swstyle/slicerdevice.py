"""Printers in FreeCAD, as in the slicers' Device tab: add a printer (found on the network, from a
Bambu Lab account, or typed in), log in to Bambu Lab, send the last slice to a printer and start
it, and the Device panel: live camera, state, progress, temperatures, light, pause/resume/stop.

The network work is in slicerprinters.py and runs in worker threads; Qt signals bring its
results to the window."""
import os
import threading
import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

class _LazyNet:
    """extapps140: slicerprinters (ssl, sockets, MQTT, FTPS) loads the first time a printer is touched, not at start-up."""

    def __getattr__(self, name):
        import importlib
        mod = importlib.import_module(__package__ + ".slicerprinters")
        globals()["net"] = mod
        return getattr(mod, name)


net = _LazyNet()
from . import slicersettings

Qt = QtCore.Qt
KINDS = (("bambu", "Bambu Lab (LAN mode)"), ("elegoo", "Elegoo (Elegoo Link)"),
         ("moonraker", "Klipper (Moonraker: Sovol, Creality K1, Voron...)"), ("octoprint", "OctoPrint"),
         ("prusalink", "Prusa (PrusaLink: MK4/MK4S, XL, MINI+, CORE One)"))
STATE_TEXT = {"idle": "Idle", "running": "Printing", "printing": "Printing", "pause": "Paused",
              "prepare": "Preparing", "finish": "Finished", "failed": "Stopped", "offline": "Offline",
              "connecting": "Connecting...", "connected": "Connected", "slicing": "Slicing"}


def _main():
    return Gui.getMainWindow()


def _label(row):
    return "%s  (%s)" % (row.get("name") or row.get("serial") or row.get("ip"), row.get("ip") or "address not found yet")


# ---------------------------------------------------------------------- the chosen device
class Hub(QtCore.QObject):
    """Tells every device picker and account bar that the printers, the chosen one or the login
    changed."""
    changed = QtCore.Signal()
    jobs_changed = QtCore.Signal()

    instance = None

    @classmethod
    def get(cls):
        if cls.instance is None:
            cls.instance = Hub(QtWidgets.QApplication.instance())
        return cls.instance


def _device_key(row):
    row = row or {}
    return row.get("serial") or ("%s@%s" % (row.get("kind"), row.get("ip")) if row.get("ip") else "")


def current_device():
    """The printer you picked last (beside the printer preset, in the Device panel or the send box)."""
    key = net.params().GetString("Device", "")
    rows = net.saved_printers()
    return next((r for r in rows if key and _device_key(r) == key), rows[0] if rows else None)


def set_current_device(row):
    key = _device_key(row)
    if key != net.params().GetString("Device", ""):
        net.params().SetString("Device", key)
        Hub.get().changed.emit()


def fill_devices(combo, add_none=False):
    combo.blockSignals(True)
    combo.clear()
    for r in net.saved_printers():
        combo.addItem(_label(r), r)
    if combo.count() == 0 and add_none:
        combo.addItem("No printer yet: Add Printer or Log In", None)
    cur = _device_key(current_device())
    for i in range(combo.count()):
        if cur and _device_key(combo.itemData(i)) == cur:
            combo.setCurrentIndex(i)
    combo.blockSignals(False)


# ---------------------------------------------------------------------- the jobs sent from FreeCAD
JOBS_KEEP = 30
RESULT_TEXT = {"sent": "On the printer", "started": "Started", "failed": "Not sent", "finish": "Finished",
               "stopped": "Stopped", "printing": "Printing", "pause": "Paused"}


def jobs():
    """The files sent to printers from FreeCAD, newest first: {"time", "printer", "device", "file", "result",
    "message"}."""
    import json
    try:
        rows = json.loads(net.params().GetString("Jobs", "") or "[]")
    except ValueError:
        rows = []
    return [r for r in rows if isinstance(r, dict)]


def _save_jobs(rows):
    import json
    net.params().SetString("Jobs", json.dumps(rows[:JOBS_KEEP]))
    Hub.get().jobs_changed.emit()


def add_job(row, path, result, message=""):
    rows = jobs()
    rows.insert(0, {"time": time.strftime("%Y-%m-%d %H:%M"), "printer": row.get("name") or row.get("ip") or "",
                    "device": _device_key(row), "file": os.path.basename(str(path or "")), "result": result,
                    "message": message})
    _save_jobs(rows)


def update_job(row, file_name, result):
    """The printer's own word on the newest job sent to it with this file (printing, paused, finished, stopped)."""
    key, rows = _device_key(row), jobs()
    for r in rows:
        if r.get("device") == key and file_name and r.get("file", "").startswith(file_name):
            if r.get("result") in ("failed", result):
                return
            r["result"] = result
            _save_jobs(rows)
            return


def clear_jobs():
    _save_jobs([])


def log_in(parent=None, on_status=None):
    """The slicers' Log In: the Bambu Lab account login, then its printers become your printers
    (with their access codes and network addresses) to pick from."""
    if LoginDialog(parent).exec() != QtWidgets.QDialog.Accepted:
        Hub.get().changed.emit()
        return
    say = on_status or (lambda text: None)
    say("Reading your printers from Bambu Lab...")

    def done(result):
        if isinstance(result, Exception):
            say("<span style='color:#c00000'>Could not read your printers: %s</span>" % result)
        else:
            say("%d printer%s from your account." % (len(result), "" if len(result) == 1 else "s"))
            if result and not net.params().GetString("Device", ""):
                set_current_device(next((r for r in net.saved_printers() if r.get("serial") == result[0].get("serial")),
                                        None))
        Hub.get().changed.emit()

    Hub.get()._sync = run_in_thread(net.sync_account, done)


class AccountBar(QtWidgets.QWidget):
    """The account line as at the top of Bambu Studio and Orca Slicer: who is logged in, Log In /
    Log Out."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.label = QtWidgets.QLabel()
        self.label.setWordWrap(True)
        self.button = QtWidgets.QPushButton()
        self.button.setObjectName("SWStyle_SlicerLogIn")
        self.button.setIcon(_v2(_icon("login")))
        self.button.clicked.connect(self._clicked)
        lay.addWidget(self.label, 1)
        lay.addWidget(self.button)
        self.note = ""
        Hub.get().changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        acc = net.BambuAccount()
        on = acc.logged_in()
        self.button.setText("Log Out" if on else "Log In")
        self.button.setToolTip("Log out of %s" % acc.account if on else
                               "Log in to your Bambu Lab account: your printers then appear in the device list")
        self.label.setText(("Bambu Lab: <b>%s</b>" % (acc.account or "logged in") if on else "Bambu Lab: not logged in")
                           + ("<br>%s" % self.note if self.note else ""))

    def _say(self, text):
        self.note = text
        self.refresh()

    def _clicked(self):
        acc = net.BambuAccount()
        if acc.logged_in():
            if QtWidgets.QMessageBox.question(self, "Log Out", "Log out of %s?" % (acc.account or "Bambu Lab")) \
                    != QtWidgets.QMessageBox.Yes:
                return
            acc.logout()
            self.note = ""
            Hub.get().changed.emit()
            return
        log_in(self, self._say)


class DevicePicker(QtWidgets.QWidget):
    """The device beside the printer preset (the slicers' connection button): which of your
    printers the slice is sent to, + to add one."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.combo = QtWidgets.QComboBox()
        self.combo.setObjectName("SWStyle_SlicerDevicePick")
        self.combo.setToolTip("The printer the slice is sent to")
        self.combo.currentIndexChanged.connect(self._picked)
        self.add = QtWidgets.QToolButton()
        self.add.setIcon(_v2(_icon("addprinter")))
        self.add.setToolTip("Add Printer: find one on the network or in your Bambu Lab account, or type one in")
        self.add.clicked.connect(self._add)
        lay.addWidget(self.combo, 1)
        lay.addWidget(self.add)
        Hub.get().changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        fill_devices(self.combo, add_none=True)

    def _picked(self, i):
        if self.combo.itemData(i):
            set_current_device(self.combo.itemData(i))

    def _add(self):
        AddPrinterDialog(self).exec()
        Hub.get().changed.emit()


class Bridge(QtCore.QObject):
    """Worker-thread results into the GUI thread."""
    status = QtCore.Signal(dict)
    frame = QtCore.Signal(bytes)
    done = QtCore.Signal(object)
    progress = QtCore.Signal(int, int)


def run_in_thread(fn, on_done):
    """fn() in a thread, on_done(result or Exception) in the GUI thread."""
    bridge = Bridge()
    bridge.done.connect(on_done)

    def work():
        try:
            result = fn()
        except Exception as error:
            result = error
        bridge.done.emit(result)

    t = threading.Thread(target=work, daemon=True)
    t._bridge = bridge          # keep the QObject alive with the thread
    t.start()
    return bridge


# ---------------------------------------------------------------------- Bambu Lab login
class LoginDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or _main())
        self.setWindowTitle("Bambu Lab Account")
        self.setMinimumWidth(440)
        self.account = net.BambuAccount()
        lay = QtWidgets.QFormLayout(self)
        self.info = QtWidgets.QLabel()
        self.info.setWordWrap(True)
        lay.addRow(self.info)
        self.email = QtWidgets.QLineEdit(self.account.account)
        self.password = QtWidgets.QLineEdit()
        self.password.setEchoMode(QtWidgets.QLineEdit.Password)
        self.code = QtWidgets.QLineEdit()
        self.code_label = QtWidgets.QLabel("Code")
        lay.addRow("Email", self.email)
        self.password_label = QtWidgets.QLabel("Password")
        lay.addRow(self.password_label, self.password)
        lay.addRow(self.code_label, self.code)
        self.buttons = QtWidgets.QDialogButtonBox()
        self.login_button = self.buttons.addButton("Log In", QtWidgets.QDialogButtonBox.AcceptRole)
        # accounts made with Google, Apple or Facebook have no password: Bambu Lab emails them a code
        self.code_button = QtWidgets.QPushButton("Email Me a Code")
        self.code_button.setObjectName("SWStyle_SlicerEmailCode")
        self.code_button.setToolTip("No password, or you sign in to Bambu Lab with Google, Apple or Facebook?\n"
                                    "Bambu Lab emails a login code to your account's address.")
        self.code_button.clicked.connect(self.send_code)
        lay.addRow("", self.code_button)
        self.logout_button = self.buttons.addButton("Log Out", QtWidgets.QDialogButtonBox.ResetRole)
        self.buttons.addButton(QtWidgets.QDialogButtonBox.Close)
        self.login_button.clicked.connect(self.login)
        self.logout_button.clicked.connect(self.logout)
        self.buttons.rejected.connect(self.reject)
        lay.addRow(self.buttons)
        self.mode = "password"
        self._show()

    def _show(self, text=None):
        on = self.account.logged_in()
        self.logout_button.setVisible(on)
        need_code = self.mode in ("need_code", "need_tfa")
        self.code.setVisible(need_code)
        self.code_label.setVisible(need_code)
        # a code replaces the password, as on Bambu Lab's sign-in page
        self.password.setVisible(self.mode != "need_code")
        self.password_label.setVisible(self.mode != "need_code")
        self.info.setText(text or ("Logged in as <b>%s</b>." % self.account.account if on else
                                   "Log in with your Bambu Lab account to list your printers with their access "
                                   "codes. Printing and the camera then go over your local network.<br>"
                                   "Signed up with Google, Apple or Facebook? Type your email and press "
                                   "<b>Email Me a Code</b>."))

    def login(self):
        email, pw, code = self.email.text().strip(), self.password.text(), self.code.text().strip()
        self.login_button.setEnabled(False)
        mode = self.mode
        tfa = getattr(self.account, "tfa_key", None)

        def work():
            if mode == "need_tfa":
                return self.account.login(email, code=code, tfa_key=tfa)
            if mode == "need_code":
                return self.account.login(email, code=code)
            return self.account.login(email, password=pw)

        def done(result):
            self.login_button.setEnabled(True)
            if isinstance(result, Exception):
                self._show("<span style='color:#c00000'>Could not reach Bambu Lab: %s</span>" % result)
                return
            if result == "ok":
                self.mode = "password"
                self._show()
                self.accept()
            elif result in ("need_code", "need_tfa"):
                self.mode = result
                self._show("Enter the code %s." % ("Bambu Lab emailed you" if result == "need_code"
                                                   else "from your authenticator app"))
            else:
                self._show("<span style='color:#c00000'>%s</span>" % result)

        self._bridge = run_in_thread(work, done)

    def send_code(self):
        email = self.email.text().strip()
        if not email:
            self._show("<span style='color:#c00000'>Type the email address of your Bambu Lab account first "
                       "(for a Google account, your Gmail address).</span>")
            return
        self.code_button.setEnabled(False)

        def done(result):
            self.code_button.setEnabled(True)
            if isinstance(result, Exception):
                self._show("<span style='color:#c00000'>Could not reach Bambu Lab: %s</span>" % result)
            elif result == "need_code":
                self.mode = "need_code"
                self._show("Bambu Lab emailed a code to <b>%s</b>. Type it below and press Log In." % email)
                self.code.setFocus()
            else:
                self._show("<span style='color:#c00000'>%s</span>" % result)

        self._bridge = run_in_thread(lambda: self.account.send_code(email), done)

    def logout(self):
        self.account.logout()
        self._show()


# ---------------------------------------------------------------------- Add printer
class AddPrinterDialog(QtWidgets.QDialog):
    """Printers on the network and in the Bambu Lab account; or typed in."""

    def __init__(self, parent=None):
        super().__init__(parent or _main())
        self.setWindowTitle("Printers")
        self.resize(640, 480)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("<b>Your printers</b>"))
        self.saved = QtWidgets.QListWidget()
        self.saved.setMaximumHeight(110)
        lay.addWidget(self.saved)
        row = QtWidgets.QHBoxLayout()
        self.remove = QtWidgets.QPushButton("Remove")
        self.remove.clicked.connect(self._remove)
        row.addStretch(1)
        row.addWidget(self.remove)
        lay.addLayout(row)
        lay.addWidget(QtWidgets.QLabel("<b>Add a printer</b>"))
        top = QtWidgets.QHBoxLayout()
        self.search = QtWidgets.QPushButton("Search the Network")
        self.search.clicked.connect(self._search)
        self.account_button = QtWidgets.QPushButton("Log In to Bambu Lab...")
        self.account_button.clicked.connect(self._from_account)
        top.addWidget(self.search)
        top.addWidget(self.account_button)
        top.addStretch(1)
        lay.addLayout(top)
        self.found = QtWidgets.QListWidget()
        self.found.currentRowChanged.connect(self._pick)
        lay.addWidget(self.found, 1)
        form = QtWidgets.QFormLayout()
        self.kind = QtWidgets.QComboBox()
        for k, label in KINDS:
            self.kind.addItem(label, k)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.name = QtWidgets.QLineEdit()
        self.ip = QtWidgets.QLineEdit()
        self.ip.setPlaceholderText("192.168.1.50")
        self.serial = QtWidgets.QLineEdit()
        self.code = QtWidgets.QLineEdit()
        self.code.setPlaceholderText("on the printer: Settings > Network (LAN mode)")
        self.code_label = QtWidgets.QLabel("Access code")
        self.user = QtWidgets.QLineEdit("maker")
        self.user.setToolTip("PrusaLink's user name (printer screen: Settings > Network > PrusaLink); empty for an "
                             "API key")
        self.user_label = QtWidgets.QLabel("User")
        form.addRow("Type", self.kind)
        form.addRow("Name", self.name)
        form.addRow("IP address", self.ip)
        self.serial_label = QtWidgets.QLabel("Serial number")
        form.addRow(self.serial_label, self.serial)
        form.addRow(self.user_label, self.user)
        form.addRow(self.code_label, self.code)
        lay.addLayout(form)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        buttons = QtWidgets.QDialogButtonBox()
        self.add = buttons.addButton("Add Printer", QtWidgets.QDialogButtonBox.ActionRole)
        self.add.clicked.connect(self._add)
        buttons.addButton(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.rows = []
        self._fill_saved()
        self._kind_changed()

    def _fill_saved(self):
        self.saved.clear()
        for r in net.saved_printers():
            item = QtWidgets.QListWidgetItem(_label(r))
            item.setData(Qt.UserRole, r)
            self.saved.addItem(item)
        # Remove works on the printer picked in the list: one is always picked, and with none saved it is not there
        if self.saved.count():
            self.saved.setCurrentRow(0)
        self.remove.setVisible(self.saved.count() > 0)

    def _remove(self):
        item = self.saved.currentItem()
        if item is not None:
            net.remove_printer(item.data(Qt.UserRole))
            self._fill_saved()

    def _kind_changed(self, *_):
        kind = self.kind.currentData()
        self.code.setVisible(kind in ("bambu", "octoprint", "moonraker", "prusalink"))
        self.code_label.setVisible(kind in ("bambu", "octoprint", "moonraker", "prusalink"))
        self.code_label.setText({"bambu": "Access code", "prusalink": "Password"}.get(kind, "API key"))
        self.code.setEchoMode(QtWidgets.QLineEdit.Password if kind == "prusalink" else QtWidgets.QLineEdit.Normal)
        self.code.setPlaceholderText({"bambu": "on the printer: Settings > Network (LAN mode)",
                                      "octoprint": "OctoPrint: Settings > Application Keys",
                                      "moonraker": "only if Moonraker asks for one",
                                      "prusalink": "printer screen: Settings > Network > PrusaLink"}.get(kind, ""))
        self.user.setVisible(kind == "prusalink")
        self.user_label.setVisible(kind == "prusalink")
        self.serial.setVisible(kind in ("bambu", "elegoo"))
        self.serial_label.setVisible(kind in ("bambu", "elegoo"))
        self.ip.setPlaceholderText("192.168.1.50  (or 192.168.1.50:7125)" if kind == "moonraker" else "192.168.1.50")

    def _search(self):
        self.search.setEnabled(False)
        self.status.setText("Listening for printers on the network...")

        def done(result):
            self.search.setEnabled(True)
            if isinstance(result, Exception):
                self.status.setText(net.plain_error(result))
                return
            self._merge(result)
            self.status.setText("%d printer%s found." % (len(result), "" if len(result) == 1 else "s"))

        self._bridge = run_in_thread(lambda: net.discover(5.0), done)

    def _from_account(self):
        acc = net.BambuAccount()
        if not acc.logged_in():
            if LoginDialog(self).exec() != QtWidgets.QDialog.Accepted:
                return
            acc = net.BambuAccount()
        self.status.setText("Reading the printers of %s..." % acc.account)

        def done(result):
            if isinstance(result, Exception):
                self.status.setText(str(result))
                return
            self._merge(result)
            self.status.setText("%d printer%s in the account. Search the network to fill in their IP addresses."
                                % (len(result), "" if len(result) == 1 else "s"))

        self._bridge = run_in_thread(acc.printers, done)

    def _merge(self, rows):
        for r in rows:
            old = next((x for x in self.rows if r.get("serial") and x.get("serial") == r.get("serial")), None)
            if old is None:
                self.rows.append(dict(r))
            else:
                for k, v in r.items():
                    if v and not old.get(k):
                        old[k] = v
        self.found.clear()
        for r in self.rows:
            item = QtWidgets.QListWidgetItem("%s  ·  %s  ·  %s" % (r.get("name"), r.get("model") or r["kind"],
                                                                   r.get("ip") or "IP not known yet"))
            self.found.addItem(item)

    def _pick(self, i):
        if not 0 <= i < len(self.rows):
            return
        r = self.rows[i]
        self.kind.setCurrentIndex(max(0, self.kind.findData(r.get("kind", "bambu"))))
        self.name.setText(r.get("name", ""))
        self.ip.setText(r.get("ip", ""))
        self.serial.setText(r.get("serial", ""))
        self.code.setText(r.get("access_code", ""))
        if r.get("kind") == "prusalink":
            self.user.setText(r.get("user", "maker"))

    def row(self):
        r = {"kind": self.kind.currentData(), "name": self.name.text().strip() or self.ip.text().strip(),
             "ip": self.ip.text().strip(), "serial": self.serial.text().strip(),
             "access_code": self.code.text().strip()}
        if r["kind"] == "prusalink":
            r["user"] = self.user.text().strip()
        return r

    def _add(self):
        r = self.row()
        if not r["ip"]:
            self.status.setText("<span style='color:#c00000'>The printer's IP address is needed.</span>")
            return
        if r["kind"] == "bambu" and not (r["serial"] and r["access_code"]):
            self.status.setText("<span style='color:#c00000'>Bambu Lab printers need the serial number and the "
                                "access code (printer screen: Settings > Network).</span>")
            return
        self.add.setEnabled(False)
        self.status.setText("Connecting to %s..." % r["ip"])

        def test():
            p = net.Printer(r)
            p.connect()
            p.close()
            return True

        def done(result):
            self.add.setEnabled(True)
            if isinstance(result, Exception):
                self.status.setText("<span style='color:#c00000'>Could not connect: %s</span>" % net.plain_error(result, r))
                return
            net.add_printer(r)
            set_current_device(r)
            self._fill_saved()
            self.status.setText("Added %s." % r["name"])

        self._bridge = run_in_thread(test, done)


# ---------------------------------------------------------------------- send to printer
class SendDialog(QtWidgets.QDialog):
    """The slicers' send dialog: which printer, the print options, then upload and start."""

    def __init__(self, result, parent=None):
        super().__init__(parent or _main())
        self.setWindowTitle("Send to Printer")
        self.result = result
        lay = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.printer = QtWidgets.QComboBox()
        fill_devices(self.printer, add_none=True)
        form.addRow("Printer", self.printer)
        self.file_label = QtWidgets.QLabel()
        form.addRow("File", self.file_label)
        lay.addLayout(form)
        box = QtWidgets.QGroupBox("Print options")
        bl = QtWidgets.QVBoxLayout(box)
        self.opts = {}
        for key, text, default in (("bed_levelling", "Bed leveling", True), ("flow_cali", "Flow dynamics calibration", False),
                                   ("vibration_cali", "Vibration compensation calibration", True),
                                   ("timelapse", "Timelapse", False), ("use_ams", "Use AMS", False),
                                   ("layer_inspect", "First layer inspection", False)):
            c = QtWidgets.QCheckBox(text)
            c.setChecked(default)
            self.opts[key] = c
            bl.addWidget(c)
        lay.addWidget(box)
        self.start = QtWidgets.QCheckBox("Start printing when the file is on the printer")
        self.start.setChecked(True)
        lay.addWidget(self.start)
        self.bar = QtWidgets.QProgressBar()
        self.bar.hide()
        lay.addWidget(self.bar)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        buttons = QtWidgets.QDialogButtonBox()
        self.send_button = buttons.addButton("Send", QtWidgets.QDialogButtonBox.AcceptRole)
        self.send_button.clicked.connect(self.send)
        buttons.addButton(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.printer.currentIndexChanged.connect(self._changed)
        self._changed()

    def _file(self):
        r = self.printer.currentData() or {}
        if r.get("kind") == "bambu":
            from . import slicerui
            return slicerui.ensure_project(self.result)
        return self.result.get("gcode")

    def _changed(self, *_):
        r = self.printer.currentData() or {}
        bambu = r.get("kind") == "bambu"
        for key in ("flow_cali", "vibration_cali", "use_ams", "layer_inspect"):
            self.opts[key].setVisible(bambu)
        # bed leveling and timelapse go with the print on Bambu Lab and Elegoo printers only (the others print the
        # G-code as it is): no option that does nothing
        own = r.get("kind") in ("bambu", "elegoo") or not r
        for key in ("bed_levelling", "timelapse"):
            self.opts[key].setVisible(own)
        self.opts["bed_levelling"].parentWidget().setVisible(own)
        f = self._file()
        self.file_label.setText(os.path.basename(str(f)) if f else "(slice first)")
        # no printer yet: the button adds one (never a greyed Send)
        self.send_button.setText("Send" if r else "Add Printer...")
        if not r:
            self.status.setText("No printer yet: Add Printer, or Log In to Bambu Lab.")
        else:
            self.status.setText("")

    def options(self):
        return {k: c.isChecked() for k, c in self.opts.items() if not c.isHidden()}

    def send(self):
        r = self.printer.currentData()
        if not r:
            Gui.runCommand("SWStyle_SlicerAddPrinter")
            fill_devices(self.printer, add_none=True)
            self._changed()
            return
        f = self._file()
        if not f:
            self.status.setText("<span style='color:#c00000'>Nothing sliced for this printer yet: slice the plate "
                                "first%s.</span>" % (" (Bambu Lab printers take the sliced project, .gcode.3mf)"
                                                     if r.get("kind") == "bambu" else ""))
            return
        path = str(f)
        start = self.start.isChecked()
        opts = self.options()
        bridge = Bridge()
        bridge.progress.connect(lambda a, t: (self.bar.setRange(0, max(1, t)), self.bar.setValue(a)))
        self.bar.show()
        self.send_button.setEnabled(False)
        self.status.setText("Sending to %s..." % r.get("name"))

        def work():
            device = DevicePanel.printer_for(r)
            owned = device is None
            p = device or net.Printer(r)
            if owned:
                p.connect()
            try:
                p.send(path, start=start, options=opts, progress=lambda a, t: bridge.progress.emit(a, t))
            finally:
                if owned:
                    p.close()
            return True

        def done(result):
            self.send_button.setEnabled(True)
            if isinstance(result, Exception):
                text = net.plain_error(result, r)
                add_job(r, path, "failed", text)
                self.status.setText("<span style='color:#c00000'>Not sent: %s</span>" % text)
                return
            add_job(r, path, "started" if start else "sent")
            self.status.setText("Sent%s." % (" and started" if start else ""))
            self._sent = True
            QtCore.QTimer.singleShot(800, self.accept)

        self._bridge = (bridge, run_in_thread(work, done))


# ---------------------------------------------------------------------- the Device panel
_LAST = {"ams": None}      # the AMS report of the printer last connected


def last_ams():
    """The AMS report of the connected Bambu Lab printer (None until one has reported)."""
    return _LAST["ams"]


class DevicePanel(QtWidgets.QDockWidget):
    """The slicers' Device tab as a panel beside the 3D view."""

    instance = None

    def __init__(self):
        super().__init__("Device", _main())
        self.setObjectName("SWStyle_SlicerDevice")
        self.setAllowedAreas(Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea)
        self.printer = None
        self._targets = {}          # the printer's own target temperatures, as last reported
        self.bridge = Bridge()
        self.bridge.status.connect(self._status)
        self.bridge.frame.connect(self._frame)
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        self.account = AccountBar()
        lay.addWidget(self.account)
        top = QtWidgets.QHBoxLayout()
        self.pick = QtWidgets.QComboBox()
        self.pick.currentIndexChanged.connect(lambda i: self.pick.itemData(i) and set_current_device(self.pick.itemData(i)))
        self.connect_button = QtWidgets.QPushButton("Connect")
        self.connect_button.setCheckable(True)
        self.connect_button.toggled.connect(self._connect_toggled)
        add = QtWidgets.QToolButton()
        add.setText("+")
        add.setToolTip("Add Printer")
        add.clicked.connect(self._add)
        top.addWidget(self.pick, 1)
        top.addWidget(add)
        top.addWidget(self.connect_button)
        lay.addLayout(top)
        # as the slicers' Device tab: before a printer is connected only the printer row shows, with a line on
        # what comes; the camera, state, temperatures and controls show once it is connected (never greyed)
        self.offline_note = QtWidgets.QLabel()
        self.offline_note.setObjectName("SWStyle_SlicerDeviceOffline")
        self.offline_note.setWordWrap(True)
        self.offline_note.setAlignment(Qt.AlignCenter)
        self.offline_note.setMinimumHeight(120)
        lay.addWidget(self.offline_note, 1)
        self.live = QtWidgets.QWidget()
        self.live.setObjectName("SWStyle_SlicerDeviceLive")
        outer = lay
        lay = QtWidgets.QVBoxLayout(self.live)
        lay.setContentsMargins(0, 0, 0, 0)
        self.camera = QtWidgets.QLabel("Camera")
        self.camera.setAlignment(Qt.AlignCenter)
        self.camera.setMinimumSize(320, 180)
        self.camera.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.camera.setStyleSheet("background:#202020; color:#9a9a9a;")
        lay.addWidget(self.camera, 1)
        cam_row = QtWidgets.QHBoxLayout()
        self.camera_button = QtWidgets.QPushButton("Live View")
        self.camera_button.setCheckable(True)
        self.camera_button.toggled.connect(self._camera_toggled)
        self.light_button = QtWidgets.QPushButton("Light")
        self.light_button.setCheckable(True)
        self.light_button.clicked.connect(self._light)
        cam_row.addWidget(self.camera_button)
        cam_row.addWidget(self.light_button)
        cam_row.addStretch(1)
        lay.addLayout(cam_row)
        info = QtWidgets.QGroupBox("Printing")
        g = QtWidgets.QGridLayout(info)
        self.state = QtWidgets.QLabel("-")
        self.file = QtWidgets.QLabel("")
        self.bar = QtWidgets.QProgressBar()
        self.bar.setRange(0, 100)
        self.layer = QtWidgets.QLabel("")
        self.left = QtWidgets.QLabel("")
        g.addWidget(QtWidgets.QLabel("State"), 0, 0)
        g.addWidget(self.state, 0, 1)
        g.addWidget(QtWidgets.QLabel("File"), 1, 0)
        g.addWidget(self.file, 1, 1)
        g.addWidget(self.bar, 2, 0, 1, 2)
        g.addWidget(self.layer, 3, 0)
        g.addWidget(self.left, 3, 1)
        btns = QtWidgets.QHBoxLayout()
        self.pause_button = QtWidgets.QPushButton("Pause")
        self.pause_button.clicked.connect(self._pause)
        self.stop_button = QtWidgets.QPushButton("Stop")
        self.stop_button.clicked.connect(self._stop)
        btns.addWidget(self.pause_button)
        btns.addWidget(self.stop_button)
        g.addLayout(btns, 4, 0, 1, 2)
        lay.addWidget(info)
        temps = QtWidgets.QGroupBox("Temperatures")
        t = QtWidgets.QGridLayout(temps)
        self.temp_labels, self.temp_set = {}, {}
        for i, (key, text) in enumerate((("nozzle", "Nozzle"), ("bed", "Bed"), ("chamber", "Chamber"))):
            t.addWidget(QtWidgets.QLabel(text), i, 0)
            lab = QtWidgets.QLabel("-")
            self.temp_labels[key] = lab
            t.addWidget(lab, i, 1)
            if key != "chamber":
                box = QtWidgets.QSpinBox()
                box.setRange(0, 350 if key == "nozzle" else 120)
                box.setSuffix(" °C")
                box.setToolTip("Target temperature: press Enter to set it (asked first)")
                box.editingFinished.connect(lambda k=key, b=box, n=text: self._set_temperature(k, n, b))
                self.temp_set[key] = box
                t.addWidget(box, i, 2)
        lay.addWidget(temps)
        lay.addWidget(self._ams_box())
        lay.addWidget(self._controls_box())
        outer.addWidget(self.live, 1)
        lay = outer
        lay.addWidget(self._jobs_box())
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        lay.addWidget(self.error)
        self.setWidget(w)
        slicersettings.guard_wheel(w)
        Hub.get().changed.connect(self._fill)
        self._fill()
        self._enable(False)

    @classmethod
    def show_panel(cls):
        if cls.instance is None:
            cls.instance = DevicePanel()
            _main().addDockWidget(Qt.RightDockWidgetArea, cls.instance)
        cls.instance._fill()
        cls.instance.show()
        cls.instance.raise_()
        return cls.instance

    @classmethod
    def printer_for(cls, row):
        """The Device panel's live connection to this printer, if it has one."""
        d = cls.instance
        if d is not None and d.printer is not None and net._same_printer(d.printer.row, row) \
                and d.printer.status.get("state") not in ("offline", "connecting"):
            return d.printer
        return None

    def _fill(self):
        if self.printer is not None:
            # connected: keep the list as it is
            return
        fill_devices(self.pick)
        self.connect_button.setVisible(self.pick.count() > 0)     # no printer yet: + (Add Printer) only
        self.pick.setVisible(self.pick.count() > 0)
        self.offline_note.setText("Connect a printer to see its camera, state, temperatures and controls."
                                  if self.pick.count() else
                                  "No printer yet: + adds one (Search the Network, or by its address).")

    def _add(self):
        AddPrinterDialog(self).exec()
        Hub.get().changed.emit()

    def _enable(self, on):
        for w in (self.camera_button, self.light_button, self.pause_button, self.stop_button,
                  *self.temp_set.values(), self.speed, self.speed_set, self.home_button, self.step,
                  *self.jog_buttons.values(), *[x for pair in self.fan_boxes.values() for x in pair]):
            w.setEnabled(True)
        self.live.setVisible(on)
        self.offline_note.setVisible(not on)
        # Klipper and OctoPrint name no light: no button for it
        kind = self.printer.kind if self.printer is not None else ""
        self.light_button.setVisible(on and self.printer is not None and kind not in net.HTTP_KINDS
                                     and net.can(kind, "light"))
        # PrusaLink: state, progress, temperatures, Pause / Resume and Stop; no command for the camera, targets or
        # moves, so those are not shown
        self.camera_button.setVisible(net.can(kind, "camera"))
        self.camera.setVisible(net.can(kind, "camera"))
        for box in self.temp_set.values():
            box.setVisible(net.can(kind, "temperature"))
        self.controls.setVisible(net.can(kind, "jog"))
        self.temp_labels["chamber"].setVisible(net.can(kind, "chamber"))
        lab = self.temp_labels["chamber"].parentWidget().layout().itemAtPosition(2, 0)
        if lab is not None and lab.widget() is not None:
            lab.widget().setVisible(net.can(kind, "chamber"))

    def _connect_toggled(self, on):
        if on:
            row = self.pick.currentData()
            if not row:
                self.connect_button.setChecked(False)
                return
            if not row.get("ip"):
                self.error.setText("<span style='color:#c00000'>%s's network address is not known yet: Add "
                                   "Printer > Search the Network, with the printer on.</span>" % row.get("name"))
                self.connect_button.setChecked(False)
                return
            self.printer = net.Printer(row)
            self.printer.on_status = self.bridge.status.emit
            self.printer.on_frame = self.bridge.frame.emit
            self.state.setText(STATE_TEXT["connecting"])
            self.connect_button.setText("Disconnect")

            def done(result):
                if isinstance(result, Exception):
                    self.connect_button.setChecked(False)
                    self.error.setText("<span style='color:#c00000'>%s</span>" % net.plain_error(result, row))
                    return
                self.error.setText("")
                self._enable(True)

            self._bridge = run_in_thread(self.printer.connect, done)
        else:
            if self.printer is not None:
                self.printer.close()
            self.printer = None
            self.camera_button.setChecked(False)
            self.connect_button.setText("Connect")
            self.state.setText("-")
            self._enable(False)

    def _camera_toggled(self, on):
        if self.printer is None:
            return
        if on:
            self.printer.start_camera()
            self.camera.setText("Starting the camera...")
        else:
            self.printer.stop_camera()
            self.camera.setPixmap(QtGui.QPixmap())
            self.camera.setText("Camera")

    def _frame(self, data):
        img = QtGui.QImage.fromData(data, "JPG")
        if img.isNull() or not self.camera_button.isChecked():
            return
        self.last_frame = img
        self.camera.setPixmap(QtGui.QPixmap.fromImage(img).scaled(self.camera.size(), Qt.KeepAspectRatio,
                                                                   Qt.SmoothTransformation))

    def _status(self, st):
        if st.get("ams") is not None:
            _LAST["ams"] = st["ams"]
            self._show_ams(st["ams"])
        if "error" in st:
            code = int(st.get("error") or 0)
            self.error.setText("<span style='color:#c00000'>The printer reports error %08X. Its screen says what "
                               "to do.</span>" % code if code else "")
        state = st.get("state", "")
        self.state.setText(STATE_TEXT.get(state, state.title()))
        self.file.setText(st.get("file") or "")
        prog = st.get("progress")
        self.bar.setValue(int(prog or 0))
        if st.get("layers"):
            self.layer.setText("Layer %s / %s" % (st.get("layer") or 0, st["layers"]))
        else:
            self.layer.setText("")
        rem = st.get("remaining")
        if rem:
            h, m = divmod(int(rem) // 60, 60)
            self.left.setText("%dh %02dm left" % (h, m) if h else "%dm left" % m)
        else:
            self.left.setText("")
        for key in ("nozzle", "bed", "chamber"):
            v, target = st.get(key), st.get(key + "_target")
            if v is None:
                continue
            self.temp_labels[key].setText("%.0f °C" % float(v) + (" / %.0f" % float(target) if target else ""))
            if target is not None:
                self._targets[key] = int(float(target))
            box = self.temp_set.get(key)
            if box is not None and not box.hasFocus() and target is not None:
                box.blockSignals(True)
                box.setValue(int(float(target)))
                box.blockSignals(False)
        self.light_button.blockSignals(True)
        self.light_button.setChecked(st.get("light") == "on")
        self.light_button.blockSignals(False)
        paused = state == "pause"
        self.pause_button.setText("Resume" if paused else "Pause")
        if self.printer is not None and st.get("file"):
            done = {"finish": "finish", "failed": "stopped", "running": "printing", "printing": "printing",
                    "pause": "pause"}.get(state)
            if done:
                update_job(self.printer.row, st["file"], done)
        if st.get("camera_error") and self.camera_button.isChecked():
            self.camera.setText("Camera: %s" % st["camera_error"])
        if state == "offline":
            self._enable(False)

    # ------------------------------------------------------------------ controls (as the slicers' Device tab)
    SPEEDS = (("Silent", 50), ("Standard", 100), ("Sport", 124), ("Ludicrous", 166))

    def _controls_box(self):
        box = QtWidgets.QGroupBox("Controls")
        g = QtWidgets.QGridLayout(box)
        self.speed = QtWidgets.QComboBox()
        for name, pct in self.SPEEDS:
            self.speed.addItem("%s (%d%%)" % (name, pct), pct)
        self.speed.setCurrentIndex(1)
        self.speed_set = QtWidgets.QPushButton("Set")
        self.speed_set.clicked.connect(lambda: self._confirmed(
            "Set the print speed to %s?" % self.speed.currentText(), lambda p: p.set_speed(self.speed.currentData())))
        g.addWidget(QtWidgets.QLabel("Speed"), 0, 0)
        g.addWidget(self.speed, 0, 1)
        g.addWidget(self.speed_set, 0, 2)
        self.fan_boxes = {}
        for i, (key, text) in enumerate((("part", "Part fan"), ("aux", "Aux fan"), ("chamber", "Chamber fan")), 1):
            spin = QtWidgets.QSpinBox()
            spin.setRange(0, 100)
            spin.setSuffix(" %")
            b = QtWidgets.QPushButton("Set")
            b.clicked.connect(lambda _=False, k=key, sp=spin, t=text: self._confirmed(
                "Set the %s to %d %%?" % (t.lower(), sp.value()), lambda p: p.set_fan(k, sp.value())))
            g.addWidget(QtWidgets.QLabel(text), i, 0)
            g.addWidget(spin, i, 1)
            g.addWidget(b, i, 2)
            self.fan_boxes[key] = (spin, b)
        self.step = QtWidgets.QComboBox()
        for mm in (1, 10, 50):
            self.step.addItem("%d mm" % mm, mm)
        self.step.setCurrentIndex(1)
        g.addWidget(QtWidgets.QLabel("Move by"), 4, 0)
        g.addWidget(self.step, 4, 1, 1, 2)
        self.jog_buttons = {}
        for col, axis in enumerate(("X", "Y", "Z")):
            for sign, text in ((1, axis + "+"), (-1, axis + "-")):
                b = QtWidgets.QPushButton(text)
                b.clicked.connect(lambda _=False, a=axis, sg=sign: self._confirmed(
                    "Move %s by %s%d mm?" % (a, "+" if sg > 0 else "-", self.step.currentData()),
                    lambda p: p.jog(a, sg * self.step.currentData())))
                g.addWidget(b, 5 if sign > 0 else 6, col)
                self.jog_buttons[text] = b
        self.home_button = QtWidgets.QPushButton("Home All Axes")
        self.home_button.clicked.connect(lambda: self._confirmed("Home all axes?", lambda p: p.home()))
        g.addWidget(self.home_button, 7, 0, 1, 3)
        self.controls = box
        return box

    def _confirmed(self, question, fn):
        """Every command to a printer asks first (until the owner has agreed to a real test)."""
        if self.printer is None:
            return False
        if os.environ.get("SWSTYLE_DEVICE_AUTOYES") != "1":
            if QtWidgets.QMessageBox.question(self, "Printer", question + "\n\n" + self.printer.row.get("name", "")
                                              ) != QtWidgets.QMessageBox.Yes:
                return False
        self._do(fn)
        return True

    def _do(self, fn):
        if self.printer is None:
            return
        row = self.printer.row
        self._bridge = run_in_thread(lambda: fn(self.printer), lambda r: self.error.setText(
            "<span style='color:#c00000'>%s</span>" % net.plain_error(r, row) if isinstance(r, Exception) else ""))

    def _pause(self):
        if self.pause_button.text() == "Resume":
            self._confirmed("Resume the print?", lambda p: p.resume())
        else:
            self._confirmed("Pause the print?", lambda p: p.pause())

    def _stop(self):
        self._confirmed("Stop the print? It cannot be resumed.", lambda p: p.stop())

    def _light(self, on):
        if not self._confirmed("Turn the printer's light %s?" % ("on" if on else "off"), lambda p: p.light(on)):
            self.light_button.blockSignals(True)
            self.light_button.setChecked(not on)
            self.light_button.blockSignals(False)

    def _set_temperature(self, key, name, box):
        target = box.value()
        if target == self._targets.get(key):
            return                                  # Enter on an unchanged value: nothing to ask
        if not self._confirmed("Set the %s to %d °C?" % (name.lower(), target), lambda p: p.set_temperature(key, target)):
            box.blockSignals(True)
            box.setValue(int(self._targets.get(key) or 0))
            box.blockSignals(False)

    # ------------------------------------------------------------------ jobs (the files sent from FreeCAD)
    def _jobs_box(self):
        box = QtWidgets.QGroupBox("Jobs")
        box.setObjectName("SWStyle_SlicerJobs")
        v = QtWidgets.QVBoxLayout(box)
        self.jobs = QtWidgets.QTreeWidget()
        self.jobs.setObjectName("SWStyle_SlicerJobList")
        self.jobs.setRootIsDecorated(False)
        self.jobs.setHeaderLabels(["Sent", "Printer", "File", "Result"])
        self.jobs.setMaximumHeight(140)
        v.addWidget(self.jobs)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        self.jobs_clear = QtWidgets.QPushButton("Clear List")
        self.jobs_clear.setToolTip("Clear the list of files sent from FreeCAD (the printers keep their files)")
        self.jobs_clear.clicked.connect(clear_jobs)
        row.addWidget(self.jobs_clear)
        v.addLayout(row)
        self.jobs_box = box
        Hub.get().jobs_changed.connect(self._fill_jobs)
        self._fill_jobs()
        return box

    def _fill_jobs(self):
        self.jobs.clear()
        rows = jobs()
        for r in rows:
            item = QtWidgets.QTreeWidgetItem([r.get("time", ""), r.get("printer", ""), r.get("file", ""),
                                              RESULT_TEXT.get(r.get("result"), r.get("result", ""))])
            if r.get("message"):
                item.setToolTip(3, r["message"])
            if r.get("result") == "failed":
                item.setForeground(3, QtGui.QBrush(QtGui.QColor("#c00000")))
            self.jobs.addTopLevelItem(item)
        for i in range(4):
            self.jobs.resizeColumnToContents(i)
        # the list shows once a file has been sent; nothing to clear before that
        self.jobs_box.setVisible(bool(rows))

    # ------------------------------------------------------------------ AMS (read only, as the slicers' Device tab)
    def _ams_box(self):
        box = QtWidgets.QGroupBox("AMS")
        box.setObjectName("SWStyle_SlicerAMS")
        self.ams_grid = QtWidgets.QGridLayout(box)
        self.ams_slots = []
        self.ams_box = box
        box.setVisible(False)
        return box

    def _show_ams(self, ams):
        """ams: the printer's report ({"ams": [{"id", "humidity", "tray": [...]}], "tray_now"}) or a unit list."""
        units = ams.get("ams") if isinstance(ams, dict) else ams
        units = [u for u in units or [] if isinstance(u, dict)]
        now = str(ams.get("tray_now", "")) if isinstance(ams, dict) else ""
        while self.ams_grid.count():
            item = self.ams_grid.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().setParent(None)
        self.ams_slots = []
        for row, unit in enumerate(units):
            uid = int(unit.get("id") or row)
            head = QtWidgets.QLabel("AMS %s" % chr(ord("A") + uid))
            hum = str(unit.get("humidity") or "")
            if hum:
                head.setToolTip("Humidity level %s (1 dry ... 5 wet)" % hum)
                head.setText(head.text() + "   humidity %s" % hum)
            self.ams_grid.addWidget(head, row * 2, 0, 1, 4)
            head.show()
            for t in unit.get("tray") or []:
                if not isinstance(t, dict):
                    continue
                tid = int(t.get("id") or 0)
                kind = t.get("tray_type") or ""
                colour = (t.get("tray_color") or "")[:6]
                slot = QtWidgets.QLabel(kind or "Empty")
                slot.setObjectName("SWStyle_SlicerAMSTray")
                slot.setAlignment(Qt.AlignCenter)
                slot.setMinimumSize(56, 28)
                active = now != "" and now == str(uid * 4 + tid)
                text_colour = "#000000"
                if len(colour) == 6:
                    r, g, b = (int(colour[i:i + 2], 16) for i in (0, 2, 4))
                    text_colour = "#000000" if (r * 299 + g * 587 + b * 114) / 1000 > 128 else "#ffffff"
                slot.setStyleSheet("background:%s; color:%s; border:%s; border-radius:3px;" % (
                    "#" + colour if len(colour) == 6 else "transparent", text_colour,
                    "2px solid #1f6fd1" if active else "1px solid #8a8a8a"))
                tip = ["Slot %d" % (tid + 1), t.get("tray_sub_brands") or kind or "Empty"]
                if t.get("remain") not in (None, -1, ""):
                    tip.append("%s %% left" % t.get("remain"))
                if active:
                    tip.append("printing from this slot")
                slot.setToolTip("\n".join(tip))
                self.ams_grid.addWidget(slot, row * 2 + 1, tid)
                slot.show()
                self.ams_slots.append({"unit": uid, "tray": tid, "type": kind, "colour": colour, "active": active,
                                       "widget": slot})
        self.ams_box.setVisible(bool(units))


# ---------------------------------------------------------------------- commands
def _icon(name):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "slicer", name + ".svg")


class AddPrinterCommand:
    def GetResources(self):
        return {"Pixmap": _icon("addprinter"), "MenuText": "Add Printer",
                "ToolTip": "Find printers on the network or in a Bambu Lab account, or type one in"}

    def Activated(self):
        AddPrinterDialog().exec()
        Hub.get().changed.emit()

    def IsActive(self):
        return True


class LoginCommand:
    def GetResources(self):
        return {"Pixmap": _icon("login"), "MenuText": "Log In",
                "ToolTip": "Log in to Bambu Lab: lists your printers with their access codes"}

    def Activated(self):
        if net.BambuAccount().logged_in():
            LoginDialog().exec()        # who is logged in, Log Out
            Hub.get().changed.emit()
        else:
            log_in(_main(), lambda text: Gui.getMainWindow().statusBar().showMessage(
                QtGui.QTextDocumentFragment.fromHtml(text).toPlainText(), 8000))

    def IsActive(self):
        return True


class SendCommand:
    def GetResources(self):
        return {"Pixmap": _icon("send"), "MenuText": "Send to Printer",
                "ToolTip": "Send the last slice to a printer and start it (with no slice yet, it slices first)"}

    def Activated(self):
        from . import slicerui
        slicerui.after_slice("Send to Printer", lambda _key, result: SendDialog(result).exec())

    def IsActive(self):
        from . import slicerui
        panel = slicerui.SlicerPanel.current
        return panel is None or panel.job is None


class DeviceCommand:
    def GetResources(self):
        return {"Pixmap": _icon("device"), "MenuText": "Device",
                "ToolTip": "The printer's live camera, state, temperatures and controls"}

    def Activated(self):
        DevicePanel.show_panel()

    def IsActive(self):
        return True


COMMANDS = (
    ("SWStyle_SlicerAddPrinter", AddPrinterCommand),
    ("SWStyle_SlicerLogin", LoginCommand),
    ("SWStyle_SlicerSend", SendCommand),
    ("SWStyle_SlicerDevice", DeviceCommand),
)

BUTTONS = (
    ("SlicerSend", "Send to Printer", "SWStyle_SlicerSend", "Sends the last slice to a printer and starts it (slices first when there is no slice yet).",
     "Send to\nPrinter", "send"),
    ("SlicerDevice", "Device", "SWStyle_SlicerDevice", "The printer's live camera, state and controls.",
     "Device", "device"),
    ("SlicerAddPrinter", "Add Printer", "SWStyle_SlicerAddPrinter", "Finds printers on the network or in your "
     "Bambu Lab account.", "Add\nPrinter", "addprinter"),
    ("SlicerLogin", "Log In", "SWStyle_SlicerLogin", "Logs in to your Bambu Lab account.", "Log\nIn", "login"),
)


def _v2(path):
    """v2last-1127: the V2 pack's themed picture for one of the add-on's own drawings, else the file itself."""
    from . import icons
    return icons.family(str(path))
