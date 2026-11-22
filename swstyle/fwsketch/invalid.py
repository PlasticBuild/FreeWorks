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

try:
    from PySide import QtCore, QtWidgets
except ImportError:  # pragma: no cover
    from PySide6 import QtCore, QtWidgets

NAME_TEXT = "The characters '@', '+', '-' or '=' cannot be used in dimension's name."
VALUE_TEXT = ("Changing this value would result in invalid geometry. The previous sketch state "
              "has been restored.")
DRAG_TEXT = "This drag created invalid geometry. The pre-drag sketch state will be restored."
DRAG_STEP = "Drag Point"
START, END = 1, 2


def _box(icon, title, text, name, parent=None):
    """A box over the main window, not waiting (FreeCAD's dialogs go on behind it)."""
    box = QtWidgets.QMessageBox(icon, title, text, QtWidgets.QMessageBox.Ok,
                                parent or Gui.getMainWindow())
    box.setObjectName(name)
    box.setAttribute(QtCore.Qt.WA_DeleteOnClose)
    box.setWindowModality(QtCore.Qt.ApplicationModal)
    box.show()
    return box


# --- names and values ---------------------------------------------------------------------------
def bad_name(name):
    return any(c in name for c in "@+-=")


def name_box(parent=None):
    return _box(QtWidgets.QMessageBox.Warning, "Dimension Name", NAME_TEXT, "DimensionNameCharacters",
                parent)


def value_error(error):
    """True when setDatum failed because the solver found no shape (FreeCAD's wording)."""
    return "Invalid constraint index" in str(error)


def value_box(parent=None):
    return _box(QtWidgets.QMessageBox.Information, "Modify", VALUE_TEXT, "DatumInvalidGeometry", parent)


# --- drags --------------------------------------------------------------------------------------
def _other(pos):
    return END if pos == START else START


def degenerate(sketch, tiny):
    """Indices of lines with no length and circles/arcs with no radius."""
    out = set()
    for k, g in enumerate(sketch.Geometry):
        name = type(g).__name__
        try:
            if name == "LineSegment" and (g.EndPoint - g.StartPoint).Length < tiny:
                out.add(k)
            elif name in ("Circle", "ArcOfCircle") and g.Radius < tiny:
                out.add(k)
        except Exception as _fw_err:
            _fw_log("fwsketch/invalid.py:91", _fw_err)
    return out


def _tiny(session, px=None):
    return max(1e-7, px if px else getattr(session, "_fw_px", 0.0) or 0.0)


def drag_moved(session, global_point):
    """After each move of a point drag (dragwatch.DragSession.moved_to): the tooltip while the
    point sits on its own curve's other end."""
    if not session.dragged or session.pos is None:
        return
    sketch = session.sketch
    p, px = session.pointer()
    if p is None:
        return
    session._fw_px = px
    if not hasattr(session, "_fw_base"):
        session._fw_base = degenerate(sketch, _tiny(session, px))
    if session.pos not in (START, END):
        return
    try:
        end = sketch.getPoint(session.geo, _other(session.pos))
    except Exception:
        return
    on_own_end = (App.Vector(p[0], p[1], 0) - App.Vector(end.x, end.y, 0)).Length < _tiny(session, px)
    show_tip(session, on_own_end, global_point)


def show_tip(session, invalid, global_point):
    """The tooltip once per invalid spell (shown again on every move, Windows restarts its fade)."""
    was = getattr(session, "_fw_invalid", False)
    session._fw_invalid = invalid
    if invalid and not was:
        QtWidgets.QToolTip.showText(global_point + QtCore.QPoint(16, -36), DRAG_TEXT)
    elif was and not invalid:
        QtWidgets.QToolTip.hideText()


def drop_invalid(session):
    """After FreeCAD's drop: the drag left new invalid geometry, or a sketch the solver cannot
    solve (without a clash, which is the over-defined look's business)."""
    sketch = session.sketch
    if getattr(session, "_fw_invalid", False):
        return True
    base = getattr(session, "_fw_base", None)
    if base is not None and degenerate(sketch, _tiny(session)) - base:
        return True
    try:
        code = sketch.solve()
    except Exception:
        return False
    return code not in (0, -2, -3) and not list(sketch.ConflictingConstraints)


def restore(session):
    ""
    QtWidgets.QToolTip.hideText()
    session._fw_invalid = False
    sketch = session.sketch
    doc = sketch.Document
    names = list(doc.UndoNames)
    if names and names != session.names_before and names[0] in (
            DRAG_STEP, "Drag Curve", "Drag geometries",
            QtCore.QCoreApplication.translate("Command", DRAG_STEP)):
        doc.undo()
    sketch.solve()
    try:
        doc.recompute()
    except Exception as _fw_err:
        _fw_log("fwsketch/invalid.py:162", _fw_err)
    session.result = ("restored", True)
    return True
