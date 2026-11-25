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

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import asmcore as ac

TRANSPARENT_PROP = "FwTransparent"
TRANSPARENCY = 0.75
SUPPRESS_PROP = "FwUserSuppressed"   # a mate suppressed from its menu (FreeCAD's Suppressed also marks errors)


# ----------------------------------------------------------------------------- what a row is
def assembly_of(obj):
    doc = getattr(obj, "Document", None)
    return ac.assembly_of(doc) if doc is not None else None


def is_component(obj):
    asm = assembly_of(obj) if obj is not None and not isinstance(obj, App.Document) else None
    return asm is not None and obj in ac.components(asm)


def is_mate(obj):
    ""

    if getattr(obj, ac.PART_OF_PROP, ""):
        return False
    return (hasattr(obj, "JointType") and hasattr(obj, "Reference1")) or getattr(obj, ac.MATE_PROP, "") in ac.VIRTUAL


def kind(target):
    if target is None or isinstance(target, App.Document) or not hasattr(target, "TypeId"):
        return None
    if target.TypeId == "Assembly::AssemblyObject":
        return "assembly"
    if target.TypeId == "Assembly::JointGroup":
        return "matesfolder"
    from . import asmfolder
    if asmfolder.is_folder(target) or asmfolder.is_component_folder(target):
        return "matefolder_sub"
    if is_mate(target):
        return "mate"
    if is_component(target):
        return "component"
    from . import asmexpanim
    if asmexpanim.is_view(target):
        return "explodedview"
    from . import asmexplode
    if asmexplode.view_of_step(target) is not None:
        return "explodestep"
    if target.TypeId == "Assembly::ViewGroup":
        return "viewgroup"
    if getattr(target, "ObjectToGround", None) is not None:
        return "fixedrow"
    return None


TREE_ONLY = ("GoTo", "Collapse", "Rename", "TreeItems", "Customize")


def _tree_only(items):
    return [i for i in items if i[0] in TREE_ONLY or (i[0] == "-" and i[1] is None) or (i[0] is None and i[1] is None)]


def mates_of(comp):
    asm = assembly_of(comp)
    out = []
    for j in ac.mates(asm) if asm is not None else []:
        refs = [getattr(j, p, None) for p in ("Reference1", "Reference2")]
        if any(r and r[0] is comp for r in refs):
            out.append(j)
    return out


def _select(comp):
    asm = assembly_of(comp)
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(comp.Document.Name, asm.Name, comp.Name + ".")


def _run(comp, command):
    _select(comp)
    Gui.runCommand(command, 0)


def _refresh():
    try:
        from . import asmui
        asmui.refresh()
    except Exception as _fw_err:
        _fw_log("asmmenu.py:117", _fw_err)


# ----------------------------------------------------------------------------- component commands
def edit_part(comp):
    _run(comp, "SWStyle_EditComponent")


def shown(comp):
    return comp.ViewObject is not None and bool(comp.ViewObject.Visibility)


def hide_show(comp):
    comp.ViewObject.Visibility = not shown(comp)


def transparent(comp):
    return bool(getattr(comp, TRANSPARENT_PROP, False))


def change_transparency(comp):
    ""

    vobj = comp.ViewObject
    if TRANSPARENT_PROP not in comp.PropertiesList:
        comp.addProperty("App::PropertyBool", TRANSPARENT_PROP, "FreeCAD", "Change Transparency")
        comp.setPropertyStatus(TRANSPARENT_PROP, "Hidden")
    on = not transparent(comp)
    setattr(comp, TRANSPARENT_PROP, on)
    if on:
        source = getattr(getattr(comp, "LinkedObject", None), "ViewObject", None)
        colour = tuple((getattr(source, "ShapeColor", None) or (0.8, 0.8, 0.8))[:3])
        material = App.Material()
        material.DiffuseColor = colour
        material.Transparency = TRANSPARENCY
        vobj.ShapeMaterial = material
        vobj.OverrideMaterial = True
    else:
        vobj.OverrideMaterial = False
    try:
        from . import asmappearance
        if asmappearance.own(comp) is not None:
            asmappearance.paint(comp)       # its own colour stays (see-through or not)
    except Exception as _fw_err:
        _fw_log("asmmenu.py:161", _fw_err)


def isolate(comp):
    ""

    from . import asmisolate
    return asmisolate.isolate(_picked_or(comp))


def _isolate_bodies(comp):
    """Only this component shows until Exit Isolate (the look's Isolate bar)."""
    from . import displayextras
    iso = displayextras.ISOLATE
    if iso.on:
        iso.exit()
    asm = assembly_of(comp)
    saved = []
    for other in ac.components(asm):
        if other is not comp and other.ViewObject is not None:
            saved.append((other.Name, other.ViewObject.Visibility))
            other.ViewObject.Visibility = False
    if not shown(comp):
        saved.append((comp.Name, False))
        comp.ViewObject.Visibility = True
    iso.saved = (comp.Document.Name, saved)
    iso._show_bar()


def part_document(comp):
    target = comp.getLinkedObject(True) if comp.TypeId == "App::Link" else \
        (comp.LinkedObject if ac.is_subassembly(comp) else comp)
    doc = getattr(target, "Document", None)
    return doc if doc is not None and doc is not comp.Document else None


def open_part(comp):
    ""
    from . import asmcomp
    if asmcomp.is_virtual_sub(comp):
        # a virtual subassembly lives in this assembly's file: a window that mirrors it, its
        # edits written back (asmvirtualwin)
        from . import asmvirtualwin
        return asmvirtualwin.open_virtual(comp) is not None
    doc = part_document(comp)
    if doc is None:
        return False
    if getattr(doc, "Partial", False):
        # an assembly opened again loads its parts only in part (FreeCAD's partial loading of linked

        # whole part: load it fully
        try:
            doc = Gui.reload(doc.Name) or App.getDocument(doc.Name)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Open Part: %s could not be loaded fully (%s)\n" % (doc.Label, error))
    gdoc = Gui.getDocument(doc.Name)
    if gdoc is None:
        return False
    Gui.setActiveDocument(doc.Name)
    if not gdoc.mdiViewsOfType("Gui::View3DInventor"):
        try:            # a part opened only for the assembly, or made without a window (Form New Subassembly)
            gdoc.createView("Gui::View3DInventor")
        except Exception:
            Gui.runCommand("Std_ViewCreate", 0)
        Gui.setActiveDocument(doc.Name)
    return True


def inner_source(comp):
    ""


    try:
        if getattr(comp, "TypeId", "") != "App::Link":
            return None
        if not any(ac.is_subassembly(o) for o in comp.InList):
            return None
        src = comp.LinkedObject
        if src is None or src.Document is comp.Document or getattr(src, "TypeId", "") not in ("App::Link", "Assembly::AssemblyLink"):
            return None
        asm = assembly_of(src)
        if asm is None or src not in ac.components(asm):
            return None
        return asm, src
    except Exception as _fw_err:
        _fw_log("asmmenu.py:inner source", _fw_err)
        return None


def _after_inner(sub_doc, top_doc):
    """The subassembly changed: rebuilt, and the top assembly with it."""
    try:
        sub_doc.recompute()
        if top_doc is not None and top_doc is not sub_doc:
            for o in top_doc.Objects:
                if ac.is_subassembly(o):
                    o.touch()
                    o.recompute()       # its copies of the parts follow (the document's recompute left it touched)
            top_doc.recompute()
    except Exception as _fw_err:
        _fw_log("asmmenu.py:after inner", _fw_err)


def fix_float(comp):
    inner = inner_source(comp)
    if inner is not None:
        asm, src = inner
        doc = src.Document
        fixed = src in ac.grounded(asm)
        doc.openTransaction("Float" if fixed else "Fix")
        try:
            (ac.float_ if fixed else ac.fix)(asm, src)
            ac.solve(asm)
        finally:
            doc.commitTransaction()
        _after_inner(doc, comp.Document)
        _refresh()
        return
    asm = assembly_of(comp)
    _run(comp, "SWStyle_FloatComponent" if comp in ac.grounded(asm) else "SWStyle_FixComponent")


def _confirm_class():
    from . import confirmdelete as cd

    class ComponentConfirmDelete(cd.ConfirmDelete):
        ""


        def __init__(self, item, many, parent=None):
            self.mates = mates_of(item) if is_component(item) else []
            self.what = "Component" if is_component(item) else "Mate"
            super().__init__(item, many, parent)
            self.name.setText("%s ( %s )" % (item.Label, self.what))
            self.children, self.absorbed = [(j, item) for j in self.mates], []
            self.absorbed_box.setChecked(False)
            self.absorbed_box.setEnabled(False)
            self.child_box.setChecked(bool(self.mates))     # a component's mates always go with it
            self.child_box.setEnabled(False)
            self.advanced.setEnabled(False)
            self.fill()

        def fill(self, *args):
            self.list.clear()
            for j, _c in getattr(self, "children", []) if hasattr(self, "mates") else []:
                self.list.addTopLevelItem(QtWidgets.QTreeWidgetItem(["%s ( Mate )" % j.Label]))

        def done_with(self, answer):
            self.answer = answer
            if answer != self.CANCEL and self.again.isChecked():
                cd.params().SetBool("FeatureAsk", False)
            self.accept() if answer != self.CANCEL else self.reject()

    return ComponentConfirmDelete


