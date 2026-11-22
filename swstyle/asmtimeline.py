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
import math
import os
import shutil
import subprocess
import tempfile

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import asmcore as ac

KEYS_PROP = "FwKeys"
V = App.Vector
Qt = QtCore.Qt


# ---------------------------------------------------------------- keys
def _props(sim):
    if not hasattr(sim, KEYS_PROP):
        sim.addProperty("App::PropertyString", KEYS_PROP, "FreeCAD", "MotionManager key points (json)")
        sim.setEditorMode(KEYS_PROP, 2)


def data(sim):
    _props(sim)
    try:
        d = json.loads(getattr(sim, KEYS_PROP) or "{}")
    except Exception:
        d = {}
    d.setdefault("comps", {})
    d.setdefault("view", [])
    return d


def save(sim, d):
    _props(sim)
    setattr(sim, KEYS_PROP, json.dumps(d))


def _enc(plc):
    q = plc.Rotation.Q
    return [list(plc.Base), list(q)]


def _dec(k):
    return App.Placement(V(*k[1]), App.Rotation(*k[2]))


def animated(asm):
    """What the timeline keys: the components and the parts of exploded subassemblies."""
    from . import asmexplode as ax
    return ac.components(asm) + ax.nested_parts(asm)


def ensure_start(asm, sim):
    ""
    d = data(sim)
    changed = False
    for c in ac.components(asm):
        if c.Name not in d["comps"]:
            d["comps"][c.Name] = [[0.0] + _enc(c.Placement)]
            changed = True
    if changed:
        save(sim, d)
    return d


def keys(sim, name):
    return [k[0] for k in data(sim)["comps"].get(name, [])]


def set_key(sim, obj, t, plc=None):
    """A key for obj at time t (its placement now, or plc); an existing key there is updated."""
    d = data(sim)
    rows = d["comps"].setdefault(obj.Name, [])
    plc = plc if plc is not None else obj.Placement
    t = round(float(t), 4)
    for k in rows:
        if abs(k[0] - t) < 1e-6:
            k[1:3] = _enc(plc)                  # the key's interpolation mode stays
            break
    else:
        rows.append([t] + _enc(plc))
        rows.sort(key=lambda k: k[0])
    save(sim, d)


def delete_key(sim, name, t):
    d = data(sim)
    rows = d["comps"].get(name, [])
    d["comps"][name] = [k for k in rows if abs(k[0] - t) > 1e-6 or (k[0] == 0 and len(rows) == 1)]
    save(sim, d)


def move_key(sim, name, t, new_t):
    d = data(sim)
    new_t = max(0.0, round(float(new_t), 4))
    rows = d["comps"].get(name, [])
    if any(abs(k[0] - new_t) < 1e-6 for k in rows if abs(k[0] - t) > 1e-6):
        return False                    # another key is there
    for k in rows:
        if abs(k[0] - t) < 1e-6:
            k[0] = new_t
    rows.sort(key=lambda k: k[0])
    save(sim, d)
    return True



INTERPOLATION = ("Linear", "Snap", "Ease In", "Ease Out", "Ease In/Out")
INTERPOLATION_TEXT = {"Linear": "Linear", "Snap": "Snap", "Ease In": "Ease in", "Ease Out": "Ease out",
                      "Ease In/Out": "Ease in/Ease out"}


# ---------------------------------------------------------------- Suppress Key
def suppressed(sim):
    """{(kind, name, t)} of the suppressed keys (playback goes past them)."""
    return {(k, n, round(float(t), 4)) for k, n, t in data(sim).get("suppressed", [])}


def is_suppressed(sim, kind, name, t):
    return (kind, name, round(float(t), 4)) in suppressed(sim)


def set_suppressed(sim, kind, name, t, on=True):
    d = data(sim)
    rows = [r for r in d.get("suppressed", []) if not (r[0] == kind and r[1] == name and abs(r[2] - t) < 1e-6)]
    if on and t > 0:                   # the start key always holds
        rows.append([kind, name, round(float(t), 4)])
    d["suppressed"] = rows
    save(sim, d)


def _move_suppressed(sim, kind, name, t, new_t=None):
    d = data(sim)
    rows = d.get("suppressed", [])
    hit = [r for r in rows if r[0] == kind and r[1] == name and abs(r[2] - t) < 1e-6]
    if not hit:
        return
    for r in hit:
        rows.remove(r)
        if new_t is not None:
            rows.append([kind, name, round(float(new_t), 4)])
    save(sim, d)


def live_data(sim):
    """data(sim) without the suppressed keys: what playback uses."""
    d = data(sim)
    off = {(k, n, round(float(t), 4)) for k, n, t in d.get("suppressed", [])}
    if not off:
        return d
    for kind, section in (("key", "comps"), ("look", "look"), ("mate", "mates")):
        for name, rows in d.get(section, {}).items():
            d[section][name] = [r for r in rows if (kind, name, round(float(r[0]), 4)) not in off]
    if "cams" in d:
        d["cams"] = [r for r in d["cams"] if ("cam", "__view__", round(float(r[0]), 4)) not in off]
    return d


def reverse_path(sim, picked):
    """Reverse Path: on each row, the picked keys hold their values in the other order (the
    motion between them runs backwards)."""
    d = data(sim)
    rows_by = {}
    for kind, name, t in picked:
        rows_by.setdefault((kind, name), []).append(t)
    done = 0
    for (kind, name), times in rows_by.items():
        if len(times) < 2:
            continue
        rows = _rows(d, kind, name)
        chosen = sorted([r for r in rows if any(abs(r[0] - t) < 1e-6 for t in times)], key=lambda r: r[0])
        payloads = [list(r[1:]) for r in chosen]
        for r, pl in zip(chosen, reversed(payloads)):
            r[1:] = pl
        done += 1
    if done:
        save(sim, d)
    return done


def interpolation(sim, name, t):
    for k in data(sim)["comps"].get(name, []):
        if abs(k[0] - t) < 1e-6:
            return k[3] if len(k) > 3 else "Linear"
    return None


def set_interpolation(sim, name, t, mode):
    if mode not in INTERPOLATION:
        raise ValueError(mode)
    d = data(sim)
    for k in d["comps"].get(name, []):
        if abs(k[0] - t) < 1e-6:
            del k[3:]
            if mode != "Linear":
                k.append(mode)
            save(sim, d)
            return True
    return False


def ease(f, mode):
    """The share of the way done at f (0..1) between two keys."""
    if mode == "Snap":
        return 1.0 if f >= 1.0 - 1e-9 else 0.0      # holds, then jumps at the key
    if mode == "Ease In":
        return f * f                                  # starts slow
    if mode == "Ease Out":
        return 1.0 - (1.0 - f) * (1.0 - f)            # ends slow
    if mode == "Ease In/Out":
        return f * f * (3.0 - 2.0 * f)
    return f


def placement_at(rows, t):
    """The placement keys rows give at time t: straight line and even turn between keys."""
    if not rows:
        return None
    if t <= rows[0][0]:
        return _dec(rows[0])
    for a, b in zip(rows, rows[1:]):
        if a[0] <= t <= b[0]:
            span = b[0] - a[0]
            f = 0.0 if span <= 0 else (t - a[0]) / span
            f = ease(f, b[3] if len(b) > 3 else "Linear")
            pa, pb = _dec(a), _dec(b)
            base = pa.Base + (pb.Base - pa.Base) * f
            rot = pa.Rotation.slerp(pb.Rotation, f)
            return App.Placement(base, rot)
    return _dec(rows[-1])


def view_angle(d, t):
    """Rotate model: the view's turn (axis, degrees) at t from the wizard's segments."""
    axis, total = None, 0.0
    for seg in d.get("view", []):
        t0, t1, ax, turns, sign = seg
        if t < t0:
            continue
        f = 1.0 if t >= t1 or t1 <= t0 else (t - t0) / (t1 - t0)
        axis = ax
        total += sign * 360.0 * turns * f
    return axis, total


def end_time(sim):
    d = data(sim)
    ts = [k[0] for rows in d["comps"].values() for k in rows] + [s[1] for s in d.get("view", [])]
    return max(ts) if ts else 0.0


def has_motion(sim):
    d = data(sim)
    return any(len(rows) > 1 for rows in d["comps"].values()) or bool(d.get("view")) \
        or any(len(rows) > 1 for rows in d.get("look", {}).values()) or len(d.get("cams", [])) > 1 \
        or any(len(rows) > 1 for rows in d.get("mates", {}).values())


# ---------------------------------------------------------------- appearance keys (hide/show, colour)
def look_of(comp):
    """(visible, colour (r, g, b) or None when the part's own colour shows)."""
    vo = getattr(comp, "ViewObject", None)
    colour = None
    try:
        if vo is not None and getattr(vo, "OverrideMaterial", False):
            colour = [round(c, 4) for c in vo.ShapeMaterial.DiffuseColor[:3]]
    except Exception:
        colour = None
    return [bool(comp.Visibility), colour]


def apply_look(comp, look):
    vis, colour = look
    if bool(comp.Visibility) != bool(vis):
        comp.Visibility = bool(vis)
    vo = getattr(comp, "ViewObject", None)
    if vo is None or not hasattr(vo, "OverrideMaterial"):
        return
    try:
        if colour is None:
            if vo.OverrideMaterial:
                vo.OverrideMaterial = False
        else:
            now = [round(c, 4) for c in vo.ShapeMaterial.DiffuseColor[:3]]
            if not vo.OverrideMaterial or now != [round(c, 4) for c in colour]:
                mat = vo.ShapeMaterial
                mat.DiffuseColor = tuple(colour) + (0.0,)
                vo.ShapeMaterial = mat
                vo.OverrideMaterial = True
    except Exception as _fw_err:
        _fw_log("asmtimeline.py:326", _fw_err)


def look_keys(sim, name):
    return [k[0] for k in data(sim).get("look", {}).get(name, [])]


def set_look_key(sim, comp, t, look=None, start=None):
    """An appearance key for comp at t (its look now, or look); start = the look at 0 when the
    component has no appearance key yet (what it looked like before the change)."""
    d = data(sim)
    rows = d.setdefault("look", {}).setdefault(comp.Name, [])
    look = list(look if look is not None else look_of(comp))
    t = round(float(t), 4)
    if not rows and t > 0 and start is not None:
        rows.append([0.0] + list(start))
    for k in rows:
        if abs(k[0] - t) < 1e-6:
            k[1:] = look
            break
    else:
        rows.append([t] + look)
        rows.sort(key=lambda k: k[0])
    save(sim, d)


def delete_look_key(sim, name, t):
    d = data(sim)
    rows = d.get("look", {}).get(name, [])
    d.setdefault("look", {})[name] = [k for k in rows if abs(k[0] - t) > 1e-6 or (k[0] == 0 and len(rows) == 1)]
    save(sim, d)


def move_look_key(sim, name, t, new_t):
    d = data(sim)
    rows = d.get("look", {}).get(name, [])
    new_t = max(0.0, round(float(new_t), 4))
    if any(abs(k[0] - new_t) < 1e-6 for k in rows if abs(k[0] - t) > 1e-6):
        return False
    for k in rows:
        if abs(k[0] - t) < 1e-6:
            k[0] = new_t
    rows.sort(key=lambda k: k[0])
    save(sim, d)
    return True


