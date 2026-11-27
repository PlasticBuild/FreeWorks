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
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

TEMPLATE_TYPES = {"Part": ("Part Templates (*.FCStd)", ("FCStd",), "parttemplate"),
                  "Assembly": ("Assembly Templates (*.FCStd)", ("FCStd",), "asmtemplate"),
                  "Drawing": ("Drawing Templates (*.FCStd)", ("FCStd",), "drawtemplate")}
WRITERS = {t[2] for t in TEMPLATE_TYPES.values()}
DETACHED = ("Detached Drawing (*.FCStd)", ("FCStd",), "detached")
_DONE = []


def folder():
    from . import newdoc
    out = os.path.join(newdoc.templates_folder(), "Templates")
    try:
        os.makedirs(out, exist_ok=True)
    except OSError as _fw_err:
        _fw_log("drawtemplates.py:37", _fw_err)
    return out


def install():
    if _DONE:
        return
    try:
        wrap_default_row()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Default Templates > Drawings: %s\n" % error)
    try:
        from . import saveas
    except Exception:
        return
    _DONE.append(True)
    old_types, old_write, old_dialog = saveas.save_types, saveas.write, saveas.save_dialog

    def save_types(doc):
        out = list(old_types(doc))
        # the template types are saveas.py's own since Features 179
        if saveas.kind_of(doc) == "Drawing" and DETACHED not in out:
            labels = [x[0] for x in out]
            at = labels.index(TEMPLATE_TYPES["Drawing"][0]) + 1 if TEMPLATE_TYPES["Drawing"][0] in labels else 1
            out.insert(at, DETACHED)
        return tuple(out)

    def write(doc, path, writer):
        if writer == DETACHED[2]:
            from . import drawmaint
            return drawmaint.save_detached(doc, path)
        return old_write(doc, path, writer)

    def save_dialog(doc):
        box, types = old_dialog(doc)

        def chosen(label):
            if any(label == t[0] for t in TEMPLATE_TYPES.values()):
                box.setDirectory(folder())
        box.filterSelected.connect(chosen)
        return box, types
    saveas.save_types, saveas.write, saveas.save_dialog = save_types, write, save_dialog
    try:
        wrap_new()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: New from a drawing template: %s\n" % error)


def save_template(doc, path):
    ""
    if not path.lower().endswith(".fcstd"):
        path += ".FCStd"
    doc.saveAs(path)
    try:
        Gui.getDocument(doc.Name).Modified = False
    except Exception as _fw_err:
        _fw_log("drawtemplates.py:89", _fw_err)
    return path


def drawing_templates():
    """[(name, path)] of the drawing templates on the Templates tabs."""
    from . import newdoc
    out = []
    for _tab, entries in newdoc.template_tabs():
        for name, target in entries:
            if os.path.isfile(str(target)) and newdoc._kind_of_template(target) == "Drawing":
                out.append((name, target))
    return out


def prompt_on():
    try:
        from . import paths
        return paths.params().GetBool("TemplatePrompt", False)
    except Exception as _fw_err:
        _fw_log("drawtemplates.py:110", _fw_err)
        return False


PICK_ANSWER = []      # checks: the answer the box would give ("" = the plain drawing, a path, or None = Cancel)


def pick_drawing_template():
    ""

    temps = drawing_templates()
    if not temps or not prompt_on():
        return ""
    if PICK_ANSWER:
        return PICK_ANSWER[0]
    box = QtWidgets.QDialog(Gui.getMainWindow())
    box.setObjectName("SWDrawingTemplatePick")
    box.setWindowTitle("New Document")
    lay = QtWidgets.QVBoxLayout(box)
    lay.addWidget(QtWidgets.QLabel("Select a drawing template:", box))
    lst = QtWidgets.QListWidget(box)
    lst.setObjectName("SWDrawingTemplates")
    it = QtWidgets.QListWidgetItem("Drawing", lst)
    it.setData(QtCore.Qt.UserRole, "")
    for name, path in temps:
        it = QtWidgets.QListWidgetItem(name, lst)
        it.setData(QtCore.Qt.UserRole, path)
    lst.setCurrentRow(0)
    lst.itemDoubleClicked.connect(lambda *_: box.accept())
    lay.addWidget(lst)
    bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, box)
    bb.accepted.connect(box.accept)
    bb.rejected.connect(box.reject)
    lay.addWidget(bb)
    if box.exec() != QtWidgets.QDialog.Accepted or lst.currentItem() is None:
        return None
    return lst.currentItem().data(QtCore.Qt.UserRole) or ""


def open_drawing_template(path):
    ""


    import shutil
    from . import newdoc, drawings as D
    stem = {k[0]: k[4] for k in newdoc.KINDS}["Drawing"]
    name = newdoc._next_name(stem)
    copy = os.path.join(D.temp_dir(), name + ".FCStd")
    shutil.copyfile(path, copy)
    doc = App.openDocument(copy)
    doc.Label = name
    D.temp_save(doc)
    doc.recompute()
    return doc


