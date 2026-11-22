# SPDX-License-Identifier: LGPL-2.1-or-later
"""The last System Options rows with nothing behind them (Options audit, features/154):

Selection: Allow selection in wireframe and HLV modes (off: picks are dropped in those display
styles), Allow selection in HLR and shaded modes (on: a click on a face near an edge hidden behind
it picks that edge).
Display: Highlight all edges of features selected in graphics view (on: the picked feature's edges
light up), Use shaded face highlighting (off: a picked face is outlined).
Touch: Automatically pop up Selection tool while hunting for precise location (a touch held still
starts Magnified Selection).
Spin Box Increments: Time increments (the step of time boxes: motion study, timeline).
Messages: Display (potential) circular references in equations: "Equation dialog and FeatureManager"
marks features whose equations refer to each other in the tree.
Import: B-Rep mapping (on: re-importing a file over a part keeps the features built on it, the
imported body is replaced in place).
"""

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

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except ImportError:
    Gui = None

WIREFRAME = ("Fixed", "Allow selection in wireframe and HLV modes", True)
HLR = ("Fixed", "Allow selection in HLR and shaded modes", False)
FEATURE_EDGES = ("Fixed", "Highlight all edges of features selected in graphics view", False)
SHADED_FACES = ("Fixed", "Use shaded face highlighting", True)
TOUCH = ("Touch", "Automatically pop up Selection tool while hunting for precise location", True)
TIME_STEP = ("Spin Box Increments", "Time increments", "0.10s")
CIRCULAR = ("Messages/Errors/Warnings", "Display circular references in equations", "In equation dialog only")
POTENTIAL = ("Messages/Errors/Warnings", "Display potential circular references", "In equation dialog only")
BREP_MAP = ("Import", "B-Rep mapping", False)
TREE = "Equation dialog and FeatureManager"

_state = {"observer": None, "overlay": None, "busy": False, "touch": None}


def _kept(row):
    from . import optionspages
    return optionspages.stored(row[0], row[1], row[2])


def _shell():
    try:
        from . import shell
        return shell.shell()
    except Exception:
        return None


def draw_style():
    """'wireframe' (Wireframe, Hidden Lines Visible), 'hlr' (Hidden line) or 'shaded'."""
    try:
        from . import hlv
        if hlv.active():
            return "wireframe"
    except Exception as _fw_err:
        _fw_log("optionsextras5.py:71", _fw_err)
    try:
        mode = Gui.ActiveDocument.ActiveView.getViewer().getOverrideMode()
        if mode == "Wireframe":
            return "wireframe"
        if mode == "Hidden Line":
            return "hlr"
        if mode:
            return "shaded"
    except Exception as _fw_err:
        _fw_log("optionsextras5.py:81", _fw_err)
    sh = _shell()
    index = sh.draw_style_index() if sh is not None else None
    if index == 2:
        return "wireframe"
    if index == 3:
        return "hlr"
    return "shaded"


def time_step():
    """Spin Box Increments > Time increments, in seconds."""
    text = str(_kept(TIME_STEP)).strip().lower().rstrip("s").strip()
    try:
        v = float(text)
        return v if v > 0 else 0.1
    except Exception:
        return 0.1


# ---------------------------------------------------------------- overlays
def _lines_node(edges, colour, width):
    from pivy import coin
    sep = coin.SoSeparator()
    pick = coin.SoPickStyle()
    pick.style = coin.SoPickStyle.UNPICKABLE
    sep.addChild(pick)
    style = coin.SoDrawStyle()
    style.lineWidth = width
    sep.addChild(style)
    col = coin.SoBaseColor()
    col.rgb = colour
    sep.addChild(col)
    pts, counts = [], []
    for e in edges:
        try:
            line = [tuple(v) for v in e.discretize(Deflection=0.05)]
        except Exception:
            continue
        if len(line) > 1:
            pts.extend(line)
            counts.append(len(line))
    if not pts:
        return None
    co = coin.SoCoordinate3()
    co.point.setValues(0, len(pts), pts)
    ls = coin.SoLineSet()
    ls.numVertices.setValues(0, len(counts), counts)
    sep.addChild(co)
    sep.addChild(ls)
    return sep


def _clear_overlay():
    got = _state["overlay"]
    _state["overlay"] = None
    if got is not None:
        try:
            got[0].removeChild(got[1])
        except Exception as _fw_err:
            _fw_log("optionsextras5.py:141", _fw_err)


def _selection_colour():
    u = App.ParamGet("User parameter:BaseApp/Preferences/View").GetUnsigned("SelectionColor", 0x1CAD1CFF)
    return ((u >> 24) & 255) / 255.0, ((u >> 16) & 255) / 255.0, ((u >> 8) & 255) / 255.0


