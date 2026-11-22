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

import math

import FreeCAD as App

from . import asmcore as ac

V = App.Vector
GRAVITY = 9806.65
DENSITY = 7.85e-6                  # kg/mm^3 (steel), when the part has no density
ANALYSIS_PROP = "FwMateAnalysis"   # json from the Mate PM's Analysis tab
# Dynamic friction coefficients (common engineering values) for the Analysis tab's materials
MATERIALS = ("Steel (Dry)", "Steel (Greasy)", "Aluminum (Dry)", "Aluminum (Greasy)", "Cast Iron (Dry)",
             "Cast Iron (Greasy)", "Brass (Dry)", "Bronze (Dry)", "Nylon", "Acrylic", "Rubber (Dry)",
             "Rubber (Greasy)", "Teflon")
_MU = {"Steel (Dry)": 0.42, "Steel (Greasy)": 0.08, "Aluminum (Dry)": 0.47, "Aluminum (Greasy)": 0.10,
       "Cast Iron (Dry)": 0.40, "Cast Iron (Greasy)": 0.08, "Brass (Dry)": 0.35, "Bronze (Dry)": 0.36,
       "Nylon": 0.25, "Acrylic": 0.40, "Rubber (Dry)": 0.80, "Rubber (Greasy)": 0.30, "Teflon": 0.04}
TURN = ("Revolute", "Cylindrical")
SLIDE = ("Slider",)


def friction(mat1, mat2):
    """The pair's coefficient: the softer pairing (the mean of the two, greasy wins)."""
    a, b = _MU.get(mat1, 0.3), _MU.get(mat2, 0.3)
    return round(min(a, b) if "Greasy" in mat1 + mat2 else (a + b) / 2.0, 3)


def analysis(joint):
    import json
    try:
        return json.loads(getattr(joint, ANALYSIS_PROP, "") or "{}")
    except ValueError:
        return {}


def _radius_of(comp, subs):
    for sub in subs or []:
        g = ac.geometry(ac.element(comp, sub))
        if g is not None and g[0] == "axis" and len(g) > 3:
            return g[3]
    return 0.0


def _axis_of(comp, subs):
    for sub in subs or []:
        g = ac.geometry(ac.element(comp, sub))
        if g is not None and g[0] in ("axis", "line"):
            return V(g[1]), V(g[2]).normalize()
        if g is not None and g[0] == "plane":
            return V(g[1]), V(g[2]).normalize()
    return None


def bodies(asm, motor_joints=None):
    """[{comp, kind 'turn'|'slide', point, axis, joint}] for each component free on one mate to a
    fixed component."""
    fixed = set(ac.grounded(asm))
    out = []
    seen = set()
    for j in ac.joint_group(asm).Group:
        jt = getattr(j, "JointType", None)
        if jt not in TURN + SLIDE or getattr(j, "Suppressed", False):
            continue
        refs = [getattr(j, p, None) for p in ("Reference1", "Reference2")]
        if not all(r and r[0] is not None for r in refs):
            continue
        a, b = refs
        if a[0] in fixed and b[0] not in fixed:
            moving = b
        elif b[0] in fixed and a[0] not in fixed:
            moving = a
        else:
            continue
        comp = moving[0]
        if comp.Name in seen:
            continue
        geo = _axis_of(comp, list(moving[1])) or _axis_of(a[0] if moving is b else b[0], list((a if moving is b else b)[1]))
        if geo is None:
            continue
        seen.add(comp.Name)
        radius = _radius_of(comp, list(moving[1])) or _radius_of(*((a[0], list(a[1])) if moving is b else (b[0], list(b[1]))))
        out.append({"comp": comp, "kind": "turn" if jt in TURN else "slide", "point": geo[0],
                    "axis": geo[1], "joint": j, "radius": radius, "analysis": analysis(j)})
    return out


def mass_props(comp):
    shape = comp.Shape
    density = DENSITY
    try:
        own = comp.LinkedObject
        d = getattr(own, "Density", None) or getattr(getattr(own, "ShapeMaterial", None), "Density", None)
        if d:
            density = float(getattr(d, "Value", d)) * 1e-9      # kg/m^3 -> kg/mm^3
    except Exception as _fw_err:
        _fw_log("asmphysics.py:117", _fw_err)
    solids = shape.Solids or [shape]
    vol = sum(x.Volume for x in solids)
    if vol <= 0:
        return 0.0, V(shape.BoundBox.Center), App.Matrix(), density
    com = V()
    for x in solids:
        com += V(x.CenterOfMass) * (x.Volume / vol)
    total = [[0.0] * 3 for _ in range(3)]    # the solids' inertia about the common centre (volume units)
    for x in solids:
        m = x.MatrixOfInertia
        d = V(x.CenterOfMass) - com
        rows = ((m.A11, m.A12, m.A13), (m.A21, m.A22, m.A23), (m.A31, m.A32, m.A33))
        dv = (d.x, d.y, d.z)
        for i in range(3):
            for k in range(3):
                shift = x.Volume * ((d.Length ** 2 if i == k else 0.0) - dv[i] * dv[k])
                total[i][k] += rows[i][k] + shift
    mat = App.Matrix(total[0][0], total[0][1], total[0][2], 0, total[1][0], total[1][1], total[1][2], 0,
                     total[2][0], total[2][1], total[2][2], 0, 0, 0, 0, 1)
    return density * vol, com, mat, density


