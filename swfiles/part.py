# SPDX-License-Identifier: LGPL-2.1-or-later
""












import os

import FreeCAD as App
import Part

from . import doc_name, msg, params, warn
from . import swapp

TOLERANCE = 0.005        # share of the volume the rebuilt tree may differ by
DETAIL_TOLERANCE = 0.02  # ... when only detail features (fillets, chamfers, threads) did not rebuild
DETAIL_KINDS = ("fillet", "chamfer", "sweepthread", "thread", "cosmeticthread")


def exact_bodies(path):
    ""

    from . import djb_import
    try:
        bodies = djb_import._convert(path)
    except Exception as exc:
        if not swapp.use_solidworks():
            raise
        why = exc
    else:
        if all(_closed(shape) for _l, shape, _a in bodies) or not swapp.use_solidworks():
            return bodies
        try:
            return solidworks_bodies(path)
        except Exception as exc:
            warn("%s: the decoded shape is not closed and SolidWorks could not give it (%s)" % (
                os.path.basename(path), exc))
            return bodies
    try:
        return solidworks_bodies(path)
    except Exception as exc:
        raise RuntimeError("could not decode the part geometry (%s), and SolidWorks could not give it "
                           "either (%s)" % (why, exc))


def _closed(shape):
    try:                        # an open shell the solid leaves out is still a face decoded wrongly
        if any(not sh.isClosed() for sh in shape.Shells):
            return False
        solids = as_solid(shape).Solids
        return bool(solids) and all(x.isValid() and all(sh.isClosed() for sh in x.Shells) for x in solids)
    except Exception:
        return False


def solidworks_bodies(path):
    ""
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="fw-sw-")
    try:
        step = os.path.join(tmp, "part.step")
        swapp.run("export-step", [path, step], "Reading the shape from SolidWorks...")
        shape = Part.read(step)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    solids = shape.Solids
    if not solids:
        raise RuntimeError("SolidWorks gave no solid")
    base = os.path.splitext(os.path.basename(path))[0]
    if len(solids) == 1:
        return SolidWorksBodies([(base, solids[0], None)])
    return SolidWorksBodies([("%s %d" % (base, i), sol, None) for i, sol in enumerate(solids, 1)])


class SolidWorksBodies(list):
    ""
    from_solidworks = True


def apply_appearance(obj, appearance, visible=True):
    from . import djb_import
    djb_import._apply_appearance(obj, appearance, visible)


def as_solid(shape):
    from . import rebuild
    return rebuild.as_solid(shape)


def mark_source(doc, path, kind, how):
    meta = dict(doc.Meta)
    meta.update({"FreeWorksSource": os.path.abspath(path), "FreeWorksSourceKind": kind,
                 "FreeWorksTree": how})
    doc.Meta = meta


def open_part(path, doc=None, read_tree=None):
    """Opens the part in doc (a new document named after the file when None). Returns
    (doc, how) with how "tree" or "imported"."""
    bodies = exact_bodies(path)
    base = os.path.splitext(os.path.basename(path))[0]
    new_doc = doc is None
    if doc is None:
        doc = App.newDocument(doc_name(base))
        doc.Label = base
    if read_tree is None:
        read_tree = params().GetBool("ReadFeatureTree", True) and swapp.use_solidworks()
    how = "imported"
    if read_tree:
        tree = read_feature_tree(path)
        retry = not getattr(bodies, "from_solidworks", False)
        if tree is not None and rebuild_tree(doc, tree, bodies, base, quiet=retry):
            how = "tree"
        elif tree is not None and retry:
            try:
                sw_bodies = solidworks_bodies(path)
            except Exception as exc:
                sw_bodies = None
                warn("%s: SolidWorks did not give its shape (%s)" % (base, exc))
            if sw_bodies and rebuild_tree(doc, tree, sw_bodies, base):
                how, bodies = "tree", sw_bodies
            elif not sw_bodies:
                warn("%s: the feature tree did not rebuild; opened as an imported body" % base)
    if how == "imported":
        add_imported(doc, bodies, base)
    mark_source(doc, path, "sldprt", how)
    doc.recompute()
    bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
    if new_doc and len(bodies) == 1:
        mark_source_body(bodies[0], path)
    return doc, how


def read_feature_tree(path):
    try:
        return swapp.run("tree", [path], "Reading the FeatureManager tree from SolidWorks...")["tree"]
    except swapp.HelperError as exc:
        warn("%s: feature tree not read (%s); opened as an imported body" % (os.path.basename(path), exc))
        return None


