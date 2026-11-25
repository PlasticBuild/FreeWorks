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
import math

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import asmcore as ac

V = App.Vector
LOADS_PROP = "FwLoads"
SPRINGS = ("Linear Spring", "Torsional Spring")
FORCES = ("Force", "Torque")


def _show(w, on):
    """Show or hide a field with its form label (no greyed controls)."""
    w.setVisible(on)
    p = w.parentWidget()
    lay = p.layout() if p is not None else None
    for form in ([lay] if lay is not None else []) + (p.findChildren(QtWidgets.QFormLayout) if p is not None else []):
        if isinstance(form, QtWidgets.QFormLayout):
            lab = form.labelForField(w)
            if lab is not None:
                lab.setVisible(on)
                return

def _prop(sim):
    if not hasattr(sim, LOADS_PROP):
        sim.addProperty("App::PropertyString", LOADS_PROP, "FreeCAD", "Springs, dampers, forces (json)")
        sim.setEditorMode(LOADS_PROP, 2)


def loads(sim):
    try:
        return json.loads(getattr(sim, LOADS_PROP, "") or "[]")
    except Exception:
        return []


def updated(asm, rows):
    ""

    doc = asm.Document
    out = []
    for r in rows:
        if r.get("kind") == "Linear Spring" and r.get("update") and r.get("a") and r.get("b"):
            try:
                ps = [doc.getObject(e[0]).Placement.multVec(V(*e[1])) for e in (r["a"], r["b"])]
                r = dict(r, free=(ps[0] - ps[1]).Length)
            except Exception as _fw_err:
                _fw_log("asmloads.py:updated", _fw_err)
        out.append(r)
    return out


def _save(sim, rows):
    _prop(sim)
    setattr(sim, LOADS_PROP, json.dumps(rows))


def _base(kind):
    return {"Contact": "Contact", "Linear Spring": "LinearSpring", "Torsional Spring": "TorsionalSpring", "Linear Damper": "LinearDamper",
            "Force": "Force", "Torque": "Torque"}[kind]


def add_load(sim, row):
    rows = loads(sim)
    if not row.get("name"):
        base = _base(row["kind"])
        used = {r["name"] for r in rows}
        n = 1
        while "%s%d" % (base, n) in used:
            n += 1
        row["name"] = "%s%d" % (base, n)
    rows = [r for r in rows if r["name"] != row["name"]] + [row]
    _save(sim, rows)
    return row["name"]


def remove_load(sim, name):
    _save(sim, [r for r in loads(sim) if r["name"] != name])


def local(comp, p):
    return list(comp.Placement.inverse().multVec(V(*p)))


def local_dir(comp, d):
    return list(comp.Placement.Rotation.inverted().multVec(V(*d)))


# ---------------------------------------------------------------- spring display
COIL = {"coil_d": 20.0, "coils": 10, "wire": 2.0}
DRAWN = {}      # doc name -> (view, SoSeparator)


def spring_points(row, comps, steps=24):
    """The drawn coil of a linear spring: a helix of row's coil diameter and coil count between its
    two ends (world points), or None."""
    if row.get("kind") != SPRINGS[0] or not row.get("a") or not row.get("b"):
        return None
    ends = []
    for e in (row["a"], row["b"]):
        c = comps.get(e[0])
        if c is None:
            return None
        ends.append(c.Placement.multVec(V(*e[1])))
    a, b = ends
    axis = b - a
    length = axis.Length
    if length < 1e-9:
        return None
    axis.normalize()
    u = axis.cross(V(0, 0, 1)) if abs(axis.z) < 0.9 else axis.cross(V(1, 0, 0))
    u.normalize()
    w = axis.cross(u)
    r = float(row.get("coil_d", COIL["coil_d"])) / 2.0
    n = max(1, int(row.get("coils", COIL["coils"])))
    import math
    lead = length * 0.06
    pts = [a, a + axis * lead]
    total = n * steps
    for k in range(total + 1):
        t = k / float(total)
        ang = 2 * math.pi * n * t
        pts.append(a + axis * (lead + (length - 2 * lead) * t) + u * (r * math.cos(ang)) + w * (r * math.sin(ang)))
    pts += [b - axis * lead, b]
    return pts


def draw_springs(asm, sim):
    ""

    if not App.GuiUp:
        return
    try:
        from pivy import coin
        from . import asmcore as ac
        doc = asm.Document
        gdoc = Gui.getDocument(doc.Name)
        view = getattr(gdoc, "ActiveView", None) if gdoc is not None else None
        if view is None or not hasattr(view, "getSceneGraph"):
            try:
                view = gdoc.activeView()
            except Exception:
                view = None
        if view is None or not hasattr(view, "getSceneGraph"):
            return
        root = view.getSceneGraph()
        old = DRAWN.get(doc.Name)
        if old is not None:
            try:
                old[0].getSceneGraph().removeChild(old[1])
            except Exception as _fw_err:
                _fw_log("asmloads.py:151", _fw_err)
            DRAWN.pop(doc.Name, None)
        comps = {c.Name: c for c in ac.components(asm)}
        rows = [r for r in (loads(sim) if sim is not None else []) if r.get("kind") == SPRINGS[0]]
        if not rows:
            return
        sep = coin.SoSeparator()
        sep.setName("FwSprings")
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        sep.addChild(pick)
        col = coin.SoBaseColor()
        col.rgb = (0.85, 0.65, 0.1)
        sep.addChild(col)
        for r in rows:
            pts = spring_points(r, comps)
            if not pts:
                continue
            sub = coin.SoSeparator()
            style = coin.SoDrawStyle()
            style.lineWidth = max(1.0, min(8.0, float(r.get("wire", COIL["wire"])) * 1.2))
            sub.addChild(style)
            co = coin.SoCoordinate3()
            co.point.setValues(0, len(pts), [(p.x, p.y, p.z) for p in pts])
            sub.addChild(co)
            ls = coin.SoLineSet()
            ls.numVertices.setValue(len(pts))
            sub.addChild(ls)
            sep.addChild(sub)
        root.addChild(sep)
        DRAWN[doc.Name] = (view, sep)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: spring display: %s\n" % error)


