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
import re
import zipfile

import FreeCAD as App

from . import asmcore as ac

_XLINK = re.compile(r'(<XLink(?:Sub)?\b[^>]*?\bfile=")([^"]*)(")')


def _comps_all(asm):
    out = []
    for c in ac.components(asm):
        out.append(c)
        if ac.is_subassembly(c):
            sub = getattr(c, "LinkedObject", None)
            if sub is not None and sub.TypeId == "Assembly::AssemblyObject":
                out += _comps_all(sub)
    return out


def _doc_of(comp):
    try:
        return comp.LinkedObject.Document
    except Exception:
        return None


def _is_toolbox_doc(doc):
    try:
        from . import toolbox
        return any(hasattr(o, toolbox.PROP) for o in doc.Objects)
    except Exception:
        return False


def left_out(docs, include_suppressed=True, include_toolbox=True):
    """The documents Pack and Go leaves out for those two check boxes."""
    from . import asmcomp
    out = set()
    if not docs:
        return out
    used, suppressed_only = {}, set()
    for d in docs:
        asm = ac.assembly_of(d)
        if asm is None:
            continue
        for c in _comps_all(asm):
            pd = _doc_of(c)
            if pd is None:
                continue
            sup = False
            try:
                sup = asmcomp.is_suppressed(c)
            except Exception as _fw_err:
                _fw_log("asmpackgo.py:78", _fw_err)
            used.setdefault(pd.Name, []).append(sup)
    for name, sups in used.items():
        if all(sups):
            suppressed_only.add(name)
    for d in docs[1:]:
        if not include_suppressed and d.Name in suppressed_only:
            out.add(d.Name)
        if not include_toolbox and _is_toolbox_doc(d):
            out.add(d.Name)
    return out


def relink(path, mapping):
    """The packed file at path: each XLink to an old file (absolute, from the source folder) points
    at its packed copy (relative to path's folder). mapping: {old absolute path: new absolute path};
    src_dir: the source document's folder (old relative links are read from there)."""
    old_dir = mapping.get("__src_dir__", os.path.dirname(path))
    new_dir = os.path.dirname(path)
    changed = []

    def fix(m):
        rel = m.group(2)
        if not rel:
            return m.group(0)
        old = os.path.normpath(rel if os.path.isabs(rel) else os.path.join(old_dir, rel))
        new = mapping.get(old)
        if new is None:
            return m.group(0)
        value = os.path.relpath(new, new_dir).replace("\\", "/")
        if value != rel:
            changed.append((rel, value))
        return m.group(1) + value + m.group(3)
    try:
        z = zipfile.ZipFile(path)
        names = z.namelist()
        data = {n: z.read(n) for n in names}
        infos = {n: z.getinfo(n) for n in names}
        z.close()
    except Exception:
        return []
    xml = data.get("Document.xml")
    if xml is None:
        return []
    text = _XLINK.sub(fix, xml.decode("utf-8"))
    if not changed:
        return []
    data["Document.xml"] = text.encode("utf-8")
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
        for n in names:
            out.writestr(infos[n], data[n])
    os.replace(tmp, path)
    return changed


def fix_saved_links(doc, path):
    """FreeCAD 1.1 writes a subassembly's link (Assembly::AssemblyLink.LinkedObject) with the relative
    path it had when it was set: saved into another folder (Save As, a new assembly's first Save from
    its holding file) the file points at "../../Sub.FCStd", which is not there, and opening it from
    elsewhere asks for the missing file. The saved file's links that do not resolve are pointed at the
    open document of that name. Returns the [(old, new)] paths changed."""
    if not path or not path.lower().endswith(".fcstd"):
        return []
    if not any(o.TypeId == "Assembly::AssemblyLink" for o in doc.Objects):
        return []
    here = os.path.dirname(os.path.abspath(path))
    by_name = {}
    for d in App.listDocuments().values():
        if d.FileName and d is not doc:
            by_name.setdefault(os.path.basename(d.FileName).lower(), []).append(os.path.abspath(d.FileName))
    mapping = {"__src_dir__": here}
    try:
        z = zipfile.ZipFile(path)
        xml = z.read("Document.xml").decode("utf-8")
        z.close()
    except Exception:
        return []
    for m in _XLINK.finditer(xml):
        rel = m.group(2)
        if not rel or os.path.isabs(rel):
            continue
        old = os.path.normpath(os.path.join(here, rel))
        if os.path.exists(old):
            continue
        hits = by_name.get(os.path.basename(rel).lower(), [])
        if len(hits) == 1:
            mapping[old] = os.path.normpath(hits[0])
    if len(mapping) == 1:
        return []
    return relink(path, mapping)


class _SaveWatch:
    def slotFinishSaveDocument(self, doc, path):
        try:
            changed = fix_saved_links(doc, path)
            if changed:
                App.Console.PrintLog("FreeCAD: %s: links set to their files: %s\n" % (doc.Label, changed))
        except Exception as error:
            _fw_log("asmpackgo.py:save links", error)


_SAVE_WATCH = []


def install():
    if not _SAVE_WATCH:
        _SAVE_WATCH.append(_SaveWatch())
        App.addDocumentObserver(_SAVE_WATCH[0])
    try:
        from . import filecmds
    except Exception:
        return
    cls = getattr(filecmds, "PackAndGoDialog", None)
    if cls is None or getattr(cls, "_fw_asm", False):
        return
    cls._fw_asm = True
    plan0, write0 = cls.plan, cls._write

    def plan(self):
        rows = plan0(self)
        inc = getattr(self, "include", {})
        sup = inc.get("suppressed").isChecked() if inc.get("suppressed") is not None else True
        tb = inc.get("toolbox").isChecked() if inc.get("toolbox") is not None else True
        drop = left_out(list(self.docs), sup, tb)
        return [r for r in rows if r[0] is None or r[0].Name not in drop]

    def _write(self, plan_rows, work):
        written = write0(self, plan_rows, work)
        mapping = {}
        for (d, src, _name, _folder), target in zip(plan_rows, written):
            if d is not None and src:
                mapping[os.path.normpath(src)] = os.path.normpath(target)
        for (d, src, _name, _folder), target in zip(plan_rows, written):
            if not target.lower().endswith(".fcstd"):
                continue                     # a drawing file packed unopened is relinked too
            m = dict(mapping)
            m["__src_dir__"] = os.path.dirname(src) if src else os.path.dirname(target)
            try:
                relink(target, m)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: Pack and Go references: %s\n" % error)
        return written

    cls.plan, cls._write = plan, _write
