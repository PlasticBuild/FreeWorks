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
from PySide import QtCore, QtWidgets

from . import asmcore as ac

Qt = QtCore.Qt
OPEN = []
MARKS = {"In context": "->", "Out of context": "->?", "Locked": "->*", "Broken": "->x"}


def _part_of(comp):
    """The part a component stands for: an assembly cut through it links the cut's copy in the
    assembly file, and the part (with its in-context references) is that copy's own."""
    target = comp.getLinkedObject(True)
    try:
        from . import asmfeature
        if asmfeature.is_body(target):
            target = asmfeature.source(target) or target
    except Exception:
        pass
    return target


def _body_of(comp):
    target = _part_of(comp) if comp.TypeId == "App::Link" else comp
    return target if target is not None and target.TypeId == "PartDesign::Body" else None


def binders(doc):
    """The SubShapeBinders of doc that bind geometry of another document (in-context references)."""
    out = []
    for o in doc.Objects:
        if o.TypeId != "PartDesign::SubShapeBinder" or getattr(o, "FwNoReference", False):
            continue        # a copy made with "Allow creation of references external to the model" off
        try:
            sup = o.Support or []
        except Exception:
            sup = []
        if any(s[0] is not None and s[0].Document is not doc for s in sup) or getattr(o, "FwReferenced", ""):
            out.append(o)
        elif not sup and getattr(o, "FwContext", "") and dependents(o):
            out.append(o)       # its part was closed again (not loaded): still a reference, out of context
    return out


def prune(doc):
    ""

    n = 0
    for b in [o for o in doc.Objects if o.TypeId == "PartDesign::SubShapeBinder"]:
        if getattr(b, "FwInContext", False) and not dependents(b):
            try:
                doc.removeObject(b.Name)
                n += 1
            except Exception as _fw_err:
                _fw_log("asmextref.py:70", _fw_err)
    return n


def status(binder):
    mode = getattr(binder, "BindMode", "Synchronized")
    if mode == "Frozen":
        return "Locked"
    if mode == "Detached":
        return "Broken"
    ctx = getattr(binder, "FwContext", "")
    if ctx:
        want = os.path.normcase(os.path.normpath(ctx))
        for d in App.listDocuments().values():
            if d.FileName and os.path.normcase(os.path.normpath(d.FileName)) == want:
                return "In context"
        return "Out of context"
    try:
        sup = binder.Support or []
        if sup and all(s[0] is not None and App.listDocuments().get(s[0].Document.Name) is s[0].Document for s in sup):
            return "In context"
    except Exception as _fw_err:
        _fw_log("asmextref.py:92", _fw_err)
    return "Out of context"


def referenced_entity(binder):
    ""
    if getattr(binder, "FwReferenced", ""):
        return binder.FwReferenced
    out = []
    for obj, subs in binder.Support or []:
        for sub in subs or [""]:
            names = [n for n in sub.split(".") if n]
            comp = None
            for n in names:
                o = obj.Document.getObject(n)
                if o is not None and o.TypeId in ("App::Link", "Assembly::AssemblyLink"):
                    comp = o
            el = names[-1] if names else ""
            who = comp.Label if comp is not None else (getattr(binder, "FwRefLabel", "") or obj.Label)
            out.append("%s of %s" % (el, who) if el else who)
    return ", ".join(out)


def dependents(binder):
    """The features built on a reference (they carry its mark in the tree)."""
    return [o for o in binder.InList if o.Document is binder.Document and o.TypeId != "PartDesign::Body"]


def rows(doc):
    """[(feature, data, status, referenced entity, binder)] for List External References."""
    out = []
    for b in binders(doc):
        feats = []
        for f in dependents(b) or [b]:
            if f not in feats:
                feats.append(f)     # a sketch using four of the reference's edges is one row
        for f in feats:
            out.append((f.Label, b.Label, status(b), referenced_entity(b), b))
    return out


def feature_component(binder):
    """List External References' Feature's Component: the instance the reference was made in
    ("Part1<1>"), while the assembly it was made in is open; else the part's own name."""
    body = next((o for o in binder.InList if o.TypeId == "PartDesign::Body"), None)
    path = getattr(binder, "FwContext", "") or ""
    if path and body is not None:
        want = os.path.normcase(os.path.normpath(path))
        for d in App.listDocuments().values():
            if d.FileName and os.path.normcase(os.path.normpath(d.FileName)) == want:
                asm = ac.assembly_of(d)
                comp = _holder(asm, binder, body) if asm is not None else None
                if comp is not None:
                    return comp.Label
    return body.Label if body is not None else binder.Document.Label


def marks(doc):
    ""
    out = {}
    from . import asmrefopts
    show_x = asmrefopts.on(asmrefopts.SHOW_X)
    for b in binders(doc):
        st = status(b)
        if st == "Broken" and not show_x:
            continue            # Options: Show "x" in feature tree for broken external references off
        m = MARKS[st]
        for f in [b] + dependents(b):
            out[f.Label] = f.Label + m
    return out


