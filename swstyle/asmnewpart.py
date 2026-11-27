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

import os

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except Exception:   # pragma: no cover
    Gui = None

from . import asmcore as ac

V = App.Vector
KIND = "InPlace"
REL_PROP = "FwInPlace"          # the new part's placement in the picked component's frame
STATE = {"pick": None}


# ---------------------------------------------------------------- the part
def _next_part(doc):
    taken = {o.Label.split("^")[0] for o in doc.Objects}
    n = 1
    while "Part%d" % n in taken:
        n += 1
    return "Part%d" % n


def make_part(asm):
    """A new body kept in the assembly's document, and its virtual component."""
    from . import asminsert
    doc = asm.Document
    name = _next_part(doc)
    body = doc.addObject("PartDesign::Body", "Body")
    body.Label = "%s^%s" % (name, doc.Label)
    if body.ViewObject is not None:
        body.ViewObject.Visibility = False
    link = asm.newObject("App::Link", "Component")
    link.LinkedObject = body
    if not hasattr(link, asminsert.VIRTUAL_PROP):
        link.addProperty("App::PropertyBool", asminsert.VIRTUAL_PROP, "FreeCAD", "Virtual component (kept in the assembly)")
        link.setEditorMode(asminsert.VIRTUAL_PROP, 2)
    setattr(link, asminsert.VIRTUAL_PROP, True)
    link.Label = asminsert._instance(asm, "[%s^%s]" % (name, doc.Label), link)
    doc.recompute()
    return body, link


def _frame_of(root, sub, pnt=None):
    """(placement, component or None, element) for a picked plane or flat face: the frame's Z the
    plane's normal (a face's outward normal), its origin the picked point on it."""
    import Part
    asm = ac.assembly_of(root.Document)
    ref = ac.reference(asm, root, sub) if asm is not None else None
    if ref is not None:
        s = ac.element(*ref)
        if s is not None and s.ShapeType == "Face" and isinstance(s.Surface, Part.Plane):
            n = V(s.normalAt(*s.Surface.parameter(s.CenterOfMass)[:2]))
            if s.Orientation == "Reversed":
                pass        # normalAt already gives the outward normal of the face as it is
            c = V(pnt) if pnt is not None else V(s.CenterOfMass)
            c = c - n * (c - V(s.CenterOfMass)).dot(n)
            return App.Placement(c, App.Rotation(V(0, 0, 1), n)), ref[0], ref[1]
        return None
    try:
        obj = root.getSubObject(sub, 1)
    except Exception:
        obj = None
    if obj is not None and obj.TypeId == "App::Plane":
        pl = obj.getGlobalPlacement() if hasattr(obj, "getGlobalPlacement") else obj.Placement
        return App.Placement(pl.Base, pl.Rotation), None, ""
    return None


def place(asm, link, frame, comp=None, element=""):
    """The new part on the pick: its XY on the plane, an InPlace mate to the component picked
    (or fixed, on an assembly plane)."""
    link.Placement = frame
    doc = asm.Document
    if comp is not None and _refs_off():
        ac.fix(asm, link)       # No External References: no InPlace mate, the part fixed where it is made
        doc.recompute()
        return None
    joint = ac.joint_group(asm).newObject("App::FeaturePython", "InPlace")
    for prop, t, tip in ((ac.MATE_PROP, "App::PropertyString", "Mate type"),
                         (ac.ERROR_PROP, "App::PropertyBool", "The mate over defines the assembly"),
                         ("Suppressed", "App::PropertyBool", "Suppressed"),
                         ("Reference1", "App::PropertyXLinkSubHidden", "The new part"),
                         ("Reference2", "App::PropertyXLinkSubHidden", "The plane or face picked"),
                         (REL_PROP, "App::PropertyPlacement", "The new part in the picked component's frame")):
        joint.addProperty(t, prop, "FreeCAD", tip)
    setattr(joint, ac.MATE_PROP, KIND)
    joint.Label = ac._next_mate_name(asm, KIND)
    if App.GuiUp and joint.ViewObject is not None:
        joint.ViewObject.Proxy = 0
    joint.Reference1 = (link, [""])
    if comp is not None:
        joint.Reference2 = (comp, [element])
        setattr(joint, REL_PROP, comp.Placement.inverse().multiply(frame))
    else:
        setattr(joint, REL_PROP, frame)
        ac.fix(asm, link)
    doc.recompute()
    return joint


def _refs_off():
    try:
        from . import asmtools
        return asmtools.external_refs_off()
    except Exception as _fw_err:
        _fw_log("asmnewpart.py:refs", _fw_err)
        return False