def clear_springs():
    for name, (view, sep) in list(DRAWN.items()):
        try:
            view.getSceneGraph().removeChild(sep)
        except Exception as _fw_err:
            _fw_log("asmloads.py:191", _fw_err)
        DRAWN.pop(name, None)


class _SpringWatch:
    """A spring's ends move with their components (a drag, a frame): the coil is drawn again."""
    pending = [False]

    def slotChangedObject(self, obj, prop):
        if prop != "Placement" or not DRAWN:
            return
        try:
            if obj.Document.Name not in DRAWN or self.pending[0]:
                return
        except Exception:
            return
        self.pending[0] = True
        QtCore.QTimer.singleShot(30, self._redraw)

    def _redraw(self):
        self.pending[0] = False
        try:
            from . import asmmotion as am
            p = am.pane()
            if p is not None:
                draw_springs(p.asm, p.sim)
            else:
                clear_springs()     # the Model tab: the study's springs aren't shown
        except Exception as _fw_err:
            _fw_log("asmloads.py:220", _fw_err)

    def slotDeletedDocument(self, doc):
        DRAWN.pop(doc.Name, None)


_watch = []


def watch_springs():
    if not _watch:
        _watch.append(_SpringWatch())
        App.addDocumentObserver(_watch[0])


# ---------------------------------------------------------------- physics (asmphysics calls these)
FUNCTIONS = ("Constant", "Step", "Harmonic", "Segments", "Data Points", "Expression")
BUILDER_FUNCTIONS = ("Segments", "Data Points", "Expression")      # edited in the Function Builder
_FUNC_CACHE = {}


def force_at(r, t):
    ""



    fn = r.get("function") or "Constant"
    if fn == "Step":
        t0, t1 = float(r.get("t0", 0.0)), float(r.get("t1", 1.0))
        f0, f1 = float(r.get("value0", 0.0)), float(r.get("value", 1.0))
        if t <= t0:
            return f0
        if t >= t1 or t1 <= t0:
            return f1
        u = (t - t0) / (t1 - t0)
        return f0 + (f1 - f0) * u * u * (3.0 - 2.0 * u)
    if fn == "Harmonic":
        return float(r.get("average", 0.0)) + float(r.get("value", 1.0)) * math.sin(
            math.radians(360.0 * float(r.get("freq", 1.0)) * t + float(r.get("phase", 0.0))))
    if fn in BUILDER_FUNCTIONS and r.get("func"):
        key = json.dumps(r["func"], sort_keys=True)
        y = _FUNC_CACHE.get(key)
        if y is None:
            from . import asmfunction
            try:
                y = asmfunction.y_of(r["func"])
            except ValueError:
                y = lambda _t: 0.0
            _FUNC_CACHE[key] = y
        return float(y(t))
    return float(r.get("value", 0.0))


def generalized(rows, s, x, v, place_of, comps, t=0.0):
    """The loads' push on body s at x (rad or mm) and speed v at time t: the generalized force in
    kg*mm/s^2 (slide) or kg*mm^2/s^2 (turn), by virtual work (force . d point / dx)."""
    name = s["comp"].Name
    out = 0.0
    eps = 1e-6
    for r in rows:
        kind = r.get("kind")
        if kind == "Contact":
            continue                                    # contact acts on the frames (contact_step)
        if kind == "Torsional Spring":
            if r["a"][0] == name and s["kind"] == "turn":
                k = float(r.get("k", 0.0))                 # N*mm/deg
                out -= 1000.0 * k * (math.degrees(x) - float(r.get("free", 0.0)))
                if r.get("damper"):
                    out -= 1000.0 * float(r.get("c", 0.0)) * math.degrees(v)
            continue
        if kind == "Torque":
            if r["a"][0] == name and s["kind"] == "turn":
                d = V(*r["dir"])
                d = s["place0"].Rotation.multVec(d)     # turns with the component; the axis does not move
                out += 1000.0 * force_at(r, t) * (-1 if r.get("reverse") else 1) * d.dot(s["axis"])
            continue
        ends = [r.get("a"), r.get("b")]
        if not any(e and e[0] == name for e in ends):
            continue

        def point(e, xx):
            comp = comps.get(e[0])
            if comp is None:
                return V(*e[1])
            plc = place_of(s, xx) if e[0] == name else comp.Placement
            return plc.multVec(V(*e[1]))

        if kind == "Force":
            p0, p1 = point(ends[0], x), point(ends[0], x + eps)
            plc = place_of(s, x)
            d = plc.Rotation.multVec(V(*r["dir"]))
            if d.Length > 0:
                d.normalize()
            f = 1000.0 * force_at(r, t) * (-1 if r.get("reverse") else 1)
            out += f * d.dot((p1 - p0) * (1.0 / eps))
            continue
        # Linear Spring / Linear Damper between two points
        mine = 0 if ends[0][0] == name else 1
        other = ends[1 - mine]

        def length(xx):
            return (point(ends[mine], xx) - point(other, xx)).Length

        L = length(x)
        dL = (length(x + eps) - L) / eps                # d length / dx
        f = 0.0                                         # N along the line, + pulls the ends together
        if kind == "Linear Spring":
            stretch = L - float(r.get("free", L))
            e = float(r.get("exp", 1.0))
            f += float(r.get("k", 0.0)) * math.copysign(abs(stretch) ** e, stretch)
            if r.get("damper"):
                rate = dL * v
                ce = float(r.get("cexp", 1.0))
                f += float(r.get("c", 0.0)) * math.copysign(abs(rate) ** ce, rate)
        elif kind == "Linear Damper":
            rate = dL * v
            e = float(r.get("exp", 1.0))
            f += float(r.get("c", 0.0)) * math.copysign(abs(rate) ** e, rate)
        out -= 1000.0 * f * dL
    return out