def component_mark(comp):
    ""

    body = _body_of(comp)
    if body is None:
        return ""
    from . import asmrefopts
    show_x = asmrefopts.on(asmrefopts.SHOW_X)
    found = []
    for b in binders(body.Document):
        try:
            if b.getParentGeoFeatureGroup() is not body:
                continue
        except Exception:
            continue
        st = status(b)
        if st == "Broken" and not show_x:
            continue
        found.append(st)
    for st in ("In context", "Out of context", "Locked", "Broken"):
        if st in found:
            return MARKS[st]
    return ""


def set_mode(doc, mode):
    """Lock All (Frozen), Unlock All (Synchronized), Break All (Detached)."""
    n = 0
    for b in binders(doc):
        if getattr(b, "BindMode", "") == "Detached":
            continue                # broken for good
        if b.BindMode != mode:
            if mode == "Detached" and not hasattr(b, "FwReferenced"):
                b.addProperty("App::PropertyString", "FwReferenced", "FreeCAD", "What the reference was on")
                b.setEditorMode("FwReferenced", 2)
                b.FwReferenced = referenced_entity(b)
            b.BindMode = mode
            n += 1
    doc.recompute()
    return n


def lock_all(doc):
    return set_mode(doc, "Frozen")


def unlock_all(doc):
    n = set_mode(doc, "Synchronized")
    # unlocked, a reference catches up with where its component is now (it was left where it was locked)
    for d in list(App.listDocuments().values()):
        try:
            asm = ac.assembly_of(d)
            if asm is not None and (d is doc or doc in _ref_docs(asm)):
                follow_binders(asm)
        except Exception as _fw_err:
            _fw_log("asmextref.py:unlock follow", _fw_err)
    doc.recompute()
    return n


def break_all(doc):
    return set_mode(doc, "Detached")


def sketch_on_reference(asm, comp, other, sub):
    """While comp's part is edited in context: a sketch on other's face sub, through a reference
    (SubShapeBinder) that follows other in the assembly. Returns (binder, sketch)."""
    body = _body_of(comp)
    if body is None:
        return None, None
    from . import asmrefopts
    others = asmrefopts.other_contexts(body.Document, asm)
    if others and not asmrefopts.on(asmrefopts.MULTI_CONTEXT):
        asmrefopts.message("%s already has external references in the context of %s.\n\nTo add references in "
                           "this assembly too, turn on \"Allow multiple contexts for parts when editing in assembly\" "
                           "(Options, External References)." % (body.Document.Label, ", ".join(others)))
        return None, None
    binder = reference_binder(asm, body, other, sub)
    sk = body.newObject("Sketcher::SketchObject", "Sketch")
    sk.AttachmentSupport = [(binder, "Face1")]
    sk.MapMode = "FlatFace"
    body.Document.recompute()
    return binder, sk


def reference_binder(asm, body, other, sub):
    """A reference in body to other's element sub (SubShapeBinder). It binds other's own part,
    placed where the assembly has other (follow_binders), not the element through the assembly:
    the assembly holds this part, so a reference through it loops and the sketch on it fails
    (the binder, its sketch and their feature invalid), as in_context_items already does."""
    from . import asmrefopts
    external = asmrefopts.on(asmrefopts.ALLOW_EXTERNAL)
    target = other.getLinkedObject(True) if other.TypeId in ("App::Link", "Assembly::AssemblyLink") else other
    binder = body.newObject("PartDesign::SubShapeBinder", "Binder")
    binder.Support = [(target, [sub])]
    try:
        binder.Relative = True      # a face or edge: not relative, FreeCAD puts it off where the part has it
        _own_context(binder)
    except Exception as _fw_err:
        _fw_log("asmextref.py:204", _fw_err)
    binder.Label = "Reference (%s)" % other.Label
    for prop, typ in (("FwInContext", "App::PropertyBool"), ("FwRefComp", "App::PropertyString"),
                      ("FwRefLabel", "App::PropertyString")):
        binder.addProperty(typ, prop, "FreeCAD", "In-context reference")
        binder.setEditorMode(prop, 2)
    binder.FwInContext, binder.FwRefComp, binder.FwRefLabel = True, other.Name, other.Label
    _remember_context(binder, asm)
    if binder.ViewObject is not None:
        binder.ViewObject.Visibility = False
    follow_binders(asm)
    body.Document.recompute()
    if not external:        # no reference: the face is copied in and stays as it is
        binder.addProperty("App::PropertyBool", "FwNoReference", "FreeCAD", "A copy, not an external reference")
        binder.setEditorMode("FwNoReference", 2)
        binder.FwNoReference = True
        binder.BindMode = "Detached"
        binder.Label = "Copied face (%s)" % other.Label
    return binder


def note_context(binder, asm):
    ""


    path = asm.Document.FileName or ""
    if path and getattr(binder, "FwContext", None) not in (None, path):
        binder.FwContext = path


def note_contexts(asm_doc):
    """After an assembly is saved: its parts' in-context references name its file."""
    asm = ac.assembly_of(asm_doc)
    if asm is None or not asm_doc.FileName:
        return 0
    n = 0
    seen = set()
    for c in ac.components(asm):
        try:
            d = _part_of(c).Document
        except Exception:
            continue
        if d is asm_doc or d.Name in seen:
            continue
        seen.add(d.Name)
        for b in d.Objects:
            name = getattr(b, "FwRefComp", "")
            if not name or b.TypeId != "PartDesign::SubShapeBinder" or asm_doc.getObject(name) is None:
                continue
            if _holder(asm, b, b.getParentGeoFeatureGroup()) is None:
                continue
            was = getattr(b, "FwContext", "")
            note_context(b, asm)
            n += was != getattr(b, "FwContext", "")
    return n


