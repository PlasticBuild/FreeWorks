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


import json
import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtWidgets
except ImportError:  # pragma: no cover
    Gui = None

COMMAND = "SWStyle_SimApplyMaterial"
# materialdlg names -> the SimXpress/Evaluate table (evaltools.MATERIALS) for the mechanical values the library lacks
ALIASES = {"AISI 304": "AISI 304 Stainless", "6061 Alloy": "6061-T6 Aluminium", "6061-T6": "6061-T6 Aluminium",
           "Nylon 6/10": "Nylon 6/6", "Alloy Steel": "Plain Carbon Steel", "AISI 1020": "Plain Carbon Steel",
           "Cast Alloy Steel": "Plain Carbon Steel"}


# The library's common names (material.COMMON) carry only a density: typical published values of each, linear elastic

# name: (E MPa, Poisson, yield MPa or None, tensile MPa, expansion 1/K, conductivity W/(m.K), specific heat J/(kg.K))
LIBRARY = {
    "Plain Carbon Steel": (210000, 0.28, 220.594, 399.826, 1.3e-5, 43, 440),
    "AISI 1020": (200000, 0.29, 351.6, 420.5, 1.5e-5, 47, 420),
    "AISI 304": (190000, 0.29, 206.8, 517.0, 1.8e-5, 16, 500),
    "Alloy Steel": (210000, 0.28, 620.4, 723.8, 1.3e-5, 50, 460),
    "Cast Alloy Steel": (190000, 0.26, 241.3, 448.1, 1.5e-5, 38, 440),
    "Gray Cast Iron": (66178, 0.27, None, 151.7, 1.2e-5, 45, 510),
    "Malleable Cast Iron": (190000, 0.27, 275.7, 413.6, 1.2e-5, 47, 510),
    "1060 Alloy": (69000, 0.33, 27.6, 68.9, 2.4e-5, 200, 900),
    "6061 Alloy": (69000, 0.33, 55.1, 124.1, 2.4e-5, 167, 896),
    "6063-T6": (69000, 0.33, 215.0, 240.0, 2.34e-5, 200, 900),
    "7075-T6": (72000, 0.33, 505.0, 570.0, 2.4e-5, 130, 960),
    "Brass": (100000, 0.33, 239.4, 478.4, 1.9e-5, 110, 390),
    "Copper": (110000, 0.37, 258.6, 394.4, 1.7e-5, 390, 390),
    "Nickel": (207000, 0.31, 148.0, 462.0, 1.3e-5, 90, 440),
    "Ti-6Al-4V": (104800, 0.31, 827.4, 1050.0, 9.0e-6, 6.7, 526),
    "ABS": (2000, 0.394, None, 30.0, 9.0e-5, 0.2256, 1386),
    "ABS PC": (2410, 0.3897, None, 40.0, 6.7e-5, 0.2618, 1900),
    "Acrylic (Medium-high impact)": (3000, 0.35, None, 73.0, 5.2e-5, 0.21, 1500),
    "Nylon 6/10": (8300, 0.28, 139.0, 142.0, 3.0e-5, 0.53, 1500),
    "PE High Density": (1070, 0.4101, None, 22.1, 1.2e-4, 0.461, 1796),
    "PP Copolymer": (896, 0.4103, None, 26.2, 1.5e-4, 0.147, 1881),
    "PLA": (3500, 0.36, 50.0, 60.0, 6.8e-5, 0.13, 1800),
    "PETG": (2010, 0.39, 50.0, 53.0, 6.8e-5, 0.2, 1200),
    "PBT General Purpose": (2400, 0.39, None, 50.0, 8.0e-5, 0.21, 1500),
    "Rubber": (6.1, 0.49, None, 13.8, 6.7e-4, 0.14, 2000),
    "Balsa": (3000, 0.3, None, 20.0, 4.0e-6, 0.05, 2900),
    "Pine": (9000, 0.3, None, 40.0, 5.0e-6, 0.12, 1600),
    "Oak": (11000, 0.3, None, 60.0, 5.0e-6, 0.17, 2400),
}


