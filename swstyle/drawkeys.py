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
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import drawings as D

Qt = QtCore.Qt
PARAM = "User parameter:BaseApp/Preferences/Mod/FreeWorks/Drawings"
CLIP = {"doc": None, "names": []}
HISTORY = {}                 # id(page view) -> [(transform, h scroll, v scroll)]
SKIP = ("TechDraw::DrawPage", "TechDraw::DrawSVGTemplate", "TechDraw::DrawParametricTemplate")


def increment():
    ""
    return App.ParamGet(PARAM).GetFloat("KeyboardMovementIncrement", 10.0)


def _page_of(gv):
    page = D.active_page()
    if page is None:
        return None
    try:
        return page if D.page_view(page) is gv else None
    except Exception:
        return None


def sheet_items(page):
    """Everything on the sheet: its views (projection group members too) and annotations."""
    out = []

    def add(views):
        for v in views:
            if v.TypeId in SKIP or v in out:
                continue
            out.append(v)
            if v.TypeId == "TechDraw::DrawProjGroup":
                add(list(v.Views))
    add(list(page.Views))
    return out


def picked(page):
    """The picked views and annotations (whole objects: an edge picked inside a view does not count)."""
    items = sheet_items(page)
    out = []
    for s in Gui.Selection.getSelectionEx(page.Document.Name):
        o = s.Object
        if o in items and not [n for n in s.SubElementNames if n] and o not in out:
            out.append(o)
    return out


def select_all(page):
    Gui.Selection.clearSelection()
    for o in sheet_items(page):
        Gui.Selection.addSelection(page.Document.Name, o.Name)


def dependents(objs, page):
    """objs and what hangs on them on this sheet (dimensions, balloons, projected / section / detail views)."""
    items = sheet_items(page)
    out = list(objs)
    for o in objs:
        for d in o.InListRecursive:
            if d in items and d not in out:
                out.append(d)
    return out


CONFIRM_ANSWER = [None]     # checks: the Confirm Delete answer given at once (1 Yes, 2 Yes to All, 3 No, 4 Cancel)
_KINDS = {"TechDraw::DrawViewDimension": "Dimension", "TechDraw::DrawViewBalloon": "Balloon",
          "TechDraw::DrawLeaderLine": "Leader", "TechDraw::DrawViewSpreadsheet": "Table",
          "TechDraw::DrawViewSymbol": "Annotation", "TechDraw::DrawViewAnnotation": "Note"}


def _is_view(o):
    return o.isDerivedFrom("TechDraw::DrawViewPart") or o.TypeId == "TechDraw::DrawProjGroup"


def _kind(o):
    if _is_view(o):
        return "Drawing View"
    return getattr(o, "SWAnnotation", "") or _KINDS.get(o.TypeId, "Annotation")


def confirm_views(objs, page):
    ""


    from . import confirmdelete as CD
    views = [o for o in objs if _is_view(o)]
    if not views or not CD.params().GetBool("FeatureAsk", True):
        return objs
    keep = [o for o in objs if not _is_view(o)]
    ask = True
    for v in views:
        if not ask:
            keep.append(v)
            continue
        box = CD.ConfirmDelete(v, len(views) > 1)
        box.name.setText("%s ( %s )" % (v.Label, _kind(v)))
        for w in (box.absorbed_box, box.child_box, box.equation_box, box.advanced):
            w.setVisible(False)
            try:
                w.toggled.disconnect()
            except Exception as _fw_err:
                _fw_log("drawkeys.py:confirm disconnect", _fw_err)
        box.list.clear()
        box.list.setRootIsDecorated(False)
        for o in dependents([v], page)[1:]:
            box.list.addTopLevelItem(QtWidgets.QTreeWidgetItem(["%s ( %s )" % (o.Label, _kind(o))]))
        if CONFIRM_ANSWER[0] is not None:
            box.answer = CONFIRM_ANSWER[0]
        else:
            box.exec()
        if box.answer == box.CANCEL:
            return None
        if box.answer in (box.YES, box.YES_ALL):
            keep.append(v)
        if box.answer == box.YES_ALL:
            ask = False
    return keep


