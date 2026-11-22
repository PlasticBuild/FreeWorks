# SPDX-License-Identifier: LGPL-2.1-or-later
"""Small 2D vector helpers on (x, y) tuples, for the snap engine."""

import math


def add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def mul(a, s):
    return (a[0] * s, a[1] * s)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def length(a):
    return math.hypot(a[0], a[1])


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def unit(a):
    n = length(a)
    return (a[0] / n, a[1] / n) if n > 0.0 else (0.0, 0.0)


def perp(a):
    """a turned 90 degrees counter-clockwise."""
    return (-a[1], a[0])


def xy(v):
    """(x, y) of a FreeCAD vector."""
    return (v.x, v.y)