def refresh_overlay():
    """Feature edges (row on) and face outlines (shaded face highlighting off) for the selection."""
    _clear_overlay()
    if Gui is None or Gui.ActiveDocument is None:
        return
    edges = []
    try:
        sel = Gui.Selection.getSelectionEx("", 0)
    except Exception:
        sel = []
    feature_edges, outline = bool(_kept(FEATURE_EDGES)), not bool(_kept(SHADED_FACES))
    if not (feature_edges or outline):
        return
    for s in sel:
        for sub in s.SubElementNames or ():
            try:
                prefix, _, element = sub.rpartition(".")
                owner_shape = s.Object.getSubObject(prefix + ".", retType=0) if prefix else s.Object.Shape
                if owner_shape is None or not element:
                    continue
                if feature_edges:
                    edges += list(owner_shape.Edges)
                if outline and element.startswith("Face"):
                    edges += list(owner_shape.getElement(element).Edges)
            except Exception:
                continue
    if not edges:
        return
    node = _lines_node(edges, _selection_colour() if outline and not feature_edges else (0.3, 0.6, 1.0), 2)
    if node is None:
        return
    try:
        root = Gui.ActiveDocument.ActiveView.getSceneGraph()
        root.addChild(node)
        _state["overlay"] = (root, node)
    except Exception as _fw_err:
        _fw_log("optionsextras5.py:185", _fw_err)


# ---------------------------------------------------------------- picks
def _hidden_edge(obj, sub, pnt, reach=6.0):
    """The edge nearest the click on screen that the face hides (HLR/shaded pick-through)."""
    try:
        view = Gui.ActiveDocument.ActiveView
        shape = obj.Shape
        face = shape.getElement(sub)
        own = {e.hashCode() for e in face.Edges}
        click = view.getPointOnViewport(App.Vector(*pnt))
    except Exception:
        return None
    best, name = reach, None
    for i, e in enumerate(shape.Edges, 1):
        if e.hashCode() in own:
            continue
        try:
            pts = e.discretize(24)
        except Exception:
            continue
        for k in range(len(pts) - 1):
            a, b = view.getPointOnViewport(pts[k]), view.getPointOnViewport(pts[k + 1])
            d = _seg_dist(click, a, b)
            if d < best:
                best, name = d, "Edge%d" % i
    return name


def _seg_dist(p, a, b):
    ax, ay, bx, by, px, py = a[0], a[1], b[0], b[1], p[0], p[1]
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
    qx, qy = ax + t * dx, ay + t * dy
    return ((px - qx) ** 2 + (py - qy) ** 2) ** 0.5


class _SelObserver:
    def addSelection(self, doc, obj, sub, pnt):
        if _state["busy"]:
            return
        style = draw_style()
        try:
            dialog = bool(Gui.Control.activeDialog())
        except Exception:
            dialog = False
        if style == "wireframe" and not dialog and not _kept(WIREFRAME):
            QtCore.QTimer.singleShot(0, lambda: _drop(doc, obj, sub))
            return
        if style in ("hlr", "shaded") and _kept(HLR) and sub and sub.startswith("Face") and pnt:
            QtCore.QTimer.singleShot(0, lambda: _through(doc, obj, sub, pnt))
        QtCore.QTimer.singleShot(0, refresh_overlay)

    def removeSelection(self, doc, obj, sub):
        QtCore.QTimer.singleShot(0, refresh_overlay)

    def clearSelection(self, doc):
        QtCore.QTimer.singleShot(0, refresh_overlay)


def _drop(doc, obj, sub):
    _state["busy"] = True
    try:
        Gui.Selection.removeSelection(doc, obj, sub)
    except Exception as _fw_err:
        _fw_log("optionsextras5.py:252", _fw_err)
    finally:
        _state["busy"] = False


def _through(doc, obj, sub, pnt):
    try:
        o = App.getDocument(doc).getObject(obj)
        edge = _hidden_edge(o, sub, pnt) if o is not None and hasattr(o, "Shape") else None
    except Exception:
        edge = None
    if edge is None:
        return
    _state["busy"] = True
    try:
        Gui.Selection.removeSelection(doc, obj, sub)
        Gui.Selection.addSelection(doc, obj, edge)
    except Exception as _fw_err:
        _fw_log("optionsextras5.py:270", _fw_err)
    finally:
        _state["busy"] = False
    refresh_overlay()


# ---------------------------------------------------------------- equations in the tree
_CIRCULAR = {}      # document name -> (key, the circular set): kept while the document stays the same


