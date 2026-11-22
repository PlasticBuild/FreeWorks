# SPDX-License-Identifier: LGPL-2.1-or-later
""









import FreeCADGui as Gui
from PySide import QtWidgets

from . import paths, style

THEME_LABELS = (("Light", "Light"), ("Medium Light", "Medium Light"), ("Medium", "Medium"), ("Dark", "Dark"),
                ("AMOLED", "AMOLED (pure black)"))      # themes-medium-1120
SCENE_OWN = "The theme's own"
PREF_PATH = "Mod/FreeWorks"
_registered = False


def _live_shell():
    try:
        from . import shell
        s = shell.shell()
    except Exception:
        return None
    return s if s is not None and s.enabled else None


class LookPage:
    ""


    def __init__(self):
        from . import viewselector, whatswrong
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("FreeCAD")
        lay = QtWidgets.QVBoxLayout(self.form)
        colours = QtWidgets.QGroupBox("Colors")
        form = QtWidgets.QFormLayout(colours)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldsStayAtSizeHint)
        self.theme = QtWidgets.QComboBox()
        self.theme.setObjectName("SWThemeBox")
        self.theme.setMinimumWidth(180)
        for key, label in THEME_LABELS:
            self.theme.addItem(label, key)
        self.theme.setToolTip("Light: a light grey interface. Dark: dark greys "
                              "with light text and a dark 3D view. AMOLED: pure black panes and a black 3D "
                              "view for OLED screens. FreeCAD's own panels change with it")
        form.addRow("Background:", self.theme)
        self.scene = QtWidgets.QComboBox()
        self.scene.setObjectName("SWSceneBox")
        self.scene.setMinimumWidth(180)
        self.scene.addItem(SCENE_OWN, -1)
        for i, (name, _colours, _gradient) in enumerate(style.SCENES):
            self.scene.addItem(name, i)
        self.scene.setToolTip("The 3D view's background. The theme's own is a light blue-grey gradient for "
                              "Light, a dark grey gradient for Dark and black for AMOLED; the others are the "
                              "Apply Scene choices (3 Point Faded, the light gradient, is the first). The sketch colours "
                              "follow the scene")
        form.addRow("Viewport scene:", self.scene)
        lay.addWidget(colours)
        general = QtWidgets.QGroupBox("General")
        inner = QtWidgets.QVBoxLayout(general)
        self.errors = QtWidgets.QCheckBox("Show errors every rebuild")
        self.errors.setObjectName("SWErrorsEveryRebuildBox")
        self.errors.setToolTip("Opens What's Wrong after a rebuild (Ctrl+B, Ctrl+Q, the traffic light) that "
                               "left a feature with an error")
        self.selector = QtWidgets.QCheckBox("View Selector with the Orientation box (Space)")
        self.selector.setObjectName("SWViewSelectorBox")
        self.selector.setToolTip("Space draws the clickable box around the model along with the Orientation "
                                 "box; off, Space shows the Orientation box alone. The box's own button "
                                 "switches it too")
        inner.addWidget(self.errors)
        inner.addWidget(self.selector)
        lay.addWidget(general)
        lay.addStretch(1)
        self._keys = (whatswrong.SETTING, viewselector.SETTING)
        for widget, entry in ((self.theme, style.THEME_SETTING), (self.scene, style.SCENE_SETTING),
                              (self.errors, whatswrong.SETTING), (self.selector, viewselector.SETTING)):
            # FreeCAD's Reset button removes the parameters these name
            widget.setProperty("prefPath", PREF_PATH)
            widget.setProperty("prefEntry", entry)
        self.loaded = None

    def _values(self):
        return (self.theme.currentData(), self.scene.currentData(),
                self.errors.isChecked(), self.selector.isChecked())

    def loadSettings(self):
        from . import viewselector, whatswrong
        self.theme.setCurrentIndex(max(0, self.theme.findData(style.theme_name())))
        try:
            scene = paths.params().GetInt(style.SCENE_SETTING, -1)
        except Exception:
            scene = -1
        self.scene.setCurrentIndex(max(0, self.scene.findData(scene)))
        self.errors.setChecked(whatswrong.show_every_rebuild())
        self.selector.setChecked(viewselector.enabled())
        self.loaded = self._values()

    def saveSettings(self):
        if self.loaded is None:
            return
        from . import viewselector
        theme, scene, errors, selector = self._values()
        params = paths.params()
        if errors != self.loaded[2]:
            params.SetBool(self._keys[0], bool(errors))
        if selector != self.loaded[3]:
            viewselector.set_enabled(selector)
        if (theme, scene) != self.loaded[:2]:
            if _live_shell() is not None:
                style.set_theme(theme, scene)
            else:
                # the classic interface is up: kept for the next time the look is switched on
                params.SetString(style.THEME_SETTING, theme)
                params.SetInt(style.SCENE_SETTING, int(scene))
        self.loaded = self._values()


def register():
    ""

    global _registered
    Gui.addPreferencePage(LookPage, "Display")
    _registered = True
