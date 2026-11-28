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

import hashlib
import time
from pathlib import Path

import FreeCAD as App
from PySide import QtCore, QtGui, QtWidgets

from . import slicer, slicerembed

Qt = QtCore.Qt
WATCH_MS = 2000
PRINT3D = ("orca", "bambu", "prusa")     # slicers sent one 3MF with names, colours and plates (slicer3mf)


def sheet():
    """The strip and status line in the CommandManager's colours for the current theme."""
    try:
        from . import style
        t = style.tokens()
    except Exception as _fw_err:
        _fw_log("slicertab.py:43", _fw_err)
        return ""
    return ("QFrame#SWStyle_SlicerStrip{background:%(pane)s;border-bottom:1px solid %(line)s;}"
            "QFrame#SWStyle_SlicerStrip QToolButton{color:%(text)s;background:transparent;border:1px solid transparent;"
            "padding:3px 8px;}"
            "QFrame#SWStyle_SlicerStrip QToolButton:hover{background:%(hover)s;border:1px solid %(hover_line)s;}"
            "QFrame#SWStyle_SlicerStrip QToolButton:pressed{background:%(down)s;border:1px solid %(down_line)s;}"
            "QLabel#SWStyle_SlicerStatus{background:%(pane)s;color:%(text_dim)s;border-top:1px solid %(line)s;}") % t


def parts_dir():
    path = Path(App.getUserAppDataDir()) / "SolidWorksStyle" / "slicer-parts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def shape_key(objects):
    """A short fingerprint of the objects' shapes (placement included)."""
    h = hashlib.sha1()
    for obj in objects:
        try:
            s = obj.Shape
            h.update(("%s|%.6f|%.6f|%d|%d|%s" % (obj.Name, s.Volume, s.Area, len(s.Faces), len(s.Edges),
                                                  s.Placement.toMatrix())).encode())
        except Exception:
            h.update(obj.Name.encode())
    return h.hexdigest()


def keep_positions():
    """Send several bodies as one object whose parts keep their places (an assembly's default)."""
    return slicer.params().GetBool("KeepAssemblyPositions", True)


