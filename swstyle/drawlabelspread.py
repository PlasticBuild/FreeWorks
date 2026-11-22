# SPDX-License-Identifier: LGPL-2.1-or-later

"""Deterministic placement of drawing dimension text boxes."""


_EPS = 1e-7


def _overlap(a, b):
    return a[0] < b[2] - 1e-9 and b[0] < a[2] - 1e-9 and \
        a[1] < b[3] - 1e-9 and b[1] < a[3] - 1e-9


def _half(label, gap):
    return (label["w"] + gap) / 2.0, (label["h"] + gap) / 2.0


def _box(label, pos, gap):
    hw, hh = _half(label, gap)
    return pos[0] - hw, pos[1] - hh, pos[0] + hw, pos[1] + hh


def _valid(label, pos, keepout, obstacles, gap):
    box = _box(label, pos, gap)
    if _overlap(box, keepout):
        return False
    return all(not _overlap(box, other) for other in obstacles)


def _axis_position(label, keepout, obstacles, gap, axis, centre):
    original = (label["x"], label["y"])
    if _valid(label, original, keepout, obstacles, gap):
        return original
    hw, hh = _half(label, gap)
    fixed = original[1] if axis == "x" else original[0]
    half = hw if axis == "x" else hh
    span = hh if axis == "x" else hw
    intervals = []
    for other in [keepout] + obstacles:
        if axis == "x":
            if fixed + span <= other[1] or other[3] <= fixed - span:
                continue
            intervals.append((other[0] - half - _EPS, other[2] + half + _EPS))
        else:
            if fixed + span <= other[0] or other[2] <= fixed - span:
                continue
            intervals.append((other[1] - half - _EPS, other[3] + half + _EPS))
    value = original[0] if axis == "x" else original[1]
    candidates = [value]
    for low, high in intervals:
        candidates.extend((low, high))
    choices = []
    for candidate in candidates:
        if any(low < candidate < high for low, high in intervals):
            continue
        pos = (candidate, original[1]) if axis == "x" else (original[0], candidate)
        if _valid(label, pos, keepout, obstacles, gap):
            distance = candidate - value
            outward = -abs(candidate - centre)
            choices.append((abs(distance), outward, candidate, pos))
    if choices:
        return min(choices)[-1]
    return original


def _free_position(label, keepout, obstacles, gap, centre):
    original = (label["x"], label["y"])
    if _valid(label, original, keepout, obstacles, gap):
        return original
    hw, hh = _half(label, gap)
    everything = [keepout] + obstacles
    xs = {original[0]}
    ys = {original[1]}
    for other in everything:
        xs.update((other[0] - hw - _EPS, other[2] + hw + _EPS))
        ys.update((other[1] - hh - _EPS, other[3] + hh + _EPS))

    if len(everything) <= 60:
        candidates = ((x, y) for x in xs for y in ys)
    else:
        points = set()
        for other in everything:
            left, right = other[0] - hw - _EPS, other[2] + hw + _EPS
            bottom, top = other[1] - hh - _EPS, other[3] + hh + _EPS
            for x in (left, right):
                points.update(((x, original[1]), (x, bottom), (x, top)))
            for y in (bottom, top):
                points.update(((original[0], y), (left, y), (right, y)))
        candidates = points

    choices = []
    for pos in candidates:
        if not _valid(label, pos, keepout, obstacles, gap):
            continue
        dx, dy = pos[0] - original[0], pos[1] - original[1]
        movement = dx * dx + dy * dy
        outward = -((pos[0] - centre[0]) ** 2 + (pos[1] - centre[1]) ** 2)
        choices.append((movement, outward, pos[1], pos[0], pos))
    if choices:
        return min(choices)[-1]
    return original


def spread(labels, keepout, gap=1.0, max_iter=200):
    """Place labels without overlaps, preserving input order and movement axes."""
    keepout = (keepout[0] - gap / 2.0, keepout[1] - gap / 2.0,
               keepout[2] + gap / 2.0, keepout[3] + gap / 2.0)
    originals = [(label["x"], label["y"]) for label in labels]
    initial = [_box(label, pos, gap) for label, pos in zip(labels, originals)]
    fixed = set()
    for i, box in enumerate(initial):
        if _overlap(box, keepout):
            continue
        if all(i == j or not _overlap(box, other) for j, other in enumerate(initial)):
            fixed.add(i)

    positions = list(originals)
    obstacles = [initial[i] for i in sorted(fixed)]
    centre = ((keepout[0] + keepout[2]) / 2.0, (keepout[1] + keepout[3]) / 2.0)
    for i, label in enumerate(labels):
        if i in fixed:
            continue
        axis = label.get("axis", "free")
        if axis == "x":
            pos = _axis_position(label, keepout, obstacles, gap, "x", centre[0])
        elif axis == "y":
            pos = _axis_position(label, keepout, obstacles, gap, "y", centre[1])
        else:
            pos = _free_position(label, keepout, obstacles, gap, centre)
        positions[i] = pos
        obstacles.append(_box(label, pos, gap))
    return positions
