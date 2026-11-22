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
from PySide import QtCore

from . import paths

PARAM = "MatteFaces"
SPECULAR = (0x1A / 255.0,) * 3
SHININESS = 0.10
_FREECAD_SPECULAR = 0x88 / 255.0      # FreeCAD's default specular grey
_FREECAD_SHININESS = 0.90
SMOOTH = "SmoothCurves"
ANGULAR = 8.0                         # degrees, the display's angular deviation
_FREECAD_ANGULAR = 28.5
PART = "User parameter:BaseApp/Preferences/Mod/Part"

_observer = None
changed = []          # (document, object) made matte, for checks


def enabled():
    return paths.params().GetBool(PARAM, True)


def shiny_default(material):
    spec = material.SpecularColor
    return (abs(material.Shininess - _FREECAD_SHININESS) < 0.02
            and all(abs(c - _FREECAD_SPECULAR) < 0.02 for c in spec[:3]))


def smooth_enabled():
    return paths.params().GetBool(SMOOTH, True)


def smooth_default():
    """New parts drawn at ANGULAR, once: Mod/Part's value is the Options page's own."""
    store = paths.params()
    if not smooth_enabled() or store.GetBool("SmoothCurvesDefaultSet", False):
        return
    part = App.ParamGet(PART)
    if abs(part.GetFloat("MeshAngularDeflection", _FREECAD_ANGULAR) - _FREECAD_ANGULAR) < 1e-6:
        part.SetFloat("MeshAngularDeflection", ANGULAR)
    store.SetBool("SmoothCurvesDefaultSet", True)


def make_smooth(doc):
    """Redraws the parts of doc still at FreeCAD's 28.5° at the angular deviation of the Options."""
    if not smooth_enabled() or doc is None:
        return 0
    try:
        if "FreeWorks:Image_Quality_Angular_deviation" in dict(doc.Meta):     # QUALITY
            return 0        # the document keeps its own Image Quality (Document Properties): left as saved
    except Exception as _fw_err:
        _fw_log("matte.py:79", _fw_err)
    angular = App.ParamGet(PART).GetFloat("MeshAngularDeflection", _FREECAD_ANGULAR)
    if angular >= _FREECAD_ANGULAR - 1e-6:
        return 0
    n = 0
    for obj in doc.Objects:
        vo = getattr(obj, "ViewObject", None)
        try:
            if vo is None or not hasattr(vo, "AngularDeflection"):
                continue
            if abs(float(vo.AngularDeflection) - _FREECAD_ANGULAR) < 1e-6:
                vo.AngularDeflection = angular
                n += 1
        except Exception as _fw_err:
            _fw_log("matte.py:93", _fw_err)
    return n


def make_matte(doc):
    """Gives every appearance of doc still at FreeCAD's shiny default the matte shine (and its
    round faces the smooth drawing)."""
    if doc is None:
        return 0
    make_smooth(doc)
    if not enabled():
        return 0
    n = 0
    for obj in doc.Objects:
        vo = getattr(obj, "ViewObject", None)
        if vo is None or not hasattr(vo, "ShapeAppearance"):
            continue
        try:
            looks = list(vo.ShapeAppearance)
        except Exception:
            continue
        if not looks or not any(shiny_default(m) for m in looks):
            continue
        for m in looks:
            if shiny_default(m):
                m.SpecularColor = SPECULAR + (1.0,)
                m.Shininess = SHININESS
        try:
            vo.ShapeAppearance = looks
            changed.append((doc.Name, obj.Name))
            n += 1
        except Exception as _fw_err:
            _fw_log("matte.py:125", _fw_err)
    return n


class _Observer:
    def __init__(self):
        self.seen = set()

    def slotFinishRestoreDocument(self, doc):
        self.later(doc.Name)

    def slotActivateDocument(self, doc):
        # as cleanopen.py: FreeCAD 1.1 tells Python little when a file finishes opening
        if doc.FileName:
            self.later(doc.Name)

    def later(self, name):
        if name in self.seen:
            return
        self.seen.add(name)
        # once the view's looks are read back, and after cleanopen.py has seen the file open clean
        QtCore.QTimer.singleShot(300, lambda: make_matte(App.listDocuments().get(name)))

    def slotDeletedDocument(self, doc):
        self.seen.discard(doc.Name)

    def slotCreatedObject(self, obj):
        # a shape made in a document with its own Image Quality is drawn at it (the view object is
        # made after this signal: right after)
        try:
            meta = obj.Document.Meta
            if not any(k in meta for k in QUALITY):
                return
        except Exception:
            return
        QtCore.QTimer.singleShot(0, lambda d=obj.Document.Name, n=obj.Name: document_quality(d, n))


QUALITY = {"FreeWorks:Image_Quality_Angular_deviation": "AngularDeflection",
           "FreeWorks:Image_Quality_Deviation": "Deviation"}


def document_quality(doc_name, obj_name):
    """Document Properties > Image Quality kept in the file, on one new object."""
    doc = App.listDocuments().get(doc_name)
    obj = doc.getObject(obj_name) if doc is not None else None
    vo = getattr(obj, "ViewObject", None)
    if vo is None:
        return
    meta = dict(doc.Meta)
    for key, prop in QUALITY.items():
        if key in meta and prop in vo.PropertiesList:
            try:
                setattr(vo, prop, float(meta[key]))
            except Exception as _fw_err:
                _fw_log("matte.py:180", _fw_err)


def install():
    global _observer
    if _observer is not None:
        return
    smooth_default()
    _observer = _Observer()
    App.addDocumentObserver(_observer)
    # FreeCAD 1.1 sends no restore signals to Python: restorehook reports opened files instead
    from . import restorehook
    restorehook.on_restored(_observer.slotFinishRestoreDocument)
    for doc in App.listDocuments().values():
        _observer.slotActivateDocument(doc)


def remove():
    global _observer
    if _observer is not None:
        try:
            App.removeDocumentObserver(_observer)
        except Exception as _fw_err:
            _fw_log("matte.py:203", _fw_err)
    _observer = None