def _gen(doc):
    try:
        from . import asmgen
        return asmgen.gen(doc)
    except Exception:
        return -1


def circular_objects(doc):
    try:
        from . import tickcache
        return tickcache.get(("fw_circular", doc.Name), lambda: _circular(doc))
    except Exception:
        return _circular(doc)


def _circular(doc):
    ""



    objs = doc.Objects
    with_expr = []
    for i, o in enumerate(objs):
        try:
            engine = o.ExpressionEngine
        except Exception:
            continue
        if engine:
            with_expr.append((i, o, engine))
    gen = _gen(doc)
    key = (gen, len(objs), tuple((o.Name, len(e)) for _i, o, e in with_expr))
    hit = _CIRCULAR.get(doc.Name)
    if hit is not None and gen != -1 and hit[0] == key:
        return hit[1]
    found = set()
    for i, o, engine in with_expr:
        exprs = [expr for _path, expr in engine]
        for other in objs[i + 1:]:
            if other.TypeId in ("Spreadsheet::Sheet", "App::VarSet"):
                continue        # a table of values (design table, variables) is not in the rebuild order
            name, label = other.Name + ".", "<<%s>>" % other.Label
            if any(name in e or label in e for e in exprs):
                found.add(o.Name)
                break
    _CIRCULAR[doc.Name] = (key, found)
    return found


def _tree_wanted():
    """Options asks for circular references in the tree (read once per pass of the event loop)."""
    def read():
        return TREE in (str(_kept(CIRCULAR)), str(_kept(POTENTIAL)))
    try:
        from . import tickcache
        return tickcache.get(("fw_circular_option",), read)
    except Exception:
        return read()


def _wrap_tree():
    try:
        from . import fmtree
        if getattr(fmtree._warned, "_fw_opt5", False):
            return
        old = fmtree._warned

        def warned(obj, _old=old):
            if _old(obj):
                return True
            try:
                from . import optionsextras3      # tree warnings Never: no marks at all
                if _tree_wanted() and str(_kept(optionsextras3.TREE_WARNINGS)) != "Never":
                    return obj.Name in circular_objects(obj.Document)
            except Exception as _fw_err:
                _fw_log("optionsextras5.py:352", _fw_err)
            return False
        warned._fw_opt5 = True
        fmtree._warned = warned
    except Exception as error:
        App.Console.PrintLog("FreeCAD: circular references option: %s\n" % error)


# ---------------------------------------------------------------- touch
class _Touch(QtCore.QObject if Gui is not None else object):
    """A touch held still for 0.6 s over the 3D view starts Magnified Selection."""

    def __init__(self):
        super().__init__()
        self.timer = QtCore.QTimer()
        self.timer.setSingleShot(True)
        self.timer.setInterval(600)
        self.timer.timeout.connect(self._pop)
        self.at = None

    def eventFilter(self, obj, event):
        try:
            t = event.type()
            if t == QtCore.QEvent.Show and isinstance(obj, QtWidgets.QDoubleSpinBox):
                if obj.suffix().strip() in ("s", "sec") and not obj.property("fw_time_step"):
                    obj.setProperty("fw_time_step", True)
                    obj.setSingleStep(time_step())      # Spin Box Increments > Time increments
                return False
            if t == QtCore.QEvent.TouchBegin and _kept(TOUCH):
                pts = event.points() if hasattr(event, "points") else event.touchPoints()
                self.at = pts[0].position() if pts and hasattr(pts[0], "position") else None
                self.timer.start()
            elif t == QtCore.QEvent.TouchUpdate and self.at is not None:
                pts = event.points() if hasattr(event, "points") else event.touchPoints()
                p = pts[0].position() if pts and hasattr(pts[0], "position") else None
                if p is not None and (p - self.at).manhattanLength() > 12:
                    self.timer.start()      # still hunting: wait until it holds still
                    self.at = p
            elif t in (QtCore.QEvent.TouchEnd, QtCore.QEvent.TouchCancel):
                self.timer.stop()
                self.at = None
        except Exception as _fw_err:
            _fw_log("optionsextras5.py:394", _fw_err)
        return False

    def _pop(self):
        try:
            if "SWStyle_MagnifiedSelection" in Gui.listCommands():
                Gui.runCommand("SWStyle_MagnifiedSelection", 0)
        except Exception as _fw_err:
            _fw_log("optionsextras5.py:402", _fw_err)


# ---------------------------------------------------------------- B-Rep mapping
def remap_import(old_obj, new_shape):
    """B-Rep mapping on: a re-imported shape replaces the imported body in place, so what was
    built on it (features, sketches, mates) stays on the same object."""
    if not _kept(BREP_MAP):
        return False
    try:
        old_obj.Shape = new_shape
        old_obj.touch()
        old_obj.Document.recompute()
        return True
    except Exception:
        return False


