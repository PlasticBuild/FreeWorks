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
import Part
from PySide import QtCore, QtWidgets

from . import naming, pmboxes


def _error_css():
    ""
    try:
        from . import propertymanager
        return propertymanager.error_css()
    except Exception:
        return "color: #c00000;"

SPECS = {}
WHOLE = ("Object", "Feature")     # picks of whole objects; "Object" turns a feature into its body


def _surface_only(obj):
    """True for an object whose shape is surfaces only (faces, no solid)."""
    try:
        shape = obj.Shape
        return bool(shape.Faces) and not shape.Solids
    except Exception:
        return False


_fw_incontext = True        # in-context picks are built in (below): asmincontext.install() leaves this module as it is


def _context():
    """(assembly, component being edited, its body) while a part is edited in an assembly, else None."""
    try:
        from . import asmincontext
        return asmincontext._context()
    except Exception as _fw_err:
        _fw_log("simplefeature.py:49", _fw_err)
        return None


def _map_pick(obj, sub):
    """A component picked in the assembly, as a reference in the edited part (or obj itself)."""
    try:
        from . import asmincontext
        return asmincontext.map_pick(obj, sub)
    except Exception as _fw_err:
        _fw_log("simplefeature.py:59", _fw_err)
        return obj


def _open_in_context(ctx, obj):
    from . import asmincontext
    return asmincontext.open_edit(ctx[0], ctx[1], obj)


class Field:
    ""









    def __init__(self, name, kind, label, default=None, tip="", values=None, what=("Face",), many=False,
                 low=None, high=None, shown=None, box=None, optional=False, icons=None, action=None, legacy=None,
                 flip=False, group=False):

        self.flip = flip
        # group: loose edges that chain into one curve show as one SelectionManager row,

        self.group = group
        self.name, self.kind, self.label, self.default, self.tip = name, kind, label, default, tip
        # the value a property added to a feature from an older file starts at (None: the default),
        # so a new row leaves old parts as they were
        self.legacy = legacy
        self.action = action
        self.optional = optional
        self.icons = icons or {}
        self.values, self.what, self.many = values or [], what, many
        self.low, self.high, self.shown, self.box = low, high, shown, box

    PROPERTY = {"int": "App::PropertyInteger", "text": "App::PropertyString", "info": "App::PropertyString", "length": "App::PropertyLength", "distance": "App::PropertyDistance", "float": "App::PropertyFloat",
                "angle": "App::PropertyAngle", "bool": "App::PropertyBool", "enum": "App::PropertyEnumeration",
                "icons": "App::PropertyEnumeration", "radio": "App::PropertyEnumeration",
                "vector": "App::PropertyVector"}

    def property(self):
        if self.kind == "pick":
            # Global: tools may live outside the body (another body, a surface, a datum)
            return "App::PropertyLinkSubListGlobal" if self.what not in WHOLE else (
                "App::PropertyLinkListGlobal" if self.many else "App::PropertyLinkGlobal")
        return self.PROPERTY[self.kind]


class Spec:
    def __init__(self, command, title, label, tip, icon, pixmap, fields, compute, subtractive=False,
                 first_pick=None, needs_body=True, refine=True, panel=None, cache=False):
        self.command, self.title, self.label, self.tip = command, title, label, tip
        self.icon, self.pixmap, self.fields, self.compute = icon, pixmap, fields, compute
        self.subtractive, self.first_pick, self.needs_body = subtractive, first_pick, needs_body
        self.refine = refine           # False keeps split faces (Split Line)
        self.panel = panel             # a Panel subclass for a page that needs more than the fields
        self.cache = cache             # slow features keep results for unchanged inputs (fcache)
        self.internal = "".join(title.split())
        SPECS[self.internal] = self

    @property
    def type(self):
        return "PartDesign::FeatureSubtractivePython" if self.subtractive else "PartDesign::FeatureAdditivePython"


def elements(obj, field):
    """[(object, shape element)] of a pick field."""
    value = getattr(obj, field, None)
    out = []
    if not value:
        return out
    if isinstance(value, App.DocumentObject):
        return [(value, Part.getShape(value))]
    for item in value:
        if isinstance(item, App.DocumentObject):
            out.append((item, Part.getShape(item)))
            continue
        source, subs = item
        subs = subs if isinstance(subs, (list, tuple)) else [subs]
        for sub in subs:
            shape = Part.getShape(source)
            out.append((source, _element(source, shape, sub) if sub else shape))
    return out


def put_value(obj, name, value):
    ""


    try:
        from . import configs, configmanager as cm
        if any(p == name for p, _e in obj.ExpressionEngine) and configs.configured(obj, name):
            t = cm.table(obj.Document)
            new = configs._number(value)
            if configs._number(getattr(obj, name)) != new:
                configs.set_cell(t, configs._alias_for(obj, name), new, [t.active()])
            return
    except Exception as _fw_err:
        _fw_log("simplefeature.py:configured value", _fw_err)
    setattr(obj, name, value)


def _element(source, shape, sub):
    ""


    try:
        return shape.getElement(sub)
    except Exception:
        name = sub.split(".")[-1].lstrip("?")
        if name == sub:
            raise
        _fw_log("simplefeature.py:lost pick", "%s: %s used as %s" % (source.Name, sub, name))
        return shape.getElement(name)


def _valid(shape):
    """Shape.isValid() takes most of a second on a big result (a 200-instance pattern): there only
    the solids' volumes are checked, which a broken boolean fails too."""
    if len(shape.Faces) <= 300:
        return shape.isValid()
    try:
        solids = shape.Solids
        return bool(solids) and all(s.Volume > 1e-12 for s in solids)
    except Exception:
        return False


def _base_valid(base):
    try:
        return base is None or base.isNull() or _valid(base)
    except Exception:
        return True


def store(obj, shape, tool=None):
    """Sets a PartDesign Python feature's Shape and AddSubShape from shapes in global coordinates.

    FreeCAD gives a feature's Shape the feature's Placement, so a shape that carries its own
    (the part so far after a Pad on the Front plane, or a moved primitive) would be moved or
    turned. The feature takes the shape's Placement instead, as PartDesign's own features do,
    and AddSubShape is kept in the feature's coordinates (global = Placement * AddSubShape)."""
    place = shape.Placement if shape is not None and not shape.isNull() else App.Placement()
    obj.Placement = place
    if tool is None or tool.isNull():
        obj.AddSubShape = Part.Shape()
    else:
        local = tool.copy()
        local.Placement = place.inverse().multiply(tool.Placement)
        obj.AddSubShape = local
    obj.Shape = shape