def _moved_shape(comp, plc):
    """comp's shape as it is with comp at plc."""
    try:
        sh = comp.Shape.copy()
    except Exception:
        return None
    if sh.isNull():
        return None
    sh.transformShape(plc.multiply(comp.Placement.inverse()).toMatrix(), True)
    return sh


def _moved_edge(comp, edge, plc):
    try:
        e = comp.Shape.getElement(edge).copy()
    except Exception:
        return None
    e.transformShape(plc.multiply(comp.Placement.inverse()).toMatrix(), True)
    return e


CURVE_TOUCH = 0.05      # mm: two contact curves this close touch


def curves_hit(r, s, x0, x1, others, place_of, comps):
    """Curves contact: s's curve reaches the other curve on the way from x0 to x1 (sampled)."""
    name = s["comp"].Name
    ends = r.get("curves") or []
    if len(ends) != 2 or name not in (ends[0][0], ends[1][0]):
        return False
    mine, other = (ends[0], ends[1]) if ends[0][0] == name else (ends[1], ends[0])
    oc = comps.get(other[0])
    if oc is None:
        return False
    oe = _moved_edge(oc, other[1], others.get(other[0], oc.Placement))
    if oe is None:
        return False
    def gap(xx):
        me = _moved_edge(s["comp"], mine[1], place_of(s, xx))
        if me is None:
            return None
        try:
            dist, pts, _i = me.distToShape(oe)
        except Exception:
            return None
        return dist, V(pts[0][1]) - V(pts[0][0])
    first = gap(x0)
    if first is None:
        return False
    if first[0] <= CURVE_TOUCH:
        return _closing(gap, x0, x1)
    for k in range(1, 9):
        g = gap(x0 + (x1 - x0) * k / 8.0)
        if g is None:
            return False
        if g[0] <= CURVE_TOUCH or g[1].dot(first[1]) < 0:   # touching, or passed through the other curve
            return True
    return False


def _closing(gap, x0, x1):
    """Already touching: a hit only while moving further in (the gap would turn round)."""
    a, b = gap(x0), gap(x0 + (x1 - x0) * 0.25)
    if a is None or b is None:
        return False
    return b[0] <= CURVE_TOUCH and (a[1].Length < 1e-9 or b[1].Length < 1e-9 or b[1].dot(a[1]) <= 0 or b[0] < a[0])


def contact_mu(r):
    """The contact's dynamic friction coefficient: from the two materials, or the number given."""
    if not r.get("friction"):
        return 0.0
    if r.get("materials"):
        from . import asmphysics
        m = r["materials"]
        return asmphysics.friction(m[0], m[1])
    return float(r.get("mu", 0.0))


STATIC_V = 0.1


def contact_static(r):
    """The contact's static friction coefficient, or None (only the dynamic one)."""
    if not r.get("friction") or r.get("materials") or not r.get("static"):
        return None
    return float(r.get("mus", 0.0))


def friction_at(mu, mus, v):
    """The coefficient at slip speed v: the static one at rest, easing to the dynamic one."""
    if mus is None:
        return mu
    import math
    return mu + (mus - mu) * math.exp(-(v / STATIC_V) ** 2)


def contact_touch(rows, s, x, others, place_of, comps, gap=0.2):
    """Friction: s's component rests on (or slides along) a contact set with friction. Returns
    (coefficient, contact point) or None."""
    name = s["comp"].Name
    mine = None
    for r in rows:
        if r.get("kind") != "Contact" or not r.get("friction") or r.get("type") == "Curves":
            continue
        if name not in r.get("comps", []):
            continue
        if mine is None:
            mine = _moved_shape(s["comp"], place_of(s, x))
            if mine is None:
                return None
        for o in r["comps"]:
            if o == name or o not in comps:
                continue
            other = _moved_shape(comps[o], others.get(o, comps[o].Placement))
            if other is None:
                continue
            bb = App.BoundBox(mine.BoundBox)
            bb.enlarge(gap)
            if not bb.intersect(other.BoundBox):
                continue
            try:
                dist, pts, _info = mine.distToShape(other)
            except Exception:
                continue
            if dist <= gap:
                return contact_mu(r), V(pts[0][0]) if pts else None, contact_static(r)
    return None


def contact_hit(rows, s, x, others, place_of, comps):
    """Solid Bodies contact: s's component at x overlaps a component of one of its contact sets
    (others: {name: Placement now}). Returns the coefficient of restitution of that set, or None."""
    name = s["comp"].Name
    mine = None
    for r in rows:
        if r.get("kind") != "Contact" or r.get("type") == "Curves" or name not in r.get("comps", []):
            continue
        if mine is None:
            mine = _moved_shape(s["comp"], place_of(s, x))
            if mine is None:
                return None
        for o in r["comps"]:
            if o == name or o not in comps:
                continue
            other = _moved_shape(comps[o], others.get(o, comps[o].Placement))
            if other is None or not mine.BoundBox.intersect(other.BoundBox):
                continue
            try:
                if mine.common(other).Volume > 1e-3:
                    return float(r.get("e", 0.5))
            except Exception:
                continue
    return None


