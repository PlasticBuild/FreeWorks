# SPDX-License-Identifier: LGPL-2.1-or-later
"""extapps/63: the add-on's shape caches let go of a document's shapes when it closes.

multibody keeps the solids it has looked at (so their hashCode is not reused while the answer is kept) and silhouette keeps
the faces of each shape it outlines. Nothing emptied them when a part closed, so every part opened and closed in a session
stayed in memory: on the bench about 12 MB per open of a 20-feature part (stock FreeCAD: 0.3 MB). These are caches only:
whatever is asked again is worked out again, as on the first look."""
import sys

import FreeCAD as App

_PKG = __name__.rpartition(".")[0]
SHAPE_CACHES = (("multibody", "_QUICK"), ("multibody", "_PRINTS"), ("silhouette", "_INFO"),
                ("multibody", "_HISTORY"), ("displayextras", "_SEAMS_BY_SHAPE"))     # extapps/66
DOC_KEYED = (("multibody", "_name_cache"), ("displayextras", "_SEAMS"))     # keys start with the document's Name
_observer = None


def _cache(mod, attr):
    m = sys.modules.get(_PKG + "." + mod)
    c = getattr(m, attr, None) if m is not None else None
    return c if isinstance(c, dict) else None


def forget(doc_name=None):
    """Empties the shape caches and drops the entries of document doc_name. Returns how many entries went."""
    n = 0
    for mod, attr in SHAPE_CACHES:
        c = _cache(mod, attr)
        if c:
            n += len(c)
            c.clear()
    if doc_name:
        for mod, attr in DOC_KEYED:
            c = _cache(mod, attr)
            if c:
                for k in [k for k in c if isinstance(k, tuple) and k and k[0] == doc_name]:
                    c.pop(k, None)
                    n += 1
    return n


class _Observer:
    def slotDeletedDocument(self, doc):
        try:
            name = doc.Name
        except Exception:
            name = None
        try:
            forget(name)
        except Exception as error:
            App.Console.PrintLog("memtrim: %s\n" % error)


def install():
    global _observer
    if _observer is None:
        _observer = _Observer()
        App.addDocumentObserver(_observer)
    return _observer
