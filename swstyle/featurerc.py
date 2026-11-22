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
import FreeCADGui as Gui
from PySide import QtWidgets

T_CONFIGURE = "Configure Feature"
T_UNSUPPRESS_DEP = "Unsuppress with Dependents"
T_INSERT_NEW_PART = "Insert into New Part..."
T_DELETE_KEEP = "Delete/Keep Body..."
T_CREATE_ASSEMBLY = "Create Assembly..."
DEFAULT_REFS = ("App::Plane", "App::Line", "App::Point", "App::Origin")
USER_REFS = ("PartDesign::Plane", "PartDesign::Line", "PartDesign::Point", "PartDesign::CoordinateSystem")


def is_reference(obj):
    t = getattr(obj, "TypeId", "")
    return t in DEFAULT_REFS or t in USER_REFS or t.endswith("CoordinateSystem")


def _suppressed(obj):
    return bool(getattr(obj, "Suppressed", False))


def _configure(obj):
    from . import partextras
    return partextras.configure_feature(obj)


def _unsuppress(obj, dependents):
    from . import suppress
    return suppress.unsuppress([obj], with_dependents=dependents)


def _delete(obj):
    from . import fmmenu
    return fmmenu.delete(obj)


def _select(objs):
    Gui.Selection.clearSelection()
    for o in objs:
        Gui.Selection.addSelection(o.Document.Name, o.Name)


def _body_op(kind, bodies):
    from . import multibody
    _select(bodies)
    return multibody.start_op(kind, bodies[0].Document if bodies else None, [])


def _isolate(body):
    from . import partmenu
    return partmenu.isolate(body)


def _create_assembly():
    from . import createassembly
    Gui.runCommand(createassembly.COMMAND, 0)


def insert_into_new_part(body, path=None, ask=True):
    """A new part with the body's shape, saved to path (asked when not given). The new doc."""
    src = body.Document
    if path is None and ask:
        start = os.path.join(os.path.dirname(src.FileName or "") or os.path.expanduser("~"), body.Label + ".FCStd")
        path = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Insert into New Part", start,
                                                     "FreeCAD part (*.FCStd)")[0]
        if not path:
            return None
    doc = App.newDocument(os.path.splitext(os.path.basename(path))[0] if path else body.Label)
    obj = doc.addObject("Part::Feature", body.Label)
    obj.Shape = body.Shape.copy()
    for prop, value in (("SourceFile", src.FileName or src.Name), ("SourceBody", body.Label)):
        obj.addProperty("App::PropertyString", prop, "Derived part", "Where this body came from")
        setattr(obj, prop, value)
    try:
        if App.GuiUp and body.ViewObject is not None:
            obj.ViewObject.ShapeColor = body.ViewObject.ShapeColor
    except Exception as _fw_err:
        _fw_log("featurerc.py:109", _fw_err)
    doc.recompute()
    if path:
        doc.saveAs(path)
    return doc


# --------------------------------------------------------------------------- the tree (fmmenu)
def _entry(key, label, run, ok=True):
    return (key, label, run, ok)


def _insert_after(out, after, new):
    keys = [e[0] for e in out]
    for a in after:
        if a in keys:
            at = keys.index(a) + 1
            return out[:at] + new + out[at:]
    return out + new


def tree(out, target, kind):
    """fmmenu.entries' list for target with the per-type entries added."""
    try:
        if _is_solid_row(target):
            return _solid_row_entries(out, target)
        keys = [e[0] for e in out]
        if kind in ("feature", "plane", "reference") and not isinstance(target, App.Document):
            t = getattr(target, "TypeId", "")
            add = []
            if "ConfigureFeature" not in keys and (kind == "feature" or t in USER_REFS):
                add.append(_entry("ConfigureFeature", T_CONFIGURE, lambda: _configure(target)))
            if kind == "feature" and getattr(target, "FwLibraryFeature", ""):
                from . import libfeature
                add += libfeature.rc_entries(target)
            if kind == "feature" and (getattr(target, "Comment", "") or "").strip():
                add.append(_entry("CommentStatus", "Comment Status...", lambda: comment_status(target)))
            if kind in ("plane", "reference") and t in USER_REFS and "Delete" not in keys:
                add.append(_entry("Delete", "Delete...", lambda: _delete(target)))
            out = _insert_after(out, ("ParentChild",), add)
        if kind == "feature" and _suppressed(target):
            # R9 read 52: nothing is greyed on a suppressed feature's row (Change Transparency stays live)
            out = _insert_after(out, ("Delete", "ParentChild"), [
                _entry("Unsuppress", "Unsuppress", lambda: _unsuppress(target, False)),
                _entry("UnsuppressDependents", T_UNSUPPRESS_DEP, lambda: _unsuppress(target, True))])
        if kind in ("body", "bodies"):
            if kind == "body":
                bodies = [target]
            else:
                from . import fmmenu
                bodies = fmmenu._solid_bodies(target.doc)
            out = _insert_after(out, ("HideBodies", "ParentChild"), _body_entries(bodies, folder=kind == "bodies"))
    except Exception as error:
        App.Console.PrintLog("FreeCAD: featurerc.tree: %s\n" % error)
    return out


def set_comment_status(obj, status):
    """The comment's status: Description, High Priority, Low Priority, Complete or Reminder (its
    colour in the tree comes from Document Properties > Model Display)."""
    if "CommentStatus" not in obj.PropertiesList:
        obj.addProperty("App::PropertyString", "CommentStatus", "Comment", "The comment's status")
    obj.CommentStatus = status
    try:
        from . import fmtree
        fmtree.refresh() if hasattr(fmtree, "refresh") else None
    except Exception as _fw_err:
        _fw_log("featurerc.py:176", _fw_err)
    return status


