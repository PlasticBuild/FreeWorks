# SPDX-License-Identifier: LGPL-2.1-or-later
""









from PySide import QtCore, QtGui, QtSvg, QtWidgets

_DEFS = ('<defs>'
         '<linearGradient id="b" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#5aa0ec"/><stop offset="1" stop-color="#2a73c9"/></linearGradient>'
         '<linearGradient id="y" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffd957"/><stop offset="1" stop-color="#f0a800"/></linearGradient>'
         '<linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#6cc77a"/><stop offset="1" stop-color="#3a9a4a"/></linearGradient>'
         '<linearGradient id="r" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ee6a5c"/><stop offset="1" stop-color="#cc3b2f"/></linearGradient>'
         '</defs>')


def _svg(body):
    return '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">' + _DEFS + body + '</svg>'


SVGS = {
    "information": _svg('<circle cx="24" cy="24" r="20" fill="url(#b)" stroke="#1d5aa3" stroke-width="1.5"/>'
                        '<circle cx="24" cy="14.5" r="3" fill="#fff"/>'
                        '<rect x="21" y="20" width="6" height="16" rx="1.6" fill="#fff"/>'),
    "question": _svg('<circle cx="24" cy="24" r="20" fill="url(#b)" stroke="#1d5aa3" stroke-width="1.5"/>'
                     '<path d="M17.5 18.5 C17.5 13.5 21 11.5 24.5 11.5 C28.5 11.5 31 14 31 17.4 C31 21.5 26.5 22.4 25.6 26.2" '
                     'fill="none" stroke="#fff" stroke-width="4.4" stroke-linecap="round" stroke-linejoin="round"/>'
                     '<circle cx="25.4" cy="34.4" r="3" fill="#fff"/>'),
    "warning": _svg('<path d="M24 4.5 L45 41 Q46 43.5 43 43.5 H5 Q2 43.5 3 41 Z" fill="url(#y)" stroke="#b57d00" stroke-width="1.5" stroke-linejoin="round"/>'
                    '<rect x="21.2" y="16" width="5.6" height="14" rx="1.6" fill="#3d3200"/>'
                    '<circle cx="24" cy="36" r="3" fill="#3d3200"/>'),
    "ok": _svg('<circle cx="24" cy="24" r="20" fill="url(#g)" stroke="#2a7a37" stroke-width="1.5"/>'
               '<path d="M14 25 L21 32 L34.5 16.5" fill="none" stroke="#fff" stroke-width="5.2" stroke-linecap="round" stroke-linejoin="round"/>'),
    "critical": _svg('<circle cx="24" cy="24" r="20" fill="url(#r)" stroke="#9e2016" stroke-width="1.5"/>'
                     '<path d="M16.5 16.5 L31.5 31.5 M31.5 16.5 L16.5 31.5" fill="none" stroke="#fff" stroke-width="5.2" stroke-linecap="round"/>'),
}
KIND = {"Information": "information", "Question": "question", "Warning": "warning", "Critical": "critical"}
_MARK = "fwMsgIcon"
_filter = None
_cache = {}


def pixmap(kind, size=48, ratio=1.0):
    """The picture for 'information' | 'question' | 'warning' | 'critical' | 'ok' at size px (device pixels size*ratio)."""
    kind = {"info": "information"}.get(kind, kind)
    key = (kind, size, ratio)
    pix = _cache.get(key)
    if pix is None:
        side = int(round(size * ratio))
        pix = QtGui.QPixmap(side, side)
        pix.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pix)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        QtSvg.QSvgRenderer(QtCore.QByteArray(SVGS[kind].encode("utf-8"))).render(painter)
        painter.end()
        pix.setDevicePixelRatio(ratio)
        _cache[key] = pix
    return pix


def icon(kind, size=32):
    """A QIcon (16, 24, 32 and 48 px pictures) for a tree row or button; kind as in pixmap(), plus 'ok' (green tick)."""
    kind = {"info": "information"}.get(kind, kind)
    result = QtGui.QIcon()
    for px in (16, 24, 32, 48):
        result.addPixmap(pixmap(kind, px))
    return result


def _kind_of(box):
    icon = box.icon()
    for name, kind in KIND.items():
        if icon == getattr(QtWidgets.QMessageBox, name):
            return kind
    return None


def apply(box):
    """Swaps the stock picture of one QMessageBox; returns True when it changed it."""
    if box.property(_MARK):
        return False
    kind = _kind_of(box)
    if kind is None:
        return False                      # no icon, or a custom icon pixmap: not ours to change
    label = box.findChild(QtWidgets.QLabel, "qt_msgboxex_icon_label")
    if label is None:
        return False
    ratio = box.devicePixelRatioF() if hasattr(box, "devicePixelRatioF") else 1.0
    size = max(32, min(48, label.pixmap().width() // max(1, int(round(ratio))) if label.pixmap() else 48))
    label.setPixmap(pixmap(kind, size, ratio))
    box.setProperty(_MARK, True)
    return True


class _Filter(QtCore.QObject):
    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Show and isinstance(obj, QtWidgets.QMessageBox):
            try:
                apply(obj)
            except Exception:
                pass
        return False


def install():
    global _filter
    app = QtWidgets.QApplication.instance()
    if app is None or _filter is not None:
        return False
    _filter = _Filter(app)
    app.installEventFilter(_filter)
    try:                                   # the filter goes before FreeCAD tears the application down (exit crashes, review 1119)
        from . import teardown
        teardown.on_quit(uninstall)
    except Exception:
        pass
    return True


def uninstall():
    global _filter
    app = QtWidgets.QApplication.instance()
    if app is not None and _filter is not None:
        app.removeEventFilter(_filter)
    _filter = None
    _cache.clear()