def _wrap_reimport():
    ""

    import importlib
    try:
        mod = importlib.import_module("ImportGui")
    except Exception:
        return
    old = getattr(mod, "insert", None)
    if old is None or getattr(old, "_fw_opt5", False):
        return

    def insert(path, doc_name=None, *args, _old=old, **kw):
        import os
        doc = App.getDocument(doc_name) if doc_name else App.ActiveDocument
        before = set(o.Name for o in doc.Objects) if doc is not None else set()
        result = _old(path, doc_name, *args, **kw) if doc_name else _old(path, *args, **kw)
        if doc is None or not _kept(BREP_MAP):
            return result
        stem = os.path.splitext(os.path.basename(path))[0]
        new = [o for o in doc.Objects if o.Name not in before and hasattr(o, "Shape")]
        olds = [o for o in doc.Objects if o.Name in before and getattr(o, "Label", "").startswith(stem)
                and o.TypeId == "Part::Feature"]
        for n, o in zip(new, olds):
            if remap_import(o, n.Shape):
                try:
                    doc.removeObject(n.Name)
                except Exception as _fw_err:
                    _fw_log("optionsextras5.py:448", _fw_err)
        return result
    insert._fw_opt5 = True
    try:
        mod.insert = insert
    except Exception as _fw_err:
        _fw_log("optionsextras5.py:454", _fw_err)


# ---------------------------------------------------------------- View > Transitions
TRANSITIONS = {"Off": 0, "Slow": 600, "Medium": 300, "Fast": 150}
HIDE_SHOW = ("View", "Hide/show component", "Fast")
ISOLATE = ("View", "Isolate", "Fast")
VIEW_SELECTOR = ("View", "View selector", "Fast")


def _ms(row):
    return TRANSITIONS.get(str(_kept(row)), 150)


_FADES = []         # the running fades' "end now" functions


def settle():
    """Ends every running fade at once on its end look. A fade still running when the next command
    changes the same components (Exit Isolate right after Isolate, Show right after Hide) would
    otherwise finish later and undo it: the component hidden again after Exit Isolate."""
    for end in list(_FADES):
        try:
            end()
        except Exception as _fw_err:
            _fw_log("optionsextras5.py:479", _fw_err)
    del _FADES[:]


def fading():
    return bool(_FADES)


