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

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

from . import contextbar, relationspm, sketchtoolpm

PROP = "FreeWorksPatterns"
_pending = None          # the record a page being opened for Edit takes its settings from


def records(sketch):
    try:
        return json.loads(getattr(sketch, PROP, "") or "[]")
    except Exception:
        return []


def _save(sketch, recs):
    if PROP not in sketch.PropertiesList:
        sketch.addProperty("App::PropertyString", PROP, "FreeCAD", "Sketch patterns, for Edit Pattern", 4)
        try:
            sketch.setEditorMode(PROP, 2)
        except Exception as _fw_err:
            _fw_log("patternedit.py:47", _fw_err)
    setattr(sketch, PROP, json.dumps(recs))


def _types(sketch, geos):
    return [sketch.Geometry[g].TypeId if 0 <= g < len(sketch.Geometry) else "" for g in geos]


def _ids(sketch, geos):
    """Saved geometry ids: they stay with an entity when earlier ones are deleted (indices shift)."""
    try:
        return [sketch.getGeometryId(g) for g in geos]
    except Exception as _fw_err:
        _fw_log("patternedit.py:_ids", _fw_err)
        return None


def _live(sketch, rec):
    """rec with seed/first/end/made read from the geometry ids it saved, or None when its
    geometry is gone. Records saved before ids were kept come back as they are."""
    if not rec.get("ids"):
        return rec
    where = {}
    for i in range(len(sketch.Geometry)):
        try:
            where[sketch.getGeometryId(i)] = i
        except Exception:
            pass
    seed = [where.get(g) for g in rec.get("seed_ids", [])]
    made = sorted(where[g] for g in rec["ids"] if g in where)
    if None in seed or not made:
        return None
    return dict(rec, seed=seed, made=made, first=made[0], end=made[-1] + 1, _saved=rec)


def remember(page):
    """Called by a pattern page's check: record what it made."""
    sk = page.sketch
    first, end = page._original[0], len(sk.Geometry)
    if end <= first or not page.entities:
        return
    state = {}
    for name in page.STATE:
        w = getattr(page, name)
        state[name] = w.isChecked() if isinstance(w, QtWidgets.QAbstractButton) else w.value()
    state["skip"] = [list(k) for k in getattr(page, "skip", [])]
    recs = records(sk)
    rec = {"kind": page.KIND, "seed": list(page.entities), "seed_types": _types(sk, page.entities),
           "first": first, "end": end, "state": state}
    ids, seed_ids = _ids(sk, range(first, end)), _ids(sk, page.entities)
    if ids and seed_ids:
        rec["ids"], rec["seed_ids"] = ids, seed_ids
    recs.append(rec)
    _save(sk, recs)


def find(sketch, geo, kind):
    """The record of kind that geo belongs to (an instance or the seed) and still matches."""
    for saved in reversed(records(sketch)):
        if saved.get("kind") != kind:
            continue
        rec = _live(sketch, saved)
        if rec is None:
            continue
        inside = geo in rec["made"] if "made" in rec else rec["first"] <= geo < rec["end"]
        if not (inside or geo in rec["seed"]):
            continue
        if rec["end"] > len(sketch.Geometry) or _types(sketch, rec["seed"]) != rec["seed_types"]:
            continue
        return rec
    return None


def remove(sketch, rec):
    """Deletes the pattern's geometry; the records above it shift down."""
    first, end = rec["first"], rec["end"]
    sketch.delGeometries(list(rec.get("made") or range(first, end)))
    n = end - first
    saved = rec.get("_saved", rec)
    out = []
    for r in records(sketch):
        if r == saved:
            continue
        if r.get("ids"):                 # ids do not shift
            out.append(r)
            continue
        if r["first"] >= end:
            r["first"] -= n
            r["end"] -= n
        r["seed"] = [g - n if g >= end else g for g in r["seed"]]
        out.append(r)
    _save(sketch, out)
    sketch.solve()


def apply_state(page, rec):
    """Fills a freshly built page from rec (call with the page's _filling on)."""
    for name, value in rec["state"].items():
        w = getattr(page, name, None)
        if name not in page.STATE or w is None:
            continue
        if isinstance(w, QtWidgets.QAbstractButton):
            w.setChecked(bool(value))
        else:
            w.setValue(value)
    if hasattr(page, "skip"):
        page.skip = [tuple(k) for k in rec["state"].get("skip", [])]
        if hasattr(page, "_fill_skip"):
            page._fill_skip()
    names = relationspm._entity_names(page.sketch.Geometry)
    page.entities = list(rec["seed"])
    page.list.clear()
    for g in page.entities:
        page.list.addItem(names[g])


class EditCommand:
    def __init__(self, kind, page_class, menu):
        self.kind, self.page_class, self.menu = kind, page_class, menu

    def GetResources(self):
        return {"Pixmap": self.page_class.PIXMAP, "MenuText": self.menu,
                "ToolTip": "Select an instance of a sketch pattern to change its settings",
                "CmdType": "ForEdit"}

    def IsActive(self):
        return contextbar.sketch_in_edit() is not None

    def Activated(self):
        global _pending
        sketch = contextbar.sketch_in_edit()
        if sketch is None:
            return
        rec = None
        for sub in relationspm.picked_subs(sketch):
            item = sketchtoolpm.item_of(sketch, sub)
            if item is not None and item.geo >= 0:
                rec = find(sketch, item.geo, self.kind)
                if rec is not None:
                    break
        if rec is None:

            try:
                Gui.getMainWindow().statusBar().showMessage(
                    "%s: select an instance of the pattern first." % self.menu.rstrip("."), 6000)
            except Exception as _fw_err:
                _fw_log("patternedit.py:154", _fw_err)
            App.Console.PrintMessage("%s: select an instance of the pattern first (%d remembered)\n"
                                     % (self.menu.rstrip("."), len(records(sketch))))
            return
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("patternedit.py:161", _fw_err)
        doc = sketch.Document
        doc.openTransaction(self.menu.rstrip("."))
        try:
            remove(sketch, rec)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        _pending = rec
        try:
            page = self.page_class(sketch)
        except Exception:
            doc.undo()                   # the old pattern back, then report
            raise
        finally:
            _pending = None
        page._edit_record = rec
        sketchtoolpm.open_page(page)


def restore(page):
    """The cross on an Edit page: the old pattern comes back as it was."""
    rec = getattr(page, "_edit_record", None)
    if rec is None:
        return
    page._edit_record = None
    try:
        page.remake(rec)
        sk = page.sketch
        recs = records(sk)
        first, end = page._original[0], len(sk.Geometry)
        rec = {k: v for k, v in rec.items() if k not in ("made", "_saved", "ids", "seed_ids")}
        rec.update(first=first, end=end)
        ids, seed_ids = _ids(sk, range(first, end)), _ids(sk, rec["seed"])
        if ids and seed_ids:
            rec["ids"], rec["seed_ids"] = ids, seed_ids
        recs.append(rec)
        _save(sk, recs)
        sketchtoolpm._refresh(sk)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: the old pattern could not be put back: %s\n" % error)
