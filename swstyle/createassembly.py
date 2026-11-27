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

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except ImportError:
    Gui = None

TITLE = "Create Assembly"
COMMAND = "SWStyle_CreateAssembly"


def _safe(name):
    return "".join(ch if ch.isalnum() or ch in "-_ .[]()" else "_" for ch in name).strip() or "Body"


def solid_bodies(doc):
    """[(name, solid in global coordinates)] for the part's solid bodies."""
    out = []
    try:
        from . import multibody
        for body in multibody.bodies(doc):
            for name, solid in multibody.solids(body):
                s = solid.copy()
                s.Placement = body.Placement.multiply(s.Placement)
                out.append((name.replace("​", ""), s))
    except Exception:
        out = []
    if not out:
        for obj in doc.Objects:
            shape = getattr(obj, "Shape", None)
            if shape is None or shape.isNull() or not shape.Solids:
                continue
            if obj.TypeId == "PartDesign::Body" or obj.getParentGeoFeatureGroup() is not None:
                continue
            if not getattr(obj.ViewObject, "Visibility", True) if App.GuiUp else False:
                continue
            for i, s in enumerate(shape.Solids):
                out.append((obj.Label if len(shape.Solids) == 1 else "%s[%d]" % (obj.Label, i + 1), s.copy()))
        if not out:
            for body in [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]:
                for i, s in enumerate(body.Shape.Solids):
                    out.append(("%s[%d]" % (body.Label, i + 1) if len(body.Shape.Solids) > 1 else body.Label, s.copy()))
    return out


def body_sources(doc):
    ""

    out = []
    try:
        from . import multibody
        for body in multibody.bodies(doc):
            for i, (name, _solid) in enumerate(multibody.solids(body)):
                out.append((body, name, i))
    except Exception:
        out = []
    return out


def save_part(solid, path, label, source=None):
    """One body as a part file: a Body built on the saved solid (FreeCAD's base feature); with source, a linked
    stock that follows that body of the original part on rebuild."""
    name = "FWCreateAsm%d" % len(App.listDocuments())
    doc = App.newDocument(name, hidden=True)
    if source is not None:
        base = doc.addObject("Part::FeaturePython", "Stock")
        LinkedStock(base)
        src_body, solid_name, index = source
        base.SourceDocument = src_body.Document.Name
        base.SourceBody = src_body.Name
        if src_body.Document.FileName:
            try:
                base.Source = src_body
            except Exception as _fw_err:
                _fw_log("createassembly.py:save link", _fw_err)
        watch_sources()
        base.SolidName = solid_name or ""
        base.Index = int(index or 0)
        base.BreakLink = False
        base.Label = "Stock-" + label
        try:
            if base.ViewObject is not None:
                base.ViewObject.Proxy = 0
        except Exception as _fw_err:
            _fw_log("createassembly.py:save link view", _fw_err)
    else:
        base = doc.addObject("Part::Feature", "Imported")
    base.Shape = solid
    body = doc.addObject("PartDesign::Body", "Body")
    body.BaseFeature = base
    body.Label = label
    doc.recompute()
    doc.saveAs(path)
    doc.Label = os.path.splitext(os.path.basename(path))[0]
    return doc, body


def save_bodies(chosen, folder, sources=None):
    """Save Bodies without an assembly: each chosen body to its own part file. Returns the paths."""
    os.makedirs(folder, exist_ok=True)
    paths = []
    for k, (name, solid) in enumerate(chosen):
        path = os.path.join(folder, _safe(name) + ".FCStd")
        part_doc, _body = save_part(solid, path, name, (sources or {}).get(k))
        paths.append(path)
        App.closeDocument(part_doc.Name)
    return paths


