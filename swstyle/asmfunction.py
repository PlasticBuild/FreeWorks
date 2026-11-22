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
import math

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

KINDS = ("Segments", "Data Points", "Expression")
Y_KINDS = ("Displacement", "Velocity", "Acceleration")
INTERPOLATIONS = ("Linear", "Cubic Spline", "Akima Spline")
PI = math.pi


def _mod_trap(u):
    s4 = math.sin
    if u < 0.125:
        return 0.38898448 * u - 0.0309544 * s4(4 * PI * u)
    if u < 0.375:
        return 2.44406184 * u * u - 0.22203097 * u + 0.00723407
    if u < 0.625:
        return 1.6110154 * u - 0.0309544 * s4(4 * PI * u - PI) - 0.3055077
    if u < 0.875:
        return -2.44406184 * u * u + 4.6660917 * u - 1.2292648
    return 0.6110154 + 0.38898448 * u + 0.0309544 * s4(4 * PI * u - 3 * PI)


def _mod_sine(u):
    if u < 0.125:
        return 0.43990085 * u - 0.0350062 * math.sin(4 * PI * u)
    if u < 0.875:
        return 0.28004957 + 0.43990085 * u - 0.31505577 * math.cos(4 * PI / 3 * u - PI / 6)
    return 0.56009915 + 0.43990085 * u - 0.0350062 * math.sin(4 * PI * u - 2 * PI)


# a segment's profile: P(u) on 0..1, from 0 to 1 (Constant holds the start value)
PROFILES = {
    "Constant": lambda u: 0.0,
    "Linear": lambda u: u,
    "Cubic": lambda u: u * u * (3 - 2 * u),
    "Quintic": lambda u: u ** 3 * (10 - 15 * u + 6 * u * u),
    "Quarter Sine": lambda u: math.sin(PI * u / 2),
    "Haversine": lambda u: (1 - math.cos(PI * u)) / 2,
    "Cycloidal": lambda u: u - math.sin(2 * PI * u) / (2 * PI),
    "Modified Sine": _mod_sine,
    "Modified Trapezoidal": _mod_trap,
}
PROFILE_NAMES = tuple(PROFILES)



def _step(x, x0, h0, x1, h1):
    if x <= x0:
        return h0
    if x >= x1:
        return h1
    u = (x - x0) / (x1 - x0)
    return h0 + (h1 - h0) * u * u * (3 - 2 * u)


def _if(e, neg, zero, pos):
    return neg if e < 0 else (zero if e == 0 else pos)


FUNCTIONS = {
    "abs": abs, "acos": math.acos, "asin": math.asin, "atan": math.atan, "atan2": math.atan2,
    "cos": math.cos, "cosh": math.cosh, "exp": math.exp, "log": math.log, "log10": math.log10,
    "max": max, "min": min, "mod": math.fmod, "sign": lambda a, b=1.0: math.copysign(abs(a), b),
    "sin": math.sin, "sinh": math.sinh, "sqrt": math.sqrt, "tan": math.tan, "tanh": math.tanh,
    "step": _step, "if": _if, "pow": math.pow,
}
CONSTANTS = {"pi": math.pi, "e": math.e}
# the Function Builder's Functions list: (inserted text, tip)
FUNCTION_LIST = (
    ("ABS()", "ABS(x): absolute value"), ("ACOS()", "ACOS(x)"), ("ASIN()", "ASIN(x)"), ("ATAN()", "ATAN(x)"),
    ("ATAN2(,)", "ATAN2(y, x)"), ("COS()", "COS(x), x in radians"), ("COSH()", "COSH(x)"), ("EXP()", "EXP(x)"),
    ("IF(,,,)", "IF(e, value if e<0, value if e=0, value if e>0)"), ("LOG()", "LOG(x): natural log"),
    ("LOG10()", "LOG10(x)"), ("MAX(,)", "MAX(a, b)"), ("MIN(,)", "MIN(a, b)"), ("MOD(,)", "MOD(a, b)"),
    ("SIGN(,)", "SIGN(a, b): |a| with the sign of b"), ("SIN()", "SIN(x), x in radians"), ("SINH()", "SINH(x)"),
    ("SQRT()", "SQRT(x)"), ("STEP(,,,,)", "STEP(x, x0, h0, x1, h1): a cubic step from h0 at x0 to h1 at x1"),
    ("TAN()", "TAN(x)"), ("TANH()", "TANH(x)"), ("PI", "3.14159..."),
)
VARIABLES = (("time", "Time (s)"),)
_NODES = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call, ast.Name, ast.Load, ast.Constant,
          ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.USub, ast.UAdd)


