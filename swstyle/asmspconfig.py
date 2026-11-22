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

import json

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import asmcore as ac

META = "FreeWorks:SpeedPak:"
SUFFIX = "_speedpak"
CONFIG_PROP = "FwSpeedPakConfig"
TOL = 1e-4


# ---------------------------------------------------------------- the stored SpeedPaks
def configs(doc):
    """{configuration: {"faces": [[x, y, z, area]], "bodies": [[x, y, z, volume]]}}."""
    out = {}
    if doc is None:
        return out
    for k, v in dict(getattr(doc, "Meta", {}) or {}).items():
        if k.startswith(META):
            try:
                out[k[len(META):]] = json.loads(v)
            except ValueError as _fw_err:
                _fw_log("asmspconfig.py:54", _fw_err)
    return out


def has(doc, config):
    return config in configs(doc)


def store(doc, config, faces, bodies, ex_faces=(), ex_bodies=()):
    meta = dict(doc.Meta or {})
    data = {"faces": [list(f) for f in faces], "bodies": [list(b) for b in bodies]}
    if ex_faces or ex_bodies:
        data["ex_faces"] = [list(f) for f in ex_faces]
        data["ex_bodies"] = [list(b) for b in ex_bodies]
    meta[META + config] = json.dumps(data)
    doc.Meta = meta
    _modified(doc)


def delete(doc, config):
    meta = dict(doc.Meta or {})
    meta.pop(META + config, None)
    doc.Meta = meta
    _modified(doc)


def _modified(doc):
    try:
        Gui.getDocument(doc.Name).Modified = True
    except Exception as _fw_err:
        _fw_log("asmspconfig.py:84", _fw_err)


def speedpak_name(config):
    return config + SUFFIX


def base_of(name):
    return name[:-len(SUFFIX)] if name.endswith(SUFFIX) else None


def main_object(doc):
    """What a component of this document shows: the assembly, else the body or part."""
    asm = ac.assembly_of(doc)
    if asm is not None:
        return asm
    from . import asmfeature as af
    cands = [o for o in doc.Objects if hasattr(o, "Shape") and not o.InList and _solidish(o)]
    bodies = [o for o in cands if af.is_body(o)]
    return (bodies or cands or [None])[0]


def _solidish(o):
    try:
        return not o.Shape.isNull() and bool(o.Shape.Faces)
    except Exception:
        return False


def face_key(face):
    c = face.CenterOfMass
    return [round(c.x, 6), round(c.y, 6), round(c.z, 6), round(face.Area, 6)]


def body_key(solid):
    c = solid.CenterOfMass
    return [round(c.x, 6), round(c.y, 6), round(c.z, 6), round(solid.Volume, 6)]


def _match(keys, items, size_of):
    out = []
    for k in keys:
        scale = max(1.0, abs(k[3]))
        best = None
        for i, it in enumerate(items):
            c = it.CenterOfMass
            d = ((c.x - k[0]) ** 2 + (c.y - k[1]) ** 2 + (c.z - k[2]) ** 2) ** 0.5
            if d < 1e-3 and abs(size_of(it) - k[3]) < TOL * scale + 1e-6:
                best = i
                break
        if best is not None and best not in out:
            out.append(best)
    return sorted(out)


def indexes(target, data):
    """The SpeedPak's faces and bodies as indexes into the component's light shape."""
    from . import asmspeedpak as sp
    shape = sp.light_shape(target)
    return (_match(data.get("faces", []), shape.Faces, lambda f: f.Area),
            _match(data.get("bodies", []), shape.Solids, lambda s: s.Volume))


def ex_indexes(target, data):
    """The SpeedPak's excluded faces and bodies as indexes into the component's light shape."""
    from . import asmspeedpak as sp
    shape = sp.light_shape(target)
    return (_match(data.get("ex_faces", []), shape.Faces, lambda f: f.Area),
            _match(data.get("ex_bodies", []), shape.Solids, lambda s: s.Volume))


# ---------------------------------------------------------------- a component using one
def own_target(comp):
    from . import asmspeedpak as sp, asmcfginst
    return sp.own(asmcfginst.source(comp))


def used_config(comp):
    """The configuration whose SpeedPak the component shows, else None."""
    target = getattr(comp, "LinkedObject", None)
    return getattr(target, CONFIG_PROP, None) or None


def names_for(doc):
    """The configurations a component of doc can show: its own, each followed by its SpeedPak."""
    from . import asmreplacecomp
    base = list(asmreplacecomp.configurations(doc) or [])
    sps = configs(doc)
    out = []
    for n in base:
        out.append(n)
        if n in sps:
            out.append(speedpak_name(n))
    return out


