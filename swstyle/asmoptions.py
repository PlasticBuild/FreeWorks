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

from . import paths

MOVE_BY_DRAG = "AsmMoveByDragging"
OPTIMIZE_PLACEMENT = "AsmOptimizePlacement"
MISALIGNED = "AsmAllowMisaligned"
ALIGN_ON_EDIT = "AsmChangeAlignmentOnEdit"      # "Always", "Never" or "Prompt"
ALIGN_CHOICES = ("Always", "Never", "Prompt")
IN_CONTEXT = "AsmInContextTransparency"
IN_CONTEXT_CHOICES = ("Opaque assembly", "Maintain assembly transparency", "Force assembly transparency")
IN_CONTEXT_LEVEL = "AsmInContextLevel"          # % for Force assembly transparency
SPEEDPAK_OPACITY = "AsmSpeedPakCircleOpacity"
SAVE_EXTERNAL = "AsmSaveNewExternal"            # Save new components to external files
UPDATE_GRAPHICS = "AsmUpdateGraphicsOnSave"     # Update model graphics when saving files
LDR_UPDATE = "AsmLDRCheckUpdate"                # Automatically check and update all components in LDR
SPEEDPAK_SAVE = "AsmSpeedpakOnSave"             # "None", "All" or "Prompt"
SPEEDPAK_CHOICES = ("None", "All", "Prompt")
ENV_LIGHT = "AsmEnvelopeLightweight"            # Envelope Components: Automatically load lightweight
ENV_READ_ONLY = "AsmEnvelopeReadOnly"           # Envelope Components: Load read-only
MIRROR_AFFIX = "AsmMirrorAffix"                 # "Add Prefix" or "Add Suffix"
MIRROR_AFFIX_CHOICES = ("Add Prefix", "Add Suffix")
MIRROR_TEXT = "AsmMirrorAffixText"
VIRTUAL_PREFIX = "AsmVirtualPrefix"


def _p():
    return paths.params()


def move_by_dragging():
    return _p().GetBool(MOVE_BY_DRAG, True)


def optimize_placement():
    return _p().GetBool(OPTIMIZE_PLACEMENT, True)


def misaligned():
    return _p().GetBool(MISALIGNED, True)


def align_on_edit():
    value = _p().GetString(ALIGN_ON_EDIT, "Always")
    return value if value in ALIGN_CHOICES else "Always"


def _old(text, default):
    ""
    try:
        from . import optionspages
        return optionspages.stored("Assemblies", text, default)
    except Exception as _fw_err:
        _fw_log("asmoptions.py:84", _fw_err)
        return default


def save_external():
    return _p().GetBool(SAVE_EXTERNAL, _old("Save new components to external files", False))


def update_graphics():
    return _p().GetBool(UPDATE_GRAPHICS, _old("Update model graphics when saving files", False))


def ldr_update():
    return _p().GetBool(LDR_UPDATE, _old("Automatically check and update all components in Large Design Review mode", False))


def speedpak_on_save():
    v = _p().GetString(SPEEDPAK_SAVE, "") or _old("Update out-of-date Speedpak configurations when saving files", "None")
    return v if v in SPEEDPAK_CHOICES else "None"


def envelope_lightweight():
    return _p().GetBool(ENV_LIGHT, False)


def envelope_read_only():
    return _p().GetBool(ENV_READ_ONLY, False)


def mirror_affix():
    """(prefix, suffix) the Mirror Components PM starts its opposite hand file names with."""
    kind = _p().GetString(MIRROR_AFFIX, "Add Prefix")
    text = _p().GetString(MIRROR_TEXT, "Mirror")
    return (text, "") if kind != "Add Suffix" else ("", text)


def virtual_prefix():
    return _p().GetString(VIRTUAL_PREFIX, "Copy of")


def set_move_by_dragging(on):
    _p().SetBool(MOVE_BY_DRAG, bool(on))
    apply_move_by_dragging()


def apply_move_by_dragging():
    """Every open assembly follows the setting."""
    from . import asmcore as ac
    for doc in App.listDocuments().values():
        asm = ac.assembly_of(doc)
        vo = getattr(asm, "ViewObject", None) if asm is not None else None
        if vo is not None and hasattr(vo, "EnableMovement"):
            vo.EnableMovement = move_by_dragging()