# ---------------------------------------------------------------- picks
def pick_point(doc_name, obj_name, sub, pnt=None):
    """(component, world point, direction) of a pick: a vertex, an edge's centre (a circle's
    centre) and direction, or a face's centre and normal."""
    doc = App.getDocument(doc_name)
    asm = ac.assembly_of(doc)
    if asm is None:
        return None
    comps = {c.Name: c for c in ac.components(asm)}
    obj = doc.getObject(obj_name)
    comp, rest = None, sub or ""
    if obj is not None and obj.Name in comps:
        comp = obj
        rest = sub
        top = obj
        shape_sub = sub
    else:
        head = rest.split(".")[0]
        comp = comps.get(head)
        top = obj
        shape_sub = sub
    if comp is None:
        return None
    try:
        shape = top.getSubObject(shape_sub)
    except Exception:
        shape = None
    if shape is None or shape.isNull():
        return (comp, V(*pnt) if pnt else comp.Placement.Base, None)
    st = shape.ShapeType
    if st == "Vertex":
        return comp, shape.Point, None
    if st == "Edge":
        c = getattr(shape, "Curve", None)
        if c is not None and hasattr(c, "Center") and hasattr(c, "Axis"):
            return comp, V(c.Center), V(c.Axis)
        a, b = shape.Vertexes[0].Point, shape.Vertexes[-1].Point
        return comp, (a + b) * 0.5, (b - a)
    if st == "Face":
        u0, u1, v0, v1 = shape.ParameterRange
        n = shape.normalAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
        return comp, shape.CenterOfMass, n
    return comp, V(*pnt) if pnt else shape.CenterOfMass, None


class _Panel:
    """The shared PM bits: a pick list taking picks from the view while open."""

    def _picks(self, lay, name, rows=2):
        from . import asmpm
        w = QtWidgets.QListWidget()
        w.setObjectName(name)
        w.setStyleSheet(asmpm.PICK_STYLE)
        w.setFixedHeight(asmpm._rows(w, rows))
        lay.addWidget(w)
        return w

    def addSelection(self, doc, name, sub, pnt):
        if doc != self.asm.Document.Name:
            return
        got = pick_point(doc, name, sub, pnt)
        if got is not None:
            QtCore.QTimer.singleShot(0, lambda: self.add_pick(*got, label=(sub or name).split(".")[-1]))

    def removeSelection(self, *a):
        pass

    def setSelection(self, *a):
        pass

    def clearSelection(self, *a):
        pass

    def setPreselection(self, *a):
        pass

    def _observe(self):
        Gui.Selection.addObserver(self)

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmloads.py:542", _fw_err)
        Gui.Control.closeDialog()
        try:
            from . import asmmotion
            p = asmmotion.pane()
            if p is not None:
                p.refresh()
                p.frames, p.own = 0, None
        except Exception as _fw_err:
            _fw_log("asmloads.py:551", _fw_err)

    def reject(self):
        self._close()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _num(self, name, lo, hi, value, suffix, decimals=3):
        w = QtWidgets.QDoubleSpinBox()
        w.setObjectName(name)
        w.setRange(lo, hi)
        w.setDecimals(decimals)
        w.setSuffix(suffix)
        w.setValue(value)
        return w


