""










import math

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    Gui = None

UNITS = (("SI", "N", 1.0), ("English (IPS)", "lbf", 0.2248089431), ("Metric (G)", "kgf", 0.1019716213))
OPTIONS = ("Reaction force", "Free body force")
STRESS = ("NodeStressXX", "NodeStressYY", "NodeStressZZ", "NodeStressXY", "NodeStressXZ", "NodeStressYZ")


def _fw_log(site, err):
    try:
        App.Console.PrintLog("FreeCAD: %s: %s\n" % (site, err))
    except Exception:
        pass


def _sp():
    from . import simplots
    return simplots


def result(a):
    return _sp().result(a)


def meshed_shape(a, res=None):
    res = res or result(a)
    try:
        return _sp()._meshed_shape(res)
    except Exception:
        return None


class Forces:
    """The study's nodal stress tensors and outer triangles, ready to integrate over faces."""

    def __init__(self, a):
        import numpy as np
        from . import simxpress as sx
        self.np = np
        self.a = a
        self.res = res = result(a)
        if res is None:
            raise RuntimeError("Run the study first.")
        fm = res.Mesh.FemMesh
        every = fm.Nodes
        nodes = list(res.NodeNumbers)
        self.at = {n: i for i, n in enumerate(nodes)}
        comps = [list(getattr(res, name, []) or []) for name in STRESS]
        if any(len(c) != len(nodes) for c in comps):
            raise RuntimeError("This result has no stresses.")
        s = np.array(comps, dtype=float).T                        # (N, 6) xx yy zz xy xz yz
        self.sigma = np.stack([np.stack([s[:, 0], s[:, 3], s[:, 4]], 1),
                               np.stack([s[:, 3], s[:, 1], s[:, 5]], 1),
                               np.stack([s[:, 4], s[:, 5], s[:, 2]], 1)], 1)       # (N, 3, 3)
        self.pos = np.array([(every[n].x, every[n].y, every[n].z) if n in every else (0.0, 0.0, 0.0) for n in nodes])
        self.tris = [t for t in sx.surface(res) if all(k in self.at for k in t)]
        self.surface_nodes = {k for t in self.tris for k in t}
        self.shape = meshed_shape(a, res)
        self._fm = fm
        self._cache = {}

    def face_nodes(self, sub):
        """The mesh nodes on a face of the meshed part (the mesher's own map, else by where they are)."""
        got = self._cache.get(sub)
        if got is not None:
            return got
        out = set()
        face = None
        try:
            face = self.shape.Shape.getElement(sub)
        except Exception as _fw_err:
            _fw_log("simforce.py:face", _fw_err)
        if face is None:
            return out
        try:
            out = set(self._fm.getNodesByFace(face))
        except Exception:
            out = set()
        if not out:
            import Part
            box = face.BoundBox
            tol = max(1e-6, box.DiagonalLength * 1e-6, 1e-3)
            box.enlarge(tol)
            for n in self.surface_nodes:
                p = App.Vector(*self.pos[self.at[n]])
                if box.isInside(p) and face.distToShape(Part.Vertex(p))[0] <= tol:
                    out.add(n)
        self._cache[sub] = out
        return out

    def on_face(self, sub):
        """(Fx, Fy, Fz) in N on a face."""
        np = self.np
        nodes = self.face_nodes(sub)
        total = np.zeros(3)
        for t in self.tris:
            if not (t[0] in nodes and t[1] in nodes and t[2] in nodes):
                continue
            i = [self.at[k] for k in t]
            p = self.pos[i]
            cr = np.cross(p[1] - p[0], p[2] - p[0])
            area2 = np.linalg.norm(cr)
            if area2 == 0:
                continue
            n = cr / area2                               # outward (the outer triangles face out)
            sig = self.sigma[i].mean(axis=0)             # linear stress: its mean over the triangle
            total += sig @ n * (0.5 * area2)
        return tuple(float(v) for v in total)

    def fixture_faces(self):
        """Every face a fixture of the study holds (the Entire Model of a reaction)."""
        out = []
        for o in getattr(self.a, "Group", []) or []:
            try:
                if not (o.isDerivedFrom("Fem::ConstraintFixed") or o.isDerivedFrom("Fem::ConstraintDisplacement")):
                    continue
                if getattr(o, "Suppressed", False):
                    continue
                for _obj, subs in o.References:
                    for sub in subs:
                        if sub.startswith("Face") and sub not in out:
                            out.append(sub)
            except Exception as _fw_err:
                _fw_log("simforce.py:fixtures", _fw_err)
        return out