def look_at(rows, t):
    """Hide/show changes at its key; a colour fades from one key's to the next."""
    if not rows:
        return None
    if t <= rows[0][0]:
        return list(rows[0][1:])
    for a, b in zip(rows, rows[1:]):
        if a[0] <= t < b[0]:
            vis = a[1]
            ca, cb = a[2], b[2]
            if ca is not None and cb is not None and b[0] > a[0]:
                f = (t - a[0]) / (b[0] - a[0])
                return [vis, [x + (y - x) * f for x, y in zip(ca, cb)]]
            return [vis, ca]
    return list(rows[-1][1:])


def apply_looks(asm, sim, t):
    doc = asm.Document
    for name, rows in live_data(sim).get("look", {}).items():
        obj = doc.getObject(name)
        look = look_at(rows, t)
        if obj is not None and look is not None:
            apply_look(obj, look)


def frames(asm, sim, duration, fps):
    """[{name: placement}] at each frame from 0 to duration, and the view turns [(axis, deg)].
    With mate keys, each frame sets the mates' values and solves, and the frame holds where
    every component went."""
    d = live_data(sim)
    n = int(round(duration * fps))
    out, views = [], []
    keyed_mates = {k: rows for k, rows in d.get("mates", {}).items() if len(rows) > 1}
    doc = asm.Document
    saved = {c.Name: App.Placement(c.Placement) for c in ac.components(asm)} if keyed_mates else {}
    for i in range(n + 1):
        t = i / float(fps)
        frame = {name: placement_at(rows, t) for name, rows in d["comps"].items() if rows}
        if keyed_mates:
            for name, plc in frame.items():
                obj = doc.getObject(name)
                if obj is not None and plc is not None:
                    obj.Placement = plc
            apply_mates(asm, sim, t)
            frame = {c.Name: App.Placement(c.Placement) for c in ac.components(asm)}
        out.append(frame)
        views.append(view_angle(d, t))
    if keyed_mates:
        apply_mates(asm, sim, 0.0)
        for c in ac.components(asm):
            if c.Name in saved:
                c.Placement = saved[c.Name]
    return out, views


# ---------------------------------------------------------------- mate keys (a Distance or Angle changed over time)
def keyable_mates(asm):
    return [j for j in ac.mates(asm) if ac.mate_type(j) in ("Distance", "Angle")]


def mate_value(j):
    if ac.mate_type(j) == "Distance":
        return round(ac.distance_value(j), 6)
    prop = "Angle" if ac.mate_type(j) == "Angle" else "Distance"
    v = getattr(j, prop, 0.0)
    return round(float(getattr(v, "Value", v)), 6)


def set_mate_value(j, value):
    if ac.mate_type(j) == "Distance":
        ac.set_value(j, "Distance", float(value))
        return
    prop = "Angle" if ac.mate_type(j) == "Angle" else "Distance"
    setattr(j, prop, float(value))


def mate_keys(sim, name):
    return [k[0] for k in data(sim).get("mates", {}).get(name, [])]


def set_mate_key(sim, name, t, value, start=None):
    d = data(sim)
    rows = d.setdefault("mates", {}).setdefault(name, [])
    t = round(float(t), 4)
    if not rows and t > 0 and start is not None:
        rows.append([0.0, float(start)])
    for k in rows:
        if abs(k[0] - t) < 1e-6:
            k[1] = float(value)
            break
    else:
        rows.append([t, float(value)])
        rows.sort(key=lambda k: k[0])
    save(sim, d)


def delete_mate_key(sim, name, t):
    d = data(sim)
    rows = d.get("mates", {}).get(name, [])
    d.setdefault("mates", {})[name] = [k for k in rows if abs(k[0] - t) > 1e-6 or (k[0] == 0 and len(rows) == 1)]
    save(sim, d)


def move_mate_key(sim, name, t, new_t):
    d = data(sim)
    rows = d.get("mates", {}).get(name, [])
    new_t = max(0.0, round(float(new_t), 4))
    if any(abs(k[0] - new_t) < 1e-6 for k in rows if abs(k[0] - t) > 1e-6):
        return False
    for k in rows:
        if abs(k[0] - t) < 1e-6:
            k[0] = new_t
    rows.sort(key=lambda k: k[0])
    save(sim, d)
    return True


def mate_value_at(rows, t):
    if not rows:
        return None
    if t <= rows[0][0]:
        return rows[0][1]
    for a, b in zip(rows, rows[1:]):
        if a[0] <= t <= b[0]:
            f = 0.0 if b[0] <= a[0] else (t - a[0]) / (b[0] - a[0])
            return a[1] + (b[1] - a[1]) * f
    return rows[-1][1]


def apply_mates(asm, sim, t):
    """The keyed mates' values at t, then a solve; False when nothing changed."""
    doc = asm.Document
    changed = False
    for name, rows in live_data(sim).get("mates", {}).items():
        j = doc.getObject(name)
        v = mate_value_at(rows, t)
        if j is None or v is None:
            continue
        if abs(mate_value(j) - v) > 1e-9:
            set_mate_value(j, v)
            changed = True
    if changed:
        ac.solve(asm)
    return changed