def ask_flip():
    """Prompt: the edited mate solves only with its alignment flipped."""
    from PySide import QtWidgets
    import FreeCADGui as Gui
    box = QtWidgets.QMessageBox(Gui.getMainWindow())
    box.setWindowTitle("Mate")
    box.setText("The mate cannot be solved with its current alignment. Change the mate alignment?")
    box.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
    box.setObjectName("FW_MateFlipPrompt")
    return box.exec() == QtWidgets.QMessageBox.Yes


def in_context():
    v = _p().GetString(IN_CONTEXT, "Force assembly transparency")
    return v if v in IN_CONTEXT_CHOICES else "Force assembly transparency"


def in_context_level():
    return max(0, min(100, _p().GetInt(IN_CONTEXT_LEVEL, 75)))


def speedpak_opacity():
    return max(10, min(100, _p().GetInt(SPEEDPAK_OPACITY, 100)))


def display_rows():
    ""

    from .optionspages import Combo, NumberFn
    return [
        Combo(IN_CONTEXT, "Assembly transparency for in context edit", [(c, c) for c in IN_CONTEXT_CHOICES],
              in_context, lambda v: _p().SetString(IN_CONTEXT, v)),
        NumberFn(IN_CONTEXT_LEVEL, "Transparency", "%", 0, 100, in_context_level,
                 lambda v: _p().SetInt(IN_CONTEXT_LEVEL, int(v)),
                 tip="How see-through the rest of the assembly is with Force assembly transparency"),
        NumberFn(SPEEDPAK_OPACITY, "SpeedPak graphics circle opacity", "%", 10, 100, speedpak_opacity,
                 lambda v: _p().SetInt(SPEEDPAK_OPACITY, max(10, min(100, int(v)))),
                 tip="How solid the SpeedPak graphics circle is drawn (10 to 100 %)"),
    ]


def install_display_rows():
    from . import optionspages
    if getattr(optionspages, "_fw_asm_display", False):
        return
    base = optionspages._display

    def _display():
        sections = base()
        try:
            title, rows = sections[0]
            sections[0] = (title, list(rows) + display_rows())
        except Exception as error:
            App.Console.PrintLog("FreeCAD: display options: %s\n" % error)
        return sections
    optionspages._display = _display
    optionspages._fw_asm_display = True


def page():
    ""

    from .optionspages import BoolFn, Combo
    bool_fn = lambda key, default: ((lambda: _p().GetBool(key, default)), (lambda v: _p().SetBool(key, bool(v))))
    return [
        (None, [
            BoolFn(MOVE_BY_DRAG, "Move components by dragging", move_by_dragging, set_move_by_dragging,
                   "Drag an under defined component in the graphics area to move it within its mates"),
            BoolFn(OPTIMIZE_PLACEMENT, "Optimize component placement when adding mates",
                   *bool_fn(OPTIMIZE_PLACEMENT, True),
                   tip="A new mate takes the alignment that moves the components least"),
            BoolFn(MISALIGNED, "Allow creation of misaligned mates", *bool_fn(MISALIGNED, True),
                   tip="A Concentric mate slightly off another one keeps the axes parallel instead of failing"),
            BoolFn(SAVE_EXTERNAL, "Save new components to external files", save_external,
                   lambda v: _p().SetBool(SAVE_EXTERNAL, bool(v)),
                   "New Part in an assembly makes a part file next to the assembly instead of a virtual component"),
            BoolFn(UPDATE_GRAPHICS, "Update model graphics when saving files", update_graphics,
                   lambda v: _p().SetBool(UPDATE_GRAPHICS, bool(v)),
                   "Saving the assembly rebuilds out of date parts first, so their graphics are current"),
            BoolFn(LDR_UPDATE, "Automatically check and update all components in Large Design Review mode", ldr_update,
                   lambda v: _p().SetBool(LDR_UPDATE, bool(v)),
                   "An assembly opened in Large Design Review rebuilds its out of date components"),
        ]),
        (None, [
            _align_combo(Combo),
            Combo(SPEEDPAK_SAVE, "Update out-of-date Speedpak configurations when saving files:",
                  [(c, c) for c in SPEEDPAK_CHOICES], speedpak_on_save, lambda v: _p().SetString(SPEEDPAK_SAVE, v),
                  "When the assembly is saved: None leaves them, All updates them, Prompt asks"),
        ]),
        ("Opening a large assembly", _threshold_rows()),
        ("Large Assembly Settings", _large_rows(BoolFn)),
        ("Envelope Components", [
            BoolFn(ENV_LIGHT, "Automatically load lightweight", envelope_lightweight,
                   lambda v: _p().SetBool(ENV_LIGHT, bool(v)), "Envelope components open lightweight"),
            BoolFn(ENV_READ_ONLY, "Load read-only", envelope_read_only,
                   lambda v: _p().SetBool(ENV_READ_ONLY, bool(v)), "Envelope components' files open read-only"),
        ]),
        ("Prefix / Suffix defaults", [
            ComboText(MIRROR_AFFIX, "Opposite hand mirror components:", MIRROR_AFFIX_CHOICES,
                      lambda: (_p().GetString(MIRROR_AFFIX, "Add Prefix"), _p().GetString(MIRROR_TEXT, "Mirror")),
                      _set_mirror_affix, "How Mirror Components names the opposite hand parts"),
            ComboText(VIRTUAL_PREFIX, "Prefix for virtual components created from external files:", None,
                      lambda: (None, virtual_prefix()), lambda v: _p().SetString(VIRTUAL_PREFIX, v[1]),
                      "Make Virtual names the virtual component with this before the part name"),
        ]),
    ]


