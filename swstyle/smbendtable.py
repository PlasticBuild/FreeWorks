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

import ast
import csv
import json
import math
import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import naming, paths

NEW_COMMAND = "SWStyle_SMBendTableNew"
FILE_COMMAND = "SWStyle_SMBendTableFile"
LABEL = "Bend Table"
TYPES = ("Bend Allowance", "Bend Deduction", "K-Factor")
CALCULATION = "Bend Calculation"
SAMPLE_CALC = "Bend Calculation Sample.csv"
UNITS = (("Millimeters", 1.0), ("Centimeters", 10.0), ("Meters", 1000.0), ("Inches", 25.4), ("Feet", 304.8))
DEFAULT_UNITS = "Inches"
FOLDER = "Sheetmetal Bend Tables"
GROUP = "Bend Table"
ANGLES = tuple(range(15, 181, 15))
NO_XLS = ("Old Excel .xls files cannot be read here. Save the table as .xlsx (Excel Workbook) or .csv "
          "and open that.")


def scale(units):
    return dict(UNITS).get(units, 1.0)


# ================================================================ bend math
def ossb(angle, radius, thickness):
    ""

    a = math.radians(angle)
    if angle <= 90.0 + 1e-9:
        return (radius + thickness) * math.tan(a / 2)
    return radius + thickness


def allowance_from_k(k, angle, radius, thickness):
    return math.radians(angle) * (radius + k * thickness)


def k_from_allowance(ba, angle, radius, thickness):
    a = math.radians(angle)
    if a <= 0 or thickness <= 0:
        return 0.5
    return (ba / a - radius) / thickness


def deduction_from_allowance(ba, angle, radius, thickness):
    return 2 * ossb(angle, radius, thickness) - ba


def allowance_from_deduction(bd, angle, radius, thickness):
    return 2 * ossb(angle, radius, thickness) - bd


def k_of_value(kind, value, angle, radius, thickness):
    """The K-Factor a value of the given kind gives for one bend (lengths in mm)."""
    if kind == "K-Factor":
        return float(value)
    if kind == "Bend Allowance":
        return k_from_allowance(value, angle, radius, thickness)
    return k_from_allowance(allowance_from_deduction(value, angle, radius, thickness), angle, radius, thickness)


# ================================================================ tables
def starter(kind, units, k=0.5):
    """A starter table: three thicknesses, four radii, angles 15 to 180, from a K-Factor."""
    s = scale(units)
    if units in ("Inches", "Feet"):
        thicknesses = [round(x / s, 4) for x in (0.762, 1.524, 3.048)]       # 0.03, 0.06, 0.12 in
    else:
        thicknesses = [round(x / s, 4) for x in (1.0, 2.0, 3.0)]
    blocks = []
    for t in thicknesses:
        radii = [round(t * f, 4) for f in (0.5, 1.0, 2.0, 3.0)]
        rows = []
        for r in radii:
            row = [r]
            for a in ANGLES:
                tm, rm = t * s, r * s
                ba = allowance_from_k(k, a, rm, tm)
                if kind == "K-Factor":
                    v = k
                elif kind == "Bend Allowance":
                    v = ba / s
                else:
                    v = deduction_from_allowance(ba, a, rm, tm) / s
                row.append(round(v, 4))
            rows.append(row)
        blocks.append({"thickness": t, "angles": list(ANGLES), "rows": rows})
    return {"type": kind, "units": units, "blocks": blocks}


def starter_calculation(units="Millimeters", k=0.44):
    """A starter Bend Calculation table: the allowance a K-Factor gives, for 0 to 180 degrees."""
    return {"type": CALCULATION, "units": units,
            "ranges": [[0, 180, "radians(A) * (R + %g * T)" % k]]}


_FUNCS = {"sin": lambda x: math.sin(x), "cos": lambda x: math.cos(x), "tan": lambda x: math.tan(x),
          "sqrt": lambda x: math.sqrt(x), "radians": lambda x: math.radians(x)}


