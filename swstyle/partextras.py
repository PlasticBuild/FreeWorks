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

T_CONFIGURE = "Configure Feature"
T_GO_TO_FEATURE = "Go To Feature (in Tree)"
T_FACE_PROPERTIES = "Face Properties..."
T_EDGE_PROPERTIES = "Edge Properties..."
T_BODY_PROPERTIES = "Body Properties..."
T_SELECT_CONNECTED = "Select Connected Faces"
T_PREVIOUS = "Previous Selection"
T_FEATUREWORKS = "Feature Recognition..."
T_RECOGNIZE = "Recognize Features..."
T_FW_OPTIONS = "Options..."
T_TOGGLE_FLAT = "Toggle flat display"
T_BEND_NOTES = "Insert bend notes"
T_REORDER_BENDS = "Reorder Bends"
T_EXIT_FLATTEN = "Exit Flatten"
T_FLATTEN = "Flatten"


def _mw():
    return Gui.getMainWindow()


def _shape_of(doc, name, sub):
    try:
        obj = App.getDocument(doc).getObject(name)
        return obj, obj.getSubObject(sub) if sub else obj.Shape
    except Exception:
        return None, None


def _select_subs(doc, name, prefix, subs):
    Gui.Selection.clearSelection()
    for s in subs:
        Gui.Selection.addSelection(doc, name, prefix + s)


def _prefix(sub):
    return sub[: len(sub) - len(sub.split(".")[-1])] if sub else ""


def _top_shape(doc, name, sub):
    """The whole shape the picked element belongs to (in the same placement as the pick)."""
    obj = App.getDocument(doc).getObject(name)
    pre = _prefix(sub)
    return obj.getSubObject(pre) if pre else obj.Shape


# --------------------------------------------------------------------------- selecting
def _face_index(shape, face):
    for i, f in enumerate(shape.Faces, 1):
        if f.isSame(face):
            return i
    return None


def _indexer(top):
    """Face -> its FaceN number, by hash first (a right-click on a big part asked every face in turn)."""
    faces = top.Faces
    by_hash = {}
    for i, f in enumerate(faces, 1):
        by_hash.setdefault(f.hashCode(), []).append((i, f))

    def index(face):
        for i, f in by_hash.get(face.hashCode(), ()):
            if f.isSame(face):
                return i
        return _face_index(top, face)
    return index


def tangent_faces(item, first=False):
    """The faces reached from the picked face over smooth (tangent) edges, the picked one first.
    first: stop at the first tangent neighbour (enough to know the menu needs Select Tangency)."""
    import Part
    doc, name, sub = item[:3]
    top = _top_shape(doc, name, sub)
    index = _indexer(top)
    start = top.getElement(sub.split(".")[-1])
    seen, todo, out = {index(start)}, [start], [start]
    while todo:
        f = todo.pop()
        for e in f.Edges:
            for g in top.ancestorsOfType(e, Part.Face):
                i = index(g)
                if i in seen:
                    continue
                if _smooth(f, g, e):
                    seen.add(i)
                    todo.append(g)
                    out.append(g)
                    if first:
                        return ["Face%d" % index(f) for f in out]
    return ["Face%d" % index(f) for f in out]


def _smooth(f, g, e):
    try:
        s1, s2 = f.Surface, g.Surface
        if type(s1).__name__ == "Plane" and type(s2).__name__ == "Plane":    # no projection needed
            a = s1.Axis.getAngle(s2.Axis)
            return a < 1e-3 or abs(a - 3.141592653589793) < 1e-3
        p = e.valueAt((e.FirstParameter + e.LastParameter) / 2.0)
        n1 = f.normalAt(*f.Surface.parameter(p))
        n2 = g.normalAt(*g.Surface.parameter(p))
        a = n1.getAngle(n2)
        return a < 1e-3 or abs(a - 3.141592653589793) < 1e-3
    except Exception:
        return False


def has_tangent(item):
    try:
        return len(tangent_faces(item, first=True)) > 1
    except Exception:
        return False


def _edge_dir(e, v):
    """The edge's unit tangent at vertex v, pointing along the edge away from v."""
    u0, u1 = e.FirstParameter, e.LastParameter
    at_start = e.valueAt(u0).distanceToPoint(v.Point) <= e.valueAt(u1).distanceToPoint(v.Point)
    d = e.tangentAt(u0 if at_start else u1)
    d = App.Vector(d)
    if d.Length < 1e-12:
        return None
    d.normalize()
    return d if at_start else d * -1


