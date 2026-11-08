"""
MMI-Gram Core State Models.

Defines the shared structured state schema used by LangGraph nodes,
quality control, georeferencing, and human review queues.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Literal
try:
    from typing import TypedDict
except ImportError:
    from typing_extensions import TypedDict
import datetime


@dataclass
class Coordinates:
    """Geographic coordinate representation with provenance and validation status."""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    source: str = "unknown"  # 'dms_parsed', 'exif', 'report_text', 'manual_override', 'unknown'
    is_valid: bool = False
    validation_error: Optional[str] = None
    confidence: float = 0.0
    is_authoritative: bool = False  # False until independently verified by ground truth / GIS consensus

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Coordinates:
        if not data:
            return cls()
        return cls(
            latitude=data.get("latitude"),
            longitude=data.get("longitude"),
            source=data.get("source", "unknown"),
            is_valid=data.get("is_valid", False),
            validation_error=data.get("validation_error"),
            confidence=float(data.get("confidence", 0.0)),
            is_authoritative=bool(data.get("is_authoritative", False)),
        )


@dataclass
class LocationContext:
    """
    Location information extracted from media, text, or coordinates.
    Maintains document-extracted and model-predicted coordinates separately to prevent
    treating either as verified ground truth without authoritative validation.
    """
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    coordinates: Optional[Coordinates] = None             # Resolved candidate coordinates (or None if unknown)
    document_coordinates: Optional[Coordinates] = None    # Coordinates parsed from source document text
    model_coordinates: Optional[Coordinates] = None       # Coordinates output by multimodal model
    comparison_status: str = "LOCATION_UNKNOWN"          # 'COORDINATES_AGREE', 'COORDINATES_DISAGREE', 'MODEL_LOCATION_UNAVAILABLE', 'DOCUMENT_LOCATION_UNAVAILABLE', 'BOTH_LOCATIONS_UNAVAILABLE'
    coordinates_disagree: bool = False                   # True ONLY if document & model coordinates actively conflict (distance > threshold or invalid)
    discrepancy_details: Optional[str] = None
    discrepancy_distance_km: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "address": self.address,
            "city": self.city,
            "country": self.country,
            "coordinates": self.coordinates.to_dict() if self.coordinates else None,
            "document_coordinates": self.document_coordinates.to_dict() if self.document_coordinates else None,
            "model_coordinates": self.model_coordinates.to_dict() if self.model_coordinates else None,
            "comparison_status": self.comparison_status,
            "coordinates_disagree": self.coordinates_disagree,
            "discrepancy_details": self.discrepancy_details,
            "discrepancy_distance_km": self.discrepancy_distance_km,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> LocationContext:
        if not data:
            return cls()
        coords_raw = data.get("coordinates")
        coords = Coordinates.from_dict(coords_raw) if isinstance(coords_raw, dict) else None
        doc_raw = data.get("document_coordinates")
        doc_coords = Coordinates.from_dict(doc_raw) if isinstance(doc_raw, dict) else None
        model_raw = data.get("model_coordinates")
        model_coords = Coordinates.from_dict(model_raw) if isinstance(model_raw, dict) else None
        return cls(
            address=data.get("address"),
            city=data.get("city"),
            country=data.get("country"),
            coordinates=coords,
            document_coordinates=doc_coords,
            model_coordinates=model_coords,
            comparison_status=data.get("comparison_status", "LOCATION_UNKNOWN"),
            coordinates_disagree=bool(data.get("coordinates_disagree", False)),
            discrepancy_details=data.get("discrepancy_details"),
            discrepancy_distance_km=data.get("discrepancy_distance_km"),
        )


@dataclass
class StructuralDamageAssessment:
    """Physical damage observations and building typology."""
    building_type: Optional[str] = None
    building_materials: Optional[str] = None
    observed_damage_level: Optional[str] = None  # e.g., 'EMS-98 Grade 4', 'Partial Collapse'
    visual_observations: str = ""
    auditory_cues: Optional[str] = None
    video_evidence: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> StructuralDamageAssessment:
        if not data:
            return cls()
        return cls(
            building_type=data.get("building_type"),
            building_materials=data.get("building_materials"),
            observed_damage_level=data.get("observed_damage_level"),
            visual_observations=data.get("visual_observations", ""),
            auditory_cues=data.get("auditory_cues"),
            video_evidence=data.get("video_evidence"),
        )


@dataclass
class MMIEstimationResult:
    """Seismic intensity estimate, reasoning, and empirical indicators."""
    mmi_value: Optional[float] = None
    confidence: float = 0.0
    reasoning: str = ""
    governing_indicators: List[str] = field(default_factory=list)
    is_calibrated: bool = False  # False until validated by expert/authoritative consensus

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MMIEstimationResult:
        if not data:
            return cls()
        mmi = data.get("mmi_value")
        if mmi is not None:
            mmi = float(mmi)
        return cls(
            mmi_value=mmi,
            confidence=float(data.get("confidence", 0.0)),
            reasoning=data.get("reasoning", ""),
            governing_indicators=list(data.get("governing_indicators", [])),
            is_calibrated=bool(data.get("is_calibrated", False)),
        )


@dataclass
class EvidenceMetadata:
    """Metadata regarding raw media, sources, and provenance."""
    blob_name: str
    signed_url: str = ""
    mime_type: str = "application/octet-stream"
    sha256_hash: Optional[str] = None
    media_source: str = "unknown"  # 'recon_pdf', 'twitter_x', 'telegram', 'field_upload'
    external_url: Optional[str] = None
    timestamp_utc: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EvidenceMetadata:
        return cls(
            blob_name=data.get("blob_name", "unknown"),
            signed_url=data.get("signed_url", ""),
            mime_type=data.get("mime_type", "application/octet-stream"),
            sha256_hash=data.get("sha256_hash"),
            media_source=data.get("media_source", "unknown"),
            external_url=data.get("external_url"),
            timestamp_utc=data.get("timestamp_utc"),
        )


@dataclass
class QualityControlRecord:
    """Automated quality checks and validation flags."""
    is_valid_evidence: bool = True
    qc_status: Literal["PASSED", "FLAGGED", "REJECTED"] = "PASSED"
    qc_flags: List[str] = field(default_factory=list)
    qc_score: float = 1.0  # 1.0 = perfect, 0.0 = rejected

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> QualityControlRecord:
        if not data:
            return cls()
        return cls(
            is_valid_evidence=data.get("is_valid_evidence", True),
            qc_status=data.get("qc_status", "PASSED"),
            qc_flags=list(data.get("qc_flags", [])),
            qc_score=float(data.get("qc_score", 1.0)),
        )


@dataclass
class HumanReviewRecord:
    """Tracking structure for human expert oversight and overrides."""
    review_required: bool = False
    review_status: Literal["UNREVIEWED", "APPROVED", "REJECTED", "OVERRIDDEN"] = "UNREVIEWED"
    review_triggers: List[str] = field(default_factory=list)
    reviewer_id: Optional[str] = None
    reviewer_notes: Optional[str] = None
    reviewed_at_utc: Optional[str] = None
    overridden_mmi: Optional[float] = None
    overridden_coordinates: Optional[Coordinates] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.overridden_coordinates:
            d["overridden_coordinates"] = self.overridden_coordinates.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> HumanReviewRecord:
        if not data:
            return cls()
        coords_raw = data.get("overridden_coordinates")
        coords = Coordinates.from_dict(coords_raw) if isinstance(coords_raw, dict) else None
        return cls(
            review_required=data.get("review_required", False),
            review_status=data.get("review_status", "UNREVIEWED"),
            review_triggers=list(data.get("review_triggers", [])),
            reviewer_id=data.get("reviewer_id"),
            reviewer_notes=data.get("reviewer_notes"),
            reviewed_at_utc=data.get("reviewed_at_utc"),
            overridden_mmi=data.get("overridden_mmi"),
            overridden_coordinates=coords,
        )


class MMIGramState(TypedDict, total=False):
    """
    Shared structured state for LangGraph runtime orchestration.
    Maintains compatibility with legacy CRAG keys while introducing
    structured sub-domains.
    """
    # Legacy keys for backward compatibility with existing CRAG nodes
    blob_name: str
    signed_url: str
    mime_type: str
    initial_analysis: str
    context_summary: str
    mmi_documents: List[Any]
    web_search: str
    final_analysis: Dict[str, Any]
    generation: str

    # Modular Phase 2 structured models
    evidence: Dict[str, Any]             # EvidenceMetadata dict
    location: Dict[str, Any]             # LocationContext dict
    damage: Dict[str, Any]               # StructuralDamageAssessment dict
    estimation: Dict[str, Any]           # MMIEstimationResult dict
    qc: Dict[str, Any]                   # QualityControlRecord dict
    review: Dict[str, Any]               # HumanReviewRecord dict
    map_url: Optional[str]
    persisted: bool