def comment_status(obj):
    from PySide import QtWidgets
    import FreeCADGui as Gui
    from . import fmtree
    items = list(fmtree.COMMENT_STATUSES)
    now = str(getattr(obj, "CommentStatus", "") or "Description")
    choice, ok = QtWidgets.QInputDialog.getItem(Gui.getMainWindow(), "Comment Status", "Status of the comment on %s:"
                                                % obj.Label, items, items.index(now) if now in items else 0, False)
    if ok:
        App.ActiveDocument.openTransaction("Comment Status")
        try:
            set_comment_status(obj, choice)
        except BaseException:
            try:
                App.ActiveDocument.abortTransaction()
            except Exception:
                pass
            raise
        App.ActiveDocument.commitTransaction()
    return choice if ok else None


def _is_solid_row(target):
    try:
        from . import multibody
        return getattr(getattr(target, "Proxy", None), "Type", None) == multibody.ROW_TYPE
    except Exception:
        return False


# A body in the Solid Bodies folder is not a feature: no Parent/Child, Configure Feature, Delete...
# (the row stands for the body; Body-Delete/Keep removes it), FeatureWorks or Save Selection.
_ROW_DROP = ("ParentChild", "ConfigureFeature", "Delete", "Favorites", "SaveSelection", "FeatureWorks",
             "CreateNewFolder")


def _solid_row_entries(out, row):
    ""
    from . import multibody
    doc = row.Document
    rows = [r for r in _picked_rows(doc) if r is not row] + [row]
    body_items = [
        _entry("DeleteKeepBody", T_DELETE_KEEP, lambda: multibody.start_op("DeleteKeep", doc, rows)),
        _entry("InsertIntoNewPart", T_INSERT_NEW_PART, lambda: _insert_rows(rows)),
        _entry("IsolateBody", "Isolate", lambda: multibody.isolate(doc, rows)),
        _entry("MoveCopyBody", "Move/Copy Body...", lambda: multibody.start_op("MoveCopy", doc, rows)),
        _entry("BodyAppearance", "Appearance...", lambda: multibody.pick_colour(row))]
    if multibody._ISOLATED.get(doc.Name) is not None:
        body_items[2] = _entry("ExitIsolate", "Exit Isolate", lambda: multibody.exit_isolate(doc))
    kept = [e for e in out if e[0] not in _ROW_DROP]
    return _insert_after(kept, ("AddToNewFolder", "Comment"), body_items)


def _insert_rows(rows):
    """Insert into New Part: a new part linked to this body (multibody / createassembly LinkedStock)."""
    from . import multibody
    return multibody.insert_rows_into_new_part(rows)


def _picked_rows(doc):
    try:
        from . import multibody
        return [s.Object for s in Gui.Selection.getSelectionEx(doc.Name)
                if getattr(getattr(s.Object, "Proxy", None), "Type", None) == multibody.ROW_TYPE]
    except Exception:
        return []


def _body_entries(bodies, folder=False):
    have = bool(bodies)
    # Insert into New Part takes solid bodies (the folder: each of them, as the picked rows do)
    solids = [b for b in bodies if _has_solid(b)]
    out = [_entry("DeleteKeepBody", T_DELETE_KEEP, lambda: _body_op("DeleteKeep", bodies), have),
           _entry("InsertIntoNewPart", T_INSERT_NEW_PART, lambda: [insert_into_new_part(b) for b in solids][-1:],
                  bool(solids) and (folder or len(solids) == 1)),
           _entry("IsolateBody", "Isolate", lambda: _isolate(bodies[0]), have)]
    if not folder:
        out += [_entry("MoveCopyBody", "Move/Copy Body...", lambda: _body_op("MoveCopy", bodies), have),
                _entry("BodyMaterial", "Material...", lambda: _body_material(bodies[0]), have),
                _entry("BodyProperties", "Body Properties...", lambda: _body_properties(bodies[0]), have)]
    else:
        out.append(_entry("CreateAssembly", T_CREATE_ASSEMBLY, _create_assembly, have))
    return out


def _has_solid(obj):
    try:
        return bool(obj.Shape.Solids)
    except Exception:
        return False


def _body_material(body):
    ""
    from . import massprops
    return massprops.edit_body_material(body)


def _body_properties(body):
    from . import fmmenu
    return fmmenu.feature_properties(body, "Body Properties")


# --------------------------------------------------------------------------- the graphics area (partmenu)
def reference_items(feature):
    ""
    from . import rcmenus, fmmenu
    rows = {}
    try:
        kind = fmmenu.kind_of(feature)
        for k, label, run, ok in tree(fmmenu.entries(rcmenus.shell(), feature), feature, kind):
            if k:
                rows[k] = (label, run, ok)
    except Exception as _fw_err:
        _fw_log("featurerc.py:278", _fw_err)
    out = [rcmenus.header("Feature (%s)" % feature.Label, "HeaderFeature")]
    for key in ("Comment", "ParentChild", "ConfigureFeature", "Delete", "Favorites", "SaveSelection", "Properties"):
        r = rows.get(key)
        if r is None:
            continue
        label, run, ok = r
        if hasattr(run, "fill"):
            out.append(rcmenus.dynamic(key, label, run.fill))
        else:
            out.append(rcmenus.action(key, label, run, enabled=ok))
    return out
