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


def compare_coordinates(
    doc_coords: Optional[Coordinates],
    model_coords: Optional[Coordinates],
    threshold_km: float = 10.0,
    source_label: str = "Document",
    source_type: Optional[str] = None,
) -> Tuple[str, bool, Optional[float], Optional[str]]:
    """
    Compare document/geocoded/URL candidate coordinates with model-predicted coordinates.
    Identifies specific source comparison status codes:
      - DOCUMENT_VS_MODEL_AGREE / DOCUMENT_VS_MODEL_DISAGREE
      - GEOCODED_VS_MODEL_AGREE / GEOCODED_VS_MODEL_DISAGREE
      - MAP_LINK_VS_MODEL_AGREE / MAP_LINK_VS_MODEL_DISAGREE
      - Legacy COORDINATES_AGREE / COORDINATES_DISAGREE (when source is generic or unspecified)
      - MODEL_LOCATION_UNAVAILABLE, DOCUMENT_LOCATION_UNAVAILABLE, BOTH_LOCATIONS_UNAVAILABLE

    IMPORTANT: Agreement between Gemini and coordinates parsed/geocoded from the same input
    reflects internal consistency and must NOT be presented as independent ground-truth validation.

    Returns:
        (comparison_status, coordinates_disagree, discrepancy_distance_km, discrepancy_details)
    """
    # If source_type is explicitly provided, return specific provenance status
    # (e.g. DOCUMENT_VS_MODEL_AGREE, GEOCODED_VS_MODEL_AGREE, MAP_LINK_VS_MODEL_AGREE).
    # If source_type is omitted/None, preserve legacy status (COORDINATES_AGREE, COORDINATES_DISAGREE).
    effective_source_type = source_type
    effective_label = source_label or ("Document" if not source_type else source_type.replace("_", " ").title())

    doc_valid = (
        doc_coords is not None
        and doc_coords.is_valid
        and doc_coords.latitude is not None
        and doc_coords.longitude is not None
    )
    model_valid = (
        model_coords is not None
        and model_coords.is_valid
        and model_coords.latitude is not None
        and model_coords.longitude is not None
    )

    if doc_valid and model_valid:
        dist = haversine_distance_km(
            doc_coords.latitude, doc_coords.longitude,
            model_coords.latitude, model_coords.longitude
        )
        dist_round = round(dist, 2)
        if dist > threshold_km:
            status = f"{effective_source_type}_VS_MODEL_DISAGREE" if effective_source_type else "COORDINATES_DISAGREE"
            details = (
                f"{effective_label} coordinates ({doc_coords.latitude:.4f}, {doc_coords.longitude:.4f}) and "
                f"model coordinates ({model_coords.latitude:.4f}, {model_coords.longitude:.4f}) "
                f"disagree by {dist:.1f} km (threshold: {threshold_km:.1f} km)."
            )
            return (status, True, dist_round, details)
        else:
            status = f"{effective_source_type}_VS_MODEL_AGREE" if effective_source_type else "COORDINATES_AGREE"
            details = (
                f"{effective_label} coordinates ({doc_coords.latitude:.4f}, {doc_coords.longitude:.4f}) and "
                f"model coordinates ({model_coords.latitude:.4f}, {model_coords.longitude:.4f}) "
                f"agree within {dist:.1f} km (threshold: {threshold_km:.1f} km). "
                f"Note: model coordinates and {effective_label.lower()} coordinates were derived from the same source document input "
                "and do not constitute independent authoritative GIS validation."
            )
            return (status, False, dist_round, details)

    elif doc_valid and not model_valid:
        if model_coords is not None and model_coords.validation_error:
            status = f"{effective_source_type}_VS_MODEL_DISAGREE" if effective_source_type else "COORDINATES_DISAGREE"
            details = (
                f"{effective_label} text contains valid coordinates ({doc_coords.latitude:.4f}, {doc_coords.longitude:.4f}), "
                f"but model returned invalid coordinates: {model_coords.validation_error}"
            )
            return (status, True, None, details)
        else:
            details = f"{effective_label} text provided valid coordinates, but model location was unavailable (Unknown)."
            return ("MODEL_LOCATION_UNAVAILABLE", False, None, details)

    elif not doc_valid and model_valid:
        details = (
            f"Model predicted coordinates ({model_coords.latitude:.4f}, {model_coords.longitude:.4f}), "
            f"but no coordinates were detected in {effective_label.lower()} text."
        )
        status = f"{effective_source_type}_LOCATION_UNAVAILABLE" if effective_source_type else "DOCUMENT_LOCATION_UNAVAILABLE"
        return (status, False, None, details)

    else:
        details = f"Neither {effective_label.lower()} text nor multimodal model established geographic coordinates."
        return ("BOTH_LOCATIONS_UNAVAILABLE", False, None, details)