def _remember_context(binder, asm):
    """The assembly file the reference was made in (its -> / ->? mark)."""
    if "FwContext" not in binder.PropertiesList:
        binder.addProperty("App::PropertyString", "FwContext", "FreeCAD", "The assembly this reference was made in")
        binder.setEditorMode("FwContext", 2)
    binder.FwContext = asm.Document.FileName or ""


def in_context_items(sketch, obj, name, detach=True):
    """Convert Entities on another component while a part is edited in context: FreeCAD lets a
    sketch reference only its own body, so the pick goes through a reference (SubShapeBinder)
    and its edges are converted. [(binder, EdgeN)] or None when obj is no other component."""
    asm = ac.assembly_of(obj.Document)
    if asm is None or obj not in ac.components(asm):
        return None
    body = sketch.getParentGeoFeatureGroup()
    if body is None or body.TypeId != "PartDesign::Body":
        return None
    # through the assembly would loop (the assembly holds this part): the binder takes the other
    # part itself and is placed where the assembly has it (follow_binders after each solve)
    from . import asmrefopts
    target = obj.getLinkedObject(True) if obj.TypeId == "App::Link" else obj
    binder = body.newObject("PartDesign::SubShapeBinder", "Binder")
    binder.Support = [(target, [name])]
    binder.Relative = True      # an edge or face: placed by follow_binders (not relative it lands off on a tilted part)
    _own_context(binder)
    binder.Label = "Reference (%s)" % obj.Label
    for prop, typ in (("FwInContext", "App::PropertyBool"), ("FwRefComp", "App::PropertyString")):
        binder.addProperty(typ, prop, "FreeCAD", "In-context reference")
        binder.setEditorMode(prop, 2)
    binder.FwInContext, binder.FwRefComp = True, obj.Name
    binder.addProperty("App::PropertyString", "FwRefLabel", "FreeCAD", "The component referenced")
    binder.setEditorMode("FwRefLabel", 2)
    binder.FwRefLabel = obj.Label
    _remember_context(binder, asm)
    if binder.ViewObject is not None:
        binder.ViewObject.Visibility = False
        binder.ViewObject.ShowInTree = False
    if not asmrefopts.on(asmrefopts.ALLOW_EXTERNAL):
        binder.addProperty("App::PropertyBool", "FwNoReference", "FreeCAD", "A copy, not an external reference")
        binder.FwNoReference = True
    body.Document.recompute()
    follow_binders(asm)
    if detach and getattr(binder, "FwNoReference", False):
        binder.BindMode = "Detached"        # a copy: FreeCAD drops the support when detached
    edges = binder.Shape.Edges
    if name.startswith("Vertex"):
        return [(binder, "Vertex1")]
    return [(binder, "Edge%d" % (i + 1)) for i in range(len(edges))]


def _same_edge(a, b):
    try:
        if a.isSame(b):
            return True
        if abs(a.Length - b.Length) > 1e-6 or len(a.Vertexes) != len(b.Vertexes):
            return False
        return a.CenterOfMass.isEqual(b.CenterOfMass, 1e-6) and \
            all(any(v.Point.isEqual(w.Point, 1e-6) for w in b.Vertexes) for v in a.Vertexes)
    except Exception:
        return False


def in_context_many(sketch, items):
    ""



    groups, order = {}, []
    for obj, name in items:
        try:
            asm = ac.assembly_of(obj.Document)
            ok = asm is not None and obj in ac.components(asm) and name.startswith(("Edge", "Face", "Vertex"))
        except Exception:
            ok = False
        if ok:
            if obj.Name not in groups:
                groups[obj.Name] = (obj, [])
                order.append(obj.Name)
            groups[obj.Name][1].append(name)
    if not groups:
        return None
    done = {}
    for key in order:
        obj, names = groups[key]
        first = in_context_items(sketch, obj, names[0], detach=False)   # the rest go on it first
        if not first:
            return None
        binder = first[0][0]
        got = {names[0]: [binder.Shape.getElement(n) for _b, n in first]}
        target = obj.getLinkedObject(True) if obj.TypeId == "App::Link" else obj
        for name in names[1:]:
            before = list(binder.Shape.Edges)
            nv = list(binder.Shape.Vertexes)
            sup = [(o, list(subs)) for o, subs in binder.Support]
            for o, subs in sup:
                if o is target and name not in subs:
                    subs.append(name)
            mode = binder.BindMode
            if mode == "Detached":
                binder.BindMode = "Synchronized"
            binder.Support = sup
            binder.touch()
            binder.recompute()
            if mode == "Detached":
                binder.BindMode = "Detached"
            if name.startswith("Vertex"):
                got[name] = [v for v in binder.Shape.Vertexes if not any(v.Point.isEqual(w.Point, 1e-6) for w in nv)][:1]
            else:
                got[name] = [e for e in binder.Shape.Edges if not any(_same_edge(e, b) for b in before)]
        binder.Document.recompute()
        if getattr(binder, "FwNoReference", False):
            binder.BindMode = "Detached"    # No External References: kept as a copy
        edges, verts = binder.Shape.Edges, binder.Shape.Vertexes
        for name, shapes in got.items():
            out = []
            for sh in shapes:
                if sh.ShapeType == "Vertex":
                    k = next((i for i, v in enumerate(verts) if v.Point.isEqual(sh.Point, 1e-6)), None)
                    if k is not None:
                        out.append((binder, "Vertex%d" % (k + 1)))
                else:
                    k = next((i for i, e in enumerate(edges) if _same_edge(e, sh)), None)
                    if k is not None:
                        out.append((binder, "Edge%d" % (k + 1)))
            done[(key, name)] = out
    try:
        follow_binders(ac.assembly_of(obj.Document))
    except Exception as error:
        App.Console.PrintLog("FreeCAD: in-context reference: %s\n" % error)
    result = []
    for obj, name in items:
        if (obj.Name, name) in done:
            result += done[(obj.Name, name)]
        else:
            result.append((obj, name))
    return result


