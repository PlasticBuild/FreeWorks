# SPDX-License-Identifier: LGPL-2.1-or-later
""









import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

V = App.Vector
TITLE = "3D Texture"


def _image(path):
    from PySide import QtGui
    img = QtGui.QImage(path)
    if img.isNull():
        raise RuntimeError("The picture %s can't be read" % path)
    return img.convertToFormat(QtGui.QImage.Format_Grayscale8)


def _sampler(img, repeat, invert):
    w, h = img.width(), img.height()

    def grey(s, t):
        s, t = (s * repeat) % 1.0, (t * repeat) % 1.0
        x = min(w - 1, int(s * w))
        y = min(h - 1, int((1.0 - t) * h))
        g = (img.pixel(x, y) & 0xFF) / 255.0
        return 1.0 - g if invert else g
    return grey


def _border(mesh):
    """Indices of the points on the mesh's open edges."""
    count = {}
    for f in mesh.Facets:
        a, b, c = f.PointIndices
        for e in ((a, b), (b, c), (c, a)):
            k = (min(e), max(e))
            count[k] = count.get(k, 0) + 1
    out = set()
    for (a, b), n in count.items():
        if n == 1:
            out.add(a)
            out.add(b)
    return out


def textured(shape, faces, img, offset, repeat=1.0, invert=False, size=1.0):
    """A closed Mesh of shape, the given faces (indices into shape.Faces) pushed out by img."""
    import Mesh
    import MeshPart
    grey = _sampler(img, repeat, invert)
    out = Mesh.Mesh()
    for i, face in enumerate(shape.Faces):
        m = MeshPart.meshFromShape(Shape=face, MaxLength=size)
        if i in faces and offset != 0:
            pts, tris = m.Topology
            keep = _border(m)
            u0, u1, v0, v1 = face.ParameterRange
            du, dv = (u1 - u0) or 1.0, (v1 - v0) or 1.0
            moved = []
            for n, p in enumerate(pts):
                if n in keep:
                    moved.append(p)
                    continue
                u, v = face.Surface.parameter(p)
                normal = face.normalAt(u, v)
                moved.append(p + normal * (grey((u - u0) / du, (v - v0) / dv) * offset))
            m = Mesh.Mesh([[moved[a], moved[b], moved[c]] for a, b, c in tris])
        out.addMesh(m)
    out.removeDuplicatedPoints()
    return out


