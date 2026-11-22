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
import zipfile
import re

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import asmcore as ac

XR = "External References"
RO_OPEN = (XR, "Open referenced documents with read-only access", False)
RO_NO_PROMPT = (XR, "Don't prompt to save read-only referenced documents (discard changes)", False)
MULTI_CONTEXT = (XR, "Allow multiple contexts for parts when editing in assembly", False)
LOAD_REFS = (XR, "Load referenced documents", "Prompt")
MEMORY_ONLY = (XR, "Load documents in memory only", True)
SEARCH_REF = (XR, "Reference Documents specified in File Locations", True)
SEARCH_SUBS = (XR, "Include sub-folders", False)
SEARCH_NO_ACTIVE = (XR, "Exclude active folders and recent save locations", False)
DESIGN_TABLES = (XR, "Update out-of-date linked design tables to", "Prompt")
AUTO_NAMES = (XR, "Automatically generate names for referenced geometry", False)
REPLACE_NAMES = (XR, "Update component names when documents are replaced", True)
ALLOW_EXTERNAL = (XR, "Allow creation of references external to the model", True)
SHOW_X = (XR, 'Show "x" in feature tree for broken external references', True)
FORCE_VERSION = (XR, "Force referenced document to save to current major version", True)
EDIT_COLORS = ("Colors", "Use specified colors when editing parts in assemblies", True)
MISSING_ERRORS = ("Messages/Errors/Warnings", "Treat missing mate references as errors", False)
AUTO_DISMISS = ("Messages/Errors/Warnings", "Automatically dismiss reference and update messages after 10 seconds", True)
TB_LOCK = ("Hole Wizard/Toolbox", "Lock rotation of new concentric mates to Toolbox components", False)
TB_SEARCH = ("Hole Wizard/Toolbox", "Make this folder the default search location for Toolbox components", True)

EDIT_PART_COLOR = (0.0, 0.32, 0.86)
NON_EDIT_COLOR = (0.62, 0.62, 0.62)        # Assembly, Non-Edit Parts grey

READ_ONLY = set()       # names of documents opened read-only as references
BEFORE = {}             # document name -> the documents open before it was opened
# checks set this to a callable(text, buttons) -> answer instead of showing the box
answer_hook = None


def on(row):
    from . import optionspages
    page, text, default = row
    try:
        return optionspages.stored(page, text, default)
    except Exception as _fw_err:
        _fw_log("asmrefopts.py:96", _fw_err)
        return default


value = on


def message(text, title="FreeCAD", buttons=None, default=None):
    """A reference/update message; with Messages > Automatically dismiss... on it goes after 10 s
    with its default answer. buttons: [(text, answer)]; returns the answer."""
    buttons = buttons or [("OK", "ok")]
    default = default if default is not None else buttons[0][1]
    if answer_hook is not None:
        return answer_hook(text, buttons)
    box = QtWidgets.QMessageBox(Gui.getMainWindow())
    box.setObjectName("FW_ReferenceMessage")
    box.setWindowTitle(title)
    box.setText(text)
    by_button = {}
    for label, answer in buttons:
        b = box.addButton(label, QtWidgets.QMessageBox.AcceptRole)
        by_button[b] = answer
        if answer == default:
            box.setDefaultButton(b)
    if on(AUTO_DISMISS):
        QtCore.QTimer.singleShot(10000, box.close)
    box.exec()
    return by_button.get(box.clickedButton(), default)


# ----------------------------------------------------------------------------- referenced documents
def referenced_docs(asm_doc):
    """The documents an assembly's components come from (subassemblies' too)."""
    out = []
    asm = ac.assembly_of(asm_doc)
    if asm is None:
        return out

    def walk(a, depth=0):
        for c in ac.components(a):
            try:
                lo = c.getLinkedObject(True)
            except Exception:
                lo = None
            d = getattr(lo, "Document", None)
            if d is not None and d is not asm_doc and d not in out:
                out.append(d)
                sub = ac.assembly_of(d)
                if sub is not None and depth < 6:
                    walk(sub, depth + 1)
    walk(asm)
    return out


def is_read_only(doc):
    return doc is not None and doc.Name in READ_ONLY


