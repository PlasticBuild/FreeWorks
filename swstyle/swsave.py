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

COMMAND = "SWStyle_Save"


def _clear_modified(doc):
    """App's save leaves the GUI document "modified" (title asterisk, Save prompt on close: ChatGPT
    C13-01); Std_Save clears it, so clear it the same way."""
    try:
        Gui.getDocument(doc.Name).Modified = False
    except Exception as _fw_err:
        _fw_log("swsave.py:29", _fw_err)


def _clear_after(doc):
    """An assembly saved with its parts (Save Modified Documents > Save All) is marked modified again
    a moment later, when its links take the parts' new files: the title kept its asterisk although
    nothing changed (rcmenus menus-only pass). Clear it again then, unless something did change."""
    try:
        from PySide import QtCore
    except Exception:
        return
    name = doc.Name

    def again():
        d = App.listDocuments().get(name)
        if d is not None and not d.isTouched():
            _clear_modified(d)
    for ms in (0, 300, 1000):
        QtCore.QTimer.singleShot(ms, again)



def _modified(doc):
    try:
        gdoc = Gui.getDocument(doc.Name)
        if gdoc is not None and gdoc.Modified:
            return True
    except Exception as _fw_err:
        _fw_log("swsave.py:57", _fw_err)
    try:
        return bool(doc.isTouched())
    except Exception as _fw_err:
        _fw_log("swsave.py:62", _fw_err)
        return False


def modified_dependents(doc):
    """The changed documents this one references (an assembly's parts and subassemblies), nearest
    first, without the document itself."""
    try:
        deps = list(doc.getDependentDocuments())
    except Exception as _fw_err:
        _fw_log("swsave.py:72", _fw_err)
        return []
    out = []
    for d in deps:
        if d is doc or d.Name == doc.Name or getattr(d, "Temporary", False):
            continue
        if _modified(d) and d not in out:
            out.append(d)
    return out


def _save_dependents(doc):
    ""


    deps = modified_dependents(doc)
    if not deps:
        return True
    from . import closeprompt
    answer, ticked = closeprompt.ask([doc] + deps)
    if answer == closeprompt.CANCEL:
        return False
    if answer == closeprompt.SAVE:
        for d in ticked:
            if d is doc or d.Name == doc.Name:
                continue
            if not closeprompt._save(d):
                return False
            _clear_modified(d)
    return True


def save(doc=None, ask_dependents=True):
    """True when the document was saved. ask_dependents False (Save All): the changed referenced documents are
    saved by Save All itself, so no Save Modified Documents box."""
    doc = doc or App.ActiveDocument
    if doc is None:
        return False
    try:
        from . import drawings
        holding = drawings.temp_path(doc)
    except Exception:
        holding = None
    if holding:
        # a new drawing or assembly still in its holding file: Save As first (drawings / assemblies

        if not drawings.save_as_first(doc):
            return False
        if ask_dependents:
            _save_dependents(doc)
        return True
    if ask_dependents and not _save_dependents(doc):
        return False
    try:
        from . import filecmds
        if doc.FileName and filecmds.is_read_only(doc):

            from PySide import QtWidgets
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Save", filecmds.read_only_message(doc))
            return False
    except Exception as _fw_err:
        _fw_log("swsave.py:read-only", _fw_err)
    if doc.FileName:
        try:
            from . import rebuildsave
            if not rebuildsave.ask(doc):
                return False
            if not rebuildsave.ask_errors(doc):     # msgbox-1119: rebuild errors left: save anyway?
                return False
        except Exception as error:
            App.Console.PrintLog("FreeCAD: rebuild on save: %s\n" % error)
        try:
            from . import filelock      # fh163: a file changed on disk after it was opened here: ask first
            if not filelock.save_over_ok(doc):
                return False
        except Exception as _fw_err:
            _fw_log("swsave.py:changed-on-disk", _fw_err)
        try:
            doc.save()
        except Exception as error:
            # refs129: a file read-only on disk or held open by another program: say so (it was a Report view line)
            from PySide import QtWidgets
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Save", (
                "%s could not be saved. It is read-only, or open in another program.\n\nUse Save As to save it "
                "under a different name.\n\n%s" % (__import__("os").path.basename(doc.FileName), error)))
            return False
        _clear_modified(doc)
        _clear_after(doc)
        return True
    try:
        from . import saveas
        return saveas.save_as(doc) is not None
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Save As box: %s\n" % error)
        Gui.runCommand("Std_SaveAs", 0)
        return bool(doc.FileName)


