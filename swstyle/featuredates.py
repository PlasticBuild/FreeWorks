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

import datetime, getpass
import FreeCAD as App

PREFIX = "FwFeat:"
# outputs and view-only properties: changing them is not the user editing the feature
_QUIET = {"Shape", "AddSubShape", "SuppressedShape", "PreviewShape", "Placement", "Label2", "Visibility",
          "State", "Tip", "Group", "BaseFeature", "_Body", "ShapeMaterial", "ExpressionEngine",
          "SWStyleKind", "Content", "ColorMap"}
_STEP = datetime.timedelta(seconds=30)


def _now():
    return datetime.datetime.now().replace(microsecond=0)


def author():
    try:
        name = App.ParamGet("User parameter:BaseApp/Preferences/Document").GetString("prefAuthor", "")
    except Exception:
        name = ""
    if not name:
        try:
            name = getpass.getuser()
        except Exception:
            name = ""
    return name


def _feature(obj):
    t = getattr(obj, "TypeId", "")
    return t.startswith("PartDesign::") or t.startswith("Sketcher::") or t.startswith("Part::")


def _read(doc, name):
    try:
        raw = doc.Meta.get(PREFIX + name)
    except Exception:
        return None
    if not raw:
        return None
    parts = (raw.split("|") + ["", "", ""])[:3]
    return parts


def _write(doc, name, created, modified, who):
    try:
        meta = doc.Meta
        meta[PREFIX + name] = "%s|%s|%s" % (created, modified, who)
        doc.Meta = meta
    except Exception as error:
        App.Console.PrintLog("FreeCAD: feature date not kept: %r\n" % (error,))


def created(obj):
    now = _now().isoformat()
    _write(obj.Document, obj.Name, now, now, author())


def changed(obj, prop):
    if prop in _QUIET or not _feature(obj):
        return
    doc = obj.Document
    if getattr(doc, "Restoring", False) or getattr(doc, "Recomputing", False):
        return
    entry = _read(doc, obj.Name)
    if entry is None:
        return
    now = _now()
    try:
        last = datetime.datetime.fromisoformat(entry[1])
        if now - last < _STEP:
            return
    except Exception as _fw_err:
        _fw_log("featuredates.py:92", _fw_err)
    _write(doc, obj.Name, entry[0], now.isoformat(), entry[2])


def _show(iso):
    try:
        from PySide import QtCore
        dt = QtCore.QDateTime.fromString(iso, QtCore.Qt.ISODate)
        return QtCore.QLocale().toString(dt, QtCore.QLocale.ShortFormat)
    except Exception:
        return iso.replace("T", " ")


def info(obj):
    """(created by, date created, last modified) as shown in Feature Properties."""
    doc = obj.Document
    entry = _read(doc, obj.Name)
    if entry is None:
        return (getattr(doc, "CreatedBy", "") or "", getattr(doc, "CreationDate", "") or "",
                getattr(doc, "LastModifiedDate", "") or "")
    return entry[2], _show(entry[0]), _show(entry[1])


_GONE = {}      # (document, feature) -> its entry when it was deleted: Undo (or Redo) brings it back as it was


class _Watch:
    def slotCreatedObject(self, obj):
        try:
            doc = obj.Document
            if _feature(obj) and not getattr(doc, "Restoring", False):
                raw = _GONE.pop((doc.Name, obj.Name), None) if getattr(doc, "Transacting", False) else None
                if raw:
                    meta = doc.Meta
                    meta[PREFIX + obj.Name] = raw
                    doc.Meta = meta
                else:
                    created(obj)
        except Exception as _fw_err:
            _fw_log("featuredates.py:122", _fw_err)

    def slotChangedObject(self, obj, prop):
        try:
            changed(obj, prop)
        except Exception as _fw_err:
            _fw_log("featuredates.py:128", _fw_err)

    def slotDeletedObject(self, obj):
        try:
            doc = obj.Document
            meta = doc.Meta
            raw = meta.pop(PREFIX + obj.Name, None)
            if raw is not None:
                doc.Meta = meta
                if len(_GONE) > 500:
                    _GONE.clear()
                _GONE[(doc.Name, obj.Name)] = raw
        except Exception as _fw_err:
            _fw_log("featuredates.py:137", _fw_err)


_WATCH = []


def install():
    if _WATCH:
        return
    _WATCH.append(_Watch())
    App.addDocumentObserver(_WATCH[0])
