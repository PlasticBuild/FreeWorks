# -*- coding: utf-8 -*-
""


import csv
import os
import tempfile

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:  # pragma: no cover
    Gui = None

_FW_SEEN = set()


def _fw_log(site, err):
    key = (site, type(err).__name__)
    if key in _FW_SEEN:
        return
    _FW_SEEN.add(key)
    try:
        App.Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        pass


def _view(a):
    return Gui.getDocument(a.Document.Name).ActiveView


def _size():
    try:
        from . import simxpress as sx
        host = sx._host()
        if host is not None:
            return max(200, host.width()), max(150, host.height())
    except Exception as _fw_err:
        _fw_log("simresults.py:size", _fw_err)
    return 1200, 800


def save_view(a, path):
    """The graphics area as it is now (the shown plot, its legend and title drawn in) into an image file."""
    from . import simxpress as sx
    host = sx._host()
    if host is not None:                       # the overlays (legend, title, callouts) are widgets: grab them too
        img = host.grab().toImage()
        if not img.isNull() and img.save(path):
            return path
    w, h = _size()
    _view(a).saveImage(path, w, h, "Current")
    return path


def _plot_image(a):
    path = os.path.join(tempfile.gettempdir(), "fw-sim-view.png")
    save_view(a, path)
    return QtGui.QImage(path)


def copy_view(a):
    """Copy: the plot as a picture on the clipboard (paste into a document)."""
    img = _plot_image(a)
    QtWidgets.QApplication.clipboard().setImage(img)
    Gui.getMainWindow().statusBar().showMessage("The plot is on the clipboard.", 5000)
    return not img.isNull()


def save_as(a, name, path=None):
    """Save As...: the plot as a picture (PNG, JPEG or BMP)."""
    if path is None:
        start = os.path.join(os.path.dirname(a.Document.FileName or "") or os.path.expanduser("~"),
                             "%s-%s-%s.png" % (a.Document.Label, a.Label, name))
        path, _f = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Save As", start,
                                                         "PNG (*.png);;JPEG (*.jpg);;Bitmap (*.bmp)")
        if not path:
            return None
    save_view(a, path)
    Gui.getMainWindow().statusBar().showMessage("Saved %s" % os.path.basename(path), 6000)
    return path


def print_support():
    """Qt's printing module (FreeCAD's PySide shim does not always carry it), or None."""
    for name in ("PySide", "PySide6", "PySide2"):
        try:
            return __import__(name + ".QtPrintSupport", fromlist=["QtPrintSupport"])
        except Exception:
            continue
    return None


def print_view(a, printer=None):
    """Print...: the plot, fitted to the page."""
    QtPrintSupport = print_support()
    if QtPrintSupport is None:
        raise RuntimeError("Printing is not available in this FreeCAD.")
    img = _plot_image(a)
    if printer is None:
        printer = QtPrintSupport.QPrinter()
        dlg = QtPrintSupport.QPrintDialog(printer, Gui.getMainWindow())
        dlg.setWindowTitle("Print")
        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return False
    p = QtGui.QPainter(printer)
    try:
        page = p.viewport()
        size = img.size()
        size.scale(page.size(), QtCore.Qt.KeepAspectRatio)
        p.setViewport(page.x(), page.y(), size.width(), size.height())
        p.setWindow(img.rect())
        p.drawImage(0, 0, img)
    finally:
        p.end()
    return True


def save_all(a, folder=None):
    """Save All Plots as JPEG Files: each plot of the study shown in turn and saved as <model>-<study>-<plot>.jpg."""
    from . import simplots
    if folder is None:
        start = os.path.dirname(a.Document.FileName or "") or os.path.expanduser("~")
        folder = QtWidgets.QFileDialog.getExistingDirectory(Gui.getMainWindow(), "Save All Plots as JPEG Files", start)
        if not folder:
            return []
    was = simplots.SHOWN.get("name") if simplots.SHOWN.get("a") is a else None
    saved = []
    try:
        for p in simplots.plots(a):
            simplots.show(a, p["name"])
            QtWidgets.QApplication.processEvents()
            path = os.path.join(folder, "%s-%s-%s.jpg" % (a.Document.Label, a.Label, p["name"]))
            save_view(a, path)
            saved.append(path)
    finally:
        if was:
            simplots.show(a, was)
        else:
            simplots.clear()
    Gui.getMainWindow().statusBar().showMessage("%d plots saved in %s" % (len(saved), folder), 8000)
    return saved


