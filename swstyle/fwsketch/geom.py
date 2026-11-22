# SPDX-License-Identifier: LGPL-2.1-or-later
"""Pure geometry of the sketch tools (no FreeCAD here), so the unit tests can check it.

Ports of the arithmetic in DrawSketchHandlerLineSet.h (tangent and normal arcs), Rectangle.h
(corner order), Circle.h and Arc.h (three point circle and arc, centre arc angle)."""

import math

from .vec import sub, add, mul, dot, cross, length, unit

TWO_PI = 2.0 * math.pi
START, END = 1, 2


def tangent_arc(start, tangent, pos, snap45=False):
    """The arc that leaves start along tangent and ends at pos (LineSet mouseMove, arc mode).
    Returns (center, radius, start_angle, end_angle, arc_angle) with radius signed as the C++:
    negative for a counter-clockwise arc; None when pos lies on the tangent line."""
    away = sub(pos, start)
    theta = _angle_between(tangent, away)
    s = math.sin(theta)
    if abs(s) < 1e-12 or length(away) < 1e-12:
        return None
    radius = length(away) / (2.0 * s)
    x1, y1 = start
    x2, y2 = x1 + tangent[0], y1 + tangent[1]
    x3, y3 = pos
    if (x2 * y3 - x3 * y2) - (x1 * y3 - x3 * y1) + (x1 * y2 - x2 * y1) > 0:
        radius = -radius
    if math.isnan(radius) or math.isinf(radius):
        return None
    center = (x1 + radius * tangent[1], y1 - radius * tangent[0])
    rx, ry = x1 - center[0], y1 - center[1]
    start_angle = math.atan2(ry, rx)
    rxe, rye = x3 - center[0], y3 - center[1]
    arc_angle = math.atan2(-rxe * ry + rye * rx, rxe * rx + rye * ry)
    if math.isnan(arc_angle) or math.isinf(arc_angle):
        arc_angle = 0.0
    if radius >= 0 and arc_angle > 0:
        arc_angle -= TWO_PI
    if radius < 0 and arc_angle < 0:
        arc_angle += TWO_PI
    if snap45:
        arc_angle = round(arc_angle / (math.pi / 4)) * math.pi / 4
    return center, radius, start_angle, start_angle + arc_angle, arc_angle


def arc_points(center, radius, start_angle, arc_angle, n=29):
    """n + 1 points along the arc, start first (the preview polyline)."""
    r = abs(radius)
    return [(center[0] + r * math.cos(start_angle + i * arc_angle / n),
             center[1] + r * math.sin(start_angle + i * arc_angle / n)) for i in range(n + 1)]


def circle_points(center, radius, n=48):
    pts = [(center[0] + radius * math.cos(TWO_PI * i / n), center[1] + radius * math.sin(TWO_PI * i / n))
           for i in range(n)]
    pts.append(pts[0])
    return pts


def _angle_between(a, b):
    """Angle from a to b in [0, pi] (Base::Vector2d::GetAngle)."""
    la, lb = length(a), length(b)
    if la < 1e-12 or lb < 1e-12:
        return 0.0
    c = max(-1.0, min(1.0, dot(a, b) / (la * lb)))
    return math.acos(c)


def arc_transition_for(direction, away):
    ""


    along = direction[0] * away[0] + direction[1] * away[1]
    side = direction[0] * away[1] - direction[1] * away[0]
    if abs(along) >= abs(side):
        return "tangent"
    return "perpendicular_l" if side > 0 else "perpendicular_r"


def transition_tangent(direction, mode):
    """The tangent of the next segment at its start for a transition mode."""
    if mode == "tangent":
        return direction
    if mode == "perpendicular_l":
        return (-direction[1], direction[0])
    return (direction[1], -direction[0])


def line_end_tangent(start, pos, tangent):
    """A line leaving tangentially: pos projected on the tangent through start; (end, suppressed)
    with suppressed True when pos lies behind the start (the C++ draws to pos and drops the
    tangency then)."""
    t = unit(tangent)
    along = dot(sub(pos, start), t)
    if along < 0:
        return pos, True
    return add(start, mul(t, along)), False


