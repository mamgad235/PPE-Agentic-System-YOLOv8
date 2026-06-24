# backend/agent/zones.py
"""
Tiny zone-geometry helpers. No Shapely dependency.
Polygon = list of [x, y] points. None = full frame (always matches).
"""
from __future__ import annotations

from typing import Optional

Point   = tuple[float, float]
Polygon = list[list[float]]


def point_in_polygon(point: Point, polygon: Optional[Polygon]) -> bool:
    if polygon is None: return True
    x, y = point
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i][0], polygon[i][1]
        xj, yj = polygon[j][0], polygon[j][1]
        intersect = ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi)
        if intersect: inside = not inside
        j = i
    return inside


def box_center(box: list[float]) -> Point:
    x1, y1, x2, y2 = box[0], box[1], box[2], box[3]
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def box_in_polygon(box: list[float], polygon: Optional[Polygon]) -> bool:
    return point_in_polygon(box_center(box), polygon)


def find_zone_for_box(box: list[float], zones: list) -> Optional[str]:
    """
    Given a detection box and the list of ZonePolicy objects (with id/polygon),
    return the id of the first zone whose polygon contains the box center.
    Falls back to 'default' zone (or None if no default exists).
    """
    default_id = None
    for z in zones:
        if z.id == "default": default_id = z.id; continue
        if box_in_polygon(box, z.polygon): return z.id
    return default_id
