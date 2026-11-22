"""The slicers' object info box in the bottom right of the plate view: the picked object's name, size,
volume and triangle count (Orca Slicer and Bambu Studio show it under "Object name:")."""
from PySide import QtCore, QtWidgets

from . import style

Qt = QtCore.Qt


class ObjectInfo(QtWidgets.QFrame):
    def __init__(self, bed, host):
        super().__init__(host)
        self.bed, self.host = bed, host
        self.setObjectName("SWSlicerObjectInfo")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        self.label = QtWidgets.QLabel()
        self.label.setTextFormat(Qt.RichText)
        lay.addWidget(self.label)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(600)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        host.installEventFilter(self)
        style.signals.theme_changed.connect(self._restyle)
        self._restyle()
        self.refresh()

    def _restyle(self, *_):
        T = style.T
        self.setStyleSheet("#SWSlicerObjectInfo{background:%s;border:1px solid %s;border-left:4px solid %s;}"
                           "#SWSlicerObjectInfo QLabel{color:%s;background:transparent;}"
                           % (T.hex("pane"), T.hex("line_mid"), T.hex("accent"), T.hex("text")))

    def eventFilter(self, obj, event):
        if obj is self.host and event.type() in (QtCore.QEvent.Resize, QtCore.QEvent.Show):
            self.place()
        return False

    def place(self):
        self.adjustSize()
        self.move(max(0, self.host.width() - self.width() - 12), max(0, self.host.height() - self.height() - 12))
        self.raise_()

    def refresh(self):
        items = self.bed.targets() if self.bed.items else []
        if not items:
            self.hide()
            return
        try:
            if len(items) == 1:
                it = items[0]
                name = it.name
                mesh = self.bed.placed_mesh(items=items)
            else:
                name, mesh = "%d objects" % len(items), self.bed.placed_mesh(items=items)
            box = mesh.BoundBox
            text = ("<b>Object name:</b> %s<br><b>Size:</b> %.1f x %.1f x %.1f mm<br>"
                    "<b>Volume:</b> %.0f mm&sup3;<br><b>Triangles:</b> %d"
                    % (name, box.XLength, box.YLength, box.ZLength, mesh.Volume, mesh.CountFacets))
        except Exception:
            self.hide()
            return
        if text != getattr(self, "_text", None):
            self._text = text
            self.label.setText(text)
        self.show()
        self.place()

    def remove(self):
        self.timer.stop()
        try:
            style.signals.theme_changed.disconnect(self._restyle)
        except Exception:
            pass
        self.host.removeEventFilter(self)
        self.hide()
        self.setParent(None)
        self.deleteLater()