def compile_expression(text):
    ""
    src = (text or "").strip().replace("^", "**")
    if not src:
        raise ValueError("Type an expression of time, for example 30*SIN(2*PI*time).")
    try:
        tree = ast.parse(src.lower(), mode="eval")
    except SyntaxError:
        raise ValueError("The expression is not complete: check its brackets and operators.")
    for node in ast.walk(tree):
        if not isinstance(node, _NODES):
            raise ValueError("Use numbers, time, + - * / ^ and the functions in the list.")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS or node.keywords:
                raise ValueError("Unknown function: %s" % ast.unparse(node.func).upper())
        elif isinstance(node, ast.Name) and node.id not in FUNCTIONS and node.id not in CONSTANTS \
                and node.id != "time":
            raise ValueError("Unknown name: %s (the variable is time)" % node.id)
        elif isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            raise ValueError("Use numbers, time, + - * / ^ and the functions in the list.")
    code = compile(tree, "<expression>", "eval")
    env = dict(FUNCTIONS, **CONSTANTS)
    env["__builtins__"] = {}

    def f(t):
        return float(eval(code, env, {"time": float(t)}))
    try:
        f(0.0)
        f(1.0)
    except ZeroDivisionError as _fw_err:
        _fw_log("asmfunction.py:143", _fw_err)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("The expression can't be worked out: %s" % error)
    return f


# ---------------------------------------------------------------- the function as y(x)
def _spline(xs, ys, akima=False):
    """Interpolating cubic (natural spline, or Akima): returns y(x), constant outside the points."""
    n = len(xs)
    if n == 1:
        return lambda x: ys[0]
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    if akima:
        m = [(ys[i + 1] - ys[i]) / h[i] for i in range(n - 1)]
        if n == 2:
            d = [m[0], m[0]]
        else:
            ext = [3 * m[0] - 2 * m[1], 2 * m[0] - m[1]] + m + [2 * m[-1] - m[-2], 3 * m[-1] - 2 * m[-2]]
            d = []
            for i in range(n):
                w1, w2 = abs(ext[i + 3] - ext[i + 2]), abs(ext[i + 1] - ext[i])
                d.append((ext[i + 1] + ext[i + 2]) / 2 if w1 + w2 < 1e-12
                         else (w1 * ext[i + 1] + w2 * ext[i + 2]) / (w1 + w2))
    else:
        # natural spline: second derivatives M, M0 = Mn = 0
        a = [0.0] * n
        b = [1.0] * n
        c = [0.0] * n
        r = [0.0] * n
        for i in range(1, n - 1):
            a[i], b[i], c[i] = h[i - 1], 2 * (h[i - 1] + h[i]), h[i]
            r[i] = 6 * ((ys[i + 1] - ys[i]) / h[i] - (ys[i] - ys[i - 1]) / h[i - 1])
        for i in range(1, n):
            w = a[i] / b[i - 1]
            b[i] -= w * c[i - 1]
            r[i] -= w * r[i - 1]
        M = [0.0] * n
        M[-1] = r[-1] / b[-1]
        for i in range(n - 2, -1, -1):
            M[i] = (r[i] - c[i] * M[i + 1]) / b[i]
        d = []
        for i in range(n):
            if i < n - 1:
                d.append((ys[i + 1] - ys[i]) / h[i] - h[i] * (2 * M[i] + M[i + 1]) / 6)
            else:
                d.append((ys[i] - ys[i - 1]) / h[i - 1] + h[i - 1] * (M[i - 1] + 2 * M[i]) / 6)

    def y(x):
        if x <= xs[0]:
            return ys[0]
        if x >= xs[-1]:
            return ys[-1]
        i = max(k for k in range(n - 1) if xs[k] <= x)
        u = (x - xs[i]) / h[i]
        h00, h10 = 2 * u ** 3 - 3 * u * u + 1, u ** 3 - 2 * u * u + u
        h01, h11 = -2 * u ** 3 + 3 * u * u, u ** 3 - u * u
        return h00 * ys[i] + h10 * h[i] * d[i] + h01 * ys[i + 1] + h11 * h[i] * d[i + 1]
    return y