def tangent_edges(item, first=False):
    ""

    import Part
    doc, name, sub = item[:3]
    top = _top_shape(doc, name, sub)
    edges = top.Edges
    start = top.getElement(sub.split(".")[-1])
    index = lambda e: next((i for i, x in enumerate(edges, 1) if x.isSame(e)), None)
    seen, todo, out = {index(start)}, [start], [start]
    while todo:
        e = todo.pop()
        for v in e.Vertexes:
            mine = _edge_dir(e, v)
            if mine is None:
                continue
            for g in top.ancestorsOfType(v, Part.Edge):
                i = index(g)
                if i is None or i in seen:
                    continue
                other = _edge_dir(g, v)
                if other is None or mine.getAngle(other * -1) > 1e-3:
                    continue          # not running on in the same direction: a corner
                seen.add(i)
                todo.append(g)
                out.append(g)
                if first:
                    return ["Edge%d" % index(x) for x in out]
    return ["Edge%d" % index(x) for x in out]


def edge_has_tangent(item):
    try:
        return len(tangent_edges(item, first=True)) > 1
    except Exception:
        return False


def select_edge_tangency(item):
    doc, name, sub = item[:3]
    subs = tangent_edges(item)
    _select_subs(doc, name, _prefix(sub), subs)
    return subs


def select_face_tangency(item):
    doc, name, sub = item[:3]
    subs = tangent_faces(item)
    _select_subs(doc, name, _prefix(sub), subs)
    return subs


def select_connected_faces(item):
    ""

    import Part
    doc, name, sub = item[:3]
    top = _top_shape(doc, name, sub)
    start = top.getElement(sub.split(".")[-1])
    seen, todo = {_face_index(top, start)}, [start]
    while todo:
        f = todo.pop()
        for e in f.Edges:
            for g in top.ancestorsOfType(e, Part.Face):
                i = _face_index(top, g)
                if i not in seen:
                    seen.add(i)
                    todo.append(g)
    subs = ["Face%d" % i for i in sorted(seen)]
    _select_subs(doc, name, _prefix(sub), subs)
    return subs


def select_contour(item):
    """Contour Select Tool on the model: the outer loop of the picked face (an edge: the loops of
    its faces' outer wires that hold it)."""
    import Part
    doc, name, sub = item[:3]
    top = _top_shape(doc, name, sub)
    leaf = sub.split(".")[-1]
    el = top.getElement(leaf)
    if leaf.startswith("Face"):
        wire = el.OuterWire
    else:
        faces = top.ancestorsOfType(el, Part.Face)
        if not faces:
            return []
        wire = next((f.OuterWire for f in faces if any(x.isSame(el) for x in f.OuterWire.Edges)), faces[0].OuterWire)
    subs = []
    for e in wire.Edges:
        for i, x in enumerate(top.Edges, 1):
            if x.isSame(e):
                subs.append("Edge%d" % i)
                break
    _select_subs(doc, name, _prefix(sub), subs)
    return subs


class _ContourPick:
    """Contour Select Tool from empty space: the next face picked is turned into its outer loop."""

    def __init__(self):
        self.on = False
        self.busy = False

    def start(self):
        if not self.on:
            Gui.Selection.addObserver(self)
            self.on = True
        try:
            _mw().statusBar().showMessage("Contour Select Tool: pick a face to select its contour", 6000)
        except Exception as _fw_err:
            _fw_log("partextras.py:266", _fw_err)

    def stop(self):
        if self.on:
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("partextras.py:273", _fw_err)
        self.on = False

    def addSelection(self, doc, name, sub, point):
        if self.busy or not sub or not sub.split(".")[-1].startswith("Face"):
            return
        self.stop()
        QtCore.QTimer.singleShot(0, lambda: self._turn((doc, name, sub)))

    def _turn(self, item):
        self.busy = True
        try:
            select_contour(item)
        finally:
            self.busy = False


CONTOUR = _ContourPick()


def contour_select_tool(item=None):
    if item is not None:
        return select_contour(item)
    CONTOUR.start()
    return None


class _History:
    """Remembers the selection before the current one, for Previous Selection."""

    def __init__(self):
        self.last, self.previous = [], []
        self.on = False

    def watch(self):
        if not self.on:
            try:
                Gui.Selection.addObserver(self)
                self.on = True
            except Exception as _fw_err:
                _fw_log("partextras.py:313", _fw_err)

    def _now(self):
        out = []
        for s in Gui.Selection.getSelectionEx("", 0):
            out += [(s.DocumentName, s.ObjectName, n) for n in (s.SubElementNames or ("",))]
        return out

    def _changed(self, *args):
        now = self._now()
        if now and now != self.last:
            if self.last:
                self.previous = self.last
            self.last = now

    addSelection = removeSelection = setSelection = _changed

    def clearSelection(self, *args):
        if self.last:
            self.previous = self.last
        self.last = []


HISTORY = _History()


def has_previous():
    return bool(HISTORY.previous)


def previous_selection():
    picks = list(HISTORY.previous)
    if not picks:
        return False
    Gui.Selection.clearSelection()
    for doc, name, sub in picks:
        try:
            Gui.Selection.addSelection(doc, name, sub)
        except Exception as _fw_err:
            _fw_log("partextras.py:352", _fw_err)
    return True


