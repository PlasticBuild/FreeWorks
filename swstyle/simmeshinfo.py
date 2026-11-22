# SPDX-License-Identifier: LGPL-2.1-or-later
""















import math
import socket
import time

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except ImportError:
    Gui = None

TIMES = {}
_SEEN = set()
WINDOWS = []


def _log(site, err):
    if site not in _SEEN:
        _SEEN.add(site)
        try:
            App.Console.PrintLog("FreeCAD Mesh Details %s: %s\n" % (site, err))
        except Exception:
            return


def _kept(mesh):
    try:
        from . import simpms
        return simpms.kept(mesh)
    except Exception:
        return {}


def _length(q):
    """A length property as the user sees it (document units)."""
    try:
        return App.Units.Quantity(q).UserString if not hasattr(q, "UserString") else q.UserString
    except Exception:
        return str(q)


def _tet_quality(p):
    """(aspect ratio, distorted) of the tetrahedron with corners p[0..3]."""
    a, b, c, d = p
    vol = (b - a).cross(c - a).dot(d - a) / 6.0
    edges = [(a - b).Length, (a - c).Length, (a - d).Length, (b - c).Length, (b - d).Length, (c - d).Length]
    longest = max(edges)
    areas = [(b - a).cross(c - a).Length / 2.0, (b - a).cross(d - a).Length / 2.0,
             (c - a).cross(d - a).Length / 2.0, (c - b).cross(d - b).Length / 2.0]
    if abs(vol) < 1e-30 or max(areas) <= 0:
        return float("inf"), 0.0
    hmin = 3.0 * abs(vol) / max(areas)
    return (longest / hmin) / math.sqrt(1.5), vol               # regular tetrahedron: h = sqrt(2/3) * edge


def _tri_quality(p):
    a, b, c = p
    area = (b - a).cross(c - a).Length / 2.0
    edges = [(a - b).Length, (b - c).Length, (c - a).Length]
    longest = max(edges)
    if area <= 1e-30:
        return float("inf"), 0.0
    hmin = 2.0 * area / longest
    return (longest / hmin) * math.sqrt(3) / 2.0, 1.0                  # equilateral: h = sqrt(3)/2 * edge


def distorted(q):
    """How many of q [(aspect ratio, signed corner volume)] are distorted: zero volume, or turned the other way
    from most of the mesh (the mesher's node order fixes which sign is right)."""
    if not q:
        return 0
    right = 1.0 if sum(1 for _r, v in q if v > 0) >= sum(1 for _r, v in q if v < 0) else -1.0
    return sum(1 for _r, v in q if v == 0 or v * right < 0)


def quality(fem):
    """[(aspect ratio, signed corner volume)] of the solid elements, else of the faces (volume 1)."""
    out = []
    nodes = fem.Nodes
    try:
        vols = list(fem.Volumes)
    except Exception:
        vols = []
    if vols:
        for e in vols:
            ids = fem.getElementNodes(e)
            if len(ids) >= 4:
                out.append(_tet_quality([nodes[i] for i in ids[:4]]))
        return out
    try:
        faces = list(fem.Faces)
    except Exception:
        faces = []
    for e in faces:
        ids = fem.getElementNodes(e)
        if len(ids) >= 3:
            out.append(_tri_quality([nodes[i] for i in ids[:3]]))
    return out


def _mesh_type(fem):
    try:
        if fem.VolumeCount:
            return "Solid Mesh"
        if fem.FaceCount:
            return "Shell Mesh"
        if fem.EdgeCount:
            return "Beam Mesh"
    except Exception as _fw_err:
        _log("type", _fw_err)
    return None


