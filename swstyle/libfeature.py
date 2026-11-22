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
import os

import FreeCAD as App

LIB_FEATURE = "FwLibraryFeature"
SOURCE = "FwLibrarySource"
LINKED = "FwLibraryLinked"
STAMP = "FwLibraryStamp"
UNDEF = -2000
DIMENSIONAL = ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle")
FEATURE_VALUES = ("Length", "Length2", "Angle", "Radius", "Size", "Depth")


# --------------------------------------------------------------------------- constraints as data
def _record(c):
    return {"type": c.Type, "a": [c.First, c.FirstPos, c.Second, c.SecondPos, c.Third, c.ThirdPos],
            "value": c.Value, "name": c.Name, "driving": getattr(c, "Driving", True)}


def _rebuild(rec, geo):
    """A Sketcher constraint from a record; geo maps a record's GeoId to the sketch's one."""
    import Sketcher
    t, v = rec["type"], rec["value"]
    F, FP, S, SP, T, TP = rec["a"]
    F, S, T = geo(F), geo(S), geo(T)
    if t == "Coincident":
        args = (F, FP, S, SP)
    elif t == "PointOnObject":
        args = (F, FP, S)
    elif t in ("Distance", "DistanceX", "DistanceY"):
        if S == UNDEF:
            args = (F, v) if FP == 0 else (F, FP, v)
        elif SP == 0:
            args = (F, FP, S, v)
        else:
            args = (F, FP, S, SP, v)
    elif t == "Angle":
        args = (F, v) if S == UNDEF else ((F, S, v) if FP == 0 else (F, FP, S, SP, v))
    elif t in ("Radius", "Diameter"):
        args = (F, v)
    elif t in ("Horizontal", "Vertical"):
        args = (F,) if S == UNDEF else (F, FP, S, SP)
    elif t == "Symmetric":
        args = (F, FP, S, SP, T) if TP == 0 else (F, FP, S, SP, T, TP)
    elif t in ("Parallel", "Perpendicular", "Equal", "Tangent"):
        args = (F, S) if FP == 0 else (F, FP, S, SP)
    else:
        return None
    if t in DIMENSIONAL and t != "Angle":
        args = tuple(App.Units.Quantity(a, App.Units.Length) if i == len(args) - 1 else a
                     for i, a in enumerate(args))
    return Sketcher.Constraint(t, *args)


def _touches_external(c):
    return any(g is not None and g <= -3 and g != UNDEF for g in (c.First, c.Second, c.Third))


def _edge_kind(edge):
    try:
        return type(edge.Curve).__name__
    except Exception:
        return "Edge"


# --------------------------------------------------------------------------- making a library feature
def split_sketch(src, copy):
    """The copy's references (its external geometry) taken out and kept: [(refs), (locating)].
    Called before the copy's external geometry is cleared."""
    refs, locating = [], []
    for i, (obj, subs) in enumerate(getattr(src, "ExternalGeometry", []) or []):
        for sub in (subs if isinstance(subs, (list, tuple)) else [subs]):
            try:
                el = obj.Shape.getElement(sub)
                kind, length = _edge_kind(el), round(getattr(el, "Length", 0.0), 3)
            except Exception:
                kind, length = "Edge", 0.0
            refs.append({"sketch": copy.Name, "index": len(refs), "ext": i, "kind": kind, "length": length,
                         "was": "%s.%s" % (obj.Label, sub)})
    for k, c in enumerate(src.Constraints):
        if _touches_external(c):
            rec = _record(c)
            rec["sketch"] = copy.Name
            rec["label"] = c.Name or "%s@%s" % ("D%d" % (k + 1) if c.Type in DIMENSIONAL else c.Type, src.Label)
            locating.append(rec)
    return refs, locating


