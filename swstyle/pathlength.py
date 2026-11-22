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
from PySide import QtCore, QtWidgets

from . import contextbar, dimtools, relationspm, sketchtoolpm

PROP = "SWPathLengths"
TOLERANCE = 1e-7
LENGTH_TYPES = ("Distance",)


# --------------------------------------------------------------------------- the data
def paths(sketch):
    try:
        return json.loads(getattr(sketch, PROP, "") or "[]")
    except Exception:
        return []


def _save(sketch, items):
    if PROP not in sketch.PropertiesList:
        sketch.addProperty("App::PropertyString", PROP, "FreeCAD", "Path length dimensions")
        sketch.setEditorMode(PROP, 2)
    setattr(sketch, PROP, json.dumps(items))


def indices(sketch, ids):
    """Geometry indices of the ids, or None when one has gone."""
    lookup = {}
    for i in range(len(sketch.Geometry)):
        try:
            lookup[sketch.getGeometryId(i)] = i
        except Exception as _fw_err:
            _fw_log("pathlength.py:63", _fw_err)
    out = [lookup.get(i) for i in ids]
    return None if any(i is None for i in out) else out


def _length(sketch, i):
    return sketch.Geometry[i].toShape().Length


def total(sketch, idx):
    return sum(_length(sketch, i) for i in idx)


def _ends(sketch, i):
    kind = dimtools._kind(sketch.Geometry[i])
    if kind in ("circle", "ellipse", "point"):
        return []
    return [sketch.getPoint(i, 1), sketch.getPoint(i, 2)]


def chain(sketch, idx):
    """idx put in order along the chain they form, or None when they do not form one."""
    idx = list(dict.fromkeys(idx))
    if len(idx) == 1:
        return idx
    ends = {i: _ends(sketch, i) for i in idx}
    if any(not e for e in ends.values()):
        return None

    def touch(a, b):
        return any((p - q).Length < 1e-6 for p in ends[a] for q in ends[b])
    links = {i: [j for j in idx if j != i and touch(i, j)] for i in idx}
    if any(len(v) > 2 for v in links.values()):
        return None                      # a branch, not a chain
    starts = [i for i in idx if len(links[i]) == 1] or [idx[0]]
    order = [starts[0]]
    while len(order) < len(idx):
        nxt = [j for j in links[order[-1]] if j not in order]
        if not nxt:
            return None
        order.append(nxt[0])
    return order


def connected(sketch, i):
    ""
    out = [i]
    changed = True
    while changed:
        changed = False
        for j in range(len(sketch.Geometry)):
            if j in out or sketch.getConstruction(j) or not _ends(sketch, j):
                continue
            if any((p - q).Length < 1e-6 for k in out for p in _ends(sketch, k) for q in _ends(sketch, j)):
                out.append(j)
                changed = True
    return chain(sketch, out) or out


def _held(sketch, i):
    """True when a driving dimension already sets the length of entity i."""
    for c in sketch.Constraints:
        if not c.Driving or c.Type not in ("Distance", "DistanceX", "DistanceY"):
            continue
        if c.First == i and c.FirstPos == 0 and c.Second < -1999:
            return True
        if c.First == i and c.Second == i:
            return True
    return False


def _constraint(sketch, name):
    for k, c in enumerate(sketch.Constraints):
        if c.Name == name:
            return k
    return None


def _next_name(sketch):
    used = {p["name"] for p in paths(sketch)}
    k = 1
    while "PathLength%d" % k in used:
        k += 1
    return "PathLength%d" % k


def _absorb(sketch, idx, name):
    """Gives one entity of the chain a hidden length dimension named name; returns True when one
    could take it without over-defining the sketch."""
    import Sketcher
    for i in reversed(idx):
        if _held(sketch, i):
            continue
        k = sketch.addConstraint(Sketcher.Constraint("Distance", i, _length(sketch, i)))
        if sketch.solve() != 0 or sketch.ConflictingConstraints or sketch.RedundantConstraints:
            sketch.delConstraint(k)
            sketch.solve()
            continue
        sketch.renameConstraint(k, name)
        try:
            sketch.setVirtualSpace(k, True)
        except Exception as _fw_err:
            _fw_log("pathlength.py:165", _fw_err)
        return True
    return False


