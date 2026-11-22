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

TYPE = "PartDesign::FeaturePython"
NAME = "HoleWizard"


class HoleGroup:
    def __init__(self, obj):
        self.setup(obj)
        obj.Proxy = self

    def setup(self, obj):
        if "Holes" not in obj.PropertiesList:
            obj.addProperty("App::PropertyLinkList", "Holes", "Hole Wizard", "The holes of this Hole Wizard feature")
        if "Members" not in obj.PropertiesList:
            obj.addProperty("App::PropertyLinkList", "Members", "Hole Wizard",
                            "Everything the holes brought (planes, sketches, options, cosmetic threads)")
            obj.setEditorMode("Members", 2)

    def execute(self, obj):
        base = obj.BaseFeature
        if base is not None and not base.Shape.isNull():
            obj.Shape = base.Shape.copy()

    def onChanged(self, obj, prop):
        if prop == "Suppressed" and not getattr(obj.Document, "Restoring", False):
            for hole in getattr(obj, "Holes", []) or []:
                try:
                    if hole.Suppressed != obj.Suppressed:
                        hole.Suppressed = obj.Suppressed
                except Exception as _fw_err:
                    _fw_log("holegroup.py:54", _fw_err)

            for m in getattr(obj, "Members", []) or []:
                try:
                    if m.isDerivedFrom("PartDesign::Feature") and "Suppressed" in m.PropertiesList \
                            and m.Suppressed != obj.Suppressed:
                        m.Suppressed = obj.Suppressed
                except Exception as _fw_err:
                    _fw_log("holegroup.py:62", _fw_err)

    def onDocumentRestored(self, obj):
        self.setup(obj)
        obj.Proxy = self

    def dumps(self):
        return None

    def loads(self, state):
        return None


class HoleGroupView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.ViewObject = vobj
        self.Object = vobj.Object

    def _object(self):
        obj = getattr(self, "Object", None)
        if obj is None:
            # a restored view provider: FreeCAD may not call attach again
            vobj = getattr(self, "ViewObject", None)
            obj = getattr(vobj, "Object", None)
        if obj is None:
            for doc in App.listDocuments().values():
                for o in doc.Objects:
                    try:
                        if o.ViewObject is not None and o.ViewObject.Proxy is self:
                            obj = o
                            break
                    except Exception as _fw_err:
                        _fw_log("holegroup.py:97", _fw_err)
                if obj is not None:
                    break
            if obj is not None:
                self.Object = obj
        return obj

    def getIcon(self):
        return ":/icons/PartDesign_Hole.svg"

    def claimChildren(self):
        obj = self._object()
        return list(getattr(obj, "Members", []) or []) if obj is not None else []

    def doubleClicked(self, vobj):
        return edit(vobj.Object) is not None

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return False
        edit(vobj.Object)
        return False

    def unsetEdit(self, vobj, mode=0):
        return False

    def onDelete(self, vobj, subelements):
        ""
        try:
            remove(vobj.Object)
        except Exception as error:
            App.Console.PrintError("Hole Wizard: %s\n" % error)
        return False

    def dumps(self):
        return None

    def loads(self, state):
        return None


def group_of(hole):
    for obj in getattr(hole, "InList", []) or []:
        if isinstance(getattr(obj, "Proxy", None), HoleGroup) and hole in (obj.Holes or []):
            return obj
    return None


def holes_with(hole):
    """The holes edited together with this one (its Hole Wizard feature's), itself first."""
    group = group_of(hole)
    if group is None:
        return [hole]
    return [hole] + [h for h in group.Holes if h is not hole]