def mark_source_body(body, path):
    ""

    if not hasattr(body, "FwSourceFile"):
        body.addProperty("App::PropertyFile", "FwSourceFile", "FreeWorks",
                         "The SolidWorks part this body was opened from")
    body.FwSourceFile = os.path.abspath(path)
    body.setEditorMode("FwSourceFile", 1)
    body.Document.recompute()
    if not hasattr(body, "FwSourceShape"):
        body.addProperty("App::PropertyString", "FwSourceShape", "FreeWorks",
                         "Fingerprint of the shape as opened")
    body.FwSourceShape = shape_key(body.Shape)
    body.setEditorMode("FwSourceShape", 2)


def shape_key(shape):
    """A fingerprint of a solid: changes with any edit that changes the geometry."""
    try:
        b = shape.BoundBox
        return "%.6g|%.6g|%s" % (shape.Volume, shape.Area, ",".join("%.4f" % x for x in (
            b.XMin, b.YMin, b.ZMin, b.XMax, b.YMax, b.ZMax)))
    except Exception:
        return ""


def reference_shape(bodies):
    solids = []
    for _label, shape, _app in bodies:
        solids.extend(as_solid(shape).Solids)
    if not solids:
        return None
    return solids[0] if len(solids) == 1 else Part.makeCompound(solids)


def rebuild_tree(doc, tree, bodies, base, quiet=False):
    ""

    from . import rebuild_api
    ref = reference_shape(bodies)
    if ref is None:
        return False
    before = set(o.Name for o in doc.Objects)
    real_new = App.newDocument
    App.newDocument = lambda *a, **k: doc         # the rebuilder makes its own document
    undo = doc.UndoMode
    doc.UndoMode = 0                              # trial features are no undo steps
    try:
        r = rebuild_api.ApiRebuilder(tree, ref)
        r.run()
        final = r.tip_shape()
        err = r.mismatch(final)
        good = err <= TOLERANCE * r.ref_vol
        failed = [row for row in r.log if row["status"] in ("failed", "not rebuilt", "deferred")]
        # a fillet OpenCASCADE cannot roll, or a modelled thread, only changes details: keep the

        if not good and failed and err <= DETAIL_TOLERANCE * r.ref_vol and \
                all(str(row.get("kind", "")).lower() in DETAIL_KINDS for row in failed):
            good = True
        if good and hasattr(r, "add_threads"):
            # threads go on last, once the check is done: a boolean of the modelled thread

            r.add_threads()
        failed = [row for row in r.log if row["status"] in ("failed", "not rebuilt", "deferred")]
    except Exception as exc:
        warn("%s: feature tree rebuild stopped: %s" % (base, exc))
        good, failed, r = False, [], None
    finally:
        App.newDocument = real_new
        doc.UndoMode = undo
    if good:
        r.body.Label = base if r.body.Label in ("Part", "Body") else r.body.Label
        if bodies and bodies[0][2]:
            doc.recompute()
            apply_appearance(r.body, bodies[0][2])
        msg("%s: opened with its SolidWorks feature tree (%d features%s)" % (
            base, len(r.log), ", %d not rebuilt" % len(failed) if failed else ""))
        for row in failed:
            msg("  %s: %s %s" % (row["feature"], row["status"], row.get("kind", "")))
        return True
    for name in [o.Name for o in doc.Objects if o.Name not in before]:
        try:
            doc.removeObject(name)
        except Exception:
            pass
    pct = r.pct(err) if r is not None else None
    if not quiet:
        warn("%s: the feature tree did not rebuild to the SolidWorks shape (%s %% off); "
             "opened as an imported body" % (base, pct))
    return False


def add_imported(doc, bodies, base):
    """One PartDesign body per solid, its first feature the exact shape ("Imported1")."""
    made = []
    for i, (label, shape, app) in enumerate(bodies, 1):
        solid = as_solid(shape)
        feat = doc.addObject("Part::Feature", "Imported%d" % i)
        feat.Label = "Imported%d" % i
        feat.Shape = solid
        body = doc.addObject("PartDesign::Body", "Body")
        body.Label = base if len(bodies) == 1 else label
        body.BaseFeature = feat
        made.append((body, feat, app))
    doc.recompute()
    for body, feat, app in made:
        if App.GuiUp:
            feat.ViewObject.Visibility = False
        apply_appearance(body, app)
    return [b for b, _f, _a in made]