def inplace_mates(asm):
    return [j for j in ac.mates(asm) if ac.mate_type(j) == KIND]


def _target(joint):
    rel = getattr(joint, REL_PROP)
    ref = joint.Reference2
    comp = ref[0] if ref else None
    return comp.Placement.multiply(rel) if comp is not None else App.Placement(rel)


def follow(asm):
    _follow(asm)
    try:
        from . import asmextref
        asmextref.follow_binders(asm)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: in-context references: %s\n" % error)


def _follow(asm):
    """After a solve: each new part back where its InPlace mate keeps it."""
    for j in inplace_mates(asm):
        if getattr(j, "Suppressed", False):
            continue
        try:
            part = j.Reference1[0]
            want = _target(j)
            if not part.Placement.isSame(want, 1e-9):
                part.Placement = want
        except Exception as error:
            App.Console.PrintLog("FreeCAD: InPlace: %s\n" % error)


def holds(joint, tol=1e-3):
    try:
        want = _target(joint)
        have = joint.Reference1[0].Placement
        return (want.Base - have.Base).Length < tol * 10 and want.Rotation.isSame(have.Rotation, tol)
    except Exception:
        return True


def sketch_on(body):
    """A sketch on the part's Front Plane (its XY), the first feature of the new part."""
    xy = None
    for f in body.Origin.OriginFeatures:
        if getattr(f, "Role", "") == "XY_Plane":
            xy = f
    sk = body.newObject("Sketcher::SketchObject", "Sketch")
    if xy is not None:
        sk.AttachmentSupport = [(xy, "")]
        sk.MapMode = "FlatFace"
    body.Document.recompute()
    return sk


def finish(asm, body, link, frame, comp=None, element=""):
    """Place it, open it for editing with its sketch."""
    doc = asm.Document
    doc.openTransaction("New Part")
    try:
        joint = place(asm, link, frame, comp, element)
        sk = sketch_on(body)
    finally:
        doc.commitTransaction()
    if Gui is not None:
        from . import asmtools
        try:
            asmtools.edit_component(asm, link)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: New Part edit: %s\n" % error)
        try:
            # In context, through the component: the other parts stay drawn and pickable, and the

            try:
                Gui.getDocument(asm.Document.Name).setEdit(asm, 0, "%s.%s." % (link.Name, sk.Name))
            except Exception:
                Gui.ActiveDocument.setEdit(sk)
        except Exception as _fw_err:
            _fw_log("asmnewpart.py:199", _fw_err)
    return joint, sk


def _app_filter(name, types, flt, on=True):
    ""
    try:
        from . import events
        if on:
            events.register(name, types, flt.eventFilter)
        else:
            events.unregister(name)
        return True
    except ImportError:
        app = QtWidgets.QApplication.instance()
        (app.installEventFilter if on else app.removeEventFilter)(flt)
        return False