def _inertia(matrix, density, mass, com, point, axis):
    a = axis
    j = matrix
    ja = V(j.A11 * a.x + j.A12 * a.y + j.A13 * a.z,
           j.A21 * a.x + j.A22 * a.y + j.A23 * a.z,
           j.A31 * a.x + j.A32 * a.y + j.A33 * a.z)
    r = com - point
    r_perp = r - a * r.dot(a)
    return density * a.dot(ja) + mass * r_perp.Length ** 2


def _rotate(v, axis, angle):
    return App.Rotation(axis, math.degrees(angle)).multVec(v)


def _motion_fn(text):
    env = {"sin": math.sin, "cos": math.cos, "pi": math.pi, "sqrt": math.sqrt, "exp": math.exp,
           "abs": abs, "__builtins__": {}}
    code = compile(text.replace("^", "**"), "<motor>", "eval")      # FreeCAD's formula writes ^ for power
    return lambda t: float(eval(code, env, {"time": t}))


def _motor_axis(b):
    """A motor turns or slides its component the way FreeCAD's motion does (Animation): about the mate's
    Z axis, + for the mate's second component. So the same motor moves the same way in every study type."""
    axis = V(b["axis"])
    try:
        import UtilsAssembly
        j = b["joint"]
        z = UtilsAssembly.getJcsGlobalPlc(j.Placement1, j.Reference1).Rotation.multVec(V(0, 0, 1))
        if j.Reference1[0] is b["comp"]:
            z = -z
        if axis.dot(z) < 0:
            axis = -axis
    except Exception as _fw_err:
        _fw_log("asmphysics.py:175", _fw_err)
    return axis