def mark_library(body, sources, copies):
    """Library body: references and locating dimensions from the source sketches; the copies'
    external geometry cleared."""
    all_refs, all_loc = [], []
    for s, c in zip(sources, copies):
        if not s.TypeId.startswith("Sketcher::"):
            continue
        refs, loc = split_sketch(s, c)
        base = len(all_refs)
        for r in refs:
            r["index"] = base + r["index"]
        for rec in loc:
            rec["refbase"] = base
        all_refs += refs
        all_loc += loc
        # constraints to external geometry go with it; the sketch's own stay
        for k in reversed(range(len(c.Constraints))):
            if _touches_external(c.Constraints[k]):
                c.delConstraint(k)
        for i in reversed(range(len(refs))):
            try:
                c.delExternal(i)
            except Exception as _fw_err:
                _fw_log("libfeature.py:144", _fw_err)
    for prop, value in (("LibReferences", all_refs), ("LibLocating", all_loc)):
        if prop not in body.PropertiesList:
            body.addProperty("App::PropertyString", prop, "FreeCAD", "Library feature " + prop[3:].lower())
        setattr(body, prop, json.dumps(value))
    return all_refs, all_loc


def references(lib_body):
    try:
        return json.loads(getattr(lib_body, "LibReferences", "") or "[]")
    except ValueError:
        return []


def locating(lib_body):
    try:
        return json.loads(getattr(lib_body, "LibLocating", "") or "[]")
    except ValueError:
        return []


def dimensions(objs):
    """[(label, object, key, value)]: the feature's own sizes. key is "Constraints.<i>" or a property."""
    out = []
    for o in objs:
        if o.TypeId.startswith("Sketcher::"):
            for i, c in enumerate(o.Constraints):
                if c.Type in DIMENSIONAL and getattr(c, "Driving", True) and not _touches_external(c):
                    v = c.Value if c.Type != "Angle" else c.Value * 57.29577951308232
                    out.append(("%s@%s" % (c.Name or "D%d" % (i + 1), o.Label), o, "Constraints.%d" % i, round(v, 6)))
        else:
            for p in FEATURE_VALUES:
                if p == "Length2" and getattr(o, "Type", "") != "TwoLengths":
                    continue
                if p in o.PropertiesList and hasattr(getattr(o, p), "Value"):
                    out.append(("%s@%s" % (p, o.Label), o, p, round(getattr(o, p).Value, 6)))
    return out


def set_dimension(obj, key, value):
    if key.startswith("Constraints."):
        i = int(key.split(".", 1)[1])
        c = obj.Constraints[i]
        q = App.Units.Quantity("%s deg" % value) if c.Type == "Angle" else App.Units.Quantity(value, App.Units.Length)
        obj.setDatum(i, q)
    else:
        setattr(obj, key, value)


# --------------------------------------------------------------------------- putting it on a part
def apply_references(copies, lib_body, picks, values=None):
    """References picked (one (object, "EdgeN") per library reference, or None) back into the
    copied sketches, and the locating dimensions on them (values: {label: new value})."""
    values = values or {}
    refs = references(lib_body)
    by_name = {c.Name: c for c in copies}
    names = {}
    for o in copies:
        names[getattr(o, "FwLibraryOriginal", o.Name)] = o
    made = {"references": 0, "locating": 0, "skipped": []}
    new_ext = {}                                     # library reference index -> GeoId in its sketch
    for r in refs:
        pick = picks[r["index"]] if r["index"] < len(picks) else None
        sk = names.get(r["sketch"]) or by_name.get(r["sketch"])
        if pick is None or sk is None:
            continue
        obj, sub = pick
        try:
            before = len(sk.ExternalGeo) - 2          # the sketch's H and V axes come first
        except Exception:
            before = sum(len(subs) if isinstance(subs, (list, tuple)) else 1 for _o, subs in sk.ExternalGeometry or [])
        sk.addExternal(obj.Name, sub)
        new_ext[r["index"]] = -3 - before
        made["references"] += 1
    for rec in locating(lib_body):
        sk = names.get(rec["sketch"]) or by_name.get(rec["sketch"])
        if sk is None:
            continue
        base = rec.get("refbase", 0)
        ok = [True]

        def geo(g, base=base):
            if g is None or g == UNDEF or g > -3:
                return g
            idx = base + (-3 - g)
            if idx not in new_ext:
                ok[0] = False
                return g
            return new_ext[idx]
        rec2 = dict(rec)
        if rec["label"] in values:
            v = float(values[rec["label"]])
            rec2["value"] = v if rec["type"] != "Angle" else v / 57.29577951308232
        _side(sk, rec2, geo)
        c = _rebuild(rec2, geo)
        if c is None or not ok[0]:
            made["skipped"].append(rec["label"])
            continue
        k = sk.addConstraint(c)
        if rec.get("name"):
            try:
                sk.renameConstraint(k, rec["name"])
            except Exception as _fw_err:
                _fw_log("libfeature.py:248", _fw_err)
        made["locating"] += 1
    return made