# ---------------------------------------------------------------- the view (Rotate model)
class _Camera:
    """The camera at time 0, turned about the model's centre for the Rotate model keys."""

    def __init__(self):
        self.base = None

    def capture(self):
        try:
            cam = Gui.ActiveDocument.ActiveView.getCameraNode()
            o = cam.orientation.getValue()
            q = o.getValue()
            pos = cam.position.getValue()
            self.base = (App.Rotation(q[0], q[1], q[2], q[3]), V(pos[0], pos[1], pos[2]), cam.focalDistance.getValue())
        except Exception:
            self.base = None

    def turn(self, centre, axis, degrees):
        if self.base is None or axis is None:
            return
        from pivy import coin
        rot0, pos0, focal = self.base
        r = App.Rotation(V(*{"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1)}[axis]), -degrees)
        rot = r.multiply(rot0)
        new_pos = centre + r.multVec(pos0 - centre)
        try:
            cam = Gui.ActiveDocument.ActiveView.getCameraNode()
            q = rot.Q
            cam.orientation.setValue(coin.SbRotation(q[0], q[1], q[2], q[3]))
            cam.position.setValue(coin.SbVec3f(new_pos.x, new_pos.y, new_pos.z))
            cam.focalDistance.setValue(focal)
        except Exception as _fw_err:
            _fw_log("asmtimeline.py:552", _fw_err)


# ---------------------------------------------------------------- view keys (Orientation and Camera Views)
def camera_now():
    """[position xyz, orientation quaternion, height (orthographic) or height angle, focal distance]."""
    try:
        cam = Gui.ActiveDocument.ActiveView.getCameraNode()
        pos = list(cam.position.getValue().getValue())
        q = list(cam.orientation.getValue().getValue())
        h = cam.height.getValue() if hasattr(cam, "height") else cam.heightAngle.getValue()
        return [[round(x, 6) for x in pos], [round(x, 8) for x in q], round(float(h), 6),
                round(float(cam.focalDistance.getValue()), 6)]
    except Exception as _fw_err:
        _fw_log("asmtimeline.py:567", _fw_err)
        return None


def set_camera(c):
    from pivy import coin
    try:
        cam = Gui.ActiveDocument.ActiveView.getCameraNode()
        cam.position.setValue(coin.SbVec3f(*c[0]))
        cam.orientation.setValue(coin.SbRotation(*c[1]))
        if hasattr(cam, "height"):
            cam.height.setValue(c[2])
        else:
            cam.heightAngle.setValue(c[2])
        cam.focalDistance.setValue(c[3])
    except Exception as _fw_err:
        _fw_log("asmtimeline.py:581", _fw_err)


def same_camera(a, b, tol=1e-4):
    if a is None or b is None:
        return a is b
    return all(abs(x - y) < tol for x, y in zip(a[0] + a[1] + [a[2], a[3]], b[0] + b[1] + [b[2], b[3]]))


def view_keys(sim):
    return [k[0] for k in data(sim).get("cams", [])]


def set_view_key(sim, t, cam, start=None):
    d = data(sim)
    rows = d.setdefault("cams", [])
    t = round(float(t), 4)
    if not rows and t > 0 and start is not None:
        rows.append([0.0] + list(start))
    for k in rows:
        if abs(k[0] - t) < 1e-6:
            k[1:] = list(cam)
            break
    else:
        rows.append([t] + list(cam))
        rows.sort(key=lambda k: k[0])
    save(sim, d)


def delete_view_key(sim, t):
    d = data(sim)
    rows = d.get("cams", [])
    d["cams"] = [k for k in rows if abs(k[0] - t) > 1e-6 or (k[0] == 0 and len(rows) == 1)]
    save(sim, d)


def move_view_key(sim, t, new_t):
    d = data(sim)
    rows = d.get("cams", [])
    new_t = max(0.0, round(float(new_t), 4))
    if any(abs(k[0] - new_t) < 1e-6 for k in rows if abs(k[0] - t) > 1e-6):
        return False
    for k in rows:
        if abs(k[0] - t) < 1e-6:
            k[0] = new_t
    rows.sort(key=lambda k: k[0])
    save(sim, d)
    return True


def camera_at(rows, t):
    """The camera between view keys: position, zoom and focal distance straight, turn even."""
    if not rows:
        return None
    if t <= rows[0][0]:
        return rows[0][1:]
    for a, b in zip(rows, rows[1:]):
        if a[0] <= t <= b[0]:
            f = 0.0 if b[0] <= a[0] else (t - a[0]) / (b[0] - a[0])
            pos = [x + (y - x) * f for x, y in zip(a[1], b[1])]
            ra, rb = App.Rotation(*a[2]), App.Rotation(*b[2])
            q = list(ra.slerp(rb, f).Q)
            return [pos, q, a[3] + (b[3] - a[3]) * f, a[4] + (b[4] - a[4]) * f]
    return rows[-1][1:]


def apply_view_keys(sim, t):
    """Playback of view keys (unless Disable Playback of View Keys)."""
    rows = live_data(sim).get("cams", [])
    if len(rows) < 1 or study_option(sim, "no_view_playback"):
        return False
    c = camera_at(rows, t)
    if c is not None:
        set_camera(c)
    return True


def model_centre(asm):
    try:
        bb = None
        for c in ac.components(asm):
            s = c.Shape
            if s.isNull():
                continue
            if bb is None:
                bb = App.BoundBox(s.BoundBox)
            else:
                bb.add(s.BoundBox)
        return bb.Center if bb is not None else V()
    except Exception:
        return V()


# ---------------------------------------------------------------- Animation Wizard
def wizard_rotate(sim, axis="Y", turns=1, clockwise=True, duration=10.0, start=0.0):
    d = data(sim)
    d["view"].append([float(start), float(start) + float(duration), axis, float(turns), -1.0 if clockwise else 1.0])
    save(sim, d)


def _step_positions(asm, view):
    """[(step, {name: placement after it})], applied one by one from the mated positions, which
    are put back at the end."""
    from . import asmexplode as ax
    ax._props(view)
    was = ax.is_exploded(view)
    if was:
        ax.collapse(asm, view)
    comps = ac.components(asm) + ax.nested_parts(asm)
    base = {c.Name: App.Placement(c.Placement) for c in comps}
    out = []
    com, size = ax._ua().getComAndSize(asm)
    try:
        for step in view.Group:
            sd = ax.step_data(step)
            if sd:
                ax._apply_own(asm, step, sd)
            else:
                step.Proxy.applyStep(step, com, size)
            out.append((step, {c.Name: App.Placement(c.Placement) for c in comps}))
    finally:
        for c in comps:
            if c.Name in base:
                c.Placement = base[c.Name]
        for obj in [asm] + comps:
            obj.purgeTouched()
    return base, out



COLOURS = {
    "Drive motion": "#3d6fd6",          # a component keyed or driven (motor): blue
    "Followed motion": "#e6c21e",       # moved by its mates as another moves: yellow
    "Explode": "#f0861c",               # Animation Wizard Explode / Collapse: orange
    "Appearance": "#e66fc4",            # hide / show / colour: pink
    "Mate dimension": "#8a8a8a",        # a mate's distance or angle changing: grey
    "Key point": "#7a7a7a",             # any component or mate key point
    "Study key": "#505050",             # the study's own start and end keys
    "View": "#9a9a9a",                  # orientation and camera views
}


def explode_spans(d, name):
    return [tuple(sp) for sp in d.get("explode", {}).get(name, [])]


def bar_colour(d, name, t0, t1):
    """The changebar colour of a component row between two of its keys."""
    for a, b in explode_spans(d, name):
        if a - 1e-6 <= t0 and t1 <= b + 1e-6:
            return COLOURS["Explode"]
    return COLOURS["Drive motion"]


def wizard_explode(asm, sim, duration=10.0, start=0.0, collapse=False):
    """Keys that play the exploded view's steps one after the other over duration (Collapse: the
    other way, from exploded to mated)."""
    from . import asmexplode as ax
    vs = ax.views(asm)
    if not vs:
        return False
    base, steps = _step_positions(asm, vs[0])
    if not steps:
        return False
    states = [base] + [s for _st, s in steps]
    if collapse:
        states = list(reversed(states))
    n = len(states) - 1
    d = data(sim)
    for name in base:
        rows = d["comps"].setdefault(name, [])
        moving = [i for i in range(n) if not states[i][name].isSame(states[i + 1][name], 1e-9)]
        if not moving:
            continue        # only what the exploded view moves gets keys (a motor's component keeps its own motion)
        times = [start + duration * i / n for i in range(n + 1)]
        for i, t in enumerate(times):
            if i == 0 or i == n or (i in moving or i - 1 in moving):
                rows[:] = [k for k in rows if abs(k[0] - t) > 1e-6]
                rows.append([round(t, 4)] + _enc(states[i][name]))
        rows.sort(key=lambda k: k[0])
        spans = d.setdefault("explode", {}).setdefault(name, [])
        spans.append([round(start, 4), round(start + duration, 4)])
    save(sim, d)
    return True


def calculated(asm, sim, kind):
    """The last calculated Basic Motion or Motion Analysis of this study: (frames, duration, fps) or None."""
    from . import asmmotion as mo
    got = mo.CALCULATED.get((asm.Document.Name, sim.Name, kind))
    return got if got and len(got[0]) > 1 else None


def wizard_import(asm, sim, got, duration=None, start=0.0):
    """Import motion from Basic Motion / Motion Analysis: the calculated frames become key points
    of the study, spread over duration (the calculated one when None) from start. Only the
    components that move get keys; their keys in that span are replaced."""
    frames, calc_duration, _fps = got
    n = len(frames) - 1
    if n < 1:
        return False
    dur = float(duration) if duration else float(calc_duration)
    d = data(sim)
    moved = 0
    for name, plc0 in frames[0].items():
        if all(f.get(name) is None or f[name].isSame(plc0, 1e-9) for f in frames[1:]):
            continue
        rows = d["comps"].setdefault(name, [])
        rows[:] = [k for k in rows if k[0] < start - 1e-6 or k[0] > start + dur + 1e-6]
        for i, f in enumerate(frames):
            if f.get(name) is not None:
                rows.append([round(start + dur * i / n, 4)] + _enc(f[name]))
        rows.sort(key=lambda k: k[0])
        moved += 1
    if moved:
        save(sim, d)
    return moved > 0


class AnimationWizard(QtWidgets.QDialog):
    ""


    def __init__(self, asm, sim, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        from . import asmexplode as ax
        self.asm, self.sim = asm, sim
        self.setObjectName("SWAnimationWizard")
        self.setWindowTitle("Select an Animation Type")
        lay = QtWidgets.QVBoxLayout(self)
        self.stack = QtWidgets.QStackedWidget(self)
        lay.addWidget(self.stack)
        # page 1: the type
        p1 = QtWidgets.QWidget()
        l1 = QtWidgets.QVBoxLayout(p1)
        self.rotate = QtWidgets.QRadioButton("Rotate model")
        self.rotate.setObjectName("SWWizardRotate")
        self.explode = QtWidgets.QRadioButton("Explode")
        self.explode.setObjectName("SWWizardExplode")
        self.collapse = QtWidgets.QRadioButton("Collapse")
        self.collapse.setObjectName("SWWizardCollapse")
        self.delete_all = QtWidgets.QCheckBox("Delete all existing paths")
        self.delete_all.setObjectName("SWWizardDeleteAll")
        has_view = bool(ax.views(asm))
        self.explode.setVisible(has_view)   # no greyed choices: shown with an exploded view
        self.collapse.setVisible(has_view)
        self.rotate.setChecked(True)
        # Import motion from Basic Motion / Motion Analysis: shown in an Animation study once this study
        # has been calculated as that type (no greyed choices)
        from . import asmmotion as mo
        self.import_basic = QtWidgets.QRadioButton("Import motion from Basic Motion")
        self.import_basic.setObjectName("SWWizardImportBasic")
        self.import_analysis = QtWidgets.QRadioButton("Import motion from Motion Analysis")
        self.import_analysis.setObjectName("SWWizardImportAnalysis")
        anim = mo.study_type(sim) == mo.STUDY_TYPES[0]
        self.imports = {self.import_basic: calculated(asm, sim, mo.STUDY_TYPES[1]) if anim else None,
                        self.import_analysis: calculated(asm, sim, mo.STUDY_TYPES[2]) if anim else None}
        for r, got in self.imports.items():
            r.setVisible(got is not None)
        for w in (self.rotate, self.explode, self.collapse, self.import_basic, self.import_analysis):
            l1.addWidget(w)
        if not has_view:
            l1.addWidget(QtWidgets.QLabel("Explode and Collapse need an exploded view of the assembly."))
        l1.addStretch(1)
        l1.addWidget(self.delete_all)
        self.stack.addWidget(p1)
        # page 2: Rotate model
        p2 = QtWidgets.QWidget()
        l2 = QtWidgets.QFormLayout(p2)
        self.axis = {}
        row = QtWidgets.QHBoxLayout()
        for a in ("X", "Y", "Z"):
            r = QtWidgets.QRadioButton("%s-axis" % a)
            r.setObjectName("SWWizardAxis" + a)
            self.axis[a] = r
            row.addWidget(r)
        self.axis["Y"].setChecked(True)
        l2.addRow("Select an Axis of Rotation:", row)
        self.turns = QtWidgets.QSpinBox()
        self.turns.setObjectName("SWWizardTurns")
        self.turns.setRange(1, 100)
        self.turns.setValue(1)
        l2.addRow("Number of rotations:", self.turns)
        self.cw = QtWidgets.QRadioButton("Clockwise")
        self.cw.setObjectName("SWWizardClockwise")
        self.ccw = QtWidgets.QRadioButton("Counterclockwise")
        self.cw.setChecked(True)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.cw)
        row.addWidget(self.ccw)
        l2.addRow(row)
        self.stack.addWidget(p2)
        # page 3: Animation Control Options
        p3 = QtWidgets.QWidget()
        l3 = QtWidgets.QFormLayout(p3)
        self.duration = QtWidgets.QDoubleSpinBox()
        self.duration.setObjectName("SWWizardDuration")
        self.duration.setRange(0.1, 3600.0)
        self.duration.setValue(10.0)
        self.duration.setSuffix(" sec")
        l3.addRow("Duration:", self.duration)
        self.start = QtWidgets.QDoubleSpinBox()
        self.start.setObjectName("SWWizardStart")
        self.start.setRange(0.0, 3600.0)
        self.start.setSuffix(" sec")
        l3.addRow("Start Time:", self.start)
        for r, got in self.imports.items():      # an import takes the calculated duration
            if got is not None:
                r.toggled.connect(lambda on, g=got: on and self.duration.setValue(float(g[1])))
        self.stack.addWidget(p3)
        row = QtWidgets.QHBoxLayout()
        self.back = QtWidgets.QPushButton("< Back")
        self.next = QtWidgets.QPushButton("Next >")
        self.next.setObjectName("SWWizardNext")
        self.finish = QtWidgets.QPushButton("Finish")
        self.finish.setObjectName("SWWizardFinish")
        cancel = QtWidgets.QPushButton("Cancel")
        for b in (self.back, self.next, self.finish, cancel):
            row.addWidget(b)
        lay.addLayout(row)
        self.back.clicked.connect(self.go_back)
        self.next.clicked.connect(self.go_next)
        self.finish.clicked.connect(self.do_finish)
        cancel.clicked.connect(self.reject)
        self._buttons()

    def _pages(self):
        return [0, 1, 2] if self.rotate.isChecked() else [0, 2]

    def _buttons(self):
        pages = self._pages()
        i = pages.index(self.stack.currentIndex())
        self.back.setVisible(i > 0)         # no greyed buttons: each shows on the pages it works on
        self.next.setVisible(i < len(pages) - 1)
        self.finish.setVisible(i == len(pages) - 1)
        titles = {0: "Select an Animation Type", 1: "Select an Axis of Rotation", 2: "Animation Control Options"}
        self.setWindowTitle(titles[self.stack.currentIndex()])

    def go_next(self):
        pages = self._pages()
        i = pages.index(self.stack.currentIndex())
        if i < len(pages) - 1:
            self.stack.setCurrentIndex(pages[i + 1])
        self._buttons()

    def go_back(self):
        pages = self._pages()
        i = pages.index(self.stack.currentIndex())
        if i > 0:
            self.stack.setCurrentIndex(pages[i - 1])
        self._buttons()

    def imported(self):
        """The calculated motion picked to import, or None."""
        return next((got for r, got in self.imports.items() if got is not None and r.isChecked()), None)

    def do_finish(self):
        doc = self.asm.Document
        pane = getattr(self, "pane", None)
        was = getattr(pane, "_applying", False)
        if pane is not None:
            pane._applying = True               # working out the steps moves parts: no Autokey
        doc.openTransaction("Animation Wizard")
        try:
            if self.delete_all.isChecked():
                d = data(self.sim)
                d["comps"] = {n: rows[:1] for n, rows in d["comps"].items()}
                d["view"] = []
                d["explode"] = {}
                save(self.sim, d)
            dur, start = self.duration.value(), self.start.value()
            if self.rotate.isChecked():
                axis = next(a for a, r in self.axis.items() if r.isChecked())
                wizard_rotate(self.sim, axis, self.turns.value(), self.cw.isChecked(), dur, start)
            elif self.imported() is not None:
                wizard_import(self.asm, self.sim, self.imported(), dur, start)
            else:
                wizard_explode(self.asm, self.sim, dur, start, collapse=self.collapse.isChecked())
            end = start + dur
            if float(self.sim.bTimeEnd) < end:
                self.sim.bTimeEnd = end              # the study grows to hold the animation
        finally:
            doc.commitTransaction()
            if pane is not None:
                pane._applying = was
        self.accept()


# ---------------------------------------------------------------- Save Animation
def ffmpeg():
    return shutil.which("ffmpeg")


SAVE_TYPES = (("AVI (*.avi)", ".avi"), ("MP4 (*.mp4)", ".mp4"), ("Series of PNG files (*.png)", ".png"))


def save_animation(pane, path, width=1280, height=720, fps=None, start=None, end=None):
    """Renders the frames (Calculate first when needed) and writes the movie or the PNG series.
    Returns the files written."""
    if pane.frames <= 0 and not pane.calculate():
        return []
    fps = int(fps or pane.fps.value())
    step = float(pane.sim.cTimeStepOutput) or (1.0 / max(1, pane.fps.value()))
    first, last = pane.slider.minimum(), pane.slider.maximum()
    if start is not None:
        first = max(first, 1 + int(round(start / step)))
    if end is not None:
        last = min(last, 1 + int(round(end / step)))
    ext = os.path.splitext(path)[1].lower()
    view = Gui.ActiveDocument.ActiveView
    out = []
    tmp = tempfile.mkdtemp(prefix="fwanim") if ext != ".png" else None
    base = os.path.splitext(path)[0]
    pane.stop()
    for n, i in enumerate(range(first, last + 1)):
        pane.slider.setValue(i)
        pane.show_frame(i)
        name = os.path.join(tmp, "f%05d.png" % n) if tmp else "%s%04d.png" % (base, n)
        view.saveImage(name, int(width), int(height), "Current")
        out.append(name)
    if tmp is None:
        return out
    exe = ffmpeg()
    if exe is None or os.environ.get("FW_NO_FFMPEG"):
        if ext != ".avi":
            shutil.rmtree(tmp, ignore_errors=True)
            raise RuntimeError("MP4 needs ffmpeg: save as AVI or a series of PNG files instead")
        write_mjpeg_avi(path, out, fps)         # no ffmpeg on the computer: AVI written here
        shutil.rmtree(tmp, ignore_errors=True)
        return [path]
    codec = ["-c:v", "mjpeg", "-q:v", "3"] if ext == ".avi" else ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    cmd = [exe, "-y", "-loglevel", "error", "-framerate", str(fps), "-i", os.path.join(tmp, "f%05d.png")] + codec + [path]
    subprocess.run(cmd, check=True, timeout=600)
    shutil.rmtree(tmp, ignore_errors=True)
    return [path]


def write_mjpeg_avi(path, pngs, fps):
    """A Motion JPEG AVI (RIFF AVI 1.0, idx1 index) from the PNG frames: plays in Windows Media
    Player and every common player, and needs nothing but Qt."""
    import struct
    frames = []
    w = h = 0
    for f in pngs:
        img = QtGui.QImage(f)
        w, h = img.width(), img.height()
        buf = QtCore.QBuffer()
        buf.open(QtCore.QIODevice.WriteOnly)
        img.save(buf, "JPG", 90)
        frames.append(bytes(buf.data()))
    if not frames:
        raise RuntimeError("no frames to save")
    fps = max(1, int(fps))
    big = max(len(f) for f in frames)

    def chunk(cc, data):
        pad = b"\0" if len(data) % 2 else b""
        return cc + struct.pack("<I", len(data)) + data + pad

    def lst(kind, data):
        return b"LIST" + struct.pack("<I", len(data) + 4) + kind + data

    avih = struct.pack("<IIIIIIIIIIIIII", int(1000000 / fps), big * fps, 0, 0x10, len(frames), 0, 1,
                       big, w, h, 0, 0, 0, 0)
    strh = struct.pack("<4s4sIHHIIIIIIIIhhhh", b"vids", b"MJPG", 0, 0, 0, 0, 1, fps, 0, len(frames),
                       big, 0xFFFFFFFF, 0, 0, 0, w, h)
    strf = struct.pack("<IiiHH4sIiiII", 40, w, h, 1, 24, b"MJPG", w * h * 3, 0, 0, 0, 0)
    hdrl = lst(b"hdrl", chunk(b"avih", avih) + lst(b"strl", chunk(b"strh", strh) + chunk(b"strf", strf)))
    movi_data = b""
    index = b""
    for f in frames:
        index += struct.pack("<4sIII", b"00dc", 0x10, len(movi_data) + 4, len(f))
        movi_data += chunk(b"00dc", f)
    body = b"AVI " + hdrl + lst(b"movi", movi_data) + chunk(b"idx1", index)
    with open(path, "wb") as fh:
        fh.write(b"RIFF" + struct.pack("<I", len(body)) + body)
    return path


class SaveAnimationDialog(QtWidgets.QDialog):
    ""


    def __init__(self, pane, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.pane = pane
        self.setObjectName("SWSaveAnimation")
        self.setWindowTitle("Save Animation to File")
        lay = QtWidgets.QFormLayout(self)
        doc = pane.asm.Document
        folder = os.path.dirname(doc.FileName) if doc.FileName else os.path.expanduser("~")
        row = QtWidgets.QHBoxLayout()
        self.path = QtWidgets.QLineEdit(os.path.join(folder, "%s.avi" % doc.Label))
        self.path.setObjectName("SWSaveAnimationPath")
        browse = QtWidgets.QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        row.addWidget(self.path, 1)
        row.addWidget(browse)
        lay.addRow("File name:", row)
        self.kind = QtWidgets.QComboBox()
        self.kind.setObjectName("SWSaveAnimationType")
        for label, ext in SAVE_TYPES:
            self.kind.addItem(label, ext)
        if ffmpeg() is None:
            self.kind.model().item(1).setToolTip("MP4 needs ffmpeg on the computer; AVI and PNG are written here")
        self.kind.currentIndexChanged.connect(self._ext)
        lay.addRow("Save as type:", self.kind)
        self.width = QtWidgets.QSpinBox()
        self.width.setObjectName("SWSaveAnimationWidth")
        self.width.setRange(16, 8192)
        self.width.setValue(1280)
        self.height = QtWidgets.QSpinBox()
        self.height.setObjectName("SWSaveAnimationHeight")
        self.height.setRange(16, 8192)
        self.height.setValue(720)
        self.aspect = QtWidgets.QCheckBox("Fixed aspect ratio")
        self.aspect.setChecked(True)
        self.width.valueChanged.connect(self._w)
        size = QtWidgets.QHBoxLayout()
        size.addWidget(self.width)
        size.addWidget(QtWidgets.QLabel("x"))
        size.addWidget(self.height)
        size.addWidget(self.aspect)
        lay.addRow("Image size:", size)
        self.fps = QtWidgets.QSpinBox()
        self.fps.setObjectName("SWSaveAnimationFps")
        self.fps.setRange(1, 240)
        self.fps.setValue(pane.fps.value())
        lay.addRow("Frames per second:", self.fps)
        self.entire = QtWidgets.QRadioButton("Entire animation")
        self.entire.setChecked(True)
        self.range = QtWidgets.QRadioButton("Time range")
        self.t0 = QtWidgets.QDoubleSpinBox()
        self.t1 = QtWidgets.QDoubleSpinBox()
        for s in (self.t0, self.t1):
            s.setRange(0.0, 3600.0)
            s.setSuffix(" sec")
        self.t1.setValue(pane.duration.value())
        rr = QtWidgets.QHBoxLayout()
        for w in (self.entire, self.range, self.t0, QtWidgets.QLabel("to"), self.t1):
            rr.addWidget(w)
        lay.addRow("Frames to Output:", rr)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.do_save)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)
        self.written = []
        self._ext()

    def _w(self, v):
        if self.aspect.isChecked():
            self.height.blockSignals(True)
            self.height.setValue(int(round(v * 9 / 16.0)))
            self.height.blockSignals(False)

    def _ext(self, *a):
        ext = self.kind.currentData()
        p = os.path.splitext(self.path.text())[0] + ext
        self.path.setText(p)

    def _browse(self):
        p, _f = QtWidgets.QFileDialog.getSaveFileName(self, "Save Animation to File", self.path.text(),
                                                      ";;".join(l for l, _e in SAVE_TYPES))
        if p:
            self.path.setText(p)

    def do_save(self):
        start = self.t0.value() if self.range.isChecked() else None
        end = self.t1.value() if self.range.isChecked() else None
        try:
            self.written = save_animation(self.pane, self.path.text(), self.width.value(), self.height.value(),
                                          self.fps.value(), start, end)
        except Exception as error:
            QtWidgets.QMessageBox.warning(self, "Save Animation", str(error))
            return
        self.accept()


# ---------------------------------------------------------------- Motion Study Properties
OPTIONS_PROP = "FwStudyOptions"
OPTION_DEFAULTS = {"anim_fps": 25, "basic_fps": 25, "full_names": False, "tooltips": True,
                   "no_view_keys": False, "no_view_playback": False,
                   "contact_res": 50, "precise_contact": False,
                   "ma_fps": 25, "ma_animate": True, "ma_replay": 1}
REPLAY_SPEEDS = ("0.5x", "1x", "2x", "Real time")
_PARAM = "User parameter:BaseApp/Preferences/Mod/FreeWorks/MotionStudy"


def study_options(sim):
    out = dict(OPTION_DEFAULTS)
    g = App.ParamGet(_PARAM)
    for k, v in OPTION_DEFAULTS.items():                 # Make default: the saved defaults
        if isinstance(v, bool):
            out[k] = g.GetBool(k, v)
        else:
            out[k] = g.GetInt(k, v)
    try:
        out.update(json.loads(getattr(sim, OPTIONS_PROP, "") or "{}"))
    except Exception as _fw_err:
        _fw_log("asmtimeline.py:1126", _fw_err)
    return out


def study_option(sim, key):
    return study_options(sim).get(key)


def set_study_options(sim, values, make_default=False):
    if not hasattr(sim, OPTIONS_PROP):
        sim.addProperty("App::PropertyString", OPTIONS_PROP, "FreeCAD", "Motion Study Properties (json)")
        sim.setEditorMode(OPTIONS_PROP, 2)
    d = study_options(sim)
    d.update(values)
    setattr(sim, OPTIONS_PROP, json.dumps(d))
    if make_default:
        g = App.ParamGet(_PARAM)
        for k, v in d.items():
            (g.SetBool if isinstance(v, bool) else g.SetInt)(k, v)
    return d


def full_name(comp):
    ""
    cfg = "Default"
    try:
        from . import asmmenu, configmanager as cm
        doc = asmmenu.part_document(comp)
        t = cm.table(doc) if doc is not None else None
        if t is not None:
            cfg = t.active()
    except Exception as _fw_err:
        _fw_log("asmtimeline.py:1158", _fw_err)
    return "%s (%s)" % (comp.Label, cfg)


class MotionStudyProperties(QtWidgets.QDialog):
    ""



    def __init__(self, pane, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.pane = pane
        self.setObjectName("SWMotionStudyProperties")
        self.setWindowTitle("Motion Study Properties")
        o = study_options(pane.sim)
        lay = QtWidgets.QVBoxLayout(self)

        def group(title):
            g = QtWidgets.QGroupBox(title)
            f = QtWidgets.QFormLayout(g)
            lay.addWidget(g)
            return f

        def spin(name, v):
            w = QtWidgets.QSpinBox()
            w.setObjectName(name)
            w.setRange(1, 240)
            w.setValue(int(v))
            return w

        f = group("Animation")
        self.anim_fps = spin("FW_MSPAnimFps", o["anim_fps"])
        f.addRow("Frames per second:", self.anim_fps)
        f = group("Basic Motion")
        self.basic_fps = spin("FW_MSPBasicFps", o["basic_fps"])
        f.addRow("Frames per second:", self.basic_fps)
        r = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        r.setObjectName("FW_MSPContactRes")
        r.setRange(1, 100)
        r.setValue(int(o["contact_res"]))
        r.setToolTip("3D contact resolution: higher finds contacts between smaller steps (slower)")
        self.contact_res = r
        f.addRow("3D contact resolution:", r)
        self.precise = QtWidgets.QCheckBox("Use precise contact")
        self.precise.setObjectName("FW_MSPPreciseContact")
        self.precise.setChecked(bool(o["precise_contact"]))
        f.addRow(self.precise)
        f = group("Motion Analysis")
        self.ma_fps = spin("FW_MSPMaFps", o["ma_fps"])
        f.addRow("Frames per second:", self.ma_fps)
        self.ma_animate = QtWidgets.QCheckBox("Animate during simulation")
        self.ma_animate.setObjectName("FW_MSPAnimateDuring")
        self.ma_animate.setChecked(bool(o["ma_animate"]))
        f.addRow(self.ma_animate)
        self.ma_replay = QtWidgets.QComboBox()
        self.ma_replay.setObjectName("FW_MSPReplaySpeed")
        self.ma_replay.addItems(list(REPLAY_SPEEDS))
        self.ma_replay.setCurrentIndex(int(o["ma_replay"]))
        f.addRow("Replay speed:", self.ma_replay)
        f = group("General Options")
        self.full_names = QtWidgets.QCheckBox("Display full names")
        self.full_names.setObjectName("FW_MSPFullNames")
        self.full_names.setChecked(bool(o["full_names"]))
        self.tooltips = QtWidgets.QCheckBox("Display all MotionManager tooltips")
        self.tooltips.setObjectName("FW_MSPTooltips")
        self.tooltips.setChecked(bool(o["tooltips"]))
        self.make_default = QtWidgets.QCheckBox("Make default")
        self.make_default.setObjectName("FW_MSPMakeDefault")
        for w in (self.full_names, self.tooltips, self.make_default):
            f.addRow(w)
        b = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        lay.addWidget(b)

    def accept(self):
        sim = self.pane.sim
        set_study_options(sim, {"anim_fps": self.anim_fps.value(), "basic_fps": self.basic_fps.value(),
                                "full_names": self.full_names.isChecked(), "tooltips": self.tooltips.isChecked(),
                                "contact_res": self.contact_res.value(), "precise_contact": self.precise.isChecked(),
                                "ma_fps": self.ma_fps.value(), "ma_animate": self.ma_animate.isChecked(),
                                "ma_replay": self.ma_replay.currentIndex()},
                          self.make_default.isChecked())
        self.pane.apply_study_fps()
        self.pane.timeline.update()
        super().accept()


# ---------------------------------------------------------------- any key: copy, paste, move, select
# kind: "key" component placement, "look" appearance, "mate" mate dimension, "cam" view orientation
SECTIONS = {"key": "comps", "look": "look", "mate": "mates", "cam": "cams"}


def _rows(d, kind, name, make=False):
    if kind == "cam":
        return d.setdefault("cams", []) if make else d.get("cams", [])
    box = d.setdefault(SECTIONS[kind], {}) if make else d.get(SECTIONS[kind], {})
    return box.setdefault(name, []) if make else box.get(name, [])


def key_payload(sim, kind, name, t):
    """What the key holds (everything after its time), or None."""
    for k in _rows(data(sim), kind, name):
        if abs(k[0] - t) < 1e-6:
            return list(k[1:])
    return None


def put_key(sim, kind, name, t, payload):
    """Paste: a key with payload at t (a key already there takes it)."""
    d = data(sim)
    rows = _rows(d, kind, name, True)
    t = max(0.0, round(float(t), 4))
    for k in rows:
        if abs(k[0] - t) < 1e-6:
            k[1:] = list(payload)
            break
    else:
        rows.append([t] + list(payload))
        rows.sort(key=lambda k: k[0])
    save(sim, d)


def delete_any(sim, kind, name, t):
    _move_suppressed(sim, kind, name, t)
    {"key": lambda: delete_key(sim, name, t), "look": lambda: delete_look_key(sim, name, t),
     "mate": lambda: delete_mate_key(sim, name, t), "cam": lambda: delete_view_key(sim, t)}[kind]()


def move_any(sim, kind, name, t, new_t):
    done = {"key": lambda: move_key(sim, name, t, new_t), "look": lambda: move_look_key(sim, name, t, new_t),
            "mate": lambda: move_mate_key(sim, name, t, new_t), "cam": lambda: move_view_key(sim, t, new_t)}[kind]()
    if done is not False:
        _move_suppressed(sim, kind, name, t, new_t)
    return done


def all_keys(sim):
    """Every key of the study as (kind, name, t), the ones at 0 too."""
    d = data(sim)
    out = [("cam", "__view__", k[0]) for k in d.get("cams", [])]
    for kind in ("key", "look", "mate"):
        for name, rows in d.get(SECTIONS[kind], {}).items():
            out += [(kind, name, k[0]) for k in rows]
    return out


def current_payload(asm, kind, name):
    """Replace Key: what the component, mate or view is now."""
    doc = asm.Document
    if kind == "key":
        obj = doc.getObject(name)
        return _enc(obj.Placement) if obj is not None else None
    if kind == "look":
        obj = doc.getObject(name)
        return list(look_of(obj)) if obj is not None else None
    if kind == "mate":
        obj = doc.getObject(name)
        return [float(mate_value(obj))] if obj is not None else None
    cam = camera_now()
    return list(cam) if cam is not None else None


LAST_DIALOG = {}
KIND_TEXT = {"key": "Component", "look": "Appearance", "mate": "Mate", "cam": "Orientation and Camera Views"}


class KeyProperties(QtWidgets.QDialog):
    """Key Properties: what the key is and holds; its time, interpolation and suppression can be
    changed here (OK applies them, one Undo step each)."""

    def __init__(self, timeline, hit):
        super().__init__(timeline)
        self.setObjectName("FW_KeyProperties")
        self.setWindowTitle("Key Properties")
        self.timeline, self.hit = timeline, tuple(hit)
        sim = timeline.pane.sim
        kind, name, t = self.hit
        doc = timeline.pane.asm.Document
        obj = doc.getObject(name) if kind != "cam" else None
        form = QtWidgets.QFormLayout(self)
        form.addRow("Key:", QtWidgets.QLabel(KIND_TEXT.get(kind, kind)))
        if obj is not None:
            form.addRow("Of:", QtWidgets.QLabel(obj.Label))
        self.time = QtWidgets.QDoubleSpinBox()
        self.time.setObjectName("FW_KeyPropTime")
        self.time.setRange(0.0, 100000.0)
        self.time.setDecimals(3)
        self.time.setSuffix(" s")
        self.time.setValue(t)
        if t > 0:
            form.addRow("Time:", self.time)
        else:                               # the start key stays at 0: shown as text (not greyed)
            self.time.setParent(self)
            self.time.hide()
            form.addRow("Time:", QtWidgets.QLabel("0.000 s"))
        payload = key_payload(sim, kind, name, t) or []
        if kind == "key" and len(payload) >= 2:
            plc = App.Placement(V(*payload[0]), App.Rotation(*payload[1]))
            form.addRow("Position:", QtWidgets.QLabel("%.3f, %.3f, %.3f mm" % tuple(plc.Base)))
            axis, ang = plc.Rotation.Axis, plc.Rotation.Angle
            form.addRow("Rotation:", QtWidgets.QLabel("%.2f deg about (%.3f, %.3f, %.3f)"
                                                      % (math.degrees(ang), axis.x, axis.y, axis.z)))
        elif kind == "mate" and payload:
            form.addRow("Value:", QtWidgets.QLabel("%g" % float(payload[0])))
        self.mode = None
        if kind == "key" and t > 0:
            self.mode = QtWidgets.QComboBox()
            self.mode.setObjectName("FW_KeyPropInterpolation")
            for m in INTERPOLATION:
                self.mode.addItem(INTERPOLATION_TEXT[m], m)
            self.mode.setCurrentIndex(INTERPOLATION.index(interpolation(sim, name, t) or "Linear"))
            form.addRow("Interpolation mode:", self.mode)
        self.suppress = QtWidgets.QCheckBox("Suppress Key")
        self.suppress.setObjectName("FW_KeyPropSuppress")
        self.suppress.setChecked(is_suppressed(sim, kind, name, t))
        if t > 0:
            form.addRow(self.suppress)
        else:                               # the start key cannot be suppressed: not shown
            self.suppress.setParent(self)
            self.suppress.hide()
        box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def accept(self):
        tl, (kind, name, t) = self.timeline, self.hit
        sim = tl.pane.sim
        if self.mode is not None and self.mode.currentData() != (interpolation(sim, name, t) or "Linear"):
            tl.interpolate(name, t, self.mode.currentData())
        if self.suppress.isChecked() != is_suppressed(sim, kind, name, t):
            tl.suppress((kind, name, t), self.suppress.isChecked())
        if abs(self.time.value() - t) > 1e-6:
            tl.edit_time((kind, name, t), self.time.value())
        super().accept()


def _bar_icon(kind):
    """The MotionManager's small filter and zoom buttons, drawn (16 px): a funnel with a mark for
    the four filters (key point, motor arrow, pointer, chart), a lens for the zooms; FreeCAD's own
    zoom pictures when it has them."""
    std = {"zoom_in": ":/icons/zoom-in.svg", "zoom_out": ":/icons/zoom-out.svg", "zoom_fit": ":/icons/zoom-all.svg"}
    if kind in std and QtCore.QFile.exists(std[kind]):
        return QtGui.QIcon(std[kind])
    pm = QtGui.QPixmap(32, 32)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    blue, dark = QtGui.QColor("#3d6fd6"), QtGui.QColor("#1d4f9e")
    pen = QtGui.QPen(dark, 2)
    p.setPen(pen)
    if kind.startswith("zoom"):
        p.setBrush(QtGui.QColor("#ffffff"))
        p.drawEllipse(QtCore.QRectF(4, 4, 18, 18))
        p.setPen(QtGui.QPen(dark, 4))
        p.drawLine(QtCore.QPointF(19, 19), QtCore.QPointF(28, 28))
        p.setPen(QtGui.QPen(blue, 2.5))
        if kind in ("zoom_in", "zoom_out"):
            p.drawLine(QtCore.QPointF(8, 13), QtCore.QPointF(18, 13))
        if kind == "zoom_in":
            p.drawLine(QtCore.QPointF(13, 8), QtCore.QPointF(13, 18))
        if kind == "zoom_fit":
            p.drawRect(QtCore.QRectF(9, 9, 8, 8))
    else:
        p.setBrush(QtGui.QColor("#e8eef9"))
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(2, 3), QtCore.QPointF(22, 3), QtCore.QPointF(14, 13),
                                       QtCore.QPointF(14, 22), QtCore.QPointF(10, 25), QtCore.QPointF(10, 13)]))
        p.setPen(QtGui.QPen(blue, 2))
        p.setBrush(blue)
        if kind == "animated":          # a key point diamond
            p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(24, 16), QtCore.QPointF(30, 23), QtCore.QPointF(24, 30),
                                           QtCore.QPointF(18, 23)]))
        elif kind == "driving":         # a turning motor arrow
            p.setBrush(Qt.NoBrush)
            p.drawArc(QtCore.QRectF(17, 16, 12, 12), 30 * 16, 270 * 16)
            p.setBrush(blue)
            p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(27, 14), QtCore.QPointF(31, 20), QtCore.QPointF(25, 20)]))
        elif kind == "selected":        # a pointer
            p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(18, 15), QtCore.QPointF(30, 24), QtCore.QPointF(24, 25),
                                           QtCore.QPointF(22, 31)]))
        else:                           # results: a small chart
            p.setBrush(Qt.NoBrush)
            p.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(17, 30), QtCore.QPointF(21, 22), QtCore.QPointF(25, 26),
                                            QtCore.QPointF(30, 16)]))
    p.end()
    return QtGui.QIcon(pm)