def other_contexts(part_doc, asm):
    """Labels of the other assemblies part_doc holds in-context references to."""
    from . import asmextref
    out = []
    for b in asmextref.binders(part_doc):
        if getattr(b, "BindMode", "") == "Detached":
            continue
        try:
            for obj, _subs in b.Support or []:
                d = obj.Document
                if d is not asm.Document and d.Label not in out:
                    out.append(d.Label)
        except Exception as _fw_err:
            _fw_log("asmrefopts.py:165", _fw_err)
    return out


def context_files(part_doc):
    """{file name: assembly doc or None} the part's in-context references point at, read from its
    file (the assembly may not be open)."""
    out = {}
    try:
        with zipfile.ZipFile(part_doc.FileName) as z:
            xml = z.read("Document.xml").decode("utf-8", "replace")
    except Exception:
        return out
    for m in re.finditer(r'<XLink\w* file="([^"]+)"', xml):
        out.setdefault(m.group(1), None)
    return out


def after_restore(doc):
    """A document finished opening: the External References rows that act on opening."""
    if ac.assembly_of(doc) is not None:
        refs = referenced_docs(doc)
        relink_missing(doc)
        refs = referenced_docs(doc)
        if on(RO_OPEN):
            READ_ONLY.update(d.Name for d in refs)
        if not on(MEMORY_ONLY):
            for d in refs:
                _window(d)
        return
    _load_contexts(doc)


def _window(doc):
    try:
        g = Gui.getDocument(doc.Name)
        if g is not None and not g.mdiViewsOfType("Gui::View3DInventor"):
            g.createView("Gui::View3DInventor")
    except Exception as error:
        App.Console.PrintLog("FreeCAD: referenced document window: %s\n" % error)


def _load_contexts(part_doc):
    """Load referenced documents: a part with in-context references opened on its own; the
    documents its references point at are opened (All), left closed (None), asked about
    (Prompt), or opened only when newer than the part (Changed)."""
    from . import asmextref
    bs = [b for b in asmextref.binders(part_doc) if getattr(b, "BindMode", "") != "Detached"]
    if not bs or not part_doc.FileName:
        return
    for other in App.listDocuments().values():
        try:
            if other is not part_doc and ac.assembly_of(other) is not None and part_doc in other.getDependentDocuments():
                BEFORE.pop(part_doc.Name, None)
                return
        except Exception:   # when the part itself is opened
            pass
    opened_before = set(BEFORE.pop(part_doc.Name, ()) or ())
    here = os.path.dirname(part_doc.FileName)
    files = []
    for f in context_files(part_doc):
        path = f if os.path.isabs(f) else os.path.normpath(os.path.join(here, f))
        if path not in files:
            files.append(path)
    mode = on(LOAD_REFS)
    for path in files:
        loaded = next((d for d in App.listDocuments().values()
                       if d.FileName and os.path.normcase(os.path.normpath(d.FileName)) == os.path.normcase(path)), None)
        if loaded is not None and loaded.Name in opened_before:
            continue            # it was open already: nothing to load
        keep = True
        if mode == "None":
            keep = False
        elif mode == "Changed":
            try:
                keep = os.path.getmtime(path) > os.path.getmtime(part_doc.FileName)
            except Exception:
                keep = False
        elif mode == "Prompt":
            keep = message("%s has references to %s.\n\nOpen the referenced document?" % (
                part_doc.Label, os.path.basename(path)), "Load referenced documents",
                [("Yes", True), ("No", False)], default=False)
        if keep and loaded is None and os.path.exists(path):
            try:
                App.openDocument(path)
                App.setActiveDocument(part_doc.Name)
                Gui.setActiveDocument(part_doc.Name)
            except Exception as error:
                App.Console.PrintLog("FreeCAD: load referenced document: %s\n" % error)
        elif not keep and loaded is not None:
            QtCore.QTimer.singleShot(0, lambda n=loaded.Name, p=part_doc.Name: _close_quiet(n, p))


def _close_quiet(name, part_name=None):
    """A document loaded only as a reference a moment ago (nobody edited it) closes again."""
    d = App.listDocuments().get(name)
    if d is None:
        return
    for other in App.listDocuments().values():
        if other is d or other.Name == part_name:
            continue
        try:
            if d in other.getDependentDocuments():
                return      # another document (an assembly opened since) uses it: it stays
        except Exception as _fw_err:
            _fw_log("asmrefopts.py:263", _fw_err)
    try:
        App.closeDocument(name)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: close referenced document: %s\n" % error)
    try:
        from . import asmui
        asmui.refresh()
    except Exception as _fw_err:
        _fw_log("asmrefopts.py:272", _fw_err)


