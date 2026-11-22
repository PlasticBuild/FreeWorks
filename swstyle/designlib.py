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

from . import toolbox
from .widgets import alive

Qt = QtCore.Qt
ROLE = Qt.UserRole + 1
MIME = "application/x-freeworks-library"
PARAM = "User parameter:BaseApp/Preferences/Mod/FreeWorks/DesignLibrary"
FORMING_CATEGORIES = ("embosses", "extruded flanges", "lances", "louvers", "ribs")
SUBFOLDERS = ("annotations", "assemblies", "features", "forming tools", "motion", "parts", "routing", "smart components")
FILES = (".fcstd", ".step", ".stp", ".iges", ".igs", ".brep", ".brp", ".stl")


def library_root():

    root = App.ParamGet(PARAM).GetString("Root", "") or os.path.join(App.getUserAppDataDir(), "FreeWorks", "Design Library")
    try:
        for sub in SUBFOLDERS:
            os.makedirs(os.path.join(root, sub), exist_ok=True)
        for sub in FORMING_CATEGORIES:  # extapps108: the forming tools' category folders
            os.makedirs(os.path.join(root, "forming tools", sub), exist_ok=True)
    except Exception as _fw_err:
        _fw_log("designlib.py:55", _fw_err)
    return root


def parts_library():
    for base in (os.path.join(App.getUserAppDataDir(), "Mod", "parts_library"),
                 os.path.join(App.getUserAppDataDir(), "Mod", "FreeCAD-library")):
        if os.path.isdir(base):
            return base
    return None


def locations():
    text = App.ParamGet(PARAM).GetString("Locations", "")
    return [p for p in text.split(";") if p and os.path.isdir(p)]


def add_location(path):
    if not path or not os.path.isdir(path):
        return False
    have = locations()
    if path not in have:
        have.append(path)
        App.ParamGet(PARAM).SetString("Locations", ";".join(have))
    return True


def remove_location(path):
    App.ParamGet(PARAM).SetString("Locations", ";".join(p for p in locations() if p != path))



# the forming tools and the assemblies (the library's own "forming tools" and "assemblies" folders until one is marked)
MARKS = {"forming": ("FormingToolsFolder", "forming tools"), "assemblies": ("AssembliesFolder", "assemblies")}


def marked_folder(which):
    key, sub = MARKS[which]
    path = App.ParamGet(PARAM).GetString(key, "")
    return path if path and os.path.isdir(path) else os.path.join(library_root(), sub)


def is_marked(which, path):
    return os.path.normcase(os.path.abspath(path or "")) == os.path.normcase(os.path.abspath(marked_folder(which)))


def set_marked(which, path, on=True):
    """Marks the folder (the old one is let go); unmarking puts the library's own folder back."""
    App.ParamGet(PARAM).SetString(MARKS[which][0], path if on else "")


def folder_summary(path):
    files = folders = size = 0
    for base, dirs, names in os.walk(path):
        folders += len(dirs)
        files += len(names)
        for n in names:
            try:
                size += os.path.getsize(os.path.join(base, n))
            except Exception as _fw_err:
                _fw_log("designlib.py:size", _fw_err)
    return files, folders, size


def open_folder(path):
    """Open Folder...: the folder in the file manager."""
    if not path or not os.path.isdir(path):
        return False
    return bool(QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path)))


def files_in(folder):
    try:
        names = sorted(os.listdir(folder), key=str.lower)
    except Exception:
        return []
    return [os.path.join(folder, n) for n in names
            if os.path.isfile(os.path.join(folder, n)) and os.path.splitext(n)[1].lower() in FILES]


def new_folder(parent):
    n, name = 1, "New Folder"
    while os.path.exists(os.path.join(parent, name)):
        n += 1
        name = "New Folder (%d)" % n
    path = os.path.join(parent, name)
    os.makedirs(path)
    return path


def add_to_library(doc, folder, name=None):
    ""
    if doc is None or not folder or not os.path.isdir(folder):
        return None
    base = name or (os.path.splitext(os.path.basename(doc.FileName))[0] if doc.FileName else doc.Label)
    path = os.path.join(folder, base + ".FCStd")
    doc.saveCopy(path)
    return path


def rename_path(path, new_name):
    """Rename a library file or folder in place (its description follows a file)."""
    new_name = (new_name or "").strip()
    if not path or not new_name or any(c in new_name for c in '\\/:*?"<>|'):
        return None
    if os.path.isfile(path) and not os.path.splitext(new_name)[1]:
        new_name += os.path.splitext(path)[1]          # the extension stays, as Windows Explorer keeps it
    target = os.path.join(os.path.dirname(path), new_name)
    if os.path.exists(target):
        return None
    os.rename(path, target)
    if os.path.isfile(target):
        text = description(path)
        if text:
            set_description(target, text)
    if path in locations():
        remove_location(path)
        add_location(target)
    return target


def trash(path):
    ""
    if not path or not os.path.exists(path):
        return False
    try:
        ok = QtCore.QFile.moveToTrash(path)
        ok = ok[0] if isinstance(ok, tuple) else ok
    except Exception:
        ok = False
    return bool(ok) and not os.path.exists(path)


def open_file(path):
    """The file's right-click > Open: the part or assembly in its own window."""
    if not path or not os.path.isfile(path):
        return None
    if path.lower().endswith(".fcstd"):
        for d in App.listDocuments().values():
            if d.FileName and os.path.normcase(d.FileName) == os.path.normcase(path):
                Gui.setActiveDocument(d.Name)
                return d
        return App.openDocument(path)
    Gui.open(path)
    return App.ActiveDocument