class LinkedStock:
    """FeaturePython proxy that keeps Stock linked to one solid in a source body."""

    def __init__(self, obj):
        self._add_properties(obj)
        obj.Proxy = self

    @staticmethod
    def _add_properties(obj):
        properties = (
            ("App::PropertyXLink", "Source", "The body this stock follows"),
            ("App::PropertyString", "SolidName", "The solid body's name in the source part"),
            ("App::PropertyInteger", "Index", "The solid's place in the source body"),
            ("App::PropertyBool", "BreakLink", "Break link: keep the shape as last read"),
            ("App::PropertyString", "SourceDocument", "The source part (while it is not saved, for Source)"),
            ("App::PropertyString", "SourceBody", "The source body's name in that part"),
        )
        for type_id, name, tip in properties:
            if name not in obj.PropertiesList:
                obj.addProperty(type_id, name, "Linked Stock", tip)

    def execute(self, obj):
        body = source_of(obj)
        if getattr(obj, "BreakLink", False) or body is None:
            return
        from . import multibody
        try:
            solids = list(multibody.solids(body))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: linked stock could not read %s (%s)\n" % (body.Label, error))
            return

        found = None
        for i, (name, candidate) in enumerate(solids):
            if name == obj.SolidName:
                found = candidate
                break
        if found is None:
            for i, (name, candidate) in enumerate(solids):
                if i == obj.Index:
                    found = candidate
                    break
        if found is None:
            App.Console.PrintWarning("FreeCAD: linked stock solid %r at index %d was not found\n" %
                                     (obj.SolidName, obj.Index))
            return
        shape = found.copy()
        shape.Placement = body.Placement.multiply(found.Placement)
        obj.Shape = shape
        obj.Placement = shape.Placement     # a Part feature puts its own Placement on the shape after execute

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def onDocumentRestored(self, obj):
        self._add_properties(obj)
        watch_sources()


def source_of(stock):
    """The body a linked Stock follows: its Source, else the part and body named (a part not saved
    yet cannot be an external link in FreeCAD)."""
    body = getattr(stock, "Source", None)
    if body is not None:
        return body
    try:
        doc = App.getDocument(stock.SourceDocument) if stock.SourceDocument else None
    except Exception:
        doc = None
    return doc.getObject(stock.SourceBody) if doc is not None and stock.SourceBody else None


def linked_stocks():
    for d in App.listDocuments().values():
        for o in d.Objects:
            if isinstance(getattr(o, "Proxy", None), LinkedStock):
                yield o


class _SourceWatch:
    ""



    def slotRecomputedDocument(self, doc):
        for st in linked_stocks():
            try:
                body = source_of(st)
                if body is not None and body.Document is doc and not st.BreakLink and st.Document is not doc:
                    st.touch()
            except Exception as _fw_err:
                _fw_log("createassembly.py:191", _fw_err)

    def slotFinishSaveDocument(self, doc, _filename):
        """FreeCAD links to another part only when both parts have a file: once they do, Source is set,
        and a part saved just now is saved again so its file has the link."""
        again = set()
        for st in linked_stocks():
            try:
                if st.Source is not None or st.BreakLink or not st.SourceBody:
                    continue
                src = App.getDocument(st.SourceDocument) if st.SourceDocument else None
                body = src.getObject(st.SourceBody) if src is not None else None
                if body is None or not src.FileName or not st.Document.FileName:
                    continue
                if doc is not src and doc is not st.Document:
                    continue
                st.Source = body
                if st.Document is doc:
                    again.add(doc.Name)
            except Exception as _fw_err:
                _fw_log("createassembly.py:211", _fw_err)
        for name in again:
            if name in _resaving:
                continue
            _resaving.add(name)
            try:
                App.getDocument(name).save()
            except Exception as error:
                App.Console.PrintLog("FreeCAD: linked stock save: %s\n" % error)
            finally:
                _resaving.discard(name)


_resaving = set()


_watch = []


def watch_sources():
    if not _watch:
        _watch.append(_SourceWatch())
        App.addDocumentObserver(_watch[0])


def insert_into_new_part(solid, label, source=None):
    """Insert into New Part: a new, unsaved part whose first feature is the body (its Stock)."""
    from . import newdoc
    doc = None
    try:
        doc = newdoc.make("Part")
    except Exception:
        doc = None
    if doc is None:
        doc = App.newDocument("Part")
    if source is None:
        stock = doc.addObject("Part::Feature", "Stock")
        stock.Shape = solid
    else:
        # Part::FeaturePython: a Shape of its own and Part's own view (the body's BaseFeature shows it)
        stock = doc.addObject("Part::FeaturePython", "Stock")
        LinkedStock(stock)
        source_body, solid_name, index = source
        stock.SourceDocument = source_body.Document.Name
        stock.SourceBody = source_body.Name
        try:
            stock.Source = source_body
        except Exception as _fw_err:
            _fw_log("createassembly.py:259", _fw_err)
        watch_sources()
        stock.SolidName = solid_name or ""
        stock.Index = int(index or 0)
        stock.BreakLink = False
        stock.Shape = solid
        if App.GuiUp:
            stock.ViewObject.Proxy = 0
    stock.Label = "Stock-" + label
    body = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
    body = body[0] if body else doc.addObject("PartDesign::Body", "Body")
    body.BaseFeature = stock
    doc.recompute()
    if App.GuiUp:
        try:
            stock.ViewObject.Visibility = False
            Gui.getDocument(doc.Name).ActiveView.viewIsometric()
            Gui.SendMsgToActiveView("ViewFit")
        except Exception as _fw_err:
            _fw_log("createassembly.py:278", _fw_err)
    return doc