class TimelineBar(QtWidgets.QWidget):
    """Above the MotionManager tree and timeline: the filters (Animated, Driving, Selected,
    Results; one at a time, none = everything) and Zoom In, Zoom Out, Zoom to Fit."""

    FILTERS = (("FW_FilterAnimated", "Filter Animated", "animated"), ("FW_FilterDriving", "Filter Driving", "driving"),
               ("FW_FilterSelected", "Filter Selected", "selected"), ("FW_FilterResults", "Filter Results", "results"))

    def __init__(self, timeline):
        super().__init__()
        self.timeline = timeline
        self.setObjectName("FW_TimelineBar")
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.buttons = {}
        for name, text, key in self.FILTERS:
            b = QtWidgets.QToolButton()
            b.setObjectName(name)
            b.setText(text.replace("Filter ", ""))
            b.setToolTip(text)
            b.setCheckable(True)
            b.setIcon(_bar_icon(key))
            b.setIconSize(QtCore.QSize(16, 16))
            b.setToolButtonStyle(Qt.ToolButtonIconOnly)
            b.setAutoRaise(True)
            b.toggled.connect(lambda on, k=key: self._filter(k, on))
            row.addWidget(b)
            self.buttons[key] = b
        row.addStretch(1)
        for name, text, slot in (("FW_ZoomIn", "Zoom In", timeline.zoom_in), ("FW_ZoomOut", "Zoom Out", timeline.zoom_out),
                                 ("FW_ZoomFit", "Zoom to Fit", timeline.zoom_fit)):
            b = QtWidgets.QToolButton()
            b.setObjectName(name)
            b.setText(text)
            b.setToolTip(text)
            b.setIcon(_bar_icon(name[3:].replace("ZoomIn", "zoom_in").replace("ZoomOut", "zoom_out").replace("ZoomFit", "zoom_fit")))
            b.setIconSize(QtCore.QSize(16, 16))
            b.setToolButtonStyle(Qt.ToolButtonIconOnly)
            b.setAutoRaise(True)
            b.clicked.connect(slot)
            row.addWidget(b)

    def _filter(self, key, on):
        if on:
            for k, b in self.buttons.items():
                if k != key and b.isChecked():
                    b.blockSignals(True)
                    b.setChecked(False)
                    b.blockSignals(False)
            self.timeline.set_filter(key)
        elif self.timeline.filter == key:
            self.timeline.set_filter(None)


