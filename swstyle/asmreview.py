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
import xml.etree.ElementTree as ET
import zipfile

import FreeCAD as App

try:
    import FreeCADGui as Gui
except Exception:   # pragma: no cover
    Gui = None

SAVED = {}           # review document name: {"path": assembly file, "plan": [...]}


# ---------------------------------------------------------------- reading the files
def _objects(path):
    """{name: (type, {property: element})} of a .FCStd, read from its Document.xml."""
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("Document.xml"))
    types = {}
    for o in root.iter("Object"):
        if o.get("type") and o.get("name"):
            types[o.get("name")] = o.get("type")
    out = {}
    data = root.find("ObjectData")
    for o in (data if data is not None else []):
        props = {}
        holder = o.find("Properties")
        for p in (holder if holder is not None else []):
            if p.tag == "Property" and p.get("name"):
                props[p.get("name")] = p
        out[o.get("name")] = (types.get(o.get("name"), ""), props)
    return out


def _placement(prop):
    pp = prop.find("PropertyPlacement") if prop is not None else None
    if pp is None:
        return App.Placement()
    f = lambda k: float(pp.get(k, "0"))
    return App.Placement(App.Vector(f("Px"), f("Py"), f("Pz")), App.Rotation(f("Q0"), f("Q1"), f("Q2"), f("Q3")))


def _string(prop, default=""):
    s = prop.find("String") if prop is not None else None
    return s.get("value", default) if s is not None else default


def _bool(prop, default=True):
    b = prop.find("Bool") if prop is not None else None
    return (b.get("value") == "true") if b is not None else default


def _links(prop):
    ll = prop.find("LinkList") if prop is not None else None
    return [l.get("value") for l in ll.findall("Link")] if ll is not None else []


def _xlink(prop):
    x = prop.find("XLink") if prop is not None else None
    if x is None:
        return None
    return x.get("file", ""), x.get("name", "")


class _Unfit(Exception):
    pass


def _walk(path, place, top, depth, out, seen):
    if depth > 12 or path in seen:
        raise _Unfit("nesting")
    objs = _objects(path)
    asm = next((n for n, (t, _) in objs.items() if t == "Assembly::AssemblyObject"), None)
    if asm is None:
        raise _Unfit("no assembly in %s" % path)
    folder = os.path.dirname(path)
    for name in _links(objs[asm][1].get("Group")):
        typ, props = objs.get(name, ("", {}))
        if typ not in ("App::Link", "Assembly::AssemblyLink"):
            continue
        xl = _xlink(props.get("LinkedObject"))
        if not xl or not xl[0]:
            raise _Unfit("%s links inside the file" % name)
        count = props.get("ElementCount")
        if count is not None and count.find("Integer") is not None and int(count.find("Integer").get("value", "0")) > 0:
            raise _Unfit("%s is a link array" % name)
        file = os.path.normpath(os.path.join(folder, xl[0]))
        if not os.path.isfile(file):
            raise _Unfit("%s missing" % file)
        at = place.multiply(_placement(props.get("Placement")))
        entry = {"name": name, "label": _string(props.get("Label"), name), "file": file, "placement": at,
                 "visible": _bool(props.get("Visibility")), "top": top or name, "depth": depth, "children": []}
        if typ == "Assembly::AssemblyLink":
            entry["children"] = []
            _walk(file, at, top or name, depth + 1, entry["children"], seen | {path})
        else:
            from . import tessave, asmtesscache
            if not tessave.has(file) and not asmtesscache.has(file):
                raise _Unfit("%s has no saved tessellation" % file)
        out.append(entry)


def plan(path):
    """The components of an assembly file, read without opening anything: a list of
    {name, label, file, placement (global), visible, top, children}, or None when it cannot be shown
    from saved graphics."""
    try:
        out = []
        _walk(os.path.normpath(path), App.Placement(), None, 0, out, frozenset())
        return out
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Large Design Review loads the parts: %s\n" % error)
        return None


def count(items):
    return len(items)


# ---------------------------------------------------------------- the review window
def _is_open(path):
    path = os.path.normcase(os.path.normpath(path))
    for doc in App.listDocuments().values():
        if doc.FileName and os.path.normcase(os.path.normpath(doc.FileName)) == path:
            return doc
    return None


def _mesh(file, cache):
    if file not in cache:
        from . import tessave, asmtesscache
        items = tessave.read(file) or asmtesscache.read(file)     # in the file, else the cache
        import Mesh
        facets = []
        for m in items:
            p = m["points"]
            facets += [(p[a], p[b], p[c]) for a, b, c in m["triangles"]]
        cache[file] = (Mesh.Mesh(facets), tuple(items[0]["color"][:3]) if items else (0.8, 0.8, 0.8))
    mesh, color = cache[file]
    return mesh.copy(), color


def _tag(obj, entry):
    for prop, value in (("FwComponent", entry["top"]), ("FwFile", entry["file"])):
        if prop not in obj.PropertiesList:
            obj.addProperty("App::PropertyString", prop, "FreeCAD", "", 4)
        setattr(obj, prop, value)


def _add(doc, entry, parent, cache):
    if entry["children"]:
        obj = doc.addObject("App::DocumentObjectGroup", entry["name"])
        for child in entry["children"]:
            _add(doc, child, obj, cache)
    else:
        obj = doc.addObject("Mesh::Feature", entry["name"])
        mesh, color = _mesh(entry["file"], cache)
        obj.Mesh = mesh
        obj.Placement = entry["placement"]
        vo = getattr(obj, "ViewObject", None)
        if vo is not None:
            for prop in ("ShapeColor", "DiffuseColor"):
                try:
                    setattr(vo, prop, color)
                    break
                except Exception:
                    continue
    obj.Label = entry["label"]
    _tag(obj, entry)
    if parent is not None:
        parent.addObject(obj)
    if not entry["visible"]:
        obj.Visibility = False
        if getattr(obj, "ViewObject", None) is not None:
            obj.ViewObject.Visibility = False
    return obj