class SpringPanel(_Panel):
    ""


    def __init__(self, asm, sim, row=None):
        from . import asmpm
        self.asm, self.sim, self.row = asm, sim, row or {}
        self.points = []
        box, lay = asmpm._box("Spring Type", "Spring", "MOTION_SPRING")
        self.kind = QtWidgets.QComboBox()
        self.kind.setObjectName("FW_SpringType")
        self.kind.addItems(SPRINGS)
        lay.addWidget(self.kind)
        from . import asmlook
        self.kind_buttons = asmlook.type_buttons(self.kind, lay)
        par, play = asmpm._box("Spring Parameters")
        self.pick_list = self._picks(play, "FW_SpringEnds")
        form = QtWidgets.QFormLayout()
        self.exp = QtWidgets.QComboBox()
        self.exp.setObjectName("FW_SpringExponent")
        self.exp.addItems(["1", "2", "3", "4"])
        self.k = self._num("FW_SpringK", 0.0, 1e9, 1.0, " N/mm")
        self.free = self._num("FW_SpringFree", -1e9, 1e9, 0.0, " mm")
        form.addRow("Exponent of spring force expression:", self.exp)
        form.addRow("Spring constant:", self.k)
        form.addRow("Free length:", self.free)
        play.addLayout(form)

        # the study is calculated (the box is hidden then, not greyed: the length it takes is shown)
        self.update_on = QtWidgets.QCheckBox("Update to model changes")
        self.update_on.setObjectName("FW_SpringUpdate")
        play.addWidget(self.update_on)
        self.update_note = QtWidgets.QLabel("")
        self.update_note.setObjectName("FW_SpringUpdateLength")
        self.update_note.setVisible(False)
        play.addWidget(self.update_note)
        self._free_form = form
        self.update_on.toggled.connect(self._update_shown)
        damp, dlay = asmpm._box("Damper")
        self.damper = QtWidgets.QCheckBox("Damper")
        self.damper.setObjectName("FW_SpringDamper")
        dlay.addWidget(self.damper)
        self.c = self._num("FW_SpringC", 0.0, 1e9, 0.0, " N/(mm/s)")
        self.cexp = QtWidgets.QComboBox()
        self.cexp.setObjectName("FW_SpringDamperExponent")
        self.cexp.addItems(["1", "2", "3", "4"])
        dform2 = QtWidgets.QFormLayout()
        dform2.addRow("Exponent of damper force expression:", self.cexp)
        dform2.addRow("Damping constant:", self.c)
        dlay.addLayout(dform2)
        self._damp_form = dform2
        self._damper_shown(False)           # shown with Damper (not greyed)
        self.damper.toggled.connect(self._damper_shown)
        disp, ylay = asmpm._box("Display")
        dform = QtWidgets.QFormLayout()
        self.coil_d = self._num("FW_SpringCoilDiameter", 0.1, 1e4, COIL["coil_d"], " mm", 2)
        self.coils = QtWidgets.QSpinBox()
        self.coils.setObjectName("FW_SpringCoils")
        self.coils.setRange(1, 200)
        self.coils.setValue(COIL["coils"])
        self.wire = self._num("FW_SpringWire", 0.01, 1e3, COIL["wire"], " mm", 2)
        dform.addRow("Coil diameter:", self.coil_d)
        dform.addRow("Number of coils:", self.coils)
        dform.addRow("Wire diameter:", self.wire)
        ylay.addLayout(dform)
        self.disp = disp
        self.form = [box, par, damp, disp]
        self.kind.currentTextChanged.connect(self._kind)
        if row:
            self.kind.setCurrentText(row["kind"])
            self.k.setValue(float(row.get("k", 1.0)))
            self.free.setValue(float(row.get("free", 0.0)))
            self.exp.setCurrentText(str(int(row.get("exp", 1))))
            self.damper.setChecked(bool(row.get("damper")))
            self.c.setValue(float(row.get("c", 0.0)))
            self.cexp.setCurrentText(str(int(row.get("cexp", 1))))
            self.update_on.setChecked(bool(row.get("update")))
            self.coil_d.setValue(float(row.get("coil_d", COIL["coil_d"])))
            self.coils.setValue(int(row.get("coils", COIL["coils"])))
            self.wire.setValue(float(row.get("wire", COIL["wire"])))
            for e in (row.get("a"), row.get("b")):
                if e:
                    comp = asm.Document.getObject(e[0])
                    self.points.append((e[0], e[1]))
                    self.pick_list.addItem(comp.Label if comp else "point")
        self._kind(self.kind.currentText())
        self._observe()

    def _damper_shown(self, on):
        for w in (self.cexp, self.c):
            _show(w, on)
            lab = self._damp_form.labelForField(w)
            if lab is not None:
                lab.setVisible(on)

    def _update_shown(self, on=None):
        on = self.update_on.isChecked() if on is None else on
        lab = self._free_form.labelForField(self.free)
        for w in (self.free, lab):
            if w is not None:
                w.setVisible(not on)
        L = self.length()
        self.update_note.setText("Free length: the endpoints' distance (now %.2f mm)" % L if len(self.points) >= 2
                                 else "Free length: the endpoints' distance")
        self.update_note.setVisible(on)

    def _kind(self, text):
        lin = text == SPRINGS[0]
        self.k.setSuffix(" N/mm" if lin else " N*mm/deg")
        self.free.setSuffix(" mm" if lin else " deg")
        self.c.setSuffix(" N/(mm/s)" if lin else " N*mm/(deg/s)")
        _show(self.exp, lin)                # no greyed controls: shown where they apply
        if hasattr(self, "update_on"):
            self.update_on.setVisible(lin)
            if not lin and self.update_on.isChecked():
                self.update_on.setChecked(False)
        if hasattr(self, "disp"):
            self.disp.setVisible(lin)

    def add_pick(self, comp, point, direction=None, label=""):
        need = 2 if self.kind.currentText() == SPRINGS[0] else 1
        if len(self.points) >= need:
            self.points.pop(0)
            self.pick_list.takeItem(0)
        self.points.append((comp.Name, local(comp, point)))
        self.pick_list.addItem("%s@%s" % (label, comp.Label) if label else comp.Label)
        if need == 2 and len(self.points) == 2 and not self.row:
            self.free.setValue(self.length())
        if hasattr(self, "update_on") and self.update_on.isChecked():
            self._update_shown(True)
        return len(self.points)

    def length(self):
        doc = self.asm.Document
        ps = [doc.getObject(n).Placement.multVec(V(*p)) for n, p in self.points[:2]]
        return (ps[0] - ps[1]).Length if len(ps) == 2 else 0.0

    def accept(self):
        lin = self.kind.currentText() == SPRINGS[0]
        if len(self.points) < (2 if lin else 1):
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Spring",
                                          "Pick the two spring endpoints." if lin else "Pick the turning component.")
            return False
        row = {"name": self.row.get("name"), "kind": self.kind.currentText(), "a": list(self.points[0]),
               "b": list(self.points[1]) if lin else None, "k": self.k.value(), "free": self.free.value(),
               "exp": int(self.exp.currentText()), "damper": self.damper.isChecked(), "c": self.c.value(),
               "cexp": int(self.cexp.currentText()), "update": lin and self.update_on.isChecked(),
               "coil_d": self.coil_d.value(), "coils": self.coils.value(), "wire": self.wire.value()}
        doc = self.asm.Document
        doc.openTransaction("Spring")
        try:
            self.name = add_load(self.sim, row)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        self._close()
        return True