def use(comp, name):
    """The component shows configuration name: a "<cfg>_speedpak" one as that SpeedPak."""
    from . import asmspeedpak as sp, asmreplacecomp
    target = own_target(comp)
    if target is None:
        return False
    pdoc = target.Document
    base = base_of(name)
    doc = comp.Document
    doc.openTransaction("Configuration")
    try:
        if sp.is_speedpak(comp.LinkedObject):
            sp.remove(comp)
        if base is not None and has(pdoc, base):
            asmreplacecomp.set_configuration(target, base)
            data = configs(pdoc)[base]
            faces, bodies = indexes(target, data)
            ex_faces, ex_bodies = ex_indexes(target, data)
            made = sp.add(comp, faces, bodies, ex_faces, ex_bodies)
            if made is not None:
                made.addProperty("App::PropertyString", CONFIG_PROP, "FreeCAD", "The configuration's SpeedPak")
                made.setEditorMode(CONFIG_PROP, 2)
                setattr(made, CONFIG_PROP, base)
        else:
            from . import asmcfginst
            asmcfginst.set_configuration(comp, name, recompute=False)     # this instance only
        doc.recompute()
    finally:
        doc.commitTransaction()
    try:
        from . import asmui
        asmui.refresh()
    except Exception as _fw_err:
        _fw_log("asmspconfig.py:213", _fw_err)
    return True


