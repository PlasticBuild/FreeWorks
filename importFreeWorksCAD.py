# SPDX-License-Identifier: LGPL-2.1-or-later
""


import os

import FreeCAD as App

SW = (".sldprt", ".sldasm", ".x_t", ".x_b", ".xmt_txt", ".xmt_bin")


def _open_into(filename, doc):
    from swfiles import cadconv
    if not filename:
        raise ValueError("no file given")
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".sldasm":
        from swfiles import assembly
        doc = assembly.open_assembly(filename, doc)
    elif ext in SW:
        from swfiles import part
        doc, _how = part.open_part(filename, doc)
    elif ext in cadconv.OPEN:
        doc = cadconv.open_file(filename, doc)
    else:
        raise ValueError("FreeCAD cannot open %s files" % ext)
    if App.GuiUp:
        import FreeCADGui as Gui
        Gui.SendMsgToActiveView("ViewFit")
    return doc


def open(filename):
    """File > Open: a new document named after the file."""
    try:
        return _open_into(filename, None)
    except Exception as exc:
        from swfiles import tell
        tell("Could not open %s:\n\n%s" % (os.path.basename(filename or ""), exc), icon="warning")
        raise


def insert(filename, docname):
    """File > Import: into an existing document."""
    try:
        doc = App.getDocument(docname)
    except NameError:
        doc = App.newDocument(docname)
    App.setActiveDocument(doc.Name)
    return _open_into(filename, doc)


def export(objs, filename):
    ""
    from swfiles import save
    save.export(objs, filename)
