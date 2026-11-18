"""
Google Maps Geocoding API adapter with offline safeguards, caching, and precision mapping.

Enforces:
- Strict offline mode: live API requests are disabled by default (allow_live_geocoding=False).
- Secure credential management: reads GOOGLE_MAPS_API_KEY from environment or .env without logging secrets.
- In-memory and disk caching to eliminate duplicate API requests and prevent accidental charges.
- Precise location type mapping (ROOFTOP, RANGE_INTERPOLATED, GEOMETRIC_CENTER, APPROXIMATE).
- Complete call and cache telemetry accounting.
"""

from __future__ import annotations
import json
import os
import re
import urllib.parse
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable, Tuple

from ..core.state import Coordinates

DEFAULT_CACHE_PATH = Path("data/geocoding_cache.json")


@dataclass
class GeocodedResult:
    """Structured result from Google Maps Geocoding."""
    query: str
    latitude: float
    longitude: float
    formatted_address: str
    location_type: str  # 'ROOFTOP', 'RANGE_INTERPOLATED', 'GEOMETRIC_CENTER', 'APPROXIMATE'
    precision_level: str  # 'geocoded_rooftop', 'geocoded_interpolated', 'city_centroid_approximate'
    partial_match: bool = False
    place_id: Optional[str] = None
    confidence: float = 0.90
    from_cache: bool = False

    def to_coordinates(self) -> Coordinates:
        # Lower confidence for approximate city centroids
        conf = self.confidence
        if self.precision_level == "city_centroid_approximate":
            conf = min(conf, 0.60)
        return Coordinates(
            latitude=round(self.latitude, 6),
            longitude=round(self.longitude, 6),
            source="geocoded",
            is_valid=True,
            confidence=conf,
            is_authoritative=False,
            precision_level=self.precision_level,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GoogleMapsGeocodingAdapter:
    """
    Adapter for Google Maps Geocoding API with multi-tiered caching and offline guards.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        allow_live_geocoding: bool = False,
        cache_path: Optional[Path] = None,
        custom_fetcher: Optional[Callable[[Dict[str, str]], Optional[Dict[str, Any]]]] = None,
    ):
        self._api_key = api_key
        self.allow_live_geocoding = allow_live_geocoding
        self.cache_path = cache_path or DEFAULT_CACHE_PATH
        self.custom_fetcher = custom_fetcher

        # In-memory query cache: normalized query string -> raw JSON payload
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        # Deterministic mock responses for testing
        self._mock_responses: Dict[str, Dict[str, Any]] = {}

        # Telemetry metrics
        self.api_call_count: int = 0
        self.cache_hit_count: int = 0
        self.offline_blocked_count: int = 0

        self._load_disk_cache()

    def get_api_key(self) -> Optional[str]:
        """Safely retrieve API key without leaking into logs."""
        if self._api_key:
            return self._api_key

        env_key = os.getenv("GOOGLE_MAPS_API_KEY")
        if env_key:
            return env_key.strip().strip('"').strip("'")

        # Check candidate .env paths
        candidate_paths = [Path(".env"), Path("server/.env"), Path("../.env")]
        for p in candidate_paths:
            if p.exists():
                try:
                    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                        line = line.strip()
                        if line.startswith("GOOGLE_MAPS_API_KEY=") and not line.startswith("#"):
                            _, val = line.split("=", 1)
                            clean_val = val.strip().strip('"').strip("'")
                            if clean_val:
                                return clean_val
                except Exception:
                    pass
        return None

    def _normalize_query(self, query: str) -> str:
        """Normalize address query string for consistent cache keying."""
        q = query.lower().strip()
        q = re.sub(r'[\s,;:.]+', ' ', q)
        return q.strip()

    def _load_disk_cache(self) -> None:
        """Load persistent cache from disk if available."""
        if self.cache_path and self.cache_path.exists():
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self._memory_cache.update(data)
            except Exception:
                pass

    def _save_disk_cache(self) -> None:
        """Save in-memory cache to disk."""
        if self.cache_path:
            try:
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.cache_path, "w", encoding="utf-8") as f:
                    json.dump(self._memory_cache, f, indent=2)
            except Exception:
                pass

    def register_mock_response(self, query: str, response_payload: Dict[str, Any]) -> None:
        """Register a mock geocoding API response for testing."""
        norm_q = self._normalize_query(query)
        self._mock_responses[norm_q] = response_payload

    def clear_mock_responses(self) -> None:
        """Clear test mock responses."""
        self._mock_responses.clear()

    def map_location_type(self, raw_type: str) -> str:
        """
        Map Google Maps location_type to seismic precision levels.
        ROOFTOP: exact building rooftop -> geocoded_rooftop
        RANGE_INTERPOLATED: street address interpolated between two points -> geocoded_interpolated
        GEOMETRIC_CENTER: center of a street, neighborhood, or boundary -> city_centroid_approximate
        APPROXIMATE: broad city, township, or country center -> city_centroid_approximate
        """
        raw_upper = (raw_type or "").upper()
        if raw_upper == "ROOFTOP":
            return "geocoded_rooftop"
        elif raw_upper == "RANGE_INTERPOLATED":
            return "geocoded_interpolated"
        elif raw_upper in ("GEOMETRIC_CENTER", "APPROXIMATE"):
            return "city_centroid_approximate"
        return "city_centroid_approximate"

    def _parse_api_result(self, query: str, result_dict: Dict[str, Any], from_cache: bool = False) -> Optional[GeocodedResult]:
        """Parse raw Google Maps geocoding result into structured GeocodedResult."""
        try:
            geometry = result_dict.get("geometry", {})
            loc = geometry.get("location", {})
            lat = float(loc.get("lat"))
            lon = float(loc.get("lng"))
            loc_type = geometry.get("location_type", "APPROXIMATE")
            precision = self.map_location_type(loc_type)
            formatted_addr = result_dict.get("formatted_address", query)
            partial = bool(result_dict.get("partial_match", False))
            place_id = result_dict.get("place_id")

            # Determine baseline confidence
            conf = 0.95 if loc_type == "ROOFTOP" else (0.85 if loc_type == "RANGE_INTERPOLATED" else 0.60)
            if partial:
                conf = min(conf, 0.70)

            return GeocodedResult(
                query=query,
                latitude=lat,
                longitude=lon,
                formatted_address=formatted_addr,
                location_type=loc_type,
                precision_level=precision,
                partial_match=partial,
                place_id=place_id,
                confidence=conf,
                from_cache=from_cache,
            )
        except (ValueError, TypeError, KeyError):
            return None

    def geocode(self, query: str, timeout: float = 5.0) -> Optional[GeocodedResult]:
        """
        Resolve address query to coordinates using Google Maps Geocoding API.
        
        Execution Flow:
        1. Query normalization and cache lookup (memory/disk).
        2. Check for registered test mock responses.
        3. If custom fetcher provided, use it.
        4. Guard: if allow_live_geocoding is False, block live network call, record telemetry, and return None.
        5. Check API key; if missing, return None.
        6. Live HTTP call with timeout, parse response, store in cache.
        """
        if not query or not query.strip():
            return None

        clean_q = query.strip()
        norm_q = self._normalize_query(clean_q)

        # 1. Cache hit check
        if norm_q in self._memory_cache:
            self.cache_hit_count += 1
            cached_item = self._memory_cache[norm_q]
            return self._parse_api_result(clean_q, cached_item, from_cache=True)

        # 2. Mock response check
        if norm_q in self._mock_responses:
            mock_item = self._mock_responses[norm_q]
            self._memory_cache[norm_q] = mock_item
            return self._parse_api_result(clean_q, mock_item, from_cache=False)

        # 3. Custom fetcher check (e.g. test fixture or mock HTTP handler)
        if self.custom_fetcher is not None:
            self.api_call_count += 1
            fetched = self.custom_fetcher({"address": clean_q})
            if fetched:
                self._memory_cache[norm_q] = fetched
                self._save_disk_cache()
                return self._parse_api_result(clean_q, fetched, from_cache=False)
            return None

        # 4. Strict Offline Mode Guard
        if not self.allow_live_geocoding:
            self.offline_blocked_count += 1
            return None

        # 5. API key verification
        api_key = self.get_api_key()
        if not api_key:
            return None

        # 6. Live Google Maps Geocoding HTTP request
        import urllib.request
        import urllib.error

        params = urllib.parse.urlencode({"address": clean_q, "key": api_key})
        endpoint = f"https://maps.googleapis.com/maps/api/geocode/json?{params}"

        req = urllib.request.Request(
            endpoint,
            headers={"User-Agent": "MMIGram-SeismicRecon/1.0"}
        )

        try:
            self.api_call_count += 1
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                status = data.get("status")
                if status == "OK" and data.get("results"):
                    top_result = data["results"][0]
                    # Cache successful result
                    self._memory_cache[norm_q] = top_result
                    self._save_disk_cache()
                    return self._parse_api_result(clean_q, top_result, from_cache=False)
                elif status == "ZERO_RESULTS":
                    return None
                else:
                    return None
        except Exception:
            return None

    def get_telemetry(self) -> Dict[str, Any]:
        """Return usage and caching statistics."""
        return {
            "api_call_count": self.api_call_count,
            "cache_hit_count": self.cache_hit_count,
            "offline_blocked_count": self.offline_blocked_count,
            "cached_entries_count": len(self._memory_cache),
            "allow_live_geocoding": self.allow_live_geocoding,
        }