def _side(sk, rec, geo):
    ""

    if rec["type"] not in ("DistanceX", "DistanceY"):
        return
    F, FP, S, SP, _T, _TP = rec["a"]
    if S is None or S == UNDEF or not FP or not SP:
        return
    try:
        sk.recompute()
        a, b = sk.getPoint(geo(F), FP), sk.getPoint(geo(S), SP)
    except Exception as _fw_err:
        _fw_log("libfeature.py:266", _fw_err)
        return
    now = (b - a).x if rec["type"] == "DistanceX" else (b - a).y
    if abs(now) > 1e-9 and (now < 0) != (rec["value"] < 0):
        rec["value"] = -rec["value"]


def mark_instance(copies, name, path, linked):
    for c in copies:
        for prop, kind, value in ((LIB_FEATURE, "App::PropertyString", name), (SOURCE, "App::PropertyFile", path),
                                  (LINKED, "App::PropertyBool", bool(linked)),
                                  (STAMP, "App::PropertyFloat", os.path.getmtime(path) if os.path.exists(path) else 0.0)):
            if prop not in c.PropertiesList:
                c.addProperty(kind, prop, "Library Feature", "")
            setattr(c, prop, value)


def instance_name(doc, path):
    base = os.path.splitext(os.path.basename(path))[0]
    used = {getattr(o, LIB_FEATURE, "") for o in doc.Objects}
    n = 1
    while "%s%d" % (base, n) in used:
        n += 1
    return "%s%d" % (base, n)


def members(obj):
    """The features of obj's library feature instance (not its tree row)."""
    name = getattr(obj, LIB_FEATURE, "")
    if not name:
        return []
    return [o for o in obj.Document.Objects if getattr(o, LIB_FEATURE, "") == name and not is_row(o)]