def confirm_delete(items):
    ""


    from . import confirmdelete as cd
    dialog_class = _confirm_class()
    ask = cd.params().GetBool("FeatureAsk", True)
    picked = []
    for i, item in enumerate(items):
        if ask:
            dlg = dialog_class(item, len(items) - i > 1)
            dlg.exec()
            if dlg.answer == dlg.CANCEL:
                break
            if dlg.answer == dlg.NO:
                continue
            if dlg.answer == dlg.YES_ALL:
                ask = False
        picked.append(item)
    if not picked:
        return []
    doc = picked[0].Document
    asm = assembly_of(picked[0])
    names = [(item.Name, is_component(item)) for item in picked]
    done = []
    doc.openTransaction("Delete")
    try:
        for name, comp in names:
            item = doc.getObject(name)
            if item is None:
                continue        # a mate already gone with its component
            if comp:
                _remove_component(asm, item)
            else:
                doc.removeObject(name)
            done.append(name)
        ac.solve(asm)
    finally:
        doc.commitTransaction()
    _refresh()
    return done


def assembly_picks():
    """The picked components and mates (whole objects) of the assembly being edited, or None
    when the pick holds anything else (then the part's or FreeCAD's own Delete runs)."""
    out = []
    for sel in Gui.Selection.getSelectionEx("", 0):
        subs = [s for s in sel.SubElementNames if s] or [""]
        for s in subs:
            if s and s.split(".")[-1]:
                return None             # a face, edge or vertex
            obj = sel.Object
            for part in [x for x in s.split(".") if x]:
                found = obj.Document.getObject(part)
                if found is None:
                    return None
                obj = found
            if not (is_component(obj) or is_mate(obj)):
                return None
            if obj not in out:
                out.append(obj)
    return out or None


def install_delete():
    ""

    from . import confirmdelete as cd
    if getattr(cd, "_fw_asm_delete", False):
        return
    original = cd.handle

    def handle(*a, **k):
        try:
            edit = Gui.ActiveDocument.getInEdit() if Gui.ActiveDocument is not None else None
            edit = getattr(edit, "Object", None) if edit is not None else None
            # an active assembly is "in edit"; a part edited in context or a PM open is not ours
            if Gui.ActiveDocument is not None and (edit is None or edit.TypeId == "Assembly::AssemblyObject") \
                    and not Gui.Control.activeDialog():
                picks = assembly_picks()
                if picks:
                    confirm_delete(picks)
                    return True
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: assembly Delete: %s\n" % error)
        return original(*a, **k)

    cd.handle = handle
    cd._fw_asm_delete = True


def delete(comp, ask=True):
    ""
    inner = inner_source(comp)
    if inner is not None:

        top = comp.Document
        src = inner[1]
        done = confirm_delete([src]) if ask else delete(src, ask=False)
        if done:
            _after_inner(inner[0].Document, top)
        return bool(done)
    if ask:
        return bool(confirm_delete([comp]))
    asm = assembly_of(comp)
    doc = comp.Document
    doc.openTransaction("Delete")
    try:
        _remove_component(asm, comp)
        ac.solve(asm)
    finally:
        doc.commitTransaction()
    _refresh()
    return True


def _remove_component(asm, comp):
    doc = comp.Document
    gone = mates_of(comp)
    ground = ac.grounded(asm).get(comp)
    for j in gone + ([ground] if ground is not None else []):
        if doc.getObject(j.Name) is not None:
            doc.removeObject(j.Name)
    from . import asmcomp
    virtual = comp.LinkedObject if asmcomp.is_virtual_sub(comp) else None
    kids = list(getattr(comp, "Group", []) or []) if ac.is_subassembly(comp) else []
    doc.removeObject(comp.Name)
    for k in kids:
        try:
            if doc.getObject(k.Name) is not None:
                doc.removeObject(k.Name)
        except Exception as _fw_err:
            _fw_log("asmmenu.py:392", _fw_err)
    if virtual is not None:
        asmcomp.remove_virtual_source(virtual)      # a virtual component is kept nowhere else


class ViewMatesDialog(QtWidgets.QDialog):
    ""

    def __init__(self, comp, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("FW_ViewMates")
        self.setWindowTitle("View Mates: %s" % comp.Label)
        lay = QtWidgets.QVBoxLayout(self)
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("FW_ViewMatesList")
        from . import asmpm
        self.mates = mates_of(comp)
        for j in self.mates:
            self.list.addItem(QtWidgets.QListWidgetItem(asmpm.sw_icon(ac.mate_type(j)), ac.mate_text(j)))
        self.list.itemDoubleClicked.connect(self._edit)
        lay.addWidget(self.list)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, QtCore.Qt.AlignRight)
        self.resize(320, 220)

    def _edit(self, item):
        joint = self.mates[self.list.row(item)]
        self.accept()
        QtCore.QTimer.singleShot(0, lambda: edit_mate(joint))


REF_PROP = "FwComponentReference"
DESC_PROP = "FwComponentDescription"
REFCONFIG_PROP = "FwReferencedConfiguration"
REFDISPLAY_PROP = "FwReferencedDisplayState"


def _text_prop(comp, prop, tip):
    if not hasattr(comp, prop):
        comp.addProperty("App::PropertyString", prop, "FreeCAD", tip)
        comp.setEditorMode(prop, 2)


def component_reference(comp):
    return getattr(comp, REF_PROP, "")


def component_description(comp):
    """The component's description: its own, else the part's Description property."""
    own = getattr(comp, DESC_PROP, "")
    if own:
        return own
    doc = part_document(comp)
    try:
        from . import fileprops
        return (fileprops.value(doc, "Description") or "") if doc is not None else ""
    except Exception:
        return ""


def suppression_state(comp):
    from . import asmcomp
    if asmcomp.is_suppressed(comp):
        return "Suppressed"
    if asmcomp.is_lightweight(comp):
        return "Lightweight"
    return "Resolved"


def set_suppression_state(comp, state, scope="this"):
    """Suppressed / Resolved / Lightweight, as the Component Properties' Suppression state."""
    from . import asmcomp, configmanager
    now = suppression_state(comp)
    if scope not in ("this", None) and configmanager.table(comp.Document) is not None:
        # All / Specify configurations: the other configurations change even when this one does not
        from . import configs
        configs.suppress_component(comp, state == "Suppressed", scope)
        asmcomp.set_lightweight(comp, state == "Lightweight")
        return True
    if state == now:
        return False
    if state == "Suppressed" or now == "Suppressed":
        on = state == "Suppressed"
        if configmanager.table(comp.Document) is not None:
            from . import configs
            configs.suppress_component(comp, on, scope)
        else:
            asmcomp.suppress(comp, on)
    asmcomp.set_lightweight(comp, state == "Lightweight")
    return True


