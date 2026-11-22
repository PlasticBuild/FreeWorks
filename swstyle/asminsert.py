# SPDX-License-Identifier: LGPL-2.1-or-later
""









import os
import zipfile

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import asmcore as ac

VIRTUAL_PROP = "FwVirtual"
ENVELOPE_PROP = "FwEnvelope"
ENVELOPE_BLUE = (0.45, 0.65, 1.0)


# ----------------------------------------------------------------------------- Make virtual
def make_virtual(asm, link):
    """The component's part copied into the assembly document and linked there instead."""
    target = link.LinkedObject
    doc = asm.Document
    if target is None or target.Document is doc:
        return link
    copies = doc.copyObject(target, True)
    copy = copies[0] if isinstance(copies, (list, tuple)) else copies
    if copy.ViewObject is not None:
        copy.ViewObject.Visibility = False
    from . import asmoptions
    prefix = asmoptions.virtual_prefix().strip()    # Options > Assemblies, Prefix for virtual components
    part = ("%s %s" % (prefix, ac.part_name(link))) if prefix else ac.part_name(link)
    copy.Label = "%s^%s" % (part, asm.Document.Label)
    link.LinkedObject = copy
    if not hasattr(link, VIRTUAL_PROP):
        link.addProperty("App::PropertyBool", VIRTUAL_PROP, "FreeCAD", "Virtual component (kept in the assembly)")
        link.setEditorMode(VIRTUAL_PROP, 2)
    setattr(link, VIRTUAL_PROP, True)
    link.Label = _instance(asm, "[%s^%s]" % (part, asm.Document.Label), link)
    doc.recompute()
    return link


def _instance(asm, name, link):
    taken = {c.Label for c in ac.components(asm) if c is not link}
    n = 1
    while "%s<%d>" % (name, n) in taken:
        n += 1
    return "%s<%d>" % (name, n)


def is_virtual(comp):
    return bool(getattr(comp, VIRTUAL_PROP, False))


# ----------------------------------------------------------------------------- Envelope
def make_envelope(link, on=True):
    if not hasattr(link, ENVELOPE_PROP):
        link.addProperty("App::PropertyBool", ENVELOPE_PROP, "FreeCAD", "Envelope (reference only)")
        link.setEditorMode(ENVELOPE_PROP, 2)
    setattr(link, ENVELOPE_PROP, bool(on))
    vo = getattr(link, "ViewObject", None)
    if vo is not None and hasattr(vo, "OverrideMaterial"):
        try:
            if on:
                m = App.Material()
                m.DiffuseColor = ENVELOPE_BLUE
                m.Transparency = 0.7
                vo.ShapeMaterial = m
                vo.OverrideMaterial = True
            else:
                vo.OverrideMaterial = False
        except Exception as error:
            App.Console.PrintLog("FreeCAD: envelope look: %s\n" % error)
    return link


def is_envelope(comp):
    return bool(getattr(comp, ENVELOPE_PROP, False))


EXCLUDE_PROP = "FwExcludeBOM"


def is_excluded(comp):
    return bool(getattr(comp, EXCLUDE_PROP, False))


def set_excluded(comp, on=True):
    """Component Properties > Exclude from bill of materials."""
    if not hasattr(comp, EXCLUDE_PROP):
        comp.addProperty("App::PropertyBool", EXCLUDE_PROP, "FreeCAD", "Left out of the bill of materials")
        comp.setEditorMode(EXCLUDE_PROP, 2)
    setattr(comp, EXCLUDE_PROP, bool(on))


def _out_of_bom(comp):
    return is_envelope(comp) or is_excluded(comp)


def envelope_labels(doc):
    out = set()
    for obj in doc.Objects:
        if is_envelope(obj):
            out.add(obj.Label)
            out.add(ac.part_name(obj))
    return out


def _file(comp):
    try:
        return comp.getLinkedObject(True).Document.FileName or ""
    except Exception:
        return ""


def filter_bom(bom):
    ""

    doc = bom.Document
    asm = ac.assembly_of(doc)
    if asm is None:
        return False
    comps = ac.components(asm)
    env = [c for c in comps if _out_of_bom(c)]
    if not env:
        return False
    keep = {_file(c) for c in comps if not _out_of_bom(c)}
    files = {_file(c) for c in env} - keep - {""}
    labels = {c.Label for c in env}
    removed = False
    try:
        cols = _columns(bom)
        rows = _rows(bom)
        for r in reversed(range(2, rows + 1)):
            values = [str(_cell(bom, "%s%d" % (c, r))).lstrip("'") for c in cols]
            if any(v in files or v in labels for v in values):
                bom.removeRows(str(r), 1)
                removed = True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: envelope BOM: %s\n" % error)
    return removed