def details(mesh, study=None):
    rows = []
    k = _kept(mesh)
    fem = getattr(mesh, "FemMesh", None)
    if study is not None:
        rows.append(("Study name", study.Label))
    t = _mesh_type(fem) if fem is not None else None
    if t:
        rows.append(("Mesh type", t))
    kind = k.get("kind")

    if kind:
        rows.append(("Mesher Used", "Curvature-based mesh" if kind == "Curvature-based" else "Standard mesh"))
    else:
        rows.append(("Mesher Used", "Gmsh" if "Gmsh" in mesh.TypeId + str(getattr(getattr(mesh, "Proxy", None), "Type", ""))
                     else "Netgen" if "Netgen" in mesh.TypeId + str(getattr(getattr(mesh, "Proxy", None), "Type", "")) else "FreeCAD"))
    if t == "Solid Mesh":
        rows.append(("Jacobian points for High quality mesh", k.get("jacobian") or "4 Points"))
    if "CharacteristicLengthMax" in mesh.PropertiesList and float(getattr(mesh.CharacteristicLengthMax, "Value", 0) or 0) > 0:
        mx = mesh.CharacteristicLengthMax
        mn = getattr(mesh, "CharacteristicLengthMin", None)
        mn = mn if kind == "Curvature-based" and mn is not None and float(mn.Value) > 0 else mx
        try:
            from . import addintabs
            inch = addintabs._inch_units(study)
        except Exception:
            inch = False
        size = (lambda q: "%.6g in" % (float(q.getValueAs("mm")) / 25.4)) if inch else (lambda q: "%.6g mm" % float(q.getValueAs("mm")))
        rows.append(("Max Element Size", size(mx)))
        rows.append(("Min Element Size", size(mn)))
    if k.get("tolerance"):
        rows.append(("Tolerance", "%s %s" % (k["tolerance"], k.get("unit", "mm"))))
    if "ElementOrder" in mesh.PropertiesList:
        rows.append(("Mesh quality", "Draft" if mesh.ElementOrder == "1st" else "High"))
    elif "SecondOrder" in mesh.PropertiesList:
        rows.append(("Mesh quality", "High" if mesh.SecondOrder else "Draft"))
    if fem is not None and fem.NodeCount:
        rows.append(("Total nodes", "%d" % fem.NodeCount))
        n = fem.VolumeCount or fem.FaceCount or fem.EdgeCount
        rows.append(("Total elements", "%d" % n))
        q = quality(fem)
        if q:
            ars = [r for r, _bad in q if r != float("inf")]
            if ars:
                rows.append(("Maximum Aspect Ratio", "%.5g" % max(ars)))
            rows.append(("Percentage of elements with Aspect Ratio < 3", "%.3g" % (100.0 * sum(1 for r, _b in q if r < 3) / len(q))))
            rows.append(("Percentage of elements with Aspect Ratio > 10", "%.3g" % (100.0 * sum(1 for r, _b in q if r > 10) / len(q))))
            if t == "Solid Mesh":
                bad = distorted(q)
                rows.append(("Percentage of distorted elements", "%.3g" % (100.0 * bad / len(q))))
                rows.append(("Number of distorted elements", "%d" % bad))
    rows.append(("Reuse mesh for identical bodies", "Off"))          # FreeCAD meshes every body afresh
    rows.append(("Number of bodies that have reused mesh", "0"))
    secs = TIMES.get(mesh.Name)
    if secs is not None:
        rows.append(("Time to complete mesh(hh:mm:ss)", time.strftime("%H:%M:%S", time.gmtime(max(0, int(round(secs)))))))
    try:
        rows.append(("Computer name", socket.gethostname()))
    except Exception as _fw_err:
        _log("host", _fw_err)
    return rows


def _study_of(mesh):
    for p in getattr(mesh, "InList", []):
        if p.isDerivedFrom("Fem::FemAnalysis"):
            return p
    return None


def show(mesh=None, study=None):
    """Opens Mesh Details for mesh (else the active study's mesh). Returns the window."""
    if Gui is None:
        return None
    if mesh is None and study is not None:
        mesh = next((o for o in study.Group if o.isDerivedFrom("Fem::FemMeshObject")), None)
    if mesh is None:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Mesh Details", "The study has no mesh yet: create the mesh first.")
        return None
    study = study or _study_of(mesh)
    rows = details(mesh, study)
    w = QtWidgets.QDialog(Gui.getMainWindow())
    w.setObjectName("SWSimMeshDetails")
    w.setWindowTitle("Mesh Details")
    w.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
    lay = QtWidgets.QVBoxLayout(w)
    table = QtWidgets.QTableWidget(len(rows), 2, w)
    table.setObjectName("SWSimMeshDetailsTable")
    table.setHorizontalHeaderLabels(["Details", "Value"])
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    for r, (name, value) in enumerate(rows):
        table.setItem(r, 0, QtWidgets.QTableWidgetItem(name))
        table.setItem(r, 1, QtWidgets.QTableWidgetItem(value))
    table.resizeColumnsToContents()
    table.horizontalHeader().setStretchLastSection(True)
    lay.addWidget(table)
    w.resize(max(380, table.horizontalHeader().length() + 40), min(520, 60 + 26 * len(rows)))
    w.show()
    WINDOWS[:] = [x for x in WINDOWS if _alive(x)] + [w]
    return w


def _alive(w):
    try:
        w.isVisible()
        return True
    except RuntimeError:
        return False
