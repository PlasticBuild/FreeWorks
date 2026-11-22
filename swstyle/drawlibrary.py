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

import json
import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import drawings as D

ANNOT_FILES = (".fwblock", ".svg", ".fwtbt")
_DONE = []


def annotations_folder():
    from . import designlib
    out = os.path.join(designlib.library_root(), "annotations")
    try:
        os.makedirs(out, exist_ok=True)
    except OSError as _fw_err:
        _fw_log("drawlibrary.py:40", _fw_err)
    return out


# --------------------------------------------------------------------------- Add to Library (drawing)
def add_annotations(objs, folder=None, name=None):
    """Add to Library on a drawing: the picked notes / symbols (or one block) as a file in folder (the
    library's annotations folder). Returns the path."""
    from . import drawblocks as B
    folder = folder or annotations_folder()
    tables = [o for o in objs if o.TypeId == "TechDraw::DrawViewSpreadsheet"]
    objs = [o for o in objs if o.TypeId == "TechDraw::DrawViewSymbol"]
    if tables and not objs:
        from . import drawtables as T                 # a table (a title block table): its table template
        return T.save_table_template(tables[0], os.path.join(folder, (name or tables[0].Label).replace(" ", "_")
                                                             + ".fwtbt"))
    if not objs:
        return None
    if len(objs) == 1 and getattr(objs[0], "SWAnnotation", "") == "Block":
        base = name or objs[0].SWBlockName
        return B.save_block(objs[0], os.path.join(folder, base + ".fwblock"))
    at = (sum(float(o.X) for o in objs) / len(objs), sum(float(o.Y) for o in objs) / len(objs))
    members = [B.member_of(o, at) for o in objs]
    base = name or objs[0].Label.replace(" ", "_")
    path = os.path.join(folder, base + ".fwblock")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"FreeWorksBlock": 1, "FreeWorksAnnotation": 1, "name": base, "members": members,
                   "at": list(at)}, f)
    return path


# --------------------------------------------------------------------------- dropping on a sheet
def insert(path, page, at):
    """An annotation file from the library onto page at sheet point at: [objects made]."""
    from . import drawblocks as B
    if not path or os.path.splitext(path)[1].lower() not in ANNOT_FILES or page is None:
        return []
    if path.lower().endswith(".fwtbt"):
        return insert_table(path, page, at)
    origin = None
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        data = json.loads(text) if text.lstrip().startswith("{") else {}
        annot = data.get("FreeWorksAnnotation")
        if data.get("at"):
            origin = tuple(data["at"])[:2]
    except Exception:
        annot = False
    name, members = B.load_block(path)
    doc = page.Document
    doc.openTransaction("Insert from Library")
    try:
        if annot or path.lower().endswith(".svg"):
            inst = B.place_block(page, name, members, at)
            made = B.explode_block(page, inst)      # notes and symbols come in as themselves
        else:
            if name in B.blocks_in(doc) and B.blocks_in(doc)[name] != members:
                name = B.next_block_name(doc)
            made = [B.place_block(page, name, members, at)]
        delta = (at[0] - origin[0], at[1] - origin[1]) if origin else None
        for o in made:
            settle(page, o, at, delta)
    finally:
        doc.commitTransaction()
    doc.recompute()
    return made


def settle(page, o, at, delta=None):
    """A dropped annotation: its leader point moves with it, it attaches to the view under the drop point (else
    the sheet; the library file's own attachment is from another drawing), and a property-linked note reads this
    drawing's properties."""
    from . import drawattach as DT
    from . import drawviews as DV
    tip = getattr(o, "SWTip", None)
    if tip is not None and tip.z >= 0 and delta is not None:
        o.SWTip = App.Vector(tip.x + delta[0], tip.y + delta[1], 0)
    for p in ("SWAttachedTo", "SWAttachAt"):
        if p in o.PropertiesList:
            o.removeProperty(p)
    if DT.attachable(o):
        DT.attach(o, DV.focus_view(page, at, margin=0.0))
    relink(page, o)