def _cell(sheet, addr):
    try:
        return sheet.getContents(addr) or ""
    except Exception:
        return ""


def _columns(sheet):
    out = []
    for i in range(26):
        c = chr(ord("A") + i)
        if not _cell(sheet, "%s1" % c):
            break
        out.append(c)
    return out


def _rows(sheet):
    n = 1
    while _cell(sheet, "A%d" % (n + 1)) or _cell(sheet, "B%d" % (n + 1)):
        n += 1
    return n


class _BomObserver:
    def slotRecomputedObject(self, obj):
        if obj.TypeId == "Assembly::BomObject" and not getattr(self, "busy", False):
            self.busy = True
            try:
                filter_bom(obj)
            finally:
                self.busy = False


_observer = None


def install_bom_filter():
    global _observer
    if _observer is None:
        _observer = _BomObserver()
        App.addDocumentObserver(_observer)


def patch_massprops():
    """Mass properties of an assembly: its components without the envelopes."""
    try:
        from . import massprops
    except Exception:
        return
    if getattr(massprops, "_fw_envelope", False):
        return
    old = massprops._targets

    def _targets():
        objs, label = old()
        out = []
        for obj in objs:
            if obj.TypeId == "Assembly::AssemblyObject":
                out += [c for c in ac.components(obj) if not is_envelope(c) and massprops._solids_of(c)
                        and (massprops.INCLUDE_HIDDEN or _shown(c))]
            elif not is_envelope(obj):
                out.append(obj)
        return out, label

    def _shown(c):
        vo = getattr(c, "ViewObject", None)
        return vo is None or vo.Visibility

    massprops._targets = _targets
    bm0 = massprops.body_material

    def body_material(obj):
        ""

        got = bm0(obj)
        if got[1] or obj is None or obj.TypeId not in ("App::Link", "Assembly::AssemblyLink"):
            return got
        try:
            from . import asmevaluate as ae
            over = ae.part_mass_override(obj)
            if over:
                vol = sum(s.Volume for s in massprops._solids_of(obj))
                if vol > 0:
                    return "(override)", over / (vol * 1e-6)
            part = obj.getLinkedObject(True)
            if getattr(part, "Document", None) is not None and part.Document is not obj.Document:
                d = ae._density(obj, 0.0)
                if d:
                    from . import material
                    return material.current(part.Document)[1] or "(part material)", d
        except Exception as error:
            App.Console.PrintLog("FreeCAD: component material: %s\n" % error)
        return got
    massprops.body_material = body_material
    massprops._fw_envelope = True


# ----------------------------------------------------------------------------- Thumbnail Preview
def thumbnail(doc, size=96):
    """The picture FreeCAD saved in the file (thumbnails/Thumbnail.png), else None."""
    path = getattr(doc, "FileName", "") or ""
    if not path or not os.path.isfile(path):
        return None
    try:
        with zipfile.ZipFile(path) as z:
            data = z.read("thumbnails/Thumbnail.png")
    except Exception:
        return None
    pm = QtGui.QPixmap()
    if not pm.loadFromData(data):
        return None
    return pm.scaled(size, size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)


# ----------------------------------------------------------------------------- Rotate context toolbar
class RotateBar(QtWidgets.QFrame):
    """X, Y, Z and the angle: each click turns the component that follows the pointer."""

    def __init__(self, panel):
        super().__init__(Gui.getMainWindow(), QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint)
        self.setObjectName("FW_InsertRotateBar")
        self.panel = panel
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)
        self.buttons = {}
        for axis in ("X", "Y", "Z"):
            b = QtWidgets.QToolButton()
            b.setObjectName("FW_InsertRotate%s" % axis)
            b.setText(axis)
            b.setToolTip("Rotate about %s" % axis)
            b.clicked.connect(lambda _=False, a=axis: panel.rotate(a))
            lay.addWidget(b)
            self.buttons[axis] = b
        self.angle = QtWidgets.QDoubleSpinBox()
        self.angle.setObjectName("FW_InsertRotateAngle")
        self.angle.setRange(-360.0, 360.0)
        self.angle.setDecimals(2)
        self.angle.setSuffix("deg")
        self.angle.setValue(90.0)
        lay.addWidget(self.angle)

    def moveEvent(self, event):
        super().moveEvent(event)
        from . import asmpm
        asmpm.keep_on_screen(self, True)      # pkg300: it follows the pointer, whole on the screen
