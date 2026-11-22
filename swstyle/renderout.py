# SPDX-License-Identifier: LGPL-2.1-or-later
""


















import os
import tempfile
import time

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    Gui = None

PREF = "User parameter:BaseApp/Preferences/Mod/FreeWorks/Render"
SIZES = (("Same as the view", 0, 0), ("640 x 480", 640, 480), ("1280 x 720 (HD)", 1280, 720),
         ("1920 x 1080 (Full HD)", 1920, 1080), ("3840 x 2160 (4K)", 3840, 2160), ("Custom", -1, -1))
QUALITY = (("Preview", 1), ("Good", 2), ("Best", 3))
FORMATS = (("PNG", "png"), ("JPEG", "jpg"), ("Bitmap", "bmp"), ("TIFF", "tif"))
BACKGROUNDS = (("As shown", "Current"), ("Transparent", "Transparent"), ("White", "White"), ("Black", "Black"))
_state = {"preview": None, "overlay": None, "last": None, "timers": []}


def _wb():
    """renderwb (the Render workbench link), or None when it cannot load."""
    try:
        from . import renderwb
        return renderwb
    except Exception:
        return None


def _p():
    return App.ParamGet(PREF)


def options():
    p = _p()
    return {"size": p.GetInt("Size", 2), "width": p.GetInt("Width", 1920), "height": p.GetInt("Height", 1080),
            "quality": p.GetInt("Quality", 1), "format": p.GetInt("Format", 0), "background": p.GetInt("Background", 0),
            "engine": p.GetString("Engine", "auto") or "auto", "rtpreview": p.GetInt("RayPreview", 1)}


def set_options(o):
    p = _p()
    p.SetInt("Size", o["size"])
    p.SetInt("Width", o["width"])
    p.SetInt("Height", o["height"])
    p.SetInt("Quality", o["quality"])
    p.SetInt("Format", o["format"])
    p.SetInt("Background", o["background"])
    p.SetString("Engine", o.get("engine", "auto"))
    p.SetInt("RayPreview", int(o.get("rtpreview", 1)))


def _say(text, ms=8000):
    try:
        Gui.getMainWindow().statusBar().showMessage(text, ms)
    except Exception:
        pass


def _view():
    try:
        v = Gui.ActiveDocument.ActiveView
        return v if hasattr(v, "saveImage") else None
    except Exception:
        return None


def _size(o):
    name, w, h = SIZES[min(o["size"], len(SIZES) - 1)]
    if w < 0:
        return max(16, o["width"]), max(16, o["height"])
    if w == 0:
        try:
            return tuple(int(x) for x in _view().getSize())
        except Exception:
            return 1280, 720
    return w, h


def render_image(w, h, factor, background):
    """The 3D view as a QImage w x h: drawn factor times larger and shrunk back for smooth edges."""
    view = _view()
    if view is None:
        raise RuntimeError("there is no 3D view to render")
    tmp = os.path.join(tempfile.gettempdir(), "fw_render_%d.png" % int(time.time() * 1000))
    view.saveImage(tmp, int(w * factor), int(h * factor), background)
    img = QtGui.QImage(tmp)
    try:
        os.remove(tmp)
    except OSError:
        pass
    if img.isNull():
        raise RuntimeError("the view could not be saved as a picture")
    if factor > 1:
        img = img.scaled(int(w), int(h), QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation)
    return img


def _render_with_options(o=None):
    o = o or options()
    w, h = _size(o)
    return render_image(w, h, QUALITY[min(o["quality"], 2)][1], BACKGROUNDS[min(o["background"], 3)][1])


def _engine(o, kind):
    """The Render workbench renderer for this job ("preview" or "final"), or None for the 3D-view render."""
    try:
        want = o.get("engine", "auto")
        if want == "builtin" or (kind == "preview" and not o.get("rtpreview", 1)):
            return None
        wb = _wb()
        names = wb.engine_names() if wb else []
        if not names:
            return None
        return want if want in names else names[0]
    except Exception:
        return None


def _with_camera(camera, fn):
    if not camera or _view() is None:
        return fn()
    view = _view()
    now = view.getCamera()
    view.setCamera(camera)
    QtWidgets.QApplication.processEvents()
    try:
        return fn()
    finally:
        view.setCamera(now)