class SaveCommand:
    def GetResources(self):
        return {"MenuText": "Save", "ToolTip": "Saves the open file (Ctrl+S)", "Accel": "Ctrl+S",
                "Pixmap": "document-save", "CmdType": "ForEdit"}     # extapps77: also while a sketch is open

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        try:
            save()
        except Exception as error:
            App.Console.PrintError("FreeCAD: Save failed: %s\n" % error)


class SaveAllCommand:
    ""

    def GetResources(self):
        return {"MenuText": "Save All", "ToolTip": "Saves every open document that has changes.",
                "Pixmap": "document-save", "CmdType": "ForEdit"}

    def IsActive(self):
        return bool(App.listDocuments())

    def Activated(self):
        save_all()


def save_order(docs):
    ""

    docs = list(docs)
    names = {d.Name for d in docs}
    out, done = [], set()

    def visit(d, depth=0):
        if d.Name in done or depth > 40:
            return
        done.add(d.Name)
        try:
            deps = [x for x in d.getDependentDocuments() if x.Name != d.Name and x.Name in names]
        except Exception:
            deps = []
        for x in deps:
            visit(x, depth + 1)
        out.append(d)
    for d in docs:
        visit(d)
    return out


def _read_only(doc):
    try:
        from . import filecmds
        return bool(doc.FileName) and filecmds.is_read_only(doc)
    except Exception as _fw_err:
        _fw_log("swsave.py:read-only", _fw_err)
        return False


def save_all():
    ""

    saved = []
    for doc in save_order(App.listDocuments().values()):
        try:
            if getattr(doc, "Temporary", False):
                continue
            if not _modified(doc) and doc.FileName:
                continue
            if _read_only(doc):
                # save112: a document opened read-only is left as it is (Save would refuse it with a box and stop
                # Save All); the other documents are still saved
                App.Console.PrintMessage("FreeCAD: Save All: %s was opened read-only and was not saved.\n" % doc.Label)
                continue
            if not save(doc, ask_dependents=False):
                break
            saved.append(doc.Name)
        except Exception as error:
            App.Console.PrintError("FreeCAD: Save All: %s: %s\n" % (doc.Label, error))
    return saved


def saved_by():
    ""

    try:
        name = App.ParamGet("User parameter:BaseApp/Preferences/Document").GetString("prefAuthor", "")
        if name:
            return name
        import getpass
        return getpass.getuser()
    except Exception as _fw_err:
        _fw_log("swsave.py:saved-by", _fw_err)
        return ""


class _SavedBy:
    """save112: File > Properties' Last Saved By was blank: every save (Save, Save As, Save All, Pack and Go,
    a copy) writes who saved it, whichever way the file is saved."""
    def slotStartSaveDocument(self, doc, path):
        try:
            name = saved_by()
            if name and doc.LastModifiedBy != name:
                doc.LastModifiedBy = name
        except Exception as _fw_err:
            _fw_log("swsave.py:saved-by", _fw_err)


_SAVED_BY = []


def register():
    if not _SAVED_BY:
        _SAVED_BY.append(_SavedBy())
        App.addDocumentObserver(_SAVED_BY[0])
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, SaveCommand())
    if "SWStyle_SaveAll" not in Gui.listCommands():
        Gui.addCommand("SWStyle_SaveAll", SaveAllCommand())