# ---------------------------------------------------------------- the pick
if Gui is not None:
    class _Pick(QtCore.QObject):
        ""


        def __init__(self, asm, body, link):
            super().__init__()
            self.asm, self.body, self.link = asm, body, link
            self.done = False
            Gui.Selection.clearSelection()
            Gui.Selection.addObserver(self, 0)
            self.press = None
            _app_filter("asm.newpart", (QtCore.QEvent.KeyPress, QtCore.QEvent.MouseButtonPress,
                                        QtCore.QEvent.MouseButtonRelease), self)
            self.prompt = "Select a plane or face for the new part, or click in empty space to place it at the assembly origin."
            self._say(self.prompt)
            self.timer = QtCore.QTimer(self)
            self.timer.timeout.connect(self._keep_prompt)
            self.timer.start(250)

        def _keep_prompt(self):
            try:
                if Gui.getMainWindow().statusBar().currentMessage() != self.prompt:
                    self._say(self.prompt)
            except Exception as _fw_err:
                _fw_log("asmnewpart.py:242", _fw_err)

        def _say(self, text):
            try:
                Gui.getMainWindow().statusBar().showMessage(text, 0)
            except Exception as _fw_err:
                _fw_log("asmnewpart.py:248", _fw_err)

        def addSelection(self, doc, obj, sub, pnt):
            if self.done:
                return
            root = App.getDocument(doc).getObject(obj)
            if root is None or not sub:
                return
            got = _frame_of(root, sub, V(*pnt) if pnt else None)
            if got is None:
                self.prompt = "Select a plane or a flat face for the new part, or click in empty space to place it at the assembly origin."
                self._say(self.prompt)
                return
            QtCore.QTimer.singleShot(0, lambda: self._end(*got))

        def removeSelection(self, *a):
            pass

        def clearSelection(self, *a):
            pass

        def eventFilter(self, obj, ev):
            if not isinstance(ev, QtCore.QEvent):
                return False
            if ev.type() == QtCore.QEvent.KeyPress and ev.key() == QtCore.Qt.Key_Escape and not self.done:
                QtCore.QTimer.singleShot(0, lambda: self._end(App.Placement(), None, ""))
                return True
            if ev.type() in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease) and not self.done \
                    and ev.button() == QtCore.Qt.LeftButton and self._in_view(obj):
                at = ev.globalPosition().toPoint() if hasattr(ev, "globalPosition") else ev.globalPos()
                if ev.type() == QtCore.QEvent.MouseButtonPress:
                    self.press = at
                elif self.press is not None and (at - self.press).manhattanLength() <= 4 and not self._over_something():

                    QtCore.QTimer.singleShot(150, lambda: self.done or self._end(App.Placement(), None, ""))
                if ev.type() == QtCore.QEvent.MouseButtonRelease:
                    self.press = None
            return False

        def _in_view(self, obj):
            try:
                return obj is Gui.ActiveDocument.ActiveView.graphicsView().viewport()
            except Exception:
                return False

        def _over_something(self):
            try:
                pre = Gui.Selection.getPreselection()
                return bool(getattr(pre, "ObjectName", "") or getattr(pre, "Object", None) is not None)
            except Exception:
                return False

        def _end(self, frame, comp, element):
            if self.done:
                return
            self.done = True
            self.stop()
            Gui.Selection.clearSelection()
            finish(self.asm, self.body, self.link, frame, comp, element)
            self._say("Editing %s" % self.link.Label)

        def stop(self):
            try:
                self.timer.stop()
            except Exception as _fw_err:
                _fw_log("asmnewpart.py:290", _fw_err)
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("asmnewpart.py:294", _fw_err)
            try:
                _app_filter("asm.newpart", (), self, False)
            except Exception as _fw_err:
                _fw_log("asmnewpart.py:298", _fw_err)
            if STATE["pick"] is self:
                STATE["pick"] = None


def external(asm, body, link):
    """Options > Assemblies, Save new components to external files: the new part gets its own
    file beside the saved assembly (Part1.FCStd, Part2.FCStd ...) at once; the body returned is
    the one in that file. Off, or the assembly not saved yet: the virtual part stays."""
    from . import asmoptions
    folder = os.path.dirname(asm.Document.FileName or "")
    if not asmoptions.save_external() or not folder:
        return body
    name = link.Label.split("<")[0].strip("[]").split("^")[0] or "Part1"
    n = 1
    base = name.rstrip("0123456789") or "Part"
    while os.path.exists(os.path.join(folder, name + ".FCStd")) or App.listDocuments().get(name):
        n += 1
        name = "%s%d" % (base, n)
    from . import asmsavepart
    try:
        link.Label = "[%s^%s]<1>" % (name, asm.Document.Label)
        asmsavepart.save_external(asm, link, os.path.join(folder, name + ".FCStd"))
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: New Part not saved to its own file: %s\n" % error)
        return body
    asm.Document.recompute()
    return link.LinkedObject


def new_part(asm):
    """The command: the part and its component now, the plane or face next."""
    if STATE["pick"] is not None:
        STATE["pick"].stop()
    doc = asm.Document
    doc.openTransaction("New Part")
    try:
        body, link = make_part(asm)
        body = external(asm, body, link)
    finally:
        doc.commitTransaction()
    if Gui is not None:
        STATE["pick"] = _Pick(asm, body, link)
    return body, link


class NewPartCommand:
    def GetResources(self):
        return {"MenuText": "New Part", "Pixmap": "PartDesign_Body",
                "ToolTip": "Creates a new part in the assembly: select a plane or face for it."}

    def Activated(self, *a):
        from . import asmtools
        asm = asmtools._assembly()
        if asm is not None:
            new_part(asm)

    def IsActive(self):
        from . import asmtools
        return asmtools._assembly() is not None


COMMANDS = (("SWStyle_NewPartInAssembly", NewPartCommand),)


def register():
    for name, cls in COMMANDS:
        try:
            Gui.addCommand(name, cls())
        except Exception as _fw_err:
            _fw_log("asmnewpart.py:363", _fw_err)
