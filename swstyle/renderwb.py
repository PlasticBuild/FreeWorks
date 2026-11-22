# SPDX-License-Identifier: LGPL-2.1-or-later
"""Real ray-traced renders for the Render Tools tab, through FreeCAD's third-party Render workbench.

When the Render workbench is installed and at least one of its renderers (Cycles, POV-Ray, LuxCore, Appleseed) is set up
in Edit > Preferences > Render, Final Render, the previews and Schedule Render can hand the scene to it. Without the
workbench, or without a renderer set up, none of this shows and renderout keeps drawing the 3D view as before.

How a render goes:
- The visible solids of the document are put into a short-lived Render project (a scene template with studio lights, the
  3D view's camera, the Options size). It is built inside a transaction that is rolled back as soon as the scene file is
  written (and anything left is removed), so the model tree and the undo list are not touched and the document is not
  left marked as changed.
- Appearance -> material: colours (also face by face) always come from the object. Anything with transparency goes
  through the Render workbench's own handling (glass, or a glass/diffuse mix). Everything opaque gets a Disney material
  that keeps the object's colours ("Object" base colour), with the roughness taken from the appearance's shininess and a
  metal look when the part's material is a metal. A part or assembly container gets one such material for its members.
- The renderer runs in the background. The status bar counts the seconds, FreeCAD stays usable, and the picture comes
  back through the callback when the renderer has ended.
"""
import os
import shutil
import tempfile
import time

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except ImportError:
    Gui = None

PARAMS = "User parameter:BaseApp/Preferences/Mod/Render"
# label, Render renderer name, the Render preference that holds its program (batch use), template name start
ENGINES = (("Cycles", "Cycles", "CyclesPath", "cycles_"),
           ("POV-Ray", "Povray", "PovRayPath", "povray_"),
           ("LuxCore", "Luxcore", "LuxCoreConsolePath", "luxcore_"),
           ("Appleseed", "Appleseed", "AppleseedCliPath", "appleseed_"))
SAMPLES = {"preview": 8, "final": (32, 128, 512)}
METALS = ("steel", "alumin", "iron", "brass", "bronze", "copper", "gold", "silver", "titanium", "chrom", "nickel",
          "zinc", "magnesium", "tungsten", "metal", "aisi", "inox", "ti-6al")
METAL_FOLDERS = ("Steel", "Iron", "Aluminium Alloys", "Copper Alloys", "Titanium Alloys", "Other Alloys")
SKIP_TYPES = ("Sketcher::", "App::Origin", "App::Line", "App::Plane", "App::Point", "Part::Datum", "PartDesign::Plane",
              "PartDesign::Line", "PartDesign::Point", "PartDesign::CoordinateSystem", "App::Text", "Spreadsheet::",
              "TechDraw::", "Draft::")
_state = {"busy": False}


# ------------------------------------------------------------------ detecting it
def installed():
    """True when the Render workbench is in this FreeCAD."""
    try:
        return Gui is not None and "RenderWorkbench" in Gui.listWorkbenches()
    except Exception:
        return False


def _render_module():
    try:
        import Render
        return Render
    except Exception:
        return None


def _program_set(key):
    value = App.ParamGet(PARAMS).GetString(key, "").strip().strip('"')
    return bool(value) and (os.path.isfile(value) or shutil.which(value) is not None)


def engines():
    """[(label, Render renderer name)] of the renderers that are set up in the Render preferences."""
    if not installed():
        return []
    return [(label, name) for label, name, key, _ in ENGINES if _program_set(key)]


def engine_names():
    return [name for _, name in engines()]


def template_for(name):
    """The studio-light scene template that ships with the Render workbench for this renderer (name relative to its
    templates folder), or None."""
    mod = _render_module()
    if mod is None:
        return None
    prefix = [p for _, n, _, p in ENGINES if n == name]
    if not prefix:
        return None
    try:
        files = sorted(f for f in os.listdir(mod.TEMPLATEDIR) if f.lower().startswith(prefix[0]))
    except Exception:
        return None
    for want in ("studio_light", "studio", "light"):
        for f in files:
            if want in f.lower():
                return f
    return files[0] if files else None


def why_not():
    """One line saying what is missing, or '' when a render can go."""
    if not installed():
        return "the Render workbench is not installed"
    if not engines():
        return "no renderer is set up in Edit > Preferences > Render"
    return ""


def busy():
    return bool(_state["busy"])


# ------------------------------------------------------------------ the scene
def _top_level(obj):
    for parent in obj.InList:
        if parent is not obj and (parent.isDerivedFrom("App::Part") or parent.isDerivedFrom("PartDesign::Body")):
            return False
    return True


