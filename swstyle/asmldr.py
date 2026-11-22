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

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except Exception:   # pragma: no cover
    Gui = None

from . import asmcore as ac

MODES = ("Resolved", "Lightweight", "Large Assembly Settings", "Large Design Review")
PARAM = "User parameter:BaseApp/Preferences/Mod/FreeWorks/Assemblies"
REVIEW = {}          # document name: {"edit": bool}
BAR = "FW_LargeDesignReviewBar"


def _p():
    return App.ParamGet(PARAM)


# ---------------------------------------------------------------- options (Options > Assemblies)
def ldr_auto():
    return _p().GetBool("LDRWhenOver", False)


def ldr_limit():
    return _p().GetInt("LDRLimit", 5000)


def light_auto():
    return _p().GetBool("LightweightWhenOver", True)


def light_limit():
    return _p().GetInt("LightweightLimit", 500)


def mode_for(count, chosen="Resolved"):
    """The mode an assembly of count components opens in: the one picked in the Open dialog, or
    the Options' thresholds when Resolved was left."""
    if chosen != "Resolved":
        return chosen
    if ldr_auto() and count > ldr_limit():
        return "Large Design Review"
    if light_auto() and count > light_limit():
        return "Large Assembly Settings"
    return "Resolved"


# ---------------------------------------------------------------- the review state
def in_review(doc):
    """True while doc is in Large Design Review with Edit Assembly off."""
    if doc is None:
        return False
    state = REVIEW.get(doc.Name)
    return state is not None and not state["edit"]


def is_ldr(doc):
    return doc is not None and doc.Name in REVIEW


def enter(doc):
    REVIEW[doc.Name] = {"edit": False}
    _show_bar(doc)
    _refresh()
    return True


def leave(doc_name):
    REVIEW.pop(doc_name, None)
    _hide_bar()
    _refresh()


def set_edit(doc, on):
    """Edit Assembly: on, the assembly commands come back; off, review again."""
    if doc is None or doc.Name not in REVIEW:
        return False
    if on and REVIEW[doc.Name].get("saved_graphics"):
        from . import asmreview          # the review window of saved graphics: load the assembly now
        return asmreview.resolve(doc, edit=True) is not None
    REVIEW[doc.Name]["edit"] = bool(on)
    if _bar() is not None:
        _bar().edit.blockSignals(True)
        _bar().edit.setChecked(bool(on))
        _bar().edit.blockSignals(False)
    _refresh()
    return True


def _refresh():
    """The commands' enabled state again now. FreeCAD 1.1 on Windows has no updateCommands; its
    main window updates the commands on its own timer, so nothing more is needed there."""
    update = getattr(Gui, "updateCommands", None)
    if update is None:
        return
    try:
        update()
    except Exception as _fw_err:
        _fw_log("asmldr.py:121", _fw_err)


def _edit_later(doc_name, on):
    """Edit Assembly from the review bar's check: run after the click is done. Leaving a review of
    saved graphics closes that window (and this bar with it), which must not happen inside the
    check's own signal (Windows aborts)."""
    def run():
        doc = App.listDocuments().get(doc_name)
        if doc is not None:
            set_edit(doc, on)
    QtCore.QTimer.singleShot(0, run)


def apply_mode(doc, mode):
    """After the document opened: Lightweight components, Large Assembly Settings, or review."""
    asm = ac.assembly_of(doc)
    if asm is None or mode == "Resolved":
        return mode
    if mode == "Lightweight":
        from . import asmcomp, asmlight
        subs = asmlight.always_resolve_subs()     # Options > Performance: Always resolve sub-assemblies
        for comp in ac.components(asm):
            if subs and ac.is_subassembly(comp):
                continue
            try:
                asmcomp.set_lightweight(comp, True)
            except Exception as _fw_err:
                _fw_log("asmldr.py:138", _fw_err)
    elif mode == "Large Assembly Settings":
        from . import asmlarge
        asmlarge.set_mode(True)
    elif mode == "Large Design Review":
        enter(doc)
        from . import asmoptions
        if asmoptions.ldr_update():     # Automatically check and update all components in LDR
            REVIEW[doc.Name]["updated"] = [d.Name for d in asmoptions.update_out_of_date(asm)]
    return mode


def open_assembly(path, mode="Resolved"):
    from . import asmreview
    review = asmreview.try_open(path, mode)      # the parts' saved graphics, nothing loaded
    if review is not None:
        return review
    doc = App.openDocument(path)
    asm = ac.assembly_of(doc)
    if asm is not None:
        apply_mode(doc, mode_for(len(ac.components(asm)), mode))
    return doc


