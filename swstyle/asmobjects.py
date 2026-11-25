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
import tempfile

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

OBJECT_TYPE = "SWStyle::OleObject"


class OleObject:
    Type = OBJECT_TYPE

    def __init__(self, obj, kind):
        obj.Proxy = self
        for t, name, tip in (("App::PropertyString", "Kind", "Object or Hyperlink"),
                             ("App::PropertyFile", "LinkedFile", "The linked file (Link to file)"),
                             ("App::PropertyFileIncluded", "Embedded", "The file kept in the document"),
                             ("App::PropertyString", "Address", "Hyperlink address"),
                             ("App::PropertyString", "Text", "The text shown"),
                             ("App::PropertyBool", "AsIcon", "Display as Icon"),
                             ("App::PropertyFloat", "Scale", "Display size"),
                             ("App::PropertyVector", "Position", "Where it shows")):
            obj.addProperty(t, name, "Object", tip)
        obj.Kind = kind
        obj.Scale = 1.0

    def execute(self, obj):
        pass

    def onDocumentRestored(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


class OleView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        from pivy import coin
        self.Object = vobj.Object
        self.root = coin.SoSeparator()
        self.trans = coin.SoTranslation()
        self.colour = coin.SoBaseColor()
        self.colour.rgb.setValue(0.1, 0.3, 0.8)
        self.font = coin.SoFont()
        self.text = coin.SoText2()
        for n in (self.trans, self.colour, self.font, self.text):
            self.root.addChild(n)
        vobj.addDisplayMode(self.root, "Default")
        self.updateData(vobj.Object, "Text")

    def updateData(self, obj, prop):
        if not hasattr(self, "text"):
            return
        p = obj.Position
        self.trans.translation.setValue(p.x, p.y, p.z)
        label = display_text(obj)
        self.text.string.setValues(0, 1, [label])
        self.font.size = 14.0 * max(0.2, float(obj.Scale or 1.0))

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def getIcon(self):
        return ":/icons/web-browser.svg" if self.Object.Kind == "Hyperlink" else ":/icons/Std_Attachment.svg"

    def doubleClicked(self, vobj):
        open_object(vobj.Object)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def display_text(obj):
    if obj.AsIcon:
        return "[%s]" % ("link" if obj.Kind == "Hyperlink" else "object")
    if obj.Kind == "Hyperlink":
        return obj.Text or obj.Address
    return obj.Text or os.path.basename(obj.LinkedFile or obj.Embedded or "")


def objects(doc):
    return [o for o in (doc.Objects if doc else []) if getattr(getattr(o, "Proxy", None), "Type", None) == OBJECT_TYPE]


def _box(doc):
    """The bounding box of the model's visible solids (not the origin planes)."""
    bb = None
    for o in doc.Objects:
        s = getattr(o, "Shape", None)
        if s is None or s.isNull() or not o.Visibility or not s.Solids or o.TypeId == "Part::DatumPlane":
            continue
        if bb is None:
            bb = App.BoundBox(s.BoundBox)
        else:
            bb.add(s.BoundBox)
    return bb if bb is not None and bb.isValid() else None


def _centre(doc):
    bb = _box(doc)
    return bb.Center if bb is not None else App.Vector()


def _make(doc, kind, label):
    o = doc.addObject("App::FeaturePython", kind)
    OleObject(o, kind)
    if App.GuiUp:
        OleView(o.ViewObject)
    o.Position = _centre(doc)
    n = len([x for x in objects(doc) if x.Kind == kind])
    o.Label = "%s%d" % (label, n)
    return o


def insert_object(doc, path, link=False):
    doc.openTransaction("Insert Object")
    try:
        o = _make(doc, "Object", "Object")
        if link:
            o.LinkedFile = path
        else:
            o.Embedded = path
        o.Text = os.path.basename(path)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    doc.recompute()
    return o


def insert_hyperlink(doc, address, text=""):
    doc.openTransaction("Insert Hyperlink")
    try:
        o = _make(doc, "Hyperlink", "Hyperlink")
        o.Address, o.Text = address, text or address
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    doc.recompute()
    return o


def open_object(obj, opener=None):
    """Double-click: the file in its program, or the address in the browser."""
    if obj.Kind == "Hyperlink":
        url = QtCore.QUrl.fromUserInput(obj.Address)
    else:
        url = QtCore.QUrl.fromLocalFile(obj.LinkedFile or obj.Embedded)
    return (opener or QtGui.QDesktopServices.openUrl)(url)


def insert_picture(doc, path):
    """An image plane facing the view, at the model's centre, sized to a third of the model."""
    import Image  # noqa: F401  (loads the Image module's types)
    reader = QtGui.QImageReader(path)
    size = reader.size()
    if not size.isValid() or size.width() <= 0:
        return None
    doc.openTransaction("Insert Picture")
    try:
        o = doc.addObject("Image::ImagePlane", "Picture")
        o.ImageFile = path
        bb = _box(doc)
        w = (bb.DiagonalLength / 3.0) if bb is not None else 100.0
        o.XSize, o.YSize = w, w * size.height() / float(size.width())
        rot = App.Rotation()
        try:
            rot = Gui.ActiveDocument.ActiveView.getCameraOrientation()
        except Exception as _fw_err:
            _fw_log("asmobjects.py:202", _fw_err)
        o.Placement = App.Placement(_centre(doc), rot)
        o.Label = "Picture%d" % len([x for x in doc.Objects if x.TypeId == "Image::ImagePlane"])
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    doc.recompute()
    return o


def picked_objects():
    return [s.Object for s in Gui.Selection.getSelectionEx() if getattr(getattr(s.Object, "Proxy", None), "Type", None) == OBJECT_TYPE]


def set_icon(objs, on):
    for o in objs:
        o.AsIcon = bool(on)
        o.touch()
    App.ActiveDocument.recompute()


def reset_size(objs):
    for o in objs:
        o.Scale = 1.0
        o.touch()
    App.ActiveDocument.recompute()


# ---------------------------------------------------------------------- Edit entries
def copy_to_illustrator(path=None):
    """The view as SVG on the clipboard (image/svg+xml, and the text for programs that take it)."""
    view = Gui.ActiveDocument.ActiveView
    path = path or os.path.join(tempfile.gettempdir(), "freeworks-view-%d.svg" % os.getpid())     # pkg321: per session
    view.saveVectorGraphic(path)
    with open(path, "rb") as f:
        data = f.read()
    mime = QtCore.QMimeData()
    mime.setData("image/svg+xml", QtCore.QByteArray(data))
    mime.setText(data.decode("utf-8", "replace"))
    mime.setUrls([QtCore.QUrl.fromLocalFile(path)])
    QtWidgets.QApplication.clipboard().setMimeData(mime)
    try:
        Gui.getMainWindow().statusBar().showMessage(
            "Copied the view to the clipboard as vector graphics (SVG): paste it into Illustrator or Inkscape.", 6000)
    except Exception as _fw_err:
        _fw_log("asmobjects.py:245", _fw_err)
    return path


def _flippable(obj):
    return obj.TypeId in ("Part::DatumPlane", "PartDesign::Plane", "App::Plane") or \
        (hasattr(obj, "Shape") and obj.TypeId in ("Part::Feature", "Part::FeaturePython") and
         not obj.Shape.isNull() and obj.Shape.Faces and not obj.Shape.Solids)


def flippable():
    return [s.Object for s in Gui.Selection.getSelectionEx() if _flippable(s.Object)]


def flip_normal(objs):
    """Planes turn half a turn about their own X; surfaces have their faces reversed."""
    if not objs:
        return 0
    doc = objs[0].Document
    doc.openTransaction("Flip Normal")
    try:
        for o in objs:
            if hasattr(o, "MapReversed") and getattr(o, "MapMode", "Deactivated") != "Deactivated":
                o.MapReversed = not o.MapReversed
            elif o.TypeId in ("Part::DatumPlane", "PartDesign::Plane", "App::Plane"):
                pl = o.Placement
                o.Placement = App.Placement(pl.Base, pl.Rotation.multiply(App.Rotation(App.Vector(1, 0, 0), 180)))
            else:
                o.Shape = o.Shape.reversed()
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    doc.recompute()
    return len(objs)


def curves():
    return [s.Object for s in Gui.Selection.getSelectionEx()
            if s.Object.TypeId.startswith("Sketcher::") or s.Object.TypeId in ("Part::Part2DObjectPython", "Part::Spline")
            or (hasattr(s.Object, "Shape") and not s.Object.Shape.isNull() and s.Object.Shape.Edges and not s.Object.Shape.Faces)]


def set_curve_colour(objs, rgb):
    for o in objs:
        v = o.ViewObject
        for p in ("LineColor", "PointColor"):
            if hasattr(v, p):
                setattr(v, p, rgb)
    return len(objs)


def pick_curve_colour(objs):
    c = QtWidgets.QColorDialog.getColor(QtGui.QColor(0, 0, 0), Gui.getMainWindow(), "Sketch/Curve Color")
    if c.isValid():
        return set_curve_colour(objs, (c.redF(), c.greenF(), c.blueF()))
    return 0


# ---------------------------------------------------------------------- dialogs
def object_dialog(doc):
    d = QtWidgets.QDialog(Gui.getMainWindow())
    d.setObjectName("SWInsertObject")
    d.setWindowTitle("Insert Object")
    lay = QtWidgets.QFormLayout(d)
    path = QtWidgets.QLineEdit(d)
    path.setObjectName("SWInsertObjectFile")
    browse = QtWidgets.QPushButton("Browse...", d)
    row = QtWidgets.QHBoxLayout()
    row.addWidget(path, 1)
    row.addWidget(browse)
    lay.addRow("File:", row)
    link = QtWidgets.QCheckBox("Link", d)
    link.setObjectName("SWInsertObjectLink")
    icon = QtWidgets.QCheckBox("Display as icon", d)
    icon.setObjectName("SWInsertObjectIcon")
    lay.addRow(link)
    lay.addRow(icon)
    box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, d)
    lay.addRow(box)
    browse.clicked.connect(lambda: path.setText(QtWidgets.QFileDialog.getOpenFileName(d, "Create from File")[0] or path.text()))
    box.rejected.connect(d.reject)

    def ok():
        if os.path.isfile(path.text()):
            d.result_obj = insert_object(doc, path.text(), link.isChecked())
            if icon.isChecked():
                set_icon([d.result_obj], True)
            d.accept()
    box.accepted.connect(ok)
    d.path, d.link, d.icon, d.ok = path, link, icon, ok
    return d