def wrap_new():
    """File > New > a drawing template: the same route as Make Drawing (run time wrap of newdoc's)."""
    from . import newdoc
    old = newdoc.make_from_template
    if getattr(old, "_fw_drawtemplates", False):
        return

    def make_from_template(path):
        try:
            if newdoc._kind_of_template(path) == "Drawing":
                doc = open_drawing_template(path)
                pages = [o for o in doc.Objects if o.TypeId == "TechDraw::DrawPage"]
                if pages:
                    newdoc.show_sheet(pages[0])
                return doc
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: drawing template: %s\n" % error)
        return old(path)
    make_from_template._fw_drawtemplates = True
    newdoc.make_from_template = make_from_template


# --------------------------------------------------------------------------- shipped sheet formats and templates

# (file name, sheet size, drafting standard, units)
SHIPPED = (("Drawing (ANSI)", "A (ANSI) Landscape", "ANSI", "mm"),
           ("Drawing (ISO)", "A3 (ISO)", "ISO", "mm"))
SHIPPED_PARAM = "ShippedDrawingTemplates"
SHIPPED_VERSION = 1


def wrap_formats():
    ""
    return None


def _params():
    return App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks")


def ensure_shipped(force=False):
    ""

    p = _params()
    if not force and p.GetInt(SHIPPED_PARAM, 0) >= SHIPPED_VERSION:
        return []
    made = []
    for name, size, std, units in SHIPPED:
        path = os.path.join(folder(), name + ".FCStd")
        if os.path.isfile(path) and not force:
            continue
        if make_template(path, size, std, units):
            made.append(path)
    p.SetInt(SHIPPED_PARAM, SHIPPED_VERSION)
    return made


def make_template(path, size, std, units):
    """A drawing template file: one sheet with the size's sheet format (its fields linked to properties) and the
    drafting standard's Document Properties."""
    from . import drawsheet, drawdocprops, drawings as D
    fmt = drawsheet.size_path(size)
    if not fmt:
        return False
    doc = App.newDocument("FWDrawingTemplate", hidden=True)
    try:
        page = doc.addObject("TechDraw::DrawPage", "Sheet1")
        page.Label = "Sheet1"
        tpl = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
        tpl.Template = fmt
        page.Template = tpl
        values = dict(drawdocprops.stored(doc))
        values["standard"] = std
        values.update({k: v for k, v in drawdocprops.standard_preset(std).items()})
        values["units"] = units
        values["sheet_format"] = size
        drawdocprops.set_props(doc, values)
        try:
            drawdocprops.apply_page(page, dict(drawdocprops.defaults(), **values))
        except Exception as error:
            App.Console.PrintLog("FreeCAD: template sheet: %s\n" % error)
        doc.recompute()
        try:
            D.default_field_links(page)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: template fields: %s\n" % error)
        doc.recompute()
        doc.saveAs(path)
        return True
    finally:
        App.closeDocument(doc.Name)


# --------------------------------------------------------------------------- Options > Default Templates > Drawings

# starts on newdoc.sheet_template() (the drafting standard's sheet format); TechDraw's TemplateFile is blank on a
# fresh install. The row shows that real default; a sheet format picked there is what new drawings then use
# (and TechDraw's own default, kept the same). Run time wraps of newdoc's and optionspages' (not this thread's).
DEFAULT_PARAM = "DrawingTemplate"
_TD = "User parameter:BaseApp/Preferences/Mod/TechDraw/Files"


def chosen_drawing_template():
    """The sheet format picked in Default Templates > Drawings, when it is there ("" = none picked)."""
    path = _params().GetString(DEFAULT_PARAM, "")
    return path if path and os.path.isfile(path) else ""


def default_drawing_template():
    ""
    path = chosen_drawing_template()
    if path:
        return path
    from . import newdoc
    old = getattr(newdoc.sheet_template, "_fw_old", newdoc.sheet_template)
    try:
        path = old() or ""
    except Exception as _fw_err:
        _fw_log("drawtemplates.py:default sheet", _fw_err)
        path = ""
    if not path:
        path = App.ParamGet(_TD).GetString("TemplateFile", "")
    if not path:          # stock TechDraw's own default when its preference is blank
        for root in (App.getResourceDir(), os.path.join(App.getResourceDir(), "share")):
            p = os.path.join(root, "Mod", "TechDraw", "Templates", "Default_Template_A4_Landscape.svg")
            if os.path.isfile(p):
                return p
    return path


def set_default_drawing_template(path):
    """The row's write: a path other than the shown default becomes new drawings' sheet format; blank or the
    same default leaves new drawings following the drafting standard."""
    path = (path or "").strip()
    p = _params()
    if not path:
        p.SetString(DEFAULT_PARAM, "")
        return ""
    if os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(default_drawing_template())):
        return path                    # unchanged: OK on the box writes nothing new
    p.SetString(DEFAULT_PARAM, path)
    App.ParamGet(_TD).SetString("TemplateFile", path)
    return path


def wrap_default_row():
    from . import newdoc
    if not getattr(newdoc.sheet_template, "_fw_drawtemplates", False):
        old = newdoc.sheet_template

        def sheet_template():
            return chosen_drawing_template() or old()
        sheet_template._fw_drawtemplates = True
        sheet_template._fw_old = old
        newdoc.sheet_template = sheet_template
    try:
        from . import optionspages
    except Exception:
        return
    if hasattr(optionspages, "_tech_template_read") and \
            not getattr(optionspages._tech_template_read, "_fw_drawtemplates", False):
        default_drawing_template._fw_drawtemplates = True
        optionspages._tech_template_read = default_drawing_template
        optionspages._tech_template_write = set_default_drawing_template
