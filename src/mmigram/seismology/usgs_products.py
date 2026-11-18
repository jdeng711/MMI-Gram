"""
USGS Product Provider & ComCat Cache Manager.

Retrieves, caches, and verifies official USGS earthquake products (origin metadata,
finite-fault rupture models, ShakeMap station lists, attenuation curves, and intensity grids)
via the USGS Comprehensive Earthquake Catalog (ComCat) API.

Scientific & Operational Principles:
1. Event-Independent: Works with arbitrary USGS event IDs (e.g. us7000pn9s, us6000jllz).
2. Offline Safety: Defaults to allow_live_download=False; zero network calls during tests.
3. Provenance Tracking: Records product version, retrieval timestamp, source URL, and SHA256 hash in a local manifest.json.
4. Graceful Degradation: If a product (e.g. finite-fault rupture.json) is not produced by USGS for a given event, returns None without crashing.
5. Cache Immutability: Authoritative cached datasets are not overwritten without explicit version tracking.
"""

from __future__ import annotations
import os
import json
import time
import hashlib
import datetime
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, Optional, List, Union


def compute_sha256(filepath: Union[str, Path]) -> str:
    """Compute SHA-256 hex digest of a local file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class USGSProductProvider:
    """
    Manages local caching and ComCat retrieval of official USGS ShakeMap datasets.
    """

    COMCAT_BASE_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"

    def __init__(
        self,
        cache_dir: Optional[Union[str, Path]] = None,
        allow_live_download: bool = False,
        timeout_sec: float = 15.0,
    ):
        self.cache_dir = Path(cache_dir or Path("data/events"))
        self.allow_live_download = allow_live_download
        self.timeout_sec = timeout_sec
        # In-memory mock event registry for unit testing and offline development
        self._mock_events: Dict[str, Dict[str, Any]] = {}
        self._mock_products: Dict[str, Dict[str, Any]] = {}

    def register_mock_event(
        self,
        event_id: str,
        summary: Optional[Dict[str, Any]] = None,
        products: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Register mock event summary and product payloads for offline testing."""
        if summary is not None:
            self._mock_events[event_id] = summary
        if products is not None:
            if event_id not in self._mock_products:
                self._mock_products[event_id] = {}
            self._mock_products[event_id].update(products)

    def register_mock_product(
        self,
        event_id: str,
        product_name: str,
        data: Dict[str, Any],
    ) -> None:
        """Register a mock product payload for offline unit testing."""
        if product_name in ("event_summary", "event_metadata"):
            self.register_mock_event(event_id, summary=data)
        else:
            self.register_mock_event(event_id, products={product_name: data})

    def save_product(self, event_id: str, product_name: str, data: Dict[str, Any]) -> Path:
        """Save a product dictionary locally and update manifest.json."""
        event_dir = self.get_event_dir(event_id)
        event_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{product_name}.json" if not product_name.endswith(".json") else product_name
        local_path = event_dir / filename
        with open(local_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        manifest = self.load_manifest(event_id)
        manifest["products"][filename] = {
            "source": "local_save",
            "saved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "sha256": compute_sha256(local_path),
            "bytes": local_path.stat().st_size,
        }
        self.save_manifest(event_id, manifest)
        return local_path

    def get_event_dir(self, event_id: str) -> Path:
        """Return the local storage directory for a given event's USGS products."""
        return self.cache_dir / event_id / "usgs"

    def get_manifest_path(self, event_id: str) -> Path:
        """Return the local manifest.json path for a given event."""
        return self.get_event_dir(event_id) / "manifest.json"

    def load_manifest(self, event_id: str) -> Dict[str, Any]:
        """Load the product manifest for an event, or return an empty template."""
        p = self.get_manifest_path(event_id)
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "event_id": event_id,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "products": {},
        }

    def save_manifest(self, event_id: str, manifest: Dict[str, Any]) -> None:
        """Write the product manifest to disk."""
        p = self.get_manifest_path(event_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        manifest["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with open(p, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    # ──────────────────────────────────────────────────────────────────────────
    # Core ComCat Event Summary & Product Discovery
    # ──────────────────────────────────────────────────────────────────────────

    def fetch_event_summary(self, event_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch or load cached GeoJSON event summary from USGS ComCat.
        Returns parsed GeoJSON dict, or None if unavailable.
        """
        # 1. Check in-memory mocks
        if event_id in self._mock_events:
            return self._mock_events[event_id]

        # 2. Check cached summary file
        summary_path = self.get_event_dir(event_id) / "event_summary.json"
        if summary_path.exists():
            try:
                with open(summary_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

        # 3. If offline, refuse network download
        if not self.allow_live_download:
            return None

        # 4. Live ComCat fetch
        url = f"{self.COMCAT_BASE_URL}?eventid={event_id}&format=geojson"
        req = urllib.request.Request(url, headers={"User-Agent": "MMI-Gram/0.2.0 (Harvard EPS 55 Research)"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            summary_path.parent.mkdir(parents=True, exist_ok=True)
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            manifest = self.load_manifest(event_id)
            manifest["products"]["event_summary.json"] = {
                "source_url": url,
                "retrieved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "sha256": compute_sha256(summary_path),
                "bytes": summary_path.stat().st_size,
            }
            self.save_manifest(event_id, manifest)
            return data
        except Exception as e:
            return None

    def get_event_metadata(self, event_id: str) -> Optional[Dict[str, Any]]:
        """
        Extract core earthquake origin metadata (magnitude, epicenter lat/lon, depth, origin time).
        """
        summary = self.fetch_event_summary(event_id)
        if not summary:
            return None

        props = summary.get("properties", {})
        geom = summary.get("geometry", {})
        coords = geom.get("coordinates", [])

        lon = coords[0] if len(coords) > 0 else props.get("longitude")
        lat = coords[1] if len(coords) > 1 else props.get("latitude")
        depth = coords[2] if len(coords) > 2 else props.get("depth")

        return {
            "event_id": event_id,
            "title": props.get("title"),
            "description": props.get("place") or props.get("title", ""),
            "magnitude": props.get("mag"),
            "magnitude_type": props.get("magType"),
            "latitude": float(lat) if lat is not None else None,
            "longitude": float(lon) if lon is not None else None,
            "depth_km": float(depth) if depth is not None else None,
            "origin_time_utc": (
                datetime.datetime.fromtimestamp(props.get("time") / 1000.0, tz=datetime.timezone.utc).isoformat()
                if props.get("time")
                else None
            ),
            "status": props.get("status"),
            "event_type": props.get("type", "earthquake"),
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Individual Product Retrieval
    # ──────────────────────────────────────────────────────────────────────────

    def get_product_path(self, event_id: str, product_name: str) -> Optional[Path]:
        """
        Return the local Path to a ShakeMap product (e.g. 'rupture.json', 'stationlist.json'),
        loading from cache or downloading from ComCat if allowed.
        """
        event_dir = self.get_event_dir(event_id)
        local_path = event_dir / product_name

        # If already cached locally, return it
        if local_path.exists():
            return local_path

        # Check mock products dictionary
        if event_id in self._mock_products and product_name in self._mock_products[event_id]:
            mock_data = self._mock_products[event_id][product_name]
            event_dir.mkdir(parents=True, exist_ok=True)
            if isinstance(mock_data, (dict, list)):
                with open(local_path, "w", encoding="utf-8") as f:
                    json.dump(mock_data, f, indent=2)
            elif isinstance(mock_data, str):
                with open(local_path, "w", encoding="utf-8") as f:
                    f.write(mock_data)
            elif isinstance(mock_data, bytes):
                with open(local_path, "wb") as f:
                    f.write(mock_data)
            return local_path

        # If live download is not permitted, return None gracefully
        if not self.allow_live_download:
            return None

        # Discover product download URL from ShakeMap product contents
        summary = self.fetch_event_summary(event_id)
        if not summary:
            return None

        products = summary.get("properties", {}).get("products", {})
        shakemaps = products.get("shakemap", [])
        if not shakemaps:
            return None

        sm = shakemaps[0]
        contents = sm.get("contents", {})

        target_key = None
        for cand in [product_name, f"download/{product_name}", f"products/{product_name}"]:
            if cand in contents:
                target_key = cand
                break

        if not target_key:
            return None

        file_url = contents[target_key].get("url")
        if not file_url:
            return None

        # Download product file safely
        try:
            event_dir.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(file_url, headers={"User-Agent": "MMI-Gram/0.2.0 (Harvard EPS 55 Research)"})
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                content_bytes = resp.read()

            with open(local_path, "wb") as f:
                f.write(content_bytes)

            manifest = self.load_manifest(event_id)
            manifest["products"][product_name] = {
                "source_url": file_url,
                "retrieved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "sha256": hashlib.sha256(content_bytes).hexdigest(),
                "bytes": len(content_bytes),
                "shakemap_version": sm.get("properties", {}).get("version"),
            }
            self.save_manifest(event_id, manifest)
            return local_path

        except Exception:
            return None

    def get_rupture(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Load and parse finite-fault rupture.json GeoJSON, or None if unavailable."""
        path = self.get_product_path(event_id, "rupture.json")
        if path and path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    def get_stationlist(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Load and parse ShakeMap stationlist.json GeoJSON, or None if unavailable."""
        path = self.get_product_path(event_id, "stationlist.json")
        if path and path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    def get_attenuation_curves(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Load and parse ShakeMap attenuation_curves.json, or None if unavailable."""
        path = self.get_product_path(event_id, "attenuation_curves.json")
        if path and path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    def get_info(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Load and parse ShakeMap info.json, or None if unavailable."""
        path = self.get_product_path(event_id, "info.json")
        if path and path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    def get_grid_xml_path(self, event_id: str) -> Optional[Path]:
        """Return path to grid.xml file, or None if unavailable."""
        return self.get_product_path(event_id, "grid.xml")