def make(body, holes, members):
    """The Hole Wizard feature over holes (in body order); members: everything they brought."""
    doc = body.Document
    if len(holes) < 2:
        return None
    last = body.Tip
    obj = body.newObject(TYPE, NAME)
    HoleGroup(obj)
    if App.GuiUp:
        HoleGroupView(obj.ViewObject)
    obj.Holes = list(holes)
    obj.Members = [m for m in members if m is not None and m is not obj]
    obj.BaseFeature = last
    label = holes[0].Label
    for i, hole in enumerate(holes, 1):
        hole.Label = "%s (Position %d)" % (label, i)
    obj.Label = label
    try:
        from . import holespec
        spec = holespec.stored(holes[0])
        if spec is not None:
            obj.addProperty("App::PropertyString", holespec.SPEC_PROPERTY, "Hole Wizard", "The Type tab's choices")
            obj.setEditorMode(holespec.SPEC_PROPERTY, 2)
            setattr(obj, holespec.SPEC_PROPERTY, getattr(holes[0], holespec.SPEC_PROPERTY))
    except Exception as _fw_err:
        _fw_log("holegroup.py:178", _fw_err)
    doc.recompute()
    if App.GuiUp:
        for m in obj.Members:
            try:
                m.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("holegroup.py:185", _fw_err)
        try:
            src = last.ViewObject
            for prop in ("ShapeAppearance", "LineColor", "PointColor", "Transparency", "DisplayMode"):
                try:
                    setattr(obj.ViewObject, prop, getattr(src, prop))
                except Exception as _fw_err:
                    _fw_log("holegroup.py:192", _fw_err)
            obj.ViewObject.Visibility = True
        except Exception as _fw_err:
            _fw_log("holegroup.py:195", _fw_err)
    return obj


def edit(group):
    """Edit Feature: the Hole Wizard's Type tab on the first hole; OK changes them all."""
    holes = list(group.Holes or [])
    if not holes:
        return None
    from . import holespec
    return holespec.edit(holes[0])


def remove(group):
    doc = group.Document
    from . import holespec
    body = holespec._body_of(group)
    keep = group.BaseFeature
    first = group.Holes[0] if group.Holes else None
    before = None
    if first is not None:
        # what the first hole's position plane / hole was built on
        chain = [first] + list(group.Members or [])
        bases = [getattr(m, "BaseFeature", None) for m in chain]
        before = next((b for b in bases if b is not None and b not in chain), None)
    doc.openTransaction("Delete " + group.Label)
    try:
        for after in group.InList:
            if getattr(after, "BaseFeature", None) is group:
                after.BaseFeature = before
        members = list(group.Members or [])
        names = [group.Name] + [m.Name for m in reversed(members)]
        if body is not None:
            was_tip = body.Tip is group
            for name in names:
                o = doc.getObject(name)
                if o is not None and o in body.Group:
                    body.removeObject(o)
            if was_tip:
                body.Tip = before
        for name in names:
            if doc.getObject(name) is not None:
                doc.removeObject(name)
        if before is not None and App.GuiUp:
            try:
                before.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("holegroup.py:242", _fw_err)
        doc.recompute()
    finally:
        doc.commitTransaction()


class _SuppressWatch:
    ""



    def slotChangedObject(self, obj, prop):
        if prop != "Suppressed":
            return
        try:
            if obj.TypeId != "PartDesign::Hole" or getattr(obj.Document, "Restoring", False):
                return
            from . import holespec, holeoptions
            if holespec.SPEC_PROPERTY not in obj.PropertiesList:
                return
            kids = list(holespec.threads_of(obj))
            try:
                kids.append(holeoptions.existing(obj))
            except Exception as _fw_err:
                _fw_log("holegroup.py:266", _fw_err)
            for kid in kids:
                if kid is not None and "Suppressed" in kid.PropertiesList and kid.Suppressed != obj.Suppressed:
                    kid.Suppressed = obj.Suppressed
        except Exception as _fw_err:
            _fw_log("holegroup.py:271", _fw_err)


_watch = []


def watch():
    if not _watch:
        _watch.append(_SuppressWatch())
        App.addDocumentObserver(_watch[0])
