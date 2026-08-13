"""PR4 verification — geo primitive unit tests incl. mi→km conversion (T282737844/68).

Kept for PR8 slice completeness; PR4 already delivered but slice still needs validation.
"""

from __future__ import annotations

import math

import pytest

from app.geo import RadiusUnit, bounding_box, haversine_km, to_km
from app.search import GeoFilter, parse_geo


def test_to_km_km():
    assert to_km(10, RadiusUnit.km) == 10


def test_to_km_mi():
    assert math.isclose(to_km(1, RadiusUnit.mi), 1.60934, rel_tol=1e-3)
    assert math.isclose(to_km(10, RadiusUnit.mi), 16.0934, rel_tol=1e-3)


def test_to_km_validation():
    with pytest.raises(ValueError):
        to_km(0, RadiusUnit.km)
    with pytest.raises(ValueError):
        to_km(-5, RadiusUnit.km)
    with pytest.raises(ValueError):
        to_km(float("inf"), RadiusUnit.km)
    with pytest.raises(ValueError):
        to_km(float("nan"), RadiusUnit.km)


def test_parse_geo_basic():
    g = parse_geo(37.7749, -122.4194, 5, "km")
    assert g is not None
    assert g.radius_km == 5


def test_parse_geo_mi_conversion():
    g = parse_geo(37.7749, -122.4194, 1, "mi")
    assert g is not None
    assert math.isclose(g.radius_km, 1.60934, rel_tol=1e-3)


def test_parse_geo_cap_after_conversion():
    with pytest.raises(ValueError, match="100 km"):
        parse_geo(37.7749, -122.4194, 70, "mi")  # 70mi=112km >100
    with pytest.raises(ValueError, match="100 km"):
        parse_geo(37.7749, -122.4194, 200, "km")


def test_parse_geo_pairwise():
    with pytest.raises(ValueError, match="together"):
        parse_geo(37.7749, None, 5, "km")
    with pytest.raises(ValueError, match="together"):
        parse_geo(None, -122.4194, 5, "km")
    assert parse_geo(None, None, None, None) is None


def test_bounding_box_basic():
    box = bounding_box(37.7749, -122.4194, 5)
    assert box.south < 37.7749 < box.north
    assert box.west < -122.4194 < box.east


def test_bounding_box_pole():
    # Near pole, north clamps to 90 when radius pushes over
    box = bounding_box(89.95, 0, 10)
    assert box.north == 90.0
    assert box.south < 89.95
    # Exactly at 89.9 + small radius stays below 90
    box2 = bounding_box(89.9, 0, 5)
    assert box2.south < 89.9 < box2.north
    assert box2.north <= 90.0


def test_haversine_zero():
    assert haversine_km(37.7749, -122.4194, 37.7749, -122.4194) == 0.0


def test_haversine_known_distance():
    # SF to Oakland ~13km
    d = haversine_km(37.7749, -122.4194, 37.8044, -122.2712)
    assert 10 < d < 16


def test_geo_filter_validation():
    with pytest.raises(ValueError):
        GeoFilter(lat=float("nan"), lng=-122.4194, radius_km=5)
    with pytest.raises(ValueError):
        GeoFilter(lat=100, lng=-122.4194, radius_km=5)
    with pytest.raises(ValueError):
        GeoFilter(lat=37.7749, lng=-122.4194, radius_km=200)
