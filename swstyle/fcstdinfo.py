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
import os
import re
import zipfile

_cache = {}


def _xml(path):
    try:
        with zipfile.ZipFile(path) as z:
            return z.read("Document.xml").decode("utf-8", "replace")
    except Exception:
        return ""


def info(path):
    """{'kind', 'configurations', 'display_states', 'references', 'top_level'} for an FCStd file."""
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        return None
    key = os.path.normcase(path)
    hit = _cache.get(key)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    xml = _xml(path)
    out = {"kind": "", "configurations": ["Default"], "display_states": [], "references": [], "top_level": False}
    if xml:
        types = set(re.findall(r'<Object type="([^"]+)"', xml))
        if any(t.startswith("TechDraw::DrawPage") for t in types):
            out["kind"] = "drawing"
        elif "Assembly::AssemblyObject" in types:
            out["kind"] = "assembly"
        elif types:
            out["kind"] = "part"
        m = re.search(r'<Property name="Configuration" type="App::PropertyEnumeration".*?</Property>', xml, re.S)
        if m:
            names = re.findall(r'<Enum value="([^"]*)"', m.group(0))
            if names:
                out["configurations"] = names
        m = re.search(r'<Item key="SWDisplayStates" value="([^"]*)"', xml)
        if m:
            try:
                text = m.group(1).replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                data = json.loads(text)
                # open110: the stored states are {"order": [names], "states": {...}, "active", "cfg": {name: configuration}}
                if isinstance(data, dict) and "order" in data:
                    out["display_states"] = [n for n in data.get("order") or [] if isinstance(n, str)]
                    out["display_state_configs"] = dict(data.get("cfg") or {})
                else:
                    out["display_states"] = list(data.keys()) if isinstance(data, dict) else []
            except Exception as _fw_err:
                _fw_log("fcstdinfo.py:66", _fw_err)
        refs = re.findall(r'<XLink file="([^"]+)"', xml) + re.findall(r'<Property name="LinkedObject"[^>]*>\s*<XLink[^>]*file="([^"]+)"', xml)
        folder = os.path.dirname(path)
        seen = []
        for r in refs:
            full = r if os.path.isabs(r) else os.path.normpath(os.path.join(folder, r))
            if full not in seen:
                seen.append(full)
        out["references"] = seen
    _cache[key] = (stamp, out)
    return out


def kind(path):
    i = info(path)
    return i["kind"] if i else ""


def is_top_level(path, folder_files):
    """A top-level assembly: an assembly no other file in the folder references."""
    i = info(path)
    if not i or i["kind"] != "assembly":
        return False
    me = os.path.normcase(os.path.normpath(path))
    for other in folder_files:
        if os.path.normcase(os.path.normpath(other)) == me:
            continue
        o = info(other)
        if o and any(os.path.normcase(os.path.normpath(r)) == me for r in o["references"]):
            return False
    return True


def thumbnail(path):
    """The file's thumbnail as PNG bytes, or b''."""
    try:
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if name.lower().endswith("thumbnail.png"):
                    return z.read(name)
    except Exception as _fw_err:
        _fw_log("fcstdinfo.py:107", _fw_err)
    return _tessellation_png(path)


def _tessellation_png(path):
    """No thumbnail: the model drawn from its saved tessellation (Save tessellation with part document)."""
    try:
        from . import tessave
        if not tessave.has(path):
            return b""
        from PySide import QtCore
        img = tessave.render(path, 256, 256)
        if img is None:
            return b""
        buf = QtCore.QBuffer()
        buf.open(QtCore.QIODevice.WriteOnly)
        img.save(buf, "PNG")
        return bytes(buf.data())
    except Exception:
        return b""