def fade(objs, hide, ms, done=None):
    ""
    settle()
    objs = [o for o in objs if getattr(o, "ViewObject", None) is not None]
    if ms <= 0 or not objs:
        for o in objs:
            o.ViewObject.Visibility = not hide
        if done:
            done()
        return
    start = []          # kept by place, not by o.Name: a closed document leaves the objects deleted
    for o in objs:
        t = getattr(o.ViewObject, "Transparency", None)
        start.append(t if isinstance(t, int) else None)
        if not hide:
            if start[-1] is not None:
                o.ViewObject.Transparency = 90
            o.ViewObject.Visibility = True
    steps = max(2, ms // 30)
    state = {"i": 0}
    timer = QtCore.QTimer()

    def _alive(o):
        try:
            return o.Document is not None and o.Name is not None and o.ViewObject is not None
        except (ReferenceError, RuntimeError, AttributeError):
            return False

    def _finish():
        timer.stop()
        if _state.get("fade") is timer:
            _state.pop("fade", None)
        if end_now in _FADES:
            _FADES.remove(end_now)

    def tick():
        live = [(o, t0) for o, t0 in zip(objs, start) if _alive(o)]
        if not live:
            _finish()       # the document closed during the fade: nothing left to fade
            return
        state["i"] += 1
        k = state["i"] / float(steps)
        for o, t0 in live:
            if t0 is None:
                continue
            try:
                o.ViewObject.Transparency = int(t0 + (90 - t0) * k) if hide else int(90 + (t0 - 90) * k)
            except Exception as _fw_err:
                _fw_log("optionsextras5.py:535", _fw_err)
        if state["i"] >= steps:
            _finish()
            for o, t0 in live:
                try:
                    if hide:
                        o.ViewObject.Visibility = False
                    if t0 is not None:
                        o.ViewObject.Transparency = t0
                except Exception as _fw_err:
                    _fw_log("optionsextras5.py:545", _fw_err)
            if done:
                done()
    def end_now():
        if timer.isActive():
            state["i"] = steps - 1
            tick()

    timer.timeout.connect(tick)
    _FADES.append(end_now)
    timer.start(30)
    _state["fade"] = timer


def _wrap_transitions():
    try:
        from . import asmmenu
        if not getattr(asmmenu.hide_show, "_fw_opt5", False):
            old_hs = asmmenu.hide_show

            def hide_show(comp, _old=old_hs):
                ms = _ms(HIDE_SHOW)
                if ms <= 0:
                    return _old(comp)
                fade([comp], asmmenu.shown(comp), ms)
            hide_show._fw_opt5 = True
            asmmenu.hide_show = hide_show
    except Exception as error:
        App.Console.PrintLog("FreeCAD: hide/show transition: %s\n" % error)
    try:
        from . import asmisolate
        if not getattr(asmisolate.isolate, "_fw_opt5", False):
            old_iso = asmisolate.isolate

            def isolate(comps, *args, _old=old_iso, **kw):
                ms = _ms(ISOLATE)
                shown = {}
                if ms > 0:
                    try:
                        for d in App.listDocuments().values():
                            for o in d.Objects:
                                vo = getattr(o, "ViewObject", None)
                                if vo is not None and getattr(vo, "Visibility", False):
                                    shown[(d.Name, o.Name)] = o
                    except Exception:
                        shown = {}
                result = _old(comps, *args, **kw)
                if ms > 0 and shown:
                    gone = [o for o in shown.values() if not o.ViewObject.Visibility]
                    for o in gone:
                        o.ViewObject.Visibility = True
                    fade(gone, True, ms)
                return result
            isolate._fw_opt5 = True
            asmisolate.isolate = isolate
    except Exception as error:
        App.Console.PrintLog("FreeCAD: isolate transition: %s\n" % error)
    try:
        from . import viewselector
        cls = viewselector.ViewSelector
        if not getattr(cls.turn_to, "_fw_opt5", False):
            old_turn = cls.turn_to

            def turn_to(self, signs, _old=old_turn):
                p = App.ParamGet("User parameter:BaseApp/Preferences/View")
                keep = (p.GetBool("UseNavigationAnimations", True), p.GetInt("AnimationDuration", 250))
                ms = _ms(VIEW_SELECTOR)
                p.SetBool("UseNavigationAnimations", ms > 0)
                if ms > 0:
                    p.SetInt("AnimationDuration", ms)
                try:
                    return _old(self, signs)
                finally:
                    def back():
                        p.SetBool("UseNavigationAnimations", keep[0])
                        p.SetInt("AnimationDuration", keep[1])
                    QtCore.QTimer.singleShot(max(ms, 0) + 200, back)
            turn_to._fw_opt5 = True
            cls.turn_to = turn_to
    except Exception as error:
        App.Console.PrintLog("FreeCAD: view selector transition: %s\n" % error)


# ---------------------------------------------------------------- install
class _NewAnnotation:
    """Document Properties > Detailing > Display annotations off: an annotation made later is hidden too."""

    def slotCreatedObject(self, obj):
        try:
            doc = obj.Document
            if doc.Meta.get("FreeWorks_DisplayAnnotations", "1") != "0":
                return
        except Exception:
            return
        name, doc_name = obj.Name, doc.Name
        QtCore.QTimer.singleShot(300, lambda: _hide_if_annotation(doc_name, name))


def _hide_if_annotation(doc_name, name):
    try:
        from . import viewtypes
        o = App.getDocument(doc_name).getObject(name)
        if o is not None and o.ViewObject is not None and viewtypes.TYPES["AllAnnotations"][2](o):
            o.ViewObject.Visibility = False
    except Exception as _fw_err:
        _fw_log("optionsextras5.py:650", _fw_err)


def install():
    if Gui is None or _state["observer"] is not None:
        return
    try:
        _state["annotations"] = _NewAnnotation()
        App.addDocumentObserver(_state["annotations"])
    except Exception as error:
        App.Console.PrintLog("FreeCAD: display annotations: %s\n" % error)
    obs = _SelObserver()
    Gui.Selection.addObserver(obs)
    _state["observer"] = obs
    touch = _Touch()
    try:
        from . import events           # the add-on's one application filter: only Show and touch events reach it
        events.install()
        E = QtCore.QEvent
        events.register("optionsextras5-touch", (E.Show, E.TouchBegin, E.TouchUpdate, E.TouchEnd, E.TouchCancel),
                        touch.eventFilter)
    except Exception:
        QtWidgets.QApplication.instance().installEventFilter(touch)
    _state["touch"] = touch
    QtCore.QTimer.singleShot(4500, _wrap_tree)
    QtCore.QTimer.singleShot(1000, _wrap_reimport)
    QtCore.QTimer.singleShot(3000, _wrap_transitions)