def create_assembly(doc, chosen, folder, assembly_path, sources=None):
    """chosen = [(file name without extension, solid)]. Saves the parts and the assembly; returns
    the assembly document. sources: {index in chosen: (body, solid name, index)} the parts follow."""
    from . import asmcore
    os.makedirs(folder, exist_ok=True)
    parts = []
    for k, (name, solid) in enumerate(chosen):
        path = os.path.join(folder, _safe(name) + ".FCStd")
        parts.append(save_part(solid, path, name, (sources or {}).get(k)))
    asm_name = os.path.splitext(os.path.basename(assembly_path))[0]
    asm_doc = App.newDocument(_safe(asm_name).replace(" ", "_").replace(".", "_"))
    asm = asmcore.make_assembly(asm_doc)
    asm_doc.saveAs(assembly_path)       # a link to another file needs its own file saved first
    for _, body in parts:
        asmcore.insert(asm, body, App.Placement())
    asm_doc.recompute()
    asm_doc.Label = asm_name
    asm.Label = asm_name
    asm_doc.save()
    for part_doc, _ in parts:
        part_doc.save()
    return asm_doc


if Gui is not None:
    class CreateAssemblyPanel:
        def __init__(self, doc, save_only=False, only=None):
            ""

            self.doc = doc
            self.save_only = save_only
            self.bodies = solid_bodies(doc)
            page = QtWidgets.QWidget()
            page.setWindowTitle("Bodies to Save" if not save_only else "Resulting Bodies")
            page.setProperty("swstyle_pm_title", TITLE if not save_only else "Save Bodies")
            page.setProperty("swstyle_pm_icon", "FEATURES_CREATE_ASSEMBLY")
            lay = QtWidgets.QVBoxLayout(page)
            self.table = QtWidgets.QTableWidget(len(self.bodies), 2, page)
            self.table.setObjectName("SWStyle_CreateAssemblyBodies")
            self.table.setHorizontalHeaderLabels(["Body", "File name"])
            self.table.verticalHeader().setVisible(False)
            self.table.horizontalHeader().setStretchLastSection(True)
            part = os.path.splitext(os.path.basename(doc.FileName))[0] if doc.FileName else doc.Label
            for i, (name, _) in enumerate(self.bodies):
                item = QtWidgets.QTableWidgetItem(name)
                item.setFlags((item.flags() | QtCore.Qt.ItemIsUserCheckable) & ~QtCore.Qt.ItemIsEditable)
                item.setCheckState(QtCore.Qt.Checked if only is None or name in only else QtCore.Qt.Unchecked)
                self.table.setItem(i, 0, item)
                self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(_safe("%s-%s" % (part, name))))
            lay.addWidget(self.table)
            select = QtWidgets.QPushButton("Select all", page)
            select.clicked.connect(lambda: self._check_all(True))
            lay.addWidget(select)
            asm_box = QtWidgets.QWidget()
            asm_box.setWindowTitle("Create Assembly")
            form = QtWidgets.QFormLayout(asm_box)
            start = os.path.dirname(doc.FileName) if doc.FileName else App.getUserAppDataDir()
            self.folder = QtWidgets.QLineEdit(start, asm_box)
            self.folder.setObjectName("SWStyle_CreateAssemblyFolder")
            browse = QtWidgets.QPushButton("Browse...", asm_box)
            browse.clicked.connect(self._browse)
            row = QtWidgets.QHBoxLayout()
            row.addWidget(self.folder, 1)
            row.addWidget(browse)
            form.addRow("Folder", row)
            self.assembly = QtWidgets.QLineEdit(_safe(part + "_Assem"), asm_box)
            self.assembly.setObjectName("SWStyle_CreateAssemblyName")
            self.make_asm = QtWidgets.QCheckBox("Create Assembly", asm_box)
            self.make_asm.setObjectName("SWStyle_SaveBodiesCreateAssembly")
            self.make_asm.setChecked(not save_only)
            self.make_asm.toggled.connect(self.assembly.setEnabled)
            self.assembly.setEnabled(not save_only)
            if save_only:
                asm_box.setWindowTitle("Save Bodies")
                form.addRow(self.make_asm)
            else:
                # Create Assembly always makes the assembly: the box was left out of the layout and drew
                # cut off over the Folder row (look audit AO6, features-420)
                self.make_asm.setVisible(False)
            form.addRow("Assembly", self.assembly)
            self.message = QtWidgets.QLabel("", asm_box)
            self.message.setWordWrap(True)
            self.message.setStyleSheet("color: #c00000;")
            form.addRow(self.message)
            self.form = [page, asm_box]
            if not self.bodies:
                self.message.setText("This part has no solid bodies.")

        def _check_all(self, on):
            for i in range(self.table.rowCount()):
                self.table.item(i, 0).setCheckState(QtCore.Qt.Checked if on else QtCore.Qt.Unchecked)

        def _browse(self):
            path = QtWidgets.QFileDialog.getExistingDirectory(Gui.getMainWindow(), "Folder", self.folder.text())
            if path:
                self.folder.setText(path)

        def chosen(self):
            out = []
            for i, (_, solid) in enumerate(self.bodies):
                if self.table.item(i, 0).checkState() == QtCore.Qt.Checked:
                    out.append((self.table.item(i, 1).text().strip() or self.bodies[i][0], solid))
            return out

        def chosen_sources(self):
            ""
            found = body_sources(self.doc)
            if len(found) != len(self.bodies):
                return {}
            picked = [i for i in range(len(self.bodies)) if self.table.item(i, 0).checkState() == QtCore.Qt.Checked]
            return {k: found[i] for k, i in enumerate(picked)}

        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

        def accept(self):
            chosen = self.chosen()
            if not chosen:
                self.message.setText("Check at least one body.")
                return False
            folder = self.folder.text().strip()
            name = self.assembly.text().strip() or "Assem1"
            path = os.path.join(folder, _safe(name) + ".FCStd")
            with_asm = self.make_asm.isChecked()
            taken = [p for p in [os.path.join(folder, _safe(n) + ".FCStd") for n, _ in chosen] + ([path] if with_asm else [])
                     if os.path.exists(p)]
            if taken:
                answer = QtWidgets.QMessageBox.question(
                    Gui.getMainWindow(), TITLE, "These files exist already. Replace them?\n\n" +
                    "\n".join(os.path.basename(p) for p in taken))
                if answer != QtWidgets.QMessageBox.Yes:
                    return False
            if not with_asm:
                try:
                    self.result = save_bodies(chosen, folder, self.chosen_sources())
                except Exception as error:
                    self.message.setText("The bodies could not be saved: %s" % error)
                    return False
                Gui.Control.closeDialog()
                return True
            try:
                self.result = create_assembly(self.doc, chosen, folder, path, self.chosen_sources())
            except Exception as error:
                self.message.setText("The assembly could not be made: %s" % error)
                return False
            Gui.Control.closeDialog()
            try:
                Gui.getDocument(self.result.Name).ActiveView.viewIsometric()
                Gui.SendMsgToActiveView("ViewFit")
            except Exception as _fw_err:
                _fw_log("createassembly.py:420", _fw_err)
            return True

        def reject(self):
            Gui.Control.closeDialog()
            return True

    class Command:
        def GetResources(self):
            return {"MenuText": TITLE, "Pixmap": "Geoassembly",     # asmpkg349: FreeCAD 1.1's own name for it
                    "ToolTip": "Saves the part's bodies as parts and makes an assembly of them."}

        def IsActive(self):
            return App.ActiveDocument is not None and not Gui.Control.activeDialog()

        def Activated(self):
            Gui.Control.showDialog(CreateAssemblyPanel(App.ActiveDocument))


def register():
    if Gui is None:
        return
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, Command())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s not added (%s)\n" % (TITLE, error))