# ---------------------------------------------------------------- the bar
if Gui is not None:
    class ReviewBar(QtWidgets.QFrame):
        """Large Design Review over the assembly: its Edit Assembly check."""

        def __init__(self, doc):
            super().__init__(Gui.getMainWindow())
            self.setObjectName(BAR)
            self.doc_name = doc.Name
            lay = QtWidgets.QHBoxLayout(self)
            lay.setContentsMargins(8, 2, 8, 2)
            self.label = QtWidgets.QLabel("Large Design Review")
            self.label.setObjectName("FW_LDRLabel")
            lay.addWidget(self.label)
            self.edit = QtWidgets.QCheckBox("Edit Assembly")
            self.edit.setObjectName("FW_LDREditAssembly")
            self.edit.setToolTip("Add and edit mates, move and insert components in Large Design Review.")
            self.edit.toggled.connect(lambda on: _edit_later(self.doc_name, on))
            lay.addWidget(self.edit)
            self.selective = QtWidgets.QPushButton("Selective Open")
            self.selective.setObjectName("FW_LDRSelectiveOpen")
            self.selective.setToolTip("Open only the selected or visible components, resolved, to work on them.")
            self.selective.clicked.connect(lambda: selective_dialog(App.getDocument(self.doc_name)).show())
            lay.addWidget(self.selective)
            lay.addStretch(1)


# ---------------------------------------------------------------- Selective Open
def _mate_comps(asm, joint):
    out = []
    for prop in ("Reference1", "Reference2"):
        ref = getattr(joint, prop, None)
        if ref:
            try:
                out.append(ac._part_of(asm, ref))
            except Exception as _fw_err:
                _fw_log("asmldr.py:198", _fw_err)
    return out


def _chosen(doc, which):
    from . import asmreview
    if asmreview.is_review(doc):
        return asmreview.chosen(doc, which)
    asm = ac.assembly_of(doc)
    comps = ac.components(asm) if asm is not None else []
    if which == "Visible":
        return [c for c in comps if getattr(c, "Visibility", True)]
    picked = []
    for sel in Gui.Selection.getSelectionEx("", 0):
        if sel.Object in comps and sel.Object not in picked:
            picked.append(sel.Object)
        for sub in sel.SubElementNames:
            ref = ac.reference(asm, sel.Object, sub) if sub else None
            if ref is not None and ref[0] in comps and ref[0] not in picked:
                picked.append(ref[0])
    return picked


def selective_open(doc, comps, include_mates=True):
    ""



    from . import asmcomp, asmmenu, asmreview
    if asmreview.is_review(doc):
        return asmreview.selective_open(doc, comps, include_mates)
    asm = ac.assembly_of(doc)
    if asm is None or not comps:
        return {}
    keep = set(c.Name for c in comps)
    hidden, light, off = [], [], []
    doc.openTransaction("Selective Open")
    try:
        for c in ac.components(asm):
            if c.Name in keep:
                if asmcomp.is_lightweight(c):
                    asmcomp.set_lightweight(c, False)
                if c.ViewObject is not None and not c.ViewObject.Visibility:
                    c.ViewObject.Visibility = True
                continue
            if c.ViewObject is not None and c.ViewObject.Visibility:
                c.ViewObject.Visibility = False
                hidden.append(c.Name)
            if not asmcomp.is_lightweight(c):
                asmcomp.set_lightweight(c, True)
                light.append(c.Name)
        for j in ac.mates(asm):
            names = set(getattr(c, "Name", "") for c in _mate_comps(asm, j))
            inside = names and names <= keep
            if include_mates and inside:
                continue
            if not asmmenu.suppressed(j):
                off.append(j.Name)
    finally:
        doc.commitTransaction()
    for name in off:
        asmmenu.suppress(doc.getObject(name), True)
    REVIEW.pop(doc.Name, None)
    _hide_bar()
    _refresh()
    out = {"opened": sorted(keep), "hidden": hidden, "lightweight": light, "mates_off": off}
    SELECTIVE[doc.Name] = out
    return out


SELECTIVE = {}