def clean_points(points):
    out = {}
    for p in points or ():
        try:
            out[float(p[0])] = float(p[1])
        except (TypeError, ValueError, IndexError):
            continue
    return sorted(out.items())


def clean_segments(segments):
    out = []
    for s in segments or ():
        try:
            x0, x1, y0, y1 = (float(v) for v in s[:4])
        except (TypeError, ValueError):
            continue
        prof = s[4] if len(s) > 4 and s[4] in PROFILES else "Linear"
        if x1 > x0:
            out.append([x0, x1, y0, y1, prof])
    return sorted(out, key=lambda s: s[0])


def check(func):
    """'' when the function can be used, else what is wrong (as the Function Builder says it)."""
    kind = func.get("kind")
    if kind == "Segments":
        segs = clean_segments(func.get("segments"))
        if not segs:
            return "Add a segment: its start and end time and its start and end value."
        for a, b in zip(segs, segs[1:]):
            if b[0] < a[1] - 1e-9:
                return "Segments overlap: a segment starts at %.4g s before the one above ends." % b[0]
        return ""
    if kind == "Data Points":
        if len(clean_points(func.get("points"))) < 2:
            return "Add at least two data points (time and value)."
        return ""
    try:
        compile_expression(func.get("expression"))
    except ValueError as error:
        return str(error)
    return ""


def y_of(func):
    """y(x) as the user typed it (in the y quantity's units). ValueError if the function isn't usable."""
    msg = check(func)
    if msg:
        raise ValueError(msg)
    kind = func.get("kind")
    if kind == "Segments":
        segs = clean_segments(func.get("segments"))

        def y(x):
            if x <= segs[0][0]:
                return segs[0][2]
            for x0, x1, y0, y1, prof in segs:
                if x0 <= x <= x1:
                    if prof == "Constant":
                        return y0
                    return y0 + (y1 - y0) * PROFILES[prof]((x - x0) / (x1 - x0))
            prev = [s for s in segs if s[1] <= x]
            return prev[-1][3] if prev else segs[0][2]
        return y
    if kind == "Data Points":
        pts = clean_points(func.get("points"))
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        interp = func.get("interpolation", INTERPOLATIONS[0])
        if interp == "Linear" or len(xs) < 3:
            def y(x):
                if x <= xs[0]:
                    return ys[0]
                if x >= xs[-1]:
                    return ys[-1]
                i = max(k for k in range(len(xs) - 1) if xs[k] <= x)
                return ys[i] + (ys[i + 1] - ys[i]) * (x - xs[i]) / (xs[i + 1] - xs[i])
            return y
        return _spline(xs, ys, akima=interp == "Akima Spline")
    f = compile_expression(func.get("expression"))

    def y(x):
        try:
            return f(x)
        except (ZeroDivisionError, ValueError, OverflowError):
            return 0.0
    return y


def displacement(func, duration, sub=200):
    """Displacement d(t) from the function: integrated once (Velocity) or twice (Acceleration), from 0."""
    y = y_of(func)
    kind = func.get("y", Y_KINDS[0])
    if kind == "Displacement":
        return y
    n = max(50, int(sub * max(duration, 1e-6)))
    dt = max(duration, 1e-6) / n
    ts = [i * dt for i in range(n + 1)]
    v = [y(t) for t in ts]
    if kind == "Acceleration":
        vel = [0.0]
        for i in range(n):
            vel.append(vel[-1] + (v[i] + v[i + 1]) * dt / 2)
        v = vel
    d = [0.0]
    for i in range(n):
        d.append(d[-1] + (v[i] + v[i + 1]) * dt / 2)

    def disp(t):
        if t <= 0:
            return d[0]
        k = min(n - 1, int(t / dt))
        u = (t - ts[k]) / dt
        return d[k] + (d[k + 1] - d[k]) * min(1.0, u)
    return disp


