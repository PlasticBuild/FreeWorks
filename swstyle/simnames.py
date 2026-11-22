# SPDX-License-Identifier: LGPL-2.1-or-later
""









import re

import FreeCAD as App


NAMES = {
    "Fem::ConstraintFixed": "Fixed",
    "Fem::ConstraintDisplacement": "Roller/Slider",
    "Fem::ConstraintPlaneRotation": "Fixed Hinge",
    "Fem::ConstraintSpring": "Elastic Support",
    "Fem::ConstraintRigidBody": "Rigid Connection",
    "Fem::ConstraintTransform": "Reference Geometry",
    "Fem::ConstraintForce": "Force",
    "Fem::ConstraintPressure": "Pressure",
    "Fem::ConstraintSelfWeight": "Gravity",
    "Fem::ConstraintCentrif": "Centrifugal",
    "Fem::ConstraintBearing": "Bearing Load",
    "Fem::ConstraintTemperature": "Temperature",
    "Fem::ConstraintHeatflux": "Heat Flux",
    "Fem::ConstraintBodyHeatSource": "Heat Power",
    "Fem::ConstraintInitialTemperature": "Initial Temperature",
    "Fem::ConstraintContact": "Contact Set",
    "Fem::ConstraintTie": "Contact Set",
    "Fem::MeshRegion": "Control",
    "Fem::MeshBoundaryLayer": "Control",
}

# FreeCAD's own default labels: its type's short name, maybe with 001, 002 ...
_DEFAULT = re.compile(r"^(?:Constraint\w+|ConstraintBodyHeatSource|MeshRegion|MeshBoundaryLayer|FEMConstraint\w*)\d*$")

_SEEN = set()


def _log(site, err):
    if site not in _SEEN:
        _SEEN.add(site)
        try:
            App.Console.PrintLog("FreeCAD simnames %s: %s\n" % (site, err))
        except Exception:
            return


def ftype(o):
    t = getattr(getattr(o, "Proxy", None), "Type", None)
    return t if isinstance(t, str) and t else o.TypeId


def kind_name(o):
    ""
    try:
        return NAMES.get(ftype(o))
    except Exception:
        return None


def is_default(o):
    """True while o still has FreeCAD's own label."""
    label = getattr(o, "Label", "") or ""
    return label == o.Name or bool(_DEFAULT.match(label))


def _members(a):
    out = []
    for o in getattr(a, "Group", []) or []:
        out.append(o)
        if o.isDerivedFrom("Fem::FemMeshObject"):      # mesh controls live in the mesh's own group
            out += [c for c in (getattr(o, "MeshRegionList", []) or []) + (getattr(o, "MeshBoundaryLayerList", []) or [])
                    if c is not None]
    return out


def next_name(a, base):
    used = {o.Label for o in _members(a)}
    n = 1
    while "%s-%d" % (base, n) in used:
        n += 1
    return "%s-%d" % (base, n)


def rename(a):
    ""
    done = []
    for o in _members(a):
        base = kind_name(o)
        if base and is_default(o):
            o.Label = next_name(a, base)
            done.append(o)
    return done


def _study_of(o):
    try:
        for p in o.InList:
            if p.isDerivedFrom("Fem::FemAnalysis"):
                return p
            if p.isDerivedFrom("Fem::FemMeshObject"):
                for q in p.InList:
                    if q.isDerivedFrom("Fem::FemAnalysis"):
                        return q
    except Exception as _fw_err:
        _log("study_of", _fw_err)
    return None


class _Observer:
    """A study's Group (or a mesh's control list) grew: name its new members."""

    def slotChangedObject(self, obj, prop):
        if prop not in ("Group", "MeshRegionList", "MeshBoundaryLayerList"):
            return
        try:
            a = obj if obj.isDerivedFrom("Fem::FemAnalysis") else _study_of(obj) if obj.isDerivedFrom("Fem::FemMeshObject") else None
            if a is not None:
                _later(a)
        except Exception as _fw_err:
            _log("changed", _fw_err)

    def slotCreatedObject(self, obj):
        # a mesh control is made already linked to its mesh, and the mesh's list may not change after the label
        try:
            if ftype(obj) in ("Fem::MeshRegion", "Fem::MeshBoundaryLayer"):
                from PySide import QtCore
                QtCore.QTimer.singleShot(0, lambda o=obj: _late(o))
        except Exception as _fw_err:
            _log("created", _fw_err)


def _later(a):
    """After the code that added the member has given it its own name (simpms adds, then names)."""
    try:
        from PySide import QtCore
        QtCore.QTimer.singleShot(0, lambda: _rename_alive(a))
    except Exception:
        _rename_alive(a)


def _rename_alive(a):
    try:
        a.Name          # deleted since: RuntimeError / ReferenceError
    except Exception:
        return
    try:
        rename(a)
    except Exception as _fw_err:
        _log("rename", _fw_err)


def _late(o):
    try:
        a = _study_of(o)
        if a is not None and is_default(o):
            rename(a)
    except Exception as _fw_err:
        _log("late", _fw_err)


_OBS = {}


def install():
    if "obs" not in _OBS:
        _OBS["obs"] = _Observer()
        App.addDocumentObserver(_OBS["obs"])
    return _OBS["obs"]