class PropertiesDialog(QtWidgets.QDialog):
    """A library file's right-click > Properties: its name, where it is, and the description shown as
    its tooltip."""
    def __init__(self, path, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWDesignLibraryProperties")
        self.setWindowTitle("Properties")
        self.path = path
        form = QtWidgets.QFormLayout(self)
        form.addRow("Name:", QtWidgets.QLabel(os.path.basename(path)))
        form.addRow("Location:", QtWidgets.QLabel(os.path.dirname(path)))
        try:
            size = "%.1f KB" % (os.path.getsize(path) / 1024.0)
        except Exception:
            size = ""
        form.addRow("Size:", QtWidgets.QLabel(size))
        self.desc = QtWidgets.QLineEdit(description(path))
        self.desc.setObjectName("SWDesignLibraryPropertiesDescription")
        form.addRow("Description:", self.desc)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def accept(self):
        if self.desc.text() != description(self.path):
            set_description(self.path, self.desc.text())
        super().accept()


class FolderPropertiesDialog(QtWidgets.QDialog):
    """A library folder's right-click > Properties: its name, where it is, what it holds and whether it is the
    forming tools or assemblies folder."""
    def __init__(self, path, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWDesignLibraryFolderProperties")
        self.setWindowTitle("Properties")
        self.path = path
        form = QtWidgets.QFormLayout(self)
        form.addRow("Name:", QtWidgets.QLabel(os.path.basename(path.rstrip("/\\")) or path))
        form.addRow("Location:", QtWidgets.QLabel(os.path.dirname(path.rstrip("/\\"))))
        files, folders, size = folder_summary(path)
        form.addRow("Contains:", QtWidgets.QLabel("%d files, %d folders" % (files, folders)))
        form.addRow("Size:", QtWidgets.QLabel("%.1f KB" % (size / 1024.0)))
        kinds = [label for which, label in (("forming", "Forming tools folder"), ("assemblies", "Assemblies folder"))
                 if is_marked(which, path)]
        form.addRow("Folder type:", QtWidgets.QLabel(", ".join(kinds) or "Parts and other files"))
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok)
        bb.accepted.connect(self.accept)
        form.addRow(bb)


def _ask(title, text):
    return QtWidgets.QMessageBox.question(Gui.getMainWindow(), title, text) == QtWidgets.QMessageBox.Yes


def _name(title, label, now):
    text, ok = QtWidgets.QInputDialog.getText(Gui.getMainWindow(), title, label, text=now)
    return text if ok else None


LIB_FEATURE = "FwLibraryFeature"


def kind(path):
    """'feature' (a library feature), 'assembly' or 'part' for an .FCStd; 'part' for the others."""
    if not path.lower().endswith(".fcstd"):
        return "part"
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("Document.xml").decode("utf-8", "replace")
    except Exception:
        return None
    if 'name="%s"' % LIB_FEATURE in xml:
        return "feature"
    if "SWFormingTool" in xml:
        return "forming tool"
    if "Assembly::AssemblyObject" in xml:
        return "assembly"
    return "part"


def _with_sketches(features):
    out = []
    for f in features:
        prof = getattr(f, "Profile", None)
        obj = prof[0] if isinstance(prof, tuple) else prof
        if obj is not None and obj.TypeId.startswith("Sketcher::") and obj not in out:
            out.append(obj)
        if f not in out:
            out.append(f)
    return out


def add_features(features, folder, name=None):
    """Add to Library with features picked: a library feature file."""
    features = [f for f in features if f is not None]
    if not features or not folder or not os.path.isdir(folder):
        return None
    base = name or features[0].Label
    path, k = os.path.join(folder, base + ".FCStd"), 2
    while os.path.exists(path):
        path = os.path.join(folder, "%s%d.FCStd" % (base, k))
        k += 1
    active = App.ActiveDocument
    try:
        lib = App.newDocument("LibFeature", hidden=True, temp=True)     # no window: the part stays in front
    except TypeError:
        lib = App.newDocument("LibFeature")
    try:
        body = lib.addObject("PartDesign::Body", "Body")
        sources = _with_sketches(features)
        copies = lib.copyObject(sources, False)
        copies = copies if isinstance(copies, (list, tuple)) else [copies]
        try:
            # its references to the part around it and the locating dimensions on them
            from . import libfeature
            libfeature.mark_library(body, sources, copies)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: library feature references: %s\n" % error)
        for c in copies:
            body.addObject(c)
        for c in copies:
            if c.TypeId.startswith("Sketcher::"):
                c.AttachmentSupport = []
                c.MapMode = "Deactivated"
        body.addProperty("App::PropertyString", LIB_FEATURE, "FreeCAD", "Library feature")
        setattr(body, LIB_FEATURE, ",".join(f.Name for f in features))
        lib.recompute()
        lib.saveAs(path)
    finally:
        _close(lib, active)
    return path


def add_selection(folder, name=None):
    ""

    sel = Gui.Selection.getSelection() if App.GuiUp else []
    if sel:
        return add_items(sel, folder, name)
    return add_to_library(App.ActiveDocument, folder, name)


def insert_feature(path, body, face_obj, face_name, point=None, transaction=True):
    """A library feature onto a face: its sketches on that face, its features after the tip.
    transaction=False: the caller holds the undo step (pkg245: libfeature.insert, one Undo)."""
    src, opened = _source(path)
    lib_body = next((o for o in src.Objects if hasattr(o, LIB_FEATURE)), None)
    if lib_body is None:
        return []
    doc = body.Document
    objs = [o for o in lib_body.Group if o.TypeId.startswith(("Sketcher::", "PartDesign::"))]
    if transaction:
        doc.openTransaction("Insert Library Feature")
    try:
        copies = doc.copyObject(objs, False)
        copies = copies if isinstance(copies, (list, tuple)) else [copies]
        for c in copies:
            body.addObject(c)
        for c in copies:
            if c.TypeId.startswith("Sketcher::"):
                c.AttachmentSupport = [(face_obj, face_name)]
                c.MapMode = "FlatFace"
        doc.recompute()
        if point is not None:
            # where it was dropped: each sketch's origin moved to the drop point on the face
            for c in copies:
                if c.TypeId.startswith("Sketcher::"):
                    loc = c.Placement.inverse().multVec(point)
                    c.AttachmentOffset = App.Placement(App.Vector(loc.x, loc.y, 0), App.Rotation())
            doc.recompute()
    finally:
        if transaction:
            doc.commitTransaction()
    if opened:
        _close(src, doc)
    return copies


# --------------------------------------------------------------------------- putting a file in
def _close(src, keep):
    """Close a library document we opened and put keep's window back in front (closing even a
    hidden document leaves FreeCAD with no active view)."""
    App.closeDocument(src.Name)
    _front(keep)


def _front(doc):
    if doc is None or not App.GuiUp or doc.Name not in App.listDocuments():
        return
    try:
        App.setActiveDocument(doc.Name)
        Gui.setActiveDocument(doc.Name)
        if Gui.ActiveDocument is None:
            views = Gui.getDocument(doc.Name).mdiViewsOfType("Gui::View3DInventor")
            if views:
                Gui.getMainWindow().setActiveWindow(views[0])
    except Exception as _fw_err:
        _fw_log("designlib.py:338", _fw_err)


def _source(path):
    """The document of a library file (opened hidden when it is not open yet) and whether we opened it."""
    norm = os.path.normcase(os.path.abspath(path))
    for d in App.listDocuments().values():
        if d.Name != "ToolboxScratch" and d.FileName and os.path.normcase(os.path.abspath(d.FileName)) == norm:     # extapps141: Toolbox's scratch document saved it, but is empty now
            return d, False
    try:
        doc = App.openDocument(path, hidden=True)
    except TypeError:
        doc = App.openDocument(path)
    _classes_back(doc)
    return doc, True


def _classes_back(doc):
    ""

    try:
        from . import cleanfiles
        cleanfiles.restore(doc)
    except Exception as _fw_err:
        _fw_log("designlib.py:classes", _fw_err)


def insert(path, doc=None, pick=None, point=None, pm=True):
    ""


    doc = doc or App.ActiveDocument
    if toolbox.is_toolbox(path):
        from . import powertrans
        if powertrans.handles(path):     # gears, sprockets, the Shaft Wizard: their own PM
            return powertrans.drop(path, doc if doc is not None else App.ActiveDocument, point)
        return _toolbox_drop(path, doc, pick, point)
    if not path or not os.path.isfile(path):
        return None
    ext = os.path.splitext(path)[1].lower()
    if doc is not None and kind(path) == "forming tool" and not _assembly_doc(doc):
        return _form_drop(path, doc, pick, point)
    if doc is not None and kind(path) == "feature":
        if pick is None or not str(pick[1]).startswith("Face"):
            _tell("Insert Library Feature", "Drop the library feature on a flat face of the part.")
            return None
        face_obj, face_name = pick[0], pick[1]
        body = next((p for p in face_obj.InList if p.TypeId == "PartDesign::Body"), None)
        if body is None and face_obj.TypeId == "PartDesign::Body":
            body, face_obj = face_obj, face_obj.Tip or face_obj     # the body's face is its tip's
        if body is None:
            _tell("Insert Library Feature", "A library feature goes on a face of a part's body.")
            return None
        if pm and App.GuiUp:

            from . import libfeature
            return libfeature.open_insert(path, body, face_obj, face_name, point)
        return insert_feature(path, body, face_obj, face_name, point)
    if doc is None:
        from . import taskpane
        taskpane.open_file(path)
        return App.ActiveDocument
    try:
        from . import asmcore
        asm = asmcore.assembly_of(doc) if asmcore.is_assembly(doc) else None
    except Exception:
        asm = None
    name = os.path.splitext(os.path.basename(path))[0]
    if asm is not None:
        if ext == ".fcstd":
            src, _ = _source(path)
            target = asmcore.part_object(src)
        else:
            import Part
            shape = Part.read(path)
            target = doc.addObject("Part::Feature", name)
            target.Shape = shape
            target.Visibility = False
        if target is None or not _saved(doc):
            return None
        doc.openTransaction("Insert Component")
        try:
            link = asmcore.insert(asm, target, App.Placement(point, App.Rotation()) if point is not None else None)
            try:        # mate references: the dropped part mates itself to the matching one nearest the drop
                from . import asmrefgeom
                asmrefgeom.auto_mate(asm, link, point)
            except Exception as error:
                App.Console.PrintWarning("Mate Reference: %s\n" % error)
        finally:
            doc.commitTransaction()
        return link
    if pm and App.GuiUp and not Gui.Control.activeDialog():

        try:
            from . import insertpart, simplefeature as sf
            if not [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]:
                body = doc.addObject("PartDesign::Body", "Body")      # an empty part: its first body
                try:
                    Gui.getDocument(doc.Name).ActiveView.setActiveObject("pdbody", body)
                except Exception as _fw_err:
                    _fw_log("designlib.py:insert-body", _fw_err)
            made = sf.make(insertpart.INSERT_PART, doc, File=path)
            if made is not None:
                made.Label = os.path.splitext(os.path.basename(path))[0] + "->"
                return made
        except Exception as error:
            App.Console.PrintWarning("Insert Part: %s\n" % error)
    import Part
    if ext == ".fcstd":
        src, opened = _source(path)
        shapes = [o.Shape for o in src.Objects if o.TypeId == "PartDesign::Body" and not o.Shape.isNull()] or \
            [o.Shape for o in src.RootObjects if o.isDerivedFrom("Part::Feature") and not o.Shape.isNull()]
        shape = Part.makeCompound(shapes) if len(shapes) > 1 else (shapes[0].copy() if shapes else None)
        if opened:
            _close(src, doc)
    else:
        shape = Part.read(path)
    if shape is None or shape.isNull():
        return None
    doc.openTransaction("Insert Part")
    try:
        obj = doc.addObject("Part::Feature", name)
        obj.Shape = shape
        doc.recompute()
    finally:
        doc.commitTransaction()
    return obj


def _assembly_doc(doc):
    try:
        from . import asmcore
        return bool(asmcore.is_assembly(doc))
    except Exception:
        return False


def _form_drop(path, doc, pick, point):
    ""
    from . import smformingtool as ft
    title = getattr(ft, "APPLY_TITLE", "Form Tool")
    if pick is None or not str(pick[1]).startswith("Face"):
        _tell(title, "Drop the forming tool on a face of a sheet metal part.")
        return None
    face_obj, face_name = pick[0], pick[1]
    body = face_obj if face_obj.TypeId == "PartDesign::Body" else \
        next((p for p in face_obj.InList if p.TypeId == "PartDesign::Body"), None)
    if body is None or not ft._is_sheet(body):
        _tell(title, "A forming tool goes on a face of a sheet metal part.")
        return None
    if App.GuiUp and Gui.Control.activeDialog():
        _tell(title, "Close the open PropertyManager first.")
        return None
    src, _opened = _source(path)            # stays open (hidden), as the Form Tool's own list keeps its tools
    tool = next((o for o in src.Objects if ft.is_forming_tool(o)), None)
    if tool is None:
        return None
    _front(doc)
    doc.openTransaction(title)
    obj = ft.make(body, ft.SWFormFeature, "FormTool", "Form Tool")
    ft.use(obj, tool)
    if not App.GuiUp:
        doc.commitTransaction()
        return obj
    panel = ft.ApplyPanel(obj, True)
    Gui.Control.showDialog(panel)
    at = point
    if at is None:
        try:
            at = (body.Shape.getElement(face_name) if face_obj is body else face_obj.Shape.getElement(face_name)).CenterOfMass
        except Exception:
            at = None
    if at is not None:
        panel._picked(doc.Name, face_obj.Name, face_name, App.Vector(at))
    return obj


class AddPanel(QtWidgets.QDialog):
    ""


    def __init__(self, items, parent=None):
        super().__init__(parent or (Gui.getMainWindow() if App.GuiUp else None))
        self.setObjectName("SWAddToLibrary")
        self.setWindowTitle("Add to Library")
        self.items = [i for i in items if i is not None]
        lay = QtWidgets.QVBoxLayout(self)
        box = QtWidgets.QGroupBox("Items to Add")
        bl = QtWidgets.QVBoxLayout(box)
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("SWAddToLibraryItems")
        for i in self.items:
            self.list.addItem(i.Label)
        self.list.setMaximumHeight(70)
        bl.addWidget(self.list)
        lay.addWidget(box)
        box = QtWidgets.QGroupBox("Save To")
        bl = QtWidgets.QVBoxLayout(box)
        self.name = QtWidgets.QLineEdit(self.items[0].Label if self.items else "")
        self.name.setObjectName("SWAddToLibraryName")
        bl.addWidget(QtWidgets.QLabel("File name:"))
        bl.addWidget(self.name)
        bl.addWidget(QtWidgets.QLabel("Design Library folder:"))
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setObjectName("SWAddToLibraryFolders")
        self.tree.setHeaderHidden(True)
        bl.addWidget(self.tree, 1)
        lay.addWidget(box, 1)
        box = QtWidgets.QGroupBox("Options")
        bl = QtWidgets.QVBoxLayout(box)
        bl.addWidget(QtWidgets.QLabel("Description:"))
        self.desc = QtWidgets.QLineEdit()
        self.desc.setObjectName("SWAddToLibraryDescription")
        bl.addWidget(self.desc)
        lay.addWidget(box)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._fill()
        feature = any(i.TypeId.startswith("PartDesign::") and i.TypeId != "PartDesign::Body" for i in self.items)
        assembly = not self.items and App.ActiveDocument is not None and \
            any(o.TypeId == "Assembly::AssemblyObject" for o in App.ActiveDocument.Objects)
        self.select(marked_folder("assemblies") if assembly else os.path.join(library_root(), "features" if feature else "parts"))
        self.path = None

    def _fill(self):
        def node(parent, text, path):
            it = QtWidgets.QTreeWidgetItem([text])
            it.setData(0, ROLE, path)
            (parent.addChild(it) if parent is not None else self.tree.addTopLevelItem(it))
            try:
                for n in sorted(os.listdir(path), key=str.lower):
                    if os.path.isdir(os.path.join(path, n)) and not n.startswith("."):
                        node(it, n, os.path.join(path, n))
            except Exception as _fw_err:
                _fw_log("designlib.py:494", _fw_err)
        node(None, "Design Library", library_root())
        for p in locations():
            node(None, os.path.basename(p.rstrip("/\\")) or p, p)
        self.tree.expandToDepth(0)

    def select(self, path):
        for it in self.tree.findItems("*", Qt.MatchWildcard | Qt.MatchRecursive):
            if os.path.normcase(it.data(0, ROLE) or "") == os.path.normcase(path):
                self.tree.setCurrentItem(it)
                return True
        return False

    def folder(self):
        it = self.tree.currentItem()
        return it.data(0, ROLE) if it is not None else library_root()

    def accept(self):
        self.path = add_items(self.items, self.folder(), self.name.text().strip() or None)
        if self.path and self.desc.text().strip():
            set_description(self.path, self.desc.text().strip())
        super().accept()


def add_items(items, folder, name=None):
    """Add to Library of the items picked: features make a library feature, a component or body
    its part file."""
    feats = [o for o in items if o.TypeId.startswith("PartDesign::") and o.TypeId != "PartDesign::Body"]
    if feats:
        return add_features(feats, folder, name)
    for o in items:
        if o.TypeId in ("App::Link", "Assembly::AssemblyLink"):
            target = o.getLinkedObject(True) if o.TypeId == "App::Link" else o.LinkedObject
            doc = getattr(target, "Document", None)
            if doc is not None:
                return add_to_library(doc, folder, name)
    doc = items[0].Document if items else App.ActiveDocument
    return add_to_library(doc, folder, name)


DESCRIPTIONS = "descriptions.txt"


def set_description(path, text):
    ""
    try:
        with open(os.path.join(os.path.dirname(path), DESCRIPTIONS), "a", encoding="utf-8") as f:
            f.write("%s\t%s\n" % (os.path.basename(path), text.replace("\n", " ")))
    except Exception as _fw_err:
        _fw_log("designlib.py:543", _fw_err)


def description(path):
    out = ""
    try:
        with open(os.path.join(os.path.dirname(path), DESCRIPTIONS), encoding="utf-8") as f:
            for line in f:
                n, _, t = line.rstrip("\n").partition("\t")
                if n == os.path.basename(path):
                    out = t
    except Exception as _fw_err:
        _fw_log("designlib.py:555", _fw_err)
    return out


def add_panel(items=None):
    """Add to Library from a right-click: the PM, non-blocking."""
    if items is None:
        items = Gui.Selection.getSelection() if App.GuiUp else []
    dlg = AddPanel(items)
    dlg.setAttribute(Qt.WA_DeleteOnClose)
    dlg.open()
    return dlg


def _component_of(asm, pick):
    """The assembly component under a drop: from the picked object or its sub path."""
    from . import asmcore
    comps = asmcore.components(asm)
    if pick is None:
        return None, None
    obj, name = pick[0], pick[1]
    if obj in comps:
        return obj, name
    raw, sub = (pick[2], pick[3]) if len(pick) > 3 else (obj, "")
    for part in str(sub).split("."):
        c = asm.Document.getObject(part)
        if c in comps:
            return c, name
    return None, None


def _toolbox_drop(url, doc, pick, point):
    """A Toolbox item dropped on a hole of a component: sized from the hole and mated in."""
    from . import asmcore
    asm = asmcore.assembly_of(doc) if doc is not None and asmcore.is_assembly(doc) else None
    if asm is None:
        _tell("Toolbox", "Drag Toolbox parts into an assembly, onto a hole of a component.")
        return None
    comp, name = _component_of(asm, pick)
    toolbox.scratch_ready()     # extapps142: a new fastener file is built in it; making one inside the step would end the step
    doc.openTransaction("Insert Toolbox Component")
    try:
        if comp is None:

            made = toolbox.drop_free(url, asm, point)
        else:
            made = toolbox.drop(url, asm, (comp, name), point)
            if not made:
                made = toolbox.drop_free(url, asm, point)
    finally:
        doc.commitTransaction()
    if not made:
        _tell("Toolbox", "No round hole there to size the fastener from.")
        return None
    if App.GuiUp:
        toolbox.open_fastener(asm, made[:1])
    return made


def _tell(title, text):
    if App.GuiUp:
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Information, title, text,
                                    QtWidgets.QMessageBox.Ok, Gui.getMainWindow())
        box.setAttribute(Qt.WA_DeleteOnClose)
        box.open()
    App.Console.PrintMessage("%s: %s\n" % (title, text))


