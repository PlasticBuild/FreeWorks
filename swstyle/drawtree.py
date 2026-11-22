
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

FOLDER_ICON = ":/icons/folder.svg"


class AnnotationsFolder:
    def __init__(self, obj):
        obj.Proxy = self
        if "SWAnnotationsFolder" not in obj.PropertiesList:
            obj.addProperty("App::PropertyBool", "SWAnnotationsFolder", "FreeCAD", "Annotations folder")
        obj.SWAnnotationsFolder = True

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


class AnnotationsFolderView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return FOLDER_ICON

    def claimChildren(self):
        return []

    def doubleClicked(self, vobj):
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def folder(doc):
    return next((o for o in doc.Objects if getattr(o, "SWAnnotationsFolder", False)), None)


def ensure_folder(doc):
    """The drawing's Annotations folder (made once)."""
    f = folder(doc)
    if f is not None:
        return f
    f = doc.addObject("App::FeaturePython", "Annotations")
    AnnotationsFolder(f)
    f.Label = "Annotations"
    try:
        import FreeCADGui as Gui
        if App.GuiUp and f.ViewObject is not None:
            AnnotationsFolderView(f.ViewObject)
    except Exception as _fw_err:
        _fw_log("drawtree.py:78", _fw_err)
    return f
