"""
Unified Geolocation Resolver for Earthquake Reconnaissance.

Integrates:
- Priority 1: Site-specific DMS and directional decimal coordinates from document text.
- Priority 2: Direct coordinates embedded in mapping URLs (Google Maps, OSM, Apple, Bing, geo:).
- Priority 3: Safe short URL expansion and place name resolution from mapping links.
- Priority 4: Guarded Google Maps Geocoding API lookup for verified observation addresses.
- Priority 5: Fallback retaining null coordinates for human review (never substituting epicenter).

Enforces:
- Separation of document, mapping-link, geocoded, and model coordinates.
- Prevention of author/institution/epicenter substitution for observation locations.
- Complete coordinate provenance and ShakeMap export qualification.
"""

from __future__ import annotations
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple, Callable, Union

from ..core.state import Coordinates, LocationContext
from .parser import dms_to_dd
from .validator import (
    validate_coordinates,
    compare_coordinates,
    haversine_distance_km,
    MYANMAR_BOUNDS,
    CITY_CENTROIDS,
)
from .url_resolver import MapURLResolver, MapURLExtraction
from .geocoding_adapter import GoogleMapsGeocodingAdapter, GeocodedResult

# Known scientific reconnaissance organizations and author institutions to prevent
# mistakenly treating the author's affiliated institution as the earthquake observation site.
KNOWN_AUTHOR_INSTITUTIONS = [
    "usgs",
    "united states geological survey",
    "steer",
    "structural extreme events reconnaissance",
    "eeri",
    "earthquake engineering research institute",
    "geer",
    "mandalay university",
    "yangon university",
    "earthquake science center",
    "menlo park",
]