def delete(page, objs=None, ask=True):
    objs = picked(page) if objs is None else objs
    if objs and ask:
        objs = confirm_views(objs, page)
    if not objs:
        return False
    doc = page.Document
    gone = dependents(objs, page)
    doc.openTransaction("Delete")
    try:
        Gui.Selection.clearSelection()
        # dependents first, so nothing is left pointing at a removed view
        for o in reversed(gone):
            try:
                if doc.getObject(o.Name) is not None:
                    doc.removeObject(o.Name)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: Delete %s: %s\n" % (o.Label, error))
    finally:
        doc.commitTransaction()
    doc.recompute()
    return True


def nudge(page, dx, dy, objs=None):
    """Move the picked items by (dx, dy) mm on the sheet (locked ones stay)."""
    objs = picked(page) if objs is None else objs
    objs = [o for o in objs if not getattr(o, "LockPosition", False) and hasattr(o, "X")]
    if not objs:
        return False
    doc = page.Document
    doc.openTransaction("Move")
    try:
        for o in objs:
            try:
                o.X = float(o.X) + dx
                o.Y = float(o.Y) + dy
            except Exception as _fw_err:
                _fw_log("drawkeys.py:131", _fw_err)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    doc.recompute()
    return True


def pan(gv, dx, dy):
    for bar, d in ((gv.horizontalScrollBar(), dx), (gv.verticalScrollBar(), dy)):
        bar.setValue(bar.value() + int(d * max(bar.pageStep(), 20) * 0.1))


NOT_COPIED = ("Proxy", "ExpressionEngine", "Label", "Visibility")


def snapshot(o):
    """What a cut item needs to be made again: its type, Python class and properties."""
    props = []
    for name in o.PropertiesList:
        if name in NOT_COPIED:
            continue
        try:
            props.append((name, o.getTypeIdOfProperty(name), o.getGroupOfProperty(name),
                          o.getDocumentationOfProperty(name), o.getPropertyByName(name)))
        except Exception as _fw_err:
            _fw_log("drawkeys.py:155", _fw_err)
    proxy = getattr(o, "Proxy", None)
    return {"type": o.TypeId, "name": o.Name, "label": o.Label, "props": props,
            "proxy": type(proxy) if proxy is not None and not isinstance(proxy, (str, bytes)) else None,
            "vproxy": type(o.ViewObject.Proxy) if getattr(o, "ViewObject", None) is not None and
            getattr(o.ViewObject, "Proxy", None) is not None else None}


def remake(doc, snap):
    o = doc.addObject(snap["type"], snap["name"])
    if snap["proxy"] is not None:
        try:
            snap["proxy"](o)
        except Exception as _fw_err:
            _fw_log("drawkeys.py:169", _fw_err)
    for name, kind, group, doc_text, value in snap["props"]:
        try:
            if name not in o.PropertiesList:
                o.addProperty(kind, name, group, doc_text)
            setattr(o, name, value)
        except Exception as _fw_err:
            _fw_log("drawkeys.py:176", _fw_err)
    if snap["vproxy"] is not None and getattr(o, "ViewObject", None) is not None:
        try:
            snap["vproxy"](o.ViewObject)
        except Exception as _fw_err:
            _fw_log("drawkeys.py:181", _fw_err)
    return o


def copy(page, objs=None):
    objs = picked(page) if objs is None else objs
    CLIP["doc"] = page.Document.Name if objs else None
    CLIP["names"] = [o.Name for o in objs]
    CLIP["snaps"] = [snapshot(o) for o in objs]
    return bool(objs)


def _pointer(page):
    gv = D.page_view(page)
    if gv is None:
        return None
    vp = gv.viewport().mapFromGlobal(QtGui.QCursor.pos())
    if not gv.viewport().rect().contains(vp):
        return None
    sp = gv.mapToScene(vp)
    return sp.x() / D.REZ, -sp.y() / D.REZ