def _library(name):
    row = LIBRARY.get(name)
    if row is None:
        return {}
    e, nu, y, uts, alpha, k, cp = row
    out = {"YoungsModulus": e * 1e6, "PoissonRatio": nu, "UltimateTensileStrength": uts * 1e6,
           "ThermalExpansionCoefficient": alpha, "ThermalConductivity": float(k), "SpecificHeat": float(cp)}
    if y:
        out["YieldStrength"] = y * 1e6
    return out


def _table(name):
    try:
        from . import evaltools
        row = evaltools.MATERIALS.get(name) or evaltools.MATERIALS.get(ALIASES.get(name, ""))
        if row is None:
            return {}
        dens, yield_mpa, e_mpa, nu = row[:4]
        return {"Density": float(dens), "YieldStrength": yield_mpa * 1e6, "YoungsModulus": e_mpa * 1e6, "PoissonRatio": nu}
    except Exception as _fw_err:
        _fw_log("simmaterial.py:table", _fw_err)
        return {}


def fem_dict(entry):
    """FreeCAD FEM's material card of a Material dialog entry (its values are SI). None without an elastic modulus."""
    v = dict(_table(entry.get("name", "")))
    v.update(_library(entry.get("name", "")))   # the library name's own values over the near-match table's
    v.update({k: x for k, x in (entry.get("values") or {}).items() if x not in (None, "")})
    if not v.get("YoungsModulus"):
        return None
    out = {"Name": entry.get("name", "Material"), "YoungsModulus": "%g MPa" % (v["YoungsModulus"] / 1e6),
           "PoissonRatio": str(v.get("PoissonRatio", 0.3)), "Density": "%g kg/m^3" % v.get("Density", 7800)}
    for key, fmt, scale in (("YieldStrength", "%g MPa", 1e-6), ("UltimateTensileStrength", "%g MPa", 1e-6),
                            ("ThermalConductivity", "%g W/m/K", 1.0), ("ThermalExpansionCoefficient", "%g m/m/K", 1.0),
                            ("SpecificHeat", "%g J/kg/K", 1.0)):
        if v.get(key):
            out[key] = fmt % (v[key] * scale)
    return out


def set_study(a, entry):
    """The study's one common material becomes entry; extra common materials are taken out. True when done."""
    card = fem_dict(entry)
    if card is None:
        return False
    import ObjectsFem
    from . import simtree
    doc = a.Document
    common = [m for m in simtree._materials(a) if not list(getattr(m, "References", []) or [])
              and getattr(getattr(m, "Proxy", None), "Type", "") != "Fem::MaterialMechanicalNonlinear"]
    m = common[0] if common else ObjectsFem.makeMaterialSolid(doc, "Material")
    for extra in common[1:]:
        a.removeObject(extra)
        doc.removeObject(extra.Name)
    if m not in a.Group:
        a.addObject(m)
    m.Material = card
    try:                                     # the Tables & Curves (stress-strain for Plasticity) go with the study
        if "FwMaterialCurves" not in a.PropertiesList:
            a.addProperty("App::PropertyString", "FwMaterialCurves", "FreeWorks", "The study material's curves (JSON)")
            a.setEditorMode("FwMaterialCurves", 2)
        a.FwMaterialCurves = json.dumps(entry.get("curves") or {}, sort_keys=True)
    except Exception as _fw_err:
        _fw_log("simmaterial.py:curves", _fw_err)
    doc.recompute()
    try:
        from . import simtypes
        if simtypes.is_nonlinear(a):            # Plasticity - von Mises follows the new yield strength
            simtypes.apply_nonlinear(a)
    except Exception as _fw_err:
        _fw_log("simmaterial.py:nonlinear", _fw_err)
    return True


def curves_of(a):
    """The study material's Tables & Curves: {curve name: [[x, y], ...]} (the part's, for a study made before)."""
    try:
        got = json.loads(getattr(a, "FwMaterialCurves", "") or "{}")
        if got:
            return got
    except ValueError:
        pass
    try:
        from . import materialdlg
        return materialdlg.part_data(a.Document).get("curves") or {}
    except Exception:
        return {}


def from_part(a):
    """A new study: the part's material when it has one (else the study keeps its default)."""
    try:
        from . import material, materialdlg
        _dens, name = material.current(a.Document)
        found = materialdlg.find(name) if name else None
        if found is not None:
            return set_study(a, found[2])
    except Exception as _fw_err:
        _fw_log("simmaterial.py:frompart", _fw_err)
    return False