def grab(w, h, kind, done, camera=None, tick=None, factor=2, background="Current"):
    """A picture w x h of the model, handed to done(image, note). Ray-traced through the Render workbench when one of its
    renderers is set up (note says so; it comes back when the renderer has ended), otherwise the 3D view drawn larger and
    shrunk back. If the ray tracer cannot start or fails, the 3D view is used and the note says why."""
    o = options()
    name = _engine(o, kind)

    def view_render(why=""):
        img = _with_camera(camera, lambda: render_image(w, h, factor, background))
        done(img, ("3D view drawn instead: %s" % why) if why else "")

    if name is None:
        view_render()
        return
    wb = _wb()
    if wb.busy():
        _say("A ray-traced render is still running: wait for it to finish")
        return
    if kind == "preview" and max(w, h) > 1280:
        scale = 1280.0 / max(w, h)
        w, h = max(16, int(w * scale)), max(16, int(h * scale))
    spp = wb.SAMPLES["preview"] if kind == "preview" else wb.SAMPLES["final"][min(o["quality"], 2)]
    out = os.path.join(tempfile.gettempdir(), "fw_rt_%d.png" % int(time.time() * 1000))

    def ok(path):
        img = QtGui.QImage(path)
        try:
            os.remove(path)
        except OSError:
            pass
        if img.isNull():
            view_render("the picture could not be read")
            return
        done(img, "ray-traced with %s" % name)

    def bad(why):
        App.Console.PrintWarning("FreeCAD: ray-traced render failed (%s)\n" % why)
        view_render(why)

    tell = tick or (lambda text: _say(text, 2000))
    try:
        tell("Preparing the scene for %s..." % name)
        QtWidgets.QApplication.processEvents()
    except Exception:
        pass
    try:
        wb.render(name, out, w, h, spp, ok, bad, tell, camera)
    except RuntimeError as error:
        App.Console.PrintWarning("FreeCAD: ray-traced render did not start (%s)\n" % error)
        view_render(str(error))


# ------------------------------------------------------------------ the picture windows
class Preview(QtWidgets.QDialog):
    def __init__(self):
        super().__init__(Gui.getMainWindow())
        self.setObjectName("SWRenderPreview")
        self.setWindowTitle("Preview Window")
        self.resize(820, 560)
        self.image = None
        lay = QtWidgets.QVBoxLayout(self)
        self.label = QtWidgets.QLabel("No picture yet")
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.label)
        lay.addWidget(scroll, 1)
        self.info = QtWidgets.QLabel()
        lay.addWidget(self.info)
        row = QtWidgets.QHBoxLayout()
        again = QtWidgets.QPushButton("Render")
        again.setToolTip("Renders the view as it is now, at the preview size")
        again.clicked.connect(self.render_again)
        save = QtWidgets.QPushButton("Save Image...")
        save.clicked.connect(self.save)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.close)
        for b in (again, save):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)

    def show_image(self, img, note=""):
        self.image = img
        shown = img if img.width() <= 780 else img.scaledToWidth(780, QtCore.Qt.SmoothTransformation)
        self.label.setPixmap(QtGui.QPixmap.fromImage(shown))
        self.info.setText("%d x %d pixels%s" % (img.width(), img.height(), (": " + note) if note else ""))

    def render_again(self):
        try:
            grab(960, 600, "preview", lambda img, note: self.show_image(img, note or "preview"), tick=self.info.setText)
        except Exception as error:
            self.info.setText(str(error))

    def save(self):
        if self.image is None:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Image", "render.png",
                                                        "Pictures (*.png *.jpg *.bmp *.tif)")
        if path:
            self.image.save(path)
            _say("Image saved: " + path)


def _preview_window():
    w = _state.get("preview")
    try:
        if w is not None:
            w.objectName()
            return w
    except RuntimeError:
        pass
    w = _state["preview"] = Preview()
    return w


def show_preview(img, note=""):
    w = _preview_window()
    w.show_image(img, note)
    w.show()
    w.raise_()