# --------------------------------------------------------------------------- the tree row
def is_row(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "LibraryRow"


def row_of(obj):
    """The Library Feature row an instance's member sits under, or None."""
    name = getattr(obj, LIB_FEATURE, "")
    if not name or is_row(obj):
        return obj if is_row(obj) else None
    return next((o for o in obj.Document.Objects if is_row(o) and getattr(o, LIB_FEATURE, "") == name), None)


class LibraryRow:
    ""


    def __init__(self, obj):
        obj.Proxy = self

    def execute(self, obj):
        base = obj.BaseFeature
        obj.Shape = base.Shape.copy() if base is not None and not base.Shape.isNull() else obj.Shape

    def onDocumentRestored(self, obj):
        obj.Proxy = self
        try:
            view = obj.ViewObject.Proxy if App.GuiUp and obj.ViewObject is not None else None
            if view is not None and getattr(view, "Object", None) is None:
                view.Object = obj           # FreeCAD 1.1 asks claimChildren before attach on restore
        except Exception as _fw_err:
            _fw_log("libfeature.py:329", _fw_err)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class LibraryRowView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def _object(self):
        obj = getattr(self, "Object", None)
        if obj is None:         # restored: FreeCAD 1.1 may ask before attach()
            for d in App.listDocuments().values():
                for o in d.Objects:
                    if is_row(o) and getattr(getattr(o, "ViewObject", None), "Proxy", None) is self:
                        self.Object = obj = o
                        break
        return obj

    def claimChildren(self):
        obj = self._object()
        if obj is None:
            return []
        try:
            return members(obj)
        except Exception:
            return []

    def getIcon(self):
        try:
            import tempfile
            from . import icons
            path = os.path.join(tempfile.gettempdir(), "swstyle-library-feature-64.png")   # hidpi-1119: 64 px
            if not os.path.exists(path):
                pm = icons.family("ASSEMBLY_LIBRARY").pixmap(64, 64)
                if pm.isNull():
                    return ""
                pm.save(path)
            return path
        except Exception:
            return ""

    def doubleClicked(self, vobj):
        try:
            import FreeCADGui as Gui
            Gui.Control.showDialog(EditPM(vobj.Object))
            return True
        except Exception:
            return False

    def onDelete(self, vobj, subs):
        """Deleting the row deletes the library feature: its members go with it (after the row)."""
        obj = vobj.Object
        doc, names = obj.Document, [o.Name for o in members(obj)]
        body = obj.getParentGeoFeatureGroup()

        def drop():
            for n in reversed(names):
                o = doc.getObject(n)
                if o is None:
                    continue
                try:
                    if body is not None and o in body.Group:
                        body.removeObject(o)
                    doc.removeObject(n)
                except Exception as error:
                    App.Console.PrintLog("FreeCAD: Library Feature delete: %s\n" % error)
            doc.recompute()
        try:
            from PySide import QtCore
            QtCore.QTimer.singleShot(0, drop)
        except Exception as _fw_err:
            _fw_log("libfeature.py:408", _fw_err)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def make_row(copies, name, path):
    """Puts the Library Feature row after the instance's last feature."""
    feats = [c for c in copies if c.TypeId.startswith("PartDesign::") and c.TypeId != "PartDesign::Body"]
    if not feats:
        return None
    body = feats[-1].getParentGeoFeatureGroup()
    if body is None:
        return None
    row = body.newObject("PartDesign::FeaturePython", "LibraryFeature")
    LibraryRow(row)
    if App.GuiUp and row.ViewObject is not None:
        LibraryRowView(row.ViewObject)
    row.Label = name
    mark_instance([row], name, path, getattr(feats[0], LINKED, False))
    try:
        row.BaseFeature = body.Tip if body.Tip is not None and body.Tip != row else feats[-1]
    except Exception as _fw_err:
        _fw_log("libfeature.py:435", _fw_err)
    body.Tip = row
    return row


def dissolve(obj):
    """Dissolve Library Feature: its features become plain features of the part and the row goes."""
    group = members(obj)
    row = row_of(obj)
    doc = obj.Document
    doc.openTransaction("Dissolve Library Feature")
    try:
        if row is not None:
            body = row.getParentGeoFeatureGroup()
            if body is not None:
                body.removeObject(row)          # the body joins the chain round it again
            doc.removeObject(row.Name)
        for o in group:
            for prop in (LIB_FEATURE, SOURCE, LINKED, STAMP):
                if prop in o.PropertiesList:
                    o.removeProperty(prop)
    finally:
        doc.commitTransaction()
    return len(group)


def out_of_date(obj):
    path = getattr(obj, SOURCE, "")
    return bool(getattr(obj, LINKED, False)) and path and os.path.exists(path) and \
        os.path.getmtime(path) > float(getattr(obj, STAMP, 0.0)) + 1e-6


def update_linked(obj):
    """Link to library part: the library file's sizes put on the instance again."""
    from . import designlib
    path = getattr(obj, SOURCE, "")
    src, opened = designlib._source(path)
    try:
        lib_body = next((o for o in src.Objects if hasattr(o, designlib.LIB_FEATURE)), None)
        if lib_body is None:
            return 0
        lib_dims = {lbl.split("@")[0] + "@" + o.Name: (key, v) for lbl, o, key, v in
                    dimensions([o for o in lib_body.Group])}
        n = 0
        for m in members(obj):
            orig = getattr(m, "FwLibraryOriginal", "")
            for lbl, o, key, v in dimensions([m]):
                k = lbl.split("@")[0] + "@" + orig
                if k in lib_dims and abs(lib_dims[k][1] - v) > 1e-9:
                    set_dimension(m, key, lib_dims[k][1])
                    n += 1
            m.FwLibraryStamp = os.path.getmtime(path)
        obj.Document.recompute()
        return n
    finally:
        if opened:
            designlib._close(src, obj.Document)


def insert(path, body, face_obj, face_name, point=None, picks=(), locating_values=None, overrides=None,
           linked=False, dissolve_after=False, name=None):
    """The whole insert: designlib.insert_feature, then references, locating dimensions, the
    overridden sizes and the instance marks."""
    from . import designlib
    src, opened = designlib._source(path)
    lib_body = next((o for o in src.Objects if hasattr(o, designlib.LIB_FEATURE)), None)
    lib_refs = references(lib_body) if lib_body is not None else []
    lib_loc = locating(lib_body) if lib_body is not None else []
    order = [o.Name for o in lib_body.Group if o.TypeId.startswith(("Sketcher::", "PartDesign::"))] if lib_body else []
    holder = type("Lib", (), {})()
    holder.LibReferences, holder.LibLocating = json.dumps(lib_refs), json.dumps(lib_loc)
    doc = body.Document
    doc.openTransaction("Library Feature")          # pkg245: the whole insert is one undo step
    copies = designlib.insert_feature(path, body, face_obj, face_name, point, transaction=False)      # extapps142: the library file stays open until the step is closed (closing a document ends the step)
    if not copies:
        doc.abortTransaction()
        if opened:
            designlib._close(src, doc)
        return None
    try:
        for c, n in zip(copies, order):
            if "FwLibraryOriginal" not in c.PropertiesList:
                c.addProperty("App::PropertyString", "FwLibraryOriginal", "Library Feature", "")
                c.setEditorMode("FwLibraryOriginal", 2)
            c.FwLibraryOriginal = n
        result = apply_references(copies, holder, list(picks), locating_values)
        doc.recompute()
        dims = dimensions(copies)                  # in the library's order: overrides go by row
        for row, value in (overrides or {}).items():
            if 0 <= int(row) < len(dims) and abs(dims[int(row)][3] - float(value)) > 1e-9:
                set_dimension(dims[int(row)][1], dims[int(row)][2], float(value))
        inst = name or instance_name(doc, path)
        if not dissolve_after:
            mark_instance(copies, inst, path, linked)
            make_row(copies, inst, path)
        doc.recompute()
    finally:
        doc.commitTransaction()
        if opened:
            designlib._close(src, doc)
    result["copies"] = copies
    result["name"] = inst
    return result


# =========================================================================== the PropertyManager
if App.GuiUp:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
    from . import pmboxes

    class InsertPM:
        def __init__(self, path, body, face_obj, face_name, point=None, edit=None):
            from . import designlib
            self.path, self.body, self.face = path, body, (face_obj, face_name)
            self.point, self.edit = point, edit
            src, opened = designlib._source(path)
            lib_body = next((o for o in src.Objects if hasattr(o, designlib.LIB_FEATURE)), None)
            self.refs = references(lib_body) if lib_body else []
            self.loc = locating(lib_body) if lib_body else []
            self.dims = [(lbl, v) for lbl, _o, _k, v in dimensions(list(lib_body.Group) if lib_body else [])]
            configs = ["Default"]
            if opened:
                designlib._close(src, body.Document)
            self.picks = [None] * len(self.refs)
            self.form = QtWidgets.QWidget()
            self.form.setObjectName("SWLibraryFeaturePM")
            self.form.setWindowTitle("Library Feature")
            self.form.setProperty("swstyle_pm_title", "Library Feature")
            lay = QtWidgets.QVBoxLayout(self.form)
            g = QtWidgets.QGroupBox("Library Feature")
            gl = QtWidgets.QFormLayout(g)
            self.name = QtWidgets.QLineEdit(os.path.splitext(os.path.basename(path))[0])
            self.link = QtWidgets.QCheckBox("Link to library part")
            self.link.setObjectName("SWLibraryLink")
            self.config = QtWidgets.QComboBox()
            self.config.addItems(configs)
            gl.addRow("Name", self.name)
            gl.addRow(self.link)
            gl.addRow("Configuration", self.config)
            lay.addWidget(g)
            g = QtWidgets.QGroupBox("Dimensions")
            gl = QtWidgets.QVBoxLayout(g)
            self.override = QtWidgets.QCheckBox("Override dimension values")
            self.override.setObjectName("SWLibraryOverride")
            self.dim_table = self._table(self.dims, "SWLibraryDimensions")
            self.dim_table.setEnabled(False)
            self.override.toggled.connect(self.dim_table.setEnabled)
            self.link.toggled.connect(lambda on: (self.override.setEnabled(not on),
                                                  self.dim_table.setEnabled(not on and self.override.isChecked())))
            gl.addWidget(self.override)
            gl.addWidget(self.dim_table)
            lay.addWidget(g)
            g = QtWidgets.QGroupBox("Locating Dimensions")
            gl = QtWidgets.QVBoxLayout(g)
            locs = [(r["label"], round(r["value"] * (57.29577951308232 if r["type"] == "Angle" else 1), 6))
                    for r in self.loc if r["type"] in DIMENSIONAL]
            self.loc_table = self._table(locs, "SWLibraryLocating")
            gl.addWidget(self.loc_table)
            lay.addWidget(g)
            g = QtWidgets.QGroupBox("References")
            gl = QtWidgets.QVBoxLayout(g)
            self.ref_list = QtWidgets.QListWidget()
            self.ref_list.setObjectName("SWLibraryReferences")
            pmboxes.mark(self.ref_list, True)
            for r in self.refs:
                self.ref_list.addItem(self._ref_text(r, None))
            gl.addWidget(QtWidgets.QLabel("Pick the edges the library feature asks for, in turn:"))
            gl.addWidget(self.ref_list)
            lay.addWidget(g)
            g = QtWidgets.QGroupBox("Options")
            gl = QtWidgets.QVBoxLayout(g)
            self.dissolve = QtWidgets.QCheckBox("Dissolve library feature")
            self.dissolve.setObjectName("SWLibraryDissolve")
            gl.addWidget(self.dissolve)
            lay.addWidget(g)
            self.msg = QtWidgets.QLabel("")
            self.msg.setWordWrap(True)
            lay.addWidget(self.msg)
            Gui.Selection.clearSelection()
            Gui.Selection.addObserver(self)

        def _table(self, rows, name):
            t = QtWidgets.QTableWidget(len(rows), 2)
            t.setObjectName(name)
            t.setHorizontalHeaderLabels(["Dimension", "Value"])
            t.horizontalHeader().setStretchLastSection(True)
            t.verticalHeader().setVisible(False)
            t.setMaximumHeight(24 + 24 * max(1, min(len(rows), 6)))
            for i, (lbl, v) in enumerate(rows):
                a = QtWidgets.QTableWidgetItem(lbl)
                a.setFlags(a.flags() & ~QtCore.Qt.ItemIsEditable)
                t.setItem(i, 0, a)
                t.setItem(i, 1, QtWidgets.QTableWidgetItem("%g" % v))
            return t

        def _ref_text(self, r, pick):
            want = "%s<%d> (%s%s)" % ("Edge", r["index"] + 1, r["kind"].replace("Geom", ""),
                                      ", %g mm" % r["length"] if r["length"] else "")
            return want + ("  =  %s %s" % (pick[0].Label, pick[1]) if pick else "")

        def addSelection(self, doc, name, sub, _pos):
            sub = (sub or "").split(".")[-1]
            if not sub.startswith(("Edge", "Vertex")):
                return
            try:
                i = self.picks.index(None)
            except ValueError:
                return
            obj = App.getDocument(doc).getObject(name)
            self.picks[i] = (obj, sub)
            self.ref_list.item(i).setText(self._ref_text(self.refs[i], self.picks[i]))

        def _values(self, table):
            out = {}
            for i in range(table.rowCount()):
                try:
                    out[table.item(i, 0).text()] = float(table.item(i, 1).text())
                except (ValueError, AttributeError) as _fw_err:
                    _fw_log("libfeature.py:652", _fw_err)
            return out

        def _stop(self):
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("libfeature.py:659", _fw_err)

        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

        def accept(self):
            if None in self.picks and self.msg.text() == "":
                self.msg.setText("Not every reference is picked: the feature stays where it was dropped. OK again "
                                 "to put it in anyway.")
                return False
            self._stop()
            loc = self._values(self.loc_table)
            over = {}
            if self.override.isChecked() and not self.link.isChecked():
                for i in range(self.dim_table.rowCount()):
                    try:
                        over[i] = float(self.dim_table.item(i, 1).text())
                    except (ValueError, AttributeError) as _fw_err:
                        _fw_log("libfeature.py:677", _fw_err)
            self.result = insert(self.path, self.body, self.face[0], self.face[1], self.point, self.picks, loc, over,
                                 self.link.isChecked(), self.dissolve.isChecked(), self.name.text().strip() or None)
            Gui.Control.closeDialog()
            return True

        def reject(self):
            self._stop()
            Gui.Control.closeDialog()
            return True

    def open_insert(path, body, face_obj, face_name, point=None):
        pm = InsertPM(path, body, face_obj, face_name, point)
        Gui.Control.showDialog(pm)
        return pm

    class EditPM:
        """Edit Library Feature: its sizes and locating dimensions changed in place."""

        def __init__(self, obj):
            self.group = members(obj)
            self.form = QtWidgets.QWidget()
            self.form.setObjectName("SWLibraryEditPM")
            self.form.setWindowTitle(getattr(obj, LIB_FEATURE, "Library Feature"))
            self.form.setProperty("swstyle_pm_title", getattr(obj, LIB_FEATURE, "Library Feature"))
            lay = QtWidgets.QVBoxLayout(self.form)
            self.rows = dimensions(self.group)
            self.table = QtWidgets.QTableWidget(len(self.rows), 2)
            self.table.setObjectName("SWLibraryEditDimensions")
            self.table.setHorizontalHeaderLabels(["Dimension", "Value"])
            for i, (lbl, _o, _k, v) in enumerate(self.rows):
                a = QtWidgets.QTableWidgetItem(lbl)
                a.setFlags(a.flags() & ~QtCore.Qt.ItemIsEditable)
                self.table.setItem(i, 0, a)
                self.table.setItem(i, 1, QtWidgets.QTableWidgetItem("%g" % v))
            lay.addWidget(QtWidgets.QLabel("Dimensions"))
            lay.addWidget(self.table)

        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

        def accept(self):
            doc = self.group[0].Document if self.group else App.ActiveDocument
            doc.openTransaction("Edit Library Feature")
            try:
                for i, (_lbl, o, k, v) in enumerate(self.rows):
                    try:
                        nv = float(self.table.item(i, 1).text())
                    except ValueError:
                        continue
                    if abs(nv - v) > 1e-9:
                        set_dimension(o, k, nv)
                doc.recompute()
            finally:
                doc.commitTransaction()
            Gui.Control.closeDialog()
            return True

        def reject(self):
            Gui.Control.closeDialog()
            return True

    def rc_entries(obj):
        """featurerc's rows for a library feature member."""
        if not getattr(obj, LIB_FEATURE, ""):
            return []
        if is_row(obj):
            group = members(obj)
            obj = group[0] if group else obj
        return [("EditLibraryFeature", "Edit Library Feature", lambda: Gui.Control.showDialog(EditPM(obj)), True),
                ("UpdateLibraryFeature", "Update Library Feature", lambda: update_linked(obj), out_of_date(obj)),
                ("DissolveLibraryFeature", "Dissolve Library Feature", lambda: dissolve(obj), True)]