def renderable_objects(doc):
    """The visible solids, surfaces, bodies, parts, links and meshes of the document that are not inside another part
    or body (the Render workbench walks into parts and links by itself)."""
    out = []
    for obj in doc.Objects:
        try:
            vo = obj.ViewObject
            if vo is None or not vo.Visibility:
                continue
            if any(obj.TypeId.startswith(t) for t in SKIP_TYPES) or not _top_level(obj):
                continue
            if obj.isDerivedFrom("App::Part") or obj.isDerivedFrom("App::Link") or obj.isDerivedFrom("Mesh::Feature"):
                out.append(obj)
                continue
            shape = getattr(obj, "Shape", None)
            if shape is None or shape.isNull() or not shape.Faces:
                continue
            out.append(obj)
        except Exception:
            continue
    return out


def _leaves(src, depth=0):
    """The objects whose appearance a view of src shows: src itself, the target of a link, the visible members of a
    part or assembly (to any depth)."""
    if src is None or depth > 8:
        return []
    try:
        if src.isDerivedFrom("App::Link"):
            target = src.getLinkedObject(True)
            return _leaves(target, depth + 1) if target is not None and target is not src else []
        if src.isDerivedFrom("App::Part"):
            out = []
            for sub in src.Group:
                if getattr(sub, "Visibility", True):
                    out += _leaves(sub, depth + 1)
            return out
    except Exception:
        return []
    return [src]


def _appearances(obj):
    try:
        return list(obj.ViewObject.ShapeAppearance)
    except Exception:
        return []


def _metal_name(name):
    n = str(name or "").lower()
    if not n or n == "default":
        return False
    if any(k in n for k in METALS):
        return True
    try:
        from . import material
        return any(n == common.lower() and folder in METAL_FOLDERS for folder, common, _d in material.COMMON)
    except Exception:
        return False


def _is_metal(obj):
    """True when the object's material (its own ShapeMaterial, else the part's Material row) is a metal."""
    try:
        mat = getattr(obj, "ShapeMaterial", None)
        if "/metal" in str(getattr(mat, "Directory", "") or "").lower():
            return True
        name = str(getattr(mat, "Name", "") or "")
        if name and name.lower() != "default":
            return _metal_name(name)
    except Exception:
        pass
    try:
        from . import material
        return _metal_name(material.current(obj.Document)[1])
    except Exception:
        return False


def material_card(src):
    ""


    shins, metal, seen = [], True, False
    for leaf in _leaves(src):
        apps = _appearances(leaf)
        if not apps:
            continue
        try:
            if any(float(a.Transparency) > 0.001 for a in apps):
                return None
            shins.append(max(0.0, min(1.0, float(apps[0].Shininess))))
        except Exception:
            return None
        seen = True
        metal = metal and _is_metal(leaf)
    if not seen:
        return None
    shin = sum(shins) / len(shins)
    rough = max(0.08, 1.0 - shin) if metal else max(0.12, 1.0 - 0.7 * shin)
    card = {"Name": "FreeCAD appearance", "Render.Type": "Disney", "Render.Disney.BaseColor": "Object",
            "Render.Disney.Metallic": "0.9" if metal else "0.0",
            "Render.Disney.Roughness": "%.3f" % rough,
            "Render.Disney.Specular": "%.3f" % (0.5 if metal else 0.3 + 0.4 * shin)}
    for zero in ("Subsurface", "SpecularTint", "Anisotropic", "Sheen", "SheenTint", "ClearCoat", "ClearCoatGloss"):
        card["Render.Disney." + zero] = "0.0"
    return card


def _map_materials(doc, project, made):
    for view in project.Proxy.all_views():
        src = getattr(view, "Source", None)
        if src is None:
            continue
        card = material_card(src)
        if card is None:
            continue
        mat = doc.addObject("App::MaterialObjectPython", "FWRenderMaterial")
        mat.Proxy = _Card()
        mat.Material = card
        made.append(mat.Name)
        view.Material = mat


class _Card:
    """What the Render workbench asks a material for besides its card (no textures, so no UV map). Without it the
    workbench logs "is not a Render Material" for every object; the card is used either way."""

    def has_textures(self):
        return False

    def force_uvmap(self):
        return False

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _scene_names(project):
    """Names of the project, its views and groups (taken before anything is rolled back)."""
    try:
        return [o.Name for o in project.Proxy.all_views(include_groups=True)[1:]] + [project.Name]
    except Exception:
        try:
            return [project.Name]
        except Exception:
            return []


def _remove(doc, names):
    for name in names:
        try:
            if doc.getObject(name) is not None:
                doc.removeObject(name)
        except Exception:
            pass


def _modified(doc):
    try:
        return Gui.getDocument(doc.Name).Modified
    except Exception:
        return None