def hyperlink_dialog(doc):
    d = QtWidgets.QDialog(Gui.getMainWindow())
    d.setObjectName("SWInsertHyperlink")
    d.setWindowTitle("Insert Hyperlink")
    lay = QtWidgets.QFormLayout(d)
    text = QtWidgets.QLineEdit(d)
    text.setObjectName("SWHyperlinkText")
    addr = QtWidgets.QLineEdit(d)
    addr.setObjectName("SWHyperlinkAddress")
    lay.addRow("Text to display:", text)
    lay.addRow("Address:", addr)
    box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, d)
    lay.addRow(box)
    box.rejected.connect(d.reject)

    def ok():
        if addr.text().strip():
            d.result_obj = insert_hyperlink(doc, addr.text().strip(), text.text().strip())
            d.accept()
    box.accepted.connect(ok)
    d.text, d.addr, d.ok = text, addr, ok
    return d


OPEN = {}


def start_object(doc):
    d = object_dialog(doc)
    OPEN["object"] = d
    d.show()
    return d


def start_hyperlink(doc):
    d = hyperlink_dialog(doc)
    OPEN["hyperlink"] = d
    d.show()
    return d


def start_picture(doc):
    path, _f = QtWidgets.QFileDialog.getOpenFileName(Gui.getMainWindow(), "Picture", "",
                                                     "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff)")
    return insert_picture(doc, path) if path else None
