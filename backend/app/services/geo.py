"""Geofence math for location check-ins (spec §6.2)."""

from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS_M = 6_371_008.8
LOW_ACCURACY_M = 100.0  # spec §6.2: accuracy > 100m -> NEEDS_REVIEW


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class GeoCheck:
    distance_m: float
    within: bool
    low_accuracy: bool


def evaluate_checkin(
    *,
    lat: float,
    lon: float,
    accuracy_m: float,
    center_lat: float,
    center_lon: float,
    radius_m: float,
) -> GeoCheck:
    """Pass if ``distance - accuracy <= radius``; flag when accuracy is poor (spec §6.2)."""
    dist = haversine_m(lat, lon, center_lat, center_lon)
    return GeoCheck(
        distance_m=dist,
        within=(dist - accuracy_m) <= radius_m,
        low_accuracy=accuracy_m > LOW_ACCURACY_M,
    )
