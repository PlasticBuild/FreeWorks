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
import Part

NAME = "FlatPatternView"
LABEL = "Flat-Pattern-View"


def sheet_body(doc):
    from . import smflatten
    for o in doc.Objects:
        if o.TypeId == "PartDesign::Body":
            try:
                if smflatten.root(o) is not None:
                    return o
            except Exception as _fw_err:
                _fw_log("smflatview.py:35", _fw_err)
    return None


class FlatView:
    def __init__(self, obj, body):
        obj.addProperty("App::PropertyLink", "Body", "Flat-Pattern", "The sheet metal part")
        obj.addProperty("App::PropertyVector", "Normal", "Flat-Pattern", "Normal of the fixed face", 8)
        obj.addProperty("App::PropertyVector", "XAxis", "Flat-Pattern", "View X on the flat", 8)
        obj.Body = body
        obj.Proxy = self

    def execute(self, obj):
        from . import smdxf
        shape, folds, face = smdxf.flat(obj.Body)
        n = face.normalAt(0, 0)
        edges = [e for e in face.OuterWire.Edges if hasattr(e.Curve, "Direction")]
        longest = max(edges, key=lambda e: e.Length) if edges else None
        x = longest.Curve.Direction if longest is not None else App.Vector(1, 0, 0)
        x = x - n * x.dot(n)
        obj.Normal = n
        obj.XAxis = x.normalize() if x.Length > 1e-9 else App.Vector(1, 0, 0)
        parts = [shape] + ([folds] if folds is not None and not folds.isNull() else [])
        obj.Shape = Part.makeCompound(parts)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def flat_view(doc, create=True):
    """The part's Flat-Pattern-View feature (made on first use), or None if the part is not sheet metal."""
    obj = doc.getObject(NAME)
    if obj is not None:
        return obj
    body = sheet_body(doc)
    if body is None or not create:
        return None
    obj = doc.addObject("Part::FeaturePython", NAME)
    FlatView(obj, body)
    obj.Label = LABEL
    if App.GuiUp and obj.ViewObject is not None:
        obj.ViewObject.Proxy = 0
        obj.ViewObject.Visibility = False
        try:
            obj.ViewObject.ShowInTree = False
        except Exception as _fw_err:
            _fw_log("smflatview.py:84", _fw_err)
    doc.recompute()
    return obj


def available(doc):
    return doc is not None and sheet_body(doc) is not None
