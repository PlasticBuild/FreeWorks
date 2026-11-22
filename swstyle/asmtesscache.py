# SPDX-License-Identifier: LGPL-2.1-or-later
""











import hashlib
import json
import os
import zipfile

import FreeCAD as App

SOURCE = "FreeWorks/source.json"
_observer = []


def folder():
    try:
        base = App.getUserCachePath()
    except Exception:
        base = os.path.join(App.getUserAppDataDir(), "cache")
    return os.path.join(base, "FreeWorks", "tessellation")


def _stat(path):
    try:
        st = os.stat(path)
        return [round(st.st_mtime, 3), st.st_size]
    except OSError:
        return None


def entry(path):
    key = hashlib.sha1(os.path.normcase(os.path.abspath(path)).encode("utf-8")).hexdigest()
    return os.path.join(folder(), key + ".fwtess")


def has(path):
    """A cached mesh that still matches the part file as it is now."""
    e = entry(path)
    if not os.path.isfile(e):
        return False
    try:
        with zipfile.ZipFile(e) as z:
            src = json.loads(z.read(SOURCE).decode("utf-8"))
    except Exception:
        return False
    return src.get("stat") == _stat(path)


def read(path):
    if not has(path):
        return []
    from . import tessave
    return tessave.read(entry(path))


def write(doc):
    """doc's display mesh into the cache, stamped with its file. True when written."""
    path = doc.FileName
    if not path or not os.path.isfile(path):
        return False
    from . import tessave
    items = tessave.meshes(doc)
    if not items:
        return False
    index, blob = tessave._pack(items)
    e = entry(path)
    tmp = e + ".tmp"
    try:
        os.makedirs(folder(), exist_ok=True)
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(tessave.INDEX, json.dumps(index))
            z.writestr(tessave.DATA, blob)
            z.writestr(SOURCE, json.dumps({"path": path, "stat": _stat(path)}))
        os.replace(tmp, e)
        return True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: display mesh cache: %s\n" % error)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception as again:
            App.Console.PrintLog("FreeCAD: display mesh cache: %s\n" % again)
        return False


def _is_part(doc):
    from . import asmcore
    return bool(doc.FileName) and doc.FileName.lower().endswith(".fcstd") and asmcore.assembly_of(doc) is None


def _needs(doc):
    from . import tessave
    return _is_part(doc) and not tessave.has(doc.FileName) and not has(doc.FileName)


def _parts_of(asm, seen):
    from . import asmcore
    out = []
    for comp in asmcore.components(asm):
        try:
            target = comp.LinkedObject
            d = target.Document if target is not None else None
        except Exception:
            d = None
        if d is None or d.Name in seen:
            continue
        seen.add(d.Name)
        sub = asmcore.assembly_of(d)
        if sub is not None and sub is not asm:
            out += _parts_of(sub, seen)
        else:
            out.append(d)
    return out


def fill(doc):
    """After an assembly is saved: a mesh for each part it uses without one. Returns the count."""
    from . import asmcore
    asm = asmcore.assembly_of(doc)
    if asm is None:
        return 0
    n = 0
    for d in _parts_of(asm, {doc.Name}):
        try:
            if _needs(d) and write(d):
                n += 1
        except Exception as error:
            App.Console.PrintLog("FreeCAD: display mesh cache %s: %s\n" % (d.Name, error))
    return n


class _Observer:
    def slotFinishSaveDocument(self, doc, filename):
        try:
            if _is_part(doc):
                from . import tessave
                if os.path.isfile(entry(doc.FileName)) and not tessave.has(doc.FileName):
                    write(doc)          # a part with a mesh here: kept up with the part
            else:
                fill(doc)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: display mesh cache: %s\n" % error)


def install():
    if not _observer:
        _observer.append(_Observer())
        App.addDocumentObserver(_observer[0])
