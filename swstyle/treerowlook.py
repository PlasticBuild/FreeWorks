# SPDX-License-Identifier: LGPL-2.1-or-later
""





try:
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:      # pragma: no cover
    QtWidgets = None

TAIL = 4


class RowDelegate(QtWidgets.QStyledItemDelegate if QtWidgets is not None else object):

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.state &= ~QtWidgets.QStyle.State_HasFocus

    def paint(self, painter, option, index):
        opt = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        if not opt.state & QtWidgets.QStyle.State_Selected:
            view = opt.widget
            style = view.style() if view is not None else QtWidgets.QApplication.style()
            style.drawControl(QtWidgets.QStyle.CE_ItemViewItem, opt, painter, view)
            return
        try:
            view = opt.widget
            style = view.style() if view is not None else QtWidgets.QApplication.style()
            text = style.subElementRect(QtWidgets.QStyle.SE_ItemViewItemText, opt, view)
            right = min(opt.rect.right(), text.left() + opt.fontMetrics.horizontalAdvance(opt.text) + TAIL)
            fill = QtCore.QRect(opt.rect.left(), opt.rect.top(), max(0, right - opt.rect.left() + 1), opt.rect.height())
            group = QtGui.QPalette.Active if opt.state & QtWidgets.QStyle.State_Active else QtGui.QPalette.Inactive
            painter.fillRect(fill, opt.palette.brush(group, QtGui.QPalette.Highlight))
            ink = opt.palette.color(group, QtGui.QPalette.HighlightedText)
            opt.state &= ~QtWidgets.QStyle.State_Selected
            opt.state &= ~QtWidgets.QStyle.State_MouseOver
            opt.palette.setColor(QtGui.QPalette.Text, ink)
            style.drawControl(QtWidgets.QStyle.CE_ItemViewItem, opt, painter, view)
        except Exception:
            super().paint(painter, option, index)
