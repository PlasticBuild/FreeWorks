# SPDX-License-Identifier: LGPL-2.1-or-later
"""Geometric helpers for peg-in-hole circular edges."""

import FreeCAD as App
import Part


def is_circular_edge(edge):
    """Whether an edge is a full circle or a circular arc."""
    try:
        return edge.Curve.TypeId == "Part::GeomCircle"
    except Exception:
        return False


def flat_face_for_circle(shape, edge):
    """Return the index of the smallest planar face bounded by the circle, or None."""
    try:
        curve = edge.Curve
        if curve.TypeId != "Part::GeomCircle":
            return None
        centre = App.Vector(curve.Center)
        radius = float(curve.Radius)
        axis = App.Vector(curve.Axis)
        axis.normalize()
        best = None
        best_area = None
        for index, face in enumerate(shape.Faces):
            surface = face.Surface
            if surface.TypeId != "Part::GeomPlane":
                continue
            normal = App.Vector(surface.Axis)
            normal.normalize()
            if abs(normal.dot(axis)) < 1.0 - 1e-6:
                continue
            origin = App.Vector(getattr(surface, "Position", face.CenterOfMass))
            if abs((centre - origin).dot(normal)) >= 1e-6:
                continue
            found = False
            for face_edge in face.Edges:
                other = face_edge.Curve
                if other.TypeId != "Part::GeomCircle":
                    continue
                if abs(float(other.Radius) - radius) >= 1e-6:
                    continue
                if (App.Vector(other.Center) - centre).Length >= 1e-6:
                    continue
                found = True
                break
            if found and (best_area is None or face.Area < best_area):
                best = index
                best_area = face.Area
        return best
    except Exception:
        return None
