"""
Geographic coordinate and toponym parsing module for earthquake reconnaissance.
"""

import re
from typing import Optional, Tuple
from ..core.state import Coordinates


def dms_to_dd(degrees: float, minutes: float, seconds: float, direction: str) -> float:
    """Convert degrees, minutes, seconds to decimal degrees."""
    dd = float(degrees) + float(minutes) / 60.0 + float(seconds) / 3600.0
    if direction.upper() in ["S", "W"]:
        dd = -dd
    return dd


def parse_dms_string(text: str) -> Optional[Tuple[float, float]]:
    """
    Parse DMS coordinates from text strings.
    Matches formats such as:
      - 21 52' 49.27" N, 95 59' 5.57" E
      - 21°52'49.27"N, 95°59'5.57"E
      - 21° 52' 49.27" N 95° 59' 5.57" E
    """
    dms_pattern = re.compile(
        r"""
        (?P<lat_d>\d+)[°\s]+(?P<lat_m>\d+)['\s]+(?P<lat_s>\d+(?:\.\d+)?)["\s]*(?P<lat_dir>[NSns])
        [\s,;]+
        (?P<lon_d>\d+)[°\s]+(?P<lon_m>\d+)['\s]+(?P<lon_s>\d+(?:\.\d+)?)["\s]*(?P<lon_dir>[EWew])
        """,
        re.VERBOSE,
    )
    match = dms_pattern.search(text)
    if not match:
        return None

    lat = dms_to_dd(
        float(match.group("lat_d")),
        float(match.group("lat_m")),
        float(match.group("lat_s")),
        match.group("lat_dir"),
    )
    lon = dms_to_dd(
        float(match.group("lon_d")),
        float(match.group("lon_m")),
        float(match.group("lon_s")),
        match.group("lon_dir"),
    )
    return lat, lon


def parse_decimal_coordinates(text: str) -> Optional[Tuple[float, float]]:
    """
    Parse decimal degree coordinates from text strings or arrays.
    Matches formats such as:
      - 21.88035, 95.98488
      - 21.88 N, 95.98 E
      - [21.88035, 95.98488]
      - Lat: 21.88035 Lon: 95.98488
    """
    # 1. Decimal coordinates with optional cardinal directions (e.g. 21.88 N, 95.98 E)
    dir_pattern = re.compile(
        r"(?P<lat>[-+]?\d+(?:\.\d+)?)\s*[°]?\s*(?P<lat_dir>[NSns])?[\s,;]+(?P<lon>[-+]?\d+(?:\.\d+)?)\s*[°]?\s*(?P<lon_dir>[EWew])?"
    )
    for match in dir_pattern.finditer(text):
        try:
            lat = float(match.group("lat"))
            lon = float(match.group("lon"))
            lat_dir = match.group("lat_dir")
            lon_dir = match.group("lon_dir")

            if lat_dir and lat_dir.upper() == "S":
                lat = -abs(lat)
            if lon_dir and lon_dir.upper() == "W":
                lon = -abs(lon)

            if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                if lat_dir or lon_dir or (abs(lat) > 0 and abs(lon) > 0):
                    return lat, lon
        except ValueError:
            continue

    # 2. Fallback pair pattern for signed numbers without explicit directions
    pair_pattern = re.compile(
        r"[-+]?(?:[1-8]?\d(?:\.\d+)?|90(?:\.0+)?)[,\s]+[-+]?(?:180(?:\.0+)?|(?:(?:1[0-7]\d)|(?:[1-9]?\d))(?:\.\d+)?)"
    )
    match = pair_pattern.search(text)
    if not match:
        return None

    parts = re.split(r"[,\s]+", match.group().strip())
    if len(parts) >= 2:
        try:
            return float(parts[0]), float(parts[1])
        except ValueError:
            return None
    return None


def extract_coordinates_from_text(text: str) -> Coordinates:
    """
    Attempt to extract coordinates from text, trying DMS first, then decimal degrees.
    """
    if not text:
        return Coordinates(is_valid=False, validation_error="Empty text provided")

    # Try DMS format
    dms_result = parse_dms_string(text)
    if dms_result:
        lat, lon = dms_result
        return Coordinates(
            latitude=round(lat, 6),
            longitude=round(lon, 6),
            source="dms_parsed",
            is_valid=True,
            confidence=0.95,
            is_authoritative=False,
        )

    # Try Decimal Degrees
    dd_result = parse_decimal_coordinates(text)
    if dd_result:
        lat, lon = dd_result
        return Coordinates(
            latitude=round(lat, 6),
            longitude=round(lon, 6),
            source="decimal_parsed",
            is_valid=True,
            confidence=0.85,
            is_authoritative=False,
        )

    return Coordinates(
        latitude=None,
        longitude=None,
        source="not_found",
        is_valid=False,
        validation_error="No recognizable coordinate patterns found in text",
        confidence=0.0,
    )