def study_type(a):
    try:
        from . import simtypes
        return simtypes.study_type(a)
    except Exception:
        return "static"


def _study():
    try:
        from . import simtree
        return simtree._ctx_study()
    except Exception:
        return None


def open_dialog(a=None):
    """The Material dialog for the study a (the active one): Apply gives the part and the study the material."""
    from . import materialdlg, asmsim, simtree
    a = a or _study()
    if a is None:
        return None
    if asmsim.is_assembly_study(a):              # an assembly study: a material per component (asmsim)
        return asmsim.pick_material(a, None)

    class StudyMaterialDialog(materialdlg.MaterialDialog):
        def apply(self):
            e = self._read_back()
            if e is None:
                return
            card = fem_dict(e)
            if card is not None and study_type(a) == "thermomech" and "ThermalConductivity" not in card:
                QtWidgets.QMessageBox.warning(self, "Apply Material", "%s has no Thermal Conductivity, so the thermal "
                                              "study cannot use it. Pick another material, or give a custom one its "
                                              "Thermal Conductivity." % e.get("name", "This material"))
                return
            if card is None:
                QtWidgets.QMessageBox.warning(self, "Apply Material", "%s has no Elastic Modulus, so the study cannot "
                                              "use it. Pick another material, or give a custom one its Elastic "
                                              "Modulus." % e.get("name", "This material"))
                return
            a.Document.openTransaction("Apply Material")
            try:
                materialdlg.give_part(a.Document, e, self.use_colour.isChecked(), self._hatch())
                set_study(a, e)
            finally:
                a.Document.commitTransaction()
            Gui.getMainWindow().statusBar().showMessage("%s: %s applied" % (a.Label, e.get("name", "")), 6000)

    dlg = StudyMaterialDialog(a.Document)
    try:
        mats = [m for m in simtree._materials(a) if not list(getattr(m, "References", []) or [])]
        name = mats[0].Material.get("Name") if mats else None
        if name:
            dlg._select(name)
    except Exception as _fw_err:
        _fw_log("simmaterial.py:select", _fw_err)
    dlg.exec_()
    return dlg


class _Cmd:
    def GetResources(self):
        return {"MenuText": "Apply Material", "ToolTip": "Applies a material from the Material dialog to the part "
                "and the study.", "Pixmap": "FEM_MaterialSolid"}

    def IsActive(self):
        try:
            return App.ActiveDocument is not None and not Gui.Control.activeDialog() and _study() is not None
        except Exception:
            return False

    def Activated(self):
        open_dialog()


def follow_part(doc, entry):
    ""

    try:
        from . import simtree
        for a in simtree.studies(doc):
            set_study(a, entry)
    except Exception as _fw_err:
        _fw_log("simmaterial.py:follow_part", _fw_err)


def _hook_give_part():
    try:
        from . import materialdlg
    except Exception:
        return
    old = materialdlg.give_part
    if getattr(old, "_fw_follow", False):
        return

    def give_part(doc, entry, *args, **kw):
        # one Undo step for the part's material, its data and the studies that follow it
        from . import material
        apply_ = material.apply

        def apply_in(doc_, name, value, uuid=""):
            material.assign(doc_, name, value, uuid)
            doc_.recompute()
        doc.openTransaction("Edit Material")
        material.apply = apply_in
        try:
            out = old(doc, entry, *args, **kw)
            follow_part(doc, entry)
        finally:
            material.apply = apply_
            doc.commitTransaction()
        return out
    give_part._fw_follow = True
    give_part.__doc__ = old.__doc__
    materialdlg.give_part = give_part


def install():
    _hook_give_part()
    if Gui is None:
        return
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, _Cmd())
    try:
        from . import catalog
        cmd = catalog.BY_KEY.get("SIM_ApplyMaterial")
        if cmd is not None and (not cmd.natives or cmd.natives[0] != COMMAND):
            cmd.natives = (COMMAND,) + tuple(n for n in cmd.natives if n != COMMAND)
    except Exception as _fw_err:
        _fw_log("simmaterial.py:install", _fw_err)
