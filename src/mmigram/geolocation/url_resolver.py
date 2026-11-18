"""
Mapping URL parsing, coordinate extraction, and secure redirection handling.

Supports:
- Direct coordinate extraction from Google Maps, OpenStreetMap, Apple Maps, Bing Maps, and geo: URIs without network calls.
- Secure shortened link expansion (maps.app.goo.gl, goo.gl/maps) with domain whitelisting and SSRF protection.
- Offline-safe mode preventing unauthorized external requests.
"""

from __future__ import annotations
import ipaddress
import re
import socket
import urllib.parse
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any, List, Callable

from ..core.state import Coordinates

# Allowed domains for shortened Google Maps links and safe redirect destinations
ALLOWED_MAP_HOSTS = {
    "maps.app.goo.gl",
    "goo.gl",
    "maps.google.com",
    "www.google.com",
    "google.com",
    "openstreetmap.org",
    "www.openstreetmap.org",
    "maps.apple.com",
    "bing.com",
    "www.bing.com",
}


@dataclass
class MapURLExtraction:
    """Structured result of parsing a mapping URL."""
    url: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    provider: str = "unknown"  # 'google_maps', 'openstreetmap', 'apple_maps', 'bing_maps', 'geo_uri'
    coordinate_type: str = "unknown"  # 'url_poi_marker', 'url_query_pin', 'url_viewport_center', 'url_search_area'
    place_name: Optional[str] = None
    is_valid: bool = False
    validation_error: Optional[str] = None
    precision_level: str = "unknown"  # 'url_poi_marker', 'url_query_pin', 'url_viewport_approximate', 'unknown'
    is_site_specific: bool = True  # False for viewport centers or search areas

    def to_coordinates(self) -> Optional[Coordinates]:
        if not self.is_valid or self.latitude is None or self.longitude is None:
            return None
        # Viewport centers receive lower confidence and are flagged as approximate
        conf = 0.95 if self.coordinate_type == "url_poi_marker" else (0.90 if self.coordinate_type == "url_query_pin" else 0.60)
        return Coordinates(
            latitude=self.latitude,
            longitude=self.longitude,
            source="url_embedded",
            is_valid=True,
            confidence=conf,
            is_authoritative=False,
            precision_level=self.precision_level,
        )