# ----------------------------------------------------------------------------- search
def search_folders(asm_doc):
    from . import optionspages
    out = []
    if on(TB_SEARCH):
        tb = optionspages._fw().GetString("ToolboxFolder", "")
        if tb:
            out.append(tb)
    if on(SEARCH_REF):
        try:
            out += optionspages.folders("Reference Documents")
        except Exception as _fw_err:
            _fw_log("asmrefopts.py:287", _fw_err)
    if not on(SEARCH_NO_ACTIVE) and asm_doc.FileName:
        out.append(os.path.dirname(asm_doc.FileName))
    seen = []
    for f in out:
        if f and os.path.isdir(f) and f not in seen:
            seen.append(f)
    return seen


def find_file(name, folders):
    subs = on(SEARCH_SUBS)
    for f in folders:
        p = os.path.join(f, name)
        if os.path.exists(p):
            return p
        if subs:
            for root, _dirs, files in os.walk(f):
                if name in files:
                    return os.path.join(root, name)
    return None


def missing_links(asm_doc):
    """[(link, file name, object name)] for components whose part file was not found."""
    try:
        broken = False
        for o in asm_doc.Objects:
            if o.TypeId in ("App::Link", "Assembly::AssemblyLink") and o.LinkedObject is None:
                broken = True
                break
        if not broken:
            return []       # every link has its object: no need to read the file (slow in a big assembly)
    except Exception as _fw_err:
        _fw_log("asmrefopts.py:321", _fw_err)
    try:
        with zipfile.ZipFile(asm_doc.FileName) as z:
            xml = z.read("Document.xml").decode("utf-8", "replace")
    except Exception:
        return []
    out = []
    base = os.path.dirname(asm_doc.FileName)
    for m in re.finditer(r'<Object name="([^"]+)"[^>]*>(.*?)</Object>', xml, re.S):
        block = m.group(0)
        x = re.search(r'<Property name="LinkedObject"[^>]*>\s*<XLink file="([^"]+)"[^>]*name="([^"]+)"', block)
        if not x:
            continue
        link = asm_doc.getObject(m.group(1))
        if link is None:
            continue
        try:
            ok = link.LinkedObject is not None
        except Exception:
            ok = False
        if not ok:
            stored = x.group(1)
            if os.path.isfile(stored if os.path.isabs(stored) else os.path.join(base, stored)):
                continue    # the file is where the link says: FreeCAD is still loading it (not missing)
            out.append((link, os.path.basename(stored), x.group(2)))
    return out


def relink_missing(asm_doc):
    """Search external references in: components whose files moved are found and relinked."""
    found = 0
    if not asm_doc.FileName:
        return 0
    todo = missing_links(asm_doc)
    if not todo:
        return 0
    folders = search_folders(asm_doc)
    for link, fname, objname in todo:
        path = find_file(fname, folders)
        if not path:
            continue
        try:
            d = next((x for x in App.listDocuments().values() if x.FileName and os.path.samefile(x.FileName, path)), None)
            if d is None:
                d = App.openDocument(path)
            obj = d.getObject(objname) if d is not None else None
            if obj is None:
                continue
            link.LinkedObject = obj
            found += 1
        except Exception as error:
            App.Console.PrintLog("FreeCAD: search external references: %s\n" % error)
    if found:
        asm_doc.recompute()
        App.Console.PrintMessage("FreeCAD: %d referenced document%s found in the search folders\n" % (found, "" if found == 1 else "s"))
    return found


# ----------------------------------------------------------------------------- saving
def program_version(path):
    try:
        with zipfile.ZipFile(path) as z:
            head = z.read("Document.xml")[:600].decode("utf-8", "replace")
        m = re.search(r'ProgramVersion="(\d+)\.(\d+)', head)
        return (int(m.group(1)), int(m.group(2))) if m else None
    except Exception:
        return None


