# SPDX-License-Identifier: LGPL-2.1-or-later
""






import os
import shutil
import subprocess
import sys
import tempfile

import FreeCAD as App

from . import doc_name, msg, params, warn

# extension -> what it is (only formats cadmpeg turns into geometry)
OPEN = {
    ".ipt": "Inventor part", ".iam": "Inventor assembly", ".catpart": "CATIA part",
    ".f3d": "Fusion part", ".3dm": "Rhino model", ".pvz": "Creo View model",
    ".sat": "ACIS", ".sab": "ACIS", ".smt": "ShapeManager", ".smb": "ShapeManager",
}
SAVE = {".3dm": "Rhino model"}


class ConvertError(RuntimeError):
    pass


def executable():
    own = params().GetString("CadmpegPath", "")
    if own and os.path.isfile(own):
        return own
    exe = "cadmpeg.exe" if sys.platform == "win32" else "cadmpeg"
    found = shutil.which(exe)
    if found:
        return found
    for d in (os.path.join(os.path.expanduser("~"), ".cargo", "bin"),
              os.path.join(App.getUserAppDataDir(), "Mod", "FreeWorks", "tools")):
        p = os.path.join(d, exe)
        if os.path.isfile(p):
            return p
    return None


def convert(src, dst):
    exe = executable()
    if not exe:
        raise ConvertError("cadmpeg was not found. Install it from github.com/cadmpeg/cadmpeg "
                           "or set its path in the FreeCAD file options.")
    flags = 0x08000000 if sys.platform == "win32" else 0
    r = subprocess.run([exe, "convert", src, "-o", dst], stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, universal_newlines=True, timeout=900,
                       creationflags=flags)
    if r.returncode != 0 or not os.path.isfile(dst):
        last = (r.stdout or "").strip().splitlines()[-3:]
        raise ConvertError("cadmpeg could not convert %s: %s" % (os.path.basename(src), " / ".join(last)))
    App.Console.PrintLog(r.stdout or "")
    return dst


def open_file(path, doc=None):
    """Opens another program's CAD file through STEP. Returns the document."""
    base = os.path.splitext(os.path.basename(path))[0]
    tmp = tempfile.mkdtemp(prefix="fw-cad-")
    try:
        step = convert(path, os.path.join(tmp, "model.step"))
        if doc is None:
            doc = App.newDocument(doc_name(base))
            doc.Label = base
        import Import
        Import.insert(step, doc.Name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    meta = dict(doc.Meta)
    meta.update({"FreeWorksSource": os.path.abspath(path),
                 "FreeWorksSourceKind": os.path.splitext(path)[1].lower().lstrip(".")})
    doc.Meta = meta
    doc.recompute()
    msg("%s opened through cadmpeg (geometry)" % os.path.basename(path))
    return doc


def save_file(objs, path):
    """Writes objs to another format through STEP and cadmpeg."""
    tmp = tempfile.mkdtemp(prefix="fw-cad-")
    try:
        import Import
        step = os.path.join(tmp, "model.step")
        Import.export(objs, step)
        out = os.path.join(tmp, "out" + os.path.splitext(path)[1].lower())
        convert(step, out)
        shutil.copyfile(out, path)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    msg("wrote %s through cadmpeg" % path)
