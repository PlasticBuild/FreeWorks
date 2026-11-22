# SPDX-License-Identifier: LGPL-2.1-or-later
""











import ast
import inspect
import textwrap
import traceback

import FreeCAD as App

PARAM = "User parameter:BaseApp/Preferences/Mod/FreeWorks"
PACKAGES = ("swstyle", "smcore")
_PURE_CALLS = ("getattr", "isinstance", "len", "bool", "hasattr")
# observers whose slotChangedObject does nothing that matters while a file loads: called through the hub, which skips
# them while the object's document is restoring (extapps/61; README says why for each)
RESTORE_QUIET = frozenset(["persistrefs._Watch", "stoprepair._Observer", "saveas._SmartSave", "featuredates._Watch",
                           "sketchpicture._FollowSketch", "originaxes._DocObserver", "configmanager._Observer"])
_s = {"orig_add": None, "orig_remove": None, "hub": None, "subs": (), "proxies": {}, "gen": 0}


def _pure(node):
    """A test with no side effect: names, constants, attribute reads, comparisons, and/or/not, a few builtin calls."""
    if isinstance(node, (ast.Name, ast.Constant)):
        return True
    if isinstance(node, ast.Attribute):
        return _pure(node.value)
    if isinstance(node, ast.Compare):
        return _pure(node.left) and all(_pure(c) for c in node.comparators)
    if isinstance(node, ast.BoolOp):
        return all(_pure(v) for v in node.values)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return _pure(node.operand)
    if isinstance(node, ast.Subscript):
        return _pure(node.value) and _pure(node.slice)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_pure(e) for e in node.elts)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _PURE_CALLS:
        return all(_pure(a) for a in node.args) and not node.keywords
    return False


def _values(node, glob, watched):
    """The strings an `in` / `not in` / `==` test names, or None. Module-level names are read now and watched (the hub falls back
    to calling the handler always if one is rebound later)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.Name):
        if node.id not in glob:
            return None
        value = glob[node.id]
        if isinstance(value, str):
            watched.append((glob, node.id, value))
            return {value}
        if isinstance(value, (tuple, frozenset)) and all(isinstance(v, str) for v in value):
            watched.append((glob, node.id, value))
            return set(value)
        return None
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        out = set()
        for e in node.elts:
            got = _values(e, glob, watched)
            if got is None:
                return None
            out |= got
        return out
    return None


def _prop_term(term, prop, glob, watched, exclusion):
    """(set) when term is `prop not in S` / `prop != c` (exclusion) or `prop in S` / `prop == c` (inclusion)."""
    if not (isinstance(term, ast.Compare) and len(term.ops) == 1 and isinstance(term.left, ast.Name) and term.left.id == prop):
        return None
    op, right = term.ops[0], term.comparators[0]
    wanted = (ast.NotIn, ast.NotEq) if exclusion else (ast.In, ast.Eq)
    if not isinstance(op, wanted):
        return None
    return _values(right, glob, watched)


def _prefix_prop_term(terms, prop, glob, watched, exclusion):
    """The names of the first term that tests the property when every term before it is side-effect free (and so is all there is to
    evaluate for a property outside them: the test is False, or True, there without running anything else), else None."""
    for term in terms:
        got = _prop_term(term, prop, glob, watched, exclusion)
        if got is not None:
            return got
        if not _pure(term):
            return None
    return None


def _branch_interest(node, prop, glob, watched):
    """The properties an `if` branch (and its elif branches) acts on, or None. A branch whose test names the property in an
    `and` chain (all terms before that one pure) acts only on those; there is no else."""
    names = set()
    while True:
        test = node.test
        if isinstance(test, ast.BoolOp):
            if not isinstance(test.op, ast.And):
                return None
            terms = test.values
        else:
            terms = [test]
        got = _prefix_prop_term(terms, prop, glob, watched, False)
        if got is None:
            return None
        names |= got
        if not node.orelse:
            return names
        if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
            node = node.orelse[0]
            continue
        return None


def analyse(fn):
    """(frozenset of property names the handler acts on, watched globals) or None when it must always be called.
    fn is a plain function or bound method slotChangedObject(self, obj, prop). What is recognised (anything else: None):
      if prop != "A" [or ...]: return                  (the property test first among side-effect free terms, then anything)
      if prop in S [and ...]: ...  [elif prop == B [and ...]: ...]  as the whole handler
    after any docstring and plain assignments of side-effect free values (`page = self.page`)."""
    try:
        func = fn.__func__ if hasattr(fn, "__func__") else fn
        tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
        node = tree.body[0]
        if not isinstance(node, ast.FunctionDef) or len(node.args.args) != 3 or node.args.vararg or node.args.kwonlyargs:
            return None
        prop = node.args.args[2].arg
        body = list(node.body)
        while body and (isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant)
                        or isinstance(body[0], ast.Assign) and all(isinstance(t, ast.Name) for t in body[0].targets) and _pure(body[0].value)):
            body.pop(0)
        if not body or not isinstance(body[0], ast.If):
            return None
        first, glob, watched = body[0], func.__globals__, []
        test = first.test
        returns = not first.orelse and len(first.body) == 1 and isinstance(first.body[0], ast.Return) and \
            (first.body[0].value is None or (isinstance(first.body[0].value, ast.Constant) and first.body[0].value.value is None))
        if returns and not (isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And)):
            # `if <t1> or <t2> or ...: return`: any true term returns, so a property outside the named set returns too
            terms = test.values if isinstance(test, ast.BoolOp) else [test]
            got = _prefix_prop_term(terms, prop, glob, watched, True)
            return (frozenset(got), watched) if got is not None else None
        if len(body) == 1:
            # the whole handler is the if / elif chain
            got = _branch_interest(first, prop, glob, watched)
            return (frozenset(got), watched) if got is not None else None
        return None
    except Exception:
        return None


class _Sub:
    __slots__ = ("fn", "interest", "watched", "name", "quiet")

    def __init__(self, fn, interest, watched, name):
        self.fn, self.interest, self.watched, self.name = fn, interest, watched, name
        self.quiet = name in RESTORE_QUIET

    def sound(self):
        """False when a module constant its guard was read from has been rebound since: the handler is then called always, as before."""
        if self.interest is None:
            return False            # no guard found: called for every property (a RESTORE_QUIET observer)
        for glob, key, value in self.watched:
            if glob.get(key) is not value:
                return False
        return True


class _Hub:
    """slotChangedObject: property -> the handlers that act on it (built when observers come and go), in registration order.
    Names a guard read from module constants are re-checked every 256 changes; a rebound one makes that handler called always."""

    def __init__(self):
        self.n = 0
        self.generation = -1
        self.index, self.default = {}, ()

    def build(self):
        subs = _s["subs"]
        always = [s for s in subs if not s.sound()]
        index = {}
        for s in subs:
            if s in always:
                continue
            for prop in s.interest:
                index.setdefault(prop, []).append(s)
        s_all = tuple(always)
        self.always = s_all
        self.index = {prop: tuple(sorted(lst + list(s_all), key=subs.index)) for prop, lst in index.items()}
        self.default = tuple(always)
        self.generation = _s["gen"]

    def slotChangedObject(self, obj, prop):
        self.n += 1
        if self.generation != _s["gen"] or not self.n & 255:
            self.build()
        restoring = None
        for sub in self.index.get(prop, self.default):
            if sub.quiet:
                if restoring is None:
                    try:
                        restoring = bool(obj.Document.Restoring)
                    except Exception:
                        restoring = False
                if restoring:
                    continue
            try:
                sub.fn(obj, prop)
            except Exception:
                App.Console.PrintError("FreeCAD observer %s: %s\n" % (sub.name, traceback.format_exc()))


class _Proxy:
    """The observer without slotChangedObject; every other slot is the observer's own bound method."""

    def __init__(self, obs):
        object.__setattr__(self, "_obs", obs)

    def __getattr__(self, name):
        if name == "slotChangedObject":
            raise AttributeError(name)
        return getattr(object.__getattribute__(self, "_obs"), name)