class _Overlay(QtWidgets.QLabel):
    """The picture over the 3D view; a click or Esc takes it away."""

    def __init__(self, parent, img):
        super().__init__(parent)
        self.setObjectName("SWIntegratedPreview")
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setStyleSheet("background: #202020;")
        self.img = img
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setGeometry(parent.rect())
        self._fit()
        self.show()
        self.raise_()
        self.setFocus()

    def _fit(self):
        self.setPixmap(QtGui.QPixmap.fromImage(self.img.scaled(self.size(), QtCore.Qt.KeepAspectRatio,
                                                                QtCore.Qt.SmoothTransformation)))

    def mousePressEvent(self, event):
        self.close_preview()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.close_preview()
        else:
            super().keyPressEvent(event)

    def close_preview(self):
        _state["overlay"] = None
        self.hide()
        self.deleteLater()


def _view_widget():
    try:
        from .pmtakeover import view_widget
        return view_widget()
    except Exception:
        return None


# ------------------------------------------------------------------ the commands
def _integrated():
    old = _state.get("overlay")
    if old is not None:
        try:
            old.close_preview()
        except RuntimeError:
            pass
        return
    host = _view_widget()
    if host is None:
        _say("Integrated Preview: there is no 3D view")
        return

    def show(img, note):
        if _state.get("overlay") is not None:
            return
        try:
            _state["last"] = img
            _state["overlay"] = _Overlay(host, img)
            _say("Integrated Preview%s: click the picture or press Esc to go back to the model"
                 % ((" (" + note + ")") if note else ""), 15000)
        except RuntimeError:
            pass

    grab(max(host.width(), 16), max(host.height(), 16), "preview", show)


def _preview():
    w = _preview_window()
    w.show()
    w.raise_()
    grab(960, 600, "preview", lambda img, note: show_preview(img, note or "preview"), tick=w.info.setText)
    _say("Preview Window: Render draws the view again, Save Image keeps it")


def _final():
    o = options()
    ext = FORMATS[min(o["format"], 3)][1]
    doc = App.ActiveDocument
    base = os.path.dirname(doc.FileName) if doc is not None and doc.FileName else _p().GetString("Folder", "") or os.path.expanduser("~")
    start = os.path.join(base, "%s render.%s" % (doc.Label if doc is not None else "model", ext))
    path, _ = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Final Render", start,
                                                    "%s (*.%s)" % (FORMATS[min(o["format"], 3)][0], ext))
    ray = _engine(o, "final") is not None
    if not path and ray:
        return
    if path and not path.lower().endswith("." + ext):
        path += "." + ext
    if ray:
        _say("Final Render: the renderer is working, FreeCAD stays usable", 8000)

    def done(img, note):
        _state["last"] = img
        tag = (" (" + note + ")") if note else ""
        if not path:
            show_preview(img, "not saved" + tag)
            return
        if not img.save(path, None, 95):
            _say("Final Render: could not save " + path)
            return
        _p().SetString("Folder", os.path.dirname(path))
        _p().SetString("LastRender", path)
        show_preview(img, path + tag)
        _say("Final Render saved: " + path + tag, 12000)

    w, h = _size(o)
    grab(w, h, "final", done, factor=QUALITY[min(o["quality"], 2)][1], background=BACKGROUNDS[min(o["background"], 3)][1])


def _recall():
    img = _state.get("last")
    path = _p().GetString("LastRender", "")
    if img is None and path and os.path.isfile(path):
        img = QtGui.QImage(path)
    if img is None or img.isNull():
        _say("Recall Last Render: no render yet. Final Render makes one")
        return
    show_preview(img, path)


