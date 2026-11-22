# SPDX-License-Identifier: LGPL-2.1-or-later
"""Which event types an eventFilter can do anything for, read from its own source.

Every pointer move runs about twenty of the add-on's event filters (twelve application-wide handlers and
eight on the 3D view), and most of them only look at the event type and return False: a filter for
right-clicks is still called, guarded and run for every MouseMove. interest(fn, cls) reads the filter's
source and returns the set of QEvent types for which it can do more than "look and return False"; the
guard in safeguards.py then answers False for every other type without calling it.

The analysis is deliberately narrow. It follows the statements from the top with the set of event types
that can still be "live" (reached without anything having happened):
  - `if not isinstance(event, QEvent): return False`, `t = event.type()`, `QE = QtCore.QEvent`, and other
    assignments of side-effect-free expressions to local names change nothing;
  - `if TEST: ... elif ...: ... else: ...` splits the live set by what TEST says about the type
    (`t == QE.X`, `t != QE.X`, `t in (QE.X, QE.Y)`, `t not in NAMES`, and/or/not of those with attribute reads);
  - `return False` / `return None` ends a path; `try:` is followed into its body (its except blocks are taken
    as unreachable for a type whose path through the body only reads: a read does not raise);
  - `return self.other(obj, event)` as the whole filter is followed into that method (two levels);
  - ANYTHING else (a call, an attribute assignment, a loop, ...) makes every type still live there
    "of interest".
A part of a test that calls something (`event.button() == Qt.LeftButton`) is fine when it is only reached
for types already singled out by an earlier part (`t == QE.MouseButtonPress and event.button() ...`);
otherwise the types live at that point are of interest. Whatever is not understood means "all types",
which is the behaviour without this module: nothing is skipped.

Attribute reads (`self.state`, `self.shell.enabled`) are taken as side-effect free: skipping a filter
skips those reads too. A property that does work when read from a filter's first lines would be skipped
with it; the add-on has none (tests/evhub_check.py runs every analysed filter with recording stand-ins
for every type it is said not to handle and requires: falsy result, no call, no attribute set).
"""
import ast
import inspect
import textwrap

try:
    from PySide import QtCore
except ImportError:                                     # pragma: no cover
    QtCore = None

ALL = None                  # "every type": nothing can be skipped

# Qt getters taken as reads (name -> most constant arguments): they only return a pointer or a flag. A Python class of the
# add-on that defines one of these names to do work would break that; tests/evhub_check.py fails when one does.
GETTERS = {"viewport": 0, "parentWidget": 0, "parent": 0, "window": 0, "widget": 0, "isVisible": 0, "isHidden": 0,
           "isEnabled": 0, "isWidgetType": 0, "isWindow": 0, "objectName": 0, "inherits": 1, "metaObject": 0}


class TS:
    """A set of event types, finite or co-finite (everything but a finite set)."""
    __slots__ = ("neg", "items")

    def __init__(self, items=(), neg=False):
        self.neg, self.items = neg, frozenset(items)

    def __or__(self, o):
        if self.neg and o.neg:
            return TS(self.items & o.items, True)
        if self.neg:
            return TS(self.items - o.items, True)
        if o.neg:
            return TS(o.items - self.items, True)
        return TS(self.items | o.items)

    def __and__(self, o):
        if self.neg and o.neg:
            return TS(self.items | o.items, True)
        if self.neg:
            return TS(o.items - self.items)
        if o.neg:
            return TS(self.items - o.items)
        return TS(self.items & o.items)

    def __invert__(self):
        return TS(self.items, not self.neg)

    def empty(self):
        return not self.neg and not self.items

    def __repr__(self):
        return "%s%s" % ("~" if self.neg else "", sorted(str(i) for i in self.items))


EVERY = TS((), True)
NONE = TS(())


class _Unknown(Exception):
    pass


_REBOUND = {}