def toolbar_sketch():
    ""


    from . import asmmenu, asmtools
    ed = asmtools.editing()
    if not ed:
        return None
    sels = Gui.Selection.getSelectionEx("", 0)
    picks = [(s.Object, sub) for s in sels for sub in (s.SubElementNames or [])]
    if len(picks) != 1:
        return None
    ref = ac.reference(ed[0], picks[0][0], picks[0][1]) if picks[0][1] else None
    if ref is None or ref[0] is ed[1] or not ref[1].split(".")[-1].startswith("Face"):
        return None
    run = dict((i[0], i) for i in asmmenu._in_context_items(ref[0])).get("InContextSketch")
    return run[2]() if run else None


class ExternalRefsDialog(QtWidgets.QDialog):
    ""

    def __init__(self, doc, title=None, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        OPEN.append(self)
        self.doc = doc
        self.setObjectName("FW_ExternalReferences")
        self.setWindowTitle(title or "External References For: %s" % doc.Label)
        lay = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTreeWidget()
        self.table.setObjectName("FW_ExternalRefsList")

        self.assembly = QtWidgets.QLabel("")
        self.assembly.setObjectName("FW_ExternalRefsAssembly")
        lay.addWidget(self.assembly)
        self.table.setHeaderLabels(["Feature", "Data", "Status", "Referenced Entity", "Feature's Component"])
        self.table.setRootIsDecorated(False)
        lay.addWidget(self.table, 1)
        row = QtWidgets.QHBoxLayout()
        self.list_broken = QtWidgets.QCheckBox("List Broken")
        self.list_broken.setObjectName("FW_ExternalRefsListBroken")
        self.list_broken.toggled.connect(lambda _on: self.fill())
        row.addWidget(self.list_broken)
        self.lock = QtWidgets.QPushButton("Lock All")
        self.lock.setObjectName("FW_ExternalRefsLock")
        self.lock.clicked.connect(self._lock)
        self.brk = QtWidgets.QPushButton("Break All")
        self.brk.setObjectName("FW_ExternalRefsBreak")
        self.brk.clicked.connect(self._break)
        self.ok = QtWidgets.QPushButton("OK")
        self.ok.clicked.connect(self.accept)
        row.addWidget(self.lock)
        row.addWidget(self.brk)
        row.addStretch(1)
        row.addWidget(self.ok)
        lay.addLayout(row)
        self.resize(640, 260)
        self.fill()

    def fill(self):
        self.table.clear()
        rs = rows(self.doc)
        broken = [r for r in rs if r[2] == "Broken"]
        # List Broken: broken references are listed only with it on (shown only when there are some)
        self.list_broken.setVisible(bool(broken))
        for f, data, st, ref, b in rs:
            if st == "Broken" and not self.list_broken.isChecked():
                continue
            self.table.addTopLevelItem(QtWidgets.QTreeWidgetItem([f, data, st, ref, feature_component(b)]))
        for i in range(5):
            self.table.resizeColumnToContents(i)
        path = next((getattr(r[4], "FwContext", "") for r in rs if getattr(r[4], "FwContext", "")), "")
        self.assembly.setText("Assembly: %s" % os.path.basename(path) if path else "")
        self.assembly.setVisible(bool(path))
        locked = rs and all(r[2] == "Locked" for r in rs)
        self.lock.setText("Unlock All" if locked else "Lock All")
        live = [r for r in rs if r[2] != "Broken"]
        self.lock.setVisible(bool(live))        # all broken: nothing left to lock or break
        self.brk.setVisible(bool(live))

    def _lock(self):
        (unlock_all if self.lock.text() == "Unlock All" else lock_all)(self.doc)
        self.fill()
        _refresh()

    def _break(self, ask=True):
        if ask:
            box = QtWidgets.QMessageBox.question(
                self, "External References",
                "Breaking the external references cannot be undone. The features keep their "
                "geometry but stop following the other components. Break all of them?")
            if box != QtWidgets.QMessageBox.Yes:
                return
        break_all(self.doc)
        self.fill()
        _refresh()

    def done(self, r):
        if self in OPEN:
            OPEN.remove(self)
        super().done(r)


def _refresh():
    try:
        from . import asmui
        asmui.refresh()
    except Exception as _fw_err:
        _fw_log("asmextref.py:362", _fw_err)


def list_external_references(comp_or_doc):
    doc = comp_or_doc
    if not isinstance(comp_or_doc, App.Document):
        body = _body_of(comp_or_doc)
        doc = body.Document if body is not None else comp_or_doc.Document
    prune(doc)
    box = ExternalRefsDialog(doc)
    box.open()
    return box


HOLDER_PROP = "FwRefHolder"     # the instance the reference was made in


def context_of(doc, target=None):
    """The assembly file the part's in-context references (target's, when given) were made in."""
    refs = binders(doc)
    if target is not None and not isinstance(target, App.Document):
        deps = set(o.Name for o in target.OutListRecursive) | {target.Name}
        refs = [b for b in refs if b.Name in deps] or refs
    import os
    for b in refs:
        path = getattr(b, "FwContext", "") or ""
        if path and os.path.exists(path):
            return path, b
    return None, None


def edit_in_context(doc, target=None):
    ""


    import os
    path, binder = context_of(doc, target)
    if not path:
        return None
    want = os.path.normcase(os.path.abspath(path))
    adoc = next((d for d in App.listDocuments().values()
                 if d.FileName and os.path.normcase(os.path.abspath(d.FileName)) == want), None)
    if adoc is None:
        adoc = App.openDocument(path)
    asm = ac.assembly_of(adoc)
    if asm is None:
        return None
    body = next((o for o in doc.Objects if o.TypeId == "PartDesign::Body" and binder in o.Group), None)
    comp = _holder(asm, binder, body) if body is not None else None
    if comp is None:
        comp = next((c for c in ac.components(asm) if getattr(c.getLinkedObject(True), "Document", None) is doc), None)
    if comp is None:
        return None
    def front():
        """The assembly's window on top (the part files it loads open windows of their own)."""
        try:
            gdoc = Gui.getDocument(adoc.Name)
            views = gdoc.mdiViewsOfType("Gui::View3DInventor") if gdoc is not None else []
            if views:
                Gui.getMainWindow().setActiveWindow(views[0])
            Gui.setActiveDocument(adoc.Name)
        except Exception as _fw_err:
            _fw_log("asmextref.py:edit in context front", _fw_err)
    try:
        front()
        from . import asmui, asmtools
        asmui.activate(asm)
        asmtools.edit_component(asm, comp)
        front()
        for ms in (300, 1000):
            QtCore.QTimer.singleShot(ms, front)
    except Exception as error:
        _fw_log("asmextref.py:edit in context", error)
        return None
    return comp


def _holder(asm, binder, body):
    ""


    comps = ac.components(asm)
    want = getattr(binder, HOLDER_PROP, "")
    if want:
        got = asm.Document.getObject(want)
        if got is not None and got in comps:
            return got
    holder = next((c for c in comps if c.getLinkedObject(True) is body or _part_of(c) is body
                   or getattr(c, "LinkedObject", None) is body), None)
    if holder is not None and not want:
        try:
            binder.addProperty("App::PropertyString", HOLDER_PROP, "FreeCAD", "The instance the reference was made in")
            binder.setEditorMode(HOLDER_PROP, 2)
            setattr(binder, HOLDER_PROP, holder.Name)
        except Exception as _fw_err:
            _fw_log("asmextref.py:397", _fw_err)
    return holder


def freeze_references(features, on):
    ""

    out = []
    for f in features:
        for b in [f] + list(getattr(f, "OutList", []) or []):
            if b.TypeId != "PartDesign::SubShapeBinder" or not getattr(b, "FwInContext", False):
                continue
            mode = getattr(b, "BindMode", "Synchronized")
            if on and mode == "Synchronized":
                if "FwFreezeLocked" not in b.PropertiesList:
                    b.addProperty("App::PropertyBool", "FwFreezeLocked", "FreeCAD", "Locked by the Freeze bar")
                    b.setEditorMode("FwFreezeLocked", 2)
                b.FwFreezeLocked = True
                b.BindMode = "Frozen"
                out.append(b)
            elif not on and mode == "Frozen" and getattr(b, "FwFreezeLocked", False):
                b.FwFreezeLocked = False
                b.BindMode = "Synchronized"
                out.append(b)
    return out


def install_freeze():
    install_mend()
    _install_freeze()


def _install_freeze():
    """freezebar.freeze_to: the references of the features it freezes are locked, and unlocked again
    when it thaws them (only the ones the Freeze bar locked)."""
    try:
        from . import freezebar
    except Exception:
        return
    if getattr(freezebar, "_fw_extref", False):
        return
    freeze0 = freezebar.freeze_to

    def freeze_to(feature, body=None):
        b = body or (freezebar.body_of(feature) if feature is not None else None)
        before = {o.Name: freezebar.frozen(o) for o in (freezebar.features(b) if b is not None else [])}
        done = freeze0(feature, body)
        if done and b is not None:
            try:
                items = freezebar.features(b)
                now = [o for o in items if freezebar.frozen(o) and not before.get(o.Name)]
                gone = [o for o in items if not freezebar.frozen(o) and before.get(o.Name)]
                if freeze_references(now, True) + freeze_references(gone, False):
                    b.Document.recompute()
            except Exception as error:
                App.Console.PrintLog("FreeCAD: freeze references: %s\n" % error)
        return done
    freeze_to.__wrapped__ = freeze0
    freezebar.freeze_to = freeze_to
    freezebar._fw_extref = True


STAMP_PROP = "FwSrcStamp"


def source_stamp(binder):
    """What the reference reads, in short: each referenced element's size and place in its own part
    (a changed block gives another stamp)."""
    out = []
    try:
        for obj, subs in binder.Support or []:
            for sub in subs or [""]:
                shp = obj.getSubObject(sub) if sub else obj.Shape
                if shp is None or shp.isNull():
                    out.append("none")
                    continue
                bb = shp.BoundBox
                out.append("%.6g %.6g %.6g %.6g %.6g %.6g %.6g %.6g" % (
                    bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax,
                    getattr(shp, "Length", 0.0), getattr(shp, "Area", 0.0)))
    except Exception:
        return ""
    return "|".join(out)


def _stamp(binder, value):
    if STAMP_PROP not in binder.PropertiesList:
        binder.addProperty("App::PropertyString", STAMP_PROP, "FreeCAD", "What the reference read last")
        binder.setEditorMode(STAMP_PROP, 2)
    if binder.FwSrcStamp != value:
        binder.FwSrcStamp = value


def _size(shape):
    return (round(getattr(shape, "Length", 0.0), 6), round(getattr(shape, "Area", 0.0), 6),
            round(getattr(shape, "Volume", 0.0), 6))


def _caught_up(binder):
    """The reference's own shape is the size of what it refers to (a reference not yet rebuilt
    after its part changed is not)."""
    total = [0.0, 0.0, 0.0]
    for obj, subs in binder.Support or []:
        for sub in subs or [""]:
            shp = obj.getSubObject(sub) if sub else obj.Shape
            if shp is None or shp.isNull():
                return False
            for i, v in enumerate(_size(shp)):
                total[i] += v
    mine = _size(binder.Shape)
    return all(abs(a - b) <= 1e-6 * max(1.0, abs(a)) for a, b in zip(total, mine))


REFS_PROP = "FwExtRefs"


def _ref_sketches(doc):
    """The sketches of doc that use in-context references."""
    out = []
    for sk in doc.Objects:
        if sk.TypeId != "Sketcher::SketchObject":
            continue
        try:
            if any(getattr(o, "FwRefComp", "") for o, _ in sk.ExternalGeometry or []) or REFS_PROP in sk.PropertiesList:
                out.append(sk)
        except Exception:
            pass
    return out


def _refs_of(sk):
    return [[o.Name, list(subs)] for o, subs in sk.ExternalGeometry or []]


def _dropped(sk):
    """FreeCAD lost a reference, not the user: a missing element (?Edge1), or fewer references
    than the converted geometry it still holds (deleting a converted edge removes both)."""
    refs = _refs_of(sk)
    if any(str(s).startswith("?") for _, subs in refs for s in subs):
        return True
    try:
        return len(sk.ExternalGeo) > 2 + sum(len(subs) for _, subs in refs)
    except Exception as _fw_err:
        _fw_log("asmextref.py:536", _fw_err)
        return False


def _defining(sk):
    """'Object.Edge1' -> True for each reference kept as a defining (drawn) one."""
    out = {}
    try:
        import Sketcher
        for g in list(sk.ExternalGeo)[2:]:
            f = Sketcher.ExternalGeometryFacade(g)
            if f.Ref:
                out[f.Ref] = bool(f.testFlag("Defining"))
    except Exception:
        pass
    return out


def _relink(sk, objs, want):
    """The sketch's references made again in their order, with the relations on them (Python
    cannot set ExternalGeometry; removing a reference removes its relations)."""
    keep = [c for c in sk.Constraints      # -3 and below are references; -2000 is "none"
            if any(-2000 < getattr(c, k, 0) <= -3 for k in ("First", "Second", "Third"))]
    sk.delConstraintsToExternal()
    for _ in range(len(sk.ExternalGeo)):
        if len(sk.ExternalGeo) <= 2 and not sk.ExternalGeometry:
            break
        try:
            sk.delExternal(0)
        except Exception:
            break
    for o, w in zip(objs, want):
        flags = w[3] if len(w) > 3 else []
        for i, sub in enumerate(w[1]):
            sk.addExternal(o.Name, sub, bool(flags[i]) if i < len(flags) else False)
    for c in keep:
        sk.addConstraint(c)


def _remember_refs(doc):
    """Each in-context sketch keeps the list of what it converts (FreeCAD drops a converted edge
    when its reference is rebuilt with a part that changed while the file was closed)."""
    import json
    for sk in _ref_sketches(doc):
        refs = _refs_of(sk)
        if not refs or _dropped(sk):
            continue        # a reference already lost: keep the last good list
        defining = _defining(sk)
        text = json.dumps([[n, subs, sk.Document.getObject(n).Label,
                            [defining.get("%s.%s" % (n, x), False) for x in subs]] for n, subs in refs])
        if REFS_PROP not in sk.PropertiesList:
            sk.addProperty("App::PropertyString", REFS_PROP, "FreeCAD", "The in-context references it converts")
            sk.setEditorMode(REFS_PROP, 2)
        if sk.FwExtRefs != text:
            sk.FwExtRefs = text


def _mend_attachments(doc):
    ""



    mended = []
    for o in doc.Objects:
        try:
            sup = o.AttachmentSupport if "AttachmentSupport" in o.PropertiesList else None
        except Exception:
            continue
        if not sup:
            continue
        new, changed = [], False
        for item in sup:
            obj = item[0]
            subs = item[1] if len(item) > 1 else ()
            subs = [subs] if isinstance(subs, str) else list(subs or ())
            if obj is not None and obj.TypeId == "PartDesign::SubShapeBinder" and getattr(obj, "FwInContext", False):
                fixed = []
                for sub in subs:
                    plain = str(sub).split(".")[-1]
                    if str(sub).startswith("?") and plain:
                        try:
                            obj.Shape.getElement(plain)
                        except Exception:
                            fixed.append(sub)
                            continue
                        fixed.append(plain)
                        changed = True
                    else:
                        fixed.append(sub)
                subs = fixed
            new.append((obj, tuple(subs)))
        if changed:
            try:
                o.AttachmentSupport = new
                o.touch()
                mended.append(o)
            except Exception as error:
                App.Console.PrintLog("FreeCAD: in-context sketch %s: %s\n" % (o.Name, error))
    return mended


def _has_refs(asm):
    """asm's parts (or the assembly file itself) hold in-context references that follow a component."""
    try:
        docs = [asm.Document] + [d for d in _ref_docs(asm) if d is not asm.Document]
    except Exception:
        return False
    for d in docs:
        try:
            if any(getattr(o, "FwRefComp", "") for o in d.findObjects("PartDesign::SubShapeBinder")):
                return True
        except Exception:
            continue
    return False


class _MendWatch:
    """After a rebuild: sketches on in-context faces that lost their face (mend_attachments) put back
    and the document rebuilt once more, after the rebuild that lost them has finished."""

    def __init__(self):
        self.busy = set()
        self.following = set()

    def slotRecomputedDocument(self, doc):
        name = doc.Name
        if name in self.busy:
            return
        if name not in self.following:
            try:
                asm = ac.assembly_of(doc)
                if asm is not None and _has_refs(asm):
                    # a component moved (placed, dragged, solved): the references made in context follow it, as
                    # the reference through the assembly did; the parts' own rebuild then picks them up
                    self.following.add(name)
                    try:
                        follow_binders(asm)
                    finally:
                        self.following.discard(name)
                    self._catch_up(asm)
            except Exception as _fw_err:
                _fw_log("asmextref.py:follow on rebuild", _fw_err)
        try:
            if not any(o.TypeId == "PartDesign::SubShapeBinder" and getattr(o, "FwInContext", False) for o in doc.Objects):
                return
            if not _mend_attachments(doc):
                return
        except Exception as _fw_err:
            _fw_log("asmextref.py:mend", _fw_err)
            return

        def again():
            d = App.listDocuments().get(name)
            if d is None:
                return
            self.busy.add(name)
            try:
                d.recompute()
            finally:
                self.busy.discard(name)
        QtCore.QTimer.singleShot(0, again)


def _touched(d):
    try:
        return any("Touched" in o.State for o in d.Objects)
    except Exception:
        return False


def _catch_up_parts(watch, asm):
    """After the references followed (the parts' references moved, or noted what they read): the parts
    rebuilt, then the assembly once more, so one rebuild leaves nothing needing a rebuild (the assembly's
    components saw their parts change after it had rebuilt)."""
    doc = asm.Document
    parts = []
    for c in ac.components(asm):
        try:
            d = _part_of(c).Document
        except Exception:
            continue
        if d is not doc and d not in parts and _touched(d):
            parts.append(d)
    if not parts:
        return

    def again():
        names = [d.Name for d in parts if d.Name in App.listDocuments()] + [doc.Name]
        watch.following.update(names)
        try:
            for n in names:
                d = App.listDocuments().get(n)
                if d is not None and (n == doc.Name or _touched(d)):
                    d.recompute()
            d = App.listDocuments().get(doc.Name)
            if d is not None and _touched(d):
                d.recompute()
        finally:
            for n in names:
                watch.following.discard(n)
    QtCore.QTimer.singleShot(0, again)


_MendWatch._catch_up = lambda self, asm: _catch_up_parts(self, asm)

_MEND = []


def install_mend():
    if not _MEND:
        _MEND.append(_MendWatch())
        App.addDocumentObserver(_MEND[0])


def _restore_refs(doc):
    """The converted edges FreeCAD dropped (or marked missing) put back on their references."""
    import json
    mended = list(_mend_attachments(doc))
    for sk in _ref_sketches(doc):
        try:
            want = json.loads(getattr(sk, REFS_PROP, "") or "[]")
        except Exception:
            continue
        if not want or _refs_of(sk) == [w[:2] for w in want] or not _dropped(sk):
            continue
        objs = [doc.getObject(w[0]) for w in want]
        if any(o is None or (len(w) > 2 and o.Label != w[2]) for o, w in zip(objs, want)):
            continue        # not the objects it was kept for (a copy renamed them)
        try:
            _relink(sk, objs, want)
            sk.touch()
            mended.append(sk)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: in-context sketch %s: %s\n" % (sk.Name, error))
    return mended


def _ref_docs(asm):
    out = []
    for c in ac.components(asm):
        try:
            d = _part_of(c).Document
        except Exception:
            continue
        if d not in out:
            out.append(d)
    return out


def rebind(asm, binders=None):
    """In-context references rebuilt on their own first, then the sketches on them linked again,
    before the parts rebuild: FreeCAD names a rebuilt reference's edge anew when its part changed
    while closed, and would drop the converted edge (and ask Stop and Repair about the sketch)."""
    mended = set()
    for d in _ref_docs(asm):
        for b in d.Objects:
            if b.TypeId != "PartDesign::SubShapeBinder" or not getattr(b, "FwRefComp", ""):
                continue
            if getattr(b, "BindMode", "Synchronized") != "Synchronized":
                continue
            if binders is not None and b not in binders:
                continue
            try:
                if binders is not None or "Touched" in b.State or not _caught_up(b):
                    b.touch()
                    b.recompute()
            except Exception:
                pass
        try:
            if _restore_refs(d):
                mended.add(d)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: in-context sketches: %s\n" % error)
    return mended


def refresh_stale(asm):
    ""


    docs, ref_docs, stale = set(), set(), []
    for c in ac.components(asm):
        try:
            d = _part_of(c).Document
        except Exception:
            continue
        for b in d.Objects:
            if b.TypeId != "PartDesign::SubShapeBinder" or not getattr(b, "FwRefComp", ""):
                continue
            if getattr(b, "BindMode", "Synchronized") != "Synchronized" or getattr(b, "FwNoReference", False):
                continue
            now = source_stamp(b)
            ref_docs.add(d)
            if now and (getattr(b, STAMP_PROP, None) != now or not _caught_up(b)):
                stale.append(b)
                docs.add(d)
    if stale:
        rebind(asm, stale)
    for d in docs:
        try:
            d.recompute()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: in-context references on open: %s\n" % error)
    for d in ref_docs:
        if _restore_refs(d):        # an earlier rebuild of the opening file can drop them too
            docs.add(d)
            try:
                d.recompute()
            except Exception as error:
                App.Console.PrintLog("FreeCAD: in-context references on open: %s\n" % error)
    if docs:
        follow_binders(asm)
        for d in docs:
            d.recompute()
    return len(docs)


def _own_context(binder):
    """A relative reference is relative to its own body: follow_binders places it where the
    assembly has the other part. FreeCAD fills in the assembly being edited as its context, which
    moves it a second time (by this part's place in the assembly) and makes the part's file load
    the assembly that loads the part."""
    try:
        body = binder.getParentGeoFeatureGroup()
        ctx = binder.Context
        if body is not None and (ctx is None or ctx[0] is not body):
            binder.Context = (body, binder.Name + ".")
    except Exception as _fw_err:
        _fw_log("asmextref.py:own context", _fw_err)


def _binds_elements(binder):
    try:
        return any(sub for _o, subs in (binder.Support or []) for sub in (subs or []))
    except Exception:
        return False


def follow_binders(asm):
    """In-context references made by Convert Entities: each placed, in its part, where the
    assembly has the other component now."""
    doc = asm.Document
    docs = [doc]
    for c in ac.components(asm):        # the references live in the parts' own files
        try:
            d = _part_of(c).Document
        except Exception as _fw_err:
            _fw_log("asmextref.py:705", _fw_err)
            continue
        if d not in docs:
            docs.append(d)
    for b in [o for d in docs for o in d.Objects]:
        name = getattr(b, "FwRefComp", "")
        if not name or b.TypeId != "PartDesign::SubShapeBinder":
            continue
        if getattr(b, "BindMode", "Synchronized") != "Synchronized":
            continue        # locked or broken: it stays where it was
        other = doc.getObject(name)
        body = b.getParentGeoFeatureGroup()
        holder = _holder(asm, b, body)
        if other is None or holder is None:
            continue
        target = _part_of(other)
        own = getattr(target, "Placement", App.Placement())
        want = holder.Placement.inverse().multiply(other.Placement).multiply(own.inverse())
        if not b.Relative and _binds_elements(b):
            b.Relative = True       # made before: a face or edge bound not relative sat off on a moved or tilted part
        _own_context(b)
        if not b.Placement.isSame(want, 1e-9):
            b.Placement = want
        note_context(b, asm)
        try:
            if _caught_up(b):
                _stamp(b, source_stamp(b))      # only what the reference has really read
        except Exception:
            pass
    for d in docs[1:]:
        try:
            # a reference rebuilt in a copied file (Save As with references) names its edges anew

            # keeps the converted entities
            if _restore_refs(d):
                d.recompute()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: in-context sketches: %s\n" % error)
        try:
            _remember_refs(d)
        except Exception:
            pass
