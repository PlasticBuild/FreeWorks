# SPDX-License-Identifier: LGPL-2.1-or-later
""


















import importlib.machinery
import importlib.util
import marshal
import mmap
import os
import sys
import zlib

MAGIC = b"FWBUNDLE1\n"
NAME = "modules.fwbundle"
_finder = None


class _Loader:
    def __init__(self, finder, name, entry, path):
        self.finder, self.name, self.entry, self.path = finder, name, entry, path

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        code = self.get_code(self.name)
        exec(code, module.__dict__)

    def get_code(self, name):
        off, n = self.entry["code"]
        code = marshal.loads(self.finder.data[off:off + n])
        try:
            import _imp
            _imp._fix_co_filename(code, self.path)       # tracebacks name the file where it is now
        except Exception:
            pass
        return code

    def get_source(self, name):
        off, n = self.entry["src"]
        return zlib.decompress(self.finder.data[off:off + n]).decode("utf-8")

    def is_package(self, name):
        return self.entry["pkg"]

    def get_filename(self, name):
        return self.path


class _Finder:
    def __init__(self, package, root, index, data):
        self.package, self.root, self.index, self.data = package, root, index, data
        self.prefix = package + "."
        self.used = 0
        self.stale = []

    def find_spec(self, name, path=None, target=None):
        if name != self.package and not name.startswith(self.prefix):
            return None
        entry = self.index.get(name)
        if entry is None:
            return None
        rel = entry["rel"]
        disk = os.path.join(self.root, *rel.split("/"))
        try:
            st = os.stat(disk)
            if st.st_size != entry["size"] or (entry["mtime"] is not None and int(st.st_mtime) != entry["mtime"]):
                self.stale.append(name)
                return None                     # edited since it was packed: Python's own import takes it
        except FileNotFoundError:
            pass                                # the release may ship without the .py: the bundle has it
        except OSError:
            return None
        loader = _Loader(self, name, entry, disk)
        spec = importlib.util.spec_from_file_location(
            name, disk, loader=loader,
            submodule_search_locations=[os.path.dirname(disk)] if entry["pkg"] else None)
        self.used += 1
        return spec


def _off():
    if os.environ.get("FREEWORKS_NO_BUNDLE"):
        return True
    try:
        import FreeCAD as App
        return App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks").GetBool("BundleOff", False)
    except Exception:
        return False


def install(package, package_dir):
    """From the package's __init__.py, before any of its modules is imported. Returns the finder or None."""
    global _finder
    if _finder is not None:
        return _finder
    path = os.path.join(package_dir, NAME)
    if not os.path.isfile(path) or _off():
        return None
    try:
        with open(path, "rb") as fh:
            data = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
        if data[:len(MAGIC)] != MAGIC:
            return None
        pos = len(MAGIC)
        hlen = int.from_bytes(data[pos:pos + 8], "little")
        header = marshal.loads(data[pos + 8:pos + 8 + hlen])
        if header.get("python") != importlib.util.MAGIC_NUMBER.hex() or header.get("package") != package:
            return None                         # made by another Python: the folder is used
        base = pos + 8 + hlen
        index = {}
        for name, e in header["modules"].items():
            e = dict(e)
            e["code"] = (base + e["code"][0], e["code"][1])
            e["src"] = (base + e["src"][0], e["src"][1])
            index[name] = e
        root = os.path.dirname(package_dir)
        _finder = _Finder(package, root, index, data)
        sys.meta_path.insert(0, _finder)
        return _finder
    except Exception as error:
        try:
            import FreeCAD as App
            App.Console.PrintLog("bundle not used: %s\n" % error)
        except Exception:
            pass
        return None