def frame_times(duration, fps):
    n = max(1, int(round(float(duration) * max(1, int(fps)))))
    step = float(duration) / n
    return [i * step for i in range(n + 1)]


def formula(func, duration, fps, scale=1.0):
    """FreeCAD's motion formula: the displacement through every frame time, times scale (deg -> rad)."""
    d = displacement(func, duration)
    ts = frame_times(duration, fps)
    ys = [scale * d(t) for t in ts]
    if len(ts) < 2:
        return "%.12g" % ys[0]
    slopes = [(ys[i + 1] - ys[i]) / (ts[i + 1] - ts[i]) for i in range(len(ts) - 1)]
    terms = ["%.12g" % (ys[0] - slopes[0] * ts[0])]
    if abs(slopes[0]) > 1e-15:
        terms.append("%.12g*time" % slopes[0])
    for i in range(1, len(slopes)):
        dm = slopes[i] - slopes[i - 1]
        if abs(dm) < 1e-12:
            continue
        x = "(time-%.12g)" % ts[i]
        terms.append("%.12g*(%s+(%s^2)^0.5)" % (dm / 2.0, x, x))
    return "+".join(terms).replace("+-", "-")


def summary(func):
    kind = func.get("kind", KINDS[0])
    if kind == "Segments":
        n = len(clean_segments(func.get("segments")))
        return "%s, %d segment%s" % (func.get("y", Y_KINDS[0]), n, "" if n == 1 else "s")
    if kind == "Data Points":
        n = len(clean_points(func.get("points")))
        return "%s, %d points, %s" % (func.get("y", Y_KINDS[0]), n, func.get("interpolation", INTERPOLATIONS[0]))
    return "%s = %s" % (func.get("y", Y_KINDS[0]), func.get("expression", ""))


def default(kind, rotary=True):
    big = 90.0 if rotary else 10.0
    if kind == "Segments":
        return {"kind": kind, "y": "Displacement", "segments": [[0.0, 1.0, 0.0, big, "Cubic"],
                                                                [1.0, 2.0, big, big, "Constant"],
                                                                [2.0, 3.0, big, 0.0, "Cubic"]]}
    if kind == "Data Points":
        return {"kind": kind, "y": "Displacement", "interpolation": "Linear",
                "points": [[0.0, 0.0], [1.0, big], [2.0, big / 2], [3.0, big]]}
    return {"kind": kind, "y": "Displacement",
            "expression": ("%g*SIN(2*PI*time)" % (big / 3)) if rotary else ("%g*time" % big)}