class Feature:
    def __init__(self, obj, spec):
        obj.addProperty("App::PropertyString", "SWStyleKind", "Base", "Which FreeCAD feature this is")
        obj.SWStyleKind = spec.internal
        obj.setEditorMode("SWStyleKind", 2)
        self.setup(obj)
        obj.Proxy = self

    def spec(self, obj):
        return SPECS[obj.SWStyleKind]

    def setup(self, obj, restoring=False):
        spec = self.spec(obj)
        for field in spec.fields:
            if field.kind == "button":
                continue
            if field.name not in obj.PropertiesList:
                obj.addProperty(field.property(), field.name, spec.title, field.tip or field.label)
                # legacy: the value an older file's feature gets (a function of the feature, or a value)
                legacy = field.legacy(obj) if callable(field.legacy) else field.legacy
                if field.kind in ("enum", "icons", "radio"):
                    setattr(obj, field.name, field.values)
                    if restoring and legacy in field.values:
                        setattr(obj, field.name, legacy)
                    elif field.default in field.values:
                        setattr(obj, field.name, field.default)
                elif restoring and legacy is not None:
                    setattr(obj, field.name, legacy)
                elif field.default is not None:
                    setattr(obj, field.name, field.default)
            elif field.kind in ("enum", "icons", "radio"):
                current = getattr(obj, field.name)
                setattr(obj, field.name, field.values)
                if current in field.values:
                    setattr(obj, field.name, current)

    def execute(self, obj):
        base = obj.BaseFeature.Shape if obj.BaseFeature is not None else Part.Shape()
        spec = self.spec(obj)
        if spec.needs_body and (base is None or base.isNull()):
            raise RuntimeError("%s needs a part" % spec.title)
        from . import pickwait
        try:
            ckey = None
            if spec.cache:
                from . import fcache
                ckey = fcache.key(obj, base)
                hit = fcache.get(ckey)
            if ckey is not None and hit is not None:
                result, tool = hit
            else:
                result, tool = spec.compute(obj, base)
                if ckey is not None and result is not None:
                    # keyed on the inputs as the build leaves them (a build may set a property)
                    fcache.put(fcache.key(obj, base), result, tool)
        except Exception as error:
            if not pickwait.waits(obj, error):
                _why_failed[_key(obj)] = str(error)
                raise
            store(obj, base if base is not None else Part.Shape())    # the PM waits for its picks
            return
        pickwait.done(obj)
        _why_failed.pop(_key(obj), None)
        if result is None:
            store(obj, base)
            return
        if not result.isNull() and spec.refine:
            try:
                result = result.removeSplitter()
            except Exception as _fw_err:
                _fw_log("simplefeature.py:242", _fw_err)
        if result.isNull() or (not _valid(result) and _base_valid(base)):
            # a part that came in already broken (FreeCAD's Shell leaves some so) is not this

            raise RuntimeError("%s could not be made with these settings" % spec.title)
        solids = result.Solids
        store(obj, solids[0] if len(solids) == 1 else (Part.makeCompound(solids) if solids else result), tool)

    def onDocumentRestored(self, obj):
        self.setup(obj, restoring=True)
        obj.Proxy = self

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _owner(view):
    """The object whose view provider is view (None when FreeCAD has not made it yet)."""
    for doc in App.listDocuments().values():
        for o in doc.Objects:
            try:
                if getattr(o, "SWStyleKind", "") in SPECS and o.ViewObject is not None and o.ViewObject.Proxy is view:
                    return o
            except Exception as _fw_err:
                _fw_log("simplefeature.py:267", _fw_err)
    return None


class View:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def _spec(self, vobj=None):
        # FreeCAD may ask for the icon before attach() has run, and a view put back on a clean-saved
        # file never gets attach(): find the object this view belongs to
        if getattr(self, "Object", None) is None:
            if vobj is not None:
                self.Object = vobj.Object
            else:
                self.Object = _owner(self)
        return SPECS.get(getattr(getattr(self, "Object", None), "SWStyleKind", ""))

    def getIcon(self):
        spec = self._spec()
        if spec is None:
            return ""
        try:
            from . import icons
            icon = icons.family(spec.icon)
            if not icon.isNull():
                return icon         # a QIcon: FreeCAD reads a returned QPixmap as a QIcon
        except Exception as _fw_err:
            _fw_log("simplefeature.py:298", _fw_err)
        return ":/icons/%s.svg" % spec.pixmap

    def claimChildren(self):
        return []

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        spec = self._spec(vobj)
        Gui.Control.showDialog(((spec and spec.panel) or Panel)(vobj.Object))
        return True

    def unsetEdit(self, vobj, mode=0):
        Gui.Control.closeDialog()
        return True

    def doubleClicked(self, vobj):
        ctx = _context()
        obj = vobj.Object
        if ctx is not None and obj.Document is ctx[2].Document and obj.Document is not App.ActiveDocument:
            return _open_in_context(ctx, obj)      # a part edited in the assembly: its PM opens through the component
        Gui.ActiveDocument.setEdit(obj.Name)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


_LINES = ("App::Line", "PartDesign::Line")
_PLANES = ("App::Plane", "PartDesign::Plane")


def _under_preview(obj, element):
    """(input object, element) with the same edge or face as element of obj's shape, from what obj is built on."""
    try:
        el = obj.Shape.getElement(element)
        if el.ShapeType not in ("Edge", "Face"):
            return None

        def key(x):
            if x.ShapeType == "Edge":
                mid = x.valueAt(x.FirstParameter + (x.LastParameter - x.FirstParameter) / 2)
                return (round(x.Length, 5), tuple(sorted((round(v.Point.x, 4), round(v.Point.y, 4), round(v.Point.z, 4))
                                                        for v in x.Vertexes)), (round(mid.x, 4), round(mid.y, 4), round(mid.z, 4)))
            c = x.CenterOfMass
            return (round(x.Area, 5), (round(c.x, 4), round(c.y, 4), round(c.z, 4)))
        want = key(el)
        for o in obj.OutListRecursive:
            shape = getattr(o, "Shape", None)
            if o is obj or shape is None or shape.isNull():
                continue
            items = shape.Edges if el.ShapeType == "Edge" else shape.Faces
            for i, x in enumerate(items, 1):
                if key(x) == want:
                    return o, "%s%d" % (el.ShapeType, i)
    except Exception as _fw_err:
        _fw_log("simplefeature.py:under_preview", _fw_err)
    return None


def _accepts(field, element, holder=None):
    ""

    if element == "":
        if holder is not None and "Edge" in field.what and getattr(holder, "TypeId", "") in _LINES:
            return True
        if holder is not None and "Face" in field.what and getattr(holder, "TypeId", "") in _PLANES:
            return True
        return "" in field.what
    return any(w and element.startswith(w) for w in field.what)


def group_rows(value):
    """[(text, [pair indexes])] of a grouped pick box: whole objects and lone edges by name, each
    chain of two or more edges as one Open Group<n> / Closed Group<n> row (in pick order)."""
    pairs = []
    for item in (value if isinstance(value, (list, tuple)) else ([value] if value else [])):
        if isinstance(item, App.DocumentObject):
            pairs.append((item, ""))
            continue
        source, subs = item
        for sub in (subs if isinstance(subs, (list, tuple)) else [subs]):
            pairs.append((source, sub))
    edges = []
    for i, (source, sub) in enumerate(pairs):
        if sub and sub.split(".")[-1].startswith("Edge"):
            try:
                edges.append((i, Part.getShape(source, sub, needSubElement=True)))
            except Exception as _fw_err:
                _fw_log("simplefeature.py:363", _fw_err)
    chains = []
    if len(edges) > 1:
        try:
            for run in Part.sortEdges([e for _i, e in edges]):
                idx = [i for i, e in edges if any(e.isSame(r) for r in run)]
                chains.append((idx, Part.Wire(run).isClosed() if len(run) > 1 else False))
        except Exception:
            chains = []
    in_chain = {i: n for n, (idx, _c) in enumerate(chains) if len(idx) > 1 for i in idx}
    rows, done, number = [], set(), 0
    for i, pair in enumerate(pairs):
        if i in done:
            continue
        n = in_chain.get(i)
        if n is None:
            rows.append((_pick_text(pair if pair[1] else pair[0])[0], [i]))
            done.add(i)
            continue
        idx, closed = chains[n]
        number += 1
        rows.append(("%s Group<%d>" % ("Closed" if closed else "Open", number), list(idx)))
        done.update(idx)
    return rows