def _evaluate(expr, t, r, a):
    """The value of a Bend Calculation equation (only arithmetic, T R A, pi and a few functions)."""
    try:
        tree = ast.parse(expr.replace("^", "**"), mode="eval")
    except SyntaxError:
        raise ValueError("The equation '%s' cannot be read." % expr)
    names = {"T": t, "R": r, "A": a, "pi": math.pi}

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if isinstance(n, ast.Name) and n.id in names:
            return names[n.id]
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            v = ev(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
            x, y = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Pow) and abs(y) > 10:
                raise ValueError("The equation '%s' has too large a power." % expr)
            if isinstance(n.op, ast.Div) and y == 0:
                raise ValueError("The equation '%s' divides by zero." % expr)
            return {ast.Add: lambda: x + y, ast.Sub: lambda: x - y, ast.Mult: lambda: x * y,
                    ast.Div: lambda: x / y, ast.Pow: lambda: x ** y}[type(n.op)]()
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS and len(n.args) == 1:
            return _FUNCS[n.func.id](ev(n.args[0]))
        raise ValueError("The equation '%s' may only use numbers, T, R, A, pi, + - * / ** and sin, cos, tan, "
                         "sqrt, radians." % expr)
    return ev(tree)


def to_rows(table):
    out = [["Bend table"], ["Type:", table["type"]], ["Units:", table["units"]]]
    if table["type"] == CALCULATION:
        out.append(["Angle from", "Angle to", "Equation"])
        out.extend(list(r) for r in table["ranges"])
        return out
    for b in table["blocks"]:
        out.append([])
        out.append(["Thickness:", b["thickness"]])
        out.append(["Radius"] + list(b["angles"]))
        out.extend(list(r) for r in b["rows"])
    return out


def _num(x):
    try:
        return float(str(x).strip())
    except (TypeError, ValueError):
        return None


def from_rows(rows):
    """Parses the table layout (rows of cells, strings or numbers). Raises ValueError when it is not one."""
    kind, units, blocks, block = None, None, [], None
    for row in rows:
        cells = [c for c in row]
        while cells and str(cells[-1]).strip() == "":
            cells.pop()
        if not cells:
            continue
        head = str(cells[0]).strip().lower().rstrip(":")
        if head == "type" and len(cells) > 1:
            kind = next((t for t in TYPES + (CALCULATION,) if t.lower() == str(cells[1]).strip().lower()), None)
            continue
        if kind == CALCULATION:
            if head.startswith("angle"):
                continue
            a0, a1 = _num(cells[0]), _num(cells[1]) if len(cells) > 1 else None
            if a0 is not None and a1 is not None and len(cells) > 2 and str(cells[2]).strip():
                expr = str(cells[2]).strip()
                _evaluate(expr, 1.0, 1.0, 90.0)          # raises ValueError for a bad equation
                blocks.append([a0, a1, expr])
            continue
        if head == "units" and len(cells) > 1:
            units = next((u for u, _s in UNITS if u.lower() == str(cells[1]).strip().lower()), None)
            continue
        if head == "thickness" and len(cells) > 1:
            block = {"thickness": _num(cells[1]), "angles": [], "rows": []}
            blocks.append(block)
            continue
        if head == "radius" and block is not None:
            block["angles"] = [_num(c) for c in cells[1:]]
            continue
        first = _num(cells[0])
        if first is not None and block is not None and block["angles"]:
            block["rows"].append([first] + [_num(c) for c in cells[1:len(block["angles"]) + 1]])
    if kind is None:
        raise ValueError("The file is not a bend table: no 'Type:' row (Bend Allowance, Bend Deduction, K-Factor "
                         "or Bend Calculation).")
    if kind == CALCULATION:
        if not blocks:
            raise ValueError("The bend calculation table has no Angle from / Angle to / Equation rows.")
        return {"type": kind, "units": units or "Millimeters", "ranges": blocks}
    if not blocks or not all(b["thickness"] and b["angles"] and b["rows"] for b in blocks):
        raise ValueError("The bend table has no complete Thickness block (Radius row and values).")
    return {"type": kind, "units": units or "Millimeters", "blocks": blocks}


def write_file(path, table):
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    with open(path, "w", newline="") as f:
        csv.writer(f).writerows(to_rows(table))


