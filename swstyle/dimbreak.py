"""Utilities for breaking drawing dimension lines at crossings."""

import math


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _sub(a, b):
    return a[0] - b[0], a[1] - b[1]


def crossings(seg, cutters, eps=1e-9):
    """Return sorted, deduplicated interior intersection parameters for *seg*."""
    p = seg[0]
    r = _sub(seg[1], p)
    if r == (0, 0):
        return []

    found = []
    for cutter in cutters:
        q = cutter[0]
        s = _sub(cutter[1], q)
        if s == (0, 0):
            continue
        denominator = _cross(r, s)
        if abs(denominator) <= eps:
            continue
        q_minus_p = _sub(q, p)
        t = _cross(q_minus_p, s) / denominator
        u = _cross(q_minus_p, r) / denominator
        if eps < t < 1.0 - eps and -eps <= u <= 1.0 + eps:
            found.append(t)

    found.sort()
    unique = []
    for t in found:
        if not unique or t - unique[-1] > eps:
            unique.append(t)
    return unique


def _point_at(p0, p1, t):
    if t == 0.0:
        return p0
    if t == 1.0:
        return p1
    return (p0[0] + (p1[0] - p0[0]) * t,
            p0[1] + (p1[1] - p0[1]) * t)


def break_segments(segments, cutters, gap, keep_ends=0.0, eps=1e-9):
    """Break segments at cutters, removing and merging gaps along each line."""
    result = []
    for seg in segments:
        p0, p1 = seg
        dx = p1[0] - p0[0]
        dy = p1[1] - p0[1]
        length = math.hypot(dx, dy)
        if length == 0.0:
            result.append(seg)
            continue
        if gap <= 0.0:
            result.append(seg)
            continue

        locations = []
        for t in crossings(seg, cutters, eps):
            if t * length < keep_ends or (1.0 - t) * length < keep_ends:
                continue
            locations.append(t)
        if not locations:
            result.append(seg)
            continue

        half_gap = gap / (2.0 * length)
        intervals = []
        for t in locations:
            start = max(0.0, t - half_gap)
            end = min(1.0, t + half_gap)
            if intervals and start <= intervals[-1][1] + eps / length:
                intervals[-1][1] = max(intervals[-1][1], end)
            else:
                intervals.append([start, end])

        cursor = 0.0
        for start, end in intervals:
            if (start - cursor) * length >= eps:
                result.append((_point_at(p0, p1, cursor),
                               _point_at(p0, p1, start)))
            cursor = max(cursor, end)
        if (1.0 - cursor) * length >= eps:
            result.append((_point_at(p0, p1, cursor), p1))
    return result