def before_save(doc):
    """Force referenced document to save to current major version."""
    if not on(FORCE_VERSION) or ac.assembly_of(doc) is None:
        return []
    now = (int(App.Version()[0]), int(App.Version()[1]))
    saved = []
    for d in referenced_docs(doc):
        if not d.FileName or is_read_only(d):
            continue
        v = program_version(d.FileName)
        if v is not None and v < now:
            QtCore.QTimer.singleShot(0, lambda d=d: _save_quiet(d))
            saved.append(d.Name)
    return saved


def _save_quiet(d):
    try:
        d.save()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: save referenced document: %s\n" % error)


# ----------------------------------------------------------------------------- mates
def ref_name(asm, ref):
    ""
    try:
        obj, subs = ref[0], ref[1]
        sub = subs[0] if subs else ""
        names = [n for n in sub.split(".") if n]
        el = names[-1] if names else ""
        comp = None
        for n in names[:-1]:
            o = obj.Document.getObject(n)
            if o is not None and o.TypeId in ("App::Link", "Assembly::AssemblyLink"):
                comp = o
        kind = re.match(r"[A-Za-z]+", el)
        num = el[len(kind.group(0)):] if kind else ""
        label = (comp or obj).Label.replace("<", "-").replace(">", "")
        return "%s<%s>@%s" % (kind.group(0) if kind else el, num, label)
    except Exception:
        return ""


def name_refs(asm, joint):
    if not on(AUTO_NAMES) or joint is None:
        return
    names = [ref_name(asm, r) for r in (joint.Reference1, joint.Reference2) if r]
    if not hasattr(joint, "ReferenceNames"):
        joint.addProperty("App::PropertyStringList", "ReferenceNames", "FreeCAD", "Generated names of the mated geometry")
    joint.ReferenceNames = names


_MISSING = {}       # (document, joint) -> (change counts it was worked out at, answer)


def missing_reference(joint):
    """True when a mate's face, edge or vertex is gone. Kept until the assembly or a mated
    part's document changes (the tree asks it for every mate row on every refresh)."""
    try:
        from . import asmgen
        key = [asmgen.gen(joint.Document)]
        for r in (getattr(joint, "Reference1", None), getattr(joint, "Reference2", None)):
            target = r[0].getLinkedObject(True) if r and r[0] is not None else None
            key.append(asmgen.gen(target.Document) if target is not None else -2)
        key = tuple(key)
    except Exception:
        key = None
    if key is None or -1 in key:
        return _missing_reference(joint)
    tag = (joint.Document.Name, joint.Name)
    hit = _MISSING.get(tag)
    if hit is not None and hit[0] == key:
        return hit[1]
    value = _missing_reference(joint)
    _MISSING[tag] = (key, value)
    return value


def _missing_reference(joint):
    for r in (getattr(joint, "Reference1", None), getattr(joint, "Reference2", None)):
        if not r or r[0] is None:
            return True
        try:
            for sub in r[1] or [""]:
                if not sub:
                    continue
                got = r[0].getSubObject(sub)
                if got is None or (hasattr(got, "isNull") and got.isNull()):
                    return True
        except Exception:
            return True
    return False


MISSING_WARN = "#d8a400"
MISSING_ERROR = "#e03030"


def missing_colour():
    return MISSING_ERROR if on(MISSING_ERRORS) else MISSING_WARN


def customize(name):
    """Tools > Customize > Toolbars context-toolbar options (QuickMates, FlipAlignment,
    QuickConfigurations): on unless turned off."""
    try:
        from . import customizedlg
        return bool(customizedlg.option(name))
    except Exception:
        try:
            return App.ParamGet("User parameter:BaseApp/Preferences/Mod/SolidWorksStyle/Customize").GetBool(name, True)
        except Exception:
            return True


def toolbox_lock():
    return on(TB_LOCK)


# ----------------------------------------------------------------------------- edit colours
_EDIT = {}