def _set_mirror_affix(v):
    _p().SetString(MIRROR_AFFIX, v[0])
    _p().SetString(MIRROR_TEXT, v[1])


def _threshold_rows():
    """Opening a large assembly: a check and the component count each (asmldr's parameters)."""
    from . import asmldr
    p = asmldr._p
    return [
        CheckNumber("FwLightweightWhenOver", "Use Lightweight mode and Large Assembly Settings when the number of components exceeds:",
                    lambda: (asmldr.light_auto(), asmldr.light_limit()),
                    lambda v: (p().SetBool("LightweightWhenOver", bool(v[0])), p().SetInt("LightweightLimit", int(v[1]))),
                    "An assembly opened with more components opens lightweight with Large Assembly Settings"),
        CheckNumber("FwLDRWhenOver", "Use Large Design Review mode when the number of components exceeds:",
                    lambda: (asmldr.ldr_auto(), asmldr.ldr_limit()),
                    lambda v: (p().SetBool("LDRWhenOver", bool(v[0])), p().SetInt("LDRLimit", int(v[1]))),
                    "An assembly opened with more components opens in Large Design Review"),
    ]


def _large_rows(BoolFn):
    """Options > Assemblies, Large Assembly Settings: the settings Large Assembly Settings turns on
    (asmlarge)."""
    from . import asmlarge
    return [BoolFn("FwLarge" + key, text, lambda k=key: asmlarge.setting(k),
                   lambda v, k=key: asmlarge.set_setting(k, v), "On while Large Assembly Settings is on")
            for key, text, _d in asmlarge.SETTINGS]


def _setting_base():
    try:
        from .sketchoptions import Setting
        return Setting
    except Exception:       # no GUI: the page is never built
        return object


class CheckNumber(_setting_base()):
    ""


    def __init__(self, key, text, read, write, tip=""):
        super().__init__("", key, None, text, tip)
        self.read, self.write = read, write

    def widget(self):
        from PySide import QtWidgets
        row = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        self.box = QtWidgets.QCheckBox(self.text)
        self.box.setObjectName("SWCheck_" + self.key)
        self.box.setToolTip(self.tip)
        self.number = QtWidgets.QSpinBox()
        self.number.setObjectName("SWNumber_" + self.key)
        self.number.setRange(1, 1000000)
        self.number.setToolTip(self.tip)
        self.box.toggled.connect(self.number.setVisible)     # extapps83: hidden, not greyed, with the check off
        lay.addWidget(self.box)
        lay.addWidget(self.number)
        lay.addStretch(1)
        return row

    def value(self):
        return (self.box.isChecked(), self.number.value())

    def load(self):
        try:
            on, n = self.read()
        except Exception:
            on, n = False, 500
        self.box.setChecked(bool(on))
        self.number.setValue(int(n))
        self.number.setVisible(bool(on))
        self.loaded = self.value()

    def save(self):
        if self.changed():
            self.write(self.value())
            self.loaded = self.value()


