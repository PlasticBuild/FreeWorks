# SPDX-License-Identifier: LGPL-2.1-or-later
""






_FW_SEEN = set()


def _fw_log(site, err):
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return


import FreeCAD as App

SPEEDPAK_KEY, SPEEDPAK_TEXT = "SpeedPak", "Speedpak Options"
AFTER = "ResolvedToLightweight"


def _order():
    """Puts the keys in fmmenu's top assembly order (at run time, as hieronly-1127 does)."""
    from . import fmmenu, asmunload, asmcompref
    order = list(fmmenu.TOP_ASSEMBLY_ORDER)
    changed = False
    at = order.index(AFTER) + 1 if AFTER in order else len(order)
    for key in (asmunload.KEY, asmcompref.KEY):
        if key not in order:
            order.insert(at, key)
            changed = True
        at = order.index(key) + 1
    if changed:
        fmmenu.TOP_ASSEMBLY_ORDER = tuple(order)


def speedpak_actions(asm):
    """[(text, run)] of Speedpak Options > for the top assembly: Add SpeedPak... (or Edit SpeedPak...) for its
    active configuration, and Update SpeedPak while a SpeedPak component is out of date."""
    from . import asmspconfig, asmspeedpak, asmreplacecomp
    doc = asm.Document
    out = []
    try:
        config = asmreplacecomp.active_configuration(doc) or "Default"
        if asmspconfig.has(doc, config):
            out.append(("Edit SpeedPak...", lambda: asmspconfig.open_panel(doc, config)))
        elif asmspconfig.main_object(doc) is not None:
            out.append(("Add SpeedPak...", lambda: asmspconfig.open_panel(doc, config)))
    except Exception as _fw_err:
        _fw_log("asmtoprows.py:speedpak config", _fw_err)
    try:
        if asmspeedpak.out_of_date(asm):
            def update():
                doc.openTransaction("Update SpeedPak")
                try:
                    asmspeedpak.update(asm)
                finally:
                    doc.commitTransaction()
            out.append(("Update SpeedPak", update))
    except Exception as _fw_err:
        _fw_log("asmtoprows.py:speedpak update", _fw_err)
    return out


def items(asm):
    """The rows for asmmenu.top_items: (key, text, run or fmmenu.Sub, enabled)."""
    if asm is None:
        return []
    from . import fmmenu, asmunload, asmcompref
    try:
        _order()
    except Exception as _fw_err:
        _fw_log("asmtoprows.py:order", _fw_err)
    out = []
    acts = speedpak_actions(asm)
    if acts:
        def fill(m, acts=acts):
            for text, run in acts:
                a = m.addAction(text)
                a.triggered.connect(lambda _c=False, r=run: r())
        out.append((SPEEDPAK_KEY, SPEEDPAK_TEXT, fmmenu.Sub(fill), True))
    for row in (asmunload.menu_item(asm), asmcompref.menu_item(asm)):
        if row is not None:
            out.append(row)
    return out
