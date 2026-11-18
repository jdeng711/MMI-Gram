"""
Spatial Plausibility Gate for MMI-Gram.

Validates that extracted observation coordinates or location mentions are geographically
plausible within the event's regional domain.

SCIENTIFIC PRINCIPLES:
  - Uses documented input coordinates or textual landmark evidence when available.
  - Does NOT reject observations solely on epicentral distance (large quakes shake far).
  - Strictly does NOT substitute hypocentral or epicentral coordinates for missing locations.
  - Preserves unknown coordinates as null.

Attribution:
  Adapted and expanded from Clara Yoon's SpatialGate in QuakeLLMmap (quake_agent/gates/spatial_gate.py).
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Tuple
from mmigram.geolocation.validator import MYANMAR_BOUNDS

DEFAULT_EVENT_TOWNSHIPS = [
    "Mandalay",
    "Sagaing",
    "Amarapura",
    "Pyin Oo Lwin",
    "Naypyidaw",
    "Meiktila",
    "Kyaukse",
    "Shwebo",
    "Inwa",
    "Ava",
    "Mingun",
    "Yangon",
    "Bago",
    "Pyawbwe",
    "Taungoo",
    "Thazi",
    "Yamethin",
]


@dataclass
class SpatialCheckResult:
    """Result of spatial plausibility evaluation."""
    status: str = "WITHIN_BOUNDS"  # 'WITHIN_BOUNDS', 'OUTSIDE_BOUNDS', 'COORDINATES_UNKNOWN'
    is_plausible: bool = True
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    matched_townships: List[str] = field(default_factory=list)
    reason: str = "Coordinates verified within regional bounds."
    review_required: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SpatialGate:
    """
    Evaluates coordinate boundaries and regional township mentions.
    """

    def __init__(
        self,
        spatial_bounds: Optional[Dict[str, float]] = None,
        known_townships: Optional[List[str]] = None,
    ):
        self.bounds = spatial_bounds or MYANMAR_BOUNDS
        self.known_townships = known_townships or DEFAULT_EVENT_TOWNSHIPS

    def check(
        self,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        extracted_text: Optional[str] = None,
    ) -> SpatialCheckResult:
        """
        Evaluates spatial plausibility without inventing missing coordinates.
        """
        matched_townships = self.match_townships(extracted_text or "")

        # 1. Missing coordinates case: keep null, never invent!
        if latitude is None or longitude is None:
            township_note = f" (Townships mentioned: {', '.join(matched_townships)})" if matched_townships else ""
            return SpatialCheckResult(
                status="COORDINATES_UNKNOWN",
                is_plausible=True,
                latitude=None,
                longitude=None,
                matched_townships=matched_townships,
                reason=f"Observation coordinates unknown; not substituted with epicenter{township_note}.",
                review_required=True,
            )

        # 2. Check within regional bounds
        min_lat = self.bounds.get("min_lat", -90.0)
        max_lat = self.bounds.get("max_lat", 90.0)
        min_lon = self.bounds.get("min_lon", -180.0)
        max_lon = self.bounds.get("max_lon", 180.0)

        if not (min_lat <= latitude <= max_lat and min_lon <= longitude <= max_lon):
            return SpatialCheckResult(
                status="OUTSIDE_BOUNDS",
                is_plausible=False,
                latitude=latitude,
                longitude=longitude,
                matched_townships=matched_townships,
                reason=(
                    f"Coordinates [{latitude:.4f}, {longitude:.4f}] lie outside event regional bounds "
                    f"[{min_lat:.1f}-{max_lat:.1f} N, {min_lon:.1f}-{max_lon:.1f} E]."
                ),
                review_required=True,
            )

        return SpatialCheckResult(
            status="WITHIN_BOUNDS",
            is_plausible=True,
            latitude=latitude,
            longitude=longitude,
            matched_townships=matched_townships,
            reason=f"Coordinates [{latitude:.4f}, {longitude:.4f}] verified within regional bounds.",
            review_required=False,
        )

    def match_townships(self, text: str) -> List[str]:
        if not text:
            return []
        text_lower = text.lower()
        matched = []
        for t in self.known_townships:
            if re.search(rf"\b{re.escape(t.lower())}\b", text_lower):
                matched.append(t)
        return matched