def open_review(path, items=None):
    """The review window of an assembly file from its parts' saved graphics, in Large Design Review.
    None when it cannot be (asmldr then loads the assembly)."""
    items = plan(path) if items is None else items
    if not items or _is_open(path):
        return None
    from . import asmldr
    base = os.path.splitext(os.path.basename(path))[0]

    # Large Design Review (FreeCAD leaves a temporary document out of the tree); never asks to be saved
    try:
        doc = App.newDocument(base, base, False, False)
    except TypeError:
        doc = App.newDocument(base)
        doc.Label = base
    _no_prompt()
    cache = {}
    for entry in items:
        _add(doc, entry, None, cache)
    doc.recompute()
    SAVED[doc.Name] = {"path": os.path.normpath(path), "plan": items}
    asmldr.enter(doc)
    asmldr.REVIEW[doc.Name]["saved_graphics"] = True
    unchanged(doc)
    if Gui is not None and App.GuiUp:
        try:
            Gui.getDocument(doc.Name).ActiveView.viewIsometric()
            Gui.SendMsgToActiveView("ViewFit")
        except Exception as _fw_err:
            _fw_log("asmreview.py:233", _fw_err)
    return doc


def unchanged(doc):
    """The review window holds nothing to save: shown unchanged (no * after its name)."""
    try:
        gdoc = Gui.getDocument(doc.Name) if Gui is not None and App.GuiUp else None
        if gdoc is not None and gdoc.Modified:
            gdoc.Modified = False
    except Exception as error:
        App.Console.PrintLog("FreeCAD: review window: %s\n" % error)


def _no_prompt():
    """Closing a review window never asks to save it (it is the saved graphics, not the assembly):
    the close prompt leaves review windows out of the changed documents."""
    try:
        from . import closeprompt
    except Exception:
        return
    if getattr(closeprompt, "_fw_review", False):
        return
    modified0 = closeprompt._modified

    def _modified(docs=None):
        return [d for d in modified0(docs) if not is_review(d)]
    _modified.__wrapped__ = modified0
    closeprompt._modified = _modified
    closeprompt._fw_review = True


def try_open(path, mode):
    """asmldr's open: the review window when the mode comes out Large Design Review and the parts have
    saved graphics, else None."""
    if not path.lower().endswith(".fcstd") or _is_open(path):
        return None
    from . import asmldr
    if mode not in ("Resolved", "Large Design Review"):
        return None
    if mode == "Resolved" and not asmldr.ldr_auto():
        return None
    items = plan(path)
    if not items or asmldr.mode_for(count(items), mode) != "Large Design Review":
        return None
    if any(_is_open(f) for f in _files(items)):
        return None         # its parts are open already: nothing to save by not loading them
    return open_review(path, items)


def _files(items):
    for e in items:
        yield e["file"]
        for f in _files(e.get("children") or ()):
            yield f


def is_review(doc):
    return doc is not None and doc.Name in SAVED


# ---------------------------------------------------------------- loading the real assembly
def resolve(doc, edit=True):
    """Close the review window and open the assembly itself; Edit Assembly on when edit, else still
    in review (for Selective Open)."""
    from . import asmldr
    info = SAVED.pop(doc.Name, None)
    if info is None:
        return None
    hidden = [o.Name for o in doc.Objects if getattr(o, "FwComponent", None) == o.Name
              and getattr(o, "ViewObject", None) is not None and not o.ViewObject.Visibility]
    snaps = []
    try:
        from . import asmsnap
        snaps = [(s.Label, s.Camera, list(s.Shown), list(s.Hidden)) for s in asmsnap.snapshots(doc)]
    except Exception as _fw_err:
        _fw_log("asmreview.py:272", _fw_err)
    App.closeDocument(doc.Name)
    real = App.openDocument(info["path"])
    asmldr.enter(real)
    if edit:
        asmldr.set_edit(real, True)
    for name in hidden:
        obj = real.getObject(name)
        if obj is not None and getattr(obj, "ViewObject", None) is not None:
            obj.ViewObject.Visibility = False
    asm = ac_assembly(real)
    if snaps and asm is not None:              # snapshots taken in review go into the assembly
        from . import asmsnap
        for label, camera, shown, hidden_ in snaps:
            asmsnap.add(asm, label, camera, shown, hidden_)
    return real


def ac_assembly(doc):
    from . import asmcore
    return asmcore.assembly_of(doc)


def components(doc):
    """The review window's top-level components (meshes and subassembly folders)."""
    return [o for o in doc.Objects if getattr(o, "FwComponent", None) == o.Name]


def _top(doc, obj):
    name = getattr(obj, "FwComponent", "")
    return doc.getObject(name) if name else None


def chosen(doc, which):
    """Selective Open's components in the review window: selected (any mesh of a component picks the
    top-level component) or visible."""
    tops = components(doc)
    if which == "Visible":
        return [o for o in tops if getattr(o, "ViewObject", None) is None or o.ViewObject.Visibility]
    picked = []
    if Gui is not None:
        for sel in Gui.Selection.getSelectionEx(doc.Name, 0):
            top = _top(doc, sel.Object)
            if top is not None and top not in picked:
                picked.append(top)
    return picked


def selective_open(doc, comps, include_mates=True):
    from . import asmldr
    names = [c.Name for c in comps]
    real = resolve(doc, edit=False)
    if real is None:
        return {}
    keep = [real.getObject(n) for n in names if real.getObject(n) is not None]
    return asmldr.selective_open(real, keep, include_mates)