# ---------------------------------------------------------------- the Function Builder window
class _Graph(QtWidgets.QWidget):
    """The plot: Displacement, Velocity and Acceleration over time."""
    COLOURS = (QtGui.QColor(60, 140, 230), QtGui.QColor(230, 120, 40), QtGui.QColor(80, 180, 80))

    def __init__(self):
        super().__init__()
        self.setObjectName("FW_FunctionGraph")
        self.setMinimumSize(360, 200)
        self.curves = []
        self.span = (0.0, 1.0)
        self.message = ""

    def set_function(self, func, duration):
        self.curves, self.message = [], ""
        try:
            d = displacement(func, duration)
        except ValueError as error:
            self.message = str(error)
            self.update()
            return
        n = 200
        ts = [duration * i / n for i in range(n + 1)]
        ds = [d(t) for t in ts]
        dt = duration / n
        vs = [(ds[min(n, i + 1)] - ds[max(0, i - 1)]) / (dt * (2 if 0 < i < n else 1)) for i in range(n + 1)]
        acc = [(vs[min(n, i + 1)] - vs[max(0, i - 1)]) / (dt * (2 if 0 < i < n else 1)) for i in range(n + 1)]
        self.curves = [("Displacement", ts, ds), ("Velocity", ts, vs), ("Acceleration", ts, acc)]
        self.span = (0.0, duration)
        self.update()

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = self.rect().adjusted(40, 10, -10, -24)
        pal = self.palette()
        p.fillRect(self.rect(), pal.base())
        p.setPen(pal.text().color())
        p.drawRect(r)
        if self.message or not self.curves:
            p.drawText(r, QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap, self.message)
            return
        p.drawText(QtCore.QRectF(r.left(), r.bottom() + 4, r.width(), 18), QtCore.Qt.AlignCenter, "Time (sec)")
        x0, x1 = self.span
        for k, (name, ts, ys) in enumerate(self.curves):
            lo, hi = min(ys), max(ys)
            if hi - lo < 1e-12:
                lo, hi = lo - 1, hi + 1
            path = QtGui.QPainterPath()
            for i, (t, y) in enumerate(zip(ts, ys)):
                pt = QtCore.QPointF(r.left() + (t - x0) / max(x1 - x0, 1e-12) * r.width(),
                                    r.bottom() - (y - lo) / (hi - lo) * r.height())
                path.moveTo(pt) if i == 0 else path.lineTo(pt)
            p.setPen(QtGui.QPen(self.COLOURS[k], 1.6))
            p.drawPath(path)
            p.drawText(r.left() + 6, r.top() + 14 + 14 * k, name)