# --------------------------------------------------------------------------- tree
def go_to_feature(feature):
    """Go To Feature (in Tree): the feature picked and its row scrolled into view."""
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(feature)
    for name in ("Std_TreeSelection",):
        try:
            Gui.runCommand(name, 0)
        except Exception as _fw_err:
            _fw_log("partextras.py:365", _fw_err)
    return True


# --------------------------------------------------------------------------- properties
def _row(form, label, text):
    v = QtWidgets.QLabel(text)
    v.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
    form.addRow(label, v)
    return v


def _len(x):
    try:
        return App.Units.Quantity(x, App.Units.Length).UserString
    except Exception:
        return "%.3f mm" % x


def _area(x):
    try:
        return App.Units.Quantity(x, App.Units.Area).UserString
    except Exception:
        return "%.3f mm^2" % x


class EntityProperties(QtWidgets.QDialog):
    ""


    def __init__(self, item, kind, parent=None):
        super().__init__(parent or _mw())
        self.setObjectName("SWEntityProperties")
        self.setWindowTitle("Entity Property")
        self.item, self.kind = item, kind
        doc, name, sub = item[:3]
        obj, el = _shape_of(doc, name, sub)
        lay = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        lay.addLayout(form)
        self.name = QtWidgets.QLineEdit(self._stored() or "%s<%s>" % (kind, sub.split(".")[-1][len(kind):]))
        self.name.setObjectName("SWEntityName")
        form.addRow("Name:", self.name)
        if el is not None:
            if kind == "Face":
                _row(form, "Type:", type(el.Surface).__name__)
                _row(form, "Area:", _area(el.Area))
                _row(form, "Perimeter:", _len(sum(e.Length for e in el.Edges)))
            else:
                _row(form, "Type:", type(el.Curve).__name__)
                _row(form, "Length:", _len(el.Length))
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _obj(self):
        doc, name, sub = self.item[:3]
        from . import partmenu
        return partmenu.owner_feature(doc, name, sub)

    def _key(self):
        return self.item[2].split(".")[-1]

    def _stored(self):
        obj = self._obj()
        names = list(getattr(obj, "FWEntityNames", []) or []) if obj is not None else []
        for n in names:
            k, _, v = n.partition("=")
            if k == self._key():
                return v
        return ""

    def apply(self):
        obj = self._obj()
        if obj is None:
            return False
        if "FWEntityNames" not in obj.PropertiesList:
            obj.addProperty("App::PropertyStringList", "FWEntityNames", "FreeCAD", "Names given to faces and edges")
            obj.setPropertyStatus("FWEntityNames", "Hidden")
        names = [n for n in obj.FWEntityNames if n.partition("=")[0] != self._key()]
        text = self.name.text().strip()
        if text:
            names.append("%s=%s" % (self._key(), text))
        obj.FWEntityNames = names
        return True


def entity_properties(item, kind):
    box = EntityProperties(item, kind)
    try:
        from . import fmmenu
        fmmenu._run_dialog(box, lambda b: b.apply())
    except Exception:
        if box.exec():
            box.apply()
    return box


def body_properties(feature):
    try:
        from . import fmmenu
        body = fmmenu.body_of(feature) or feature
        fmmenu.feature_properties(body, "Body Properties")
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s: %s\n" % (T_BODY_PROPERTIES, error))


def hide_body(feature):
    try:
        from . import fmmenu
        body = fmmenu.body_of(feature) or feature
        body.ViewObject.Visibility = False
        return body
    except Exception:
        return None


def delete_body(item):
    ""
    try:
        if "SWStyle_DeleteKeepBody" in Gui.listCommands():
            Gui.runCommand("SWStyle_DeleteKeepBody", 0)
            return True
    except Exception as _fw_err:
        _fw_log("partextras.py:490", _fw_err)
    return False


# --------------------------------------------------------------------------- Configure Feature
NUMERIC = ("App::PropertyLength", "App::PropertyDistance", "App::PropertyAngle", "App::PropertyFloat",
           "App::PropertyQuantity", "App::PropertyInteger", "App::PropertyFloatConstraint",
           "App::PropertyIntegerConstraint")


def feature_values(feature):
    """The values Configure Feature lists: Suppress, then the feature's own numbers."""
    out = []
    if "Suppressed" in feature.PropertiesList:
        out.append("Suppressed")
    for p in feature.PropertiesList:
        if feature.getTypeIdOfProperty(p) not in NUMERIC:
            continue
        if feature.getGroupOfProperty(p) in ("Base", "") or p in SKIP_VALUES:
            continue
        if feature.getEditorMode(p) and ("Hidden" in feature.getEditorMode(p) or "ReadOnly" in feature.getEditorMode(p)):
            continue
        out.append(p)
    return out