def _pick_text(item):
    if isinstance(item, App.DocumentObject):
        return [item.Label]
    source, subs = item
    subs = subs if isinstance(subs, (list, tuple)) else [subs]
    return ["%s.%s" % (source.Label, s) if s else source.Label for s in subs]


def base_element(obj, element):
    """The name, in obj's BaseFeature, of the element of obj's shape called element, or None."""
    base = obj.BaseFeature
    if base is None or not element:
        return None
    try:
        mine = obj.Shape.getElement(element)
    except Exception:
        return None
    kind = mine.ShapeType
    if kind == "Vertex":
        found = [i for i, v in enumerate(base.Shape.Vertexes) if v.Point.distanceToPoint(mine.Point) < 1e-7]
    elif kind == "Edge":
        found = [i for i, e in enumerate(base.Shape.Edges) if abs(e.Length - mine.Length) < 1e-7
                 and e.CenterOfMass.distanceToPoint(mine.CenterOfMass) < 1e-7]
    elif kind == "Face":
        found = [i for i, f in enumerate(base.Shape.Faces) if abs(f.Area - mine.Area) < 1e-7 * max(1.0, f.Area)
                 and f.CenterOfMass.distanceToPoint(mine.CenterOfMass) < 1e-7]
    else:
        return None
    return "%s%d" % (kind, found[0] + 1) if found else None


class _IconRow(QtWidgets.QWidget):
    ""
    changed = QtCore.Signal()

    def __init__(self, field, value):
        super().__init__()
        self.setObjectName("SWStyle_%s" % field.name)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.group = QtWidgets.QButtonGroup(self)
        self.buttons = {}
        try:
            from . import icons
        except Exception:
            icons = None
        for name in field.values:
            b = QtWidgets.QToolButton(self)
            b.setObjectName("SWStyle_%s_%s" % (field.name, name.replace(" ", "")))
            b.setCheckable(True)
            b.setAutoRaise(True)
            b.setToolTip(name)
            spec = field.icons.get(name, "")
            if callable(spec):
                icon = spec()           # a picture drawn here (no pack family for it)
            else:
                icon = icons.family(spec) if icons is not None else None
            if icon is not None and not icon.isNull() and (icons is None or icons.paints(icon)):
                b.setIcon(icon)
                b.setIconSize(QtCore.QSize(28, 28))
            else:
                b.setText(name)
            b.setChecked(name == value)
            self.group.addButton(b)
            lay.addWidget(b)
            self.buttons[name] = b
            b.toggled.connect(lambda on: on and self.changed.emit())
        lay.addStretch(1)

    def value(self):
        for name, b in self.buttons.items():
            if b.isChecked():
                return name
        return next(iter(self.buttons), "")

    def set(self, value):
        b = self.buttons.get(value)
        if b is not None and not b.isChecked():
            b.blockSignals(True)
            b.setChecked(True)
            b.blockSignals(False)


class _RadioColumn(_IconRow):
    ""

    def __init__(self, field, value):
        QtWidgets.QWidget.__init__(self)
        self.setObjectName("SWStyle_%s" % field.name)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 0, 0, 0)
        lay.setSpacing(2)
        self.group = QtWidgets.QButtonGroup(self)
        self.buttons = {}
        for name in field.values:
            b = QtWidgets.QRadioButton(name, self)
            b.setObjectName("SWStyle_%s_%s" % (field.name, name.replace(" ", "")))
            b.setChecked(name == value)
            self.group.addButton(b)
            lay.addWidget(b)
            self.buttons[name] = b
            b.toggled.connect(lambda on: on and self.changed.emit())


_why_failed = {}     # (doc, name) -> what the last build of the feature said when it failed


def _key(obj):
    try:
        return (obj.Document.Name, obj.Name)
    except Exception:
        return (None, None)


def why_failed(obj):
    ""

    text = ""
    try:
        text = obj.getStatusString()
    except Exception:
        pass
    if text.strip() in ("", "Error", "Invalid", "Touched"):
        text = _why_failed.get(_key(obj)) or text
    return text


def _fw_retyped(spin):
    """True when the field's text is not what its value shows: a number typed and not taken yet.
    An untouched field is left alone (taking its rounded text again moved linked values: Flex's
    Radius 26.74 turned a typed Angle back to 89.99)."""
    try:
        return spin.text() != spin.prefix() + spin.textFromValue(spin.value()) + spin.suffix()
    except Exception:
        return True


_made = set()       # (doc, name) of features a page made and has not OK'd yet


def drop_made(doc, name):
    """Cancel: take out the feature name if a page made it and has not OK'd it (True when it was one)."""
    made = (doc.Name, name) in _made
    _made.discard((doc.Name, name))
    obj = doc.getObject(name)
    from . import pickwait
    pickwait.forget(doc.Name, name)     # a later feature given the same name does not inherit its wait text
    if made and obj is not None:
        try:
            for parent in obj.InList:
                if parent.TypeId == "PartDesign::Body":
                    parent.removeObject(obj)
            doc.removeObject(name)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: cancel: %r\n" % (error,))
    return made


