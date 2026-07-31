"""Bounding-box geo filtering (design doc §5.2).

Pure arithmetic — no PostGIS dependency. Accurate enough for MVP city-scale radii
(< 100K listings). Upgrade path to PostGIS ST_DWithin is documented as v1 (§10).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_KM_PER_DEG_LAT = 111.0


@dataclass(frozen=True)
class BoundingBox:
    south: float
    north: float
    west: float
    east: float


def bounding_box(latitude: float, longitude: float, radius_km: float) -> BoundingBox:
    """Return the lat/lng bounding box centered on (latitude, longitude).

    One degree of latitude is ~111 km everywhere; one degree of longitude shrinks by
    cos(latitude). We clamp latitude bounds to [-90, 90]. Near the poles the longitude
    span widens toward the full [-180, 180]; we clamp there to avoid division blow-up.
    """
    delta_lat = radius_km / _KM_PER_DEG_LAT
    cos_lat = math.cos(math.radians(latitude))
    if abs(cos_lat) < 1e-9:
        delta_lng = 180.0
    else:
        delta_lng = radius_km / (_KM_PER_DEG_LAT * cos_lat)

    return BoundingBox(
        south=max(-90.0, latitude - delta_lat),
        north=min(90.0, latitude + delta_lat),
        west=max(-180.0, longitude - abs(delta_lng)),
        east=min(180.0, longitude + abs(delta_lng)),
    )