def paste_from(page, at=None):
    """Paste into another drawing: copies of the clipboard's views (and the annotations on them) from the drawing
    they were copied in, the first at the pointer (else where it was)."""
    try:
        src = App.getDocument(CLIP["doc"]) if CLIP.get("doc") else None
    except Exception:
        src = None
    if src is None:
        return []
    objs = [src.getObject(n) for n in CLIP.get("names") or []]
    views = [o for o in objs if o is not None and o.isDerivedFrom("TechDraw::DrawViewPart")]
    if not views:
        return []
    doc = page.Document
    at = at if at is not None else _pointer(page)
    doc.openTransaction("Paste")
    made = []
    try:
        first = (float(views[0].X), float(views[0].Y))
        ox, oy = (at[0] - first[0], at[1] - first[1]) if at is not None else (0.0, 0.0)
        for o in views:
            c = doc.copyObject(o, False)
            from . import drawviews as DV
            src_shapes = DV.xsource(o) or list(getattr(o, "Source", []) or [])
            try:
                c.Source = []
                D.link_source(c, src_shapes)    # the same model, linked from this drawing's file
            except Exception as _fw_err:
                _fw_log("drawkeys.py:232", _fw_err)
            page.addView(c)
            c.X, c.Y = float(o.X) + ox, float(o.Y) + oy
            made.append(c)
    finally:
        doc.commitTransaction()
    doc.recompute()
    Gui.Selection.clearSelection()
    for c in made:
        Gui.Selection.addSelection(doc.Name, c.Name)
    return made


def paste(page, at=None):
    """Copies of the clipboard's views and annotations on this sheet: the first one at the pointer (else 10 mm
    off the original); a dimension or balloon stays on its view, 5 mm off."""
    doc = page.Document
    if CLIP["doc"] != doc.Name:
        return paste_from(page, at)
    snaps = CLIP.get("snaps") or []
    if not snaps:
        return []
    at = at if at is not None else _pointer(page)
    doc.openTransaction("Paste")
    made = []
    try:
        first = None
        for snap in snaps:
            o = doc.getObject(snap["name"])
            if o is not None and o.TypeId == snap["type"]:
                c = doc.copyObject(o, False)
            else:
                o = c = remake(doc, snap)        # cut: made again from what was kept
            page.addView(c)
            on_view = o.TypeId in ("TechDraw::DrawViewDimension", "TechDraw::DrawViewBalloon")
            try:
                if on_view:
                    c.X, c.Y = float(o.X) + 5.0, float(o.Y) + 5.0
                else:
                    if first is None:
                        first = (float(o.X), float(o.Y))
                    ox, oy = (at[0] - first[0], at[1] - first[1]) if at is not None else (10.0, -10.0)
                    c.X, c.Y = float(o.X) + ox, float(o.Y) + oy
            except Exception as _fw_err:
                _fw_log("drawkeys.py:276", _fw_err)
            made.append(c)
    finally:
        doc.commitTransaction()
    doc.recompute()
    Gui.Selection.clearSelection()
    for c in made:
        Gui.Selection.addSelection(doc.Name, c.Name)
    return made


def remember(gv):
    h = HISTORY.setdefault(id(gv), [])
    state = (QtGui.QTransform(gv.transform()), gv.horizontalScrollBar().value(), gv.verticalScrollBar().value())
    if not h or h[-1][0] != state[0] or h[-1][1:] != state[1:]:
        h.append(state)
        del h[:-20]


def previous_view(gv):
    h = HISTORY.get(id(gv), [])
    if not h:
        return False
    t, x, y = h.pop()
    gv.setTransform(t)
    gv.horizontalScrollBar().setValue(x)
    gv.verticalScrollBar().setValue(y)
    return True


def print_sheet(page):
    try:
        Gui.runCommand("FreeWorks_DrawPrint", 0)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Print: %s\n" % error)


ARROWS = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, 1), Qt.Key_Down: (0, -1)}