def _set_modified(doc, value):
    if value is None:
        return
    try:
        Gui.getDocument(doc.Name).Modified = value
    except Exception:
        pass


# ------------------------------------------------------------------ running it
def _find_executor(out):
    """The Render workbench's background runner of this picture (None when it cannot be found)."""
    try:
        want = os.path.normcase(os.path.normpath(out))
        for child in reversed(QtCore.QCoreApplication.instance().children()):
            worker = getattr(child, "worker", None)
            img = getattr(worker, "img", None)
            if img and os.path.normcase(os.path.normpath(str(img))) == want:
                return child
    except Exception:
        pass
    return None


def _running(executor):
    try:
        return bool(executor.thread.isRunning())
    except Exception:
        return False


def render(name, out, width, height, spp, on_done, on_fail, on_tick=None, camera=None):
    """Render the visible model with the Render workbench's renderer `name` into the picture file `out`.

    Raises RuntimeError when the scene cannot be handed over (the caller then falls back to the 3D view); after that
    on_done(path) or on_fail(reason) is called when the renderer has ended."""
    if _state["busy"]:
        raise RuntimeError("a render is already running")
    doc = App.ActiveDocument
    if doc is None or Gui is None:
        raise RuntimeError("there is no document")
    mod = _render_module()
    if mod is None:
        raise RuntimeError(why_not() or "the Render workbench did not load")
    template = template_for(name)
    if not template:
        raise RuntimeError("the Render workbench has no scene template for " + name)
    objs = renderable_objects(doc)
    if not objs:
        raise RuntimeError("there is nothing visible to render")
    out = out.replace("\\", "/")           # the Render workbench splits its command line the POSIX way
    try:
        os.remove(out)
    except OSError:
        pass
    view = Gui.ActiveDocument.ActiveView
    saved_camera = view.getCamera() if camera else None
    was_modified = _modified(doc)
    names, made, scene_dir, own = [], [], None, False
    _state["busy"] = True
    QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
    try:
        try:
            if not doc.HasPendingTransaction:        # never close a transaction somebody else has open
                doc.openTransaction("Render scene")
                own = True
        except Exception:
            own = False
        if camera:
            view.setCamera(camera)
            QtWidgets.QApplication.processEvents()
        _obj, project, _vp = mod.Project.create(doc, renderer=name, template=template)
        names = [project.Name]
        project.RenderWidth = int(width)
        project.RenderHeight = int(height)
        project.OutputImage = out
        project.OpenAfterRender = False
        project.BatchMode = True
        project.SamplesPerPixel = int(spp)
        project.Proxy.add_views(objs)
        names = _scene_names(project)
        _map_materials(doc, project, made)
        scene_dir = os.path.join(os.path.normpath(doc.TransientDir), project.Name)
        project.Proxy.render(wait_for_completion=False)
    except Exception as error:
        _state["busy"] = False
        raise RuntimeError(str(error) or error.__class__.__name__)
    finally:
        QtWidgets.QApplication.restoreOverrideCursor()
        if camera and saved_camera:
            try:
                view.setCamera(saved_camera)
            except Exception:
                pass
        if own:
            try:
                doc.abortTransaction()               # takes the project, its views and materials away again
            except Exception:
                pass
        _remove(doc, made + names)                   # whatever is still there (undo switched off, foreign transaction)
        _set_modified(doc, was_modified)

    started = time.time()
    watch = {"size": -1, "executor": _find_executor(out)}
    timer = QtCore.QTimer()
    timer.setInterval(700)

    def finish(ok, why=""):
        if not timer.isActive():
            return
        timer.stop()
        _state["busy"] = False
        if scene_dir:
            shutil.rmtree(scene_dir, ignore_errors=True)
        try:
            (on_done(out) if ok else on_fail(why))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: render callback failed (%s)\n" % error)

    def tick():
        seconds = int(time.time() - started)
        if on_tick:
            try:
                on_tick("Rendering with %s... %d s" % (name, seconds))
            except Exception:
                pass
        have = os.path.isfile(out) and os.path.getsize(out) > 0
        if watch["executor"] is None:
            watch["executor"] = _find_executor(out)
        if watch["executor"] is not None:
            ended = not _running(watch["executor"])
        else:
            size = os.path.getsize(out) if have else -1
            ended = have and size == watch["size"] and time.time() - os.path.getmtime(out) > 2.0
            watch["size"] = size
        if ended:
            if have:
                finish(True)
            else:
                finish(False, "the renderer made no picture (see the Report view)")
        elif seconds > 3600:
            finish(False, "the renderer took more than an hour")

    timer.timeout.connect(tick)
    timer.start()
    _state["timer"] = timer
    return True
