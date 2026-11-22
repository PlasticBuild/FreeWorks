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

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

from . import asmcore as ac
from . import compare as cmp

TABS = ("Documents", "Features", "Geometry", "BOM")


def _name(comp):
    if comp.TypeId == "App::Link" or ac.is_subassembly(comp):
        try:
            target = comp.getLinkedObject(True) if comp.TypeId == "App::Link" else comp.LinkedObject
        except Exception:
            target = None
        if target is not None:
            if target.Document is not comp.Document:
                return target.Document.Label
            return target.Label
    return comp.Label


def bom(doc):
    ""
    from . import asminsert
    asm = ac.assembly_of(doc)
    out = {}
    if asm is None:
        return out
    for comp in ac.components(asm):
        try:
            if asminsert.is_envelope(comp) or asminsert.is_excluded(comp):
                continue
        except Exception as _fw_err:
            _fw_log("asmcompare.py:57", _fw_err)
        if getattr(comp, "Suppressed", False):
            continue
        n = _name(comp)
        out[n] = out.get(n, 0) + max(1, int(getattr(comp, "ElementCount", 0) or 1))
    return out


def compare_bom(ref, mod):
    """[(part, reference quantity, modified quantity, result)] sorted by part."""
    a, b = bom(ref), bom(mod)
    rows = []
    for name in sorted(set(a) | set(b), key=str.lower):
        qa, qb = a.get(name), b.get(name)
        if qa is None:
            result = cmp.ONLY_MOD
        elif qb is None:
            result = cmp.ONLY_REF
        else:
            result = cmp.SAME if qa == qb else cmp.CHANGED
        rows.append((name, "" if qa is None else str(qa), "" if qb is None else str(qb), result))
    return rows


def open_tab(tab):
    win = cmp.compare()
    try:
        win.tabs.setCurrentIndex(TABS.index(tab))
    except Exception as _fw_err:
        _fw_log("asmcompare.py:86", _fw_err)
    return win


def install():
    W = cmp.CompareWindow
    if getattr(W, "_fw_bom", False):
        return
    init0, refresh0 = W.__init__, W.refresh

    def __init__(self, *a, **k):
        init0(self, *a, **k)
        self.bom = self._table(["Part", "Reference", "Modified", "Result"])
        self.bom.setObjectName("SWCompareBOM")
        self.tabs.addTab(self.bom, "BOM")

    def refresh(self):
        refresh0(self)
        if not self.result:
            return
        ref, mod = self._docs()
        rows = compare_bom(ref, mod)
        self.bom.clear()
        for row in rows:
            item = QtWidgets.QTreeWidgetItem(list(row))
            if row[3] != cmp.SAME:
                for col in range(4):
                    f = item.font(col)
                    f.setBold(True)
                    item.setFont(col, f)
            self.bom.addTopLevelItem(item)
        for i in range(self.bom.columnCount()):
            self.bom.resizeColumnToContents(i)
        self.result["bom"] = rows
        if ac.assembly_of(ref) is not None or ac.assembly_of(mod) is not None:
            self.summary.setText(self.summary.text() + " %d BOM rows differ." % sum(1 for r in rows if r[3] != cmp.SAME))

    W.__init__, W.refresh = __init__, refresh
    W._fw_bom = True