def drop_target(widget, pos):
    """What is under a drop point in a 3D view: ((object, "FaceN") or None, the 3D point or None)."""
    try:
        view = Gui.ActiveDocument.ActiveView
        dpr = widget.devicePixelRatioF()
        x, y = int(pos.x() * dpr), int((widget.height() - pos.y()) * dpr)
        info = view.getObjectInfo((x, y))
        point = view.getPoint(x, y)
        if info:
            # a link's pick names its parent (the assembly) and the path below it
            parent = info.get("ParentObject")
            if parent is not None and info.get("SubName"):
                obj, sub = parent, info["SubName"]
            else:
                obj = App.ActiveDocument.getObject(info["Object"])
                sub = info.get("Component") or ""
            if obj is not None:
                # a feature's face: the body's tip shape names it on the feature picked
                target, name = obj, sub.split(".")[-1]
                found = obj.getSubObject(sub, retType=1) if sub else None
                if found is not None and hasattr(found, "TypeId"):
                    target = found
                point = App.Vector(info["x"], info["y"], info["z"])
                return (target, name, obj, sub), point
        return None, point
    except Exception:
        return None, None


def _saved(doc):
    """FreeCAD links a part from another file only once the assembly is saved (as Insert Components asks)."""
    if doc.FileName:
        return True
    box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Information, "Save",
                                "Save the assembly \"%s\" first: the assembly keeps its components "
                                "as links to their saved files." % doc.Label,
                                QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Cancel, Gui.getMainWindow())
    if box.exec() != QtWidgets.QMessageBox.Save:
        return False
    return bool(Gui.getDocument(doc.Name).saveAs()) and bool(doc.FileName)