# ---------------------------------------------------------------- the timeline widget
class Timeline(QtWidgets.QWidget):
    """The MotionManager's timeline: the study row and a row per component, key diamonds, time bar."""

    ROW = 18
    LEFT = 210
    TOP = 20

    def __init__(self, pane):
        super().__init__()
        self.pane = pane
        self.setObjectName("FW_MotionTimeline")
        self.setMinimumHeight(self.TOP + self.ROW * 3)
        self.setMouseTracking(True)
        self.time = 0.0
        self.drag = None            # ("bar",) / ("key", name, t) / ("end",)
        self.selected = set()       # selected keys (kind, name, t): click, Ctrl+click, Select All
        self.setFocusPolicy(Qt.ClickFocus)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

        # its vertical scroll bar at the right edge (shown only when the rows do not fit)
        self.vrow = 0
        self.vbar = QtWidgets.QScrollBar(Qt.Vertical, self)
        self.vbar.setObjectName("FW_MotionTreeScroll")
        self.vbar.valueChanged.connect(self._scrolled)
        self.vbar.hide()

    # geometry
    def span(self):
        return max(float(self.pane.duration.value()), end_time(self.pane.sim), 0.1)

    zoom = 1.0          # Zoom In / Zoom Out: the share of the study shown
    offset = 0.0        # the time at the left edge when zoomed in
    filter = None       # MotionManager filters: None, "animated", "driving", "selected", "results"

    def visible(self):
        return self.span() / max(1.0, self.zoom)

    def x_of(self, t):
        w = max(1, self.width() - self.LEFT - 10)
        return self.LEFT + w * (t - self.offset) / self.visible()

    def t_of(self, x):
        w = max(1, self.width() - self.LEFT - 10)
        step = 1.0 / max(1, self.pane.fps.value())
        t = max(0.0, self.offset + (x - self.LEFT) * self.visible() / w)
        return round(round(t / step) * step, 4)

    def zoom_in(self):
        self.set_zoom(self.zoom * 2.0)

    def zoom_out(self):
        self.set_zoom(self.zoom / 2.0)

    def zoom_fit(self):
        self.set_zoom(1.0)

    def set_zoom(self, z):
        ""
        self.zoom = max(1.0, min(64.0, z))
        vis = self.visible()
        self.offset = 0.0 if self.zoom == 1.0 else max(0.0, min(self.span() - vis, self.time - vis / 2.0))
        self.update()

    def set_filter(self, f):
        self.filter = f
        self.setMinimumHeight(self.TOP + self.ROW * max(3, len(self.rows())))
        self.update()

    def _root_text(self):
        ""

        try:
            from . import asmui
            return asmui.top_text(self.pane.asm)
        except Exception as _fw_err:
            _fw_log("asmtimeline.py:root row", _fw_err)
            return self.pane.sim.Label

    def driving(self):
        """[(label, key)] the study's motors, springs, dampers, forces and contacts."""
        out = []
        try:
            from . import asmmotion, asmloads
            for m in asmmotion.motors(self.pane.sim):
                out.append((m.Label, "__drv__:" + m.Name))
            for r in asmloads.loads(self.pane.sim):
                out.append((r["name"], "__drv__:" + r["name"]))
        except Exception as _fw_err:
            _fw_log("asmtimeline.py:1506", _fw_err)
        return out

    def _row_icon(self, name):
        """The row's tree icon: a component's own, else a standard one for the study, views, mates, motors."""
        st = QtWidgets.QApplication.style()
        try:
            if name is None:            # the top row is the assembly: its tree icon
                icon = getattr(getattr(self.pane.asm, "ViewObject", None), "Icon", None)
                return icon if icon is not None and not icon.isNull() else st.standardIcon(QtWidgets.QStyle.SP_MediaPlay)
            if name == "__view__":
                return st.standardIcon(QtWidgets.QStyle.SP_DesktopIcon)
            if name.startswith("__mate__:"):
                o = self.pane.asm.Document.getObject(name[9:])
            elif name.startswith("__"):
                return st.standardIcon(QtWidgets.QStyle.SP_BrowserReload)
            else:
                o = self.pane.asm.Document.getObject(name)
            vo = getattr(o, "ViewObject", None)
            return vo.Icon if vo is not None else None
        except Exception:
            return None

    def rows(self):
        """[(label, name or None)]: the study row, Orientation and Camera Views, the components,
        then the driving elements (motors, springs, forces), as the MotionManager design tree,
        cut down by its filter."""
        out = [(self._root_text(), None)]
        full = study_option(self.pane.sim, "full_names")
        comps = [(full_name(c) if full else c.Label, c.Name) for c in ac.components(self.pane.asm)]
        drv = self.driving()
        f = self.filter
        mates = [(j.Label.split(" (")[0], "__mate__:" + j.Name) for j in keyable_mates(self.pane.asm)]
        if f is None:
            return out + [("Orientation and Camera Views", "__view__")] + comps + mates + drv
        if f == "animated":
            d = data(self.pane.sim)
            moving = set(n for n, rows in d["comps"].items()
                         if len({json.dumps(r[1:3]) for r in rows}) > 1)
            own = getattr(self.pane, "own", None)
            if own and own[0]:
                first, last = own[0][0], own[0][-1]
                moving |= {n for n, plc in last.items() if n in first and not plc.isSame(first[n], 1e-9)}
            view = [("Orientation and Camera Views", "__view__")] if d["view"] or len(d.get("cams", [])) > 1 else []
            mv = [r for r in mates if len(d.get("mates", {}).get(r[1][9:], [])) > 1]
            return out + view + [r for r in comps if r[1] in moving] + mv
        if f == "driving":
            return out + drv
        if f == "selected":
            names = set()
            for sel in Gui.Selection.getSelectionEx(self.pane.asm.Document.Name):
                names.add(sel.ObjectName)
                names |= {x.split(".")[0] for x in sel.SubElementNames or ()}
            return out + [r for r in comps if r[1] in names]
        if f == "results":
            own = getattr(self.pane, "own", None)
            res = own[1] if own and isinstance(own[1], dict) and not own[1].get("keyed") else {}
            return out + [r for r in comps if r[1] in res]
        return out + comps

    def event(self, e):
        if e.type() == QtCore.QEvent.ToolTip:
            hit = self.key_at(e.pos())
            if hit is not None and study_option(self.pane.sim, "tooltips"):
                if hit[0] == "key":
                    mode = interpolation(self.pane.sim, hit[1], hit[2])
                    obj = self.pane.asm.Document.getObject(hit[1])
                    QtWidgets.QToolTip.showText(e.globalPos(), "%s\nTime: %.2f sec\nInterpolation: %s"
                                                % (obj.Label if obj else hit[1], hit[2], mode), self)
                else:
                    QtWidgets.QToolTip.showText(e.globalPos(), "Duration: %.2f sec" % self.pane.duration.value(), self)
            else:
                QtWidgets.QToolTip.hideText()
            return True
        return super().event(e)

    def sizeHint(self):
        return QtCore.QSize(600, self.TOP + self.ROW * len(self.rows()) + 4)

    def _shown_rows(self):
        return max(1, (self.height() - self.TOP) // self.ROW)

    def _fit_bar(self):
        """The scroll bar's range for the rows there are now (rows added or the pane resized)."""
        extra = max(0, len(self.rows()) - self._shown_rows())
        self.vbar.blockSignals(True)
        self.vbar.setRange(0, extra)
        self.vbar.setPageStep(self._shown_rows())
        self.vrow = min(self.vrow, extra)
        self.vbar.setValue(self.vrow)
        self.vbar.blockSignals(False)
        w = self.vbar.sizeHint().width()
        self.vbar.setGeometry(self.width() - w, self.TOP, w, max(0, self.height() - self.TOP))
        self.vbar.setVisible(extra > 0)

    def _scrolled(self, v):
        self.vrow = int(v)
        self.update()

    def scroll_to_row(self, r):
        """Scrolls so that row r of rows() is in view."""
        n = self._shown_rows()
        if r < self.vrow:
            self.vrow = r
        elif r >= self.vrow + n:
            self.vrow = r - n + 1
        self._fit_bar()
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_bar()

    def wheelEvent(self, e):
        if self.vbar.isVisible():
            step = -1 if e.angleDelta().y() > 0 else 1
            self.vbar.setValue(self.vbar.value() + step * 3)
            e.accept()
            return
        super().wheelEvent(e)

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        pal = self.palette()
        p.fillRect(self.rect(), pal.base())
        text = pal.text().color()
        grid = QtGui.QColor(text)
        grid.setAlpha(40)
        span = self.span()
        vis = self.visible()
        step = next((st for st in (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
                     if vis / st <= 20), 120.0)
        p.setPen(text)
        t = math.floor(self.offset / step) * step

        every = max(1, int(math.ceil(46.0 / max(1e-6, self.x_of(step) - self.x_of(0.0)))))
        lane = QtCore.QRect(self.LEFT - 6, 0, self.width() - self.LEFT + 6, self.height())
        p.setClipRect(lane)
        while t <= min(span, self.offset + vis) + 1e-9:
            x = self.x_of(t)
            p.setPen(grid)
            p.drawLine(int(x), self.TOP, int(x), self.height())
            p.setPen(text)
            if int(round(t / step)) % every == 0:
                if x - 24 < self.LEFT:
                    p.drawText(int(x) + 2, 2, 60, self.TOP - 4, Qt.AlignLeft | Qt.AlignVCenter, "%g sec" % round(t, 4))
                else:
                    p.drawText(int(x) - 24, 2, 48, self.TOP - 4, Qt.AlignCenter, "%g sec" % round(t, 4))
            t += step
        d = data(self.pane.sim)
        self._fit_bar()
        for r, (label, name) in enumerate(self.rows()):
            if r < self.vrow:
                continue
            y = self.TOP + (r - self.vrow) * self.ROW
            if y >= self.height():
                break
            p.setClipping(False)
            p.setPen(text)
            ic = self._row_icon(name)
            pad = 4
            if ic is not None and not ic.isNull():
                isz = min(16, self.ROW - 2)
                ic.paint(p, 3, int(y + (self.ROW - isz) / 2), isz, isz)
                pad = isz + 6
            p.drawText(pad, y, self.LEFT - pad - 4, self.ROW, Qt.AlignVCenter | Qt.AlignLeft,
                       p.fontMetrics().elidedText(label, Qt.ElideRight, self.LEFT - pad - 4))
            p.setClipRect(lane)
            if name is not None and name.startswith("__drv__:"):
                p.setPen(QtGui.QPen(QtGui.QColor(COLOURS["Drive motion"]), 3))      # a motor acts the whole study
                p.drawLine(int(self.x_of(0.0)), y + self.ROW // 2, int(self.x_of(float(self.pane.duration.value()))),
                           y + self.ROW // 2)
                for kt in (0.0, float(self.pane.duration.value())):
                    self._diamond(p, self.x_of(kt), y + self.ROW / 2.0, False, COLOURS["Drive motion"])
                continue
            mid = y + self.ROW // 2
            if name is None:
                ts = [0.0, float(self.pane.duration.value())]
            elif name == "__view__":
                ts = sorted({s[0] for s in d["view"]} | {s[1] for s in d["view"]} | {k[0] for k in d.get("cams", [])})
            elif name.startswith("__mate__:"):
                ts = [k[0] for k in d.get("mates", {}).get(name[9:], [])]
            else:
                ts = [k[0] for k in d["comps"].get(name, [])]
            if len(ts) > 1 and name is not None:
                for t0, t1 in zip(ts, ts[1:]):
                    if name == "__view__":
                        colour = COLOURS["View"]
                    elif name.startswith("__mate__:"):
                        colour = COLOURS["Mate dimension"]
                    else:
                        colour = bar_colour(d, name, t0, t1)
                    p.setPen(QtGui.QPen(QtGui.QColor(colour), 3))
                    p.drawLine(int(self.x_of(t0)), mid, int(self.x_of(t1)), mid)
            looks = []
            if name not in (None, "__view__") and not name.startswith("__mate__:"):
                looks = [k[0] for k in d.get("look", {}).get(name, [])]
                if len(looks) > 1:          # appearance changebar, under the motion one
                    p.setPen(QtGui.QPen(QtGui.QColor(COLOURS["Appearance"]), 2))
                    p.drawLine(int(self.x_of(looks[0])), mid + 4, int(self.x_of(looks[-1])), mid + 4)
            kind = None if name is None else "cam" if name == "__view__" else "mate" if name.startswith("__mate__:") else "key"
            key_name = name[9:] if kind == "mate" else name
            off = suppressed(self.pane.sim) if kind is not None else set()
            for kt in ts:
                self._diamond(p, self.x_of(kt), y + self.ROW / 2.0, name is None,
                              chosen=(kind, key_name, kt) in self.selected,
                              hollow=(kind, key_name, round(kt, 4)) in off)
            for kt in looks:
                self._diamond(p, self.x_of(kt), y + self.ROW / 2.0, False, COLOURS["Appearance"],   # appearance key
                              chosen=("look", name, kt) in self.selected)
        x = self.x_of(self.time)
        p.setPen(QtGui.QPen(QtGui.QColor("#d03030"), 2))
        p.drawLine(int(x), 0, int(x), self.height())
        p.end()

    def _diamond(self, p, x, y, study, colour=None, chosen=False, hollow=False):
        s = 6 if chosen else 5
        poly = QtGui.QPolygonF([QtCore.QPointF(x, y - s), QtCore.QPointF(x + s, y), QtCore.QPointF(x, y + s),
                                QtCore.QPointF(x - s, y)])
        p.setPen(QtGui.QPen(QtGui.QColor("#3d8ee6" if chosen else "#202020"), 2 if chosen else 1))
        if hollow:                     # a suppressed key
            p.setBrush(Qt.NoBrush)
            p.setPen(QtGui.QPen(QtGui.QColor("#3d8ee6" if chosen else "#909090"), 2 if chosen else 1, Qt.DashLine))
            p.drawPolygon(poly)
            return
        p.setBrush(QtGui.QColor(colour or (COLOURS["Study key"] if study else COLOURS["Key point"])))
        p.drawPolygon(poly)

    # hit tests
    def key_at(self, pos):
        r = self.vrow + int((pos.y() - self.TOP) // self.ROW)
        rows = self.rows()
        if pos.y() < self.TOP or not (0 <= r < len(rows)):
            return None
        label, name = rows[r]
        if name is None:
            x = self.x_of(float(self.pane.duration.value()))
            return ("end",) if abs(pos.x() - x) <= 6 else None
        if name == "__view__":
            for kt in view_keys(self.pane.sim):
                if abs(pos.x() - self.x_of(kt)) <= 6:
                    return ("cam", "__view__", kt)
            return None
        if name.startswith("__drv__:"):
            return None
        if name.startswith("__mate__:"):
            for kt in mate_keys(self.pane.sim, name[9:]):
                if abs(pos.x() - self.x_of(kt)) <= 6:
                    return ("mate", name[9:], kt)
            return None
        for kt in keys(self.pane.sim, name):
            if abs(pos.x() - self.x_of(kt)) <= 6:
                return ("key", name, kt)
        for kt in look_keys(self.pane.sim, name):
            if abs(pos.x() - self.x_of(kt)) <= 6:
                return ("look", name, kt)
        return None

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        hit = self.key_at(e.pos())
        if hit is not None:
            self.drag = hit
            if hit[0] != "end":
                if e.modifiers() & Qt.ControlModifier:
                    self.selected ^= {tuple(hit)}
                elif tuple(hit) not in self.selected:
                    self.selected = {tuple(hit)}
                self.update()
            return
        self.selected = set()
        self.drv_selected = self._driving_at(e.pos())
        if self.drv_selected is not None:
            self.setFocus()
        if e.pos().x() >= self.LEFT:
            self.drag = ("bar",)
            self.set_time(self.t_of(e.pos().x()))

    def mouseMoveEvent(self, e):
        if self.drag is None:
            return
        t = self.t_of(e.pos().x())
        if self.drag[0] == "bar":
            self.set_time(t)
        elif self.drag[0] == "key" and t != self.drag[2] and self.drag[2] > 0:
            if move_key(self.pane.sim, self.drag[1], self.drag[2], t):
                self.drag = ("key", self.drag[1], t)
                self.pane.stale()
            self.update()
        elif self.drag[0] == "look" and t != self.drag[2] and self.drag[2] > 0:
            if move_look_key(self.pane.sim, self.drag[1], self.drag[2], t):
                self.drag = ("look", self.drag[1], t)
                self.pane.stale()
            self.update()
        elif self.drag[0] == "cam" and t != self.drag[2] and self.drag[2] > 0:
            if move_view_key(self.pane.sim, self.drag[2], t):
                self.drag = ("cam", "__view__", t)
                self.pane.stale()
            self.update()
        elif self.drag[0] == "mate" and t != self.drag[2] and self.drag[2] > 0:
            if move_mate_key(self.pane.sim, self.drag[1], self.drag[2], t):
                self.drag = ("mate", self.drag[1], t)
                self.pane.stale()
            self.update()
        elif self.drag[0] == "end" and t > 0:
            self.pane.duration.setValue(t)
            self.update()

    def mouseReleaseEvent(self, e):
        self.drag = None

    def _driving_at(self, pos):
        """The motor, spring, damper, force or contact row under pos in the tree column: its place
        in driving() (the pane's motor list order), else None."""
        if pos.x() >= self.LEFT or pos.y() < self.TOP:
            return None
        r = self.vrow + int((pos.y() - self.TOP) // self.ROW)
        rows = self.rows()
        if not (0 <= r < len(rows)) or not (rows[r][1] or "").startswith("__drv__:"):
            return None
        keys = [k for _l, k in self.driving()]
        return keys.index(rows[r][1]) if rows[r][1] in keys else None

    def _driving_item(self, i):
        lst = self.pane.list
        if i is None or not (0 <= i < lst.count()):
            return None
        lst.setCurrentRow(i)
        return lst.item(i)

    def edit_driving(self, i):
        """Edit Feature on a motor (spring, force...) row: its PropertyManager."""
        item = self._driving_item(i)
        if item is not None:
            self.pane._edit_motor(item)

    def delete_driving(self, i):
        if self._driving_item(i) is not None:
            self.pane.delete_current()

    def mouseDoubleClickEvent(self, e):
        i = self._driving_at(e.pos())
        if i is not None:
            self.edit_driving(i)
            return
        super().mouseDoubleClickEvent(e)

    def _tree_menu(self, pos):
        ""

        i = self._driving_at(pos)
        menu = QtWidgets.QMenu(self)
        menu.setObjectName("FW_TimelineTreeMenu")
        if i is not None:
            self.drv_selected = i
            menu.addAction("Edit Feature", lambda: self.edit_driving(i))
            menu.addAction("Delete", lambda: self.delete_driving(i))
            menu.addSeparator()
        from . import asmmotionint
        menu.addAction("Check Interference...", lambda: asmmotionint.open_panel(self.pane))
        menu.popup(self.mapToGlobal(pos))
        return menu

    def _row_at(self, pos):
        """(kind for a paste, name) of the row under pos, or (None, None)."""
        r = self.vrow + int((pos.y() - self.TOP) // self.ROW)
        rows = self.rows()
        if pos.y() < self.TOP or not (0 <= r < len(rows)) or rows[r][1] is None:
            return None, None
        name = rows[r][1]
        if name == "__view__":
            return "cam", name
        if name.startswith("__mate__:"):
            return "mate", name[9:]
        if name.startswith("__drv__:"):
            return None, None
        return "key", name

    def _menu(self, pos):
        ""



        if pos.x() < self.LEFT and pos.y() >= self.TOP:
            return self._tree_menu(pos)
        hit = self.key_at(pos)
        if hit is not None and hit[0] == "end":
            hit = None
        menu = QtWidgets.QMenu(self)
        menu.setObjectName("FW_TimelineMenu")
        sim = self.pane.sim
        if hit is not None:
            hit = tuple(hit)
            if hit not in self.selected:
                self.selected = {hit}
                self.update()
        kind, name = self._row_at(pos)
        t0 = self.t_of(pos.x()) if pos.x() >= self.LEFT else None
        at = hit[2] if hit is not None else t0
        if hit is not None and hit[2] > 0 and len(self.selected) == 1:     # not on a start key (it stays at 0)
            menu.addAction("Edit Key Point Time", lambda: self.edit_time(hit))
        if at is not None:
            menu.addAction("Move Time Bar", lambda: self.set_time(at))
        if kind == "cam":
            if t0 is not None:
                menu.addAction("Place Key", lambda: self.place_view(t0))
        elif kind == "key" and t0 is not None:
            menu.addAction("Place Key", lambda: self.place(name, t0))
        if hit is not None:
            menu.addAction("Replace Key", lambda: self.replace(hit))
        menu.addSeparator()
        if hit is not None:
            menu.addAction("Cut", self.cut)
            menu.addAction("Copy", self.copy)
        if getattr(Timeline, "clipboard", None) and kind is not None and t0 is not None:     # only with keys to paste
            menu.addAction("Paste", lambda: self.paste(kind, name, t0))
        if hit is not None:
            menu.addAction("Delete", self.delete_selected)
        menu.addSeparator()
        menu.addAction("Select All", self.select_all)
        menu.addSeparator()
        if hit is not None:
            menu.addAction("Key Properties...", lambda: self.key_properties(hit))
            if hit[2] > 0:                  # a start key cannot be suppressed: not offered
                act = menu.addAction("Suppress Key", lambda: self.suppress(hit))
                act.setCheckable(True)
                act.setChecked(is_suppressed(sim, *hit))
            if hit[0] == "key" and hit[2] > 0:
                sub = menu.addMenu("Interpolation mode")
                sub.setObjectName("FW_TimelineInterpolation")
                self._interp_menu = sub
                now = interpolation(sim, hit[1], hit[2])
                for mode in INTERPOLATION:
                    act = sub.addAction(INTERPOLATION_TEXT[mode], lambda m=mode: self.interpolate(hit[1], hit[2], m))
                    act.setCheckable(True)
                    act.setChecked(mode == now)
            menu.addSeparator()
            rows = {(k, n) for k, n, _t in self.selected}
            if any(sum(1 for k, n, _t in self.selected if (k, n) == r) > 1 for r in rows):    # two keys of a row picked
                menu.addAction("Reverse Path", self.reverse_selected)
        if kind == "cam":
            for key, text in (("no_view_keys", "Disable View Key Creation"), ("no_view_playback", "Disable Playback of View Keys")):
                act = menu.addAction(text, lambda k=key: self.toggle_option(k))
                act.setCheckable(True)
                act.setChecked(bool(study_option(sim, key)))
        menu.addSeparator()
        menu.addAction("Animation Wizard...", self.animation_wizard)
        menu.popup(self.mapToGlobal(pos))
        return menu

    def suppress(self, hit, on=None):
        """Suppress Key: playback goes past the key (it stays on the timeline, hollow)."""
        sim = self.pane.sim
        on = (not is_suppressed(sim, *hit)) if on is None else bool(on)
        doc = self.pane.asm.Document
        doc.openTransaction("Suppress Key")
        try:
            set_suppressed(sim, hit[0], hit[1], hit[2], on)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        self.pane.stale()
        self.set_time(self.time)
        return on

    def reverse_selected(self):
        doc = self.pane.asm.Document
        doc.openTransaction("Reverse Path")
        try:
            n = reverse_path(self.pane.sim, self.selected)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        self.pane.stale()
        self.set_time(self.time)
        return n

    def animation_wizard(self):
        try:
            return self.pane.animation_wizard()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: Animation Wizard: %s\n" % error)
            return None

    def key_properties(self, hit):
        dlg = KeyProperties(self, hit)
        LAST_DIALOG["keyprops"] = dlg
        dlg.show()
        return dlg

    # selection, clipboard
    def select_all(self):
        self.selected = set(all_keys(self.pane.sim))
        self.update()

    def copy(self):
        sim = self.pane.sim
        picked = sorted(self.selected, key=lambda h: h[2])
        if not picked:
            return
        t0 = picked[0][2]
        Timeline.clipboard = [(k, n, t - t0, key_payload(sim, k, n, t)) for k, n, t in picked
                              if key_payload(sim, k, n, t) is not None]

    def cut(self):
        self.copy()
        self.delete_selected("Cut")

    def paste(self, kind, name, t):
        """The copied keys at t on this row (a key of another row goes to this row when it is the same
        kind of row, an appearance key to a component row)."""
        clip = getattr(Timeline, "clipboard", None)
        if not clip or t is None:
            return
        doc = self.pane.asm.Document
        doc.openTransaction("Paste")
        try:
            rows_kinds = {k for k, *_ in clip}
            self.selected = set()
            for k, n, dt, payload in clip:
                target = n
                if len({n for _k, n, *_ in clip}) == 1 and name is not None:
                    if (k in ("key", "look") and kind == "key") or (k == kind):
                        target = name
                if k == "cam":
                    target = "__view__"
                put_key(self.pane.sim, k, target, t + dt, payload)
                self.selected.add((k, target, round(t + dt, 4)))
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        self.pane.stale()
        self.update()
        return rows_kinds

    def delete_selected(self, label="Delete"):
        doc = self.pane.asm.Document
        doc.openTransaction(label if isinstance(label, str) else "Delete")
        try:
            for k, n, t in sorted(self.selected, key=lambda h: -h[2]):
                delete_any(self.pane.sim, k, n, t)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        self.selected = set()
        self.pane.stale()
        self.update()

    def replace(self, hit):
        """Replace Key: the key takes where the component, mate or view is now."""
        payload = current_payload(self.pane.asm, hit[0], hit[1])
        if payload is None:
            return
        old = key_payload(self.pane.sim, hit[0], hit[1], hit[2]) or []
        if hit[0] == "key" and len(old) > 2:
            payload = payload + old[2:]                 # the interpolation mode stays
        doc = self.pane.asm.Document
        doc.openTransaction("Replace Key")
        try:
            put_key(self.pane.sim, hit[0], hit[1], hit[2], payload)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        self.pane.stale()
        self.update()

    def edit_time(self, hit, value=None):
        """Edit Key Point Time: the key's time typed in."""
        if value is None:
            value, ok = QtWidgets.QInputDialog.getDouble(self, "Edit Time", "Time (s):", hit[2], 0.0, 100000.0, 3)
            if not ok:
                return False
        doc = self.pane.asm.Document
        doc.openTransaction("Edit Key Point Time")
        try:
            done = move_any(self.pane.sim, hit[0], hit[1], hit[2], value)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        if done:
            self.selected = {(hit[0], hit[1], round(float(value), 4))}
            self.pane.stale()
        self.update()
        return done

    def event(self, e):
        """The timeline's own Delete, Ctrl+A/C/X/V win over the main window's shortcuts while it has focus."""
        if e.type() == QtCore.QEvent.ShortcutOverride:
            ctrl = e.modifiers() & Qt.ControlModifier
            if e.key() == Qt.Key_Delete or (ctrl and e.key() in (Qt.Key_A, Qt.Key_C, Qt.Key_X, Qt.Key_V)):
                e.accept()
                return True
        return super().event(e)

    def keyPressEvent(self, e):
        ctrl = e.modifiers() & Qt.ControlModifier
        if e.key() == Qt.Key_Delete and self.selected:
            self.delete_selected()
        elif e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and getattr(self, "drv_selected", None) is not None:
            self.delete_driving(self.drv_selected)     # a motor row picked in the tree column
            self.drv_selected = None
        elif ctrl and e.key() == Qt.Key_A:
            self.select_all()
        elif ctrl and e.key() == Qt.Key_C:
            self.copy()
        elif ctrl and e.key() == Qt.Key_X:
            self.cut()
        elif ctrl and e.key() == Qt.Key_V:
            kind, name = (self.selected and next(iter(self.selected))[:2]) or (None, None)
            self.paste(kind, name, self.time)
        else:
            super().keyPressEvent(e)

    def delete(self, name, t):
        doc = self.pane.asm.Document
        doc.openTransaction("Delete Key")
        try:
            delete_key(self.pane.sim, name, t)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        self.pane.stale()
        self.update()

    def delete_mate(self, name, t):
        doc = self.pane.asm.Document
        doc.openTransaction("Delete Key")
        try:
            delete_mate_key(self.pane.sim, name, t)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        self.pane.stale()
        self.update()

    def delete_view(self, t):
        doc = self.pane.asm.Document
        doc.openTransaction("Delete Key")
        try:
            delete_view_key(self.pane.sim, t)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        self.pane.stale()
        self.update()

    def place_view(self, t):
        """Place Key on Orientation and Camera Views: the view now, at t."""
        cam = camera_now()
        if cam is None:
            return
        doc = self.pane.asm.Document
        doc.openTransaction("Place Key")
        try:
            set_view_key(self.pane.sim, t, cam, self.pane.cam0)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        self.pane.last_cam = cam
        self.pane.stale()
        self.update()

    def toggle_option(self, key):
        set_study_options(self.pane.sim, {key: not study_option(self.pane.sim, key)})
        self.update()

    def delete_look(self, name, t):
        doc = self.pane.asm.Document
        doc.openTransaction("Delete Key")
        try:
            delete_look_key(self.pane.sim, name, t)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        self.pane.stale()
        self.update()

    def interpolate(self, name, t, mode):
        doc = self.pane.asm.Document
        doc.openTransaction("Interpolation Modes")
        try:
            set_interpolation(self.pane.sim, name, t, mode)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        self.pane.stale()
        self.update()

    def place(self, name, t):
        obj = self.pane.asm.Document.getObject(name)
        if obj is None:
            return
        rows = data(self.pane.sim)["comps"].get(name, [])
        doc = self.pane.asm.Document
        doc.openTransaction("Place Key")
        try:
            set_key(self.pane.sim, obj, t, placement_at(rows, t) or obj.Placement)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        self.pane.stale()
        self.update()

    def set_time(self, t):
        """The time bar at t: the components where their keys put them."""
        self.time = max(0.0, float(t))
        self.pane.at_time(self.time)
        self.update()
