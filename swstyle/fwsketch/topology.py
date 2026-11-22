# SPDX-License-Identifier: LGPL-2.1-or-later
"""Which sketch points are joined: the Line tool closes a profile with them (LineSet.h
closesProfile) and tells a second click on a joined point from a free one (arePointsCoincident)."""

import Part

from . import inference as I


class Joins:
    """Union-find over the end points of a sketch: 2 * geo + 0/1 for start/end, the origin last."""

    def __init__(self, sketch, with_curves):
        self.count = sketch.GeometryCount
        self.origin = 2 * self.count
        self.parent = list(range(self.origin + 1))
        if with_curves:
            for geo, g in enumerate(sketch.Geometry):
                if isinstance(g, (Part.LineSegment, Part.ArcOfCircle, Part.ArcOfEllipse, Part.ArcOfHyperbola,
                                  Part.ArcOfParabola, Part.BSplineCurve)):
                    self.join(2 * geo, 2 * geo + 1)  # an open curve joins its two ends
        for c in sketch.Constraints:
            point_to_point = c.Type == "Coincident" or (
                c.Type in ("Tangent", "Perpendicular") and c.FirstPos != I.NONE and c.SecondPos != I.NONE)
            if point_to_point:
                self.join(self.index(c.First, c.FirstPos), self.index(c.Second, c.SecondPos))

    def index(self, geo, pos):
        if geo == I.ROOT and pos == I.START:
            return self.origin
        if geo < 0 or geo >= self.count:
            return -1
        if pos == I.START:
            return 2 * geo
        return 2 * geo + 1 if pos == I.END else -1

    def find(self, i):
        parent = self.parent
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(self, a, b):
        if a >= 0 and b >= 0:
            self.parent[self.find(a)] = self.find(b)

    def joined(self, geo1, pos1, geo2, pos2):
        a, b = self.index(geo1, pos1), self.index(geo2, pos2)
        return a >= 0 and b >= 0 and self.find(a) == self.find(b)


def points_coincident(sketch, geo1, pos1, geo2, pos2):
    """The two points are the same point of the sketch (held together by relations)."""
    if (geo1, pos1) == (geo2, pos2):
        return True
    return Joins(sketch, with_curves=False).joined(geo1, pos1, geo2, pos2)


def closes_profile(sketch, first_geo, first_pos, geo, pos):
    """A segment from the chain's first point ending on (geo, pos) closes a profile: the point is
    joined to the first point through the sketch's entities and the relations between their ends."""
    return Joins(sketch, with_curves=True).joined(geo, pos, first_geo, first_pos)