if Gui is not None:
    class SelectiveOpenDialog(QtWidgets.QDialog):
        """Selective Open: Selected components or Visible components, Include mates, then
        Open Selected (Open Visible)."""

        def __init__(self, doc):
            super().__init__(Gui.getMainWindow())
            self.setObjectName("FW_SelectiveOpen")
            self.setWindowTitle("Selective Open")
            self.doc_name = doc.Name
            lay = QtWidgets.QVBoxLayout(self)
            self.selected = QtWidgets.QRadioButton("Selected components")
            self.selected.setObjectName("FW_SelOpenSelected")
            self.visible = QtWidgets.QRadioButton("Visible components")
            self.visible.setObjectName("FW_SelOpenVisible")
            self.selected.setChecked(True)
            for w in (self.selected, self.visible):
                lay.addWidget(w)
                w.toggled.connect(self._sync)
            self.list = QtWidgets.QListWidget()
            self.list.setObjectName("FW_SelOpenList")
            lay.addWidget(self.list)
            self.mates = QtWidgets.QCheckBox("Include mates")
            self.mates.setObjectName("FW_SelOpenMates")
            self.mates.setChecked(True)
            lay.addWidget(self.mates)
            row = QtWidgets.QHBoxLayout()
            row.addStretch(1)
            self.open = QtWidgets.QPushButton("Open Selected")
            self.open.setObjectName("FW_SelOpenOpen")
            self.open.clicked.connect(self.run)
            cancel = QtWidgets.QPushButton("Cancel")
            cancel.clicked.connect(self.reject)
            row.addWidget(self.open)
            row.addWidget(cancel)
            lay.addLayout(row)
            self._sync()

        def which(self):
            return "Visible" if self.visible.isChecked() else "Selected"

        def comps(self):
            return _chosen(App.getDocument(self.doc_name), self.which())

        def _sync(self, *a):
            self.open.setText("Open Visible" if self.visible.isChecked() else "Open Selected")
            self.list.clear()
            try:
                comps = self.comps()
            except Exception:
                comps = []
            for c in comps:
                self.list.addItem(c.Label)
            self.open.setEnabled(bool(comps))

        def run(self):
            self.result_ = selective_open(App.getDocument(self.doc_name), self.comps(), self.mates.isChecked())
            self.accept()


def selective_dialog(doc):
    return SelectiveOpenDialog(doc)


def _bar():
    if Gui is None:
        return None
    for bar in Gui.getMainWindow().findChildren(QtWidgets.QFrame, BAR):
        if bar.isVisibleTo(Gui.getMainWindow()):
            return bar
    return None


def _show_bar(doc):
    if Gui is None or not App.GuiUp:
        return
    _hide_bar()
    bar = ReviewBar(doc)
    mw = Gui.getMainWindow()
    tb = QtWidgets.QToolBar("Large Design Review", mw)
    tb.setObjectName(BAR + "Toolbar")
    tb.addWidget(bar)
    mw.addToolBar(QtCore.Qt.TopToolBarArea, tb)
    tb.show()


def _hide_bar():
    if Gui is None or not App.GuiUp:
        return
    mw = Gui.getMainWindow()
    for tb in mw.findChildren(QtWidgets.QToolBar, BAR + "Toolbar"):
        tb.hide()
        mw.removeToolBar(tb)
        tb.deleteLater()


class _DocWatch:
    def slotDeletedDocument(self, doc):
        if doc.Name in REVIEW:
            leave(doc.Name)
        try:
            from . import asmreview
            asmreview.SAVED.pop(doc.Name, None)
        except Exception as _fw_err:
            _fw_log("asmldr.py:374", _fw_err)


# ---------------------------------------------------------------- the Open dialog's Mode
def _add_mode(box):
    ""


    own = getattr(box, "mode", None)
    if own is not None:
        box._fw_mode = own
        return box
    try:
        lay = box.layout()
        combo = QtWidgets.QComboBox(box)
        combo.setObjectName("FW_OpenMode")
        combo.addItems(list(MODES))
        label = QtWidgets.QLabel("Mode:", box)
        row = lay.rowCount()
        lay.addWidget(label, row, 0)
        lay.addWidget(combo, row, 1)
        box._fw_mode = combo
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Open Mode: %s\n" % error)
    return box


def _assembly_modes(saveas):
    """The Open dialog's assembly Mode list with every mode this file opens (Large Assembly Settings)."""
    try:
        kinds = saveas.MODES
        have = list(kinds.get("assembly", []))
        kinds["assembly"] = [m for m in MODES if m in have or m == "Large Assembly Settings"] + \
            [m for m in have if m not in MODES]
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Open Mode list: %s\n" % error)