class OptionsPanel:
    """PhotoView 360 Options: the output of Final Render."""

    def __init__(self):
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Render Options")
        o = options()
        lay = QtWidgets.QFormLayout(self.form)
        self.size = QtWidgets.QComboBox()
        self.size.addItems([s[0] for s in SIZES])
        self.size.setCurrentIndex(min(o["size"], len(SIZES) - 1))
        self.width = QtWidgets.QSpinBox()
        self.width.setRange(16, 16000)
        self.width.setValue(o["width"])
        self.height = QtWidgets.QSpinBox()
        self.height.setRange(16, 16000)
        self.height.setValue(o["height"])
        self.quality = QtWidgets.QComboBox()
        self.quality.addItems([q[0] for q in QUALITY])
        self.quality.setCurrentIndex(min(o["quality"], 2))
        self.format = QtWidgets.QComboBox()
        self.format.addItems([f[0] for f in FORMATS])
        self.format.setCurrentIndex(min(o["format"], 3))
        self.back = QtWidgets.QComboBox()
        self.back.addItems([b[0] for b in BACKGROUNDS])
        self.back.setCurrentIndex(min(o["background"], 3))
        for label, w in (("Output image size", self.size), ("Width", self.width), ("Height", self.height),
                         ("Output image quality", self.quality), ("Image format", self.format), ("Background", self.back)):
            lay.addRow(label, w)
        self.engine = self.rt = None
        self.engine_ids = ["auto", "builtin"]
        wb = _wb()
        if wb is not None and wb.installed():
            found = wb.engines()
            if found:
                self.engine = QtWidgets.QComboBox()
                self.engine.addItems(["Automatic (ray-traced)", "3D view (built in)"] + [label for label, _ in found])
                self.engine_ids += [name for _, name in found]
                self.engine.setCurrentIndex(self.engine_ids.index(o["engine"]) if o["engine"] in self.engine_ids else 0)
                self.rt = QtWidgets.QCheckBox("Ray-trace the previews too (slower)")
                self.rt.setChecked(bool(o["rtpreview"]))
                lay.addRow("Renderer", self.engine)
                lay.addRow("", self.rt)
                lay.addRow(QtWidgets.QLabel("With a renderer, quality is the number of samples per pixel and the\n"
                                            "background comes from its scene template."))
            else:
                lay.addRow(QtWidgets.QLabel("The Render workbench is installed, but %s.\nUntil then the 3D view is used."
                                            % wb.why_not()))
        self.size.currentIndexChanged.connect(self._custom)
        self._custom()

    def _custom(self):
        on = SIZES[self.size.currentIndex()][1] < 0
        self.width.setEnabled(on)
        self.height.setEnabled(on)

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def accept(self):
        set_options({"size": self.size.currentIndex(), "width": self.width.value(), "height": self.height.value(),
                     "quality": self.quality.currentIndex(), "format": self.format.currentIndex(),
                     "background": self.back.currentIndex(),
                     "engine": self.engine_ids[self.engine.currentIndex()] if self.engine is not None else options()["engine"],
                     "rtpreview": int(self.rt.isChecked()) if self.rt is not None else options()["rtpreview"]})
        Gui.Control.closeDialog()
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True


def _options():
    if Gui.Control.activeDialog():
        return
    Gui.Control.showDialog(OptionsPanel())
    _say("Set the render size, quality and format, then click OK", 10000)


