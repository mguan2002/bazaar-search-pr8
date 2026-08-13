"""Bounding-box geo filtering + unit conversion + haversine (design doc §5.2, T282737844).

Chosen by proximity spike: bounding-box is MVP, pure arithmetic, zero new deps.
PostGIS ST_DWithin is v1 path (TDD §10).

Reference: bazaar-p3/apps/api/src/bazaar_api/modules/listings/geo.py
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

KM_PER_MILE = 1.60934
_KM_PER_DEG_LAT = 111.0
_EARTH_RADIUS_KM = 6371.0


class RadiusUnit(str, Enum):
    km = "km"
    mi = "mi"


@dataclass(frozen=True)
class BoundingBox:
    south: float
    north: float
    west: float
    east: float


def to_km(radius: float, unit: RadiusUnit) -> float:
    """Convert request radius to km. Validation per K3 / S2 middleware.

    - radius must be finite, >0, <=1000 (defensive cap before 100km post-conversion cap)
    - unit km|mi converted server-side
    """
    if not math.isfinite(radius):
        raise ValueError("radius must be finite")
    if radius <= 0:
        raise ValueError("radius must be > 0")
    if radius > 1000:
        raise ValueError("radius too large")
    if unit == RadiusUnit.km:
        return radius
    if unit == RadiusUnit.mi:
        return radius * KM_PER_MILE
    raise ValueError(f"invalid unit {unit!r}")


def bounding_box(latitude: float, longitude: float, radius_km: float) -> BoundingBox:
    """Return lat/lng bounding box centered on (latitude, longitude).

    One degree latitude ~111 km; longitude shrinks by cos(latitude). Clamp latitude
    [-90,90] and longitude [-180,180]. Near poles lon span widens to full range.
    Antimeridian crossings clamp rather than wrap (US-only MVP, 100km cap).

    Validates finite inputs per K3 guidance.
    """
    if not (
        math.isfinite(latitude)
        and math.isfinite(longitude)
        and math.isfinite(radius_km)
    ):
        raise ValueError("geo inputs must be finite")
    if not (-90.0 <= latitude <= 90.0):
        raise ValueError("latitude out of range")
    if not (-180.0 <= longitude <= 180.0):
        raise ValueError("longitude out of range")
    if radius_km <= 0 or radius_km > 100:
        # Handler enforces <=100 post-conversion; double-check for direct callers
        raise ValueError("radius_km must be in (0, 100]")

    delta_lat = radius_km / _KM_PER_DEG_LAT
    cos_lat = abs(math.cos(math.radians(latitude)))
    if cos_lat < 1e-9:
        delta_lng = 180.0
    else:
        delta_lng = radius_km / (_KM_PER_DEG_LAT * cos_lat)
    delta_lng = min(delta_lng, 180.0)

    return BoundingBox(
        south=max(-90.0, latitude - delta_lat),
        north=min(90.0, latitude + delta_lat),
        west=max(-180.0, longitude - delta_lng),
        east=min(180.0, longitude + delta_lng),
    )


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in km. Python reference for SQL refinement + distance_km projection."""
    if not all(math.isfinite(v) for v in (lat1, lng1, lat2, lng2)):
        raise ValueError("haversine inputs must be finite")
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlng / 2) ** 2
    )
    return _EARTH_RADIUS_KM * 2 * math.asin(math.sqrt(h))