def install():
    """Mode in File > Open, the review gate on the assembly commands, the document watch."""
    from . import asmtools, saveas
    if getattr(saveas, "_fw_ldr", False):
        return
    saveas._fw_ldr = True
    dialog = saveas.open_dialog
    opener = saveas.open_file

    def open_dialog():
        return _add_mode(dialog())

    def open_file(path, _mode=None, speedpak=False, skip_hidden=False, mode=None, **choices):
        # choices: configuration, display_state, read_only (the Open dialog's), passed on to its opener.
        # filehandling88: mode= by name as saveas.open_file takes it (it raised "multiple values for 'mode'")
        mode = _mode or mode or STATE.get("mode") or "Resolved"
        speedpak = speedpak or STATE.get("speedpak", False)
        skip_hidden = skip_hidden or STATE.get("skip_hidden", False)
        if mode not in MODES:           # Detailing (a drawing): the Open dialog's own
            return opener(path, mode, speedpak, skip_hidden, **choices)
        if path.lower().endswith(".fcstd"):
            from . import asmreview
            review = asmreview.try_open(path, mode)
            if review is not None:
                return review
            doc = opener(path, "Resolved", speedpak, skip_hidden, **choices)
            asm = ac.assembly_of(doc)
            if asm is not None:
                apply_mode(doc, mode_for(len(ac.components(asm)), mode))
            return doc
        return opener(path, "Resolved", speedpak, skip_hidden, **choices)

    def open_files(paths_=None, mode=None, speedpak=False, skip_hidden=False):
        if paths_ is None:
            box = saveas.open_dialog()
            if not box.exec():
                return []
            paths_ = box.selectedFiles()
            if getattr(box, "previous_version", None):
                # open124: Show previous versions opened the current file (read-only): the chosen save, as saveas does
                paths_ = [saveas._version_copy(box.previous_version)]
                import os
                saveas._PENDING.clear()         # the current file's choices are not this copy's (nor kept for later)
                saveas._PENDING[os.path.normcase(os.path.abspath(paths_[0]))] = (None, None, True)
            combo = getattr(box, "_fw_mode", None)
            mode = combo.currentText() if combo is not None else "Resolved"
            sp, sh = getattr(box, "speedpak", None), getattr(box, "skip_hidden", None)
            speedpak = sp is not None and sp.isEnabled() and sp.isChecked()
            skip_hidden = sh is not None and sh.isEnabled() and sh.isChecked()
        STATE.update(mode=mode, speedpak=speedpak, skip_hidden=skip_hidden)
        out, failed = [], []
        try:
            for p in paths_:
                try:
                    d = saveas.open_file(p)
                except Exception as error:
                    App.Console.PrintError("FreeCAD: %s not opened: %s\n" % (p, error))
                    failed.append((p, saveas._open_error_text(error)))
                    continue
                if d is not None:
                    out.append(d)
        finally:
            STATE.update(mode=None, speedpak=False, skip_hidden=False)
        if failed:
            saveas._tell_not_opened(failed)     # save114: say which files did not open, and why
        return out

    _assembly_modes(saveas)
    saveas.open_dialog = open_dialog
    saveas.open_file = open_file
    saveas.open_files = open_files
    gate = asmtools._assembly

    def _assembly():
        asm = gate()
        if asm is not None and in_review(asm.Document):
            return None
        return asm

    asmtools._assembly = _assembly
    _gate_commands()
    if not getattr(App, "_fw_ldr_watch", None):
        App._fw_ldr_watch = _DocWatch()
        App.addDocumentObserver(App._fw_ldr_watch)


STATE = {"mode": None}
# what Large Design Review keeps on: looking, measuring, sections, snapshots, motion playback
OPEN_IN_REVIEW = ("Snapshot", "Measure", "Section", "Walk", "Display", "Evaluate", "Preview", "Interference",
                  "Clearance", "Hole Alignment", "Large", "Exploded", "Motion")


def _gate_commands():
    """The assembly commands' IsActive: off in Large Design Review (Edit Assembly off)."""
    import sys
    pkg = __name__.rsplit(".", 1)[0]
    for name, mod in list(sys.modules.items()):
        if not name.startswith(pkg + ".asm") or mod is None:
            continue
        cmds = getattr(mod, "COMMANDS", None)
        items = cmds.items() if isinstance(cmds, dict) else (cmds or ())
        for entry in items:
            try:
                cname, cmd = entry[0], entry[1]
            except Exception:
                continue
            if any(k.lower() in cname.lower() for k in OPEN_IN_REVIEW):
                continue
            cls = cmd if isinstance(cmd, type) else type(cmd)
            if getattr(cls, "_fw_ldr_gate", False) or not hasattr(cls, "IsActive"):
                continue
            orig = cls.IsActive

            def is_active(self, *a, _o=orig):
                if in_review(App.ActiveDocument):
                    return False
                return _o(self, *a)
            cls.IsActive = is_active
            cls._fw_ldr_gate = True


def _safe(fn, path):
    try:
        return fn(path)
    except Exception as error:
        App.Console.PrintError("FreeCAD: %s not opened: %s\n" % (path, error))
        return None