def write_3mf(objects, path, linear=0.003, angular=0.5, together=False):
    """Several bodies as one 3MF, one plate object each: unit millimetre, the object's label as its name.
    Returns the number of triangles."""
    import zipfile
    from xml.sax.saxutils import quoteattr
    import Mesh
    import MeshPart
    out, build, total = [], [], 0
    for i, obj in enumerate(objects, 1):
        m = slicer.object_mesh(obj, linear, angular)
        pts = m.Topology[0]
        tris = m.Topology[1]
        total += len(tris)
        out.append('  <object id="%d" name=%s type="model"><mesh><vertices>%s</vertices><triangles>%s</triangles></mesh></object>' % (
            i, quoteattr(obj.Label),
            "".join('<vertex x="%.6f" y="%.6f" z="%.6f"/>' % (v.x, v.y, v.z) for v in pts),
            "".join('<triangle v1="%d" v2="%d" v3="%d"/>' % t for t in tris)))
        if not together:
            build.append('<item objectid="%d"/>' % i)
    if together:
        n = len(objects)
        out.append('  <object id="%d" name=%s type="model"><components>%s</components></object>' % (
            n + 1, quoteattr(objects[0].Document.Label or "Assembly"),
            "".join('<component objectid="%d"/>' % i for i in range(1, n + 1))))
        build.append('<item objectid="%d"/>' % (n + 1))
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" '
             'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">\n <resources>\n%s\n </resources>\n'
             ' <build>%s</build>\n</model>\n') % ("\n".join(out), "".join(build))
    with zipfile.ZipFile(str(path), "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        z.writestr("3D/3dmodel.model", model)
    return total


def export_part(objects, path):
    """One body: an STL; several bodies (a multi-body part, an assembly's parts): one 3MF with each as its
    own plate object. Returns the triangles written."""
    if len(objects) == 1:
        return slicer.export_mesh(objects, path)[1]
    return write_3mf(objects, path, together=keep_positions())


class SlicerTab(QtWidgets.QWidget):
    """key: "orca" | "bambu" | an added app's key; exe: the program; title for the tab."""

    def __init__(self, key, title, exe, parent=None):
        super().__init__(parent)
        self.key, self.title = key, title
        self.setObjectName("SWStyle_SlicerTab_" + key)
        self.setWindowTitle(title)
        self.sent = {}          # file path -> {"doc", "names", "key"}
        self._asked = set()     # files whose current change was already asked about
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._strip())
        self.host = slicerembed.EmbedHost(title, exe)
        known = slicer.SLICERS.get(key)
        if known is not None:
            # a settings folder of the program's own (SWSTYLE_<KEY>_DATADIR): the window and the second start that
            # hands files over use it both (the second start finds the open window through it)
            self.host.lead_args = list(known.datadir_args())
            self.host.second_args = tuple(known.datadir_args()) + tuple(known.second_args)
        if slicer.params().GetString("HandOver", "") == "message":
            self.host.hand_over = "message"
        lay.addWidget(self.host, 1)
        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("SWStyle_SlicerStatus")
        self.status.setContentsMargins(6, 2, 6, 2)
        self.status.setStyleSheet(sheet())
        lay.addWidget(self.status)
        self.host.failed.connect(self.status.setText)
        self.host.stray_copy.connect(self.status.setText)
        self.host.ended.connect(lambda: self.status.setText("%s was closed." % title))
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(WATCH_MS)
        self.timer.timeout.connect(self.watch)
        self.timer.start()
        try:                                       # once a day: look at the release pages, show how many are newer
            from . import slicerupdate
            slicerupdate.background_look()
            QtCore.QTimer.singleShot(8000, self.badge)
        except Exception as _fw_err:
            _fw_log("slicertab.py:152", _fw_err)

    def badge(self):
        """"Slicer Updates (2)" when a newer Orca Slicer or Bambu Studio is out."""
        try:
            from . import slicerupdate
            n = slicerupdate.available_count()
        except Exception:
            return
        self.updates_button.setText("Slicer Updates (%d)" % n if n else "Slicer Updates")

    # ------------------------------------------------------------------ the strip
    def _strip(self):
        bar = QtWidgets.QFrame()
        bar.setObjectName("SWStyle_SlicerStrip")
        bar.setStyleSheet(sheet())
        row = QtWidgets.QHBoxLayout(bar)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(2)
        res = Path(__file__).parent / "resources" / "slicer"
        for text, icon, tip, fn in (
                ("Send Part", "send", "Put the selected part (or every body, or the 3D Slicer panel's plates) on the slicer's plate, "
                 "with each part's name and color", self.send_part),
                ("Reload Part", "update", "Reload the part from FreeCAD into the slicer, keeping its orientation and settings",
                 self.reload_all),
                ("Slicer Updates", "update", "Check for a newer " + self.title, self.updates),
                ("Slicer Apps", "printer", "Add another slicer by dropping its installer", self.apps)):
            b = QtWidgets.QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setIcon(_v2(str(res / (icon + ".svg"))))
            b.setIconSize(QtCore.QSize(24, 24))
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.clicked.connect(fn)
            row.addWidget(b)
            if text == "Slicer Updates":
                self.updates_button = b
        keep = QtWidgets.QCheckBox("Keep assembly positions")
        keep.setToolTip("Several bodies go to the slicer as one object whose parts stay where they are in the "
                        "assembly. Off: each body is its own object on the plate.")
        keep.setChecked(keep_positions())
        keep.toggled.connect(lambda on: slicer.params().SetBool("KeepAssemblyPositions", bool(on)))
        row.addWidget(keep)
        row.addStretch(1)
        return bar

    def start(self):
        return self.host.start()

    # ------------------------------------------------------------------ the part
    def send_part(self):
        if self.key in PRINT3D and self.send_print3d():
            return
        objects = slicer.printable()
        if not objects:
            self.status.setText("Nothing to send: pick a body or solid.")
            return
        doc = App.ActiveDocument
        name = slicer.safe_name("%s-%s" % (doc.Name, "+".join(o.Label for o in objects)[:40]))
        path = parts_dir() / (name + (".stl" if len(objects) == 1 else ".3mf"))
        facets = export_part(objects, path)
        if not self.host.open_files([path]):
            self.status.setText("Could not send %s to %s: the handoff/start failed. Use Send Part to retry."
                                % (path.name, self.title))
            return
        self.sent[str(path)] = {"doc": doc.Name, "names": [o.Name for o in objects], "key": shape_key(objects)}
        self._asked.discard(str(path))
        self.status.setText("Sent %s (%d triangles) to %s." % (path.name, facets, self.title))

    def send_print3d(self):
        ""

        from . import slicer3mf
        data = slicer3mf.gather(self.key)
        if not data["items"] or (len(data["items"]) == 1 and not data["panel"]):
            return False
        doc = App.ActiveDocument
        path = slicer3mf.default_path(self.key, parts_dir())
        from . import slicerui
        QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ok, msg, paths = slicer3mf.write(self.key, path, env=slicerui.clean_env())
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        if not ok:
            self.status.setText("Could not write the 3MF for %s: %s" % (self.title, msg))
            return True
        if not self.host.open_files(paths[:1]):
            self.status.setText("Could not send %s to %s: the handoff/start failed. Use Send Part to retry."
                                % (paths[0].name, self.title))
            return True
        objects = [o for o in data["sources"] if o is not None]
        self.sent[str(paths[0])] = {"doc": doc.Name if doc else "", "names": [o.Name for o in objects],
                                    "key": shape_key(objects), "print3d": True}
        self._asked.discard(str(paths[0]))
        more = " (%d more plate files beside it: PrusaSlicer opens one plate at a time)" % (len(paths) - 1) \
            if len(paths) > 1 else ""
        self.status.setText("Sent %s to %s: %d part(s) with their names, colors and plates%s."
                            % (paths[0].name, self.title, len(data["items"]), more))
        return True

    def _objects(self, info):
        doc = App.getDocument(info["doc"]) if info["doc"] in App.listDocuments() else None
        if doc is None:
            return []
        return [o for o in (doc.getObject(n) for n in info["names"]) if o is not None]

    def watch(self):
        ""
        for path, info in list(self.sent.items()):
            if path in self._asked or not self.host.running():
                continue
            objects = self._objects(info)
            if objects and shape_key(objects) != info["key"]:
                self._asked.add(path)
                self.ask(path)

    def ask(self, path):
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Part changed")
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setText("%s changed in FreeCAD. Reload it in %s?" % (Path(path).stem, self.title))
        if (self.sent.get(path) or {}).get("print3d"):
            box.setText("%s changed in FreeCAD. Send the parts to %s again?" % (Path(path).stem, self.title))
            box.setInformativeText("The parts go again with their names, colors and plates; %s asks what to do "
                                   "with the project it has open." % self.title)
        else:
            box.setInformativeText("Its orientation, position and print settings in the slicer are kept. A cut or "
                                   "other change you made to this part inside the slicer is replaced by the "
                                   "FreeCAD shape.")
        box.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        box.setDefaultButton(QtWidgets.QMessageBox.Yes)
        if box.exec_() == QtWidgets.QMessageBox.Yes:
            self.reload(path)

    def reload(self, path):
        info = self.sent.get(path)
        objects = self._objects(info) if info else []
        if not objects:
            return False
        if info.get("print3d"):
            # a whole project (names, colours, plates): sent again, and the slicer asks what to do with the open one
            self._asked.discard(path)
            return self.send_print3d()
        export_part(objects, path)                      # same file, same name: Reload from Disk finds it
        if not self.host.reload_from_disk():
            self.status.setText("Could not reload %s in %s. Use Reload Part to retry."
                                % (Path(path).name, self.title))
            return False
        info["key"] = shape_key(objects)
        self._asked.discard(path)
        self.status.setText("Reloaded %s in %s." % (Path(path).name, self.title))
        return True

    def reload_all(self):
        done = [p for p in list(self.sent) if self.reload(p)]
        if not done and not self.sent:
            self.status.setText("Nothing sent yet: use Send Part first.")

    # ------------------------------------------------------------------ the other buttons
    def updates(self):
        from . import slicerupdate
        box = slicerupdate.open_box(self)
        try:
            box.finished.connect(lambda *_: self.badge())
        except Exception as _fw_err:
            _fw_log("slicertab.py:274", _fw_err)

    def apps(self):
        from . import slicerapps
        slicerapps.open_box(self)

    def closeEvent(self, event):
        self.timer.stop()
        if not self.host.shutdown():
            self.status.setText("%s is still open: it may be asking to save." % self.title)
            event.ignore()
            return
        super().closeEvent(event)


def mdi_area():
    import FreeCADGui as Gui
    win = Gui.getMainWindow()
    return win.findChild(QtWidgets.QMdiArea)


def open_tab(key, title, exe):
    """Show the slicer's tab (the one already open is brought forward)."""
    area = mdi_area()
    for sub in (area.subWindowList() if area else []):
        if sub.widget() is not None and sub.widget().objectName() == "SWStyle_SlicerTab_" + key:
            area.setActiveSubWindow(sub)
            return sub.widget()
    tab = SlicerTab(key, title, exe)
    if area is not None:
        area.subWindowActivated.connect(lambda sub, t=tab: t.host.follow(sub is not None and sub.widget() is t))
        sub = area.addSubWindow(tab)
        sub.setWindowTitle(title)
        icon = Path(__file__).parent / "resources" / "slicer" / "printer.svg"
        sub.setWindowIcon(_v2(str(icon)))
        sub.showMaximized()
    else:
        tab.show()
    tab.start()
    return tab


def _v2(path):
    """v2last-1127: the V2 pack's themed picture for one of the add-on's own drawings, else the file itself."""
    from . import icons
    return icons.family(str(path))
