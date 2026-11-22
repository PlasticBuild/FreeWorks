# SPDX-License-Identifier: LGPL-2.1-or-later
""










_FW_SEEN = set()



def _alive(obj):
    """False for None or an object deleted under its wrapper (teardown.alive, review 1119)."""
    from . import teardown
    return teardown.alive(obj)


def _doc_alive(doc):
    from . import teardown
    return teardown.doc_alive(doc)


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return

import FreeCAD as App

TYPE = "SWStyle::TreeFolder"
BODY = "PartDesign::Body"


class TreeFolder:
    Type = TYPE

    def __init__(self, obj):
        obj.Proxy = self
        self._props(obj)

    @staticmethod
    def _props(obj):
        if "Items" not in obj.PropertiesList:
            obj.addProperty("App::PropertyStringList", "Items", "Folder",
                            "Names of the features in this folder, in tree order")
        if "Before" not in obj.PropertiesList:
            obj.addProperty("App::PropertyString", "Before", "Folder",
                            "While the folder is empty: the feature it sits above")

    def onDocumentRestored(self, obj):
        self._props(obj)
        watch()

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_folder(obj):
    try:
        return getattr(getattr(obj, "Proxy", None), "Type", None) == TYPE
    except Exception:
        return False


def folders(doc):
    return [o for o in doc.Objects if is_folder(o)] if doc is not None else []


def items(folder):
    """The folder's features that still exist."""
    doc = folder.Document
    return [o for o in (doc.getObject(n) for n in folder.Items) if o is not None]


def folder_of(obj):
    if obj is None:
        return None
    for folder in folders(obj.Document):
        if obj.Name in folder.Items:
            return folder
    return None


def _tree_order(body):
    """The body's rows as the tree lists them: a sketch a feature uses sits under that feature."""
    claimed = set()
    for o in body.Group:
        try:
            claimed.update(c.Name for c in o.ViewObject.claimChildren())
        except Exception as _fw_err:
            _fw_log("treefolders.py:92", _fw_err)
    return [o for o in body.Group if getattr(o, "TypeId", "") != "App::Origin" and o.Name not in claimed]


def _body_of(obj):
    if not _alive(obj):
        return None
    try:
        for parent in obj.InList:
            if parent.TypeId == BODY and obj in parent.Group:
                return parent
    except Exception as _fw_err:
        _fw_log("treefolders.py:102", _fw_err)
    return None


def _next_name(doc):
    labels = {o.Label for o in doc.Objects}
    n = 1
    while "Folder%d" % n in labels:
        n += 1
    return "Folder%d" % n


def can_group(objs):
    ""

    objs = [o for o in objs if o is not None]
    if not objs:
        return False
    bodies = {_body_of(o) for o in objs}
    if len(bodies) != 1 or None in bodies:
        return False
    if any(folder_of(o) is not None for o in objs):
        return False
    order = [o.Name for o in _tree_order(bodies.pop())]
    at = sorted(order.index(o.Name) for o in objs if o.Name in order)
    return len(at) == len(objs) and at == list(range(at[0], at[0] + len(at)))


class _NewAtBar:
    ""


    def slotCreatedObject(self, obj):
        try:
            doc = obj.Document
            if not folders(doc) or is_folder(obj):
                return
            from PySide import QtCore
            QtCore.QTimer.singleShot(0, lambda d=doc.Name, n=obj.Name: _adopt(d, n))
        except Exception as error:
            App.Console.PrintLog("FreeCAD folders: %s\n" % error)


def _adopt(doc_name, name):
    try:
        doc = App.getDocument(doc_name)
        obj = doc.getObject(name)
        body = _body_of(obj) if obj is not None else None
        if body is None or folder_of(obj) is not None:
            return
        rows = _tree_order(body)
        names = [o.Name for o in rows]
        if obj.Name not in names:
            return              # a sketch the new feature took under it: it goes with the feature
        k = names.index(obj.Name)
        if k == 0 or k == len(names) - 1:
            return
        above, below = folder_of(rows[k - 1]), folder_of(rows[k + 1])
        if above is None or above is not below:
            return
        listed = list(above.Items)
        at = listed.index(rows[k - 1].Name) + 1 if rows[k - 1].Name in listed else len(listed)
        listed.insert(at, obj.Name)
        above.Items = listed
    except Exception as error:
        App.Console.PrintLog("FreeCAD folders: %s\n" % error)


_WATCH = []


def watch():
    if not _WATCH:
        _WATCH.append(_NewAtBar())
        App.addDocumentObserver(_WATCH[0])


def _make(doc, label):
    watch()
    folder = doc.addObject("App::DocumentObjectGroupPython", "TreeFolder")
    TreeFolder(folder)
    folder.Label = label
    return folder


def add_to_new_folder(objs):
    ""
    if not can_group(objs):
        return None
    body = _body_of(objs[0])
    order = [o.Name for o in _tree_order(body)]
    names = sorted((o.Name for o in objs), key=order.index)
    doc = objs[0].Document
    doc.openTransaction("Add to New Folder")
    try:
        folder = _make(doc, _next_name(doc))
        folder.Items = names
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    return folder