def apply(sketch, path):
    """Sets the hidden length so the chain has the path's length. Returns True when the sketch
    changed."""
    if path.get("value") is None:
        return False
    idx = indices(sketch, path["ids"])
    k = _constraint(sketch, path["name"])
    if idx is None or k is None:
        return False
    c = sketch.Constraints[k]
    held = c.First
    changed = False
    for _ in range(6):                     # the rest of the chain may follow the held entity
        rest = sum(_length(sketch, i) for i in idx if i != held)
        want = path["value"] - rest
        if want <= TOLERANCE:
            raise ValueError("%s is shorter than the rest of its chain" % path["name"])
        have = sketch.Constraints[k].Value
        if abs(have - want) < TOLERANCE:
            break
        sketch.setDatum(k, App.Units.Quantity(want, App.Units.Length))
        sketch.solve()
        changed = True
    return changed


def add(sketch, idx, value=None):
    """A new path length over the chain idx (driving at value, or driven). Returns (name, driving)."""
    order = chain(sketch, idx)
    if order is None:
        raise ValueError("The entities do not form one chain")
    name = _next_name(sketch)
    ids = [sketch.getGeometryId(i) for i in order]
    driving = value is not None and _absorb(sketch, order, name)
    items = paths(sketch)
    items.append({"name": name, "ids": ids, "value": float(value) if driving else None})
    _save(sketch, items)
    if driving:
        apply(sketch, items[-1])
    return name, driving


def update(sketch, name, value):
    """A new value for a path length (None: make it driven). Returns True when it drives."""
    items = paths(sketch)
    path = [p for p in items if p["name"] == name][0]
    k = _constraint(sketch, name)
    if value is None:
        if k is not None:
            sketch.delConstraint(k)
        path["value"] = None
        _save(sketch, items)
        return False
    idx = indices(sketch, path["ids"])
    if k is None and (idx is None or not _absorb(sketch, idx, name)):
        path["value"] = None
        _save(sketch, items)
        return False
    path["value"] = float(value)
    _save(sketch, items)
    apply(sketch, path)
    return True


def remove(sketch, name):
    k = _constraint(sketch, name)
    if k is not None:
        sketch.delConstraint(k)
    _save(sketch, [p for p in paths(sketch) if p["name"] != name])


def refresh(sketch):
    """Re-applies the driving path lengths; True when the sketch changed."""
    changed = False
    for path in paths(sketch):
        try:
            changed = apply(sketch, path) or changed
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s\n" % error)
    return changed


# --------------------------------------------------------------------------- following changes
class _Observer:
    """After a sketch with driving path lengths recomputes, their hidden lengths are set again
    (the rest of the chain may have changed) and the sketch recomputes once more."""

    def __init__(self):
        self.busy = False
        self.pending = set()

    def slotRecomputedObject(self, obj):
        if self.busy or PROP not in getattr(obj, "PropertiesList", ()):
            return
        if not any(p.get("value") is not None for p in paths(obj)):
            return
        self.pending.add((obj.Document.Name, obj.Name))
        QtCore.QTimer.singleShot(0, self.fix)

    def fix(self):
        todo, self.pending = self.pending, set()
        self.busy = True
        try:
            for doc_name, name in todo:
                doc = App.getDocument(doc_name) if doc_name in App.listDocuments() else None
                sketch = doc.getObject(name) if doc is not None else None
                if sketch is not None and refresh(sketch):
                    sketch.recompute()
        finally:
            self.busy = False


