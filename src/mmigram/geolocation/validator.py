"""
Geographic coordinate validation and sanity verification for seismic observations.
"""

import math
from typing import Optional, Tuple
from ..core.state import Coordinates

# Regional bounding box for Myanmar earthquake observation domain
MYANMAR_BOUNDS = {
    "lat_min": 9.0,
    "lat_max": 29.0,
    "lon_min": 91.0,
    "lon_max": 102.0,
}

# Known key earthquake study cities
CITY_CENTROIDS = {
    "sagaing": (21.8788, 95.9797),
    "mandalay": (21.9750, 96.0833),
    "naypyidaw": (19.7633, 96.0785),
    "yangon": (16.8409, 96.1735),
}


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points in kilometers."""
    r = 6371.0  # Earth's radius in km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def validate_coordinates(
    coords: Coordinates,
    region_bounds: Optional[dict] = MYANMAR_BOUNDS,
    allow_null_island: bool = False,
) -> Coordinates:
    """
    Validate coordinates and annotate with error details.
    
    Identifies:
      - None / uninitialized coordinates
      - (0.0, 0.0) Null Island coordinates (strictly invalid for earthquake reports)
      - Out-of-world coordinates (lat not in [-90, 90], lon not in [-180, 180])
      - Out-of-region coordinates
    """
    if coords.latitude is None or coords.longitude is None:
        coords.is_valid = False
        coords.validation_error = "Missing latitude or longitude"
        coords.confidence = 0.0
        return coords

    lat = float(coords.latitude)
    lon = float(coords.longitude)

    # 1. Check for Null Island (0.0, 0.0)
    if not allow_null_island and abs(lat) < 1e-5 and abs(lon) < 1e-5:
        coords.is_valid = False
        coords.validation_error = "Invalid coordinate (0, 0) / Null Island detected"
        coords.confidence = 0.0
        return coords

    # 2. Check Global Coordinate Bounds
    if not (-90.0 <= lat <= 90.0):
        coords.is_valid = False
        coords.validation_error = f"Latitude {lat} out of valid range [-90, 90]"
        coords.confidence = 0.0
        return coords

    if not (-180.0 <= lon <= 180.0):
        coords.is_valid = False
        coords.validation_error = f"Longitude {lon} out of valid range [-180, 180]"
        coords.confidence = 0.0
        return coords

    # 3. Check Regional Bounds (if specified)
    if region_bounds:
        lat_min = region_bounds["lat_min"]
        lat_max = region_bounds["lat_max"]
        lon_min = region_bounds["lon_min"]
        lon_max = region_bounds["lon_max"]

        if not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max):
            coords.is_valid = False
            coords.validation_error = (
                f"Coordinates ({lat:.4f}, {lon:.4f}) outside regional bounds "
                f"[{lat_min}, {lat_max}] x [{lon_min}, {lon_max}]"
            )
            # Retain lower confidence if it's geographically valid worldwide but outside target region
            coords.confidence = min(coords.confidence, 0.3)
            return coords

    # Valid coordinates
    coords.is_valid = True
    coords.validation_error = None
    if coords.confidence == 0.0:
        coords.confidence = 0.8
    return coords