class DamperPanel(_Panel):
    ""

    def __init__(self, asm, sim, row=None):
        from . import asmpm
        self.asm, self.sim, self.row = asm, sim, row or {}
        self.points = []
        box, lay = asmpm._box("Damper Parameters", "Damper", "MOTION_DAMPER")
        lay.addWidget(QtWidgets.QLabel("Linear Damper"))
        self.pick_list = self._picks(lay, "FW_DamperEnds")
        form = QtWidgets.QFormLayout()
        self.exp = QtWidgets.QComboBox()
        self.exp.setObjectName("FW_DamperExponent")
        self.exp.addItems(["1", "2", "3", "4"])
        self.c = self._num("FW_DamperC", 0.0, 1e9, 1.0, " N/(mm/s)")
        form.addRow("Exponent of damper force expression:", self.exp)
        form.addRow("Damping constant:", self.c)
        lay.addLayout(form)
        self.form = [box]
        if row:
            self.c.setValue(float(row.get("c", 1.0)))
            self.exp.setCurrentText(str(int(row.get("exp", 1))))
            for e in (row.get("a"), row.get("b")):
                if e:
                    self.points.append((e[0], e[1]))
                    self.pick_list.addItem(e[0])
        self._observe()

    def add_pick(self, comp, point, direction=None, label=""):
        if len(self.points) >= 2:
            self.points.pop(0)
            self.pick_list.takeItem(0)
        self.points.append((comp.Name, local(comp, point)))
        self.pick_list.addItem("%s@%s" % (label, comp.Label) if label else comp.Label)
        return len(self.points)

    def accept(self):
        if len(self.points) < 2:
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Damper", "Pick the two damper endpoints.")
            return False
        row = {"name": self.row.get("name"), "kind": "Linear Damper", "a": list(self.points[0]),
               "b": list(self.points[1]), "c": self.c.value(), "exp": int(self.exp.currentText())}
        doc = self.asm.Document
        doc.openTransaction("Damper")
        try:
            self.name = add_load(self.sim, row)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        self._close()
        return True