# --------------------------------------------------------------------------- drawing
class _Labels(QtCore.QObject):
    """Draws the path lengths of the sketch in edit."""

    def __init__(self):
        super().__init__()
        self.node = None
        self.view = None
        self.key = None
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(400)

    def tick(self):
        sketch = contextbar.sketch_in_edit()
        items = paths(sketch) if sketch is not None else []
        texts = []
        for p in items:
            idx = indices(sketch, p["ids"])
            if not idx:
                continue
            middle = idx[len(idx) // 2]
            where = sketch.getGlobalPlacement().multVec(sketch.Geometry[middle].toShape().valueAt(
                sketch.Geometry[middle].toShape().FirstParameter * 0.5 +
                sketch.Geometry[middle].toShape().LastParameter * 0.5))
            value = "Path %.2f mm" % total(sketch, idx)
            texts.append(((value if p.get("value") is not None else "(%s)" % value), where))
        key = tuple((t, round(w.x, 4), round(w.y, 4), round(w.z, 4)) for t, w in texts)
        if key == self.key:
            return
        self.key = key
        self.draw(texts)

    def draw(self, texts):
        self.clear()
        if not texts or Gui.ActiveDocument is None:
            return
        from pivy import coin
        view = Gui.ActiveDocument.ActiveView
        root = coin.SoAnnotation()
        root.setName("SWPathLengths")
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        root.addChild(pick)
        for text, where in texts:
            sep = coin.SoSeparator()
            colour = coin.SoBaseColor()
            colour.rgb.setValue(0.0, 0.2, 0.75) if not text.startswith("(") else colour.rgb.setValue(0.4, 0.4, 0.4)
            sep.addChild(colour)
            move = coin.SoTranslation()
            move.translation.setValue(where.x, where.y, where.z)
            sep.addChild(move)
            font = coin.SoFont()
            font.size = 14
            sep.addChild(font)
            label = coin.SoText2()
            label.string = text
            sep.addChild(label)
            root.addChild(sep)
        view.getSceneGraph().addChild(root)
        self.node, self.view = root, view

    def clear(self):
        if self.node is not None:
            try:
                self.view.getSceneGraph().removeChild(self.node)
            except Exception as _fw_err:
                _fw_log("pathlength.py:349", _fw_err)
        self.node = self.view = None


# --------------------------------------------------------------------------- the page
class PathLengthPage(sketchtoolpm.ToolPage):
    TITLE = "Path Length"
    ICON = "SKETCH_PATH_LENGTH_DIMENSION"
    PIXMAP = "Constraint_Length"
    TRANSACTION = "Path Length Dimension"

    def build(self):
        self.entities = []
        self.existing = None
        self._filling = True
        g = self.group("Path Length")
        self.which = QtWidgets.QComboBox(g.body)
        self.which.setObjectName("SWPathWhich")
        self.which.addItem("New path length")
        for p in paths(self.sketch):
            self.which.addItem(p["name"])
        self.which.setToolTip("Make a new path length, or change one of this sketch's")
        g.content.addWidget(self.which)
        g.content.addWidget(QtWidgets.QLabel("Path entities", g.body))
        self.list = QtWidgets.QListWidget(g.body)
        self.list.setObjectName("SWSelectedEntities")
        self.list.setFixedHeight(90)
        self.list.setProperty("swActive", True)
        g.content.addWidget(self.list)
        self.select_chain = QtWidgets.QPushButton("Select Chain", g.body)
        self.select_chain.setObjectName("SWPathSelectChain")
        self.select_chain.setToolTip("Adds every entity joined end to end with the ones picked")
        self.select_chain.clicked.connect(self._select_chain)
        g.content.addWidget(self.select_chain)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Length", g.body))
        self.value = QtWidgets.QDoubleSpinBox(g.body)
        self.value.setObjectName("SWPathValue")
        self.value.setRange(0.0, 1e7)
        self.value.setDecimals(3)
        self.value.setSuffix(" mm")
        self.value.setKeyboardTracking(False)
        row.addWidget(self.value, 1)
        g.content.addLayout(row)
        self.driven = QtWidgets.QCheckBox("Driven", g.body)
        self.driven.setObjectName("SWPathDriven")
        self.driven.setToolTip("Only show the length; on, the chain keeps whatever length it has")
        g.content.addWidget(self.driven)
        self.delete = QtWidgets.QPushButton("Delete Path Length", g.body)
        self.delete.setObjectName("SWPathDelete")
        self.delete.clicked.connect(self._delete)
        g.content.addWidget(self.delete)
        self.which.currentIndexChanged.connect(self._load)
        self.driven.toggled.connect(lambda on: self.value.setEnabled(not on))
        self._filling = False
        self.observer = sketchtoolpm.PickObserver(self)
        Gui.Selection.addObserver(self.observer)
        for sub in relationspm.picked_subs(self.sketch):
            self.picked(sub)
        self._load()

    def _names(self):
        return relationspm._entity_names(self.sketch.Geometry)

    def _show_entities(self):
        names = self._names()
        self.list.clear()
        self.list.addItems([names[i] for i in self.entities if 0 <= i < len(names)])
        if self.existing is None and not self._filling:
            self.value.blockSignals(True)
            self.value.setValue(total(self.sketch, self.entities) if self.entities else 0.0)
            self.value.blockSignals(False)
        if self.entities and chain(self.sketch, self.entities) is None:
            self.show_note("These entities do not form one chain.", True)
        elif self.entities:
            self.show_note("Total length %.3f mm." % total(self.sketch, self.entities))
        else:
            self.show_note("Pick the entities of the path, or one and Select Chain.")

    def _load(self, *args):
        k = self.which.currentIndex()
        items = paths(self.sketch)
        self.existing = items[k - 1]["name"] if k > 0 and k - 1 < len(items) else None
        self.delete.setVisible(self.existing is not None)
        self.list.setEnabled(self.existing is None)
        self.select_chain.setEnabled(self.existing is None)
        if self.existing is not None:
            path = items[k - 1]
            self.entities = indices(self.sketch, path["ids"]) or []
            self.value.setValue(total(self.sketch, self.entities) if self.entities else 0.0)
            self.driven.setChecked(path.get("value") is None)
        self._show_entities()

    def picked(self, sub):
        item = sketchtoolpm.item_of(self.sketch, sub)
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("pathlength.py:447", _fw_err)
        if self.existing is not None or item is None or item.geo < 0 or item.pos in (1, 2, 3):
            return
        if not _ends(self.sketch, item.geo):
            self.show_note("A path is made of lines, arcs and splines.", True)
            return
        if item.geo in self.entities:
            self.entities.remove(item.geo)
        else:
            self.entities.append(item.geo)
        self._show_entities()

    def selection_changed(self):
        pass

    def _select_chain(self):
        if self.entities:
            for i in connected(self.sketch, self.entities[0]):
                if i not in self.entities:
                    self.entities.append(i)
            self._show_entities()

    def _delete(self):
        if self.existing is None:
            return
        self.begin()
        remove(self.sketch, self.existing)
        sketchtoolpm._refresh(self.sketch)
        self.existing = None
        self.entities = []               # nothing more for the check to make
        self.accept()

    def finish(self):
        value = None if self.driven.isChecked() else self.value.value()
        if self.existing is not None:
            self.begin()
            drives = update(self.sketch, self.existing, value)
        elif self.entities:
            if chain(self.sketch, self.entities) is None:
                raise ValueError("the entities do not form one chain")
            self.begin()
            _, drives = add(self.sketch, self.entities, value)
        else:
            return
        if value is not None and not drives:
            App.Console.PrintMessage("Path Length: every entity's length is held, so it is driven\n")
        sketchtoolpm._refresh(self.sketch)


class _Command:
    def GetResources(self):
        return {"Pixmap": "Constraint_Length", "MenuText": "Path Length Dimension",
                "ToolTip": "The total length of a chain of sketch entities, driving or driven",
                "CmdType": "ForEdit"}

    def IsActive(self):
        return contextbar.sketch_in_edit() is not None

    def Activated(self):
        sketch = contextbar.sketch_in_edit()
        if sketch is not None:
            sketchtoolpm.open_page(PathLengthPage(sketch))


_observer = None
_labels = None


def register():
    global _observer, _labels
    if "SWStyle_PathLengthDimension" not in Gui.listCommands():
        Gui.addCommand("SWStyle_PathLengthDimension", _Command())
    if _observer is None:
        _observer = _Observer()
        App.addDocumentObserver(_observer)
    if _labels is None:
        _labels = _Labels()