class ScheduleDialog(QtWidgets.QDialog):
    def __init__(self):
        super().__init__(Gui.getMainWindow())
        self.setWindowTitle("Schedule Render")
        lay = QtWidgets.QFormLayout(self)
        self.when = QtWidgets.QDateTimeEdit(QtCore.QDateTime.currentDateTime().addSecs(120))
        self.when.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.when.setCalendarPopup(True)
        self.folder = QtWidgets.QLineEdit(_p().GetString("Folder", "") or os.path.expanduser("~"))
        browse = QtWidgets.QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.folder, 1)
        row.addWidget(browse)
        lay.addRow("Start rendering at", self.when)
        lay.addRow("Save in", row)
        lay.addRow(QtWidgets.QLabel("The view as it is now is rendered with the Options size, quality and renderer.\nFreeCAD has to stay open until then."))
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.button(QtWidgets.QDialogButtonBox.Ok).setText("Schedule")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)

    def _browse(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Save in", self.folder.text())
        if d:
            self.folder.setText(d)


def _schedule():
    view = _view()
    if view is None:
        _say("Schedule Render: there is no 3D view")
        return
    dlg = ScheduleDialog()
    if not dlg.exec_():
        return
    ms = max(0, QtCore.QDateTime.currentDateTime().msecsTo(dlg.when.dateTime()))
    folder = dlg.folder.text().strip() or os.path.expanduser("~")
    camera = view.getCamera()
    docname = App.ActiveDocument.Name
    o = options()

    def fire():
        try:
            doc = App.getDocument(docname)
            try:
                App.setActiveDocument(docname)
                Gui.setActiveDocument(docname)
            except Exception:
                pass
            w, h = _size(o)

            def saved(img, note):
                path = os.path.join(folder, "%s %s.%s" % (doc.Label, time.strftime("%Y%m%d-%H%M%S"), FORMATS[min(o["format"], 3)][1]))
                img.save(path, None, 95)
                _p().SetString("LastRender", path)
                _state["last"] = img
                _say("Scheduled render saved: %s%s" % (path, (" (" + note + ")") if note else ""), 20000)

            grab(w, h, "final", saved, camera=camera, factor=QUALITY[min(o["quality"], 2)][1],
                 background=BACKGROUNDS[min(o["background"], 3)][1])
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: scheduled render failed (%s)\n" % error)
            _say("Scheduled render failed: %s" % error, 20000)

    timer = QtCore.QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(fire)
    timer.start(int(ms))
    _state["timers"] = [t for t in _state["timers"] if t.isActive()] + [timer]
    _say("Render scheduled for %s: keep FreeCAD open until then" % dlg.when.dateTime().toString("HH:mm"), 12000)


# ------------------------------------------------------------------ registration
COMMANDS = (
    ("FW_RT_Integrated", "Integrated Preview", "The picture laid over the 3D view; a click goes back to the model.", _integrated),
    ("FW_RT_Preview", "Preview Window", "The picture in a window of its own.", _preview),
    ("FW_RT_Final", "Final Render", "Renders at the Options size and saves the picture.", _final),
    ("FW_RT_Options", "Render Options", "Output size, quality, format and background of Final Render.", _options),
    ("FW_RT_Schedule", "Schedule Render", "Renders the view as it is now at a time you set.", _schedule),
    ("FW_RT_Recall", "Recall Last Render", "Shows the last picture again.", _recall),
)
KEYS = (
    ("RT_Integrated", "Integrated Preview", "FW_RT_Integrated", "Integrated\nPreview"),
    ("RT_Preview", "Preview Window", "FW_RT_Preview", "Preview\nWindow"),
    ("RT_Final", "Final Render", "FW_RT_Final", "Final\nRender"),
    ("RT_Options", "Render Options", "FW_RT_Options", "Options"),
    ("RT_Schedule", "Schedule Render", "FW_RT_Schedule", "Schedule\nRender"),
    ("RT_Recall", "Recall Last Render", "FW_RT_Recall", "Recall Last\nRender"),
)
SEP = ("sep",)
LAYOUT = (("large", "EditAppearance", None), ("large", "CopyAppearance", None), ("large", "PasteAppearance", None),
          ("large", "EditDecal", None), ("large", "ApplyScene", None), SEP,
          ("large", "RT_Integrated", None), ("large", "RT_Preview", None), ("large", "RT_Final", None),
          ("large", "RT_Options", None), ("large", "RT_Schedule", None), ("large", "RT_Recall", None), SEP,
          ("large", "ChangeDisplayStates", None))


class _Cmd:
    def __init__(self, text, tip, run):
        self.text, self.tip, self.run = text, tip, run

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip}

    def IsActive(self):
        try:
            return _view() is not None and not Gui.Control.activeDialog()
        except Exception:
            return False

    def Activated(self):
        try:
            self.run()
        except Exception as error:
            App.Console.PrintError("FreeCAD render: %s\n" % error)
            _say("%s: %s" % (self.text, error))


def install():
    """After the add-in tabs: the commands, the keys, and the Render Tools tab with PhotoView 360's buttons."""
    if Gui is None:
        return
    try:
        from . import catalog, cmtabs
        for name, text, tip, run in COMMANDS:
            if name not in Gui.listCommands():
                Gui.addCommand(name, _Cmd(text, tip, run))
        for key, label, native, caption in KEYS:
            if key not in catalog.BY_KEY:
                catalog.BY_KEY[key] = catalog.c(key, label, (native,), None, label, caption=caption)
        catalog.ALL = tuple(catalog._ALL)
        if "Render Tools" in cmtabs.TABS and not any("RT_Final" in repr(i) for i in cmtabs.TABS["Render Tools"]):
            cmtabs.TABS["Render Tools"] = LAYOUT
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: render tools not added (%s)\n" % error)