def _rebound(module_globals):
    """The names of a module that one of its functions rebinds (`global NAME`): not constants."""
    name = module_globals.get("__name__")
    if name not in _REBOUND:
        names = set()
        try:
            import re
            import sys
            # a text scan, not a parse: this runs on the first event a filter sees, and the big modules take 20 ms to parse
            for m in re.finditer(r"^[ \t]*global[ \t]+([\w \t,]+)", inspect.getsource(sys.modules[name]), re.M):
                names.update(x.strip() for x in m.group(1).split(",") if x.strip())
            _REBOUND[name] = frozenset(names)
        except Exception:
            _REBOUND[name] = _EVERYNAME
    return _REBOUND[name]


class _EveryName:
    def __contains__(self, name):
        return True


_EVERYNAME = _EveryName()


class _Analysis:
    def __init__(self, fn, cls, depth=0):
        self.fn, self.cls, self.depth = fn, cls, depth
        if getattr(fn, "__wrapped__", None) is not None:
            raise _Unknown("a decorated function: its source is not all it does")
        self.free = frozenset(fn.__code__.co_freevars)
        src = textwrap.dedent(inspect.getsource(fn))
        tree = ast.parse(src)
        self.node = tree.body[0]
        if not isinstance(self.node, ast.FunctionDef):
            raise _Unknown("not a plain function")
        args = self.node.args
        if args.vararg or args.kwarg or args.kwonlyargs or len(args.args) < 3 - (0 if cls is not None else 1):
            raise _Unknown("signature")
        names = [a.arg for a in args.args]
        if cls is not None:
            self.self_name, self.obj_name, self.event_name = names[0], names[1], names[2]
        else:
            self.self_name, self.obj_name, self.event_name = None, names[0], names[1]
        self.globals = fn.__globals__
        self.typevars = set()
        self.aliases = {}           # local name -> resolved object (QEvent class, tuple of types, ...)
        self.assigned = {}          # local name -> number of assignments anywhere in the function
        self.why = []               # (line, statement kind, live types) where types became 'of interest' (for the tests)
        for n in ast.walk(self.node):
            targets = []
            if isinstance(n, ast.Assign):
                targets = n.targets
            elif isinstance(n, (ast.AugAssign, ast.AnnAssign)):
                targets = [n.target]
            elif isinstance(n, (ast.For, ast.AsyncFor)):
                targets = [n.target]
            elif isinstance(n, ast.NamedExpr):
                targets = [n.target]
            elif isinstance(n, (ast.With, ast.AsyncWith)):
                targets = [i.optional_vars for i in n.items if i.optional_vars is not None]
            elif isinstance(n, ast.ExceptHandler) and n.name:
                self.assigned[n.name] = self.assigned.get(n.name, 0) + 1
            elif isinstance(n, (ast.Global, ast.Nonlocal)):
                raise _Unknown("global statement")
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                for a in n.names:
                    nm = (a.asname or a.name).split(".")[0]
                    self.assigned[nm] = self.assigned.get(nm, 0) + 1
            for t in targets:
                for m in ast.walk(t):
                    if isinstance(m, ast.Name) and isinstance(m.ctx, ast.Store):
                        self.assigned[m.id] = self.assigned.get(m.id, 0) + 1
        for nm in (self.self_name, self.obj_name, self.event_name):
            if nm and self.assigned.get(nm):
                raise _Unknown("a parameter is reassigned")

    # ------------------------------------------------------------ expressions
    def _is_event_type_call(self, e):
        return (isinstance(e, ast.Call) and not e.args and not e.keywords and isinstance(e.func, ast.Attribute)
                and e.func.attr == "type" and isinstance(e.func.value, ast.Name) and e.func.value.id == self.event_name)

    def _is_typevar(self, e):
        return (isinstance(e, ast.Name) and e.id in self.typevars) or self._is_event_type_call(e)

    def resolve(self, e):
        """The run-time value of a name/attribute chain that cannot change (module globals, local aliases)."""
        if isinstance(e, ast.Name):
            if e.id in self.aliases:
                return self.aliases[e.id]
            if e.id in self.assigned or e.id in (self.self_name, self.obj_name, self.event_name):
                raise _Unknown("local name")
            if e.id in self.free:
                raise _Unknown("a closure variable")
            if e.id in self.globals:
                value = self.globals[e.id]
                if not (inspect.ismodule(value) or inspect.isclass(value)) and e.id in _rebound(self.globals):
                    raise _Unknown("a global some function rebinds")
                return value
            raise _Unknown("unknown name")
        if isinstance(e, ast.Attribute):
            base = self.resolve(e.value)
            # only through modules and the QEvent classes: nothing else is constant enough
            if inspect.ismodule(base) or base is QtCore.QEvent or base is QtCore.QEvent.Type:
                try:
                    value = getattr(base, e.attr)
                except AttributeError:
                    raise _Unknown("no such attribute")
                if inspect.ismodule(base) and not (inspect.ismodule(value) or inspect.isclass(value)) \
                        and (getattr(base, "__name__", "") or "").split(".")[0] not in ("PySide", "PySide2", "PySide6") \
                        and e.attr in _rebound(vars(base)):
                    raise _Unknown("a global some function rebinds")
                return value
            raise _Unknown("attribute of a non-module")
        if isinstance(e, (ast.Tuple, ast.List, ast.Set)):
            return tuple(self.resolve(x) for x in e.elts)
        raise _Unknown("not a constant")

    def types_of(self, e):
        """frozenset of QEvent.Type for the right side of a comparison with the event type."""
        v = self.resolve(e)
        T = QtCore.QEvent.Type
        if isinstance(v, T):
            return frozenset((v,))
        if isinstance(v, (tuple, frozenset)) and v and all(isinstance(x, T) for x in v):
            return frozenset(v)
        raise _Unknown("not event types")

    def pure(self, e):
        """True when evaluating e cannot do anything (reads only)."""
        if isinstance(e, (ast.Constant, ast.Name)):
            return True
        if isinstance(e, ast.Attribute):
            return self.pure(e.value)
        if isinstance(e, ast.UnaryOp) and isinstance(e.op, ast.Not):
            return self.pure(e.operand)
        if isinstance(e, ast.Subscript):
            return self.pure(e.value) and isinstance(e.slice, ast.Constant)
        if isinstance(e, ast.BoolOp):
            return all(self.pure(v) for v in e.values)
        if isinstance(e, ast.Compare):
            return self.pure(e.left) and all(self.pure(c) for c in e.comparators)
        if isinstance(e, (ast.Tuple, ast.List, ast.Set)):
            return all(self.pure(x) for x in e.elts)
        if isinstance(e, ast.Call) and not e.keywords:
            if self._is_event_type_call(e):
                return True
            f = e.func
            if isinstance(f, ast.Name) and f.id in ("isinstance", "getattr", "hasattr") and f.id not in self.assigned \
                    and f.id not in self.globals:
                if f.id == "getattr" and len(e.args) >= 2 and not isinstance(e.args[1], ast.Constant):
                    return False
                return all(self.pure(a) for a in e.args)
            if isinstance(f, ast.Attribute) and f.attr in GETTERS and self.pure(f.value) \
                    and all(isinstance(a, ast.Constant) for a in e.args) and len(e.args) <= GETTERS[f.attr]:
                return True                                 # obj is self.view.viewport(), obj.inherits("QOpenGLWidget")
            if isinstance(f, ast.Attribute) and f.attr == "get" and isinstance(f.value, ast.Name) and 1 <= len(e.args) <= 2:
                try:
                    if isinstance(self.resolve(f.value), dict):       # a module-level dict: STATE.get("doc")
                        return all(self.pure(a) for a in e.args)
                except _Unknown:
                    return False
        return False

    def test(self, e, live):
        """(may_true, may_false, interest): the live types for which e can be true / false, and the live types
        for which evaluating e may do something."""
        if isinstance(e, ast.Compare) and len(e.ops) == 1 and self._is_typevar(e.left):
            op = e.ops[0]
            try:
                s = TS(self.types_of(e.comparators[0]))
            except _Unknown:
                s = None
            if s is not None:
                if isinstance(op, (ast.Eq, ast.In, ast.Is)):
                    return live & s, live & ~s, NONE
                if isinstance(op, (ast.NotEq, ast.NotIn, ast.IsNot)):
                    return live & ~s, live & s, NONE
        if isinstance(e, ast.UnaryOp) and isinstance(e.op, ast.Not):
            t, f, i = self.test(e.operand, live)
            return f, t, i
        if isinstance(e, ast.BoolOp):
            interest = NONE
            if isinstance(e.op, ast.And):
                cur, may_false = live, NONE
                for v in e.values:
                    t, f, i = self.test(v, cur)
                    interest, may_false, cur = interest | i, may_false | f, t
                return cur, may_false, interest
            cur, may_true = live, NONE
            for v in e.values:
                t, f, i = self.test(v, cur)
                interest, may_true, cur = interest | i, may_true | t, f
            return may_true, cur, interest
        if self.pure(e):
            return live, live, NONE
        self.why.append((e.lineno, "test", live))
        return live, live, live                 # it calls something: whatever is live here is of interest

    # ------------------------------------------------------------ statements
    def _falsy_return(self, s):
        return isinstance(s, ast.Return) and (s.value is None or (isinstance(s.value, ast.Constant) and not s.value.value))

    def block(self, stmts, live, handler=False):
        """(interest, live after the block). handler: an except body (a line written to the Report view there is nothing)."""
        interest = NONE
        for index, s in enumerate(stmts):
            if live.empty():
                break
            if handler and self._says_only(s):
                continue
            if isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant):
                continue                                    # docstring
            if isinstance(s, ast.Pass):
                continue
            if isinstance(s, (ast.Import, ast.ImportFrom)) and self._loaded(s):
                continue                                    # `from . import overridedrag`: a module already loaded is a lookup
            if self._falsy_return(s):
                return interest, NONE
            if isinstance(s, ast.Assign) and len(s.targets) == 1 and isinstance(s.targets[0], ast.Name):
                name = s.targets[0].id
                if self._is_event_type_call(s.value) and self.assigned.get(name) == 1:
                    self.typevars.add(name)
                    continue
                if self.assigned.get(name) == 1:
                    try:
                        v = self.resolve(s.value)
                        self.aliases[name] = v              # QE = QtCore.QEvent, MOUSE = (QE.A, QE.B)
                        continue
                    except _Unknown:
                        pass
                if self.pure(s.value):
                    continue                                # a local set from reads only
                self.why.append((s.lineno, "assign", live))
                return interest | live, NONE
            if isinstance(s, ast.Assign) and len(s.targets) == 1 and isinstance(s.targets[0], ast.Tuple) \
                    and all(isinstance(m, (ast.Name, ast.Tuple)) for m in ast.walk(s.targets[0]) if not isinstance(m, ast.expr_context)) \
                    and self.pure(s.value):
                continue                                    # a, b = self.held: locals from a read
            if isinstance(s, ast.If):
                t, f, i = self.test(s.test, live)
                ib, lb = self.block(s.body, t, handler)
                io, lo = self.block(s.orelse, f, handler)
                interest = interest | i | ib | io
                live = lb | lo
                continue
            if isinstance(s, ast.Try) and not s.finalbody:
                ib, lb = self.block(s.body, live, handler)
                interest = interest | ib
                io, lo = self.block(s.orelse, lb, handler) if s.orelse else (NONE, lb)
                interest = interest | io
                # A read can fail too (an attribute that is not there yet), so every type that enters the try can
                # reach its except blocks: they are followed like any other code, with log lines counted as nothing.
                after = lo
                for h in s.handlers:
                    ih, lh = self.block(h.body, live, True)
                    interest = interest | ih
                    after = after | lh
                live = after
                continue
            if isinstance(s, ast.Return) and self._base_filter(s.value):
                return interest, NONE                       # return super().eventFilter(obj, event): QObject's, which is False
            if isinstance(s, ast.Return):
                sub = self._delegate(s.value)
                if sub is not None:
                    return interest | (live & sub), NONE
            self.why.append((s.lineno, type(s).__name__, live))
            return interest | live, NONE
        return interest, live

    def _loaded(self, s):
        """Every module the import statement names is already in sys.modules (so running it only looks it up)."""
        import sys
        if isinstance(s, ast.Import):
            return all(a.name in sys.modules for a in s.names)
        base = s.module or ""
        if s.level:
            pkg = (self.globals.get("__package__") or "").split(".")
            if s.level > len(pkg) or not pkg[0]:
                return False
            pkg = pkg[:len(pkg) - s.level + 1]
            base = ".".join(pkg + ([s.module] if s.module else []))
        if base not in sys.modules:
            return False
        mod = sys.modules[base]
        for a in s.names:
            if a.name == "*":
                return False
            if not hasattr(mod, a.name) and (base + "." + a.name) not in sys.modules:
                return False
        return True

    def _says_only(self, s):
        """In an except body: a statement that only writes a line to the Report view / remembers that it did."""
        if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)):
            return False
        f = s.value.func
        if isinstance(f, ast.Attribute) and f.attr in ("PrintLog", "PrintWarning", "PrintError", "PrintMessage"):
            return True
        if isinstance(f, ast.Name) and f.id == "_fw_log":
            return True
        if isinstance(f, ast.Attribute) and f.attr == "add" and len(s.value.args) == 1 and isinstance(f.value, ast.Name) \
                and f.value.id.lstrip("_").lower() in ("failed", "said", "seen", "fw_seen", "warned"):
            return True                                     # _failed.add(key): the "said once" set
        return False

    def _base_filter(self, value):
        """`super().eventFilter(obj, event)` / `QtCore.QObject.eventFilter(self, obj, event)` where that is QObject's own
        (which does nothing and answers False). A Qt class further down (QCompleter, an item view) has a filter that works."""
        if self.cls is None or not isinstance(value, ast.Call) or value.keywords:
            return False
        f = value.func
        if not (isinstance(f, ast.Attribute) and f.attr == "eventFilter"):
            return False
        names = [a.id if isinstance(a, ast.Name) else None for a in value.args]
        base = f.value
        if isinstance(base, ast.Call) and isinstance(base.func, ast.Name) and base.func.id == "super" and not base.keywords \
                and "super" not in self.globals and "super" not in self.assigned:
            if names != [self.obj_name, self.event_name]:
                return False
            if base.args and not (len(base.args) == 2 and isinstance(base.args[1], ast.Name) and base.args[1].id == self.self_name):
                return False
            # the class this function is defined in, then the next eventFilter after it in the instance's order
            mro = list(self.cls.__mro__)
            for k, c in enumerate(mro):
                own = c.__dict__.get("eventFilter")
                if own is self.fn or getattr(own, "__wrapped__", None) is self.fn:
                    for nxt in mro[k + 1:]:
                        if "eventFilter" in nxt.__dict__:
                            return nxt is QtCore.QObject
                    return False
            return False
        if names != [self.self_name, self.obj_name, self.event_name]:
            return False
        try:
            return self.resolve(base) is QtCore.QObject
        except _Unknown:
            return False

    def _delegate(self, value):
        """`return self.NAME(obj, event)`: the interest of that method (a TS), else None."""
        if self.depth >= 2 or self.cls is None or not isinstance(value, ast.Call) or value.keywords:
            return None
        f = value.func
        if not (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == self.self_name):
            return None
        a = value.args
        if not (len(a) == 2 and isinstance(a[0], ast.Name) and a[0].id == self.obj_name
                and isinstance(a[1], ast.Name) and a[1].id == self.event_name):
            return None
        target = inspect.getattr_static(self.cls, f.attr, None)
        if not inspect.isfunction(target):
            return None
        try:
            sub = _Analysis(target, self.cls, self.depth + 1)
            interest, _live = sub.block(sub.node.body, EVERY)
            self.why.extend(("%s:%s" % (f.attr, l), k, t) for l, k, t in sub.why)
            return interest
        except Exception as error:
            self.why.append((0, "delegate %s: %s" % (f.attr, error), EVERY))
            return None

    def run(self):
        interest, _live = self.block(self.node.body, EVERY)
        return interest


def explain(fn, cls=None):
    """For the tests: (interest or ALL, [(line in the function, what, live types)])."""
    try:
        a = _Analysis(fn, cls)
        ts = a.run()
        return (ALL if ts.neg else ts.items), a.why
    except Exception as error:
        return ALL, [(0, "error: %s" % error, EVERY)]


def interest(fn, cls=None):
    """frozenset of the QEvent types fn can act on, or ALL (None) when it may act on any / is not understood."""
    if QtCore is None:
        return ALL
    try:
        ts = _Analysis(fn, cls).run()
    except Exception:
        return ALL
    if ts.neg:
        return ALL
    return ts.items