def _ours(obs):
    mod = getattr(type(obs), "__module__", "") or ""
    return mod.split(".")[0] in PACKAGES


def _add(obs):
    fn = getattr(obs, "slotChangedObject", None)
    if fn is not None and _ours(obs) and id(obs) not in _s["proxies"]:
        found = analyse(fn)
        if found is None and "%s.%s" % (type(obs).__module__.split(".")[-1], type(obs).__name__) in RESTORE_QUIET:
            found = (None, [])
        if found is not None:
            interest, watched = found
            proxy = _Proxy(obs)
            _s["proxies"][id(obs)] = (obs, proxy)
            _s["gen"] += 1
            _s["subs"] = _s["subs"] + (_Sub(fn, interest, watched, "%s.%s" % (type(obs).__module__.split(".")[-1], type(obs).__name__)),)
            if _s["hub"] is None:
                _s["hub"] = _Hub()
                _s["orig_add"](_s["hub"])
            return _s["orig_add"](proxy)
    return _s["orig_add"](obs)


def _remove(obs):
    entry = _s["proxies"].pop(id(obs), None)
    if entry is not None:
        _s["gen"] += 1
        _s["subs"] = tuple(s for s in _s["subs"] if s.fn != getattr(obs, "slotChangedObject", None))
        return _s["orig_remove"](entry[1])
    return _s["orig_remove"](obs)


def install():
    """Wraps App.addDocumentObserver / removeDocumentObserver. Call it first thing at start-up, before the modules register."""
    if _s["orig_add"] is not None:
        return False
    try:
        if not App.ParamGet(PARAM).GetBool("ObserverHub", True):
            App.Console.PrintLog("FreeCAD: observer hub off (ObserverHub)\n")
            return False
    except Exception:
        pass
    _s["orig_add"], _s["orig_remove"] = App.addDocumentObserver, App.removeDocumentObserver
    App.addDocumentObserver, App.removeDocumentObserver = _add, _remove
    return True


def counts():
    return len(_s["subs"])