class ForcePanel(_Panel):
    ""



    def __init__(self, asm, sim, row=None):
        from . import asmpm
        self.asm, self.sim, self.row = asm, sim, row or {}
        self.where = None
        box, lay = asmpm._box("Type", "Force/Torque", "MOTION_FORCE")
        trow = QtWidgets.QHBoxLayout()
        self.force_r = QtWidgets.QRadioButton("Force")
        self.force_r.setObjectName("FW_ForceTypeForce")
        self.torque_r = QtWidgets.QRadioButton("Torque")
        self.torque_r.setObjectName("FW_ForceTypeTorque")
        self.force_r.setChecked(True)
        trow.addWidget(self.force_r)
        trow.addWidget(self.torque_r)
        lay.addLayout(trow)
        self.action = QtWidgets.QRadioButton("Action only")
        self.action.setObjectName("FW_ForceActionOnly")
        self.action.setChecked(True)
        lay.addWidget(self.action)
        lay.addWidget(QtWidgets.QLabel("Point of action and direction:"))
        self.pick_list = self._picks(lay, "FW_ForcePick", 1)
        self.reverse = QtWidgets.QCheckBox("Reverse Direction")
        self.reverse.setObjectName("FW_ForceReverse")
        lay.addWidget(self.reverse)
        fn, flay = asmpm._box("Force Function")
        self.function = QtWidgets.QComboBox()
        self.function.setObjectName("FW_ForceFunction")
        self.function.addItems(list(FUNCTIONS))
        flay.addWidget(self.function)
        form = QtWidgets.QFormLayout()
        self.fn_form = form
        self.value = self._num("FW_ForceValue", -1e9, 1e9, 1.0, " N")
        self.value0 = self._num("FW_ForceValue0", -1e9, 1e9, 0.0, " N")
        self.t0 = self._num("FW_ForceT0", 0.0, 1e6, 0.0, " sec")
        self.t1 = self._num("FW_ForceT1", 0.0, 1e6, 1.0, " sec")
        self.freq = self._num("FW_ForceFreq", 0.0, 1e6, 1.0, " Hz")
        self.phase = self._num("FW_ForcePhase", -360.0, 360.0, 0.0, " deg")
        self.average = self._num("FW_ForceAverage", -1e9, 1e9, 0.0, " N")
        for label, w in (("Initial value:", self.value0), ("Value:", self.value), ("Start time:", self.t0),
                         ("End time:", self.t1), ("Frequency:", self.freq), ("Phase shift:", self.phase),
                         ("Average value:", self.average)):
            form.addRow(label, w)
        flay.addLayout(form)
        self.func = None
        self.func_text = QtWidgets.QLabel()
        self.func_text.setObjectName("FW_ForceFunctionText")
        self.func_text.setWordWrap(True)
        flay.addWidget(self.func_text)
        self.func_btn = QtWidgets.QPushButton("Edit Function...")
        self.func_btn.setObjectName("FW_ForceEditFunction")
        self.func_btn.clicked.connect(lambda *_a: self.edit_function(modal=False))
        flay.addWidget(self.func_btn)
        self.torque_r.toggled.connect(lambda *_a: self._function_shown())
        self.function.currentIndexChanged.connect(self._function_picked)
        self.form = [box, fn]
        if row:
            (self.torque_r if row["kind"] == "Torque" else self.force_r).setChecked(True)
            self.value.setValue(float(row.get("value", 1.0)))
            self.function.setCurrentText(row.get("function") or "Constant")
            self.value0.setValue(float(row.get("value0", 0.0)))
            self.t0.setValue(float(row.get("t0", 0.0)))
            self.t1.setValue(float(row.get("t1", 1.0)))
            self.freq.setValue(float(row.get("freq", 1.0)))
            self.phase.setValue(float(row.get("phase", 0.0)))
            self.average.setValue(float(row.get("average", 0.0)))
            self.func = row.get("func")
            self.reverse.setChecked(bool(row.get("reverse")))
            self.where = (row["a"][0], row["a"][1], row["dir"])
            self.pick_list.addItem(row["a"][0])
        self._function_shown()
        self._observe()

    def _function_shown(self):
        ""
        fn = self.function.currentText()
        unit = " N*mm" if self.torque_r.isChecked() else " N"
        for w in (self.value, self.value0, self.average):
            w.setSuffix(unit)
        shown = {"Constant": (self.value,), "Step": (self.value0, self.value, self.t0, self.t1),
                 "Harmonic": (self.value, self.freq, self.phase, self.average)}.get(fn, ())
        for w in (self.value, self.value0, self.t0, self.t1, self.freq, self.phase, self.average):
            on = w in shown
            w.setVisible(on)
            self.fn_form.labelForField(w).setVisible(on)
        self.fn_form.labelForField(self.value).setText(
            {"Step": "Final value:", "Harmonic": "Amplitude:"}.get(fn, "Value:"))
        builder = fn in BUILDER_FUNCTIONS
        self.func_btn.setVisible(builder)
        self.func_text.setVisible(builder)
        if builder:
            from . import asmfunction
            ok = self.func and self.func.get("kind") == fn
            self.func_text.setText(asmfunction.summary(self.func) if ok else "Edit the function to set it.")

    def _function_picked(self, *_a):
        ""
        self._function_shown()
        if self.function.currentText() in BUILDER_FUNCTIONS and not (
                self.func and self.func.get("kind") == self.function.currentText()):
            QtCore.QTimer.singleShot(0, lambda: self.edit_function(modal=False))

    def _default_func(self, kind):
        big = 10.0
        if kind == "Segments":
            return {"kind": kind, "y": self._quantity(), "segments": [[0.0, 1.0, 0.0, big, "Cubic"], [1.0, 2.0, big, big, "Constant"]]}
        if kind == "Data Points":
            return {"kind": kind, "y": self._quantity(), "interpolation": "Linear", "points": [[0.0, 0.0], [1.0, big], [2.0, big]]}
        return {"kind": kind, "y": self._quantity(), "expression": "%g*SIN(2*PI*time)" % big}

    def _quantity(self):
        return "Torque" if self.torque_r.isChecked() else "Force"

    def edit_function(self, modal=True):
        from . import asmfunction
        kind = self.function.currentText()
        if kind not in BUILDER_FUNCTIONS:
            return None
        func = self.func if self.func and self.func.get("kind") == kind else self._default_func(kind)
        func = dict(func, y=self._quantity())
        out = asmfunction.edit(func, not self.force_r.isChecked(), float(getattr(self.sim, "bTimeEnd", 5.0) or 5.0),
                               modal, quantity=self._quantity())
        if not modal:
            out.accepted.connect(lambda: self._function_set(out.func))
            self.builder = out
            return out
        if out is not None:
            self._function_set(out)
        return out

    def _function_set(self, func):
        self.func = func
        self._function_shown()

    def add_pick(self, comp, point, direction=None, label=""):
        d = direction if direction is not None and direction.Length > 0 else V(0, 0, 1)
        self.where = (comp.Name, local(comp, point), local_dir(comp, d))
        self.pick_list.clear()
        self.pick_list.addItem("%s@%s" % (label, comp.Label) if label else comp.Label)
        return 1

    def accept(self):
        if self.where is None:
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Force/Torque", "Pick a face or an edge to act on.")
            return False
        kind = "Torque" if self.torque_r.isChecked() else "Force"
        fn = self.function.currentText()
        if fn in BUILDER_FUNCTIONS and not (self.func and self.func.get("kind") == fn):
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Force/Torque", "Edit the %s function first." % fn)
            return False
        row = {"name": self.row.get("name"), "kind": kind, "a": [self.where[0], self.where[1]], "dir": self.where[2],
               "value": self.value.value(), "reverse": self.reverse.isChecked(), "function": fn}
        if fn == "Step":
            row.update(value0=self.value0.value(), t0=self.t0.value(), t1=self.t1.value())
        elif fn == "Harmonic":
            row.update(freq=self.freq.value(), phase=self.phase.value(), average=self.average.value())
        elif fn in BUILDER_FUNCTIONS:
            row["func"] = dict(self.func, y=kind)
        doc = self.asm.Document
        doc.openTransaction("Force/Torque")
        try:
            self.name = add_load(self.sim, row)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        self._close()
        return True