class TextureObject:
    def __init__(self, obj):
        obj.Proxy = self
        obj.addProperty("App::PropertyLinkSubGlobal", "Faces", TITLE, "The faces textured (of one body)")
        obj.addProperty("App::PropertyFile", "Picture", TITLE, "The texture picture (brightness = height)")
        obj.addProperty("App::PropertyLength", "Offset", TITLE, "How far white pushes the face out")
        obj.addProperty("App::PropertyFloat", "Repeat", TITLE, "How many times the picture repeats each way")
        obj.addProperty("App::PropertyBool", "Invert", TITLE, "Black pushes out instead of white")
        obj.addProperty("App::PropertyLength", "ElementSize", TITLE, "Size of the mesh's triangles")
        obj.Offset, obj.Repeat, obj.ElementSize = 1.0, 1.0, 1.0

    def execute(self, obj):
        import Part
        src, subs = obj.Faces if obj.Faces else (None, [])
        if src is None or not obj.Picture:
            return
        shape = Part.getShape(src)
        index = [int(s[4:]) - 1 for s in subs if s.startswith("Face")]
        obj.Mesh = textured(shape, set(index), _image(obj.Picture), float(obj.Offset), obj.Repeat or 1.0,
                            obj.Invert, max(float(obj.ElementSize), 0.05))

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_texture(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "TextureObject"


def _owner(obj):
    body = obj.getParentGeoFeatureGroup() if hasattr(obj, "getParentGeoFeatureGroup") else None
    return body if body is not None and body.TypeId == "PartDesign::Body" else obj


def make(doc, source, faces, picture, offset=1.0, repeat=1.0, invert=False, size=None):
    import Part
    obj = doc.addObject("Mesh::FeaturePython", "Texture3D")
    TextureObject(obj)
    if App.GuiUp:
        import MeshGui        # noqa: F401  (the mesh view provider)
        obj.ViewObject.Proxy = 0
    obj.Label = "3D Texture%d" % (1 + sum(1 for o in doc.Objects if is_texture(o) and o is not obj))
    shape = Part.getShape(source)
    obj.Faces = (source, list(faces))
    obj.Picture = picture
    obj.Offset, obj.Repeat, obj.Invert = offset, repeat, invert
    obj.ElementSize = size if size else max(shape.BoundBox.DiagonalLength / 150.0, 0.2)
    doc.recompute()
    owner = _owner(source)
    if App.GuiUp and owner.ViewObject is not None:
        owner.ViewObject.Visibility = False
    return obj


class TexturePanel:
    def __init__(self, doc, source, faces):
        self.doc, self.source, self.faces = doc, source, faces
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(TITLE)
        self.form.setProperty("swstyle_pm_title", TITLE)
        lay = QtWidgets.QFormLayout(self.form)
        self.picked = QtWidgets.QLabel("%d face(s) of %s" % (len(faces), source.Label) if source else
                                       "Pick the faces to texture before 3D Texture.")
        self.picked.setObjectName("SWTexFaces")
        lay.addRow("Faces", self.picked)
        row = QtWidgets.QHBoxLayout()
        self.picture = QtWidgets.QLineEdit()
        self.picture.setObjectName("SWTexPicture")
        browse = QtWidgets.QPushButton("Browse...")
        browse.clicked.connect(self.browse)
        row.addWidget(self.picture)
        row.addWidget(browse)
        lay.addRow("Picture", row)
        self.offset = QtWidgets.QDoubleSpinBox()
        self.offset.setObjectName("SWTexOffset")
        self.offset.setRange(-1e4, 1e4)
        self.offset.setDecimals(3)
        self.offset.setSuffix(" mm")
        self.offset.setValue(1.0)
        lay.addRow("Offset", self.offset)
        self.repeat = QtWidgets.QDoubleSpinBox()
        self.repeat.setObjectName("SWTexRepeat")
        self.repeat.setRange(0.01, 1000)
        self.repeat.setValue(1.0)
        lay.addRow("Repeat", self.repeat)
        self.invert = QtWidgets.QCheckBox("Invert")
        self.invert.setToolTip("Black pushes out")
        self.invert.setObjectName("SWTexInvert")
        lay.addRow(self.invert)
        self.size = QtWidgets.QDoubleSpinBox()
        self.size.setObjectName("SWTexSize")
        self.size.setRange(0.05, 1e4)
        self.size.setDecimals(3)
        self.size.setSuffix(" mm")
        if source is not None:
            import Part
            self.size.setValue(max(Part.getShape(source).BoundBox.DiagonalLength / 150.0, 0.2))
        lay.addRow("Element size", self.size)
        self.info = QtWidgets.QLabel("Smaller elements show finer texture but make a heavier mesh.")
        self.info.setObjectName("SWTexInfo")
        self.info.setWordWrap(True)
        lay.addRow(self.info)

    def browse(self):
        path, _f = QtWidgets.QFileDialog.getOpenFileName(self.form, "Texture picture", "",
                                                         "Pictures (*.png *.jpg *.jpeg *.bmp)")
        if path:
            self.picture.setText(path)

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def accept(self):
        if self.source is None:
            self.info.setText("Pick the faces to texture first (close this and pick them).")
            return False
        path = self.picture.text().strip()
        try:
            _image(path)
        except Exception as error:
            self.info.setText(str(error))
            return False
        doc = self.doc
        doc.openTransaction(TITLE)
        try:
            make(doc, self.source, self.faces, path, self.offset.value(), self.repeat.value(),
                 self.invert.isChecked(), self.size.value())
        finally:
            doc.commitTransaction()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True


def _picks():
    source, faces = None, []
    for sel in Gui.Selection.getSelectionEx("", 0):
        doc = sel.Object.Document
        for sub in sel.SubElementNames:
            path = sub.split(".")
            holder = sel.Object
            for part in path[:-1]:
                found = doc.getObject(part)
                if found is not None:
                    holder = found
            if holder.TypeId == "PartDesign::Body":
                holder = holder.Tip
            if path[-1].startswith("Face") and (source is None or holder == source):
                source = holder
                faces.append(path[-1])
    return source, faces


class _Command:
    def GetResources(self):
        return {"Pixmap": "Mesh_Tree", "MenuText": TITLE,
                "ToolTip": "Turns a texture picture into relief on the picked faces, as a mesh body"}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        doc = App.ActiveDocument
        source, faces = _picks()
        QtCore.QTimer.singleShot(0, lambda: Gui.Control.showDialog(TexturePanel(doc, source, faces)))


def register():
    if "SWStyle_Texture3D" not in Gui.listCommands():
        Gui.addCommand("SWStyle_Texture3D", _Command())