class ComboText(_setting_base()):
    ""


    def __init__(self, key, text, choices, read, write, tip=""):
        super().__init__("", key, None, text, tip)
        self.choices, self.read, self.write = choices, read, write

    def widget(self):
        from PySide import QtWidgets
        row = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QtWidgets.QLabel(self.text))
        line = QtWidgets.QHBoxLayout()
        line.setContentsMargins(20, 0, 0, 0)
        self.combo = None
        if self.choices:
            self.combo = QtWidgets.QComboBox()
            self.combo.setObjectName("SWCombo_" + self.key)
            self.combo.addItems(list(self.choices))
            self.combo.setToolTip(self.tip)
            line.addWidget(self.combo)
        self.box = QtWidgets.QLineEdit()
        self.box.setObjectName("SWText_" + self.key)
        self.box.setToolTip(self.tip)
        self.box.setMinimumWidth(160)
        line.addWidget(self.box)
        line.addStretch(1)
        lay.addLayout(line)
        return row

    def value(self):
        return (self.combo.currentText() if self.combo is not None else None, self.box.text())

    def load(self):
        try:
            choice, text = self.read()
        except Exception:
            choice, text = None, ""
        if self.combo is not None:
            i = self.combo.findText(str(choice))
            self.combo.setCurrentIndex(max(i, 0))
        self.box.setText(text or "")
        self.loaded = self.value()

    def save(self):
        if self.changed():
            self.write(self.value())
            self.loaded = self.value()


def _align_combo(Combo):
    return Combo(ALIGN_ON_EDIT, "Change mate alignments on edit:", [(c, c) for c in ALIGN_CHOICES],
                 align_on_edit, lambda v: _p().SetString(ALIGN_ON_EDIT, v))


# ---------------------------------------------------------------- what the rows do
def _part_docs(asm):
    out = []
    for comp in ac_components(asm):
        d = getattr(getattr(comp, "LinkedObject", None), "Document", None)
        if d is not None and d is not asm.Document and d not in out:
            out.append(d)
    return out


def ac_components(asm):
    from . import asmcore as ac
    return ac.components(asm)


def update_out_of_date(asm):
    """Rebuild each part document with a feature waiting for a rebuild, then the assembly.
    Returns the part documents rebuilt."""
    done = []
    for d in _part_docs(asm):
        try:
            if any("Touched" in o.State for o in d.Objects):
                d.recompute()
                done.append(d)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: update %s: %s\n" % (d.Label, error))
    if done:
        try:
            asm.Document.recompute()
        except Exception as _fw_err:
            _fw_log("asmoptions.py:415", _fw_err)
    return done


def ask_speedpak(count):
    from PySide import QtWidgets
    import FreeCADGui as Gui
    box = QtWidgets.QMessageBox(Gui.getMainWindow())
    box.setObjectName("FW_SpeedpakSavePrompt")
    box.setWindowTitle("Save")
    box.setText("%d SpeedPak configuration%s out of date. Update before saving?" % (count, " is" if count == 1 else "s are"))
    box.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
    return box.exec() == QtWidgets.QMessageBox.Yes


LAST = {"save": None}


def before_save(doc):
    """Saving an assembly: Update model graphics when saving files, and the out of date SpeedPaks
    as Update out-of-date Speedpak configurations when saving files says."""
    from . import asmcore as ac
    asm = ac.assembly_of(doc)
    if asm is None:
        return None
    out = {"graphics": [], "speedpak": []}
    if update_graphics():
        out["graphics"] = [d.Name for d in update_out_of_date(asm)]
    choice = speedpak_on_save()
    if choice != "None":
        from . import asmspeedpak
        stale = asmspeedpak.out_of_date(asm)
        if stale and (choice == "All" or ask_speedpak(len(stale))):
            out["speedpak"] = [c.Name for c in asmspeedpak.update(asm)]
    LAST["save"] = out
    return out


def after_open(doc):
    """An assembly opened: its envelope components lightweight and read-only as the Envelope
    Components rows say."""
    from . import asmcore as ac, asminsert
    asm = ac.assembly_of(doc)
    if asm is None:
        return []
    done = []
    for comp in ac.components(asm):
        if not asminsert.is_envelope(comp):
            continue
        if envelope_lightweight():
            from . import asmcomp
            asmcomp.set_lightweight(comp, True)
        d = getattr(getattr(comp, "LinkedObject", None), "Document", None)
        if envelope_read_only() and d is not None and d is not doc:
            from . import asmrefopts
            asmrefopts.READ_ONLY.add(d.Name)
        done.append(comp.Name)
    return done


class _SaveWatch:
    def slotStartSaveDocument(self, doc, path):
        try:
            before_save(doc)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: assembly save options: %s\n" % error)


_WATCH = []


def install():
    """The Assemblies page's rows that act on save and on open."""
    if _WATCH:
        return
    _WATCH.append(_SaveWatch())
    App.addDocumentObserver(_WATCH[0])
    from . import asmrefopts
    after0 = asmrefopts.after_restore

    def after_restore(doc):
        after0(doc)
        try:
            after_open(doc)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: envelope options: %s\n" % error)
    asmrefopts.after_restore = after_restore