class ContactPanel(_Panel):
    ""




    def __init__(self, asm, sim, row=None):
        from . import asmpm, asmphysics
        self.asm, self.sim, self.row = asm, sim, row or {}
        self.comps = []
        self.curves = []
        box, lay = asmpm._box("Contact Type", "Contact", "MOTION_CONTACT")
        trow = QtWidgets.QHBoxLayout()
        self.solid = QtWidgets.QRadioButton("Solid Bodies")
        self.solid.setObjectName("FW_ContactSolid")
        self.solid.setChecked(True)
        self.curve_r = QtWidgets.QRadioButton("Curves")
        self.curve_r.setObjectName("FW_ContactCurves")
        trow.addWidget(self.solid)
        trow.addWidget(self.curve_r)
        lay.addLayout(trow)
        sel, slay = asmpm._box("Selections")
        self.sel_label = QtWidgets.QLabel("Components:")
        slay.addWidget(self.sel_label)
        self.pick_list = self._picks(slay, "FW_ContactComponents", 4)
        mat, mlay = asmpm._box("Material")
        self.material = QtWidgets.QCheckBox("Material")
        self.material.setObjectName("FW_ContactMaterial")
        mlay.addWidget(self.material)
        self.mat1 = QtWidgets.QComboBox()
        self.mat1.setObjectName("FW_ContactMaterial1")
        self.mat2 = QtWidgets.QComboBox()
        self.mat2.setObjectName("FW_ContactMaterial2")
        for c in (self.mat1, self.mat2):
            c.addItems(asmphysics.MATERIALS)
            c.setVisible(False)
            mlay.addWidget(c)
        fr, flay = asmpm._box("Friction")
        self.friction = QtWidgets.QCheckBox("Friction")
        self.friction.setObjectName("FW_ContactFriction")
        self.friction.setChecked(True)
        flay.addWidget(self.friction)
        form = QtWidgets.QFormLayout()
        self.mu = self._num("FW_ContactMu", 0.0, 5.0, 0.25, "", 3)
        form.addRow("Dynamic friction coefficient:", self.mu)
        flay.addLayout(form)
        self.static = QtWidgets.QCheckBox("Static friction")
        self.static.setObjectName("FW_ContactStatic")
        flay.addWidget(self.static)
        sform = QtWidgets.QFormLayout()
        self.mus = self._num("FW_ContactMuStatic", 0.0, 5.0, 0.3, "", 3)
        sform.addRow("Static friction coefficient:", self.mus)
        flay.addLayout(sform)
        self.static.toggled.connect(self._materials)
        el, elay = asmpm._box("Elastic Properties")
        self.restitution_r = QtWidgets.QRadioButton("Coefficient of Restitution")
        self.restitution_r.setObjectName("FW_ContactRestitutionMode")
        self.restitution_r.setChecked(True)
        elay.addWidget(self.restitution_r)
        self.e = self._num("FW_ContactRestitution", 0.0, 1.0, 0.5, "", 2)
        elay.addWidget(self.e)
        self.form = [box, sel, mat, fr, el]
        self.material.toggled.connect(self._materials)
        self.friction.toggled.connect(self._materials)
        self.curve_r.toggled.connect(self._type)
        if row:
            self.e.setValue(float(row.get("e", 0.5)))
            self.friction.setChecked(bool(row.get("friction", False)))
            self.mu.setValue(float(row.get("mu", 0.25)))
            self.static.setChecked(bool(row.get("static", False)))
            self.mus.setValue(float(row.get("mus", 0.3)))
            if row.get("materials"):
                self.material.setChecked(True)
                self.mat1.setCurrentText(row["materials"][0])
                self.mat2.setCurrentText(row["materials"][1])
            if row.get("type") == "Curves":
                self.curve_r.setChecked(True)
                for n, edge in row.get("curves", []):
                    c = asm.Document.getObject(n)
                    if c is not None:
                        self.add_pick(c, None, None, edge)
            else:
                for n in row.get("comps", []):
                    c = asm.Document.getObject(n)
                    if c is not None:
                        self.add_pick(c, None)
        self._materials()
        self._type()
        self._observe()

    def _type(self, *_a):
        curves = self.curve_r.isChecked()
        self.sel_label.setText("Curves:" if curves else "Components:")
        self.pick_list.clear()
        items = ["%s@%s" % (e, n) for n, e in self.curves] if curves else list(self.comps)
        for it in items:
            self.pick_list.addItem(it)

    def _materials(self, *_a):
        on = self.material.isChecked()

        self.mat1.setVisible(on)
        self.mat2.setVisible(on)
        fr = self.friction.isChecked() and not on
        _show(self.mu, fr)
        self.static.setVisible(fr)
        _show(self.mus, fr and self.static.isChecked())

    def add_pick(self, comp, point=None, direction=None, label=""):
        if self.curve_r.isChecked():
            if not label.startswith("Edge"):
                return len(self.curves)
            if len(self.curves) >= 2:
                self.curves.pop(0)
            self.curves.append((comp.Name, label))
        elif comp.Name not in self.comps:
            self.comps.append(comp.Name)
        self._type()
        return len(self.curves) if self.curve_r.isChecked() else len(self.comps)

    def accept(self):
        curves = self.curve_r.isChecked()
        if curves and (len(self.curves) < 2 or self.curves[0][0] == self.curves[1][0]):
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Contact", "Pick two curves (edges) on two components.")
            return False
        if not curves and len(self.comps) < 2:
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Contact", "Pick at least two components.")
            return False
        row = {"name": self.row.get("name"), "kind": "Contact", "type": "Curves" if curves else "Solid Bodies",
               "comps": [n for n, _e in self.curves] if curves else list(self.comps),
               "curves": [list(c) for c in self.curves] if curves else None,
               "e": self.e.value(), "friction": self.friction.isChecked(), "mu": self.mu.value(),
               "static": self.static.isChecked(), "mus": self.mus.value(),
               "materials": [self.mat1.currentText(), self.mat2.currentText()] if self.material.isChecked() else None}
        doc = self.asm.Document
        doc.openTransaction("Contact")
        try:
            self.name = add_load(self.sim, row)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        self._close()
        return True


OPEN = []
PANELS = {"Linear Spring": SpringPanel, "Torsional Spring": SpringPanel, "Linear Damper": DamperPanel,
          "Force": ForcePanel, "Torque": ForcePanel, "Contact": ContactPanel}


def open_panel(cls, asm, sim, row=None):
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    panel = cls(asm, sim, row)
    OPEN[:] = [panel]
    Gui.Control.showDialog(panel)
    return panel


def edit(asm, sim, name):
    row = next((r for r in loads(sim) if r["name"] == name), None)
    return open_panel(PANELS[row["kind"]], asm, sim, row) if row else None