class MapURLResolver:
    """
    Parser and resolver for mapping links in reconnaissance reports.
    """

    # In-memory mock registry for offline testing of shortened URL expansion
    _mock_redirects: Dict[str, str] = {}

    @classmethod
    def register_mock_redirect(cls, short_url: str, expanded_url: str) -> None:
        """Register a mock redirect for deterministic offline testing."""
        cls._mock_redirects[short_url.strip()] = expanded_url.strip()

    @classmethod
    def clear_mock_redirects(cls) -> None:
        """Clear test mock redirects."""
        cls._mock_redirects.clear()

    @classmethod
    def extract_mapping_urls(cls, text: str) -> List[str]:
        """
        Find all mapping URLs or geo: URIs in input text.
        """
        if not text:
            return []

        urls: List[str] = []
        # 1. Google Maps (short and long)
        gm_pattern = re.compile(
            r'https?://(?:maps\.app\.goo\.gl|goo\.gl/maps|maps\.google\.[a-z.]+|[a-z0-9.-]*google\.[a-z.]+/maps)[^\s<>\"\')]*',
            re.IGNORECASE
        )
        for m in gm_pattern.finditer(text):
            urls.append(m.group(0).rstrip(".,;:)"))

        # 2. OpenStreetMap
        osm_pattern = re.compile(
            r'https?://(?:www\.)?openstreetmap\.org[^\s<>\"\')]*',
            re.IGNORECASE
        )
        for m in osm_pattern.finditer(text):
            urls.append(m.group(0).rstrip(".,;:)"))

        # 3. Apple Maps
        apple_pattern = re.compile(
            r'https?://maps\.apple\.com[^\s<>\"\')]*',
            re.IGNORECASE
        )
        for m in apple_pattern.finditer(text):
            urls.append(m.group(0).rstrip(".,;:)"))

        # 4. Bing Maps
        bing_pattern = re.compile(
            r'https?://(?:www\.)?bing\.com/maps[^\s<>\"\')]*',
            re.IGNORECASE
        )
        for m in bing_pattern.finditer(text):
            urls.append(m.group(0).rstrip(".,;:)"))

        # 5. geo: URIs
        geo_pattern = re.compile(
            r'geo:[-+]?\d+\.\d+,[-+]?\d+\.\d+[^\s<>\"\')]*',
            re.IGNORECASE
        )
        for m in geo_pattern.finditer(text):
            urls.append(m.group(0).rstrip(".,;:)"))

        return urls

    @classmethod
    def extract_place_name(cls, url: str) -> Optional[str]:
        """
        Extract place name from Google Maps URL slug /place/<name>/.
        """
        m_place = re.search(r'/place/([^/@?&]+)', url)
        if m_place:
            slug = m_place.group(1)
            # URL unquote and clean plus signs
            name = urllib.parse.unquote(slug.replace("+", " ")).strip()
            if name:
                return name
        return None

    @classmethod
    def parse_embedded_coordinates(cls, url: str) -> Optional[MapURLExtraction]:
        """
        Parse latitude and longitude directly from URL structure without making network calls.
        Covers Google Maps POI data (!3dlat!4dlon), query params (?q=, ?ll=, ?loc:),
        center coordinates (/@lat,lon), OpenStreetMap, Apple Maps, Bing Maps, and geo: URIs.
        """
        if not url:
            return None

        clean_url = url.strip()
        place_name = cls.extract_place_name(clean_url)

        # ── 1. Google Maps POI Coordinates: !3d<lat>!4d<lon> ──
        # Highly precise point-of-interest coordinates attached to an explicit place or marker
        m_poi = re.search(r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)', clean_url)
        if m_poi:
            try:
                lat = float(m_poi.group(1))
                lon = float(m_poi.group(2))
                if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                    return MapURLExtraction(
                        url=clean_url,
                        latitude=round(lat, 6),
                        longitude=round(lon, 6),
                        provider="google_maps",
                        coordinate_type="url_poi_marker",
                        place_name=place_name,
                        is_valid=True,
                        precision_level="url_poi_marker",
                        is_site_specific=True,
                    )
            except ValueError:
                pass

        # ── 2. Google Maps Query / Pin Coordinates: ?q=lat,lon or ?ll=lat,lon or ?loc:lat,lon ──
        m_q = re.search(
            r'[?&](?:q|query|ll|loc:?)=(-?\d+\.\d+),(-?\d+\.\d+)',
            clean_url,
            re.IGNORECASE
        )
        if m_q:
            try:
                lat = float(m_q.group(1))
                lon = float(m_q.group(2))
                if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                    return MapURLExtraction(
                        url=clean_url,
                        latitude=round(lat, 6),
                        longitude=round(lon, 6),
                        provider="google_maps",
                        coordinate_type="url_query_pin",
                        place_name=place_name,
                        is_valid=True,
                        precision_level="url_query_pin",
                        is_site_specific=True,
                    )
            except ValueError:
                pass

        # ── 3. Google Maps Viewport Center: /@lat,lon,zoom ──
        # In Google Maps, /@lat,lon represents the displayed map camera/viewport center, NOT a verified site pin!
        m_at = re.search(r'/@(-?\d+\.\d+),(-?\d+\.\d+)', clean_url)
        if m_at:
            try:
                lat = float(m_at.group(1))
                lon = float(m_at.group(2))
                if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                    return MapURLExtraction(
                        url=clean_url,
                        latitude=round(lat, 6),
                        longitude=round(lon, 6),
                        provider="google_maps",
                        coordinate_type="url_viewport_center",
                        place_name=place_name,
                        is_valid=True,
                        precision_level="url_viewport_approximate",
                        is_site_specific=False,
                    )
            except ValueError:
                pass

        # ── 4. OpenStreetMap: ?mlat=lat&mlon=lon ──
        m_osm_q = re.search(
            r'[?&]mlat=(-?\d+\.\d+)&mlon=(-?\d+\.\d+)',
            clean_url,
            re.IGNORECASE
        )
        if m_osm_q:
            try:
                lat = float(m_osm_q.group(1))
                lon = float(m_osm_q.group(2))
                if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                    return MapURLExtraction(
                        url=clean_url,
                        latitude=round(lat, 6),
                        longitude=round(lon, 6),
                        provider="openstreetmap",
                        coordinate_type="url_query_pin",
                        is_valid=True,
                        precision_level="url_query_pin",
                        is_site_specific=True,
                    )
            except ValueError:
                pass

        # ── 5. OpenStreetMap: #map=zoom/lat/lon (Viewport center) ──
        m_osm_map = re.search(
            r'#map=\d+/(-?\d+\.\d+)/(-?\d+\.\d+)',
            clean_url,
            re.IGNORECASE
        )
        if m_osm_map:
            try:
                lat = float(m_osm_map.group(1))
                lon = float(m_osm_map.group(2))
                if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                    return MapURLExtraction(
                        url=clean_url,
                        latitude=round(lat, 6),
                        longitude=round(lon, 6),
                        provider="openstreetmap",
                        coordinate_type="url_viewport_center",
                        is_valid=True,
                        precision_level="url_viewport_approximate",
                        is_site_specific=False,
                    )
            except ValueError:
                pass

        # ── 6. Apple Maps: ll=lat,lon or sll=lat,lon ──
        m_apple = re.search(
            r'[?&](?:ll|sll)=(-?\d+\.\d+),(-?\d+\.\d+)',
            clean_url,
            re.IGNORECASE
        )
        if m_apple:
            try:
                lat = float(m_apple.group(1))
                lon = float(m_apple.group(2))
                if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                    return MapURLExtraction(
                        url=clean_url,
                        latitude=round(lat, 6),
                        longitude=round(lon, 6),
                        provider="apple_maps",
                        coordinate_type="url_query_pin",
                        is_valid=True,
                        precision_level="url_query_pin",
                        is_site_specific=True,
                    )
            except ValueError:
                pass

        # ── 7. Bing Maps: cp=lat~lon (Center point) ──
        m_bing = re.search(
            r'[?&]cp=(-?\d+\.\d+)~(-?\d+\.\d+)',
            clean_url,
            re.IGNORECASE
        )
        if m_bing:
            try:
                lat = float(m_bing.group(1))
                lon = float(m_bing.group(2))
                if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                    return MapURLExtraction(
                        url=clean_url,
                        latitude=round(lat, 6),
                        longitude=round(lon, 6),
                        provider="bing_maps",
                        coordinate_type="url_viewport_center",
                        is_valid=True,
                        precision_level="url_viewport_approximate",
                        is_site_specific=False,
                    )
            except ValueError:
                pass

        # ── 8. geo: URI ──
        m_geo = re.search(r'geo:(-?\d+\.\d+),(-?\d+\.\d+)', clean_url, re.IGNORECASE)
        if m_geo:
            try:
                lat = float(m_geo.group(1))
                lon = float(m_geo.group(2))
                if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                    return MapURLExtraction(
                        url=clean_url,
                        latitude=round(lat, 6),
                        longitude=round(lon, 6),
                        provider="geo_uri",
                        coordinate_type="url_query_pin",
                        is_valid=True,
                        precision_level="url_query_pin",
                        is_site_specific=True,
                    )
            except ValueError:
                pass

        # URL recognized as a mapping URL, but coordinates were not embedded in query parameters
        return MapURLExtraction(
            url=clean_url,
            provider="google_maps" if "google" in clean_url or "goo.gl" in clean_url else "unknown",
            coordinate_type="url_search_area",
            place_name=place_name,
            is_valid=False,
            is_site_specific=False,
            precision_level="unknown",
            validation_error="No direct coordinates embedded in mapping URL query parameters",
        )

    @classmethod
    def is_private_or_reserved_ip(cls, ip_str: str) -> bool:
        """
        Check if an IP address is private, loopback, link-local, multicast, or reserved.
        Protects against Server-Side Request Forgery (SSRF).
        """
        try:
            ip = ipaddress.ip_address(ip_str)
            return (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
                or ip.is_unspecified
            )
        except ValueError:
            return True

    @classmethod
    def is_safe_redirect_host(cls, hostname: str) -> bool:
        """
        Validate hostname against SSRF and whitelist policies.
        Rejects localhost, local domains, non-whitelisted domains, and resolves DNS to verify IP.
        """
        if not hostname:
            return False

        h_lower = hostname.lower().strip()
        # Explicit block on localhost/internal names
        if h_lower in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or h_lower.endswith(".local") or h_lower.endswith(".internal"):
            return False

        # Domain whitelist check: Must be a known Google or mapping domain
        is_whitelisted = False
        if h_lower in ALLOWED_MAP_HOSTS:
            is_whitelisted = True
        elif h_lower.endswith(".google.com") or h_lower.endswith(".goo.gl"):
            is_whitelisted = True

        if not is_whitelisted:
            return False

        # DNS resolution check for private IPs
        try:
            addr_info = socket.getaddrinfo(h_lower, None)
            for item in addr_info:
                ip_addr = item[4][0]
                if cls.is_private_or_reserved_ip(ip_addr):
                    return False
        except (socket.gaierror, socket.herror, OSError):
            return False

        return True

    @classmethod
    def resolve_shortened_url(
        cls,
        url: str,
        allow_network: bool = False,
        timeout: float = 3.0,
        custom_resolver: Optional[Callable[[str], Optional[str]]] = None,
    ) -> Optional[str]:
        """
        Safely resolve shortened Google Maps links (e.g. maps.app.goo.gl or goo.gl/maps).
        
        Guards:
        1. Checks in-memory test mocks first.
        2. If custom_resolver provided, delegates to it.
        3. If allow_network is False, returns None (strictly offline safe).
        4. Validates initial URL domain against ALLOWED_MAP_HOSTS.
        5. Performs HTTP HEAD/GET request with SSRF guard on redirect targets.
        """
        if not url:
            return None

        clean_url = url.strip()

        # 1. Test mock registry check
        if clean_url in cls._mock_redirects:
            return cls._mock_redirects[clean_url]

        # 2. Custom resolver hook
        if custom_resolver is not None:
            return custom_resolver(clean_url)

        # 3. Offline safety guard
        if not allow_network:
            return None

        # 4. Host validation on initial URL
        parsed = urllib.parse.urlparse(clean_url)
        if not parsed.hostname or not cls.is_safe_redirect_host(parsed.hostname):
            return None

        # 5. Safe live HTTP resolution with manual redirect loop & SSRF checking
        import urllib.request
        import urllib.error

        current_url = clean_url
        max_redirects = 5

        for _ in range(max_redirects):
            curr_parsed = urllib.parse.urlparse(current_url)
            if not curr_parsed.hostname or not cls.is_safe_redirect_host(curr_parsed.hostname):
                return None

            class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
                def http_error_301(self, req, fp, code, msg, headers):
                    return None
                def http_error_302(self, req, fp, code, msg, headers):
                    return None
                def http_error_303(self, req, fp, code, msg, headers):
                    return None
                def http_error_307(self, req, fp, code, msg, headers):
                    return None
                def http_error_308(self, req, fp, code, msg, headers):
                    return None

            opener = urllib.request.build_opener(NoRedirectHandler)
            req = urllib.request.Request(
                current_url,
                headers={"User-Agent": "MMIGram-SeismicRecon/1.0"},
                method="HEAD"
            )

            try:
                with opener.open(req, timeout=timeout) as resp:
                    # Final destination reached
                    return current_url
            except urllib.error.HTTPError as e:
                if e.code in (301, 302, 303, 307, 308) and "Location" in e.headers:
                    redirect_target = e.headers["Location"]
                    next_url = urllib.parse.urljoin(current_url, redirect_target)
                    next_parsed = urllib.parse.urlparse(next_url)
                    if not next_parsed.hostname or not cls.is_safe_redirect_host(next_parsed.hostname):
                        return None
                    current_url = next_url
                else:
                    return None
            except Exception:
                return None

        return current_url