def _owned(event):
    """The keys this layer takes on a sheet: (name, handler key)."""
    k, m = event.key(), event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier)
    ctrl = m == Qt.ControlModifier
    if m == Qt.NoModifier:
        if k in ARROWS:
            return "arrow"
        if k == Qt.Key_Delete:
            return "delete"
        if k == Qt.Key_Escape:
            return "escape"
    if ctrl and k == Qt.Key_A:
        return "all"
    if ctrl and k == Qt.Key_C:
        return "copy"
    if ctrl and k == Qt.Key_X:
        return "cut"
    if ctrl and k == Qt.Key_V:
        return "paste"
    if ctrl and k == Qt.Key_P:
        return "print"
    if ctrl and k == Qt.Key_B:
        return "rebuild"
    if m == (Qt.ControlModifier | Qt.ShiftModifier) and k == Qt.Key_Z:
        return "previous"
    return None


def _free(name):
    ""

    try:
        if name == "escape":
            try:
                from . import drawdimtools
                if drawdimtools.SMART:
                    return False        # Smart Dimension's own Esc: drop the picks, then end the tool
            except Exception as _fw_err:
                _fw_log("drawkeys.py:_free", _fw_err)
            if D.VIEW_PM and Gui.Control.activeDialog():
                return True             # a picked item's PM (keys stay on the sheet): Esc drops the pick, which closes it
            return not Gui.Control.activeDialog()
        return not D.busy()
    except Exception:
        return True


def _sheet_for(obj):
    """(page, its sheet view) when obj, the widget with the keyboard, is the sheet window in front (its view or
    the page window holding it), else (None, None)."""
    page = D.active_page()
    if page is None:
        return None, None
    try:
        gv = D.page_view(page)
    except Exception:
        return None, None
    if gv is None or not isinstance(obj, QtWidgets.QWidget):
        return None, None
    if obj is gv or obj is gv.viewport():
        return page, gv
    if obj is not Gui.getMainWindow() and obj.isAncestorOf(gv) and not isinstance(obj, QtWidgets.QMdiArea):
        return page, gv
    return None, None


class SheetKeys(QtCore.QObject):
    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False          # a stale PySide wrapper can arrive here
        try:
            t = event.type()
            if t == QtCore.QEvent.Wheel:
                gv = obj.parent() if not isinstance(obj, QtWidgets.QGraphicsView) else obj
                if isinstance(gv, QtWidgets.QGraphicsView) and _page_of(gv) is not None:
                    remember(gv)
                    if zoom_about_center():
                        k = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
                        anchor = gv.transformationAnchor()
                        gv.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorViewCenter)
                        gv.scale(k, k)
                        gv.setTransformationAnchor(anchor)
                        return True
                return False
            if t in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonRelease):
                gv = obj.parent() if isinstance(obj, QtWidgets.QWidget) else None
                if isinstance(gv, QtWidgets.QGraphicsView) and obj is gv.viewport() and _page_of(gv) is not None:
                    if PAN["on"]:
                        return self.pan_event(gv, event)
                    return _drag().handle(obj, event)
                return False
            if t not in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress):
                return False
            if obj is not QtWidgets.QApplication.focusWidget():
                return False
            page, gv = _sheet_for(obj)
            if page is None:
                return False
            if t == QtCore.QEvent.ShortcutOverride and event.modifiers() in (Qt.NoModifier, Qt.ShiftModifier) \
                    and event.key() in (Qt.Key_F, Qt.Key_Z):
                remember(gv)                       # F, Z, Shift+Z: the zoom before it, for Previous View
                return False
            name = _owned(event)
            if name is None or not _free(name):
                return False
            if name == "rebuild":
                from . import drawdocprops
                if not drawdocprops.held(page.Document):
                    return False                   # the add-on's own Ctrl+B rebuild
            if t == QtCore.QEvent.ShortcutOverride:
                event.accept()                     # the key comes to the sheet, not to a menu shortcut
                return True
            self.run(name, page, gv, event)
            return True
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: sheet key: %s\n" % error)
            return False

    def pan_event(self, gv, event):
        t = event.type()
        if t == QtCore.QEvent.MouseButtonPress:
            if event.button() != Qt.LeftButton:
                set_pan(False)                     # a right-click ends Pan, as Esc does
                return True
            PAN["from"] = event.globalPos() if hasattr(event, "globalPos") else event.globalPosition().toPoint()
            return True
        if t == QtCore.QEvent.MouseMove and PAN.get("from") is not None:
            now = event.globalPos() if hasattr(event, "globalPos") else event.globalPosition().toPoint()
            d = now - PAN["from"]
            PAN["from"] = now
            gv.horizontalScrollBar().setValue(gv.horizontalScrollBar().value() - d.x())
            gv.verticalScrollBar().setValue(gv.verticalScrollBar().value() - d.y())
            return True
        if t == QtCore.QEvent.MouseButtonRelease:
            PAN["from"] = None
            return True
        return False

    def run(self, name, page, gv, event):
        if name == "arrow":
            dx, dy = ARROWS[event.key()]
            if not nudge(page, dx * increment(), dy * increment()):
                pan(gv, dx, -dy)
        elif name == "delete":
            delete(page)
        elif name == "escape":
            if PAN["on"]:
                set_pan(False)
            else:
                Gui.Selection.clearSelection()
        elif name == "all":
            select_all(page)
        elif name == "copy":
            copy(page)
        elif name == "cut":
            objs = picked(page)
            if copy(page, objs):
                delete(page, objs, ask=False)          # Cut takes them without asking
        elif name == "paste":
            paste(page)
        elif name == "print":
            QtCore.QTimer.singleShot(0, lambda: print_sheet(page))
        elif name == "previous":
            previous_view(gv)
        elif name == "rebuild":
            from . import drawdocprops
            drawdocprops.release(page.Document)