SKIP_VALUES = ("Placement", "Refine", "FuzzyTolerance", "AllowMultiFace", "Offset", "Midplane")


NEW_ROW = "<Creates a new configuration.>"


def _alias(feature, prop):
    return ("%s_%s" % (feature.Name, prop))[:60]


class ConfigureFeature(QtWidgets.QDialog):
    ""



    def __init__(self, feature, parent=None):
        super().__init__(parent or _mw())
        from . import configmanager
        self.setObjectName("SWConfigureFeature")
        self.setWindowTitle("Modify Configurations")
        self.feature = feature
        self.doc = feature.Document
        self.t = configmanager.table(self.doc)
        self.props = feature_values(feature)
        names = self.t.names() if self.t is not None else ["Default"]
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel(feature.Label))
        self.names = list(names)
        self.grid = QtWidgets.QTableWidget(len(names), len(self.props))
        self.grid.setObjectName("SWConfigureGrid")
        self.grid.setVerticalHeaderLabels(names)
        self.grid.setHorizontalHeaderLabels(["Suppress" if p == "Suppressed" else p for p in self.props])
        for r, cname in enumerate(names):
            for c, p in enumerate(self.props):
                v = self._current(cname, p)
                cell = QtWidgets.QTableWidgetItem()
                if p == "Suppressed":
                    cell.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)
                    cell.setCheckState(QtCore.Qt.Checked if v else QtCore.Qt.Unchecked)
                else:
                    cell.setText(str(v))
                self.grid.setItem(r, c, cell)
        self._new_row()
        self.grid.verticalHeader().sectionDoubleClicked.connect(self._name_row)
        lay.addWidget(self.grid)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(420, 200)

    def _new_row(self):
        ""
        r = self.grid.rowCount()
        self.grid.insertRow(r)
        self.grid.setVerticalHeaderItem(r, QtWidgets.QTableWidgetItem(NEW_ROW))
        for c, p in enumerate(self.props):
            cell = QtWidgets.QTableWidgetItem()
            cell.setFlags(QtCore.Qt.NoItemFlags)
            self.grid.setItem(r, c, cell)

    def name_row(self, name):
        """The new-configuration row gets a name: it becomes a row of its own (values as shown now)."""
        name = (name or "").strip()
        if not name or name in self.names:
            return False
        r = len(self.names)
        self.names.append(name)
        self.grid.setVerticalHeaderItem(r, QtWidgets.QTableWidgetItem(name))
        for c, p in enumerate(self.props):
            v = getattr(self.feature, p)
            cell = QtWidgets.QTableWidgetItem()
            if p == "Suppressed":
                cell.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)
                cell.setCheckState(QtCore.Qt.Checked if v else QtCore.Qt.Unchecked)
            else:
                cell.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEditable)
                cell.setText(str(self._number(p)))
            self.grid.setItem(r, c, cell)
        self._new_row()
        return True

    def _name_row(self, r):
        if r != len(self.names):
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Modify Configurations", "Configuration name:")
        if ok:
            self.name_row(name)

    def _number(self, p):
        v = getattr(self.feature, p)
        return v.Value if hasattr(v, "Value") else v

    def _current(self, cname, p):
        t = self.t
        if t is not None:
            col = self._column(p)
            row = t.row_of(cname)
            if col and row:
                text = str(t.sheet.getContents("%s%d" % (col, row))).lstrip("'=")
                if text != "":
                    if p == "Suppressed":
                        return text.strip().lower() in ("1", "true")
                    return text
        v = getattr(self.feature, p)
        return bool(v) if p == "Suppressed" else self._number(p)

    def _column(self, p):
        t = self.t
        alias = _alias(self.feature, p)
        for c in t.columns():
            try:
                if t.sheet.getAlias("%s%d" % (c, t.first - 1)) == alias:
                    return c
            except Exception as _fw_err:
                _fw_log("partextras.py:631", _fw_err)
        return None

    def apply(self):
        from . import configmanager
        doc = self.doc
        if self.t is None:
            self.t = configmanager.insert_table(doc)
        t = self.t
        sheet = t.sheet
        active = t.active()
        for name in self.names:
            if name not in t.names():
                configmanager.add(t, name)       # the new row's configuration, from the one shown
        if t.active() != active and active in t.names():
            configmanager.show(t, active)
        doc.openTransaction(T_CONFIGURE)
        try:
            head = t.first - 1
            for c, p in enumerate(self.props):
                col = self._column(p)
                if col is None:
                    cols = t.columns()
                    from .configmanager import _col, _colnum
                    col = _col((_colnum(cols[-1]) if cols else _colnum(t.col)) + 1)
                    sheet.set("%s%d" % (col, head), str(self._number(p) if p != "Suppressed" else 0))
                    sheet.setAlias("%s%d" % (col, head), _alias(self.feature, p))
                for r, cname in enumerate(self.names):
                    cell = self.grid.item(r, c)
                    row = t.row_of(cname)
                    if row is None:
                        continue
                    if p == "Suppressed":
                        sheet.set("%s%d" % (col, row), "1" if cell.checkState() == QtCore.Qt.Checked else "0")
                    else:
                        sheet.set("%s%d" % (col, row), cell.text())
            doc.recompute()
            configmanager._bind(t)
            for p in self.props:
                alias = _alias(self.feature, p)
                expr = "%s.%s" % (sheet.Name, alias)
                self.feature.setExpression(p, ("%s == 1" % expr) if p == "Suppressed" else expr)
            doc.recompute()
        finally:
            doc.commitTransaction()
        configmanager.refresh_all()
        return True


