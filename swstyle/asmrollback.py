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

from . import asmcore as ac

TIP_PROP = "FwRollTip"
HIDDEN_PROP = "FwRollHidden"
BODY = "PartDesign::Body"


def _af():
    from . import asmfeature
    return asmfeature


_ROLLABLE = {}


def rollable(asm):
    """The items the bar passes, in tree order: the Mates folder, then the assembly's own features,
    sketches and planes (a sketch a feature uses is under that feature, not on its own row).
    Kept while the document is unchanged (the bar asks for it many times a second)."""
    from . import asmgen
    key = (asmgen.gen(asm.Document), asm.Document.Name, asm.Name)
    kept = _ROLLABLE.get(key[1:])
    if kept is not None and kept[0] == key[0] and key[0] >= 0:
        try:
            if all(o.isValid() for o in kept[1]):
                return list(kept[1])
        except Exception as _fw_err:
            _fw_log("asmrollback.py:55", _fw_err)
    out = _rollable(asm)
    _ROLLABLE[key[1:]] = (key[0], out)
    return list(out)


def _rollable(asm):
    af = _af()
    out = [ac.joint_group(asm)]
    for obj in asm.Group:
        if af.is_feature(obj):
            out.append(obj)
        elif obj.isDerivedFrom("Sketcher::SketchObject") or obj.isDerivedFrom("Part::Datum"):
            if not any(af.is_feature(p) for p in obj.InList):
                out.append(obj)
    return out


def tip(asm):
    """The last item above the bar (the last one when nothing is rolled back)."""
    items = rollable(asm)
    name = getattr(asm, TIP_PROP, "")
    for obj in items:
        if obj.Name == name:
            return obj
    return items[-1]


def rolled(asm):
    """The items under the bar."""
    items = rollable(asm)
    t = tip(asm)
    k = [o.Name for o in items].index(t.Name)
    return items[k + 1:]


def is_rolled(obj):
    asm = assembly_of(obj)
    return asm is not None and obj in rolled(asm)


def assembly_of(obj):
    try:
        for p in obj.InList:
            if p.TypeId == "Assembly::AssemblyObject":
                return p
    except Exception as _fw_err:
        _fw_log("asmrollback.py:102", _fw_err)
    return None


def _prop(asm):
    if not hasattr(asm, TIP_PROP):
        asm.addProperty("App::PropertyString", TIP_PROP, "FreeCAD", "Rollback bar: the last item above it")
        asm.setEditorMode(TIP_PROP, 2)
        asm.addProperty("App::PropertyStringList", HIDDEN_PROP, "FreeCAD", "Hidden by the rollback bar")
        asm.setEditorMode(HIDDEN_PROP, 2)


def roll(asm, new_tip, label="Rollback"):
    """Puts the bar under new_tip, in one Undo step."""
    items = rollable(asm)
    names = [o.Name for o in items]
    if new_tip is None or new_tip.Name not in names:
        return False
    if tip(asm).Name == new_tip.Name:
        return False
    doc = asm.Document
    before = tip(asm).Name
    doc.openTransaction(label)
    try:
        _prop(asm)
        k = names.index(new_tip.Name)
        under = items[k + 1:]
        hidden = set(getattr(asm, HIDDEN_PROP, []) or [])
        for o in items[1:]:             # sketches and planes under the bar hide; back above it, as they were
            vo = getattr(o, "ViewObject", None)
            if _af().is_feature(o) or vo is None:
                continue
            if o in under and vo.Visibility:
                vo.Visibility = False
                hidden.add(o.Name)
            elif o not in under and o.Name in hidden:
                vo.Visibility = True
                hidden.discard(o.Name)
        setattr(asm, HIDDEN_PROP, sorted(hidden))
        setattr(asm, TIP_PROP, "" if k == len(items) - 1 else new_tip.Name)
        feats = [o for o in items if _af().is_feature(o)]
        if feats:
            _af().update(feats[0], True)
        doc.recompute()
    except Exception as error:
        doc.abortTransaction()
        App.Console.PrintError("FreeCAD: assembly rollback: %s\n" % error)
        return False
    doc.commitTransaction()
    PREVIOUS[(doc.Name, asm.Name)] = before
    return True