def simulate(asm, duration, fps, gravity, motors=(), loads=(), sub=10):
    """gravity = (direction Vector, magnitude mm/s^2) or None; motors = [(joint, formula text)].
    Returns (frames [{comp name: Placement}], results {comp name: {t, x, v, a, kind}})."""
    found = bodies(asm)
    driven = {}
    for joint, text in motors:
        try:
            driven[joint.Name] = _motion_fn(text)
        except Exception:
            continue
    g = V(gravity[0]).normalize() * float(gravity[1]) if gravity and gravity[1] else V()
    steps = max(1, int(round(duration * fps)))
    sub = max(1, int(sub))
    dt = 1.0 / fps / sub
    states = []
    for b in found:
        comp = b["comp"]
        if b["joint"].Name in driven:
            b = dict(b, axis=_motor_axis(b))
        mass, com, matrix, density = mass_props(comp)
        inertia = _inertia(matrix, density, mass, com, b["point"], b["axis"]) if b["kind"] == "turn" else mass
        states.append(dict(b, place0=App.Placement(comp.Placement), com0=com, mass=mass,
                           inertia=max(inertia, 1e-12), x=0.0, v=0.0,
                           drive=driven.get(b["joint"].Name)))

    def losses(s, x, v):
        """The mate's Analysis tab: friction (Coulomb, smoothed) and the bushing's spring, damping and preload."""
        an = s["analysis"]
        out = 0.0
        if an.get("friction"):
            mu = float(an.get("mu", 0.0))
            weight = s["mass"] * g.Length
            arm = s["radius"] if s["kind"] == "turn" else 1.0
            out -= mu * weight * arm * math.tanh(v / 0.05)
        if an.get("bushing"):
            if s["kind"] == "turn":       # N*mm/deg and N*mm/(deg/s): 1 N*mm = 1000 kg*mm^2/s^2
                out -= 1000.0 * float(an.get("kt", 0.0)) * math.degrees(x)
                out -= 1000.0 * float(an.get("ct", 0.0)) * math.degrees(v)
                out += 1000.0 * float(an.get("pt", 0.0))       # preload torque, N*mm
            else:                         # N/mm and N/(mm/s): 1 N = 1000 kg*mm/s^2
                out -= 1000.0 * float(an.get("k", 0.0)) * x
                out -= 1000.0 * float(an.get("c", 0.0)) * v
                out += 1000.0 * float(an.get("p", 0.0))        # preload force, N
        return out

    comps = {c.Name: c for c in ac.components(asm)}

    def place_of(s, x):
        if s["kind"] == "turn":
            move = App.Placement(V(), App.Rotation(s["axis"], math.degrees(x)), s["point"])
        else:
            move = App.Placement(s["axis"] * x, App.Rotation())
        return move.multiply(s["place0"])

    def rubbing(s, v):
        """Contact friction: a body resting on or sliding along a contact with Friction feels
        Coulomb friction (its weight, on the arm to the contact point for a turning body)."""
        t = s.get("touch")
        if not t or not t[0]:
            return 0.0
        mu, point = t[0], t[1]
        if len(t) > 2 and t[2] is not None:      # static friction: more grip near rest
            from . import asmloads
            mu = asmloads.friction_at(mu, t[2], abs(v))
        weight = s["mass"] * max(g.Length, 1.0)
        if s["kind"] == "turn":
            if point is None:
                return 0.0
            r = point - s["point"]
            arm = (r - s["axis"] * r.dot(s["axis"])).Length
        else:
            arm = 1.0
        return -mu * weight * arm * math.tanh(v / 0.05)

    clock = [0.0]       # the time the loads are worked out at (a Force/Torque function of time)

    def pushes(s, x, v):
        """Springs, dampers and forces of the study (asmloads)."""
        if not loads:
            return 0.0
        from . import asmloads
        return asmloads.generalized(loads, s, x, v, place_of, comps, clock[0])

    def accel(s, x, v=0.0):
        if s["kind"] == "slide":
            return g.dot(s["axis"]) + (losses(s, x, v) + pushes(s, x, v) + rubbing(s, v)) / s["mass"]
        r = _rotate(s["com0"] - s["point"], s["axis"], x)
        torque = r.cross(g * s["mass"]).dot(s["axis"])
        return (torque + losses(s, x, v) + pushes(s, x, v) + rubbing(s, v)) / s["inertia"]

    frames, results = [], {s["comp"].Name: {"t": [], "x": [], "v": [], "a": [], "kind": s["kind"]} for s in states}

    def record(t):
        frame = {}
        for s in states:
            if s["kind"] == "turn":
                move = App.Placement(V(), App.Rotation(s["axis"], math.degrees(s["x"])), s["point"])
            else:
                move = App.Placement(s["axis"] * s["x"], App.Rotation())
            frame[s["comp"].Name] = move.multiply(s["place0"])
            r = results[s["comp"].Name]
            r["t"].append(t)
            r["x"].append(s["x"])
            r["v"].append(s["v"])
            r["a"].append(s["drive_a"] if s["drive"] else accel(s, s["x"], s["v"]))
        frames.append(frame)

    for s in states:
        s["drive_a"] = 0.0
        if s["drive"]:
            s["x"] = s["drive"](0.0)
    record(0.0)
    t = 0.0
    touching = loads and any(r.get("kind") == "Contact" for r in loads)
    for _i in range(steps):
        before = [(s["x"], s["v"]) for s in states]
        for _k in range(sub):
            for s in states:
                if s["drive"]:
                    x0, x1 = s["drive"](t), s["drive"](t + dt)
                    v1 = (x1 - x0) / dt
                    s["drive_a"] = (v1 - s["v"]) / dt if t > 0 else 0.0
                    s["x"], s["v"] = x1, v1
                    continue
                x, v = s["x"], s["v"]
                clock[0] = t
                k1x, k1v = v, accel(s, x, v)
                clock[0] = t + 0.5 * dt
                k2x, k2v = v + 0.5 * dt * k1v, accel(s, x + 0.5 * dt * k1x, v + 0.5 * dt * k1v)
                k3x, k3v = v + 0.5 * dt * k2v, accel(s, x + 0.5 * dt * k2x, v + 0.5 * dt * k2v)
                clock[0] = t + dt
                k4x, k4v = v + dt * k3v, accel(s, x + dt * k3x, v + dt * k3v)
                s["x"] = x + dt / 6.0 * (k1x + 2 * k2x + 2 * k3x + k4x)
                s["v"] = v + dt / 6.0 * (k1v + 2 * k2v + 2 * k3v + k4v)
            t += dt
        if touching:
            # Contact: a body that ran into its contact set goes back to where it was and
            # bounces off with the set's coefficient of restitution
            from . import asmloads
            now = {o["comp"].Name: place_of(o, o["x"]) for o in states}
            for s, (x0, v0) in zip(states, before):
                if s["drive"]:
                    continue
                e = asmloads.contact_hit(loads, s, s["x"], now, place_of, comps)
                if e is None:
                    for r in loads:
                        if r.get("kind") == "Contact" and r.get("type") == "Curves" and \
                                asmloads.curves_hit(r, s, x0, s["x"], now, place_of, comps):
                            e = float(r.get("e", 0.5))
                            break
                if e is not None:
                    s["x"], s["v"] = x0, -e * v0
                    now[s["comp"].Name] = place_of(s, x0)
                s["touch"] = asmloads.contact_touch(loads, s, s["x"], now, place_of, comps)
        record(t)
    return frames, results