class Panel:
    """A PropertyManager made from the Spec's fields."""

    def __init__(self, obj):
        self.obj = obj
        self.spec = SPECS[obj.SWStyleKind]
        try:
            self._was_shown = bool(obj.ViewObject.Visibility)
        except Exception:
            self._was_shown = True
        # pkg242: editing a feature (double-click, Edit Feature) opened no undo step: Cancel kept the
        # page's changes and Undo after OK took out the feature itself. An edit is one undo step now.
        try:
            doc = obj.Document
            if (doc.Name, obj.Name) not in _made and not doc.HasPendingTransaction:
                doc.openTransaction("Edit %s" % obj.Label)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: edit transaction: %r\n" % (error,))
        self.widgets = {}
        self.lists = {}
        self.active = None
        boxes, order = {}, []
        for field in self.spec.fields:
            title = field.box or self.spec.title
            if title not in boxes:
                box = QtWidgets.QWidget()
                box.setWindowTitle(title)
                QtWidgets.QFormLayout(box)
                boxes[title] = box
                order.append(box)
            self._add(boxes[title].layout(), field)
        self.error = QtWidgets.QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet(_error_css())
        order[-1].layout().addRow(self.error)
        # the last box keeps its own height: the task pane gave it the spare room, so its pick
        # heading sat far below the box title with an empty gap (Wrap's Pull Direction)
        order[-1].setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        if self.spec.command == "SWStyle_ExtendSurface":
            for box in order:
                box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        order[0].setProperty("swstyle_pm_title", self.spec.title)
        order[0].setProperty("swstyle_pm_icon", self.spec.icon)
        self.form = order if len(order) > 1 else order[0]
        self.busy = False
        first = self.spec.first_pick or next((f.name for f in self.spec.fields if f.kind == "pick"), None)
        if first is not None and getattr(obj, first):
            # filled from what was picked before the command: the next empty box takes the clicks,

            first = next((f.name for f in self.spec.fields if f.kind == "pick" and not getattr(obj, f.name)
                          and _on(f, obj)), first)
        if first is not None and not _on([f for f in self.spec.fields if f.name == first][0], obj):
            first = next((f.name for f in self.spec.fields if f.kind == "pick" and _on(f, obj)), None)
        if first is not None:
            self._activate(first)
        self._show()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)
        try:
            # a box of faces (Dome's Faces to dome, Face Fillet's sets...): a click by a face's edge
            # stays on the face (facehover gives the edge otherwise, and the box refused it)
            from . import facehover
            facehover.faces_only(self, Panel._takes_faces_only)
        except Exception:
            pass

    def _add(self, form, field):
        obj = self.obj
        if field.kind == "button":
            widget = QtWidgets.QPushButton(field.label)
            widget.setObjectName("SWStyle_%s" % field.name)
            widget.setToolTip(field.tip or field.label)
            widget.clicked.connect(lambda checked=False, f=field: self._run(f))
            form.addRow(widget)
            self.widgets[field.name] = widget
            return
        value = getattr(obj, field.name)
        if field.kind == "pick":
            widget = QtWidgets.QListWidget()
            widget.setMaximumHeight(64 if field.many else 40)
            widget.setToolTip(field.tip or field.label)
            widget.setObjectName("SWStyle_%s" % field.name)
            widget.itemSelectionChanged.connect(lambda name=field.name: self._activate(name))
            widget.installEventFilter(self._focus_filter(field.name))
            pmboxes.bind(widget, lambda row, n=field.name: self.remove_item(n, row), lambda n=field.name: self.clear_items(n))
            heading = QtWidgets.QLabel(field.label)
            form.addRow(heading)
            if field.box and field.label == field.box:
                heading.hide()
            form.addRow(widget)
            self.lists[field.name] = widget
            self.__dict__.setdefault("headings", {})[field.name] = heading
        elif field.kind == "bool" and field.flip and self._beside_last(form, field):
            widget = self.widgets[field.name]
            widget.setChecked(bool(value))
            widget.toggled.connect(self._changed)
        elif field.kind == "bool":
            widget = QtWidgets.QCheckBox(field.label)
            widget.setChecked(bool(value))
            widget.toggled.connect(self._changed)
            form.addRow(widget)
        elif field.kind == "enum":
            widget = QtWidgets.QComboBox()
            widget.addItems(field.values)
            widget.setCurrentText(str(value))
            widget.currentIndexChanged.connect(self._changed)
            form.addRow(field.label, widget)
        elif field.kind == "icons":
            widget = _IconRow(field, str(value))
            widget.changed.connect(self._changed)
            form.addRow(widget)
        elif field.kind == "radio":
            heading = QtWidgets.QLabel(field.label)
            form.addRow(heading)
            heading.setVisible(bool(field.label))       # radios that are their group's whole content
            if field.box and field.label == field.box:
                heading.hide()
            widget = _RadioColumn(field, str(value))
            widget.changed.connect(self._changed)
            form.addRow(widget)
            self.__dict__.setdefault("headings", {})[field.name] = heading
        elif field.kind == "info":
            widget = QtWidgets.QLabel(str(value))
            widget.setWordWrap(True)
            heading = QtWidgets.QLabel(field.label)
            form.addRow(heading)
            form.addRow(widget)
            # an empty message area shows nothing, not a bare "Messages" heading (look audit AA4)
            widget._fw_heading = heading
            heading.setVisible(bool(str(value)))
            widget.setVisible(bool(str(value)))
        elif field.kind == "int":
            widget = QtWidgets.QSpinBox()
            widget.setRange(field.low if field.low is not None else 1, field.high if field.high is not None else 10000)
            widget.setValue(int(value))
            widget.setKeyboardTracking(False)
            widget.valueChanged.connect(self._changed)
            form.addRow(field.label, widget)
        elif field.kind == "text":
            widget = QtWidgets.QPlainTextEdit(str(value))
            widget.setMaximumHeight(110)
            widget.setToolTip(field.tip or field.label)
            widget.textChanged.connect(self._text_later)
            form.addRow(QtWidgets.QLabel(field.label))
            form.addRow(widget)
        elif field.kind == "vector":
            widget = []
            for axis in "xyz":
                spin = self._spin(field, getattr(value, axis), "length")
                form.addRow("%s %s" % (field.label, axis.upper()), spin)
                widget.append(spin)
        else:
            widget = self._spin(field, float(value), field.kind)
            form.addRow(field.label, widget)
        # every field can be found by name (checks, the PC's click runs); a name of its own, so the
        # pages that look up "SWStyle_<name>" widgets (the Extrude page's End Condition...) skip it
        for i, w in enumerate(widget if isinstance(widget, list) else [widget]):
            try:
                if isinstance(w, QtWidgets.QWidget) and not w.objectName():
                    w.setObjectName("SWField_%s%s" % (field.name, "XYZ"[i] if isinstance(widget, list) else ""))
            except Exception as _fw_err:
                App.Console.PrintLog("FreeCAD: field name: %r\n" % (_fw_err,))
        self.widgets[field.name] = widget

    def _beside_last(self, form, field):
        ""

        try:
            from . import pmvalues
            row = form.rowCount() - 1
            item = form.itemAt(row, QtWidgets.QFormLayout.FieldRole)
            last = item.widget() if item is not None else None
            if not isinstance(last, QtWidgets.QAbstractSpinBox):
                return False
            button = QtWidgets.QToolButton()
            button.setObjectName("SWStyle_%s" % field.name)
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setIcon(pmvalues.reverse_icon())
            button.setToolTip(field.tip or field.label)
            button.setAccessibleName(field.label)
            holder = QtWidgets.QWidget()
            lay = QtWidgets.QHBoxLayout(holder)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(2)
            form.removeItem(item)
            lay.addWidget(button)
            lay.addWidget(last, 1)
            form.setWidget(row, QtWidgets.QFormLayout.FieldRole, holder)
            self.widgets[field.name] = button
            return True
        except Exception as error:
            App.Console.PrintLog("FreeCAD: reverse button: %s\n" % error)
            return False

    def _spin(self, field, value, kind):
        spin = QtWidgets.QDoubleSpinBox()
        low = field.low if field.low is not None else (0.0 if kind in ("length",) else -100000.0)
        spin.setRange(low, field.high if field.high is not None else 100000.0)
        spin.setDecimals(3 if kind == "float" else 2)
        spin.setSuffix({"length": " mm", "distance": " mm", "angle": " deg"}.get(kind, ""))
        spin.setValue(value)
        # the value is taken when Enter, Tab or a click elsewhere ends the typing (arrows at once): a
        # rebuild on each key took "1" of "180" and the rest of the typing was lost (Sweep's Twist value)
        spin.setKeyboardTracking(False)
        spin.valueChanged.connect(self._changed_soon)
        spin.setToolTip(field.tip or field.label)
        return spin

    def _focus_filter(self, name):
        panel = self

        class Filter(QtCore.QObject):
            def eventFilter(self, watched, event):
                if not isinstance(event, QtCore.QEvent):
                    return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
                if event.type() == QtCore.QEvent.FocusIn:
                    panel._activate(name)
                return False
        self._keep = getattr(self, "_keep", []) + [Filter()]
        return self._keep[-1]

    def _activate(self, name):
        self.active = name
        for other, widget in self.lists.items():
            pmboxes.mark(widget, other == name)

    def remove_item(self, name, row):
        ""
        field = [f for f in self.spec.fields if f.name == name][0]
        current = getattr(self.obj, name)
        if field.what in WHOLE:
            if field.many:
                items = list(current or [])
                if 0 <= row < len(items):
                    items.pop(row)
                setattr(self.obj, name, items)
            else:
                setattr(self.obj, name, None)
        else:
            pairs = []
            for source, subs in current or []:
                for e in (subs if isinstance(subs, (list, tuple)) else [subs]):
                    pairs.append((source, e))
            grouped = getattr(self, "_rows", {}).get(name) if getattr(field, "group", False) else None
            if grouped is not None and 0 <= row < len(grouped):
                # a group row: all of its edges go
                gone = set(grouped[row])
                pairs = [p for i, p in enumerate(pairs) if i not in gone]
            elif 0 <= row < len(pairs):
                pairs.pop(row)
            setattr(self.obj, name, [(so, [e]) for so, e in pairs])
        self._activate(name)
        self._changed()

    def clear_items(self, name):
        """Clear Selections in a pick box."""
        field = [f for f in self.spec.fields if f.name == name][0]
        setattr(self.obj, name, [] if (field.many or field.what not in WHOLE) else None)
        self._activate(name)
        self._changed()

    # selection
    def _takes_faces_only(self):
        """True while the active box takes faces (or vertices) but no edges."""
        if self.active is None or self._alive() is None:
            return False
        try:
            first = self.form[0] if isinstance(self.form, list) else self.form
            if not first.isVisible():
                return False            # the page is closed
        except RuntimeError:
            return False
        field = next((f for f in self.spec.fields if f.name == self.active), None)
        if field is None or field.kind != "pick" or isinstance(field.what, str):
            return False                # whole objects: which element is hit does not matter
        return bool(field.what) and "Edge" not in field.what

    def _drop_observer(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("simplefeature.py:728", _fw_err)

    def _alive(self):
        """The feature and its document still exist and the page is still the open task dialog
        (closed through the confirmation corner, the page may never get reject/_close)."""
        try:
            name = self.obj.Document.Name
        except (ReferenceError, RuntimeError, AttributeError):
            self._drop_observer()
            return None
        if name not in App.listDocuments():
            self._drop_observer()
            return None
        return name

    def addSelection(self, doc, name, sub, point):
        own = self._alive()
        if own is not None and self.active is not None and doc != own and self._context_pick(doc, name, sub):
            return
        if own is None or doc != own or self.active is None:
            return
        QtCore.QTimer.singleShot(0, lambda: self._alive() and self._picked(doc, name, sub))

    def _context_pick(self, doc, name, sub):
        """Another component picked in the assembly while this part is edited in it (Join, Cavity...):
        it goes in through a reference in the part. True when handled."""
        ctx = _context()
        if ctx is None or doc != ctx[0].Document.Name:
            return False
        field = next((f for f in self.spec.fields if f.name == self.active), None)
        if field is None or field.what not in WHOLE:
            return False
        top = App.getDocument(doc).getObject(name)
        mapped = _map_pick(top, sub)
        if mapped is top:
            return False

        def take(binder=mapped, field=field):
            if self._alive() is None:
                return
            Gui.Selection.clearSelection()
            current = getattr(self.obj, field.name)
            if field.many:
                items = list(current or [])
                items = [i for i in items if i != binder] if binder in items else items + [binder]
                setattr(self.obj, field.name, items)
            else:
                setattr(self.obj, field.name, None if current == binder else binder)
            try:
                self._changed()
            except Exception:
                self.obj.Document.recompute()
        QtCore.QTimer.singleShot(0, take)
        return True

    def _picked(self, doc_name, name, sub):
        field = [f for f in self.spec.fields if f.name == self.active][0]
        doc = self.obj.Document
        top = doc.getObject(name)
        path = sub.split(".")
        element = path[-1]
        holder = top
        for part in path[:-1]:
            found = doc.getObject(part)
            if found is not None:
                holder = found
        if holder is None:
            return
        if holder == self.obj:
            # A click on what this feature shows (it is the tip while it is edited): the same
            # element of the part before it, found by its geometry
            under = None
            if getattr(self.obj, "BaseFeature", None) is None and field.what not in WHOLE:
                # a surface feature has no part before it: the input surface under the preview (Filled Surface's
                # Merge result shows the patch joined to the tube it closes; features-428 lost 3 of 4 edge clicks)
                under = _under_preview(self.obj, element)
                if under is None:
                    return
                holder, element = under
            else:
                mapped = base_element(self.obj, element) if field.what not in WHOLE else None
                if mapped is None and field.what not in WHOLE:
                    return
                holder, element = self.obj.BaseFeature, mapped or element
            if holder is None:
                return
        # Elements of the part so far are taken from the feature before this one
        if holder.TypeId == "PartDesign::Body" or (self.obj.BaseFeature is not None and holder in
                                                   self._later_or_self()):
            holder = self.obj.BaseFeature
        route = getattr(self.spec, "route", None)
        if route is not None:
            # the Spec may send a pick to the box it belongs in (a plane to Split Line's
            # splitting box, the part's face after it to the faces to split)
            try:
                name = route(self.obj, field.name, holder, element)
            except Exception:
                name = field.name
            if name and name != field.name:
                field = [f for f in self.spec.fields if f.name == name][0]
                self._activate(name)
        Gui.Selection.clearSelection()
        if (field.name in getattr(self.spec, "whole_surfaces", ()) and element.startswith("Face")
                and "" in field.what and _surface_only(holder)):
            element = ""
        if field.what in WHOLE:
            if field.what == "Object" and holder.TypeId.startswith("PartDesign::") and holder.TypeId != "PartDesign::Body":
                holder = holder.getParentGeoFeatureGroup() or holder
            current = getattr(self.obj, field.name)
            if field.many:
                items = list(current or [])
                items = [i for i in items if i != holder] if holder in items else items + [holder]
                setattr(self.obj, field.name, items)
            else:
                setattr(self.obj, field.name, None if current == holder else holder)
        else:
            if not _accepts(field, element, holder):
                return
            pairs = []
            for source, subs in getattr(self.obj, field.name) or []:
                for s in (subs if isinstance(subs, (list, tuple)) else [subs]):
                    pairs.append((source, s))
            key = (holder, element)
            added = key not in pairs
            if key in pairs:
                pairs.remove(key)
            elif field.many:
                pairs.append(key)
            else:
                pairs = [key]
            setattr(self.obj, field.name, [(s, [e]) for s, e in pairs])
            if added and not field.many:
                self._advance(field)
        self._changed()

    def _advance(self, field):
        ""
        picks = [f for f in self.spec.fields if f.kind == "pick" and _on(f, self.obj)]
        if field not in picks:
            return
        i = picks.index(field)
        for nxt in picks[i + 1:] + picks[:i]:
            if not getattr(self.obj, nxt.name):
                self._activate(nxt.name)
                return

    def _later_or_self(self):
        body = self.obj.getParentGeoFeatureGroup()
        if body is None:
            return [self.obj]
        group = list(body.Group)
        return group[group.index(self.obj):] if self.obj in group else [self.obj]

    def _text_later(self):
        if not hasattr(self, "_text_timer"):
            self._text_timer = QtCore.QTimer()
            self._text_timer.setSingleShot(True)
            self._text_timer.timeout.connect(self._changed)
        self._text_timer.start(600)

    def _run(self, field):
        try:
            if field.action is not None:
                field.action(self.obj)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s: %s\n" % (field.label, error))

    def _changed_soon(self, *args):
        """A typed value is taken when the typing ends (Enter, Tab, a click in the next box), inside
        the box's own key or focus handling. The rebuild runs just after, from the event loop: a slow
        rebuild run inside that handling (Tooling Split) crashed FreeCAD on the next key in the next box
        (QAbstractSpinBox::keyPressEvent, video follow-along mold tools, 3 of 3 runs)."""
        if self.busy or getattr(self, "_fw_change_due", False) or getattr(self, "_fw_closed", False):
            return
        self._fw_change_due = True

        def run(panel=self):
            if not getattr(panel, "_fw_change_due", False):
                return          # accept() took it already
            panel._fw_change_due = False
            if getattr(panel, "_fw_closed", False) or not _widgets_alive(panel):
                return          # the page closed (Enter = OK): its boxes are gone (video_mo MO9)
            try:
                panel.obj.Name
            except Exception:
                return          # the page closed and its feature went
            panel._changed()
        QtCore.QTimer.singleShot(0, run)

    def _changed(self, *args):
        self._fw_change_due = False
        if self.busy:
            return
        obj = self.obj
        for field in self.spec.fields:
            widget = self.widgets[field.name]
            if field.kind in ("pick", "info", "button"):
                continue
            if field.kind == "bool":
                setattr(obj, field.name, widget.isChecked())
            elif field.kind == "enum":
                setattr(obj, field.name, widget.currentText())
            elif field.kind in ("icons", "radio"):
                setattr(obj, field.name, widget.value())
            elif field.kind == "vector":
                setattr(obj, field.name, App.Vector(*(w.value() for w in widget)))
            elif field.kind == "text":
                setattr(obj, field.name, widget.toPlainText())
            else:
                put_value(obj, field.name, widget.value())
        obj.Document.recompute()
        if getattr(self, "_fw_closed", False) or not _widgets_alive(self):
            return      # a slow rebuild (Tooling Split) let the page's own Enter = OK close it meanwhile
        self._preview()
        self._show()

    def _show(self):
        obj = self.obj
        for field in self.spec.fields:
            widget = self.widgets[field.name]
            if field.kind == "pick":
                widget.blockSignals(True)
                widget.clear()
                value = getattr(obj, field.name)
                items = value if isinstance(value, (list, tuple)) else ([value] if value else [])
                if getattr(field, "group", False):
                    rows = group_rows(value)
                    self._rows = dict(getattr(self, "_rows", {}), **{field.name: [r for _t, r in rows]})
                    widget.addItems([text for text, _r in rows])
                else:
                    for item in items:
                        widget.addItems(_pick_text(item))
                widget.blockSignals(False)
            if field.kind == "info":
                text = str(getattr(obj, field.name))
                widget.setText(text)
                if field.shown is None:
                    widget.setVisible(bool(text))
                    if getattr(widget, "_fw_heading", None) is not None:
                        widget._fw_heading.setVisible(bool(text))
            if field.kind in ("icons", "radio"):
                widget.set(str(getattr(obj, field.name)))
            if field.shown is not None:
                on = bool(field.shown(obj))
                for w in (widget if isinstance(widget, list) else [widget]):
                    w.setVisible(on)
                    form = w.parentWidget().layout() if w.parentWidget() else None
                    label = form.labelForField(w) if isinstance(form, QtWidgets.QFormLayout) else None
                    if label is not None:
                        label.setVisible(on)
                heading = getattr(self, "headings", {}).get(field.name)
                if heading is not None:
                    heading.setVisible(on)
        active = [f for f in self.spec.fields if f.name == getattr(self, "active", None)]
        if active and not _on(active[0], obj):
            # a switch hid the box taking the clicks (Split Line's Type): the first shown empty box takes them
            shown = [f for f in self.spec.fields if f.kind == "pick" and _on(f, obj)]
            pick = next((f for f in shown if not getattr(obj, f.name)), shown[0] if shown else None)
            if pick is not None:
                self._activate(pick.name)
        bad = "Invalid" in obj.State
        self.error.setText(why_failed(obj) if bad else "")
        self.error.setVisible(bad)

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _preview(self, on=None):
        """Show preview: a ShowPreview field shows or hides the result while the PM is open; once
        it closes the result shows again."""
        try:
            obj = self.obj
            if "ShowPreview" not in obj.PropertiesList or getattr(obj, "ViewObject", None) is None:
                return
            obj.ViewObject.Visibility = bool(obj.ShowPreview) if on is None else on
        except Exception as _fw_err:
            _fw_log("simplefeature.py:962", _fw_err)

    def _shown_after(self):
        """Once the page closes the result shows, unless a later feature carries the part on: an
        edited feature in the middle goes back as it was (it stayed shown over the finished part)."""
        try:
            body = next((p for p in self.obj.InList if p.TypeId == "PartDesign::Body"), None)
            if body is None or body.Tip is None or body.Tip is self.obj:
                return True
            return self._was_shown
        except Exception:
            return True

    def _close(self):
        self._fw_closed = True          # a rebuild still queued from the last typed value must not run now
        self._fw_change_due = False
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("simplefeature.py:968", _fw_err)
        self._preview(self._shown_after())
        Gui.ActiveDocument.resetEdit()
        Gui.Control.closeDialog()
        try:
            body = next((p for p in self.obj.InList if p.TypeId == "PartDesign::Body"), None)
            if body is not None and body.Tip is not None and body.Tip is not self.obj:
                _show_tip(body)         # the finished part again (OK on an edit in the middle left it hidden)
        except Exception as _fw_err:
            _fw_log("simplefeature.py:close-tip", _fw_err)

    def accept(self):
        doc = self.obj.Document
        try:
            from . import pmvalues as _fw_pmv
            _fw_pmv.hide_lists()
        except Exception as _fw_err:
            App.Console.PrintLog("FreeCAD: value list: %r\n" % (_fw_err,))

        # their value when the typing ends, and a click on OK does not end it)
        for w in list(self.widgets.values()):
            for x in (w if isinstance(w, list) else [w]):
                try:
                    if isinstance(x, QtWidgets.QAbstractSpinBox) and not x.keyboardTracking() and _fw_retyped(x):
                        x.interpretText()
                except Exception as _fw_err:
                    App.Console.PrintLog("FreeCAD: typed value: %r\n" % (_fw_err,))
        if getattr(self, "_fw_change_due", False):
            self._changed()     # a value taken just now whose rebuild has not run yet
        doc.recompute()
        missing = [f.label for f in self.spec.fields if f.kind == "pick" and not f.optional
                   and _on(f, self.obj) and not getattr(self.obj, f.name)]
        if "Invalid" in self.obj.State or missing:
            self.error.setText(why_failed(self.obj) if "Invalid" in self.obj.State
                               else "Pick: %s" % ", ".join(missing))
            self.error.setVisible(True)
            try:

                # why OK was refused where it can be read
                w = self.error.parentWidget()
                while w is not None and not isinstance(w, QtWidgets.QScrollArea):
                    w = w.parentWidget()
                if w is not None:
                    QtCore.QTimer.singleShot(0, lambda a=w, e=self.error: a.ensureWidgetVisible(e))
            except Exception as _fw_err:
                App.Console.PrintLog("FreeCAD: message: %r\n" % (_fw_err,))
            return False
        doc.commitTransaction()
        _made.discard((doc.Name, self.obj.Name))
        self._close()
        return True

    def reject(self):
        self._drop_observer()
        doc = self.obj.Document
        name = self.obj.Name
        made = (doc.Name, name) in _made
        try:
            body = next((p for p in self.obj.InList if p.TypeId == "PartDesign::Body"), None) if made else None
        except Exception:
            body = None
        doc.abortTransaction()
        adopted = _adopted.pop((doc.Name, name), None)
        if made and body is not None and adopted == body.Name and _undo_adopt(doc, body, name):
            body = None

        # opening transaction early (Full Round Fillet: Esc kept the feature), so a feature this page
        # made and the abort did not take out is taken out here
        drop_made(doc, name)
        doc.recompute()
        if made and body is not None:
            _show_tip(body)
        self._close()
        return True


_adopted = {}        # {(doc, feature): body} a body made for a first feature on a plain solid


def _undo_adopt(doc, body, name):
    ""


    try:
        from . import teardown
        if not teardown.doc_alive(doc):
            return False
    except Exception as _fw_err:
        _fw_log("simplefeature.py:alive", _fw_err)
    try:
        if [o for o in body.Group if o.TypeId != "PartDesign::FeatureBase" and o.Name != name]:
            return False
        if doc.UndoNames and doc.UndoNames[0] == "Body":
            doc.undo()
            feat = doc.getObject(name)
            if feat is not None:            # made outside the aborted step: it was left on its own
                doc.removeObject(name)
                _made.discard((doc.Name, name))
            doc.recompute()
            return True
        solid = body.BaseFeature
        feat = doc.getObject(name)
        doc.openTransaction("Cancel")
        if feat is not None:
            body.removeObject(feat)
            doc.removeObject(name)
        body.BaseFeature = None
        body.removeObjectsFromDocument()
        doc.removeObject(body.Name)
        doc.commitTransaction()
        if solid is not None and getattr(solid, "ViewObject", None) is not None:
            solid.ViewObject.Visibility = True
        return True
    except Exception as _fw_err:
        _fw_log("simplefeature.py:undo_adopt", _fw_err)
        return False


def _show_tip(body):
    """The part as it was: the new feature hid the body's last feature, and taking the feature out
    does not show that one again (Cancel on Dome left the part hidden)."""
    try:
        tip = body.Tip
        if tip is not None and tip.ViewObject is not None and not tip.ViewObject.Visibility:
            tip.ViewObject.show()
    except Exception:
        pass


# --------------------------------------------------------------------------- making
def body_of(doc):
    try:
        body = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
    except Exception:
        body = None
    if body is None:
        bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
        body = bodies[0] if len(bodies) == 1 else None
    return body


def has_solid(body):
    try:
        tip = body.Tip if body.Tip is not None else getattr(body, "BaseFeature", None)
        return tip is not None and not tip.Shape.isNull() and bool(tip.Shape.Solids)
    except Exception:
        return False


def ready(spec, doc):
    ""

    body = body_of(doc)
    if body is None:
        from . import solidbody
        return solidbody.loose_solid(doc) is not None or (_starts_body(spec) and _loose_surface(doc)) \
            or spec.command in STARTS_EMPTY
    return not spec.needs_body or has_solid(body)


STARTS_BODY = {"SWStyle_Thicken"}

# part's first body instead of being greyed
STARTS_EMPTY = {"SWStyle_InsertPart"}


def _starts_body(spec):
    """A solid-making feature that works without a solid (Thicken): it may start the part's first body."""
    return spec.command in STARTS_BODY


def _loose_surface(doc):
    """A surfaces-only part (no body, no solid): Thicken and the like start its first solid body."""
    for o in doc.Objects:
        try:
            if o.TypeId.startswith(("Sketcher::", "App::", "PartDesign::")) or not hasattr(o, "Shape"):
                continue
            sh = o.Shape
            if not sh.isNull() and sh.Faces and not sh.Solids:
                return True
        except Exception as _fw_err:
            _fw_log("simplefeature.py:1102", _fw_err)
            continue
    return False


def make(spec, doc=None, picks=None, edit=True, **values):
    """A new feature in the active body; picks = {field: [(obj, "Face1"), ...] or obj}.
    While a part is edited in an assembly it goes in that part, and its PM opens through the component."""
    ctx = _context() if edit and App.GuiUp else None
    if ctx is not None:
        obj = _make(spec, ctx[2].Document, picks, False, **values)
        if obj is not None:
            _open_in_context(ctx, obj)
        return obj
    return _make(spec, doc, picks, edit, **values)


def _make(spec, doc=None, picks=None, edit=True, **values):
    doc = doc or App.ActiveDocument
    body = body_of(doc) if doc is not None else None
    if body is None and doc is not None:
        from . import solidbody          # first feature on a Part or imported solid: it becomes the body's base
        body = solidbody.adopt(doc)
        if body is not None and edit:
            _adopted[doc.Name] = body.Name   # Cancel on this first feature takes the new body out too
        if body is None and (_starts_body(spec) and _loose_surface(doc) or spec.command in STARTS_EMPTY):
            body = doc.addObject("PartDesign::Body", "Body")      # the part's first solid body
            try:
                Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", body)
            except Exception as _fw_err:
                _fw_log("simplefeature.py:1086", _fw_err)
    if body is None or (spec.needs_body and body.Tip is None and getattr(body, "BaseFeature", None) is None):
        App.Console.PrintWarning("FreeCAD: %s needs a body with a solid\n" % spec.title)
        return None
    doc.openTransaction(spec.title)
    obj = body.newObject(spec.type, spec.internal)
    Feature(obj, spec)
    if edit:
        _made.add((doc.Name, obj.Name))       # Cancel takes it out even if its transaction was closed on the way
        if _adopted.get(doc.Name) == body.Name:
            _adopted[(doc.Name, obj.Name)] = _adopted.pop(doc.Name)
    else:
        _adopted.pop(doc.Name, None)
    if App.GuiUp and Gui.ActiveDocument is not None:
        View(obj.ViewObject)
    obj.Label = naming.next_label(doc, spec.label)
    for name, value in (picks or {}).items():
        field = [f for f in spec.fields if f.name == name][0]
        if field.what in WHOLE:
            setattr(obj, name, value)
        else:
            setattr(obj, name, [(o, [e]) for o, e in value])
    for name, value in values.items():
        setattr(obj, name, value)
    from . import pickwait
    with pickwait.opening(obj, edit and App.GuiUp):     # its PM opens next: empty picks wait for it
        doc.recompute()
    if edit and App.GuiUp:
        Gui.Selection.clearSelection()
        if _in_command():
            # FreeCAD 1.1 crashed in setEditingViewProvider when a pattern's PM opened inside the toolbar
            # command with a seed feature and its edge picked first: open it once the command has returned
            gdoc = Gui.ActiveDocument
            QtCore.QTimer.singleShot(0, lambda: _late_edit(gdoc, obj))
        else:
            Gui.ActiveDocument.setEdit(obj.Name)
    else:
        doc.commitTransaction()
    return obj


def _in_command():
    import inspect
    return any(f.function == "Activated" for f in inspect.stack(0)[2:12])


def _late_edit(gdoc, obj):
    try:
        if obj.Document is not None and obj.Document.getObject(obj.Name) is obj:
            gdoc.setEdit(obj.Name)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: the PM did not open (%s)\n" % error)


def _on(field, obj):
    """Whether the field is shown now (a field with no shown rule always is)."""
    try:
        return field.shown is None or bool(field.shown(obj))
    except Exception as _fw_err:
        _fw_log("simplefeature.py:1185", _fw_err)
        return True


_NOT_SEEDS = ("Sketcher::", "PartDesign::Plane", "PartDesign::Line", "PartDesign::Point", "PartDesign::CoordinateSystem",
              "PartDesign::Body", "PartDesign::ShapeBinder", "PartDesign::SubShapeBinder")


def preselected(spec):
    """Picks for the first pick field from what was selected before the command; while a part is
    edited in an assembly, other components picked whole go in as references in the part."""
    out = _preselected(spec)
    if _context() is None:
        return out
    first = spec.first_pick or next((f.name for f in spec.fields if f.kind == "pick"), None)
    field = next((f for f in spec.fields if f.name == first), None)
    if field is None or field.what not in WHOLE:
        return out
    picks = []
    for sel in Gui.Selection.getSelectionEx("", 0):
        for sub in sel.SubElementNames or [""]:
            mapped = _map_pick(sel.Object, sub)
            if mapped is not sel.Object and mapped not in picks:
                picks.append(mapped)
    if picks:
        out = dict(out or {})
        out[first] = picks if field.many else picks[0]
    return out


def _preselected(spec):
    first = spec.first_pick or next((f.name for f in spec.fields if f.kind == "pick"), None)
    if first is None:
        return {}
    field = [f for f in spec.fields if f.name == first][0]
    out = []
    seed = next((f for f in spec.fields if f.name == "Features" and f.kind == "pick" and f.name != first), None)
    surface = next((f for f in spec.fields if f.name == "Replacement" and f.kind == "pick" and f.name != first), None)
    surfaces = []
    seeds = []
    for sel in Gui.Selection.getSelectionEx("", 0):
        doc = sel.Object.Document
        for sub in sel.SubElementNames or [""]:
            path = sub.split(".")
            holder = sel.Object
            for part in path[:-1]:
                found = doc.getObject(part)
                if found is not None:
                    holder = found
            element = path[-1]
            if (seed is not None and element == "" and holder.TypeId.startswith("PartDesign::")
                    and not holder.TypeId.startswith(_NOT_SEEDS)):
                if holder not in seeds:
                    seeds.append(holder)
                continue
            if field.what in WHOLE:
                if field.what == "Feature" and holder.TypeId == "PartDesign::Body" and spec.needs_body:
                    continue    # the part picked first (Scale with the body selected): the body is not a feature pick, and a link to it from inside it would never rebuild
                if field.what == "Object" and holder.TypeId.startswith("PartDesign::") and holder.TypeId != "PartDesign::Body":
                    holder = holder.getParentGeoFeatureGroup() or holder
                out.append(holder)
            elif _accepts(field, element, holder):
                if holder.TypeId == "PartDesign::Body":
                    holder = holder.Tip
                if surface is not None and element.startswith("Face") and _surface_body(holder):

                    surfaces.append((holder, element))
                    continue
                out.append((holder, element))
    if surfaces:
        extra = {surface.name: surfaces if surface.many else surfaces[:1]}
        if not out:
            return extra
    else:
        extra = {}
    if not out:
        return {seed.name: seeds if seed.many else seeds[0]} if seeds else {}
    result = {first: out if field.many else out[0]} if field.what in WHOLE else {first: out if field.many else out[:1]}
    then = getattr(field, "split_to", None)
    if then and field.what not in WHOLE and len(out) > 1:
        result = {first: out[:1], then: out[1:]}     # Face Fillet: the first face is Set 1, the rest Set 2
    _route_rest(spec, field, result)
    if seeds:
        result[seed.name] = seeds if seed.many else seeds[0]
    result.update(extra)
    return result


def _surface_body(obj):
    try:
        shape = obj.Shape
        return not shape.isNull() and bool(shape.Faces) and not shape.Solids
    except Exception as _fw_err:
        _fw_log("simplefeature.py:1278", _fw_err)
        return False


class _Defaults:
    """The feature's properties as they start, for the fields' shown rules before it exists."""

    def __init__(self, spec):
        for f in spec.fields:
            setattr(self, f.name, f.default if f.kind != "pick" else None)


def _route_rest(spec, first, result):
    ""


    if first.what not in WHOLE:
        return
    stub = _Defaults(spec)
    rest = [f for f in spec.fields if f.kind == "pick" and f is not first and f.what not in WHOLE and _on(f, stub)]
    if not rest:
        return
    for sel in Gui.Selection.getSelectionEx("", 0):
        doc = sel.Object.Document
        for sub in sel.SubElementNames or [""]:
            path = sub.split(".")
            holder = sel.Object
            for part in path[:-1]:
                found = doc.getObject(part)
                if found is not None:
                    holder = found
            element = path[-1]
            if not element:
                continue
            field = next((f for f in rest if _accepts(f, element, holder)), None)
            if field is None:
                continue
            if holder.TypeId == "PartDesign::Body":
                holder = holder.Tip
            have = result.setdefault(field.name, [])
            if field.many or not have:
                have.append((holder, element))
    # a whole-object box took a feature only because its face was picked: when that face went to a
    # later box and another whole object was picked, the box keeps the other one
    if not first.many and isinstance(result.get(first.name), App.DocumentObject):
        whole = [s.Object for s in Gui.Selection.getSelectionEx()
                 if not any(n for n in s.SubElementNames)]
        if whole and result[first.name] not in whole:
            result[first.name] = whole[0]


class Command:
    def __init__(self, spec):
        self.spec = spec

    def GetResources(self):
        from . import icons
        return {"MenuText": self.spec.title, "ToolTip": self.spec.tip,
                "Pixmap": icons.pixmap_path(self.spec.icon, self.spec.pixmap)}

    def IsActive(self):
        doc = App.ActiveDocument
        if doc is None or Gui.Control.activeDialog():
            return False
        return ready(self.spec, doc)

    def Activated(self):
        picks = preselected(self.spec)
        # A body picked as the target of its own feature makes no sense: drop it
        make(self.spec, picks=picks)


def _widgets_alive(panel):
    """Every box of the page still exists (Qt has not deleted it with its page)."""
    try:
        import shiboken6 as _sb
    except ImportError:
        try:
            import shiboken2 as _sb
        except ImportError:
            return True
    try:
        for w in getattr(panel, "widgets", {}).values():
            for x in (w if isinstance(w, list) else [w]):
                if isinstance(x, QtCore.QObject) and not _sb.isValid(x):
                    return False
    except Exception:
        return False
    return True


def register(spec):
    try:
        if spec.command not in Gui.listCommands():
            Gui.addCommand(spec.command, Command(spec))
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s command not added (%s)\n" % (spec.title, error))