def project_along(start, pos, direction):
    """pos projected onto the line through start along direction (either way)."""
    t = unit(direction)
    return add(start, mul(t, dot(sub(pos, start), t)))


def rectangle_corners(corner1, corner3):
    """The four corners counter-clockwise from corner1 (Rectangle.h SeekSecond) and whether the
    second and fourth were swapped for that."""
    if (corner3[0] - corner1[0]) * (corner3[1] - corner1[1]) > 0:
        corner2 = (corner3[0], corner1[1])
        corner4 = (corner1[0], corner3[1])
        reversed_ = False
    else:
        corner4 = (corner3[0], corner1[1])
        corner2 = (corner1[0], corner3[1])
        reversed_ = True
    return (corner1, corner2, corner3, corner4), reversed_


def rectangle_relation_types(corner1, corner3):
    """(type of sides 0 and 2, type of sides 1 and 3): Horizontal/Vertical by the diagonal's slope."""
    sx = (corner3[0] > corner1[0]) - (corner3[0] < corner1[0])
    sy = (corner3[1] > corner1[1]) - (corner3[1] < corner1[1])
    if sx * sy < 0:
        return "Vertical", "Horizontal"
    return "Horizontal", "Vertical"


def circumcenter(a, b, c):
    """Centre of the circle through three points, None when they are in line."""
    d = 2.0 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    if abs(d) < 1e-12:
        return None
    a2, b2, c2 = dot(a, a), dot(b, b), dot(c, c)
    ux = (a2 * (b[1] - c[1]) + b2 * (c[1] - a[1]) + c2 * (a[1] - b[1])) / d
    uy = (a2 * (c[0] - b[0]) + b2 * (a[0] - c[0]) + c2 * (b[0] - a[0])) / d
    return (ux, uy)


def collinear(a, b, c, tol=1e-9):
    return abs(cross(sub(b, a), sub(c, a))) <= tol * max(1.0, length(sub(b, a)) * length(sub(c, a)))


def center_arc_angle(start_angle, cursor_angle, previous_arc_angle):
    """The arc angle for the end point of a centre arc, keeping the turning sense the arc already
    had when both branches fit (Arc.h SeekThird)."""
    angle1 = cursor_angle - start_angle
    angle2 = angle1 + (2 if angle1 < 0 else -2) * math.pi
    return angle1 if abs(angle1 - previous_arc_angle) < abs(angle2 - previous_arc_angle) else angle2


def center_arc_range(start_angle, arc_angle):
    """(start, end) of the stored counter-clockwise arc for a centre arc drawn with arc_angle."""
    if arc_angle > 0:
        return start_angle, start_angle + arc_angle
    return start_angle + arc_angle, start_angle


def three_point_arc(p1, p2, p3):
    """Arc through p1 and p2 with p3 on it (Arc.h ThreeRim SeekThird). Returns
    (center, radius, start_angle, end_angle, pos_of_p1, pos_of_p2) or None when in line."""
    center = circumcenter(p1, p2, p3)
    if center is None:
        return None
    radius = length(sub(p3, center))
    a1 = math.atan2(p1[1] - center[1], p1[0] - center[0])
    a2 = math.atan2(p2[1] - center[1], p2[0] - center[0])
    a3 = math.atan2(p3[1] - center[1], p3[0] - center[0])
    if min(a1, a2) < a3 < max(a1, a2):
        if a2 > a1:
            pos1, pos2 = START, END
        else:
            pos1, pos2 = END, START
        start_angle, end_angle = min(a1, a2), max(a1, a2)
    else:
        if a2 > a1:
            pos1, pos2 = END, START
        else:
            pos1, pos2 = START, END
        start_angle, end_angle = max(a1, a2), min(a1, a2) + TWO_PI
    return center, radius, start_angle, end_angle, pos1, pos2