PAN = {"on": False, "from": None}


def set_pan(on):
    PAN["on"], PAN["from"] = bool(on), None
    page = D.active_page()
    gv = D.page_view(page) if page is not None else None
    if gv is not None:
        if on:
            gv.viewport().setCursor(Qt.OpenHandCursor)
        else:
            gv.viewport().unsetCursor()


def zoom_about_center():
    return App.ParamGet(PARAM).GetBool("ZoomAboutScreenCenter", False)


# =========================================================================== commands (Edit and View > Modify)
COMMANDS = {
    "FreeWorks_DrawSelectAll": ("Select All", "Selects every view and annotation on the sheet (Ctrl+A).", "edit-select-all"),
    "FreeWorks_DrawCut": ("Cut", "Cuts the picked views and annotations (Ctrl+X).", "edit-cut"),
    "FreeWorks_DrawCopy": ("Copy", "Copies the picked views and annotations (Ctrl+C).", "edit-copy"),
    "FreeWorks_DrawPaste": ("Paste", "Pastes the copied views and annotations at the pointer (Ctrl+V).", "edit-paste"),
    "FreeWorks_DrawDelete": ("Delete", "Deletes the picked views and annotations (Delete).", "edit-delete"),
    "FreeWorks_DrawPreviousView": ("Previous View", "Goes back to the previous zoom of the sheet (Ctrl+Shift+Z).",
                                   "zoom-selection"),
    "FreeWorks_DrawPan": ("Pan", "Drag to move the sheet; Esc or a right-click ends it.", "zoom-border"),
    "FreeWorks_DrawZoomAboutCenter": ("Zoom About Screen Center",
                                      "The wheel zooms about the middle of the window instead of the pointer.",
                                      "zoom-in"),
}