class FunctionBuilder(QtWidgets.QDialog):
    ""


    def __init__(self, func, rotary=True, duration=5.0, parent=None, quantity=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("FW_FunctionBuilder")
        self.rotary, self.duration = rotary, max(float(duration), 1e-3)
        self.quantity = quantity            # "Force" or "Torque": a Force/Torque's function (y is that)
        self.func = dict(func)
        self.kind = self.func.get("kind", KINDS[0])
        self.setWindowTitle("Function Builder - %s" % self.kind)
        lay = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QFormLayout()
        self.y = QtWidgets.QComboBox()
        self.y.setObjectName("FW_FunctionY")
        self.y.addItems([quantity] if quantity else list(Y_KINDS))
        self.y.setCurrentText(quantity or self.func.get("y", Y_KINDS[0]))
        if quantity:                        # one value only: shown as text, not a one-entry list
            self.y.hide()
            label = QtWidgets.QLabel(quantity)
            label.setObjectName("FW_FunctionYText")
            top.addRow("Value (y):", label)
        else:
            top.addRow("Value (y):", self.y)
        self.x = QtWidgets.QComboBox()
        self.x.setObjectName("FW_FunctionX")
        self.x.addItems(["Time"])
        top.addRow("Independent variable (x):", self.x)
        self.units = QtWidgets.QLabel()
        self.units.setObjectName("FW_FunctionUnits")
        top.addRow("Units:", self.units)
        lay.addLayout(top)
        self.table = None
        self.expr = None
        if self.kind == "Segments":
            self.table = QtWidgets.QTableWidget(0, 5)
            self.table.setHorizontalHeaderLabels(["Start (x)", "End (x)", "Start (y)", "End (y)", "Profile"])
            for row in clean_segments(self.func.get("segments")):
                self._add_row(row)
            self._add_row(None)
        elif self.kind == "Data Points":
            form = QtWidgets.QFormLayout()
            self.interp = QtWidgets.QComboBox()
            self.interp.setObjectName("FW_FunctionInterpolation")
            self.interp.addItems(list(INTERPOLATIONS))
            self.interp.setCurrentText(self.func.get("interpolation", INTERPOLATIONS[0]))
            self.interp.currentIndexChanged.connect(lambda *_: self._changed())
            form.addRow("Interpolation type:", self.interp)
            lay.addLayout(form)
            self.table = QtWidgets.QTableWidget(0, 2)
            self.table.setHorizontalHeaderLabels(["Time (sec)", "Value (y)"])
            for row in clean_points(self.func.get("points")):
                self._add_row(list(row))
            self._add_row(None)
        else:
            lay.addWidget(QtWidgets.QLabel("Expression definition:"))
            self.expr = QtWidgets.QLineEdit(self.func.get("expression", ""))
            self.expr.setObjectName("FW_FunctionExpression")
            self.expr.textChanged.connect(lambda *_: self._changed())
            lay.addWidget(self.expr)
            row = QtWidgets.QHBoxLayout()
            self.functions = QtWidgets.QComboBox()
            self.functions.setObjectName("FW_FunctionMathFunctions")
            self.functions.addItem("Math functions")
            for text, tip in FUNCTION_LIST:
                self.functions.addItem(text.split("(")[0], text)
                self.functions.setItemData(self.functions.count() - 1, tip, QtCore.Qt.ToolTipRole)
            self.functions.activated.connect(self._insert_function)
            self.variables = QtWidgets.QComboBox()
            self.variables.setObjectName("FW_FunctionVariables")
            self.variables.addItem("Variables")
            for text, tip in VARIABLES:
                self.variables.addItem(text, text)
                self.variables.setItemData(self.variables.count() - 1, tip, QtCore.Qt.ToolTipRole)
            self.variables.activated.connect(self._insert_variable)
            row.addWidget(self.functions)
            row.addWidget(self.variables)
            lay.addLayout(row)
        if self.table is not None:
            self.table.setObjectName("FW_FunctionTable")
            self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            self.table.customContextMenuRequested.connect(self._table_menu)
            self.table.itemChanged.connect(lambda *_: self._changed())
            self.table.horizontalHeader().setStretchLastSection(True)
            lay.addWidget(self.table)
        self.error = QtWidgets.QLabel("")
        self.error.setObjectName("FW_FunctionError")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #d04040;")
        lay.addWidget(self.error)
        self.graph = _Graph()
        lay.addWidget(self.graph, 1)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.setObjectName("FW_FunctionButtons")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.ok = buttons.button(QtWidgets.QDialogButtonBox.Ok)
        lay.addWidget(buttons)
        self.y.currentIndexChanged.connect(lambda *_: self._changed())
        self.resize(560, 560)
        self._changed()

    # -- table rows
    def _add_row(self, values):
        t = self.table
        t.blockSignals(True)
        r = t.rowCount()
        t.insertRow(r)
        cols = t.columnCount()
        for c in range(cols if self.kind == "Data Points" else 4):
            v = "" if values is None else "%g" % values[c]
            t.setItem(r, c, QtWidgets.QTableWidgetItem(v))
        if self.kind == "Segments":
            box = QtWidgets.QComboBox()
            box.setObjectName("FW_FunctionProfile")
            box.addItems(list(PROFILE_NAMES))
            box.setCurrentText(values[4] if values else "Cubic")
            box.currentIndexChanged.connect(lambda *_: self._changed())
            t.setCellWidget(r, 4, box)
        t.blockSignals(False)

    def _rows(self):
        out = []
        t = self.table
        for r in range(t.rowCount()):
            cells = [t.item(r, c).text().strip() if t.item(r, c) else "" for c in range(
                2 if self.kind == "Data Points" else 4)]
            if not any(cells):
                continue
            try:
                row = [float(c) for c in cells]
            except ValueError:
                return None, "Row %d: type numbers." % (r + 1)
            if self.kind == "Segments":
                row.append(t.cellWidget(r, 4).currentText())
            out.append(row)
        return out, ""

    def _fill_next(self):
        ""

        t = self.table
        cols = 2 if self.kind == "Data Points" else 4

        def text(r, c):
            it = t.item(r, c)
            return it.text().strip() if it else ""
        t.blockSignals(True)
        try:
            if self.kind == "Segments":
                for r in range(1, t.rowCount()):
                    if any(text(r, c) for c in range(cols)) and not text(r, 0) and not text(r, 2) \
                            and text(r - 1, 1) and text(r - 1, 3):
                        t.item(r, 0).setText(text(r - 1, 1))
                        t.item(r, 2).setText(text(r - 1, 3))
        finally:
            t.blockSignals(False)
        last = t.rowCount() - 1
        if last < 0 or any(text(last, c) for c in range(cols)):
            self._add_row(None)

    def _table_menu(self, pos):
        r = self.table.rowAt(pos.y())
        m = QtWidgets.QMenu(self.table)
        m.setObjectName("FW_FunctionTableMenu")
        ins = m.addAction("Insert Row")
        dele = m.addAction("Delete Row")
        dele.setEnabled(0 <= r < self.table.rowCount() - 1)
        ins.setEnabled(r >= 0)
        a = m.exec_(self.table.viewport().mapToGlobal(pos))
        if a is dele:
            self.table.removeRow(r)
            self._changed()
        elif a is ins:
            self.insert_row(r)

    def insert_row(self, r):
        self._add_row(None)
        t = self.table
        last = t.rowCount() - 1
        t.blockSignals(True)
        for row in range(last, r, -1):          # move rows down one
            for c in range(4 if self.kind == "Segments" else 2):
                above = t.item(row - 1, c)
                t.item(row, c).setText(above.text() if above else "")
                if above:
                    above.setText("")
            if self.kind == "Segments":
                t.cellWidget(row, 4).setCurrentText(t.cellWidget(row - 1, 4).currentText())
        t.blockSignals(False)
        self._changed()

    def delete_row(self, r):
        if 0 <= r < self.table.rowCount() - 1:
            self.table.removeRow(r)
            self._changed()

    # -- the expression
    def _insert_function(self, i):
        if i <= 0:
            return
        text = self.functions.itemData(i)
        self.functions.setCurrentIndex(0)
        cur = self.expr.cursorPosition()
        self.expr.insert(text)
        if "(" in text:
            self.expr.setCursorPosition(cur + text.index("(") + 1)
        self.expr.setFocus()

    def _insert_variable(self, i):
        if i <= 0:
            return
        self.variables.setCurrentIndex(0)
        self.expr.insert(self.variables.itemText(i))
        self.expr.setFocus()

    # -- the function
    def function(self):
        out = {"kind": self.kind, "y": self.y.currentText()}
        if self.kind == "Segments":
            rows, msg = self._rows()
            out["segments"] = rows or []
            return out, msg
        if self.kind == "Data Points":
            rows, msg = self._rows()
            out["points"] = rows or []
            out["interpolation"] = self.interp.currentText()
            return out, msg
        out["expression"] = self.expr.text()
        return out, ""

    def _changed(self):
        if self.table is not None:
            self._fill_next()
        y = self.y.currentText()
        base = "deg" if self.rotary else "mm"
        self.units.setText({"Displacement": base, "Velocity": base + "/s", "Acceleration": base + "/s^2",
                            "Force": "N", "Torque": "N*mm"}[y])
        func, msg = self.function()
        msg = msg or check(func)
        self.error.setText(msg)
        self.error.setVisible(bool(msg))
        self.ok.setEnabled(not msg)
        span = self.duration
        if self.kind == "Segments" and not msg:
            span = max(span, max(s[1] for s in clean_segments(func["segments"])))
        elif self.kind == "Data Points" and not msg:
            span = max(span, clean_points(func["points"])[-1][0])
        self.graph.set_function(func, span)

    def accept(self):
        func, msg = self.function()
        msg = msg or check(func)
        if msg:
            self.error.setText(msg)
            self.error.show()
            return
        self.func = func
        super().accept()


LAST = {}


def edit(func, rotary=True, duration=5.0, modal=True, quantity=None):
    """Open the Function Builder on func. modal: returns the new function, or None on Cancel.
    quantity "Force" or "Torque": the function of a Force/Torque (y in N or N*mm)."""
    dlg = FunctionBuilder(func, rotary, duration, quantity=quantity)
    LAST["dialog"] = dlg
    if not modal:
        dlg.show()
        return dlg
    return dlg.func if dlg.exec_() == QtWidgets.QDialog.Accepted else None