if Gui is not None:
    class SolverMessages(QtWidgets.QDialog):
        """Results > Solver Messages...: what the last run of the study said, solver lines included."""

        def __init__(self, a, text):
            super().__init__(Gui.getMainWindow())
            self.setObjectName("SWSimSolverMessages")
            self.setWindowTitle("Solver Messages")
            lay = QtWidgets.QVBoxLayout(self)
            self.text = QtWidgets.QPlainTextEdit(text)
            self.text.setObjectName("SWSimSolverMessagesText")
            self.text.setReadOnly(True)
            lay.addWidget(self.text, 1)
            box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok)
            box.accepted.connect(self.accept)
            lay.addWidget(box)
            self.resize(560, 380)

    def solver_messages(a):
        """The last run's messages; a study solved before this session shows CalculiX's own .sta/.dat text."""
        from . import simrun
        text = simrun.messages(a)
        if not text:
            for o in getattr(a, "Group", []) or []:
                t = getattr(o, "Text", None)
                if isinstance(t, str) and t.strip() and ("S T E P" in t or "STEP" in t):
                    text = t
                    break
        dlg = SolverMessages(a, text or "%s has no solver messages yet: run the study first." % a.Label)
        dlg.show()
        return dlg

    class ListResults(QtWidgets.QDialog):
        """Results > List Stress, Displacement, Strain...: every node's value of a quantity, sorted, with Save."""

        def __init__(self, a):
            super().__init__(Gui.getMainWindow())
            from . import simplots
            self.a = a
            self.setObjectName("SWSimListResults")
            self.setWindowTitle("List Results")
            lay = QtWidgets.QVBoxLayout(self)
            form = QtWidgets.QFormLayout()
            self.quantity = QtWidgets.QComboBox()
            self.quantity.setObjectName("SWSimListQuantity")
            self.quantity.addItems([q for q in ("Stress", "Displacement", "Strain") if q in simplots.COMPONENTS])
            self.comp = QtWidgets.QComboBox()
            self.comp.setObjectName("SWSimListComponent")
            self.unit = QtWidgets.QComboBox()
            self.unit.setObjectName("SWSimListUnit")
            form.addRow("Quantity:", self.quantity)
            form.addRow("Component:", self.comp)
            self.unit_label = QtWidgets.QLabel("Units:")
            form.addRow(self.unit_label, self.unit)
            lay.addLayout(form)
            self.table = QtWidgets.QTableWidget(0, 5)
            self.table.setObjectName("SWSimListTable")
            self.table.setHorizontalHeaderLabels(["Node", "Value", "X (mm)", "Y (mm)", "Z (mm)"])
            self.table.verticalHeader().hide()
            self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            lay.addWidget(self.table, 1)
            self.summary = QtWidgets.QLabel("")
            self.summary.setObjectName("SWSimListSummary")
            lay.addWidget(self.summary)
            row = QtWidgets.QHBoxLayout()
            self.save = QtWidgets.QPushButton("Save")
            self.save.setObjectName("SWSimListSave")
            close = QtWidgets.QPushButton("Close")
            row.addStretch(1)
            row.addWidget(self.save)
            row.addWidget(close)
            lay.addLayout(row)
            close.clicked.connect(self.accept)
            self.save.clicked.connect(lambda: self.save_rows())
            self.quantity.currentIndexChanged.connect(lambda *_: self._fill_combos())
            self.comp.currentIndexChanged.connect(lambda *_: self.refresh())
            self.unit.currentIndexChanged.connect(lambda *_: self.refresh())
            self._fill_combos()
            self.resize(560, 520)

        def _fill_combos(self):
            from . import simplots
            q = self.quantity.currentText()
            for w in (self.comp, self.unit):
                w.blockSignals(True)
                w.clear()
            self.comp.addItems([label for _k, label in simplots.COMPONENTS[q]])
            first = simplots.DEFAULT_COMP.get(q)
            keys = [k for k, _l in simplots.COMPONENTS[q]]
            if first in keys:
                self.comp.setCurrentIndex(keys.index(first))
            units = list(simplots.UNITS.get(q, ()))
            self.unit.addItems(units)
            if q == "Displacement" and "mm" in units:
                self.unit.setCurrentText("mm")
            one = self.unit.count() < 2                 # no one-entry combo (strain has no unit)
            self.unit.setVisible(not one)
            self.unit_label.setVisible(not one)
            for w in (self.comp, self.unit):
                w.blockSignals(False)
            self.refresh()

        def plot(self):
            from . import simplots
            q = self.quantity.currentText()
            comp = simplots.COMPONENTS[q][max(0, self.comp.currentIndex())][0]
            p = {"name": "List", "quantity": q, "comp": comp}
            if self.unit.count():
                p["unit"] = self.unit.currentText()
            return p

        def rows(self):
            """[(node, value, x, y, z)] sorted by node number."""
            from . import simplots
            s = simplots.summary(self.a, self.plot())
            mesh = s["res"].Mesh.FemMesh
            out = []
            for n, v in sorted(s["values"]):
                q = mesh.getNodeById(n)
                out.append((n, v, q.x, q.y, q.z))
            return out, s

        def refresh(self):
            from . import simplots
            try:
                rows, s = self.rows()
            except Exception as error:
                self.table.setRowCount(0)
                self.summary.setText(str(error))
                return
            chart = dict(simplots.CHART)
            self.table.setUpdatesEnabled(False)
            self.table.setRowCount(len(rows))
            for i, r in enumerate(rows):
                for j, v in enumerate(r):
                    text = "%d" % v if j == 0 else (simplots.fmt(v, chart) if j == 1 else "%.3f" % v)
                    self.table.setItem(i, j, QtWidgets.QTableWidgetItem(text))
            self.table.setUpdatesEnabled(True)
            unit = self.unit.currentText() if not self.unit.isHidden() else ""
            self.table.setHorizontalHeaderItem(1, QtWidgets.QTableWidgetItem(("Value (%s)" % unit) if unit else "Value"))
            self.summary.setText("Min: %s (node %d)    Max: %s (node %d)    Nodes: %d"
                                 % (simplots.fmt(s["min"], chart), s["min_node"], simplots.fmt(s["max"], chart),
                                    s["max_node"], len(rows)))

        def save_rows(self, path=None):
            if path is None:
                start = os.path.join(os.path.dirname(self.a.Document.FileName or "") or os.path.expanduser("~"),
                                     "%s-%s.csv" % (self.a.Label, self.quantity.currentText()))
                path, _f = QtWidgets.QFileDialog.getSaveFileName(self, "Save", start, "CSV (*.csv)")
                if not path:
                    return None
            rows, _s = self.rows()
            with open(path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow([self.table.horizontalHeaderItem(j).text() for j in range(5)])
                w.writerows(rows)
            return path

    def list_results(a):
        dlg = ListResults(a)
        dlg.show()
        return dlg