class _Command:
    def __init__(self, name):
        self.name = name
        self.text, self.tip, self.icon = COMMANDS[name]

    def GetResources(self):
        r = {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": D.pixmap(self.icon)}
        if self.name == "FreeWorks_DrawZoomAboutCenter":
            r["Checkable"] = zoom_about_center()
        return r

    def IsActive(self):
        page = D.active_page()
        if page is None or not D.sheet_shown(page):
            return False
        n = self.name
        if n in ("FreeWorks_DrawCut", "FreeWorks_DrawCopy", "FreeWorks_DrawDelete"):
            return bool(picked(page))
        if n == "FreeWorks_DrawPaste":
            return CLIP["doc"] == page.Document.Name and bool(CLIP.get("snaps"))
        if n == "FreeWorks_DrawPreviousView":
            gv = D.page_view(page)
            return gv is not None and bool(HISTORY.get(id(gv)))
        return True

    def Activated(self, checked=None):
        page = D.active_page()
        if page is None:
            return
        gv = D.page_view(page)
        n = self.name
        if n == "FreeWorks_DrawSelectAll":
            select_all(page)
        elif n == "FreeWorks_DrawCut":
            objs = picked(page)
            if copy(page, objs):
                delete(page, objs, ask=False)          # Cut takes them without asking
        elif n == "FreeWorks_DrawCopy":
            copy(page)
        elif n == "FreeWorks_DrawPaste":
            paste(page)
        elif n == "FreeWorks_DrawDelete":
            delete(page)
        elif n == "FreeWorks_DrawPreviousView" and gv is not None:
            previous_view(gv)
        elif n == "FreeWorks_DrawPan":
            set_pan(True)
        elif n == "FreeWorks_DrawZoomAboutCenter":
            on = (not zoom_about_center()) if checked is None else bool(checked)
            App.ParamGet(PARAM).SetBool("ZoomAboutScreenCenter", on)


# --------------------------------------------------------------------------- dragging a view
DRAG_OPTION = ("Performance", "Show contents while dragging drawing view")


def show_contents_while_dragging():
    """System Options > Drawings > Performance > Show contents while dragging drawing view (default on)."""
    return bool(D.system_option(DRAG_OPTION[0], DRAG_OPTION[1], True))


def on_annotation_text(gv, pos):
    """The press is on a dimension's or balloon's text (found from their positions, not from sheet items:
    touching TechDraw's dimension items while it drags one aborted FreeCAD)."""
    page = _page_of(gv)
    if page is None:
        return False
    try:
        x, y = D.to_sheet(gv.mapToScene(pos))
        for o in page.Views:
            if o.TypeId not in ("TechDraw::DrawViewDimension", "TechDraw::DrawViewBalloon"):
                continue
            v = None
            if o.TypeId == "TechDraw::DrawViewDimension":
                for rv, _s in o.References2D or []:
                    v = rv
                    break
            else:
                v = getattr(o, "SourceView", None)
            if v is None:
                continue
            x0, y0 = D.view_position(v)
            if abs(x0 + float(o.X) - x) <= 8.0 and abs(y0 + float(o.Y) - y) <= 4.0:
                return True
    except Exception:
        return False
    return False


def view_item_at(gv, pos):
    """The sheet item of the drawing view (not an annotation) under a viewport point, with its object."""
    page = _page_of(gv)
    if page is None:
        return None, None
    doc = page.Document
    # gv.items(pos) holds the view's own item too (its group): QGraphicsItem.parentItem() is not used, as in
    # PySide 6.8 it hands the parent's wrapper to Python, which then deletes TechDraw's view item when the
    # wrapper goes (a view drag ended FreeCAD: "pure virtual method called", PC handcheck-viewalign-b 11-13)
    for it in gv.items(pos):
        try:
            name = it.data(1)
        except Exception:
            name = None
        if name:
            o = doc.getObject(str(name))
            if o is not None and o.isDerivedFrom("TechDraw::DrawView") and o.TypeId not in SKIP and \
                    not o.isDerivedFrom("TechDraw::DrawViewDimension") and \
                    not o.isDerivedFrom("TechDraw::DrawViewBalloon") and \
                    not o.isDerivedFrom("TechDraw::DrawViewAnnotation") and \
                    not o.isDerivedFrom("TechDraw::DrawLeaderLine") and \
                    not o.isDerivedFrom("TechDraw::DrawRichAnno"):
                return it, o
    return None, None


def drag_target(o):
    ""

    for g in o.InList:
        if g.TypeId == "TechDraw::DrawProjGroup":
            kind = str(getattr(o, "Type", ""))
            if kind == "Front":
                return g, None
            if kind in ("Left", "Right", "Rear"):
                return o, "x"
            if kind in ("Top", "Bottom"):
                return o, "y"
            return o, None
    return o, None


def _item_of(it, name):
    """The sheet item of view name, in it's scene (found by name: no parentItem(), see view_item_at)."""
    try:
        if it.data(1) == name:
            return it
        sc = it.scene()
    except Exception:
        return None
    for x in (sc.items() if sc is not None else []):
        try:
            if x.data(1) == name:
                return x
        except Exception as _fw_err:
            _fw_log("drawkeys.py:655", _fw_err)
    return None


class ViewDrag:
    ""





    THRESHOLD = 4                # pixels before a press becomes a drag (a click still picks)

    def __init__(self):
        self.state = None
        self.drop = QtCore.QTimer()
        self.drop.setSingleShot(True)
        self.drop.timeout.connect(self.end)

    def item(self):
        st = self.state
        if not st or not st["name"]:
            return None
        try:
            for it in st["gv"].scene().items():
                if it.data(1) == st["name"]:
                    return it
        except Exception as _fw_err:
            _fw_log("drawkeys.py:683", _fw_err)
        return None

    def handle(self, obj, event):
        try:
            t = event.type()
            if t == QtCore.QEvent.MouseButtonPress:
                self.end(commit=False)
                if event.button() == Qt.LeftButton and event.modifiers() == Qt.NoModifier and not D.busy():
                    self.press(obj, event)
                return False
            st = self.state
            if st is None:
                return False
            if t == QtCore.QEvent.MouseMove:
                if not (event.buttons() & Qt.LeftButton):
                    self.end(commit=False)
                    return False
                pt = event.position().toPoint()
                if st["mode"] is None:
                    if (pt - st["press"]).manhattanLength() < self.THRESHOLD:
                        return False
                    it = self.resolve()
                    if it is None:
                        self.state = None
                        return False
                    if not show_contents_while_dragging():
                        self.hide_contents(it)
                if st["mode"] == "ours":
                    self.follow(event.globalPosition().toPoint())
                    return True
                return False
            if t == QtCore.QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                if st["mode"] is None:
                    self.state = None           # a click: nothing moved
                else:
                    self.drop.start(0)          # after TechDraw has had the release
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: view drag: %s\n" % error)
            self.state = None
        return False

    def press(self, viewport, event):
        """Only the press is noted here: no sheet item is touched before TechDraw has had the press (doing so
        lost the pick of a view clicked inside its frame)."""
        gv = viewport.parent()
        if not isinstance(gv, QtWidgets.QGraphicsView):
            return
        pos = event.position().toPoint()
        self.state = {"gv": gv, "name": None, "start": None, "press": pos, "gpress": event.globalPosition().toPoint(),
                      "obj": None, "axis": None, "mode": None, "hidden": None, "delta": QtCore.QPointF(0, 0)}

    def resolve(self):
        """At the start of a drag: the view pressed on, what the drag moves, and whether TechDraw already moves
        it (a press on its frame) or the add-on does (a press on its lines or faces)."""
        st = self.state
        if on_annotation_text(st["gv"], st["press"]):
            return None          # a dimension's or balloon's text: TechDraw drags it (its items are not touched)
        it, o = view_item_at(st["gv"], st["press"])
        if it is None:
            return None
        target, axis = drag_target(o)
        if getattr(target, "LockPosition", False) or getattr(o, "LockPosition", False):
            return None
        tit = _item_of(it, target.Name) or it
        st.update(name=str(tit.data(1)), obj=target, axis=axis)
        top = target.TypeId == "TechDraw::DrawProjGroup" or \
            not any(g.TypeId == "TechDraw::DrawProjGroup" for g in target.InList)
        if top:                             # its item sits on the sheet (not inside a projection group's)
            home = QtCore.QPointF(float(target.X) * D.REZ, -float(target.Y) * D.REZ)
            moved = (tit.pos() - home).manhattanLength() > 0.5
        else:
            moved = False
        st["start"] = QtCore.QPointF(tit.pos()) if not moved else \
            QtCore.QPointF(float(target.X) * D.REZ, -float(target.Y) * D.REZ)
        st["mode"] = "native" if moved else "ours"
        return tit

    def follow(self, gpt):
        st = self.state
        # the pointer's own travel on the screen (a sheet window that shifts under it, e.g. as the Drawing View
        # PM opens beside it, does not throw the view off)
        gv = st["gv"]
        tr = gv.transform()
        sx, sy = tr.m11() or 1.0, tr.m22() or 1.0
        px = gpt - st["gpress"]
        d = QtCore.QPointF(px.x() / sx, px.y() / sy)
        if st["axis"] == "x":
            d.setY(0)
        elif st["axis"] == "y":
            d.setX(0)
        st["delta"] = d
        it = self.item()
        if it is None:
            return
        h, v = gv.horizontalScrollBar().value(), gv.verticalScrollBar().value()
        it.setPos(st["start"] + d)
        gv.horizontalScrollBar().setValue(h)       # the sheet stays still under the pointer (the scene grows
        gv.verticalScrollBar().setValue(v)         # as the view nears its edge)
        if st["hidden"] is not None:
            # TechDraw draws the view again as it moves (new, visible items): only the frame stays shown
            for c in it.childItems():
                if c.data(0) != "SWDragFrame" and c.isVisible():
                    c.setVisible(False)

    def hide_contents(self, it):
        st = self.state
        rect = it.childrenBoundingRect()
        st["hidden"] = []
        for c in it.childItems():
            st["hidden"].append(c.isVisible())
            c.setVisible(False)
        frame = QtWidgets.QGraphicsRectItem(rect, it)
        pen = QtGui.QPen(QtGui.QColor(90, 90, 90))
        pen.setStyle(Qt.DashLine)
        pen.setCosmetic(True)
        frame.setPen(pen)
        frame.setData(0, "SWDragFrame")

    def end(self, commit=True):
        st = self.state
        if not st:
            return
        it = self.item()
        self.state = None
        if it is not None and st["hidden"] is not None:
            kids = [c for c in it.childItems() if c.data(0) != "SWDragFrame"]
            for c in it.childItems():
                if c.data(0) == "SWDragFrame" and c.scene() is not None:
                    c.scene().removeItem(c)
            if len(kids) == len(st["hidden"]):
                for c, visible in zip(kids, st["hidden"]):
                    c.setVisible(visible)
            else:
                for c in kids:
                    c.setVisible(True)
        if st["mode"] == "ours":
            d = st["delta"]
            dx, dy = d.x() / D.REZ, -d.y() / D.REZ
            if commit and (abs(dx) > 1e-6 or abs(dy) > 1e-6):
                # where the item was put, not X + the drag: TechDraw itself writes X/Y from a moved item on the
                # release, and adding the drag on top of that landed the view twice as far (dragview off/on)
                at = st["start"] + d
                self.commit(st["obj"], dx, dy, (at.x() / D.REZ, -at.y() / D.REZ))
            elif it is not None:
                it.setPos(st["start"])

    @staticmethod
    def commit(o, dx, dy, at=None):
        doc = o.Document
        doc.openTransaction("Move")
        try:
            for g in o.InList:
                if g.TypeId == "TechDraw::DrawProjGroup" and getattr(g, "AutoDistribute", False):
                    g.AutoDistribute = False        # a projected view placed by hand stays where it is dropped
            if at is not None:
                o.X, o.Y = at
            else:
                o.X = float(o.X) + dx
                o.Y = float(o.Y) + dy
        finally:
            doc.commitTransaction()
        doc.recompute()


_FILTER = []
_DRAG = []


def _drag():
    if not _DRAG:
        _DRAG.append(ViewDrag())
    return _DRAG[0]


def hook(gv=None):
    """One application filter: keys reach whichever widget of the sheet window has the keyboard, and the
    mouse on any sheet (pan, dragging a view)."""
    if not _FILTER:
        _FILTER.append(SheetKeys())
        E = QtCore.QEvent
        try:
            from . import events            # the add-on's one application filter
            events.register("draw.keys", (E.Wheel, E.MouseButtonPress, E.MouseMove, E.MouseButtonRelease,
                                          E.ShortcutOverride, E.KeyPress), _FILTER[0].eventFilter)
        except ImportError:
            QtWidgets.QApplication.instance().installEventFilter(_FILTER[0])


def register():
    hook()
    for name in COMMANDS:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Command(name))