def edit_colours(asm, comp, start=True):
    """Use specified colors when editing parts in assemblies."""
    if start:
        if not on(EDIT_COLORS):
            return
        for c in ac.components(asm):
            vo = getattr(c, "ViewObject", None)
            if vo is None or not hasattr(vo, "OverrideMaterial"):
                continue
            _EDIT[c.Name] = (c, vo.OverrideMaterial, vo.ShapeMaterial if hasattr(vo, "ShapeMaterial") else None)
            m = vo.ShapeMaterial if vo.OverrideMaterial else App.Material()
            m.DiffuseColor = EDIT_PART_COLOR if c is comp else NON_EDIT_COLOR      # see-through stays
            try:
                vo.ShapeMaterial = m
                vo.OverrideMaterial = True
            except Exception as _fw_err:
                _fw_log("asmrefopts.py:530", _fw_err)
        return
    for name, (c, override, mat) in list(_EDIT.items()):
        try:
            if mat is not None:
                c.ViewObject.ShapeMaterial = mat
            c.ViewObject.OverrideMaterial = override
        except Exception as _fw_err:
            _fw_log("asmrefopts.py:538", _fw_err)
    _EDIT.clear()


# ----------------------------------------------------------------------------- design tables
def _patch_design_tables():
    try:
        from . import dtoptions
    except Exception:
        return
    if getattr(dtoptions, "_fw_asm_patched", False):
        return
    original = dtoptions.reload_link

    def reload_link(sheet, force=False):
        if force or sheet is None:
            return original(sheet, force)
        try:
            opts = dtoptions.options(sheet)
            path = opts.get("link")
            changed = path and os.path.exists(path) and abs(os.path.getmtime(path) - float(opts.get("mtime") or 0)) >= 1e-6
        except Exception:
            changed = False
        if not changed:
            return False
        mode = on(DESIGN_TABLES)
        if mode == "Model" or (mode == "Prompt" and message(
                "The design table's linked file %s changed since it was read.\n\nUpdate the design table "
                "from the file?" % os.path.basename(path), "Update linked design table",
                [("File", "file"), ("Model", "model")], default="file") == "model"):
            dtoptions.set_options(sheet, mtime=str(os.path.getmtime(path)))      # the model wins
            return False
        return original(sheet, force)

    dtoptions.reload_link = reload_link
    dtoptions._fw_asm_patched = True


# ----------------------------------------------------------------------------- close prompt
def _patch_close_prompt():
    try:
        from . import closeprompt
    except Exception:
        return
    if getattr(closeprompt, "_fw_asm_patched", False):
        return
    ro, mod = closeprompt._read_only, closeprompt._modified

    def _read_only(doc):
        return is_read_only(doc) or ro(doc)

    def _modified(docs=None):
        out = mod(docs)
        if on(RO_NO_PROMPT):
            for d in [d for d in out if is_read_only(d)]:
                out.remove(d)
                try:
                    Gui.getDocument(d.Name).Modified = False
                except Exception as _fw_err:
                    _fw_log("asmrefopts.py:597", _fw_err)
        return out

    closeprompt._read_only, closeprompt._modified = _read_only, _modified
    closeprompt._fw_asm_patched = True


class _Watch:
    """FreeCAD 1.1 gives Python observers no restore signals: a document created with a file
    name, once the open returns (the next event loop turn), has been opened."""

    def slotCreatedDocument(self, doc):
        name = doc.Name
        try:
            BEFORE[name] = tuple(n for n in App.listDocuments().keys() if n != name)
        except Exception as _fw_err:
            _fw_log("asmrefopts.py:613", _fw_err)
        QtCore.QTimer.singleShot(0, lambda: _after(name))

    def slotStartSaveDocument(self, doc, path):
        if is_read_only(doc):
            App.Console.PrintWarning("FreeCAD: %s was opened read-only as a referenced document\n" % doc.Label)
        before_save(doc)

    def slotFinishSaveDocument(self, doc, path):
        try:
            from . import asmextref
            asmextref.note_contexts(doc)      # Save As: the parts' in-context references name the new file
        except Exception as _fw_err:
            _fw_log("asmrefopts.py:finish save", _fw_err)

    def slotDeletedDocument(self, doc):
        READ_ONLY.discard(doc.Name)
        BEFORE.pop(doc.Name, None)


LAST = []
FIRED = []


def _after(name):
    d = App.listDocuments().get(name)
    if d is not None and d.FileName:
        try:
            after_restore(d)
            LAST[:] = [name, "ok"]
        except Exception as error:
            LAST[:] = [name, repr(error)]
            App.Console.PrintLog("FreeCAD: external references options: %s\n" % error)


_WATCH = None


def install():
    global _WATCH
    if _WATCH is None:
        _WATCH = _Watch()
        App.addDocumentObserver(_WATCH)
    _patch_design_tables()
    _patch_close_prompt()