class UnifiedGeolocationResolver:
    """
    Unified, multi-stage geolocation resolution engine with strict scientific provenance.
    """

    def __init__(
        self,
        region_bounds: Optional[Dict[str, float]] = None,
        event_epicenter: Optional[Tuple[float, float]] = None,
        geocoding_adapter: Optional[GoogleMapsGeocodingAdapter] = None,
        allow_live_geocoding: bool = False,
    ):
        self.region_bounds = region_bounds or MYANMAR_BOUNDS
        self.event_epicenter = event_epicenter
        self.geocoding_adapter = geocoding_adapter or GoogleMapsGeocodingAdapter(
            allow_live_geocoding=allow_live_geocoding
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Parsing Helpers (DMS, Decimal, Section Address)
    # ──────────────────────────────────────────────────────────────────────────

    @classmethod
    def parse_dms(cls, text: str) -> Optional[Tuple[float, float, str]]:
        """
        Parse Degrees-Minutes-Seconds coordinates supporting:
        - Lat first: 21°52'49.27"N, 95°59'5.57"E
        - Lon first: 95°59'5.57"E, 21°52'49.27"N
        - Decimal minutes: 21°52.82'N, 95°59.09'E
        - Flexible separators and punctuation.
        Returns (latitude, longitude, raw_match).
        """
        if not text:
            return None

        # 1. Full DMS Lat first: 21°52'49.27"N, 95°59'5.57"E or 21 58’ 42.10" N, 96 05’ 20.30" E
        lat_first = re.search(
            r'(\d{1,2})\s*[°ddeg\s]+\s*(\d{1,2})\s*[\'’‘′mmin\s]+\s*([\d.]+)\s*[\"”″ssec\s]*([NSns])\s*[,;\s/|]+\s*(\d{1,3})\s*[°ddeg\s]+\s*(\d{1,2})\s*[\'’‘′mmin\s]+\s*([\d.]+)\s*[\"”″ssec\s]*([EWew])',
            text, re.IGNORECASE
        )
        if lat_first:
            lat_d, lat_m, lat_s, lat_dir, lon_d, lon_m, lon_s, lon_dir = lat_first.groups()
            lat = dms_to_dd(float(lat_d), float(lat_m), float(lat_s), lat_dir)
            lon = dms_to_dd(float(lon_d), float(lon_m), float(lon_s), lon_dir)
            return round(lat, 6), round(lon, 6), lat_first.group(0)

        # 2. Full DMS Lon first: 95°59'5.57"E, 21°52'49.27"N
        lon_first = re.search(
            r'(\d{1,3})\s*[°ddeg\s]+\s*(\d{1,2})\s*[\'’‘′mmin\s]+\s*([\d.]+)\s*[\"”″ssec\s]*([EWew])\s*[,;\s/|]+\s*(\d{1,2})\s*[°ddeg\s]+\s*(\d{1,2})\s*[\'’‘′mmin\s]+\s*([\d.]+)\s*[\"”″ssec\s]*([NSns])',
            text, re.IGNORECASE
        )
        if lon_first:
            lon_d, lon_m, lon_s, lon_dir, lat_d, lat_m, lat_s, lat_dir = lon_first.groups()
            lat = dms_to_dd(float(lat_d), float(lat_m), float(lat_s), lat_dir)
            lon = dms_to_dd(float(lon_d), float(lon_m), float(lon_s), lon_dir)
            return round(lat, 6), round(lon, 6), lon_first.group(0)

        # 3. Decimal minutes: 21°52.82'N, 95°59.09'E
        dm_match = re.search(
            r'(\d{1,2})\s*[°ddeg\s]+\s*([\d.]+)\s*[\'’‘′mmin\s]*\s*([NSns])\s*[,;\s/|]+\s*(\d{1,3})\s*[°ddeg\s]+\s*([\d.]+)\s*[\'’‘′mmin\s]*\s*([EWew])',
            text, re.IGNORECASE
        )
        if dm_match:
            lat_d, lat_m, lat_dir, lon_d, lon_m, lon_dir = dm_match.groups()
            lat = float(lat_d) + float(lat_m) / 60.0
            if lat_dir.upper() == "S":
                lat = -lat
            lon = float(lon_d) + float(lon_m) / 60.0
            if lon_dir.upper() == "W":
                lon = -lon
            return round(lat, 6), round(lon, 6), dm_match.group(0)

        return None

    @classmethod
    def parse_directional_decimal(cls, text: str) -> Optional[Tuple[float, float, str]]:
        """
        Parse decimal degrees with explicit cardinal directions (N/S, E/W).
        e.g. 21.88035° N, 95.98488° E or -21.88 S, 95.98 E
        """
        if not text:
            return None

        # Lat first: 21.88035° N, 95.98488° E
        m_lat = re.search(
            r'(\d{1,2}(?:\.\d+)?)\s*°?\s*([NSns])\s*[,;\s/|]+\s*(\d{1,3}(?:\.\d+)?)\s*°?\s*([EWew])',
            text, re.IGNORECASE
        )
        if m_lat:
            lat_v, lat_dir, lon_v, lon_dir = m_lat.groups()
            lat = float(lat_v) if lat_dir.upper() == "N" else -float(lat_v)
            lon = float(lon_v) if lon_dir.upper() == "E" else -float(lon_v)
            return round(lat, 6), round(lon, 6), m_lat.group(0)

        # Lon first: 95.98488° E, 21.88035° N
        m_lon = re.search(
            r'(\d{1,3}(?:\.\d+)?)\s*°?\s*([EWew])\s*[,;\s/|]+\s*(\d{1,2}(?:\.\d+)?)\s*°?\s*([NSns])',
            text, re.IGNORECASE
        )
        if m_lon:
            lon_v, lon_dir, lat_v, lat_dir = m_lon.groups()
            lat = float(lat_v) if lat_dir.upper() == "N" else -float(lat_v)
            lon = float(lon_v) if lon_dir.upper() == "E" else -float(lon_v)
            return round(lat, 6), round(lon, 6), m_lon.group(0)

        return None

    @classmethod
    def parse_explicit_coordinate_pairs(cls, text: str) -> Optional[Tuple[float, float, str]]:
        """
        Parse bracketed [lat, lon], key-value lat: ... lon: ..., or section decimal pairs.
        """
        if not text:
            return None

        # 1. Bracketed [lat, lon] or (lat, lon)
        bracket_m = re.search(r'[\[\(]\s*(-?\d{1,2}\.\d{3,8})\s*,\s*(-?\d{1,3}\.\d{3,8})\s*[\]\)]', text)
        if bracket_m:
            return round(float(bracket_m.group(1)), 6), round(float(bracket_m.group(2)), 6), bracket_m.group(0)

        # 2. Key-value: Lat: 21.88035, Lon: 95.98488
        kv_m = re.search(
            r'lat(?:itude)?[:=\s]+(-?\d{1,2}\.\d{3,8})[^\n\r]*?lon(?:gitude)?[:=\s]+(-?\d{1,3}\.\d{3,8})',
            text, re.IGNORECASE
        )
        if kv_m:
            return round(float(kv_m.group(1)), 6), round(float(kv_m.group(2)), 6), kv_m.group(0)

        # 3. Explicit section line: "Geolocation: 21.88035, 95.98488"
        sec_m = re.search(
            r'Geolocation[^\n\r:]*?:\s*.*?(-?\d{1,2}\.\d{3,8})\s*,\s*(-?\d{1,3}\.\d{3,8})',
            text, re.IGNORECASE
        )
        if sec_m:
            return round(float(sec_m.group(1)), 6), round(float(sec_m.group(2)), 6), sec_m.group(0)

        # 4. Standard coordinate pair (e.g. 21.88035, 95.98488) not part of a URL
        pair_m = re.search(
            r'(?<![\w/@&?=])([+-]?\d{1,2}\.\d{4,8})\s*,\s*([+-]?\d{1,3}\.\d{4,8})(?![\w./?&=])',
            text
        )
        if pair_m:
            lat = float(pair_m.group(1))
            lon = float(pair_m.group(2))
            if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                return round(lat, 6), round(lon, 6), pair_m.group(0)

        return None

    @classmethod
    def extract_section_location_info(cls, text: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract the location/address string and raw source text line from standard
        'Geolocation (Address/Coordinates): ...' or 'Location: ...' blocks.
        Returns (clean_address, raw_section_line).
        """
        if not text:
            return None, None

        match = re.search(
            r'(?:Geolocation\s*(?:\([^)]*\))?|Location|Address)\s*[:\s]+\s*([^\n\r]+(?:\n[^\n\r]+)?)',
            text, re.IGNORECASE
        )
        if not match:
            return None, None

        raw_line = match.group(0).strip()
        candidate = match.group(1).strip()

        # Remove mapping URLs
        candidate = re.sub(r'https?://\S+', '', candidate).strip()
        # Remove DMS and coordinates
        candidate = re.sub(r'\d+°\S+', '', candidate).strip()
        candidate = re.sub(r'[-+]?\d+\.\d+\s*,\s*[-+]?\d+\.\d+', '', candidate).strip()
        candidate = re.sub(r'\[\s*[-+]?\d+.*?\]', '', candidate)
        candidate = re.sub(r'\(\s*[-+]?\d+.*?\)', '', candidate)
        candidate = re.sub(r'\[\s*\]|\(\s*\)', '', candidate).strip(" ,;:/-[]()")

        lines = [line.strip(" ,;:/-") for line in candidate.splitlines() if line.strip(" ,;:/-")]
        if lines:
            clean_addr = lines[0]
            if clean_addr.lower() not in ("unknown", "n/a", "none", "see below", "image", "not available"):
                return clean_addr, raw_line

        return None, raw_line

    @classmethod
    def is_author_or_institution(cls, text: str, institutions: Optional[List[str]] = None) -> bool:
        """
        Detect whether a location candidate is an author/reconnaissance institution
        (e.g. USGS Menlo Park, EERI, StEER) rather than a field earthquake observation site.
        """
        if not text:
            return False
        clean = text.lower().strip()
        inst_list = institutions or KNOWN_AUTHOR_INSTITUTIONS
        for inst in inst_list:
            if inst in clean:
                return True
        return False

    @classmethod
    def is_near_epicenter(
        cls,
        lat: float,
        lon: float,
        epicenter: Optional[Tuple[float, float]],
        tolerance_km: float = 1.0,
    ) -> bool:
        """
        Check if coordinates match the event epicenter within tight tolerance.
        """
        if not epicenter:
            return False
        dist = haversine_distance_km(lat, lon, epicenter[0], epicenter[1])
        return dist <= tolerance_km

    @classmethod
    def is_epicenter_metadata(cls, text: str, match_str: str) -> bool:
        """
        Determine whether coordinates appearing in text are described as earthquake
        event metadata (e.g. mainshock epicenter/hypocenter coordinates) rather than
        an actual physical damage observation site.
        """
        if not text:
            return False

        pos = text.find(match_str)
        if pos == -1:
            chunk = text[:250]
        else:
            start = max(0, pos - 150)
            end = min(len(text), pos + len(match_str) + 150)
            chunk = text[start:end]

        chunk_lower = chunk.lower()

        # Check for explicit metadata labels
        is_labeled_epicenter = bool(re.search(
            r'\b(?:epicenter|hypocenter)\s*(?:coordinates)?\s*[:=\s]+[^.\n]*?' + re.escape(match_str),
            chunk,
            re.IGNORECASE
        ))

        is_metadata_header = bool(re.search(
            r'\b(?:epicenter|hypocenter|event\s+parameters|mainshock\s+location|earthquake\s+source|origin\s+time|magnitude|mw\s*\d)\b',
            chunk_lower
        ))

        # Check if the surrounding text explicitly describes physical damage or field inspection
        has_field_damage_context = bool(re.search(
            r'\b(?:damage|collapsed?|cracking|inspection|building|bridge|pagoda|hospital|school|survey|field\s+observation|surface\s+rupture|observed\s+at)\b',
            chunk_lower
        ))

        # If it is labeled as an epicenter header without physical building/site damage observations, reject as metadata
        if is_labeled_epicenter and not has_field_damage_context:
            return True

        if is_metadata_header and not has_field_damage_context:
            return True

        return False

    # ──────────────────────────────────────────────────────────────────────────
    # Main Unified Resolution Engine
    # ──────────────────────────────────────────────────────────────────────────

    def resolve(
        self,
        text: Optional[str] = None,
        file_path: Optional[Union[str, Path]] = None,
        model_location: Optional[Dict[str, Any]] = None,
        region_bounds: Optional[Dict[str, float]] = None,
        event_epicenter: Optional[Tuple[float, float]] = None,
        author_institutions: Optional[List[str]] = None,
        allow_live_geocoding: Optional[bool] = None,
        url_expander: Optional[Callable[[str], Optional[str]]] = None,
    ) -> LocationContext:
        """
        Execute the unified 5-priority geolocation resolution process.
        """
        bounds = region_bounds or self.region_bounds
        epicenter = event_epicenter or self.event_epicenter

        # Coordinate candidates for provenance tracking
        doc_coords: Optional[Coordinates] = None
        mapping_link_coords: Optional[Coordinates] = None
        geocoded_coords: Optional[Coordinates] = None
        model_coords: Optional[Coordinates] = None

        primary_coords: Optional[Coordinates] = None
        selection_rationale: Optional[str] = None
        precision_level: str = "unknown"
        place_name: Optional[str] = None
        resolved_address: Optional[str] = None
        raw_source_snippet: Optional[str] = None
        conflicting_candidates: bool = False
        conflict_details: Optional[str] = None

        # Step 0: Extract section location and address text
        if text:
            section_addr, raw_line = self.extract_section_location_info(text)
            resolved_address = section_addr
            raw_source_snippet = raw_line

            # Reject author institution as observation address
            if resolved_address and self.is_author_or_institution(resolved_address, author_institutions):
                resolved_address = None

        # ──────────────────────────────────────────────────────────────────────
        # Priority 1: Explicit site-specific coordinates in document text
        # ──────────────────────────────────────────────────────────────────────
        if text:
            # 1a. Try DMS
            dms_res = self.parse_dms(text)
            if dms_res:
                lat, lon, match_str = dms_res
                cand = Coordinates(
                    latitude=lat,
                    longitude=lon,
                    source="dms_parsed",
                    is_valid=True,
                    confidence=0.95,
                    precision_level="exact_site_dms",
                )
                cand = validate_coordinates(cand, region_bounds=None)
                if cand.is_valid:
                    if bounds:
                        cand.is_within_regional_bounds = (
                            bounds["lat_min"] <= cand.latitude <= bounds["lat_max"]
                            and bounds["lon_min"] <= cand.longitude <= bounds["lon_max"]
                        )
                    if not cand.is_within_regional_bounds:
                        cand.confidence = min(cand.confidence, 0.70)
                        cand.validation_error = (
                            f"Coordinates ({cand.latitude:.4f}, {cand.longitude:.4f}) outside regional bounds "
                            f"[{bounds['lat_min']}, {bounds['lat_max']}] x [{bounds['lon_min']}, {bounds['lon_max']}]; flagged for review."
                        )
                    doc_coords = cand
                    if not raw_source_snippet:
                        raw_source_snippet = match_str

            # 1b. Try Directional Decimal Degrees
            if not doc_coords:
                dec_dir_res = self.parse_directional_decimal(text)
                if dec_dir_res:
                    lat, lon, match_str = dec_dir_res
                    cand = Coordinates(
                        latitude=lat,
                        longitude=lon,
                        source="decimal_parsed",
                        is_valid=True,
                        confidence=0.90,
                        precision_level="exact_site_dd",
                    )
                    cand = validate_coordinates(cand, region_bounds=None)
                    if cand.is_valid:
                        if bounds:
                            cand.is_within_regional_bounds = (
                                bounds["lat_min"] <= cand.latitude <= bounds["lat_max"]
                                and bounds["lon_min"] <= cand.longitude <= bounds["lon_max"]
                            )
                        if not cand.is_within_regional_bounds:
                            cand.confidence = min(cand.confidence, 0.70)
                            cand.validation_error = (
                                f"Coordinates ({cand.latitude:.4f}, {cand.longitude:.4f}) outside regional bounds "
                                f"[{bounds['lat_min']}, {bounds['lat_max']}] x [{bounds['lon_min']}, {bounds['lon_max']}]; flagged for review."
                            )
                        doc_coords = cand
                        if not raw_source_snippet:
                            raw_source_snippet = match_str

            # 1c. Try Explicit Coordinate Pairs
            if not doc_coords:
                dec_pair_res = self.parse_explicit_coordinate_pairs(text)
                if dec_pair_res:
                    lat, lon, match_str = dec_pair_res
                    cand = Coordinates(
                        latitude=lat,
                        longitude=lon,
                        source="decimal_parsed",
                        is_valid=True,
                        confidence=0.85,
                        precision_level="exact_site_dd",
                    )
                    cand = validate_coordinates(cand, region_bounds=None)
                    if cand.is_valid:
                        if bounds:
                            cand.is_within_regional_bounds = (
                                bounds["lat_min"] <= cand.latitude <= bounds["lat_max"]
                                and bounds["lon_min"] <= cand.longitude <= bounds["lon_max"]
                            )
                        if not cand.is_within_regional_bounds:
                            cand.confidence = min(cand.confidence, 0.70)
                            cand.validation_error = (
                                f"Coordinates ({cand.latitude:.4f}, {cand.longitude:.4f}) outside regional bounds "
                                f"[{bounds['lat_min']}, {bounds['lat_max']}] x [{bounds['lon_min']}, {bounds['lon_max']}]; flagged for review."
                            )
                        doc_coords = cand
                        if not raw_source_snippet:
                            raw_source_snippet = match_str

        # If document coordinates found, check against epicenter metadata
        if doc_coords and doc_coords.is_valid:
            if epicenter and self.is_near_epicenter(doc_coords.latitude, doc_coords.longitude, epicenter):
                if self.is_epicenter_metadata(text, raw_source_snippet or ""):
                    # Document coordinates match event epicenter metadata!
                    doc_coords.is_valid = False
                    doc_coords.validation_error = "Parsed coordinates match earthquake epicenter metadata; cannot be substituted for observation site."
                    doc_coords.confidence = 0.0
                    doc_coords = None
                else:
                    # Genuine damage observation located near the epicenter
                    primary_coords = doc_coords
                    precision_level = doc_coords.precision_level
                    selection_rationale = (
                        f"Priority 1: Site-specific coordinates ({doc_coords.source}) parsed directly from document text "
                        "(valid field observation located at/near epicentral zone)."
                    )
            else:
                primary_coords = doc_coords
                precision_level = doc_coords.precision_level
                selection_rationale = (
                    f"Priority 1: Site-specific coordinates ({doc_coords.source}) parsed directly from document text."
                )

        # ──────────────────────────────────────────────────────────────────────
        # Priority 2: Coordinates embedded directly in mapping URLs
        # ──────────────────────────────────────────────────────────────────────
        if text:
            urls = MapURLResolver.extract_mapping_urls(text)
            for u in urls:
                # 2a. Direct extraction without network
                extraction = MapURLResolver.parse_embedded_coordinates(u)
                if extraction and extraction.is_valid:
                    cand = extraction.to_coordinates()
                    if cand:
                        cand = validate_coordinates(cand, region_bounds=None)
                        if cand.is_valid:
                            if bounds:
                                cand.is_within_regional_bounds = (
                                    bounds["lat_min"] <= cand.latitude <= bounds["lat_max"]
                                    and bounds["lon_min"] <= cand.longitude <= bounds["lon_max"]
                                )
                            mapping_link_coords = cand
                            if extraction.place_name and not place_name:
                                place_name = extraction.place_name
                            if not raw_source_snippet:
                                raw_source_snippet = u
                            break

                # 2b. Priority 3 check: Shortened URL expansion
                if ("goo.gl" in u or "maps.app" in u) and not mapping_link_coords:
                    expanded = MapURLResolver.resolve_shortened_url(
                        u,
                        allow_network=False,  # strictly offline safe unless test expander registered
                        custom_resolver=url_expander,
                    )
                    if expanded:
                        exp_ext = MapURLResolver.parse_embedded_coordinates(expanded)
                        if exp_ext and exp_ext.is_valid:
                            cand = exp_ext.to_coordinates()
                            if cand:
                                cand = validate_coordinates(cand, region_bounds=None)
                                if cand.is_valid:
                                    if bounds:
                                        cand.is_within_regional_bounds = (
                                            bounds["lat_min"] <= cand.latitude <= bounds["lat_max"]
                                            and bounds["lon_min"] <= cand.longitude <= bounds["lon_max"]
                                        )
                                    mapping_link_coords = cand
                                    if exp_ext.place_name and not place_name:
                                        place_name = exp_ext.place_name
                                    if not raw_source_snippet:
                                        raw_source_snippet = u
                                    break
                        elif exp_ext and exp_ext.place_name and not place_name:
                            place_name = exp_ext.place_name

        # Check for conflict between document coordinates and mapping link coordinates
        if doc_coords and doc_coords.is_valid and mapping_link_coords and mapping_link_coords.is_valid:
            dist_km = haversine_distance_km(
                doc_coords.latitude, doc_coords.longitude,
                mapping_link_coords.latitude, mapping_link_coords.longitude
            )
            if dist_km > 10.0:
                conflicting_candidates = True
                conflict_details = (
                    f"Document text coordinates ({doc_coords.latitude:.4f}, {doc_coords.longitude:.4f}) and "
                    f"mapping link coordinates ({mapping_link_coords.latitude:.4f}, {mapping_link_coords.longitude:.4f}) "
                    f"conflict by {dist_km:.1f} km."
                )

        # Adopt mapping link coordinates if Priority 1 was not available
        if not primary_coords and mapping_link_coords and mapping_link_coords.is_valid:
            if epicenter and self.is_near_epicenter(mapping_link_coords.latitude, mapping_link_coords.longitude, epicenter) and self.is_epicenter_metadata(text, raw_source_snippet or ""):
                mapping_link_coords.is_valid = False
                mapping_link_coords.validation_error = "Mapping link matches earthquake epicenter metadata; cannot be substituted for observation site."
            else:
                primary_coords = mapping_link_coords
                precision_level = mapping_link_coords.precision_level
                if precision_level == "url_viewport_approximate":
                    selection_rationale = (
                        "Priority 2: Contextual map viewport center extracted from URL "
                        "(not an explicit observation site pin; ineligible for ShakeMap export)."
                    )
                else:
                    selection_rationale = (
                        f"Priority 2: Site-specific coordinates extracted directly from embedded mapping URL ({mapping_link_coords.source})."
                    )

        # ──────────────────────────────────────────────────────────────────────
        # Priority 4: Optional Google Maps Geocoding API lookup
        # ──────────────────────────────────────────────────────────────────────
        if not primary_coords:
            geocoding_query = place_name or resolved_address
            if geocoding_query and not self.is_author_or_institution(geocoding_query, author_institutions):
                # Attempt geocoding via adapter
                geo_res = self.geocoding_adapter.geocode(geocoding_query)
                if geo_res:
                    cand = geo_res.to_coordinates()
                    cand = validate_coordinates(cand, region_bounds=None)
                    if cand.is_valid:
                        if bounds:
                            cand.is_within_regional_bounds = (
                                bounds["lat_min"] <= cand.latitude <= bounds["lat_max"]
                                and bounds["lon_min"] <= cand.longitude <= bounds["lon_max"]
                            )
                        if epicenter and self.is_near_epicenter(cand.latitude, cand.longitude, epicenter) and self.is_epicenter_metadata(text, geocoding_query):
                            cand.is_valid = False
                            cand.validation_error = "Geocoded address matches earthquake epicenter metadata; cannot be substituted for observation site."
                        else:
                            geocoded_coords = cand
                            primary_coords = cand
                            precision_level = geo_res.precision_level
                            resolved_address = geo_res.formatted_address
                            selection_rationale = (
                                f"Priority 4: Geocoded from observation site query '{geocoding_query}' "
                                f"(precision: {geo_res.precision_level}, type: {geo_res.location_type})."
                            )

        # ──────────────────────────────────────────────────────────────────────
        # Priority 5: Fallback to Null Coordinates (Never Fabricate or Substitute)
        # ──────────────────────────────────────────────────────────────────────
        if not primary_coords:
            precision_level = "unknown"
            selection_rationale = (
                "Priority 5: No explicit coordinates, embedded mapping links, or geocodable observation site "
                "were detected in input evidence. Retained as coordinates: null for human review."
            )

        # ──────────────────────────────────────────────────────────────────────
        # Model Coordinates & Discrepancy Analysis (Separation of Provenance)
        # ──────────────────────────────────────────────────────────────────────
        if isinstance(model_location, dict):
            m_coords_raw = model_location.get("coordinates")
            if isinstance(m_coords_raw, (list, tuple)) and len(m_coords_raw) == 2:
                try:
                    m_lat = float(m_coords_raw[0])
                    m_lon = float(m_coords_raw[1])
                    cand_model = Coordinates(
                        latitude=m_lat,
                        longitude=m_lon,
                        source="model_predicted",
                        is_authoritative=False,
                    )
                    model_coords = validate_coordinates(cand_model, region_bounds=None)
                except (ValueError, TypeError):
                    model_coords = None

        # Determine source label and type for model comparison provenance
        if primary_coords is not None:
            if doc_coords is not None and primary_coords == doc_coords:
                source_type = "DOCUMENT"
                source_label = "Document"
            elif geocoded_coords is not None and primary_coords == geocoded_coords:
                source_type = "GEOCODED"
                source_label = "Geocoded"
            elif mapping_link_coords is not None and primary_coords == mapping_link_coords:
                source_type = "MAP_LINK"
                source_label = "Mapping link"
            else:
                source_type = "PRIMARY"
                source_label = "Primary candidate"
        else:
            source_type = None
            source_label = "Document"

        # Compare primary resolved coordinates with model coordinates
        (
            comp_status,
            coords_disagree,
            dist_km,
            discrepancy_details,
        ) = compare_coordinates(
            primary_coords,
            model_coords,
            threshold_km=10.0,
            source_label=source_label,
            source_type=source_type,
        )

        # If document coordinates and mapping link coordinates actively conflicted, flag it
        if conflicting_candidates:
            coords_disagree = True
            comp_status = "COORDINATES_DISAGREE"
            discrepancy_details = (
                f"{conflict_details} "
                + (f"Model comparison: {discrepancy_details}" if discrepancy_details else "")
            )

        # ──────────────────────────────────────────────────────────────────────
        # ShakeMap Spatial Qualification (has_exportable_site_coordinates)
        # ──────────────────────────────────────────────────────────────────────
        # True ONLY if coordinates are valid, site-specific, not in conflict, within regional bounds,
        # and not approximate city centroids or viewport centers.
        has_exportable_coords = False
        is_within_region = True
        if primary_coords and primary_coords.is_valid:
            is_within_region = getattr(primary_coords, "is_within_regional_bounds", True)
            if not coords_disagree:
                if is_within_region:
                    if precision_level in (
                        "exact_site_dms",
                        "exact_site_dd",
                        "url_poi_marker",
                        "url_query_pin",
                        "geocoded_rooftop",
                        "geocoded_interpolated",
                    ):
                        has_exportable_coords = True

        return LocationContext(
            address=resolved_address,
            place_name=place_name,
            coordinates=primary_coords,
            document_coordinates=doc_coords,
            mapping_link_coordinates=mapping_link_coords,
            geocoded_coordinates=geocoded_coords,
            model_coordinates=model_coords,
            comparison_status=comp_status,
            coordinates_disagree=coords_disagree,
            discrepancy_details=discrepancy_details,
            discrepancy_distance_km=dist_km,
            precision_level=precision_level,
            coordinate_type=primary_coords.source if primary_coords else "none",
            selection_rationale=selection_rationale,
            has_exportable_site_coordinates=has_exportable_coords,
            can_export_to_shakemap=has_exportable_coords,  # preliminary spatial eligibility
            is_within_regional_bounds=is_within_region,
            raw_source_text=raw_source_snippet,
        )