def configure_feature(feature):
    box = ConfigureFeature(feature)
    try:
        from . import fmmenu
        fmmenu._run_dialog(box, lambda b: b.apply())
    except Exception:
        if box.exec():
            box.apply()
    return box


# --------------------------------------------------------------------------- FeatureWorks
def recognize_features(feature):
    """FeatureWorks' Recognize Features: an imported solid (no feature history) becomes the base
    feature of a new Body, where features can be added; a part with history says so."""
    obj = feature
    try:
        from . import fmmenu
        body = fmmenu.body_of(feature)
    except Exception:
        body = None
    if body is not None:
        QtWidgets.QMessageBox.information(_mw(), "Feature Recognition",
                                          "%s already has features: nothing to recognize." % body.Label)
        return None
    doc = obj.Document
    doc.openTransaction(T_RECOGNIZE)
    try:
        new = doc.addObject("PartDesign::Body", "Body")
        new.BaseFeature = obj
        doc.recompute()
    finally:
        doc.commitTransaction()
    return new


class FeatureWorksOptions(QtWidgets.QDialog):
    ""

    def __init__(self, parent=None):
        super().__init__(parent or _mw())
        from . import paths
        self.p = paths.params()
        self.setObjectName("SWFeatureWorksOptions")
        self.setWindowTitle("Feature Recognition Options")
        lay = QtWidgets.QVBoxLayout(self)
        self.auto = QtWidgets.QRadioButton("Automatic")
        self.inter = QtWidgets.QRadioButton("Interactive")
        (self.auto if self.p.GetBool("FeatureWorksAutomatic", True) else self.inter).setChecked(True)
        self.prompt = QtWidgets.QCheckBox("Prompt to recognize features when a part is opened")
        self.prompt.setChecked(self.p.GetBool("FeatureWorksPrompt", False))
        for w in (self.auto, self.inter, self.prompt):
            lay.addWidget(w)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def apply(self):
        self.p.SetBool("FeatureWorksAutomatic", self.auto.isChecked())
        self.p.SetBool("FeatureWorksPrompt", self.prompt.isChecked())
        return True


def featureworks_options():
    box = FeatureWorksOptions()
    try:
        from . import fmmenu
        fmmenu._run_dialog(box, lambda b: b.apply())
    except Exception:
        if box.exec():
            box.apply()
    return box


# --------------------------------------------------------------------------- sheet metal
def sheet_metal_body(feature):
    """The sheet metal body the feature (or a Flat-Pattern) belongs to, else None."""
    try:
        from . import smflatten, fmmenu
        if smflatten.is_flat_pattern(feature):
            return feature.Body
        body = fmmenu.body_of(feature)
        return body if body is not None and smflatten.root(body) is not None else None
    except Exception:
        return None


def flat_on(body):
    try:
        from . import smflatten
        fp = smflatten.flat_pattern(body)
        return fp is not None and bool(fp.SWFlattened)
    except Exception:
        return False


def flatten(body, on):
    from . import smflatten
    return smflatten.set_flat(body, on)


_FLAT_PREVIEW = {}


def toggle_flat_display(body):
    """Toggle flat display: the flat pattern shown see-through next to the folded part, or gone."""
    from . import smflatten
    key = (body.Document.Name, body.Name)
    old = _FLAT_PREVIEW.pop(key, None)
    if old is not None:
        try:
            body.Document.removeObject(old)
        except Exception as _fw_err:
            _fw_log("partextras.py:794", _fw_err)
        return False
    fp = smflatten.ensure(body)
    was = bool(fp.SWFlattened)
    if not was:
        fp.SWFlattened = True
        fp.touch()
        body.Document.recompute()
    shape = fp.Shape.copy()
    if not was:
        fp.SWFlattened = False
        smflatten._show(fp, False)
    if shape.isNull():
        return False
    preview = body.Document.addObject("Part::Feature", "FlatDisplay")
    preview.Label = "Flat display"
    preview.Shape = shape
    try:
        preview.ViewObject.Transparency = 60
        preview.ViewObject.Selectable = False
    except Exception as _fw_err:
        _fw_log("partextras.py:815", _fw_err)
    _FLAT_PREVIEW[key] = preview.Name
    return True