class ComponentPropertiesDialog(QtWidgets.QDialog):
    ""





    def __init__(self, comp, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.comp = comp
        self.setObjectName("FW_ComponentProperties")
        self.setWindowTitle("Component Properties")
        outer = QtWidgets.QVBoxLayout(self)
        gen = QtWidgets.QGroupBox("General properties")
        form = QtWidgets.QFormLayout(gen)
        base, _, inst = comp.Label.rpartition("<")
        self.name = QtWidgets.QLineEdit(base or comp.Label)
        self.name.setObjectName("FW_ComponentName")
        form.addRow("Component Name:", self.name)
        form.addRow("Instance Id:", QtWidgets.QLabel(inst.rstrip(">") if base else "1"))
        form.addRow("Full Name:", QtWidgets.QLabel(comp.Label))
        self.reference = QtWidgets.QLineEdit(component_reference(comp))
        self.reference.setObjectName("FW_ComponentReference")
        form.addRow("Component Reference:", self.reference)
        self.description = QtWidgets.QLineEdit(component_description(comp))
        self.description.setObjectName("FW_ComponentDescription")
        form.addRow("Component Description:", self.description)
        target = comp.getLinkedObject(True) if comp.TypeId == "App::Link" else comp
        path = getattr(getattr(target, "Document", None), "FileName", "") or "(not saved)"
        form.addRow("Model document path:", QtWidgets.QLabel(path))
        outer.addWidget(gen)

        disp = QtWidgets.QGroupBox("Display State specific properties")
        dl = QtWidgets.QVBoxLayout(disp)
        self.hide_box = QtWidgets.QCheckBox("Hide component")
        self.hide_box.setObjectName("FW_ComponentHide")
        # a suppressed component is out of the view because it is suppressed, not hidden: Set to

        self.hide_box.setChecked(not shown(comp) and suppression_state(comp) != "Suppressed")
        dl.addWidget(self.hide_box)
        dl.addWidget(QtWidgets.QLabel("Referenced display state:"))
        self.display = QtWidgets.QListWidget()
        self.display.setObjectName("FW_ComponentDisplayStates")
        self.display.setMaximumHeight(60)
        pdoc = part_document(comp)
        from . import displaystates
        states = displaystates.names(pdoc) if pdoc is not None else []
        self.display.addItems(states or ["<Default>_Display State 1"])
        want = getattr(comp, REFDISPLAY_PROP, "") or (displaystates.active(pdoc) if pdoc is not None else None)
        hit = self.display.findItems(want or "", QtCore.Qt.MatchExactly)
        self.display.setCurrentItem(hit[0] if hit else self.display.item(0))
        dl.addWidget(self.display)
        outer.addWidget(disp)

        cfg = QtWidgets.QGroupBox("Configuration specific properties")
        cl = QtWidgets.QVBoxLayout(cfg)
        cl.addWidget(QtWidgets.QLabel("Referenced configuration:"))
        self.configs = QtWidgets.QListWidget()
        self.configs.setObjectName("FW_ComponentConfigurations")
        self.configs.setMaximumHeight(60)
        from . import fileprops
        names = fileprops.configurations(pdoc) if pdoc is not None else ["Default"]
        self.configs.addItems(names)
        from . import asmcfginst
        want = asmcfginst.configuration(comp)
        hit = self.configs.findItems(want or "", QtCore.Qt.MatchExactly)
        self.configs.setCurrentItem(hit[0] if hit else self.configs.item(0))
        cl.addWidget(self.configs)
        sbox = QtWidgets.QGroupBox("Suppression state")
        sl = QtWidgets.QHBoxLayout(sbox)
        self.states = {}
        now = suppression_state(comp)
        for name in ("Suppressed", "Resolved", "Lightweight"):
            b = QtWidgets.QRadioButton(name)
            b.setObjectName("FW_Component" + name)
            b.setChecked(name == now)
            sl.addWidget(b)
            self.states[name] = b
        cl.addWidget(sbox)
        self.rigid = self.flexible = None
        if ac.is_subassembly(comp):
            box = QtWidgets.QGroupBox("Solve as")
            row = QtWidgets.QHBoxLayout(box)
            self.rigid = QtWidgets.QRadioButton("Rigid")
            self.rigid.setObjectName("FW_ComponentRigid")
            self.flexible = QtWidgets.QRadioButton("Flexible")
            self.flexible.setObjectName("FW_ComponentFlexible")
            (self.flexible if ac.is_flexible(comp) else self.rigid).setChecked(True)
            row.addWidget(self.rigid)
            row.addWidget(self.flexible)
            cl.addWidget(box)
        from . import asminsert
        self.exclude = QtWidgets.QCheckBox("Exclude from bill of materials")
        self.exclude.setObjectName("FW_ComponentExcludeBOM")
        self.exclude.setChecked(asminsert.is_excluded(comp))
        cl.addWidget(self.exclude)
        self.envelope = QtWidgets.QCheckBox("Envelope")
        self.envelope.setObjectName("FW_ComponentEnvelope")
        self.envelope.setChecked(asminsert.is_envelope(comp))
        cl.addWidget(self.envelope)
        outer.addWidget(cfg)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Change properties in:"))
        self.this_config = QtWidgets.QRadioButton("This configuration")
        self.this_config.setObjectName("FW_ComponentThisConfig")
        self.this_config.setChecked(True)
        self.all_configs = QtWidgets.QRadioButton("All configurations")
        self.all_configs.setObjectName("FW_ComponentAllConfigs")
        self.specify = QtWidgets.QRadioButton("Specify configuration(s)")
        self.specify.setObjectName("FW_ComponentSpecifyConfigs")
        row.addWidget(self.this_config)
        row.addWidget(self.all_configs)
        row.addWidget(self.specify)
        row.addStretch(1)
        outer.addLayout(row)
        self.config_list = QtWidgets.QListWidget()
        self.config_list.setObjectName("FW_ComponentConfigList")
        self.config_list.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        self.config_list.setMaximumHeight(90)
        try:
            from . import configmanager
            t = configmanager.table(comp.Document)
            names = list(t.names()) if t is not None else ["Default"]
            active = t.active() if t is not None else "Default"
        except Exception:
            names, active = ["Default"], "Default"
        for n in names:
            it = QtWidgets.QListWidgetItem(n)
            self.config_list.addItem(it)
            it.setSelected(n == active)
        self.config_list.setEnabled(False)
        self.specify.toggled.connect(self.config_list.setEnabled)
        outer.addWidget(self.config_list)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def apply(self):
        comp = self.comp
        base, _, inst = comp.Label.rpartition("<")
        new = self.name.text().strip()
        if new and base and new != base:
            comp.Label = "%s<%s" % (new, inst)
        _text_prop(comp, REF_PROP, "Component Reference (shown in the bill of materials)")
        setattr(comp, REF_PROP, self.reference.text().strip())
        if self.description.text().strip() != component_description(comp):
            _text_prop(comp, DESC_PROP, "Component Description")
            setattr(comp, DESC_PROP, self.description.text().strip())
        pdoc = part_document(comp)
        item = self.display.currentItem()
        if item is not None and pdoc is not None:
            from . import displaystates
            if item.text() in displaystates.names(pdoc):
                _text_prop(comp, REFDISPLAY_PROP, "Referenced display state")
                setattr(comp, REFDISPLAY_PROP, item.text())
                try:
                    displaystates.activate(pdoc, item.text())
                except Exception as error:
                    App.Console.PrintLog("FreeCAD: display state: %s\n" % error)
        scope = "all" if self.all_configs.isChecked() else "this"
        if self.specify.isChecked():
            scope = [it.text() for it in self.config_list.selectedItems()] or "this"
        from . import asmconfigure
        item = self.configs.currentItem()
        if item is not None and pdoc is not None:
            from . import asmcfginst
            if item.text() != asmcfginst.configuration(comp) or scope != "this":
                _text_prop(comp, REFCONFIG_PROP, "Referenced configuration")
                setattr(comp, REFCONFIG_PROP, item.text())

                asmconfigure.set_specific(comp, "config", item.text(), scope)
        state = next(n for n, b in self.states.items() if b.isChecked())
        set_suppression_state(comp, state, scope)
        if state != "Suppressed":
            comp.ViewObject.Visibility = not self.hide_box.isChecked()
        from . import asminsert
        if self.exclude.isChecked() != asminsert.is_excluded(comp) or scope != "this":
            asmconfigure.set_specific(comp, "exclude", self.exclude.isChecked(), scope)
        if self.envelope.isChecked() != asminsert.is_envelope(comp):
            asminsert.make_envelope(comp, self.envelope.isChecked())
        if self.flexible is not None and (self.flexible.isChecked() != ac.is_flexible(comp) or scope != "this"):
            asmconfigure.set_specific(comp, "flex", self.flexible.isChecked(), scope)
        _refresh()


OPEN = []       # dialogs open now (tests reach them here)


def _dialog(box, on_ok=None):
    OPEN.append(box)
    try:
        if box.exec() and on_ok is not None:
            on_ok(box)
    finally:
        OPEN.remove(box)


def view_mates(comp):
    _dialog(ViewMatesDialog(comp))


def component_properties(comp):
    _dialog(ComponentPropertiesDialog(comp), lambda box: box.apply())


# ----------------------------------------------------------------------------- mate commands
def edit_mate(joint):
    from . import asmui
    return asmui.edit_mate(joint)


def suppressed(joint):
    return bool(getattr(joint, SUPPRESS_PROP, False))


def suppress(joint, on=None):
    """Suppress / Unsuppress: the mate stays in the tree, greyed, and stops holding."""
    asm = assembly_of(joint)
    on = not suppressed(joint) if on is None else on
    doc = joint.Document
    doc.openTransaction("Suppress" if on else "Unsuppress")
    try:
        if SUPPRESS_PROP not in joint.PropertiesList:
            joint.addProperty("App::PropertyBool", SUPPRESS_PROP, "FreeCAD", "Suppressed from the mate's menu")
            joint.setPropertyStatus(SUPPRESS_PROP, "Hidden")
        setattr(joint, SUPPRESS_PROP, on)
        if on:
            joint.Suppressed = True
            ac.solve(asm)
        else:
            joint.Suppressed = False
            ac._mark(joint, ac.solve(asm))      # an unsuppressed mate that no longer solves shows its error
    finally:
        doc.commitTransaction()
    _refresh()


def flip_alignment(joint):
    asm = assembly_of(joint)
    doc = joint.Document
    doc.openTransaction("Flip Mate Alignment")
    try:
        ac.flip(asm, joint)
    finally:
        doc.commitTransaction()
    _refresh()


def delete_mate(joint):
    asm = assembly_of(joint)
    doc = joint.Document
    doc.openTransaction("Delete")
    try:
        doc.removeObject(joint.Name)
        ac.solve(asm)
    finally:
        doc.commitTransaction()
    _refresh()


# ----------------------------------------------------------------------------- the entries
def component_items(comp):
    ""
    asm = assembly_of(comp)
    inner = inner_source(comp)
    fixed = inner[1] in ac.grounded(inner[0]) if inner is not None else comp in ac.grounded(asm)
    sub = ac.is_subassembly(comp)
    items = [
        ("EditPart", "Edit Subassembly" if sub else "Edit Part", lambda: edit_part(comp), True),
        ("HideComponents", "Hide Components" if shown(comp) else "Show Components", lambda: hide_show(comp), True),
        ("ChangeTransparency", "Change Transparency", lambda: change_transparency(comp), True),
        ("IsolateComponent", "Isolate", lambda: isolate(comp), True),
        ("OpenPart", "Open Subassembly" if sub else "Open Part", lambda: open_part(comp), part_document(comp) is not None),
        ("FixFloat", "Float" if fixed else "Fix", lambda: fix_float(comp), True),
        ("ViewMates", "View Mates", lambda: view_mates(comp), bool(mates_of(comp))),
        ("ComponentProperties", "Component Properties...", lambda: component_properties(comp), True),
    ] + _subassembly_items(comp) + _speedpak_items(comp) + _toolbox_items(comp) + _envelope_items(comp)
    # no greyed entries: Open Part on a virtual part (it has no file) and View Mates on a

    return [i for i in items if i[3] or i[0] not in ("OpenPart", "ViewMates")]


def _subassembly_items(comp):
    ""
    if not ac.is_subassembly(comp):
        return []
    asm = assembly_of(comp)
    flex = ac.is_flexible(comp)
    label = "Make Subassembly Rigid" if flex else "Make Subassembly Flexible"
    from . import asmmenubar
    return [("FlexibleRigid", label, lambda: _in_transaction(comp.Document, label,
                                                             lambda: ac.set_flexible(asm, comp, not flex)), True),
            ("DissolveSubassembly", "Dissolve Subassembly",
             lambda: _in_transaction(comp.Document, "Dissolve Subassembly", lambda: asmmenubar.dissolve(asm, comp)), True)]



def _picked_or(comp):
    """The components picked with comp (comp first)."""
    out = [comp]
    try:
        # full paths: a component picked in the graphics area or the tree is selected as
        # "Assembly" + "Component.Face3", whose top object is the assembly, not the component
        for sel in Gui.Selection.getSelectionEx("", 0):
            root = sel.Object
            for sub in (list(sel.SubElementNames) or [""]):
                found = root if is_component(root) else None
                if found is None and sub:
                    try:
                        chain = root.getSubObjectList(sub)
                    except Exception:
                        chain = []
                    found = next((o for o in chain[1:] if is_component(o)), None)
                if found is not None and found not in out:
                    out.append(found)
    except Exception as _fw_err:
        _fw_log("asmmenu.py:797", _fw_err)
    return out


def sw_component_rows(comp):
    ""

    from . import asmcomp
    asm = assembly_of(comp)
    sub = ac.is_subassembly(comp)
    word = "Subassembly" if sub else "Part"
    sup = asmcomp.is_suppressed(comp)
    row1 = [("OpenPart", "Open %s" % word, lambda: open_part(comp), part_document(comp) is not None),
            ("OpenPartInPosition", "Open %s in Position" % word, lambda: asmcomp.open_part_in_position(comp),
             part_document(comp) is not None),
            ("OpenDrawing", "Open Drawing", lambda: asmcomp.open_drawing(comp), True),
            ("EditPart", "Edit %s" % word, lambda: edit_part(comp), not sup),
            ("HideComponents", "Hide Components" if shown(comp) else "Show Components", lambda: hide_show(comp), not sup),
            ("ChangeTransparency", "Change Transparency", lambda: change_transparency(comp), not sup),
            ("SuppressComponent", "Set to Resolved" if sup else "Suppress",
             lambda: _in_transaction(comp.Document, "Suppress", lambda: _suppress_picked(comp, not sup)), True),
            ("MateComponent", "Mate", lambda: _run(comp, "SWStyle_Mate"), not sup),
            ("ViewMates", "View Mates", lambda: view_mates(comp), bool(mates_of(comp))),
            ("ComponentProperties", "Component Properties...", lambda: component_properties(comp), True)]
    row2 = [("ZoomSelection", "Zoom to Selection", lambda: _zoom_to(comp), not sup),
            ("ComponentPreview", "Component Preview Window", lambda: _run(comp, "SWStyle_ComponentPreview"), not sup),
            ("Appearances", "Appearances", lambda: _appearance(comp), not sup)]
    if sub:
        row2 += [i for i in _subassembly_items(comp) if i[0] == "FlexibleRigid"]
    return row1, row2


def _appearance(comp):
    ""
    from . import asmappearance
    asm = ac.assembly_of(comp.Document)
    return asmappearance.edit_appearance(asm, comp) if asm is not None else None


def _suppress_picked(comp, on):
    ""

    from . import asmcomp
    comps = [c for c in _picked_or(comp) if asmcomp.is_suppressed(c) != on]
    if comp not in comps and asmcomp.is_suppressed(comp) != on:
        comps.insert(0, comp)
    from . import configmanager
    if configmanager.table(comp.Document) is not None:
        for c in comps:
            _suppress(c, on)
        return
    for c in comps:
        asmcomp.suppress(c, on, solve=False)
    if not on and comps:
        ac.solve(assembly_of(comp))


def _suppress(comp, on):
    ""

    from . import asmcomp, configmanager
    if configmanager.table(comp.Document) is not None:
        from . import configs
        return configs.suppress_component(comp, on, "this")
    return asmcomp.suppress(comp, on)


def add_configuration(comp, name=None):
    """Add Configuration... on a component: a new configuration of the component's part."""
    from . import configs
    if name is None:
        name, ok = QtWidgets.QInputDialog.getText(Gui.getMainWindow(), "Add Configuration",
                                                  "Configuration name for %s:" % ac.part_name(comp))
        if not ok:
            return None
    return configs.add_configuration_to_part(comp, name)


def _folder(comps):
    from . import asmfolder
    return asmfolder.add_components_to_new_folder(comps)


def _new_folder(asm):
    from . import asmfolder
    return asmfolder.create_new_folder(asm)


def _zoom_to(comp):
    _select(comp)
    try:
        Gui.SendMsgToActiveView("ViewSelection")
    except Exception:
        Gui.runCommand("Std_ViewBoxZoom", 0)


def _add_to_library(comp):
    from . import designlib
    return designlib.add_panel([comp])


TRIAD = {}


def move_with_triad(comp):
    ""


    asm = assembly_of(comp)
    gdoc = Gui.getDocument(comp.Document.Name)
    if asm is None or gdoc is None:
        return False
    if gdoc.getInEdit() is not None:
        gdoc.resetEdit()
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(comp.Document.Name, asm.Name, comp.Name + ".")
    comp.Document.openTransaction("Move with Triad")
    try:
        TRIAD.update(comp=comp, asm=asm, start=App.Placement(comp.Placement))
        try:
            gdoc.setEdit(asm, 1, comp.Name + ".")      # 1: Transform (arrows and rings)
        except Exception:
            gdoc.setEdit(comp, 1)
    except BaseException:
        try:
            comp.Document.abortTransaction()
        except Exception:
            pass
        raise
    TRIAD["vp"] = gdoc.getInEdit()
    _triad_menu_on(gdoc)
    _triad_sw_look(gdoc)
    timer = QtCore.QTimer()
    timer.setInterval(200)
    timer.timeout.connect(lambda: _triad_tick(gdoc, timer))
    TRIAD["timer"] = timer
    timer.start()
    return True


def _triad_tick(gdoc, timer):
    try:
        cur = gdoc.getInEdit()
        TRIAD["comp"].Name
    except Exception:
        # the document closed while the triad was up: nothing to solve or commit
        timer.stop()
        flt = TRIAD.get("filter")
        if flt is not None:
            try:
                flt[0].removeEventFilter(flt[1])
            except Exception as _fw_err:
                _fw_log("asmmenu.py:939", _fw_err)
        TRIAD.clear()
        return
    if cur is not None and cur is TRIAD.get("vp"):
        return
    timer.stop()
    end_triad()


TRIAD_BOXES = ("Show Translate XYZ Box", "Show Translate Delta XYZ Box", "Show Rotate Delta XYZ Box")


def triad_apply(comp, which, x, y, z):
    """The triad's value boxes: Translate XYZ puts the component's origin at (x, y, z);
    Translate Delta moves it by them; Rotate Delta turns it by x, y, z degrees about X, Y, Z
    through its origin."""
    pl = App.Placement(comp.Placement)
    if which == TRIAD_BOXES[0]:
        pl.Base = App.Vector(x, y, z)
    elif which == TRIAD_BOXES[1]:
        pl.Base = pl.Base + App.Vector(x, y, z)
    else:
        rot = App.Rotation(App.Vector(0, 0, 1), z).multiply(App.Rotation(App.Vector(0, 1, 0), y)).multiply(
            App.Rotation(App.Vector(1, 0, 0), x))
        pl.Rotation = rot.multiply(pl.Rotation)
    comp.Placement = pl
    return pl


class _TriadBox(QtWidgets.QFrame):
    def __init__(self, comp, which, pos):
        super().__init__(Gui.getMainWindow(), QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint)
        self.setObjectName("FW_TriadBox")
        self.setFrameShape(QtWidgets.QFrame.Box)
        self.comp, self.which = comp, which
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        start = comp.Placement.Base if which == TRIAD_BOXES[0] else App.Vector()
        self.fields = []
        for axis, v in zip("XYZ", (start.x, start.y, start.z)):
            f = QtWidgets.QDoubleSpinBox()
            f.setObjectName("FW_TriadBox" + axis)
            f.setRange(-1e6, 1e6)
            f.setDecimals(2)
            f.setSuffix("deg" if which == TRIAD_BOXES[2] else "mm")
            f.setValue(v)
            f.setToolTip(axis)
            lay.addWidget(f)
            self.fields.append(f)
        ok = QtWidgets.QPushButton("Apply")
        ok.setObjectName("FW_TriadBoxApply")
        ok.clicked.connect(self.apply)
        lay.addWidget(ok)
        self.move(pos)

    def apply(self):
        triad_apply(self.comp, self.which, *[f.value() for f in self.fields])
        self.comp.Document.recompute()
        self.close()


def triad_box(which, pos=None):
    comp = TRIAD.get("comp")
    if comp is None:
        return None
    pos = pos or QtGui.QCursor.pos()
    box = _TriadBox(comp, which, pos)
    TRIAD["box"] = box
    box.show()
    return box


class _TriadMenuFilter(QtCore.QObject):
    def eventFilter(self, obj, event):
        if isinstance(event, QtCore.QEvent) and TRIAD.get("comp") is not None and event.type() in (
                QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease):
            _triad_click_ends(event)
            return False
        if isinstance(event, QtCore.QEvent) and event.type() == QtCore.QEvent.ContextMenu and TRIAD.get("comp") is not None:
            menu = QtWidgets.QMenu(Gui.getMainWindow())
            menu.setObjectName("FW_TriadMenu")
            for name in TRIAD_BOXES:
                a = menu.addAction(name)
                a.triggered.connect(lambda _=False, n=name, p=event.globalPos(): triad_box(n, p))
            TRIAD["menu"] = menu
            menu.popup(event.globalPos())
            return True
        return False


def _triad_menu_on(gdoc):
    try:
        view = gdoc.ActiveView.graphicsView()
        target = view.viewport() if hasattr(view, "viewport") else view
    except Exception:
        return
    f = _TriadMenuFilter(target)
    target.installEventFilter(f)
    TRIAD["filter"] = (target, f)


def _triad_dragger(gdoc):
    try:
        from pivy import coin
        sa = coin.SoSearchAction()
        sa.setType(coin.SoType.fromName("SoTransformDragger"))
        sa.setInterest(coin.SoSearchAction.FIRST)
        sa.setSearchingAll(True)
        sa.apply(gdoc.ActiveView.getSceneGraph())
        path = sa.getPath()
        return path.getTail() if path is not None else None
    except Exception as _fw_err:
        _fw_log("asmmenu.py:triad dragger", _fw_err)
        return None


def _triad_sw_look(gdoc):
    ""

    drag = _triad_dragger(gdoc)
    TRIAD["dragger"] = drag         # read by checks only, never while it drags
    if drag is not None:
        for name in ("xAxisLabel", "yAxisLabel", "zAxisLabel"):
            try:
                drag.getField(name).setValue(" ")       # an empty label crashes the dragger
            except Exception as _fw_err:
                _fw_log("asmmenu.py:triad label", _fw_err)

    def tree():
        if TRIAD.get("comp") is None:
            return
        try:
            from . import shell
            sh = shell.shell()
            if sh is not None and sh.left_pane is not None:
                sh.left_pane.select_name("Model")
        except Exception as _fw_err:
            _fw_log("asmmenu.py:triad tree", _fw_err)
    for ms in (100, 400, 900):      # after the pane's own switch to the Transform page
        QtCore.QTimer.singleShot(ms, tree)


def _triad_click_ends(event):
    ""

    t = event.type()
    if t == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
        TRIAD["press"] = event.pos()
        return
    if t == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
        start = TRIAD.pop("press", None)
        if start is None or (event.pos() - start).manhattanLength() > 3:
            return                          # a drag (the triad's arrows and rings, or the view)
        try:
            pre = Gui.Selection.getPreselection()
            if pre is not None and getattr(pre, "ObjectName", ""):
                return
        except Exception as _fw_err:
            _fw_log("asmmenu.py:triad presel", _fw_err)
        comp = TRIAD.get("comp")
        if comp is None:
            return
        if _near_triad(comp, event):
            return                          # a click on (or just off) the triad's arrows and rings
        gdoc = Gui.getDocument(comp.Document.Name)
        QtCore.QTimer.singleShot(0, lambda: gdoc.resetEdit() if gdoc is not None and gdoc.getInEdit() is not None else None)


TRIAD_NEAR_PX = 90


def _near_triad(comp, event):
    """True for a click within TRIAD_NEAR_PX of the triad's centre on screen (the component's
    origin, where FreeCAD puts the dragger): a missed arrow does not end Move with Triad."""
    try:
        gdoc = Gui.getDocument(comp.Document.Name)
        view = gdoc.ActiveView
        widget = view.graphicsView()
        widget = widget.viewport() if hasattr(widget, "viewport") else widget
        asm = TRIAD.get("asm")
        base = comp.Placement.Base
        if asm is not None and hasattr(asm, "getGlobalPlacement"):
            base = asm.getGlobalPlacement().multVec(base)
        sx, sy = view.getPointOnScreen(base)
        ratio = widget.devicePixelRatioF()
        px, py = event.pos().x() * ratio, (widget.height() - event.pos().y()) * ratio
        return ((px - sx) ** 2 + (py - sy) ** 2) ** 0.5 <= TRIAD_NEAR_PX * ratio
    except Exception as _fw_err:
        _fw_log("asmmenu.py:triad near", _fw_err)
        return False


def end_triad():
    comp, asm = TRIAD.get("comp"), TRIAD.get("asm")
    flt = TRIAD.get("filter")
    if flt is not None:
        try:
            flt[0].removeEventFilter(flt[1])
        except Exception as _fw_err:
            _fw_log("asmmenu.py:1043", _fw_err)
    TRIAD.clear()
    if comp is None:
        return False
    ok = ac.solve(asm)
    doc = comp.Document
    doc.commitTransaction()
    doc.recompute()
    try:
        from . import asmui
        gdoc = Gui.getDocument(doc.Name)
        if gdoc is not None and gdoc.getInEdit() is None:
            asmui.activate(asm)
    except Exception as _fw_err:
        _fw_log("asmmenu.py:1057", _fw_err)
    return ok


def sw_component_items(comp, long_form=False):
    ""


    from . import asmcomp, asminsert
    asm = assembly_of(comp)
    doc = comp.Document
    inner = inner_source(comp)
    fixed = inner[1] in ac.grounded(inner[0]) if inner is not None else comp in ac.grounded(asm)
    temp = asmcomp.is_temporary(comp)
    light = asmcomp.is_lightweight(comp)
    picked = _picked_or(comp)
    can_virtual = comp.TypeId == "App::Link" and not asminsert.is_virtual(comp) and part_document(comp) is not None
    out = [
        ("MakeVirtual", "Make Virtual", lambda: _in_transaction(doc, "Make Virtual", lambda: asminsert.make_virtual(asm, comp)),
         can_virtual, True),
        ("IsolateComponent", "Isolate", lambda: isolate(comp), True, True),
        ("ConfigureComponent", "Configure Component", lambda: _configure(comp), True, True),
        ("AddToLibrary", "Add to Library", lambda: _add_to_library(comp), True, False),
        ("ComponentDisplay", "Component Display", [(n, n, (lambda n=n: asmcomp.component_display(comp, n)),
                                                    asmcomp.display_of(comp) == n) for n, _m in asmcomp.DISPLAYS], True, True),
        ("Lightweight", "Set to Resolved" if light else "Set to Lightweight",
         lambda: asmcomp.set_lightweight(comp, not light), True, False),
        ("FixFloat", "Float" if fixed else "Fix", lambda: fix_float(comp), True, True),
        ("MoveWithTriad", "Move with Triad", lambda: move_with_triad(comp), True, True),   # a fixed part springs back (its Fix holds it)
        ("AddEditMates", "Add/Edit Mates", lambda: _run(comp, "SWStyle_Mate"), True, False),
        ("TemporaryFix", "Release Temporary Fix/Group" if temp else "Temporary Fix/Group",
         lambda: _in_transaction(doc, "Temporary Fix/Group",
                                 (lambda: asmcomp.release_temporary(asm)) if temp else (lambda: asmcomp.temporary_fix(asm, picked))),
         True, True),
        ("FormNewSubassembly", "Form New Subassembly",
         lambda: _in_transaction(doc, "Form New Subassembly", lambda: asmcomp.form_new_subassembly(asm, picked)),
         not ac.is_subassembly(comp), True),
        ("Reload", "Reload", lambda: asmcomp.reload(comp), part_document(comp) is not None, False),
        ("ReplaceComponents", "Replace Components", lambda: asmcomp.replace_dialog(comp), True, False),
        ("SavePartExternal", "Save Part (in External File)", lambda: _save_external(picked),
         asminsert.is_virtual(comp) and comp.TypeId == "App::Link", True),
        ("SaveAssemblyExternal", "Save Assembly (in External File)",
         lambda: _in_transaction(doc, "Save Assembly (in External File)", lambda: asmcomp.save_sub_external(asm, comp)),
         asmcomp.is_virtual_sub(comp), True),
        ("MakeIndependent", "Make Independent",
         lambda: _in_transaction(doc, "Make Independent", lambda: asmcomp.make_independent(asm, comp)),
         len(asmcomp.instances(asm, comp)) > 1, True),
        ("CopyWithMates", "Copy with Mates", lambda: _run(comp, "SWStyle_CopyWithMates"), True, True),

        ("ExternalRefs", "External References...", lambda: _external_refs(comp), _has_refs(comp), True),
        ("AddConfiguration", "Add Configuration...", lambda: add_configuration(comp),
         part_document(comp) is not None, False),
        ("DeleteComponent", "Delete", lambda: delete(comp), True, True),
        ("AddToNewFolder", "Add to New Folder", lambda: _folder(picked), True, True),
        ("CreateNewFolder", "Create New Folder", lambda: _new_folder(asm), True, True),
    ] + [(k, l, r, e, True) for k, l, r, e in _subassembly_items(comp)]
    out = _in_context_items(comp) + out

    # component, External References... on a part that has some
    out = [i for i in out if not (i[0] in ("SavePartExternal", "SaveAssemblyExternal", "ExternalRefs", "MakeVirtual",
                                           "Reload", "MakeIndependent", "AddConfiguration", "FormNewSubassembly")
                                  and not i[3])]
    return out if long_form else [i for i in out if i[4]]


def _has_refs(comp):
    try:
        from . import asmextref
        body = asmextref._body_of(comp)
        return body is not None and bool(asmextref.binders(body.Document))
    except Exception as _fw_err:
        _fw_log("asmmenu.py:1132", _fw_err)
        return False


def _external_refs(comp):
    from . import asmextref
    return asmextref.list_external_references(comp)


def picked_face_of(comp):
    """The flat face of comp picked in the graphics area, else None."""
    asm = assembly_of(comp)
    for sel in Gui.Selection.getSelectionEx("", 0):
        for sub in sel.SubElementNames or []:
            ref = ac.reference(asm, sel.Object, sub) if sub else None
            if ref and ref[0] is comp and ref[1].split(".")[-1].startswith("Face"):
                return ref[1]
    return None


def _in_context_items(comp):
    ""

    from . import asmtools
    ed = asmtools.editing()
    if not ed or ed[1] is comp:
        return []
    face = picked_face_of(comp)
    if face is None:
        return []

    def run():
        from . import asmextref
        doc = ed[1].getLinkedObject(True).Document
        doc.openTransaction("Sketch")
        try:
            _b, sk = asmextref.sketch_on_reference(ed[0], ed[1], comp, face)
        finally:
            doc.commitTransaction()
        if sk is not None:      # edited in place, through the component in the assembly
            body = ed[1].getLinkedObject(True)
            try:
                Gui.getDocument(ed[0].Document.Name).setEdit(ed[0], 0, "%s.%s.%s." % (ed[1].Name, body.Name, sk.Name))
            except Exception as error:
                App.Console.PrintLog("FreeCAD: in-context sketch edit: %s\n" % error)
                from . import fwtell
                fwtell.tell("The sketch was made, but it could not be opened for editing in the assembly.", error)
        return sk
    return [("InContextSketch", "Sketch", run, True, True)]


def _save_external(comps):
    from . import asmsavepart
    return asmsavepart.open_dialog(comps)


def _toolbox_items(comp):
    """A Toolbox component: Edit Toolbox Definition (its Configure Component PM, size and length)."""
    from . import toolbox
    if not toolbox.is_fastener(comp):
        return []
    asm = assembly_of(comp)
    out = [("EditToolbox", "Edit Toolbox Definition", lambda: toolbox.open_fastener(asm, [comp]), True)]
    if getattr(comp, "FwFastenerGroup", ""):      # put in by Smart Fasteners
        out.insert(0, ("EditSmartFastener", "Edit Smart Fastener", lambda: toolbox.edit_smart_fasteners(asm, [comp]), True))
    return out


def _envelope_items(comp):
    """An envelope: Select Using Envelope..., Show/Hide Using Envelope..."""
    from . import asmenvelope
    return asmenvelope.menu_items(comp)


def _speedpak_items(comp):
    """Add SpeedPak / Remove SpeedPak (in the menu only)."""
    from . import asmspeedpak as sp
    doc = comp.Document
    if sp.is_speedpak(getattr(comp, "LinkedObject", None)):
        return [("SpeedPak", "Remove SpeedPak", lambda: _in_transaction(doc, "Remove SpeedPak", lambda: sp.remove(comp)), True)]
    return [("SpeedPak", "Add SpeedPak", lambda: sp.open_panel(comp), sp.can_add(comp))]


def _in_transaction(doc, name, run):
    doc.openTransaction(name)
    try:
        run()
    finally:
        doc.commitTransaction()
    _refresh()


def _configure(obj):
    from . import asmconfigure
    return asmconfigure.configure_component(obj) if not is_mate(obj) else asmconfigure.configure_mate(obj)


def mate_items(joint):
    items = [("EditMate", "Edit Feature", lambda: edit_mate(joint), True),
             ("SuppressMate", "Unsuppress" if suppressed(joint) else "Suppress", lambda: suppress(joint), True),
             ("ConfigureFeature", "Configure Feature", lambda: _configure(joint), True)]
    from . import asmconfigure
    if asmconfigure.has_value(joint):
        items.append(("ConfigureDimension", "Configure Dimension", lambda: _configure(joint), True))
    if ac.mate_type(joint) not in ac.MECHANICAL + ac.LIMITS + ("Symmetric", "Width"):
        items.append(("FlipMate", "Flip Mate Alignment", lambda: flip_alignment(joint), not suppressed(joint)))
    from . import asmreplace
    if asmreplace.can_replace(joint):
        items.append(("ReplaceMate", "Replace Mate Entities", lambda: asmreplace.replace_entities(joint), True))
    from . import asmautorepair as ar
    if ar.missing_refs(joint):
        items.append(("AutoRepair", "Auto Repair", lambda: ar.auto_repair(assembly_of(joint), picked_mates(joint)), True))
    items.append(("AddToNewFolder", "Add to New Folder", lambda: add_to_new_folder(joint), True))
    return items


def picked_mates(joint):
    """The mates picked in the tree with joint (the one right-clicked) first."""
    out = [joint]
    try:
        for sel in Gui.Selection.getSelection():
            if sel is not joint and is_mate(sel):
                out.append(sel)
    except Exception as _fw_err:
        _fw_log("asmmenu.py:1242", _fw_err)
    return out


def add_to_new_folder(joint):
    from . import asmfolder
    return asmfolder.add_to_new_folder(picked_mates(joint))


def folder_items(folder):
    ""

    from . import asmfolder
    own = []
    if asmfolder.is_component_folder(folder):
        comps = list(asmfolder.component_members(folder))
        shown = any(_visible(c) for c in comps)
        off = comps and all(suppression_state(c) == "Suppressed" for c in comps)
        own = [("HideComponents", "Hide Components", lambda: folder_visibility(folder, False), bool(comps) and shown),
               ("ShowComponents", "Show Components", lambda: folder_visibility(folder, True), bool(comps) and not shown),
               ("SuppressFolder", "Set to Resolved" if off else "Suppress",
                lambda: folder_suppression(folder, not off), bool(comps))]
    elif asmfolder.is_folder(folder):
        mates = list(asmfolder.members(folder))
        off = mates and all(suppressed(j) for j in mates)
        own = [("SuppressFolder", "Unsuppress" if off else "Suppress",
                lambda: folder_suppression(folder, not off), bool(mates))]
    return own + [("DissolveFolder", "Dissolve Folder", lambda: asmfolder.remove_folder(folder), True),
                  ("DeleteFolder", "Delete...", lambda: asmfolder.remove_folder(folder, "Delete"), True)]


def _visible(comp):
    try:
        return bool(comp.ViewObject.Visibility)
    except Exception:
        return False


def folder_visibility(folder, on):
    """Hide Components / Show Components on a components folder: every component in it."""
    from . import asmfolder
    for c in asmfolder.component_members(folder):
        try:
            if suppression_state(c) != "Suppressed":
                c.ViewObject.Visibility = on
        except Exception as error:
            App.Console.PrintLog("FreeCAD: folder visibility: %s\n" % error)
    _refresh()


def folder_suppression(folder, on):
    """Suppress / Set to Resolved (components) or Suppress / Unsuppress (mates) for the folder's contents."""
    from . import asmfolder
    if asmfolder.is_component_folder(folder):
        for c in asmfolder.component_members(folder):
            set_suppression_state(c, "Suppressed" if on else "Resolved")
    else:
        for j in asmfolder.members(folder):
            if suppressed(j) != on:
                suppress(j, on)
    _refresh()


ICONS = {   # key: (catalog key whose icon it borrows, FreeCAD icon)
    "EditPart": ("EditComponent", "PartDesign_Body"),
    "QuickConfigurations": ("ConfigurationManager", "Spreadsheet"),
    "HideComponents": ("HideSelection", "Std_ToggleVisibility"),
    "ChangeTransparency": (None, "Std_ToggleTransparency"),
    "IsolateComponent": ("Isolate", "Std_ToggleVisibility"),
    "OpenPart": (None, "Std_Open"),
    "FixFloat": ("FixComponent", "Assembly_ToggleGrounded"),
    "ViewMates": ("Mate", "Assembly_CreateJointDistance"),
    "ComponentProperties": (None, "Std_DlgParameter"),
    "EditMate": ("Mate", "Assembly_CreateJointDistance"),
    "SuppressMate": (None, "Std_ToggleFreeze"),
    "FlipMate": (None, "Assembly_ToggleGrounded"),
    "ReplaceMate": ("Mate", "Assembly_CreateJointDistance"),
    "AddToNewFolder": (None, "folder"),
    "DissolveFolder": (None, "folder"),
    "SpeedPak": (None, "view-refresh"),
    "EditToolbox": (None, "Std_DlgParameter"),
    "EditSmartFastener": (None, "Std_DlgParameter"),
    "SelectUsingEnvelope": (None, "Std_SelBoundingBox"),
    "ShowHideUsingEnvelope": (None, "Std_ToggleVisibility"),
}


def _icon(shell, key):
    if key == "FlipMate":           # the mate pop-up's own Flip Mate Alignment icon
        try:
            from . import asmpm
            icon = asmpm.sw_icon("FlipAlignment")
            if not icon.isNull():
                return icon
        except Exception as _fw_err:
            _fw_log("asmmenu.py:1336", _fw_err)
    borrow, native = ICONS.get(key, (None, None))
    icon = QtGui.QIcon()
    if borrow and shell is not None:
        try:
            icon = shell.binding(borrow).icon()
        except Exception:
            icon = QtGui.QIcon()
    if icon.isNull() and native:
        try:
            import Assembly_rc  # noqa: F401
        except Exception as _fw_err:
            _fw_log("asmmenu.py:1348", _fw_err)
        for name in (native, "document-open" if key == "OpenPart" else None):
            if name and QtCore.QFile.exists(":/icons/%s.svg" % name):
                return QtGui.QIcon(":/icons/%s.svg" % name)     # (Gui.getIcon would post "Cannot find icon")
    return icon


MENU_ONLY = ("ReplaceMate", "AddToNewFolder", "ConfigureFeature", "ConfigureDimension", "SpeedPak", "EditToolbox", "SelectUsingEnvelope", "ShowHideUsingEnvelope")
MENU_ONLY = MENU_ONLY + ("EditSmartFastener",)


def row_entries(shell, target):
    """The context toolbar's buttons for a component or a mate."""
    from . import contextbar
    k = kind(target)
    items = component_items(target) if k == "component" else mate_items(target) if k == "mate" else []
    out = []
    for key, label, run, enabled in items:
        if key in MENU_ONLY:
            continue
        out.append(contextbar.Entry(key, label, _icon(shell, key), contextbar._tip(label, target.Label), run, enabled))
    if k == "component":
        entry = config_entry(shell, target)
        if entry is not None:
            out.append(entry)
    if k == "mate":
        try:
            zoom = contextbar._command_entry(shell, "ZoomSelection")
            if zoom is not None and all(e.key != "ZoomSelection" for e in out):
                out.append(zoom)
        except Exception as _fw_err:
            _fw_log("asmmenu.py:mate-zoom", _fw_err)
    return out


def config_names(comp):
    from . import asmreplacecomp, asmcfginst
    try:
        doc = asmcfginst.source(comp).Document
        return list(asmreplacecomp.configurations(doc) or []), asmcfginst.configuration(comp)
    except Exception:
        return [], None


def _instance_config(comp, name):
    ""
    from . import asmcfginst
    _text_prop(comp, REFCONFIG_PROP, "Referenced configuration")
    setattr(comp, REFCONFIG_PROP, name)
    return asmcfginst.set_configuration(comp, name)


def config_menu(comp, parent=None):
    """The context toolbar's configuration drop-down (Quick Configurations): the part's
    configurations, the shown one ticked; a pick shows it."""
    from . import asmreplacecomp
    names, now = config_names(comp)
    menu = QtWidgets.QMenu(parent or Gui.getMainWindow())
    menu.setObjectName("FW_QuickConfigurations")
    for n in names:
        a = menu.addAction(n)
        a.setCheckable(True)
        a.setChecked(n == now)
        a.triggered.connect(lambda _=False, n=n: _instance_config(comp, n))
    return menu


def config_entry(shell, comp):
    """Quick Configurations on the component's context toolbar (Customize > Toolbars can turn it off)."""
    from . import contextbar, asmrefopts
    if not asmrefopts.customize("QuickConfigurations"):
        return None
    names, now = config_names(comp)
    if len(names) < 2:
        return None         # one configuration: nothing to choose

    def run():
        config_menu(comp).exec(QtGui.QCursor.pos())
    return contextbar.Entry("QuickConfigurations", "Configurations", _icon(shell, "QuickConfigurations"),
                            contextbar._tip("Configurations", "%s: %s" % (comp.Label, now)), run, True)


def menu_entries(original, shell, target, view):
    """fmmenu.entries for the assembly's rows."""
    from . import fmmenu
    k = kind(target)
    if k == "assembly":
        items = original(shell, target.Document, view)
        drop = ("Material", "TopLevelTransparency", "Purge")
        out = []
        for key, label, run, enabled in items:
            if key is None:
                label = "Assembly (%s)" % target.Document.Label
            if key in drop:
                continue
            out.append((key, label, run, enabled))
        return out
    if k == "matesfolder":
        doc = target.Document
        return mates_folder_items(shell, target, view)
    if k == "explodedview":
        from . import asmexpanim
        rest = [i for i in original(shell, target, view) if i[0] not in (None, "Suppress", "Properties")]
        return [(None, "Exploded View (%s)" % target.Label, None, False)] + asmexpanim.view_items(target) + \
            [("-", None, None, False)] + rest
    if k == "explodestep":
        from . import asmexplode, asmexpanim
        ev = asmexplode.view_of_step(target)
        rest = [i for i in original(shell, target, view) if i[0] not in (None, "Delete", "Suppress", "Properties", "Edit", "EditFeature")]
        anim = [i for i in asmexpanim.view_items(ev) if i[0] in ("ExplodeView", "AnimateExplode", "AnimateCollapse")]
        return [(None, "Explode Step (%s)" % target.Label, None, False),
                ("EditStep", "Edit Step", lambda: asmexplode.edit_step(target), True),
                ("DeleteStep", "Delete Step", lambda: asmexplode.delete_step(target), True),
                ("-", None, None, False)] + anim + ([("-", None, None, False)] + rest if rest else [])
    if k == "viewgroup":
        from . import asmexplcfg
        return [(None, "Exploded Views", None, False),
                ("NewExplodedView", "New Exploded View...",
                 lambda: asmexplcfg.new_exploded_view(ac.assembly_of(target.Document)), True),
                ("-", None, None, False)] + _tree_only(original(shell, target, view))
    if k == "fixedrow":
        comp = target.ObjectToGround
        asm = ac.assembly_of(target.Document)
        return [(None, "Fixed (%s)" % comp.Label, None, False),
                ("Float", "Float", lambda: (ac.float_(asm, comp), _refresh()), True),
                ("SelectComponent", "Select Component", lambda: _select(comp), True),
                ("-", None, None, False)] + _tree_only(original(shell, target, view))
    if k == "matefolder_sub":
        return [(None, "Folder (%s)" % target.Label, None, False)] + folder_items(target) + [
            ("-", None, None, False)] + [i for i in original(shell, target, view)
                                         if i[0] not in (None, "Delete", "Suppress", "Properties")]
    items = original(shell, target, view)       # the feature menu with the heading below
    own = component_items(target) if k == "component" else mate_items(target)
    if k == "component":
        own = own + [("DeleteComponent", "Delete", lambda: delete(target), True)]
    else:
        own = own + [("DeleteMate", "Delete", lambda: confirm_delete([target]), True)]
    out = []
    for item in items:
        key = item[0]
        if key in ("Delete", "Suppress") or (key == "Properties" and k == "component"):
            continue        # theirs, for a feature; the component's and mate's own are above

        if key is None:
            out.append((None, ("Component (%s)" if k == "component" else "Mate (%s)")
                        % target.Label.split(" (")[0], None, False))
            out.extend(own)
            continue
        out.append(item)
    if k != "component":
        out = sw_mate_row(target, out)
    return out


MATE_ORDER = ("LockRotation", "Flip Mate Alignment", "Parent/Child...", "Delete", "Add to New Folder", "Properties...",
              "Isolate", "Configure Feature", "Add to Favorites", "Comment", "Go To...", "Create New Folder",
              "Collapse Items", "Rename tree item", "Hide/Show Tree Items...", "Customize Menu")


def toggle_lock(joint):
    ""
    asm = assembly_of(joint)
    on = not bool(getattr(joint, ac.LOCK_PROP, False))
    asm.Document.openTransaction("Lock Rotation")
    try:
        ac.change_mate(asm, joint, "Concentric", None, lock_rotation=on, editing=True)
    finally:
        asm.Document.commitTransaction()
    _refresh()


def sw_mate_row(joint, items):
    ""

    by = {}
    for it in items:
        if it[0] in (None, "-") or not it[1]:
            continue
        label = it[1].replace("&", "")
        label = {"Delete...": "Delete", "Properties": "Properties...",
                 "Feature Properties...": "Properties..."}.get(label, label)
        if label.startswith("Comment"):
            label = "Comment"
        if label == "Properties...":
            it = (it[0], label) + tuple(it[2:])
        by.setdefault(label, it)
    out = [(None, "Feature (%s)" % joint.Label.split(" (")[0], None, False)]
    for name in MATE_ORDER:
        if name == "Isolate":

            comps = mate_components(joint)
            if comps:
                out.append(("IsolateMate", "Isolate", lambda: _isolate_comps(comps), True))
            continue
        if name == "LockRotation":
            if ac.mate_type(joint) == "Concentric":
                out.append(("LockRotation", "Unlock Rotation" if getattr(joint, ac.LOCK_PROP, False) else "Lock Rotation",
                            lambda: toggle_lock(joint), not suppressed(joint)))
            continue
        it = by.get(name)
        if it is None and name == "Create New Folder":
            asm = assembly_of(joint)
            if asm is not None:
                from . import asmfolder
                it = ("NewFolder", "Create New Folder", lambda: asmfolder.create_new_folder(asm), True)
        if it is not None:
            out.append(it)
    return out


def mate_components(joint):
    """The components a mate's two references are on."""
    asm = assembly_of(joint)
    out = []
    for prop in ("Reference1", "Reference2"):
        ref = getattr(joint, prop, None)
        if not ref or asm is None:
            continue
        try:
            c = ac._part_of(asm, ref)
        except Exception:
            c = ref[0]
        if c is not None and is_component(c) and c not in out:
            out.append(c)
    return out


def _isolate_comps(comps):
    from . import asmisolate
    return asmisolate.isolate(list(comps))


def lock_all(asm):
    """The Mates folder's Lock Rotation: every concentric mate locked (or all unlocked when they all are)."""
    conc = [j for j in ac.mates(asm) if ac.mate_type(j) == "Concentric" and not suppressed(j)]
    if not conc:
        return False
    on = not all(getattr(j, ac.LOCK_PROP, False) for j in conc)
    asm.Document.openTransaction("Lock Rotation")
    try:
        for j in conc:
            ac.change_mate(asm, j, "Concentric", None, lock_rotation=on, editing=True)
    finally:
        asm.Document.commitTransaction()
    _refresh()
    return on


def group_by_type(asm):
    """Group Mates > By Mate Type: one mate folder per mate type."""
    from . import asmfolder
    groups = {}
    for j in ac.mates(asm):
        if asmfolder.folder_of(j) is None:
            groups.setdefault(ac.mate_type(j) or "Mate", []).append(j)
    made = []
    for typ, js in sorted(groups.items()):
        f = asmfolder.make_folder(asm, js)
        if f is not None:
            f.Label = "%s Mates" % typ
            made.append(f)
    _refresh()
    return made


def ungroup_all(asm):
    from . import asmfolder
    for f in list(asmfolder.folders(asm)):
        asmfolder.dissolve(f)
    _refresh()


def _isolate_all(asm):
    from . import asmisolate
    return asmisolate.isolate(list(ac.components(asm)))


def mates_folder_items(shell, target, view):
    ""
    from . import fmmenu, asmfolder
    doc = target.Document
    asm = assembly_of(target) or ac.assembly_of(doc)
    mates = ac.mates(asm) if asm is not None else []
    conc = [j for j in mates if ac.mate_type(j) == "Concentric"]
    def group_menu(m):
        a = m.addAction("By Mate Type")
        a.triggered.connect(lambda: group_by_type(asm))
        if asmfolder.folders(asm):       # only when there is a group to undo (nothing greyed, pkg208)
            b = m.addAction("Ungroup All")
            b.triggered.connect(lambda: ungroup_all(asm))
    from . import asmautorepair as ar
    bad = ar.broken(asm) if asm is not None else []
    rows = [(None, "Mates", None, False),
            ("EditFeatures", "Edit Features", lambda: edit_mate(mates[0]), bool(mates))]
    if bad:
        rows.append(("AutoRepair", "Auto Repair", lambda: ar.auto_repair(asm), True))
    return rows + [
            ("ParentChild", "Parent/Child...", lambda: fmmenu.parent_child(target), True),
            ("LockRotation", "Lock Rotation", lambda: lock_all(asm), bool(conc)),
            ("GroupMates", "Group Mates", fmmenu.Sub(group_menu), bool(mates)),
            ("Comment", "Comment", fmmenu.Sub(lambda m: fmmenu._comment_menu(m, shell, target, doc)), True),
            ("-", None, None, False),
            ("Isolate", "Isolate", lambda: _isolate_all(asm), bool(mates)),
            ("GoTo", "Go To...", lambda: fmmenu.go_to(view, doc), True),
            ("NewFolder", "Create New Folder", lambda: asmfolder.create_new_folder(asm), True),
            ("Collapse", "Collapse Items", lambda: fmmenu.collapse(view), True),
            ("Rename", "Rename tree item", lambda: fmmenu.rename(view, target), True),
            ("TreeItems", "Hide/Show Tree Items...", fmmenu.tree_items, True),
            ("-", None, None, False),
            ("Customize", "Customize Menu", None, True)]


# ----------------------------------------------------------------------------- hooks
def picked_component():
    """The component under the current pick in the graphics area (unresolved selection), or None."""
    try:
        sels = Gui.Selection.getSelectionEx("", 0)
    except Exception:
        return None
    if len(sels) != 1:
        return None
    sel = sels[0]
    asm = ac.assembly_of(sel.Object.Document)
    if asm is None:
        return None
    if sel.Object in ac.components(asm) and not sel.SubElementNames:
        return sel.Object
    subs = [s for s in sel.SubElementNames if s]
    if len(subs) != 1:
        return None
    ref = ac.reference(asm, sel.Object, subs[0]) if sel.Object is asm else None
    if ref is not None:
        return ref[0]
    first = subs[0].split(".")[0]
    obj = asm.Document.getObject(first)
    return obj if obj in ac.components(asm) else None


def install():
    from . import fmmenu, fmtree, contextbar
    try:
        install_delete()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: assembly Delete: %s\n" % error)
    if getattr(fmmenu, "_fw_asm_menu", False):
        return
    original_entries = fmmenu.entries
    original_kind = fmmenu.kind_of

    def entries(shell, target, view=None, *more, **named):
        # *more, **named: whatever fmmenu adds later reaches its own entries untouched
        if kind(target) is not None:
            try:
                return menu_entries(lambda sh, t, v: original_entries(sh, t, v, *more, **named), shell, target, view)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: assembly menu: %s\n" % error)
        return original_entries(shell, target, view, *more, **named)

    def kind_of(target, *more, **named):
        k = kind(target)
        if k == "assembly":
            return "part"           # the top row: no toolbar row of a feature
        if k in ("explodedview", "viewgroup", "fixedrow"):
            return original_kind(target, *more, **named)
        return k or original_kind(target, *more, **named)

    fmmenu.entries = entries
    fmmenu.kind_of = kind_of

    original_part_entries = contextbar.part_entries

    def part_entries(shell, obj, sub, *more, **named):
        if kind(obj) in ("component", "mate"):
            return row_entries(shell, obj)
        return original_part_entries(shell, obj, sub, *more, **named)

    contextbar.part_entries = part_entries

    original_for_selection = contextbar.entries_for_selection

    def entries_for_selection(shell, *more, **named):
        try:
            if contextbar.sketch_in_edit() is None and not contextbar.dialog_open() \
                    and not contextbar.tool_running(shell):
                comp = picked_component()
                if comp is not None:
                    return "part", row_entries(shell, comp)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: component toolbar: %s\n" % error)
        return original_for_selection(shell, *more, **named)

    contextbar.entries_for_selection = entries_for_selection

    original_object = fmtree._object

    def _object(doc, text, *more, **named):
        found = original_object(doc, text, *more, **named)
        if found is None and text and " (" in str(text):
            found = original_object(doc, str(text).split(" (")[0])     # a mate row: "Concentric1 (A,B)"
        return found

    fmtree._object = _object
    fmmenu._fw_asm_menu = True