def resultant(f):
    return math.sqrt(sum(v * v for v in f))


def table(forces, subs, option="Reaction force"):
    """{"rows": [(face, (x, y, z), resultant)], "selection": (x, y, z, r), "entire": (x, y, z, r) or None}."""
    rows = []
    sx = [0.0, 0.0, 0.0]
    for sub in subs:
        f = forces.on_face(sub)
        rows.append((sub, f, resultant(f)))
        sx = [a + b for a, b in zip(sx, f)]
    entire = None
    if option == "Reaction force":
        ex = [0.0, 0.0, 0.0]
        for sub in forces.fixture_faces():
            ex = [a + b for a, b in zip(ex, forces.on_face(sub))]
        entire = tuple(ex) + (resultant(ex),)
    return {"rows": rows, "selection": tuple(sx) + (resultant(sx),), "entire": entire}


# =========================================================================== the PM
if Gui is not None:
    class ResultForcePM:
        ""

        def __init__(self, a):
            self.a = a
            self.forces = Forces(a)
            self.subs = []
            self.data = None
            opts = QtWidgets.QWidget()
            opts.setWindowTitle("Options")
            opts.setProperty("swstyle_pm_title", "Result Force")
            ov = QtWidgets.QVBoxLayout(opts)
            self.option = {}
            for text in OPTIONS:
                r = QtWidgets.QRadioButton(text)
                r.setObjectName("SWSimForce_" + text.split()[0])
                ov.addWidget(r)
                self.option[text] = r
            self.option[OPTIONS[0]].setChecked(True)
            sel = QtWidgets.QWidget()
            sel.setWindowTitle("Selection")
            sv = QtWidgets.QVBoxLayout(sel)
            self.picks = QtWidgets.QListWidget()
            self.picks.setObjectName("SWSimForcePicks")
            self.picks.setMaximumHeight(90)
            self.picks.setToolTip("Faces")
            self.picks.setContextMenuPolicy(QtCore.Qt.ActionsContextMenu)
            act = QtGui.QAction("Clear Selections", self.picks)
            act.triggered.connect(self.clear)
            self.picks.addAction(act)
            sv.addWidget(self.picks)
            urow = QtWidgets.QFormLayout()
            self.units = QtWidgets.QComboBox()
            self.units.setObjectName("SWSimForceUnits")
            self.units.addItems([u[0] for u in UNITS])
            self.units.currentIndexChanged.connect(self._fill)
            urow.addRow("Units:", self.units)
            sv.addLayout(urow)
            self.update_btn = QtWidgets.QPushButton("Update")
            self.update_btn.setObjectName("SWSimForceUpdate")
            self.update_btn.clicked.connect(self.update)
            sv.addWidget(self.update_btn)
            res = QtWidgets.QWidget()
            res.setWindowTitle("Result Force")
            rv = QtWidgets.QVBoxLayout(res)
            self.grid = QtWidgets.QTableWidget(0, 5)
            self.grid.setObjectName("SWSimForceGrid")
            self.grid.verticalHeader().hide()
            self.grid.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            rv.addWidget(self.grid)
            comp = QtWidgets.QWidget()
            comp.setWindowTitle("Component")
            cv = QtWidgets.QVBoxLayout(comp)
            self.comp = QtWidgets.QTableWidget(4, 3)
            self.comp.setObjectName("SWSimForceComponents")
            self.comp.verticalHeader().hide()
            self.comp.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            cv.addWidget(self.comp)
            self.form = [opts, sel, res, comp]
            self._observing = False
            Gui.Selection.addObserver(self)
            self._observing = True
            self._click_cb = None
            self._hook_plot()
            for r in self.option.values():      # connected once the PM is built (a toggle filled a half-made PM)
                r.toggled.connect(self._option)
            self._fill()

        # -- picks: faces of the part (tree or view), or a click on the shown plot
        def addSelection(self, doc, obj, sub, pnt):
            name = (sub or "").split(".")[-1]
            if name.startswith("Face"):
                QtCore.QTimer.singleShot(0, lambda: self.pick(name))

        def _hook_plot(self):
            sp = _sp()
            node = sp.SHOWN.get("node")
            if node is None or sp.SHOWN.get("a") is not self.a:
                return
            from pivy import coin
            view = node[0]
            self._click_view = view
            self._click_cb = view.addEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), self._click)

        def _click(self, cb):
            from pivy import coin
            sp = _sp()
            ev = cb.getEvent()
            if not coin.SoMouseButtonEvent.isButtonPressEvent(ev, coin.SoMouseButtonEvent.BUTTON1):
                return
            node = sp.SHOWN.get("node")
            if node is None:
                return
            view = node[0]
            rp = coin.SoRayPickAction(view.getViewer().getSoRenderManager().getViewportRegion())
            rp.setPoint(ev.getPosition())
            rp.apply(view.getSceneGraph())
            pp = rp.getPickedPoint()
            if pp is None:
                return
            q = pp.getPoint()
            n = sp.node_at_drawn((q[0], q[1], q[2]))
            if n is None:
                return
            cb.setHandled()
            face = sp.face_at(self.forces.res, n)
            if face:
                QtCore.QTimer.singleShot(0, lambda: self.pick(face))

        def pick(self, sub):
            if not sub or sub in self.subs or not self.forces.face_nodes(sub):
                return None
            self.subs.append(sub)
            self.picks.addItem(sub)
            try:
                Gui.Selection.clearSelection()
            except Exception:
                pass
            return sub

        def clear(self):
            self.subs = []
            self.picks.clear()
            self.data = None
            self._fill()

        def option_text(self):
            return next((t for t, r in self.option.items() if r.isChecked()), OPTIONS[0])

        def _option(self, on):
            """Another option: the table again for it (the Entire Model column is a reaction's only)."""
            if not on:
                return
            if self.data is not None:
                self.update()
            else:
                self._fill()

        def update(self):
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            try:
                self.data = table(self.forces, self.subs, self.option_text())
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()
            self._fill()
            return self.data

        def _fill(self, *_a):
            name, unit, k = UNITS[self.units.currentIndex()]
            what = self.option_text()
            self.grid.setHorizontalHeaderLabels(["Selection", "Sum X (%s)" % unit, "Sum Y (%s)" % unit,
                                                 "Sum Z (%s)" % unit, "Resultant (%s)" % unit])
            self.grid.setRowCount(0)
            if self.data is not None:
                for r, (sub, f, total) in enumerate(self.data["rows"]):
                    self.grid.insertRow(r)
                    for c, text in enumerate([sub] + ["%.4g" % (v * k) for v in f] + ["%.4g" % (total * k)]):
                        self.grid.setItem(r, c, QtWidgets.QTableWidgetItem(text))
            entire = what == "Reaction force"
            self.comp.setColumnCount(3 if entire else 2)
            self.comp.setHorizontalHeaderLabels(["Component", "Selection", "Entire Model"][:3 if entire else 2])
            for r, label in enumerate(("Sum X", "Sum Y", "Sum Z", "Resultant")):
                self.comp.setItem(r, 0, QtWidgets.QTableWidgetItem(label))
                sel = self.data["selection"][r] * k if self.data is not None else None
                self.comp.setItem(r, 1, QtWidgets.QTableWidgetItem("" if sel is None else "%.4g" % sel))
                if entire:
                    ent = self.data["entire"][r] * k if self.data is not None and self.data["entire"] else None
                    self.comp.setItem(r, 2, QtWidgets.QTableWidgetItem("" if ent is None else "%.4g" % ent))
            self.comp.resizeColumnsToContents()

        def _stop(self):
            if self._observing:
                try:
                    Gui.Selection.removeObserver(self)
                except Exception:
                    pass
                self._observing = False
            if self._click_cb is not None:
                try:
                    from pivy import coin
                    self._click_view.removeEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), self._click_cb)
                except Exception as _fw_err:
                    _fw_log("simforce.py:cb", _fw_err)
                self._click_cb = None

        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Ok

        def accept(self):
            self._stop()
            Gui.Control.closeDialog()
            return True

        def reject(self):
            return self.accept()

    def open_pm(a):
        sp = _sp()
        return sp._open(ResultForcePM(a))


def results_menu(a):
    """simtree: the Results folder's right-click items."""
    if result(a) is None:
        return []
    return [("List Result Force...", lambda: open_pm(a))]