def create_new_folder(obj):
    ""
    if obj is None or _body_of(obj) is None:
        return None
    doc = obj.Document
    doc.openTransaction("Create New Folder")
    try:
        folder = _make(doc, _next_name(doc))
        folder.Before = obj.Name
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    return folder


def delete(folder):
    """Delete a folder; its features stay in the tree."""
    doc = folder.Document
    doc.openTransaction("Delete Folder")
    try:
        doc.removeObject(folder.Name)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    return True


def regroup(parent, node_of_folder):
    """fmtree: put each folder's feature rows under the folder's row, where its first feature is
    (or, empty, above its Before feature). parent's children are rearranged in place.
    node_of_folder(folder) makes the folder's row (not yet added anywhere). Returns the folders
    placed."""
    kids = list(parent.children)
    names = {}
    for node in kids:
        obj = getattr(node, "obj", None)
        if obj is not None and not getattr(node, "link", False):
            names[obj.Name] = node
    doc = None
    for node in kids:
        if getattr(node, "obj", None) is not None:
            doc = node.obj.Document
            break
    if doc is None:
        return []
    member = {}
    empty_before = {}
    for folder in folders(doc):
        inside = [n for n in folder.Items if n in names]
        if inside:
            for n in inside:
                member[n] = folder
        elif folder.Before in names:
            empty_before.setdefault(folder.Before, []).append(folder)
    if not member and not empty_before:
        return []
    out, made = [], {}
    for node in kids:
        obj = getattr(node, "obj", None)
        name = obj.Name if obj is not None and not getattr(node, "link", False) else None
        for folder in empty_before.get(name, ()):
            row = node_of_folder(folder)
            made[folder.Name] = row
            out.append(row)
        folder = member.get(name)
        if folder is None:
            out.append(node)
            continue
        row = made.get(folder.Name)
        if row is None:
            row = made[folder.Name] = node_of_folder(folder)
            out.append(row)
        row.add(node)
    parent.children = []
    for node in out:
        parent.add(node)
    return [doc.getObject(n) for n in made]


# ---- drag and drop (fmtree) -------------------------------------------------------------------

def _rows(obj):
    """(tree order names of obj's body, obj's body) or ([], None)."""
    body = _body_of(obj)
    return ([o.Name for o in _tree_order(body)] if body is not None else []), body


def can_move_into(folder, objs):
    """A dragged feature goes into a folder when it sits right next to the folder's features (or,
    empty, right where the folder is); the model's order does not change."""
    objs = [o for o in objs if o is not None]
    if not objs or not is_folder(folder) or any(o.Name in folder.Items for o in objs):
        return False
    if any(folder_of(o) is not None for o in objs):
        return False
    order, body = _rows(objs[0])
    if body is None or any(_body_of(o) is not body for o in objs):
        return False
    inside = [n for n in folder.Items if n in order]
    if inside:
        names = set(inside) | {o.Name for o in objs}
    elif folder.Before in order:
        names = {o.Name for o in objs}
        # the empty folder sits above Before: the feature must be Before or the one above it
        at = order.index(folder.Before)
        if not names <= set(order[max(0, at - 1):at + len(names)]):
            return False
    else:
        return False
    at = sorted(order.index(n) for n in names if n in order)
    return len(at) == len(names) and at == list(range(at[0], at[0] + len(at)))


def move_into(folder, objs):
    if not can_move_into(folder, objs):
        return False
    order, _body = _rows(objs[0])
    doc = folder.Document
    names = sorted(set(folder.Items) | {o.Name for o in objs}, key=lambda n: order.index(n) if n in order else -1)
    doc.openTransaction("Move to Folder")
    try:
        folder.Items = names
        folder.Before = ""
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    return True


def can_move_out(objs):
    """Features leave their folder from its top or bottom end (the order stays as it is)."""
    objs = [o for o in objs if o is not None]
    if not objs:
        return False
    folder = folder_of(objs[0])
    if folder is None or any(folder_of(o) is not folder for o in objs):
        return False
    order, _body = _rows(objs[0])
    inside = [n for n in sorted(folder.Items, key=lambda n: order.index(n) if n in order else -1) if n in order]
    names = {o.Name for o in objs}
    k = len(names)
    return set(inside[:k]) == names or set(inside[-k:]) == names


def move_out(objs):
    if not can_move_out(objs):
        return False
    folder = folder_of(objs[0])
    order, _body = _rows(objs[0])
    names = {o.Name for o in objs}
    rest = [n for n in folder.Items if n not in names]
    doc = folder.Document
    doc.openTransaction("Move out of Folder")
    try:
        if not rest:
            # an emptied folder stays where it was: above the first feature that left it
            first = min(names, key=lambda n: order.index(n) if n in order else len(order))
            folder.Before = first
        folder.Items = rest
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    return True
