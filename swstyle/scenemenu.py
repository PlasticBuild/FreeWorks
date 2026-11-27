# SPDX-License-Identifier: LGPL-2.1-or-later
""





import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import paths, style

FAVORITES = "SceneFavorites"
CARD = QtCore.QSize(240, 150)
T_MANAGE = "Manage Favorites..."


def favorites():
    ""
    try:
        text = paths.params().GetString(FAVORITES, "")
    except Exception:
        text = ""
    out = []
    for part in text.split(","):
        try:
            i = int(part)
        except ValueError:
            continue
        if 0 <= i < len(style.SCENES) and i not in out:
            out.append(i)
    return out if text else list(style.SCENE_MENU)


def set_favorites(order):
    paths.params().SetString(FAVORITES, ",".join(str(int(i)) for i in order))


def others():
    fav = favorites()
    return [i for i in tuple(style.SCENE_MENU) + tuple(style.SCENE_EXTRAS) if i not in fav]


def picture(index, size=CARD):
    """The scene drawn as its viewport background (linear or radial gradient, or flat), with a grey
    floor shadow so it reads as a scene."""
    pix = QtGui.QPixmap(size)
    _, (top, mid, bottom), gradient = style.SCENES[index]
    col = lambda v: QtGui.QColor((v >> 24) & 0xFF, (v >> 16) & 0xFF, (v >> 8) & 0xFF)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    rect = QtCore.QRectF(0, 0, size.width(), size.height())
    if index in style.RADIAL_SCENES:
        g = QtGui.QRadialGradient(rect.center(), max(size.width(), size.height()) * 0.7)
        g.setColorAt(0, col(top)); g.setColorAt(0.5, col(mid)); g.setColorAt(1, col(bottom))
        p.fillRect(rect, QtGui.QBrush(g))
    elif gradient:
        g = QtGui.QLinearGradient(0, 0, 0, size.height())
        g.setColorAt(0, col(top)); g.setColorAt(0.5, col(mid)); g.setColorAt(1, col(bottom))
        p.fillRect(rect, QtGui.QBrush(g))
    else:
        p.fillRect(rect, col(top))
    shade = QtGui.QColor(0, 0, 0, 40)
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(shade)
    p.drawEllipse(QtCore.QRectF(size.width() * 0.25, size.height() * 0.72, size.width() * 0.5, size.height() * 0.1))
    p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 60), 1))
    p.setBrush(QtCore.Qt.NoBrush)
    p.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))
    p.end()
    return pix


class PreviewCard(QtWidgets.QFrame):
    """The large card beside the Apply Scene list: the scene's picture and its name."""

    def __init__(self, parent=None):
        super().__init__(parent, QtCore.Qt.ToolTip | QtCore.Qt.FramelessWindowHint)
        self.setObjectName("SWScenePreview")
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        self.image = QtWidgets.QLabel(self)
        self.image.setFixedSize(CARD)
        self.name = QtWidgets.QLabel(self)
        lay.addWidget(self.image)
        lay.addWidget(self.name)
        self.index = None

    def show_scene(self, index, beside):
        """Show scene index next to the rectangle beside (global coordinates)."""
        self.index = index
        self.image.setPixmap(picture(index))
        self.name.setText(style.SCENES[index][0])
        self.adjustSize()
        x, y = beside.right() + 4, beside.top()
        screen = QtGui.QGuiApplication.screenAt(beside.center())
        if screen is not None:
            area = screen.availableGeometry()
            if x + self.width() > area.right():
                x = beside.left() - self.width() - 4
            y = min(y, area.bottom() - self.height())
        self.move(x, y)
        self.show()
        self.raise_()


def fill(menu):
    """Fill the Apply Scene flyout menu; returns it."""
    current = style.current_scene()
    shown = style.shown_scene()
    card = PreviewCard(menu)
    menu.preview_card = card

    def add(text, index):
        act = menu.addAction(text)
        act.setCheckable(True)
        act.setChecked(index == shown if index >= 0 else shown < 0)
        act.setData(index)
        act.triggered.connect(lambda checked=False, i=index: style.apply_scene(i))
        return act
    for i in favorites():
        add(style.SCENES[i][0] + (" (Default)" if i == 0 else ""), i)
    current_other = current if current in others() else None
    if current_other is not None:
        add(style.SCENES[current_other][0], current_other)     # the scene in use, though not a favourite
    menu.addSeparator()
    if style.scene_label(-1) == "Theme Background":
        # only where the theme's own background is not 3 Point Faded (it would be that row twice):

        add("Theme Background", -1)
    manage = menu.addAction(T_MANAGE)
    manage.triggered.connect(lambda checked=False: QtCore.QTimer.singleShot(0, manage_favorites))

    def hovered(act):
        index = act.data()
        if isinstance(index, int) and 0 <= index < len(style.SCENES):
            r = menu.actionGeometry(act)
            top_left = menu.mapToGlobal(QtCore.QPoint(menu.width(), r.top()))
            card.show_scene(index, QtCore.QRect(top_left - QtCore.QPoint(menu.width(), 0),
                                                QtCore.QSize(menu.width(), r.height())))
        else:
            card.hide()
    menu.hovered.connect(hovered)
    menu.aboutToHide.connect(card.hide)
    return menu


class FavoritesDialog(QtWidgets.QDialog):
    """Manage Favorites: which scenes the Apply Scene list shows at the top, and in what order."""

    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWSceneFavorites")
        self.setWindowTitle("Manage Favorites")
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("Scenes at the top of the Apply Scene list:", self))
        self.list = QtWidgets.QListWidget(self)
        self.list.setObjectName("SWSceneFavoritesList")
        self.list.setIconSize(QtCore.QSize(48, 30))
        self.list.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        fav = favorites()
        for i in fav + others():
            item = QtWidgets.QListWidgetItem(QtGui.QIcon(picture(i, QtCore.QSize(48, 30))), style.SCENES[i][0])
            item.setData(QtCore.Qt.UserRole, i)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if i in fav else QtCore.Qt.Unchecked)
            self.list.addItem(item)
        lay.addWidget(self.list)
        row = QtWidgets.QHBoxLayout()
        reset = QtWidgets.QPushButton("Reset", self)
        reset.setObjectName("SWSceneFavoritesReset")
        reset.clicked.connect(self.reset)
        row.addWidget(reset)
        row.addStretch(1)
        box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        row.addWidget(box)
        lay.addLayout(row)
        self.resize(320, 420)

    def chosen(self):
        out = []
        for r in range(self.list.count()):
            item = self.list.item(r)
            if item.checkState() == QtCore.Qt.Checked:
                out.append(int(item.data(QtCore.Qt.UserRole)))
        return out

    def reset(self):
        ""
        items = [self.list.takeItem(0) for _ in range(self.list.count())]
        by_index = {int(item.data(QtCore.Qt.UserRole)): item for item in items}
        order = list(style.SCENE_MENU) + [i for i in by_index if i not in style.SCENE_MENU]
        for i in order:
            item = by_index[i]
            item.setCheckState(QtCore.Qt.Checked if i in style.SCENE_MENU else QtCore.Qt.Unchecked)
            self.list.addItem(item)

    def accept(self):
        set_favorites(self.chosen())
        super().accept()


def manage_favorites():
    box = FavoritesDialog()
    box.exec()
    return box