def insert_bend_notes(fp):
    """Insert bend notes: a note at each bend line of the flat pattern (direction, angle, radius)."""
    lines = getattr(fp, "BendLines", None)
    shape = getattr(lines, "Shape", None)
    if shape is None or shape.isNull():
        return []
    doc = fp.Document
    base = None
    try:
        from . import smflatten
        base = smflatten.root(fp.Body)
    except Exception as _fw_err:
        _fw_log("partextras.py:832", _fw_err)
    r = getattr(base, "radius", None) or getattr(base, "Radius", None)
    rtext = (" R %s" % r.UserString) if hasattr(r, "UserString") else ""
    made = []
    doc.openTransaction(T_BEND_NOTES)
    try:
        for i, e in enumerate(shape.Edges, 1):
            mid = e.valueAt((e.FirstParameter + e.LastParameter) / 2.0)
            note = doc.addObject("App::AnnotationLabel", "BendNote")
            note.LabelText = ["UP 90°%s" % rtext]
            note.BasePosition = mid
            note.TextPosition = mid
            made.append(note)
    finally:
        doc.commitTransaction()
    return made


class ReorderBends(QtWidgets.QDialog):
    """Reorder Bends: the order the bends are made in, kept with the Flat-Pattern (for the bend
    notes and the bend table)."""

    def __init__(self, fp, parent=None):
        super().__init__(parent or _mw())
        self.fp = fp
        self.setObjectName("SWReorderBends")
        self.setWindowTitle(T_REORDER_BENDS)
        lay = QtWidgets.QVBoxLayout(self)
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("SWBendOrder")
        self.list.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        lines = getattr(getattr(fp, "BendLines", None), "Shape", None)
        n = len(lines.Edges) if lines is not None and not lines.isNull() else 0
        order = list(getattr(fp, "FWBendOrder", []) or [])
        names = order if len(order) == n else ["Bend%d" % i for i in range(1, n + 1)]
        self.list.addItems(names)
        lay.addWidget(self.list)
        row = QtWidgets.QHBoxLayout()
        for text, step in (("Up", -1), ("Down", 1)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(lambda _c=False, s=step: self.move(s))
            row.addWidget(b)
        lay.addLayout(row)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def move(self, step):
        r = self.list.currentRow()
        if r < 0 or not 0 <= r + step < self.list.count():
            return
        it = self.list.takeItem(r)
        self.list.insertItem(r + step, it)
        self.list.setCurrentRow(r + step)

    def apply(self):
        fp = self.fp
        if "FWBendOrder" not in fp.PropertiesList:
            fp.addProperty("App::PropertyStringList", "FWBendOrder", "Flat-Pattern", "The order of the bends")
        fp.FWBendOrder = [self.list.item(i).text() for i in range(self.list.count())]
        return True


def reorder_bends(fp):
    box = ReorderBends(fp)
    try:
        from . import fmmenu
        fmmenu._run_dialog(box, lambda b: b.apply())
    except Exception:
        if box.exec():
            box.apply()
    return box


# --------------------------------------------------------------------------- tree rows: extra entries
T_UNDERIVE = "Underive"
UNDERIVE = "SWStyle_UnderiveSketch"


def _underive(obj):
    try:
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(obj)
        if UNDERIVE in Gui.listCommands():
            Gui.runCommand(UNDERIVE, 0)
            return
        from . import derivedsketch
        derivedsketch.underive(obj)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Underive: %s\n" % error)


CUTLIST_KEEP = (None, "-", "Comment", "SaveSelection", "GoTo", "TreeItems", "Collapse", "Customize")


def cutlist_kind(target):
    """"folder" for the weldment Cut list(N) row, "item" for a Cut-List-Item row, else None."""
    name = type(getattr(target, "Proxy", None)).__name__
    return {"CutListFolder": "folder", "CutListItem": "item"}.get(name)


def _cutlist_bodies(target):
    from . import wecutlist
    if cutlist_kind(target) == "item":
        return [b for b in target.Bodies if b is not None]
    out = []
    for item in target.Items:
        out += [b for b in getattr(item, "Bodies", []) if b is not None and b not in out]
    return out


def _show_cutlist(bodies, on):
    for b in bodies:
        if getattr(b, "ViewObject", None) is not None:
            b.ViewObject.Visibility = on


def _isolate_bodies(bodies):
    doc = bodies[0].Document
    keep = set(b.Name for b in bodies)
    for o in doc.Objects:
        vo = getattr(o, "ViewObject", None)
        if vo is not None and hasattr(o, "Shape") and o.Name not in keep and vo.Visibility:
            vo.Visibility = False
    _show_cutlist(bodies, True)


def _auto_update(box):
    from . import wecutlist
    box.UpdateAutomatically = not box.UpdateAutomatically
    if box.UpdateAutomatically:
        wecutlist.update(box.Document, force=True)


def cutlist_items(target, items):
    ""



    from . import wecutlist
    kind = cutlist_kind(target)
    doc = target.Document
    bodies = _cutlist_bodies(target)
    shown = any(getattr(b, "ViewObject", None) is not None and b.ViewObject.Visibility for b in bodies)
    head = [i for i in items if i and i[0] is None][:1] or [(None, target.Label, None, False)]
    mine = []
    if kind == "folder":
        mine += [("CutListUpdate", "Update", lambda: wecutlist.update(doc, force=True), True),
                 ("CutListAuto", ("\u2713 " if target.UpdateAutomatically else "") + "Update Automatically",
                  lambda: _auto_update(target), True)]
    mine += [("CutListProperties", "Cut List Properties...", lambda: wecutlist.show_properties(doc), True),
             ("-", None, None, False),
             ("HideBodies", "Hide Bodies" if shown else "Show Bodies", lambda: _show_cutlist(bodies, not shown), bool(bodies)),
             ("IsolateBodies", "Isolate", lambda: _isolate_bodies(bodies), bool(bodies))]
    if kind == "item" and bodies:
        try:
            from . import featurerc
            mine.append(("InsertIntoNewPart", "Insert into New Part...",
                         lambda: featurerc.insert_into_new_part(bodies[0]), True))
        except Exception as _fw_err:
            _fw_log("partextras.py:993", _fw_err)

    try:
        box = wecutlist.folder(doc)
        if kind == "folder" and box is not None:
            wecutlist._ensure_box(box)
            mine += [("CutListCollapse", ("\u2713 " if box.CollapseItems else "") + "Collapse Cut List Items",
                      lambda: wecutlist.set_collapse(box, not box.CollapseItems), True),
                     ("CutListSaveBodies", "Save Bodies...", lambda: wecutlist.save_item_bodies(list(box.Items)),
                      bool(list(box.Items))),
                     # PATCH-MERGE (Features, weldments): Cut List Sorting Options
                     ("CutListSorting", "Sorting Options...", lambda: wecutlist.show_sorting(box), True)]
        elif kind == "item":
            wecutlist._ensure_item(target)
            picked = lambda: wecutlist._selected_items(target)
            mine += [("CutListExclude", ("\u2713 " if target.Excluded else "") + "Exclude from cut list",
                      lambda: wecutlist.set_excluded(target, not target.Excluded), True),
                     ("CutListSubweldment", "Create Sub-weldment", lambda: wecutlist.create_subweldment(picked()), True),
                     ("CutListSaveBodies", "Save Bodies...", lambda: wecutlist.save_item_bodies(picked()), bool(bodies))]
    except Exception as error:
        App.Console.PrintLog("FreeCAD: cut list items: %s\n" % error)
    rest = [i for i in items if i and i[0] in CUTLIST_KEEP and i[0] is not None]
    while rest and rest[0][0] == "-":
        rest = rest[1:]
    return head + mine + [("-", None, None, False)] + rest


def _flat_pattern_items(target, items):
    ""

    from . import smflatten
    flat = bool(getattr(target, "SWFlattened", False))
    body = getattr(target, "Body", None)
    mine = [("SMFlatten", "Unflatten" if flat else "Flatten", lambda: smflatten.toggle(body), body is not None),
            ("SMExportDXF", "Export to DXF / DWG", lambda: Gui.runCommand("SWStyle_SMExportDXF", 0),
             "SWStyle_SMExportDXF" in Gui.listCommands())]
    keys = set(i[0] for i in items if i)
    mine = [m for m in mine if m[0] not in keys]
    at = next((n + 1 for n, i in enumerate(items) if i and i[0] is None), 0)
    return list(items[:at]) + mine + list(items[at:])


MOLD_KEEP = (None, "-", "Comment", "SaveSelection", "GoTo", "TreeItems", "Collapse", "Customize", "Rename")


def mold_folder(target):
    try:
        from . import molds
        return target.TypeId == "App::DocumentObjectGroup" and target.Label in molds.FOLDERS
    except Exception:
        return False


def _folder_bodies(group):
    out = []
    for o in group.Group:
        if o.TypeId == "App::DocumentObjectGroup":
            out += _folder_bodies(o)
        elif hasattr(o, "Shape"):
            out.append(o)
    return out


def _mold_items(target, items):
    ""


    bodies = _folder_bodies(target)
    shown = any(getattr(b, "ViewObject", None) is not None and b.ViewObject.Visibility for b in bodies)
    head = [i for i in items if i and i[0] is None][:1] or [(None, target.Label, None, False)]
    mine = [("HideBodies", "Hide Bodies" if shown else "Show Bodies", lambda: _show_cutlist(bodies, not shown), bool(bodies)),
            ("IsolateBodies", "Isolate", lambda: _isolate_bodies(bodies), bool(bodies))]
    if bodies:
        try:
            from . import featurerc
            mine.append(("InsertIntoNewPart", "Insert into New Part...", lambda: featurerc.insert_into_new_part(bodies[0]), True))
        except Exception as _fw_err:
            _fw_log("partextras.py:1070", _fw_err)
    rest = [i for i in items if i and i[0] in MOLD_KEEP and i[0] is not None]
    while rest and rest[0][0] == "-":
        rest = rest[1:]
    return head + mine + [("-", None, None, False)] + rest


def sm_cutlist_kind(target):
    """"folder" for a sheet metal part's Cut list(N) row, "item" for its Sheet<N> rows, else None
    (look-audit smmenus-1120)."""
    name = type(getattr(target, "Proxy", None)).__name__
    return {"SMCutListFolder": "folder", "SMCutListItem": "item"}.get(name)


def sm_cutlist_items(target, items):
    ""


    from . import smcutlist
    kind = sm_cutlist_kind(target)
    doc = target.Document
    if kind == "item":
        bodies = [b for b in [getattr(target, "Body", None)] if b is not None]
    else:
        bodies = [i.Body for i in getattr(target, "Items", []) if getattr(i, "Body", None) is not None]
    shown = any(getattr(b, "ViewObject", None) is not None and b.ViewObject.Visibility for b in bodies)
    head = [i for i in items if i and i[0] is None][:1] or [(None, target.Label, None, False)]
    mine = []
    if kind == "folder":
        mine.append(("CutListUpdate", "Update", lambda: smcutlist.update(doc), True))
    mine += [("CutListProperties", "Cut List Properties...", lambda: smcutlist.show_properties(doc), True),
             ("-", None, None, False),
             ("HideBodies", "Hide Bodies" if shown else "Show Bodies", lambda: _show_cutlist(bodies, not shown), bool(bodies)),
             ("IsolateBodies", "Isolate", lambda: _isolate_bodies(bodies), bool(bodies))]
    if kind == "item" and bodies:
        try:
            from . import featurerc
            mine.append(("InsertIntoNewPart", "Insert into New Part...",
                         lambda: featurerc.insert_into_new_part(bodies[0]), True))
        except Exception as _fw_err:
            _fw_log("partextras.py:sm_cutlist_items", _fw_err)
    rest = [i for i in items if i and i[0] in CUTLIST_KEEP and i[0] is not None]
    while rest and rest[0][0] == "-":
        rest = rest[1:]
    return head + mine + [("-", None, None, False)] + rest


def tree_extras(target, items):
    ""

    if cutlist_kind(target):
        return cutlist_items(target, items)
    if sm_cutlist_kind(target):
        return sm_cutlist_items(target, items)
    if mold_folder(target):
        return _mold_items(target, items)
    try:
        from . import smflatten
        if smflatten.is_flat_pattern(target):
            return _flat_pattern_items(target, items)
    except Exception as _fw_err:
        _fw_log("partextras.py:1089", _fw_err)
    try:
        from . import derivedsketch
        derived = derivedsketch.is_derived(target)
    except Exception:
        derived = False
    if not derived or any(i and i[0] == "UnderiveSketch" for i in items):
        return items
    at = next((n + 1 for n, i in enumerate(items) if i and i[0] == "EditSketch"), None)
    if at is None:
        at = next((n + 1 for n, i in enumerate(items) if i and i[0] is None), 1)
    items = list(items)
    items.insert(at, ("UnderiveSketch", T_UNDERIVE, lambda o=target: _underive(o), True))
    return items


def hook_tree_extras():
    from . import fmmenu
    if getattr(fmmenu, "_fw_tree_extras", False):
        return
    original = fmmenu.entries

    def entries(shell, target, view=None, *more, **named):
        items = original(shell, target, view, *more, **named)
        try:
            return tree_extras(target, items)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: tree menu extras: %s\n" % error)
            return items

    fmmenu.entries = entries
    original_build = fmmenu.build

    def build(shell, target, *more, **named):
        menu = original_build(shell, target, *more, **named)
        try:
            if cutlist_kind(target) or sm_cutlist_kind(target) or mold_folder(target):
                # no feature context toolbar on a cut list row (Edit Feature, Suppress... do not apply)
                acts = menu.actions()
                if acts and isinstance(acts[0], QtWidgets.QWidgetAction):
                    menu.removeAction(acts[0])
                    if len(acts) > 1 and acts[1].isSeparator():
                        menu.removeAction(acts[1])
                    menu.row = None
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: cut list menu: %s\n" % error)
        return menu

    fmmenu.build = build
    fmmenu._fw_tree_extras = True