PREVIOUS = {}       # (document, assembly) -> the item the bar was under before its last move


def roll_back_to(obj):
    """Rollback on an item: the bar just above it."""
    asm = assembly_of(obj)
    if asm is None:
        return False
    items = rollable(asm)
    names = [o.Name for o in items]
    if obj.Name not in names or names.index(obj.Name) == 0:
        return False
    return roll(asm, items[names.index(obj.Name) - 1])


def previous(asm):
    """Where the bar was before its last move (Roll to Previous), or None."""
    name = PREVIOUS.get((asm.Document.Name, asm.Name))
    obj = asm.Document.getObject(name) if name else None
    if obj is None or obj not in rollable(asm) or obj.Name == tip(asm).Name:
        return None
    return obj


def roll_to_previous(asm):
    p = previous(asm)
    return p is not None and roll(asm, p, "Roll to Previous")


def roll_to_end(asm):
    return roll(asm, rollable(asm)[-1], "Roll to End")


def put_at_bar(asm, obj):
    """A new item made while the bar is up goes in at the bar, and the bar goes under it."""
    if not getattr(asm, TIP_PROP, ""):
        return False
    t = tip(asm)
    group = [o for o in asm.Group if o is not obj]
    try:
        k = group.index(t) + 1 if t in group else len(group)
    except ValueError:
        k = len(group)
    group.insert(k, obj)
    try:
        asm.Group = group
    except Exception as error:
        App.Console.PrintLog("FreeCAD: rollback, new item at the bar: %s\n" % error)
        return False
    asm.FwRollTip = obj.Name
    return True


# ----------------------------------------------------------------------------- the bar
class AsmBody:
    """The assembly as rollbackbar.py's bar sees a body: rollable items and a Tip."""

    TypeId = BODY

    def __init__(self, asm):
        self.asm = asm
        self.Document = asm.Document
        self.Name = asm.Name
        self.Label = asm.Label
        self.Origin = None

    @property
    def Group(self):
        return rollable(self.asm)

    @property
    def Tip(self):
        return tip(self.asm)

    def hasObject(self, obj):
        return obj in rollable(self.asm)

    def isValid(self):
        return self.asm.isValid()

    def __eq__(self, other):
        return isinstance(other, AsmBody) and other.asm is self.asm

    def __hash__(self):
        return hash((self.Document.Name, self.Name))


def _wrap(obj):
    if obj is not None and getattr(obj, "TypeId", "") == "Assembly::AssemblyObject":
        return AsmBody(obj)
    return obj


def _asm_rows(tree, every):
    """(document, AsmBody, index) for each assembly row the tree shows."""
    from PySide import QtCore
    model = tree.model()
    out = []
    asms = {}
    for doc in App.listDocuments().values():
        a = ac.assembly_of(doc)
        if a is not None:
            asms.setdefault(a.Label, a)
    if not asms:
        return out

    def is_asm_row(index, a):
        """The assembly's own row, not its document's (both carry the same name): the one whose
        rows include the Mates folder."""
        mates = ac.joint_group(a).Label
        n = model.rowCount(index)
        # the Mates folder sits at the end of the assembly's rows: look from the end (a large
        # assembly has hundreds of component rows above it, and this runs on every rollback tick)
        return any(model.index(r, 0, index).data(QtCore.Qt.DisplayRole) == mates for r in range(n - 1, -1, -1))

    found = set()

    def walk(parent, depth):
        for row in range(model.rowCount(parent)):
            if len(found) == len(asms):
                return
            index = model.index(row, 0, parent)
            text = index.data(QtCore.Qt.DisplayRole)
            a = asms.get(text)
            if a is not None and id(a) not in found and model.rowCount(index) and is_asm_row(index, a):
                found.add(id(a))
                out.append((a.Document, AsmBody(a), index))
                continue
            if depth < 3 and (every or tree.isExpanded(index)):
                walk(index, depth + 1)
    walk(QtCore.QModelIndex(), 0)
    return out