def relink(page, o):
    """A note whose text has $PRP links: drawn again with this drawing's property values."""
    from . import drawannot as DA
    raw = getattr(o, "SWText", "") or ""
    if "$PRP" not in raw or getattr(o, "SWAnnotation", "") != "Note":
        return False
    tip = getattr(o, "SWTip", None)
    tip = (tip.x, tip.y) if tip is not None and tip.z >= 0 else None
    try:
        f = json.loads(getattr(o, "SWNoteOptions", "") or "{}")
    except Exception:
        f = {}
    if not f:
        fmt = (getattr(o, "SWNoteFormat", "") or "").split("|")
        if len(fmt) == 4:
            f = dict(align=fmt[0], angle=float(fmt[1]), size=float(fmt[2]), border=fmt[3])
    import inspect
    names = set(inspect.signature(DA.note_svg).parameters)
    f = {k: v for k, v in f.items() if k in names and k not in ("text", "at", "tip")}
    text = DA.resolve_properties(page, raw, tip)
    body, reach = DA.note_svg(text, (float(o.X), float(o.Y)), tip, **f)
    R = max(5.0, reach + 5.0)
    o.Symbol = ('<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" viewBox="%g %g %g %g">%s</svg>'
                % (2 * R, 2 * R, -R, -R, 2 * R, 2 * R, body))
    return True


def insert_table(path, page, at):
    ""

    from . import drawtables as T
    try:
        with open(path, encoding="utf-8") as f:
            kind = json.load(f).get("kind") or "General"
        rows, widths = T.load_table_template(path)
    except Exception as _fw_err:
        _fw_log("drawlibrary.py:163", _fw_err)
        return []
    doc = page.Document
    doc.openTransaction("Insert from Library")
    try:
        t = T.make_table(page, rows, at, os.path.splitext(os.path.basename(path))[0].replace("_", " "), kind, widths)
    finally:
        doc.commitTransaction()
    doc.recompute()
    return [t] if t is not None else []


class _SheetDrop(QtCore.QObject):
    def eventFilter(self, obj, event):
        from . import designlib
        if not isinstance(event, QtCore.QEvent):
            return False
        t = event.type()
        if t not in (QtCore.QEvent.DragEnter, QtCore.QEvent.DragMove, QtCore.QEvent.Drop):
            return False
        md = event.mimeData()
        if not md.hasFormat(designlib.MIME):
            return False
        path = bytes(md.data(designlib.MIME)).decode()
        if os.path.splitext(path)[1].lower() not in ANNOT_FILES:
            return False
        if t != QtCore.QEvent.Drop:
            event.acceptProposedAction()
            return True
        page = obj.property("swDropPage")
        doc = App.ActiveDocument
        page = doc.getObject(page) if doc is not None and page else D.active_page()
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        gv = obj.parent()
        sp = gv.mapToScene(pos)
        at = (sp.x() / D.REZ, -sp.y() / D.REZ)
        QtCore.QTimer.singleShot(0, lambda p=path, pg=page, a=at: insert(p, pg, a))
        event.acceptProposedAction()
        return True


_drop = []


def watch_sheets():
    """Every open sheet's view takes Design Library drops."""
    if not _drop:
        _drop.append(_SheetDrop(Gui.getMainWindow()))
    for doc in App.listDocuments().values():
        for page in [o for o in doc.Objects if o.TypeId == "TechDraw::DrawPage"]:
            try:
                gv = D.page_view(page)
            except Exception:
                gv = None
            if gv is None:
                continue
            vp = gv.viewport()
            vp.setProperty("swDropPage", page.Name)
            if not vp.property("swLibraryDrops"):
                vp.setAcceptDrops(True)
                vp.installEventFilter(_drop[0])
                vp.setProperty("swLibraryDrops", True)


def install():
    """designlib lists annotation files and arms the sheets when a drag starts; Add to Library on a drawing."""
    if _DONE:
        return
    try:
        from . import designlib
    except Exception:
        return
    _DONE.append(True)
    designlib.FILES = tuple(designlib.FILES) + tuple(e for e in ANNOT_FILES if e not in designlib.FILES)
    old_watch = designlib.watch_views

    def watch_views():
        old_watch()
        try:
            watch_sheets()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: library drops on sheets: %s\n" % error)
    designlib.watch_views = watch_views
    old_add = designlib.add_selection

    def add_selection(folder, name=None):
        page = D.active_page() if D.in_drawing() else None
        if page is not None:
            objs = [s.Object for s in Gui.Selection.getSelectionEx(page.Document.Name)]
            if any(o.TypeId in ("TechDraw::DrawViewSymbol", "TechDraw::DrawViewSpreadsheet") for o in objs):
                return add_annotations(objs, folder, name)
        return old_add(folder, name)
    designlib.add_selection = add_selection
