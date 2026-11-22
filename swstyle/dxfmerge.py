# SPDX-License-Identifier: LGPL-2.1-or-later

"""Merge nearly coincident DXF line and polyline endpoints."""

import math


def merge_endpoints(items, tol):
    """Return new items with nearby endpoints merged and the number moved."""
    copied = []
    for item in items:
        new = dict(item)
        if "pts" in new:
            new["pts"] = list(new["pts"])
        if "ends" in new:
            new["ends"] = list(new["ends"])
        copied.append(new)
    if tol <= 0:
        return copied, 0

    endpoints = []
    for index, item in enumerate(items):
        kind = item.get("kind")
        if kind == "line":
            points = ((0, item["pts"][0]), (1, item["pts"][1]))
        elif kind == "poly" and not item.get("closed", False):
            points = [(0, item["pts"][0])]
            if len(item["pts"]) > 1:
                points.append((len(item["pts"]) - 1, item["pts"][-1]))
        elif kind == "arc":
            points = ((0, item["ends"][0]), (1, item["ends"][1]))
        else:
            continue
        for point_index, point in points:
            endpoints.append((index, point_index, point, kind == "arc"))

    parent = list(range(len(endpoints)))
    rank = [0] * len(endpoints)

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        a, b = find(i), find(j)
        if a == b:
            return
        if rank[a] < rank[b]:
            a, b = b, a
        parent[b] = a
        if rank[a] == rank[b]:
            rank[a] += 1

    grid = {}
    tolerance2 = tol * tol
    for i, (_item, _point_index, point, _arc) in enumerate(endpoints):
        cell = math.floor(point[0] / tol), math.floor(point[1] / tol)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in grid.get((cell[0] + dx, cell[1] + dy), ()):
                    other = endpoints[j][2]
                    if (point[0] - other[0]) ** 2 + (point[1] - other[1]) ** 2 < tolerance2:
                        union(i, j)
        grid.setdefault(cell, []).append(i)

    groups = {}
    for i in range(len(endpoints)):
        groups.setdefault(find(i), []).append(i)
    targets = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        arc_members = [i for i in members if endpoints[i][3]]
        if arc_members:
            target = endpoints[min(arc_members)][2]
        else:
            target = (sum(endpoints[i][2][0] for i in members) / len(members),
                      sum(endpoints[i][2][1] for i in members) / len(members))
        for i in members:
            targets[i] = target

    moved = 0
    for i, target in targets.items():
        item_index, point_index, point, is_arc = endpoints[i]
        if is_arc or point == target:
            continue
        copied[item_index]["pts"][point_index] = target
        moved += 1

    result = []
    for item in copied:
        kind = item.get("kind")
        if kind == "line" and item["pts"][0] == item["pts"][1]:
            continue
        if kind == "poly":
            points = item["pts"]
            if not points or all(point == points[0] for point in points[1:]):
                continue
        result.append(item)
    return result, moved