def read_file(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xls":
        raise ValueError(NO_XLS)
    if ext == ".xlsx":
        return from_rows(_xlsx_rows(path))
    with open(path, newline="") as f:
        return from_rows(list(csv.reader(f)))


def _xlsx_rows(path):
    """Cell values of an .xlsx file's first sheet, read with FreeCAD's own importer."""
    import importXLSX
    try:
        doc = App.newDocument("SWBendTableRead", hidden=True, temp=True)
    except TypeError:
        doc = App.newDocument("SWBendTableRead")
    try:
        importXLSX.insert(path, doc.Name)
        sheet = next(o for o in doc.Objects if o.TypeId == "Spreadsheet::Sheet")
        return sheet_rows(sheet)
    finally:
        App.closeDocument(doc.Name)


def _col(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def sheet_rows(sheet):
    used = sheet.getUsedCells() if hasattr(sheet, "getUsedCells") else []
    import re
    last_r = last_c = 0
    for cell in used:
        m = re.match(r"([A-Z]+)(\d+)", cell)
        col = 0
        for ch in m.group(1):
            col = col * 26 + ord(ch) - 64
        last_r, last_c = max(last_r, int(m.group(2))), max(last_c, col)
    rows = []
    for r in range(1, last_r + 1):
        row = []
        for c in range(1, last_c + 1):
            try:
                v = sheet.get("%s%d" % (_col(c), r))
            except Exception:
                v = ""
            row.append(v if v is not None else "")
        rows.append(row)
    return rows


def fill_sheet(sheet, table):
    sheet.clearAll()
    for r, row in enumerate(to_rows(table), 1):
        for c, v in enumerate(row, 1):
            text = str(v)
            if isinstance(v, str) and (_num(v) is not None or v[:1] in "=(-+"):
                text = "'" + text           # kept as text (a number or an equation)
            sheet.set("%s%d" % (_col(c), r), text)
    sheet.setStyle("A1", "bold")
    sheet.recompute()


def _interp(xs, ys, x):
    pts = sorted(zip(xs, ys))
    if x <= pts[0][0]:
        (x0, y0), (x1, y1) = pts[0], pts[min(1, len(pts) - 1)]
    elif x >= pts[-1][0]:
        (x0, y0), (x1, y1) = pts[max(0, len(pts) - 2)], pts[-1]
    else:
        i = next(i for i in range(1, len(pts)) if pts[i][0] >= x)
        (x0, y0), (x1, y1) = pts[i - 1], pts[i]
    if abs(x1 - x0) < 1e-12:
        return y0
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def lookup(table, thickness, radius, angle):
    """The table's value (its type, its units) for a bend; thickness and radius in mm, angle in degrees."""
    s = scale(table["units"])
    if table["type"] == CALCULATION:
        rng = next((x for x in table["ranges"] if x[0] - 1e-9 <= angle <= x[1] + 1e-9), None)
        if rng is None:
            raise ValueError("The bend calculation table has no equation for %g degrees." % round(angle, 3))
        return _evaluate(rng[2], thickness / s, radius / s, angle)
    t = thickness / s
    block = next((b for b in table["blocks"] if abs(b["thickness"] - t) <= 1e-4 * max(1.0, t)), None)
    if block is None:
        raise ValueError("The bend table has no thickness %g %s." % (round(t, 4), table["units"].lower()))
    r = radius / s
    by_angle = [_interp([row[0] for row in block["rows"]], [row[k + 1] for row in block["rows"]], r)
                for k in range(len(block["angles"]))]
    return _interp(block["angles"], by_angle, angle)


# ================================================================ feature
class BendTable:
    """A Bend Table in the part: its spreadsheet holds the table."""

    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyLink", "Sheet", GROUP, "The table's spreadsheet")
        add("App::PropertyString", "FileName", GROUP, "The file the table came from or was written to")
        add("App::PropertyString", "TableType", GROUP, "Bend Allowance, Bend Deduction or K-Factor")
        add("App::PropertyString", "Units", GROUP, "Units of the table")
        add("App::PropertyString", "Table", GROUP, "The parsed table (JSON)")
        add("App::PropertyString", "Problem", GROUP, "Why the spreadsheet is not a bend table")
        for name in ("Table", "Problem"):
            obj.setEditorMode(name, 2)
        for name in ("TableType", "Units"):
            obj.setEditorMode(name, 1)
        obj.Proxy = self

    def execute(self, obj):
        if obj.Sheet is None:
            return
        try:
            table = from_rows(sheet_rows(obj.Sheet))
            obj.Table = json.dumps(table)
            obj.TableType, obj.Units, obj.Problem = table["type"], table["units"], ""
        except ValueError as e:
            obj.Problem = str(e)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderBendTable:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def getIcon(self):
        try:
            import SheetMetalTools
            return os.path.join(SheetMetalTools.icons_path, "SheetMetal_AddBase.svg")
        except Exception:
            return ""

    def claimChildren(self):
        return [self.Object.Sheet] if self.Object.Sheet is not None else []

    def doubleClicked(self, vobj):
        sheet = vobj.Object.Sheet
        if sheet is not None:
            sheet.ViewObject.doubleClicked()
        return True

    def onDelete(self, vobj, subelements):
        sheet = vobj.Object.Sheet
        if sheet is not None:
            try:
                vobj.Object.Document.removeObject(sheet.Name)
            except Exception as _fw_err:
                _fw_log("smbendtable.py:430", _fw_err)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_bend_table(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "BendTable"


def tables(doc):
    return [o for o in doc.Objects if is_bend_table(o)]


def table_of(obj):
    try:
        return json.loads(obj.Table) if obj.Table else None
    except Exception:
        return None


def add(doc, table, path):
    doc.openTransaction(LABEL)
    try:
        obj = doc.addObject("App::FeaturePython", "BendTable")
        BendTable(obj)
        if App.GuiUp:
            ViewProviderBendTable(obj.ViewObject)
        sheet = doc.addObject("Spreadsheet::Sheet", "BendTableSheet")
        fill_sheet(sheet, table)
        obj.Sheet = sheet
        obj.FileName = path
        obj.Label = naming.next_label(doc, LABEL)
        sheet.Label = obj.Label + " Sheet"
        obj.recompute()
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    doc.recompute()
    return obj


def default_path(doc):
    """BendTable<n>.csv in the user's Sheetmetal Bend Tables folder, not yet taken."""
    folder = os.path.join(App.getUserAppDataDir(), FOLDER)
    n = 1
    while os.path.exists(os.path.join(folder, "BendTable%d.csv" % n)):
        n += 1
    return os.path.join(folder, "BendTable%d.csv" % n)


# ================================================================ allowance on the part
def bend_angles(shape):
    """Each bend's angle in degrees (the arcs of the cylindrical faces, inside ones)."""
    out = []
    for f in shape.Faces:
        if f.Surface.TypeId != "Part::GeomCylinder":
            continue
        u0, u1, _v0, _v1 = f.ParameterRange
        out.append((round(math.degrees(u1 - u0), 3), f.Surface.Radius))
    return out


def main_angle(shape):
    angles = [a for a, _r in bend_angles(shape)]
    if not angles:
        return 90.0
    return max(set(angles), key=angles.count)


def k_of(base, shape=None):
    """The K-Factor the flat pattern uses for the part whose first feature is base."""
    if base is None:
        return 0.5
    kind = getattr(base, "SWBendAllowanceType", "K-Factor")
    k = float(getattr(base, "SWKFactor", 0.5))
    if kind not in ("Bend Table", "Bend Allowance", "Bend Deduction", CALCULATION):
        return k
    t = float(getattr(base, "Thickness", 1.0))
    r = float(getattr(base, "Radius", 1.0))
    t = t.Value if hasattr(t, "Value") else t
    r = r.Value if hasattr(r, "Value") else r
    angle = main_angle(shape) if shape is not None else 90.0
    if kind == "Bend Allowance":
        return k_from_allowance(float(base.SWBendAllowance), angle, r, t)
    if kind == "Bend Deduction":
        return k_of_value("Bend Deduction", float(base.SWBendDeduction), angle, r, t)
    obj = base.Document.getObject(getattr(base, "SWBendTable", "") or "")
    table = table_of(obj) if obj is not None else None
    if table is None:
        raise ValueError("The sheet metal part's bend table is missing.")
    if (table["type"] == CALCULATION) != (kind == CALCULATION):
        raise ValueError("Pick a %s table." % ("bend calculation" if kind == CALCULATION else "bend"))
    return k_from_table(table, t, r, angle)


def k_from_table(table, t, r, angle):
    """The K-Factor a bend table or bend calculation table gives for one bend (mm, degrees)."""
    value = lookup(table, t, r, angle)
    if table["type"] != "K-Factor":
        value *= scale(table["units"])
    kind = "Bend Allowance" if table["type"] == CALCULATION else table["type"]
    return k_of_value(kind, value, angle, r, t)


def is_calculation(obj):
    table = table_of(obj)
    return table is not None and table.get("type") == CALCULATION


def sample_calculation_path():
    """The sample Bend Calculation table in the user's Sheetmetal Bend Tables folder (written on first use)."""
    path = os.path.join(App.getUserAppDataDir(), FOLDER, SAMPLE_CALC)
    if not os.path.exists(path):
        write_file(path, starter_calculation())
    return path


# ================================================================ dialog and commands
class NewDialog(QtWidgets.QDialog):
    ""

    def __init__(self, doc):
        super().__init__(Gui.getMainWindow())
        self.setObjectName("SWSMBendTableDialog")
        self.setWindowTitle("Bend table")
        lay = QtWidgets.QVBoxLayout(self)
        box = QtWidgets.QGroupBox("Bend table")
        grid = QtWidgets.QGridLayout(box)
        self.units = QtWidgets.QComboBox()
        self.units.setObjectName("SWSMBendTableUnits")
        self.units.addItems([u for u, _s in UNITS])
        self.units.setCurrentText(App.ParamGet(paths.PARAM_PATH + "/SheetMetal").GetString("BendTableUnits",
                                                                                           DEFAULT_UNITS))
        self.kind = QtWidgets.QComboBox()
        self.kind.setObjectName("SWSMBendTableType")
        self.kind.addItems(list(TYPES))
        self.file = QtWidgets.QLineEdit(default_path(doc))
        self.file.setObjectName("SWSMBendTableFile")
        self.file.setMinimumWidth(240)
        self.file.setCursorPosition(0)
        browse = QtWidgets.QPushButton("Browse...")
        browse.setObjectName("SWSMBendTableBrowse")
        browse.clicked.connect(self._browse)
        grid.addWidget(QtWidgets.QLabel("Units:"), 0, 0)
        grid.addWidget(self.units, 0, 1)
        grid.addWidget(QtWidgets.QLabel("Type:"), 1, 0)
        grid.addWidget(self.kind, 1, 1)
        grid.addWidget(QtWidgets.QLabel("File name:"), 2, 0)
        grid.addWidget(self.file, 2, 1, 1, 2)
        grid.addWidget(browse, 2, 3)
        grid.setColumnStretch(2, 1)
        lay.addWidget(box)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
                                             | QtWidgets.QDialogButtonBox.Help)
        buttons.setCenterButtons(True)
        from PySide import QtGui
        for b in buttons.buttons():
            b.setIcon(QtGui.QIcon())
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.helpRequested.connect(lambda: QtWidgets.QMessageBox.information(
            self, "Bend table", "Units, Type and File name of the new table. OK writes a starter table to the file "
            "and adds it to the part; double-click it in the tree to edit its values."))
        self.buttons = buttons
        lay.addWidget(buttons)

    def _browse(self):
        path, _f = QtWidgets.QFileDialog.getSaveFileName(self, "Bend table", self.file.text(),
                                                         "Bend tables (*.csv)")
        if path:
            self.file.setText(path if path.lower().endswith(".csv") else path + ".csv")

    def accept(self):
        path = self.file.text().strip()
        if not path.lower().endswith(".csv"):
            path += ".csv"
        doc = App.ActiveDocument
        table = starter(self.kind.currentText(), self.units.currentText())
        try:
            write_file(path, table)
        except OSError as e:
            QtWidgets.QMessageBox.warning(self, "Bend table", "The table could not be written:\n%s" % e)
            return
        App.ParamGet(paths.PARAM_PATH + "/SheetMetal").SetString("BendTableUnits", self.units.currentText())
        self.made = add(doc, table, path)
        super().accept()


def from_file(doc, path):
    table = read_file(path)
    return add(doc, table, path)


class NewCommand:
    def GetResources(self):
        return {"MenuText": "New...", "ToolTip": "Makes a new bend table for the part."}

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        NewDialog(App.ActiveDocument).exec_()


class FileCommand:
    def GetResources(self):
        return {"MenuText": "From File...", "ToolTip": "Adds a bend table from a file to the part."}

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        path, _f = QtWidgets.QFileDialog.getOpenFileName(
            Gui.getMainWindow(), "Open Bend Table", os.path.join(App.getUserAppDataDir(), FOLDER),
            "Bend tables (*.xlsx *.csv *.xls)")
        if not path:
            return
        try:
            from_file(App.ActiveDocument, path)
        except Exception as e:
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Bend Table", str(e))



EDIT_COMMAND, WINDOW_COMMAND, DELETE_COMMAND = "SWStyle_BendTableEdit", "SWStyle_BendTableEditWindow", "SWStyle_BendTableDelete"


def current_table(doc=None):
    """The picked Bend Table (or its sheet), else the part's only one, else its last one."""
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    for o in Gui.Selection.getSelection(doc.Name) if App.GuiUp else []:
        if is_bend_table(o):
            return o
        for p in o.InList:
            if is_bend_table(p) and p.Sheet is o:
                return p
    found = tables(doc)
    return found[-1] if found else None


def edit_table(obj, new_window=False):
    """Opens the table's spreadsheet, in the main area or in a window of its own."""
    if obj is None or obj.Sheet is None:
        return False
    obj.Sheet.ViewObject.doubleClicked()
    if new_window:
        _undock(obj.Sheet.Label)
    return True


def _undock(label=None, tries=10):
    """Takes the active document window out of the main area into a window of its own (as FreeCAD's
    Window > Document window > Undocked does for any view)."""
    mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    if mdi is None:
        return None
    QtWidgets.QApplication.processEvents()
    sub = next((s for s in mdi.subWindowList() if label and label in s.windowTitle()), None)
    if sub is None:
        if tries > 0:           # the sheet's window opens a moment after the double-click
            QtCore.QTimer.singleShot(150, lambda: _undock(label, tries - 1))
        return None
    w = sub.widget()
    title = sub.windowTitle()
    mdi.removeSubWindow(w)
    sub.deleteLater()
    w.setParent(Gui.getMainWindow(), QtCore.Qt.Window)
    w.setWindowTitle(title.replace("[*]", ""))
    w.resize(900, 600)
    w.show()
    w.raise_()
    return w


def delete_table(obj):
    if obj is None:
        return False
    doc = obj.Document
    doc.openTransaction("Delete " + LABEL)
    try:
        sheet = obj.Sheet
        doc.removeObject(obj.Name)
        if sheet is not None and doc.getObject(sheet.Name) is not None:
            doc.removeObject(sheet.Name)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    doc.recompute()
    return True


class _TableCmd:
    def __init__(self, text, tip, run):
        self.text, self.tip, self.run = text, tip, run

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip}

    def IsActive(self):
        return current_table() is not None

    def Activated(self):
        self.run(current_table())


def register():
    if NEW_COMMAND not in Gui.listCommands():
        Gui.addCommand(NEW_COMMAND, NewCommand())
        Gui.addCommand(FILE_COMMAND, FileCommand())
    if EDIT_COMMAND not in Gui.listCommands():
        Gui.addCommand(EDIT_COMMAND, _TableCmd("Edit Table", "Opens the part's bend table to edit it.", edit_table))
        Gui.addCommand(WINDOW_COMMAND, _TableCmd("Edit Table in New Window",
                                                 "Opens the part's bend table in a window of its own.",
                                                 lambda o: edit_table(o, True)))
        Gui.addCommand(DELETE_COMMAND, _TableCmd("Delete", "Deletes the part's bend table.", delete_table))