# ---------------------------------------------------------------- Add SpeedPak in the document
class ConfigSpeedPakPanel:
    ""

    def __init__(self, doc, config):
        from . import asmpm
        self.doc, self.config = doc, config
        self.target = main_object(doc)
        data = configs(doc).get(config, {"faces": [], "bodies": []})
        self.faces = [list(f) for f in data.get("faces", [])]
        self.bodies = [list(b) for b in data.get("bodies", [])]
        self.ex_faces = [list(f) for f in data.get("ex_faces", [])]
        self.ex_bodies = [list(b) for b in data.get("ex_bodies", [])]
        box, lay = asmpm._box("Include", "SpeedPak")
        box.setObjectName("FW_ConfigSpeedPak")
        lay.addWidget(QtWidgets.QLabel(speedpak_name(config)))
        lay.addWidget(QtWidgets.QLabel("Faces to include:"))
        self.face_list = QtWidgets.QListWidget()
        self.face_list.setObjectName("FW_SpeedPakFaces")
        self.face_list.setStyleSheet(asmpm.PICK_STYLE)
        self.face_list.setFixedHeight(asmpm._rows(self.face_list, 4))
        lay.addWidget(self.face_list)
        lay.addWidget(QtWidgets.QLabel("Bodies to include:"))
        self.body_list = QtWidgets.QListWidget()
        self.body_list.setObjectName("FW_SpeedPakBodies")
        self.body_list.setFixedHeight(asmpm._rows(self.body_list, 3))
        lay.addWidget(self.body_list)
        lay.addWidget(QtWidgets.QLabel("Quick include:"))
        self.quick = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.quick.setObjectName("FW_SpeedPakQuick")
        self.quick.setRange(0, 10)
        self.quick.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.quick.valueChanged.connect(self._quick)
        lay.addWidget(self.quick)
        note = QtWidgets.QLabel("Assemblies that use %s show it as a SpeedPak: only the included faces and "
                                "bodies can be picked and mated. Include nothing to keep every face."
                                % speedpak_name(config))
        note.setWordWrap(True)
        lay.addWidget(note)
        exbox, exlay = asmpm._box("Exclude", "SpeedPakExclude")
        exbox.setObjectName("FW_SpeedPakExclude")
        self.exclude_mode = QtWidgets.QCheckBox("Pick to exclude")
        self.exclude_mode.setObjectName("FW_SpeedPakExcludeMode")
        exlay.addWidget(self.exclude_mode)
        exlay.addWidget(QtWidgets.QLabel("Faces to exclude:"))
        self.exface_list = QtWidgets.QListWidget()
        self.exface_list.setObjectName("FW_SpeedPakExFaces")
        self.exface_list.setFixedHeight(asmpm._rows(self.exface_list, 3))
        exlay.addWidget(self.exface_list)
        exlay.addWidget(QtWidgets.QLabel("Bodies to exclude:"))
        self.exbody_list = QtWidgets.QListWidget()
        self.exbody_list.setObjectName("FW_SpeedPakExBodies")
        self.exbody_list.setFixedHeight(asmpm._rows(self.exbody_list, 2))
        exlay.addWidget(self.exbody_list)
        self.form = [box, exbox]
        self._show()
        Gui.Selection.addObserver(self, 0)

    def _quick(self, level):
        from . import asmspeedpak as sp
        if self.target is None:
            return
        shape = sp.light_shape(self.target)
        pl = self.target.Placement
        self.faces = []
        for i in sp.quick_include(self.target, level):
            f = shape.Faces[i].copy()
            f.Placement = pl
            self.faces.append(face_key(f))
        self._show()

    def _show(self):
        self.face_list.clear()
        for k in self.faces:
            self.face_list.addItem("Face at (%.1f, %.1f, %.1f)" % tuple(k[:3]))
        self.body_list.clear()
        for k in self.bodies:
            self.body_list.addItem("Body at (%.1f, %.1f, %.1f)" % tuple(k[:3]))
        if hasattr(self, "exface_list"):
            self.exface_list.clear()
            for k in self.ex_faces:
                self.exface_list.addItem("Face at (%.1f, %.1f, %.1f)" % tuple(k[:3]))
            self.exbody_list.clear()
            for k in self.ex_bodies:
                self.exbody_list.addItem("Body at (%.1f, %.1f, %.1f)" % tuple(k[:3]))

    def toggle(self, keys, key):
        for k in keys:
            if all(abs(a - b) < 1e-4 for a, b in zip(k[:3], key[:3])):
                keys.remove(k)
                return False
        keys.append(key)
        return True

    def pick(self, obj, sub):
        """A face toggles in Faces to include; a body (a whole solid, from the tree) in Bodies."""
        try:
            geo = obj.getSubObject(sub) if sub else obj.Shape
        except Exception:
            return
        if geo is None or geo.isNull():
            return
        ex = hasattr(self, "exclude_mode") and self.exclude_mode.isChecked()
        faces, other_f = (self.ex_faces, self.faces) if ex else (self.faces, self.ex_faces)
        bodies, other_b = (self.ex_bodies, self.bodies) if ex else (self.bodies, self.ex_bodies)
        if geo.ShapeType == "Face":
            key = face_key(geo)
            if self.toggle(faces, key):
                self._drop(other_f, key)
        else:
            for s in geo.Solids:
                key = body_key(s)
                if self.toggle(bodies, key):
                    self._drop(other_b, key)
        self._show()

    def _drop(self, keys, key):
        for k in list(keys):
            if all(abs(a - b) < 1e-4 for a, b in zip(k[:3], key[:3])):
                keys.remove(k)

    def addSelection(self, doc, obj, sub, pnt):
        if doc != self.doc.Name:
            return
        o = self.doc.getObject(obj)
        QtCore.QTimer.singleShot(0, lambda: (self.pick(o, sub), Gui.Selection.clearSelection()))

    def removeSelection(self, *a):
        pass

    def clearSelection(self, *a):
        pass

    def setPreselection(self, *a):
        pass

    def _done(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmspconfig.py:357", _fw_err)
        Gui.Control.closeDialog()
        _refresh_cm()
        return True

    def accept(self):
        store(self.doc, self.config, self.faces, self.bodies, self.ex_faces, self.ex_bodies)
        return self._done()

    def reject(self):
        return self._done()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


def open_panel(doc, config):
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    panel = ConfigSpeedPakPanel(doc, config)
    Gui.Control.showDialog(panel)
    return panel


def update_users(doc, config):
    """Update SpeedPak: every open assembly component showing this SpeedPak is made again."""
    done = []
    for d in App.listDocuments().values():
        asm = ac.assembly_of(d)
        if asm is None:
            continue
        for c in ac.components(asm):
            target = own_target(c)
            if target is not None and target.Document is doc and used_config(c) == config:
                use(c, speedpak_name(config))
                done.append(c)
    return done


def _refresh_cm():
    try:
        from . import configmanager
        configmanager.refresh_all()
    except Exception as _fw_err:
        _fw_log("asmspconfig.py:401", _fw_err)


# ---------------------------------------------------------------- ConfigurationManager rows
def cm_entries(doc, data):
    """Extra right-click entries for a ConfigurationManager row (data is the row's ROLE tuple)."""
    kind = data[0] if data else None
    if kind in ("config", "default"):
        name = data[1] if kind == "config" else "Default"
        if has(doc, name):
            return []
        return [("Add SpeedPak...", lambda: open_panel(doc, name), main_object(doc) is not None)]
    if kind == "speedpak":
        name = data[1]
        return [("Edit SpeedPak...", lambda: open_panel(doc, name), True),
                ("Update SpeedPak", lambda: update_users(doc, name), True),
                ("Delete", lambda: (delete(doc, name), _refresh_cm()), True)]
    return []


def _patch_configmanager():
    from . import configmanager as cm
    if getattr(cm.Page, "_fw_speedpak", False):
        return
    refresh0, entries0 = cm.Page.refresh, cm.Page.entries

    def refresh(self):
        refresh0(self)
        try:
            doc = App.ActiveDocument
            sps = configs(doc)
            root = self.tree.topLevelItem(0)
            if not sps or root is None:
                return
            todo = [root]
            while todo:
                it = todo.pop(0)
                todo += [it.child(i) for i in range(it.childCount())]
                d = it.data(0, cm.ROLE) or ()
                name = d[1] if d[:1] == ("config",) else "Default" if d[:1] == ("default",) else None
                if name in sps:
                    sub = QtWidgets.QTreeWidgetItem([speedpak_name(name)])
                    sub.setData(0, cm.ROLE, ("speedpak", name))
                    sub.setToolTip(0, "The SpeedPak of %s, for assemblies that use it" % name)
                    it.addChild(sub)
            self.tree.expandAll()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: SpeedPak rows: %s\n" % error)

    def entries(self, item):
        out = list(entries0(self, item))
        try:
            d = (item.data(0, cm.ROLE) if item is not None else None) or ("none",)
            doc = App.ActiveDocument
            extra = cm_entries(doc, d) if doc is not None else []
            if d[0] == "speedpak":
                return extra
            at = next((i for i, e in enumerate(out) if e[0] == "Edit Table..."), len(out))
            out[at:at] = extra
        except Exception as error:
            App.Console.PrintLog("FreeCAD: SpeedPak menu: %s\n" % error)
        return out

    cm.Page.refresh = refresh
    cm.Page.entries = entries
    cm.Page._fw_speedpak = True


# ---------------------------------------------------------------- the assembly side
def _patch_assembly():
    from . import asmmenu
    if getattr(asmmenu, "_fw_spconfig", False):
        return
    part_doc0 = asmmenu.part_document

    def part_document(comp):
        try:
            target = getattr(comp, "LinkedObject", None)
            from . import asmspeedpak as sp
            if sp.is_speedpak(target):
                d = sp.own(target).Document
                return d if d is not comp.Document else None
        except Exception as _fw_err:
            _fw_log("asmspconfig.py:484", _fw_err)
        return part_doc0(comp)
    asmmenu.part_document = part_document

    def config_names(comp):
        target = own_target(comp)
        try:
            from . import asmreplacecomp
            doc = target.Document
            used = used_config(comp)
            from . import asmcfginst
            now = speedpak_name(used) if used else asmcfginst.configuration(comp)
            return names_for(doc), now
        except Exception:
            return [], None
    asmmenu.config_names = config_names

    def config_menu(comp, parent=None):
        names, now = config_names(comp)
        menu = QtWidgets.QMenu(parent or Gui.getMainWindow())
        menu.setObjectName("FW_QuickConfigurations")
        for n in names:
            a = menu.addAction(n)
            a.setCheckable(True)
            a.setChecked(n == now)
            a.triggered.connect(lambda _=False, n=n: use(comp, n))
        return menu
    asmmenu.config_menu = config_menu

    dlg = asmmenu.ComponentPropertiesDialog
    init0, apply0 = dlg.__init__, dlg.apply

    def __init__(self, comp, parent=None):
        init0(self, comp, parent)
        try:
            target = own_target(comp)
            names = names_for(target.Document) if target is not None else []
            have = [self.configs.item(i).text() for i in range(self.configs.count())]
            for i, n in enumerate(names):
                if n not in have:
                    self.configs.insertItem(min(i, self.configs.count()), n)
            used = used_config(comp)
            if used:
                hit = self.configs.findItems(speedpak_name(used), QtCore.Qt.MatchExactly)
                if hit:
                    self.configs.setCurrentItem(hit[0])
            self._fw_sp_comp = comp
            self._fw_sp_was = speedpak_name(used) if used else None
        except Exception as error:
            App.Console.PrintLog("FreeCAD: SpeedPak configurations: %s\n" % error)

    def apply(self, *a, **k):
        comp = getattr(self, "_fw_sp_comp", None)
        item = self.configs.currentItem()
        pick = item.text() if item is not None else None
        was = getattr(self, "_fw_sp_was", None)
        sp_pick = pick is not None and base_of(pick) is not None
        if comp is not None and sp_pick and item is not None:
            # ours: the referenced configuration's SpeedPak; the rest of the dialog as usual
            self.configs.blockSignals(True)
            target = own_target(comp)
            from . import asmreplacecomp
            base = asmreplacecomp.active_configuration(target.Document) if target is not None else None
            hit = self.configs.findItems(base or "", QtCore.Qt.MatchExactly)
            if hit:
                self.configs.setCurrentItem(hit[0])
            self.configs.blockSignals(False)
        out = apply0(self, *a, **k)
        try:
            if comp is not None and pick is not None and (sp_pick or was) and pick != was:
                use(comp, pick)
                if REF in comp.PropertiesList:
                    setattr(comp, REF, pick)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: SpeedPak configuration: %s\n" % error)
        return out

    dlg.__init__ = __init__
    dlg.apply = apply
    asmmenu._fw_spconfig = True


REF = "FwReferencedConfiguration"


def install():
    for fn in (_patch_configmanager, _patch_assembly):
        try:
            fn()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: SpeedPak configurations (%s): %s\n" % (fn.__name__, error))
