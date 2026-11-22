# SPDX-License-Identifier: LGPL-2.1-or-later
""






import FreeCAD as App

from . import asmcore as ac

V = App.Vector
KIND = "Linear/Linear Coupler"
DATA_PROP = "FwCoupler"         # ratio 1, ratio 2, reverse, then the zero positions and the last travels
REF_PROP = "FwCouplerRefs"      # the two reference components ("" for the assembly)


def _direction(comp, elem):
    g = ac.geometry(ac.element(comp, elem))
    if g is None or g[0] not in ("line", "axis", "plane"):
        return None
    return V(g[2]).normalize()


def pickable(ref):
    return _direction(*ref) is not None


def values(joint):
    d = list(getattr(joint, DATA_PROP, []) or [])
    num = lambda i, dflt: float(d[i]) if len(d) > i and d[i] not in ("", None) else dflt
    return {"r1": num(0, 1.0), "r2": num(1, 1.0), "reverse": len(d) > 2 and d[2] == "1"}


def _frame(asm, name):
    comp = asm.Document.getObject(name) if name else None
    return comp.Placement if comp is not None else App.Placement()


def refs_of(joint):
    return (joint.Reference1[0], joint.Reference1[1][0]), (joint.Reference2[0], joint.Reference2[1][0])


def reference_names(joint):
    r = list(getattr(joint, REF_PROP, []) or [])
    r += [""] * (2 - len(r))
    return r[0], r[1]


def _local(asm, joint, which, comp):
    """The component's position in its reference component's frame."""
    return _frame(asm, reference_names(joint)[which]).inverse().multVec(comp.Placement.Base)


def _dir_local(asm, joint, which, d):
    return _frame(asm, reference_names(joint)[which]).Rotation.inverted().multVec(d)


def _zeros(joint):
    d = list(getattr(joint, DATA_PROP, []) or [])
    try:
        z = [float(x) for x in d[3:11]]
        return V(*z[0:3]), V(*z[3:6]), z[6], z[7]
    except (ValueError, TypeError, IndexError):
        return None


def _store(joint, v, zero1, zero2, last1=0.0, last2=0.0):
    b = "1" if v["reverse"] else "0"
    setattr(joint, DATA_PROP, [repr(float(v["r1"])), repr(float(v["r2"])), b]
            + [repr(float(x)) for x in (zero1.x, zero1.y, zero1.z, zero2.x, zero2.y, zero2.z, last1, last2)])


def rezero(asm, joint):
    """Travel counted from where the two are now."""
    (c1, _e1), (c2, _e2) = refs_of(joint)
    _store(joint, values(joint), _local(asm, joint, 0, c1), _local(asm, joint, 1, c2))


def make(asm, ref1, ref2, r1=1.0, r2=1.0, reverse=False, references=("", ""), joint=None):
    """Returns (mate, message)."""
    if not pickable(ref1) or not pickable(ref2):
        return None, "Pick a straight edge, an axis or a flat face on each component."
    if ref1[0] is ref2[0]:
        return None, "Pick the directions on two different components."
    if joint is None:
        joint = ac.joint_group(asm).newObject("App::FeaturePython", "LinearCoupler")
        for prop, t, doc in ((ac.MATE_PROP, "App::PropertyString", "Mate type"),
                             (ac.ERROR_PROP, "App::PropertyBool", "The mate over defines the assembly"),
                             (DATA_PROP, "App::PropertyStringList", "Linear/Linear Coupler: ratio, reverse, zeros"),
                             (REF_PROP, "App::PropertyStringList", "Reference components"),
                             ("Suppressed", "App::PropertyBool", "Suppressed"),
                             ("Reference1", "App::PropertyXLinkSubHidden", "First mate entity"),
                             ("Reference2", "App::PropertyXLinkSubHidden", "Second mate entity")):
            joint.addProperty(t, prop, "FreeCAD", doc)
        setattr(joint, ac.MATE_PROP, KIND)
        joint.Label = ac._next_mate_name(asm, KIND)
        if App.GuiUp and joint.ViewObject is not None:
            joint.ViewObject.Proxy = 0
        joint.Reference1 = (ref1[0], [ref1[1]])
        joint.Reference2 = (ref2[0], [ref2[1]])
        setattr(joint, REF_PROP, [references[0] or "", references[1] or ""])
        _store(joint, {"r1": r1, "r2": r2, "reverse": reverse},
               _local(asm, joint, 0, ref1[0]), _local(asm, joint, 1, ref2[0]))
    else:
        setattr(joint, REF_PROP, [references[0] or "", references[1] or ""])
        z = _zeros(joint)
        if z is None:
            rezero(asm, joint)
            z = _zeros(joint)
        _store(joint, {"r1": r1, "r2": r2, "reverse": reverse}, *z)
    ok = ac.solve(asm)
    return joint, (None if ac._mark(joint, ok) else ac.OVER_MESSAGE)


def couplers(asm):
    return [j for j in ac.mates(asm) if ac.mate_type(j) == KIND and not getattr(j, "Suppressed", False)]


def travels(asm, joint):
    """(first's travel, second's travel) from their zeros, along their directions."""
    (c1, e1), (c2, e2) = refs_of(joint)
    z = _zeros(joint)
    if z is None:
        return 0.0, 0.0
    d1 = _dir_local(asm, joint, 0, _direction(c1, e1))
    d2 = _dir_local(asm, joint, 1, _direction(c2, e2))
    return (_local(asm, joint, 0, c1) - z[0]).dot(d1), (_local(asm, joint, 1, c2) - z[1]).dot(d2)


def _ratio(v):
    r = v["r2"] / v["r1"] if abs(v["r1"]) > 1e-12 else 0.0
    return -r if v["reverse"] else r


def couple(asm, driver=None):
    """The component that moved (driver, else the one whose travel changed most since the last
    time) drives the other. True when something moved."""
    fixed = set(ac.grounded(asm))
    moved = False
    for joint in couplers(asm):
        try:
            moved |= _couple(asm, joint, fixed, driver)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: linear coupler: %s\n" % error)
    return moved


def _couple(asm, joint, fixed, driver):
    v = values(joint)
    (c1, e1), (c2, e2) = refs_of(joint)
    z = _zeros(joint)
    if z is None:
        rezero(asm, joint)
        return False
    t1, t2 = travels(asm, joint)
    r = _ratio(v)
    if driver is c1 or (driver is None and abs(t1 - z[2]) >= abs(t2 - z[3])):
        lead, follow, which, want = c1, c2, 1, t1 * r
    else:
        lead, follow, which, want = c2, c1, 0, (t2 / r if abs(r) > 1e-12 else 0.0)
    have = t2 if which == 1 else t1
    if follow in fixed or abs(want - have) < 1e-9:
        _store(joint, v, z[0], z[1], t1, t2)
        return False
    d = _direction(*((c2, e2) if which == 1 else (c1, e1)))
    frame = _frame(asm, reference_names(joint)[which])
    dl = frame.Rotation.inverted().multVec(d)
    shift = frame.Rotation.multVec(dl * (want - have))
    follow.Placement = App.Placement(follow.Placement.Base + shift, follow.Placement.Rotation)
    t1, t2 = travels(asm, joint)
    _store(joint, v, z[0], z[1], t1, t2)
    return True


def holds(joint, tol=1e-3):
    try:
        asm = joint.InList[0].InList[0] if joint.InList and joint.InList[0].InList else None
        if asm is None:
            return True
        t1, t2 = travels(asm, joint)
        return abs(t2 - t1 * _ratio(values(joint))) < tol * 10
    except Exception:
        return True