def install():
    from . import rollbackbar as rb
    if getattr(rb, "_fw_asm", False):
        return
    body_rows0, solid0, body_of0, roll0 = rb.body_rows, rb.solid_features, rb.body_of, rb.ROLLS.roll
    body0 = rb.RollbackBar._body

    def body_rows(tree, every=False):
        out = body_rows0(tree, every)
        try:
            out = out + _asm_rows(tree, every)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: assembly rollback rows: %s\n" % error)
        return out

    def solid_features(body):
        if isinstance(body, AsmBody):
            return rollable(body.asm)
        return solid0(body)

    def body_of(obj):
        asm = assembly_of(obj)
        if asm is not None and obj in rollable(asm):
            return AsmBody(asm)
        return body_of0(obj)

    def roll_(body, new_tip, label="Rollback"):
        if isinstance(body, AsmBody):
            old = tip(body.asm).Name
            ok = roll(body.asm, new_tip, label)
            if ok:
                rb.ROLLS.previous[rb.Rolls.key(body)] = old
                rb.ROLLS.count += 1
                for call in list(rb.ROLLS.after):
                    try:
                        call(body)
                    except Exception as _fw_err:
                        _fw_log("asmrollback.py:326", _fw_err)
            return ok
        return roll0(body, new_tip, label)

    def _body(key):
        doc = App.getDocument(key[0]) if key[0] in App.listDocuments() else None
        obj = doc.getObject(key[1]) if doc is not None else None
        if obj is not None and obj.TypeId == "Assembly::AssemblyObject":
            return AsmBody(obj)
        return body0(key)

    rb.body_rows, rb.solid_features, rb.body_of = body_rows, solid_features, body_of
    rb.ROLLS.roll = roll_
    rb.RollbackBar._body = staticmethod(_body)
    object0 = rb._object

    def _object(key):
        obj = object0(key)
        return _wrap(obj) if obj is not None and obj.TypeId == "Assembly::AssemblyObject" else obj
    rb._object = _object
    marks0 = rb._marks

    def _marks(obj, body):
        if isinstance(body, AsmBody):
            return [m for m in marks0(obj, body) if m != "PartDesign_Overlay_Tip"]
        return marks0(obj, body)
    rb._marks = _marks

    # the cuts: features under the bar make none
    af = _af()
    features0 = af.features

    def features(asm):
        out = features0(asm)
        if not getattr(asm, TIP_PROP, ""):
            return out
        gone = {o.Name for o in rolled(asm)}
        return [f for f in out if f.Name not in gone]
    af.features = features

    # a new feature goes in at the bar
    for mod, name in ((af, "make"), (af, "make_feature")):
        _wrap_maker(mod, name)
    try:
        from . import asmfpattern
        _wrap_maker(asmfpattern, "make")
    except Exception as _fw_err:
        _fw_log("asmrollback.py:373", _fw_err)
    rb._fw_asm = True


def _wrap_maker(mod, name):
    make0 = getattr(mod, name)

    def make(asm, *args, **kwargs):
        if getattr(asm, TIP_PROP, ""):
            # made at the bar: it must count before update() runs inside make0
            feat = None
            try:
                feat = make0(asm, *args, **kwargs)
            finally:
                if feat is not None and put_at_bar(asm, feat):
                    _af().update(feat, True)
                    asm.Document.recompute()
            return feat
        return make0(asm, *args, **kwargs)
    setattr(mod, name, make)


def can_roll_back(obj):
    asm = assembly_of(obj)
    if asm is None:
        return False
    names = [o.Name for o in rollable(asm)]
    return obj.Name in names and names.index(obj.Name) > 0