class _Dropper(QtCore.QObject):
    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        t = event.type()
        if t in (QtCore.QEvent.DragEnter, QtCore.QEvent.DragMove) and event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()
            return True
        if t == QtCore.QEvent.Drop and event.mimeData().hasFormat(MIME):
            path = bytes(event.mimeData().data(MIME)).decode()
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            pick, point = drop_target(obj, pos)
            QtCore.QTimer.singleShot(0, lambda p=path, k=pick, q=point: insert(p, pick=k, point=q))
            event.acceptProposedAction()
            return True
        return False


_dropper = None


def watch_views():
    global _dropper
    if os.environ.get("FW_NO_LIBDROP"):
        return          # extapps147: a probe switch: no Python event filter on the 3D view (Reviewer's sketch access violation hunt)
    if _dropper is None:
        _dropper = _Dropper(Gui.getMainWindow())
    for w in Gui.getMainWindow().findChildren(QtWidgets.QWidget):
        if w.inherits("QOpenGLWidget") and w.width() > 200 and not w.property("swLibraryDrops"):
            w.setAcceptDrops(True)
            w.installEventFilter(_dropper)
            w.setProperty("swLibraryDrops", True)


# --------------------------------------------------------------------------- the page
class Files(QtWidgets.QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SWDesignLibraryFiles")
        self.setViewMode(QtWidgets.QListView.IconMode)
        self.setIconSize(QtCore.QSize(40, 40))
        self.setGridSize(QtCore.QSize(80, 72))
        self.setResizeMode(QtWidgets.QListView.Adjust)
        self.setMovement(QtWidgets.QListView.Static)
        self.setWordWrap(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragOnly)

    def mimeData(self, items):
        data = QtCore.QMimeData()
        if items:
            data.setData(MIME, QtCore.QByteArray(items[0].data(ROLE).encode()))
        return data

    def mimeTypes(self):
        return [MIME]

    def startDrag(self, actions):
        watch_views()
        from . import taskpane
        done = taskpane.shut_on_drag_out(self)
        try:
            super().startDrag(actions)
        finally:
            done()


def page(pane):
    w = QtWidgets.QWidget()
    w.setObjectName("SWTaskPaneDesignLibrary")
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    row = QtWidgets.QHBoxLayout()
    row.setContentsMargins(2, 2, 2, 2)
    buttons = {}
    for key, tip in (("back", "Back"), ("forward", "Forward"), ("add", "Add to Library"), ("location", "Add File Location"),
                     ("folder", "Create New Folder"), ("refresh", "Refresh"), ("up", "Up one level"), ("toolbox", "Toolbox")):
        b = QtWidgets.QToolButton()
        b.setObjectName("SWDesignLibrary_" + key)
        b.setText(tip)
        b.setToolTip(tip)
        b.setAutoRaise(True)

        sp = {"add": QtWidgets.QStyle.SP_FileDialogNewFolder, "location": QtWidgets.QStyle.SP_DirLinkIcon,
              "folder": QtWidgets.QStyle.SP_FileDialogNewFolder, "refresh": QtWidgets.QStyle.SP_BrowserReload,
              "back": QtWidgets.QStyle.SP_ArrowBack, "forward": QtWidgets.QStyle.SP_ArrowForward, "up": QtWidgets.QStyle.SP_ArrowUp,
              "toolbox": QtWidgets.QStyle.SP_DriveHDIcon}[key]
        own = {"add": "list-add", "location": "folder", "folder": "folder-new", "refresh": "view-refresh", "back": "go-previous",
               "forward": "go-next", "up": "go-up", "toolbox": "applications-engineering"}[key]
        icon = QtGui.QIcon.fromTheme(own)
        if icon.isNull():
            icon = b.style().standardIcon(sp)
        if not icon.isNull():
            b.setIcon(icon)
            b.setIconSize(QtCore.QSize(16, 16))
            b.setToolButtonStyle(Qt.ToolButtonIconOnly)
        row.addWidget(b)
        buttons[key] = b
    row.addStretch(1)
    lay.addLayout(row)
    find = QtWidgets.QLineEdit()                    # extapps103: "Search in Design Library", "Search in Toolbox" inside the Toolbox
    find.setObjectName("SWDesignLibrarySearch")
    find.setClearButtonEnabled(True)
    find.setPlaceholderText("Search in Design Library")
    lay.addWidget(find)
    split = QtWidgets.QSplitter(Qt.Vertical, w)
    tree = QtWidgets.QTreeWidget()
    tree.setObjectName("SWDesignLibraryFolders")
    tree.setHeaderHidden(True)
    files = Files()
    split.addWidget(tree)
    split.addWidget(files)
    split.setSizes([200, 280])
    lay.addWidget(split, 1)
    provider = QtWidgets.QFileIconProvider()
    w.tree, w.files, w.buttons, w.find = tree, files, buttons, find
    nav = {"hist": [], "at": -1, "go": False}        # extapps103: Back and Forward over the folders looked at

    def node(parent, text, path):
        it = QtWidgets.QTreeWidgetItem([text])
        it.setData(0, ROLE, path)
        it.setToolTip(0, path)
        it.setIcon(0, provider.icon(QtWidgets.QFileIconProvider.Folder))
        (parent.addChild(it) if parent is not None else tree.addTopLevelItem(it))
        try:
            for n in sorted(os.listdir(path), key=str.lower):
                full = os.path.join(path, n)
                if os.path.isdir(full) and not n.startswith("."):
                    node(it, n, full)
        except Exception as _fw_err:
            _fw_log("designlib.py:779", _fw_err)
        return it

    def refresh():
        current = selected()
        tree.clear()
        node(None, "Design Library", library_root())
        lib = parts_library()
        if lib:
            node(None, "Parts Library", lib)
        tb = QtWidgets.QTreeWidgetItem(["Toolbox"])
        tb.setData(0, ROLE, toolbox.URL)
        tb.setIcon(0, provider.icon(QtWidgets.QFileIconProvider.Folder))
        tree.addTopLevelItem(tb)
        made = {toolbox.URL: tb}
        for p, l in toolbox.folders():
            it = QtWidgets.QTreeWidgetItem([l])
            it.setData(0, ROLE, p)
            it.setIcon(0, provider.icon(QtWidgets.QFileIconProvider.Folder))
            parent = made.get(p.rsplit("/", 1)[0] if p.count("/") > 2 else toolbox.URL, tb)
            parent.addChild(it)
            made[p] = it
        for p in locations():
            node(None, os.path.basename(p.rstrip("/\\")) or p, p)
        tree.topLevelItem(0).setExpanded(True)
        select(current or library_root())
        watch_views()

    def selected():
        it = tree.currentItem()
        return it.data(0, ROLE) if it is not None else None

    def select(path):
        for it in tree.findItems("*", Qt.MatchWildcard | Qt.MatchRecursive):
            if it.data(0, ROLE) and os.path.normcase(it.data(0, ROLE)) == os.path.normcase(path):
                tree.setCurrentItem(it)
                p = it.parent()
                while p is not None:
                    p.setExpanded(True)
                    p = p.parent()
                return it
        return None

    def _toolbox_below(folder):
        """Every Toolbox item in a folder and the folders under it: [(url, name)]."""
        out = list(toolbox.items(folder))
        for sub, _l in toolbox.children(folder):
            out += _toolbox_below(sub)
        return out

    def _look():
        """Keeps Back / Forward / Up one level and the search box's words in step with the folder shown."""
        folder = selected()
        find.setPlaceholderText("Search in Toolbox" if folder and toolbox.is_toolbox(folder) else "Search in Design Library")
        if not nav["go"] and folder and (nav["at"] < 0 or nav["hist"][nav["at"]] != folder):
            del nav["hist"][nav["at"] + 1:]
            nav["hist"].append(folder)
            nav["at"] = len(nav["hist"]) - 1
        it = tree.currentItem()
        buttons["back"].setVisible(nav["at"] > 0)
        buttons["forward"].setVisible(nav["at"] < len(nav["hist"]) - 1)
        buttons["up"].setVisible(it is not None and it.parent() is not None)

    def show_files(*args):
        files.clear()
        folder = selected()
        _look()
        if not folder:
            return
        words = find.text().strip().lower()
        if toolbox.is_toolbox(folder):
            if not words:
                for sub, label in toolbox.children(folder):
                    fi = QtWidgets.QListWidgetItem(provider.icon(QtWidgets.QFileIconProvider.Folder), label)
                    fi.setData(ROLE, sub)
                    fi.setData(ROLE + 1, True)         # a folder: opens on double click, is not dragged
                    fi.setFlags(fi.flags() & ~Qt.ItemIsDragEnabled)
                    fi.setToolTip(label)
                    files.addItem(fi)
            for url, name in (_toolbox_below(folder) if words else toolbox.items(folder)):
                if words and words not in name.lower():
                    continue
                it = QtWidgets.QListWidgetItem(provider.icon(QtWidgets.QFileIconProvider.File), name)
                it.setData(ROLE, url)
                it.setToolTip(name)
                files.addItem(it)
            return
        try:
            from . import smformlib
            here = os.path.normcase(os.path.abspath(folder))
            root = os.path.normcase(os.path.abspath(smformlib.folder()))
            if here == root or here.startswith(root + os.sep):     # extapps108: the category folders below it too
                smformlib.ensure_files()
        except Exception as _fw_err:
            _fw_log("designlib.py:forming", _fw_err)
        found = files_in(folder)
        if words:       # the search looks in the folders below too
            found = []
            for dirpath, dirs, names in os.walk(folder):
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                found += files_in(dirpath)
            found = [f for f in found if words in os.path.splitext(os.path.basename(f))[0].lower()]
        # extapps138: the list shows at once with the file icon; the pictures the files saved fill in a batch at a time
        # (300 files took 0.7 s with the picture read first, a big folder froze the pane)
        files._fw_gen = getattr(files, "_fw_gen", 0) + 1
        gen = files._fw_gen
        pending = []
        for f in found:
            icon = provider.icon(QtCore.QFileInfo(f))
            it = QtWidgets.QListWidgetItem(icon, os.path.splitext(os.path.basename(f))[0])
            it.setData(ROLE, f)
            it.setToolTip(description(f) or f)
            files.addItem(it)
            if f.lower().endswith(".fcstd"):
                pending.append(it)

        def fill(start=0):
            if getattr(files, "_fw_gen", 0) != gen:
                return          # another folder was picked: this list is gone
            from . import asminsert
            for it in pending[start:start + 24]:
                try:
                    class _Doc:
                        FileName = it.data(ROLE)
                    pm = asminsert.thumbnail(_Doc, 40)
                    if pm is not None:
                        it.setIcon(QtGui.QIcon(pm))
                except RuntimeError:
                    return      # the row was deleted meanwhile
                except Exception as _fw_err:
                    _fw_log("designlib.py:846", _fw_err)
            if start + 24 < len(pending):
                QtCore.QTimer.singleShot(0, lambda: fill(start + 24))
        if pending:
            QtCore.QTimer.singleShot(0, fill)
    tree.currentItemChanged.connect(lambda cur, prev: show_files())
    find.textChanged.connect(lambda *_a: show_files())

    def go_back(step=-1):
        at = nav["at"] + step
        if 0 <= at < len(nav["hist"]):
            nav["at"], nav["go"] = at, True
            try:
                select(nav["hist"][at])
            finally:
                nav["go"] = False
            show_files()

    def go_up():
        it = tree.currentItem()
        if it is not None and it.parent() is not None:
            tree.setCurrentItem(it.parent())

    def go_toolbox():
        for it in tree.findItems("Toolbox", Qt.MatchExactly):
            tree.setCurrentItem(it)
            it.setExpanded(True)
            return
    def open_item(it):
        if it.data(ROLE + 1):       # a Toolbox folder in the lower pane: go into it
            select(it.data(ROLE))
            return
        insert(it.data(ROLE))
    files.itemDoubleClicked.connect(open_item)

    def set_view(mode):
        ""
        big, listed = ("Large" in mode), mode.startswith("List")
        files.setViewMode(QtWidgets.QListView.ListMode if listed else QtWidgets.QListView.IconMode)
        files.setIconSize(QtCore.QSize(40, 40) if big else QtCore.QSize(20, 20))
        files.setGridSize(QtCore.QSize() if listed else (QtCore.QSize(80, 72) if big else QtCore.QSize(64, 44)))
        files._fw_view = mode
        try:
            App.ParamGet(PARAM).SetString("View", mode)
        except Exception as _fw_err:
            _fw_log("designlib.py:view", _fw_err)

    def add_view_rows(menu):
        menu.addSeparator()
        now = getattr(files, "_fw_view", "Large Icons")
        for mode in ("Large Icons", "Small Icons", "List, Large Icons", "List, Small Icons"):
            act = menu.addAction(mode)
            act.setCheckable(True)
            act.setChecked(mode == now)
            act.triggered.connect(lambda checked=False, m=mode: set_view(m))

    def create_part(url):
        dlg = toolbox.CreatePartDialog(url, w)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            size, length = dlg.pick()
            try:
                toolbox.create_part(url, size, length)
            except Exception as error:
                _tell("Create Part", str(error))

    def file_menu(pos):
        ""

        it = files.itemAt(pos)
        url = it.data(ROLE) if it is not None else None
        if url and not toolbox.is_toolbox(url) and os.path.isfile(url):
            menu = QtWidgets.QMenu(files)
            menu.setObjectName("FW_DesignLibraryFileMenu")
            menu.addAction("Open").triggered.connect(lambda *_: open_file(url))
            menu.addAction("Rename").triggered.connect(lambda *_: do_rename(url, True))
            menu.addAction("Delete").triggered.connect(lambda *_: do_delete(url, True))
            menu.addSeparator()
            menu.addAction("Properties...").triggered.connect(lambda *_: PropertiesDialog(url).exec() and show_files())
            add_view_rows(menu)
            files._fw_menu = menu
            return menu
        if not toolbox.is_toolbox(url or "") or not toolbox.type_of(url):
            if it is None and files.count() > 0:        # blank space in the list: the view rows
                menu = QtWidgets.QMenu(files)
                menu.setObjectName("FW_DesignLibraryViewMenu")
                now = getattr(files, "_fw_view", "Large Icons")
                for mode in ("Large Icons", "Small Icons", "List, Large Icons", "List, Small Icons"):
                    act = menu.addAction(mode)
                    act.setCheckable(True)
                    act.setChecked(mode == now)
                    act.triggered.connect(lambda checked=False, m=mode: set_view(m))
                files._fw_menu = menu
                return menu
            return None
        menu = QtWidgets.QMenu(files)
        menu.setObjectName("FW_ToolboxItemMenu")
        menu.addAction("Configure...").triggered.connect(lambda *_: toolbox_settings())
        menu.addAction("Create Part...").triggered.connect(lambda *_: create_part(url))
        fav = url in toolbox.favorites()
        a = menu.addAction("Remove from Favorites" if fav else "Add to Favorites")
        a.triggered.connect(lambda *_: (toolbox.set_favorite(url, not fav), show_files()))
        add_view_rows(menu)
        files._fw_menu = menu
        return menu

    def toolbox_settings():
        from . import toolboxconfig
        toolboxconfig.show(w)

    files.setContextMenuPolicy(Qt.CustomContextMenu)
    files.customContextMenuRequested.connect(
        lambda pos: (lambda m: m and m.popup(files.viewport().mapToGlobal(pos)))(file_menu(pos)))
    files._fw_build_menu = file_menu

    def do_add():
        # panesweep-1121: with no library folder picked (or a file picked) the button did nothing at all; as in

        folder = selected()
        if folder and os.path.isfile(folder):
            folder = os.path.dirname(folder)
        if not (folder and os.path.isdir(folder)):
            folder = library_root()
        path = add_selection(folder)
        show_files()
        if path:
            select(path)
        else:
            _tell("Add to Library", "Nothing was added: open a part or assembly, or pick its features, first.")
        return path

    def do_location(path=None):
        if path is None:
            path = QtWidgets.QFileDialog.getExistingDirectory(w, "Add File Location")
        if path and add_location(path):
            refresh()
            select(path)
            return True
        return False

    def do_folder():
        parent = selected() or library_root()
        path = new_folder(parent)
        refresh()
        select(path)
        return path
    def do_rename(path, ask=True, new_name=None):
        if new_name is None:
            now = os.path.splitext(os.path.basename(path))[0] if os.path.isfile(path) else os.path.basename(path)
            new_name = _name("Rename", "New name:", now) if ask else None
        if not new_name:
            return None
        target = rename_path(path, new_name)
        if target is None:
            _tell("Rename", "Cannot rename to \"%s\": the name is taken or not allowed." % new_name)
            return None
        if os.path.isdir(target):
            refresh()
            select(target)
        else:
            show_files()
        return target

    def do_delete(path, ask=True):
        what = "folder" if os.path.isdir(path) else "file"
        if ask and not _ask("Delete", "Move the %s \"%s\" to the Recycle Bin?" % (what, os.path.basename(path))):
            return False
        if not trash(path):
            _tell("Delete", "\"%s\" could not be moved to the Recycle Bin." % os.path.basename(path))
            return False
        if what == "folder":
            refresh()
        else:
            show_files()
        return True

    def do_remove_location(path):
        remove_location(path)
        refresh()
        return True

    def folder_menu(pos):
        ""



        it = tree.itemAt(pos)
        path = it.data(0, ROLE) if it is not None else None
        if not path or toolbox.is_toolbox(path) or not os.path.isdir(path):
            return None
        tree.setCurrentItem(it)
        top = it.parent() is None and path not in locations()       # the library's own top folders (Design Library, Parts Library)
        menu = QtWidgets.QMenu(tree)
        menu.setObjectName("FW_DesignLibraryFolderMenu")
        menu.addAction("Add Existing Folder...").triggered.connect(lambda *_: do_location())
        menu.addSeparator()
        menu.addAction("Open Folder...").triggered.connect(lambda *_: open_folder(path))
        menu.addSeparator()
        for which, label in (("forming", "Forming Tools Folder"), ("assemblies", "Assemblies Folder")):
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(is_marked(which, path))
            act.triggered.connect(lambda checked=False, k=which: do_mark(k, path))
        menu.addSeparator()
        menu.addAction("New Folder").triggered.connect(lambda *_: do_folder())
        if not top or path in locations():
            menu.addSeparator()
            if not top:
                menu.addAction("Delete").triggered.connect(lambda *_: do_delete(path, True))
                menu.addAction("Rename").triggered.connect(lambda *_: do_rename(path, True))
            if path in locations():
                menu.addAction("Remove File Location").triggered.connect(lambda *_: do_remove_location(path))
        menu.addSeparator()
        menu.addAction("Properties").triggered.connect(lambda *_: FolderPropertiesDialog(path).exec())
        tree._fw_menu = menu
        return menu

    def do_mark(which, path):
        set_marked(which, path, not is_marked(which, path))
        show_files()
        return True

    tree.setContextMenuPolicy(Qt.CustomContextMenu)
    tree.customContextMenuRequested.connect(
        lambda pos: (lambda m: m and m.popup(tree.viewport().mapToGlobal(pos)))(folder_menu(pos)))
    tree._fw_build_menu = folder_menu
    buttons["refresh"].clicked.connect(lambda checked=False: (refresh(), show_files()))
    buttons["back"].clicked.connect(lambda checked=False: go_back(-1))
    buttons["forward"].clicked.connect(lambda checked=False: go_back(1))
    buttons["up"].clicked.connect(lambda checked=False: go_up())
    buttons["toolbox"].clicked.connect(lambda checked=False: go_toolbox())
    buttons["back"].setVisible(False)
    buttons["forward"].setVisible(False)
    buttons["up"].setVisible(False)
    try:        # the list view the user last picked
        keep = App.ParamGet(PARAM).GetString("View", "")
        if keep:
            set_view(keep)
    except Exception as _fw_err:
        _fw_log("designlib.py:view0", _fw_err)
    buttons["add"].clicked.connect(lambda checked=False: do_add())
    buttons["location"].clicked.connect(lambda checked=False: do_location())
    buttons["folder"].clicked.connect(lambda checked=False: do_folder())
    w.refresh, w.select, w.selected = refresh, select, selected
    w.go_back, w.go_up, w.go_toolbox, w.view_mode = go_back, go_up, go_toolbox, lambda m: set_view(m)
    w.do_add, w.do_location, w.do_folder, w.show_files = do_add, do_location, do_folder, show_files
    w.do_rename, w.do_delete, w.do_remove_location, w.do_mark = do_rename, do_delete, do_remove_location, do_mark
    refresh()
    return w
