"""
Composite Pre-MMI Screening Pipeline for MMI-Gram.

Orchestrates all 5 screening gates prior to MMI analysis:
  1. Recycled Media & Duplicate Gate (SHA-256 and dHash)
  2. Pre-MMI Evidence Relevance Gate (Usable damage vs model maps/title slides)
  3. Temporal Consistency Gate (Check against T0)
  4. Spatial Plausibility Gate (Regional bounds & township check, no hypocenter substitution)
  5. Authenticity Gate (Synthetic AI-media forensics)

Executes BEFORE expensive model inference. Irrelevant documents (NOT_ESTIMABLE)
are stopped immediately, preventing unnecessary API costs and ensuring downstream
ShakeMap exports only receive authentic, estimable observations.
"""

from __future__ import annotations
import hashlib
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Dict, Any, List, Union

from .relevance_gate import RelevanceGate, RelevanceDecision
from .temporal_gate import TemporalGate, TemporalCheckResult
from .recycled_gate import RecycledMediaGate, DuplicateCheckResult
from .authenticity_gate import AuthenticityGate, AuthenticityCheckResult
from .spatial_gate import SpatialGate, SpatialCheckResult


@dataclass
class ScreeningResult:
    """Comprehensive structured result of pre-MMI screening."""
    event_id: str
    file_path: str
    file_name: str
    sha256_hash: str
    relevance_decision: str  # 'ESTIMABLE', 'NOT_ESTIMABLE', 'REVIEW_REQUIRED'
    is_estimable: bool
    decision_reasons: List[str] = field(default_factory=list)
    evidence_types: List[str] = field(default_factory=list)
    decision_mode: str = "deterministic_local"
    confidence: float = 1.0

    duplicate: Optional[Dict[str, Any]] = None
    temporal: Optional[Dict[str, Any]] = None
    spatial: Optional[Dict[str, Any]] = None
    authenticity: Optional[Dict[str, Any]] = None

    review_required: bool = False
    review_triggers: List[str] = field(default_factory=list)
    token_usage: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CompositeScreener:
    """
    Unified screener executing all five gates before MMI estimation.
    """

    def __init__(
        self,
        event_id: str = "us7000pn9s",
        origin_time_utc: str = "2025-03-28T06:20:00Z",
        spatial_bounds: Optional[Dict[str, float]] = None,
        allow_live_api: bool = False,
        provider: str = "ai_studio",
    ):
        self.event_id = event_id
        self.origin_time_utc = origin_time_utc
        self.allow_live_api = allow_live_api
        self.provider = provider

        # Initialize gates
        self.relevance_gate = RelevanceGate(allow_live_api=allow_live_api, provider=provider)
        self.temporal_gate = TemporalGate(origin_time_utc=origin_time_utc)
        self.recycled_gate = RecycledMediaGate()
        self.authenticity_gate = AuthenticityGate(allow_live_api=allow_live_api, provider=provider)
        self.spatial_gate = SpatialGate(spatial_bounds=spatial_bounds)

    def reset(self):
        """Reset session registries (e.g. duplicate hashes)."""
        self.recycled_gate.reset()

    def screen(
        self,
        file_path: Union[str, Path],
        extracted_text: Optional[str] = None,
        has_extractable_text: bool = True,
        page_count: int = 1,
        image_count: int = 0,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        coordinates_raw: Optional[str] = None,
    ) -> ScreeningResult:
        """
        Executes screening sequence.
        """
        path = Path(file_path).resolve()
        file_name = path.name

        # Compute hash
        try:
            sha256_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        except Exception:
            sha256_hash = "unknown"

        review_triggers: List[str] = []

        # ── Gate 1: Duplicate & Recycled Media Check ────────────────────────
        dup_result = self.recycled_gate.check(path)
        if not dup_result.is_unique:
            review_triggers.append(
                f"Duplicate observation detected: {dup_result.status} of '{dup_result.duplicate_of}'"
            )

        # ── Gate 2: Pre-MMI Evidence Relevance Check ───────────────────────
        rel_decision = self.relevance_gate.evaluate(
            file_path=path,
            extracted_text=extracted_text,
            has_extractable_text=has_extractable_text,
            page_count=page_count,
            image_count=image_count,
            coordinates_raw=coordinates_raw,
        )

        if rel_decision.decision == "NOT_ESTIMABLE":
            # Early exit: document does not contain usable MMI evidence
            return ScreeningResult(
                event_id=self.event_id,
                file_path=str(path),
                file_name=file_name,
                sha256_hash=sha256_hash,
                relevance_decision="NOT_ESTIMABLE",
                is_estimable=False,
                decision_reasons=rel_decision.reasons,
                evidence_types=rel_decision.evidence_types,
                decision_mode=rel_decision.decision_mode,
                confidence=rel_decision.confidence,
                duplicate=dup_result.to_dict(),
                temporal=None,
                spatial=None,
                authenticity=None,
                review_required=False,
                review_triggers=[],
                token_usage=rel_decision.token_usage,
            )

        if rel_decision.decision == "REVIEW_REQUIRED":
            review_triggers.extend([f"Relevance Gate: {r}" for r in rel_decision.reasons])

        # ── Gate 3: Temporal Consistency Check ──────────────────────────────
        temp_result = self.temporal_gate.check(
            file_path=path,
            extracted_text=extracted_text,
        )
        if not temp_result.is_valid:
            review_triggers.append(f"Temporal Contradiction: {temp_result.reason}")

        # ── Gate 4: Spatial Plausibility Check ──────────────────────────────
        spatial_result = self.spatial_gate.check(
            latitude=latitude,
            longitude=longitude,
            extracted_text=extracted_text,
        )
        if spatial_result.review_required and spatial_result.status == "OUTSIDE_BOUNDS":
            review_triggers.append(f"Spatial Plausibility: {spatial_result.reason}")

        # ── Gate 5: Authenticity Screening ──────────────────────────────────
        auth_result = self.authenticity_gate.check(
            file_path=path,
            extracted_text=extracted_text,
        )
        if not auth_result.is_authentic_candidate:
            review_triggers.append(f"Authenticity Warning: {auth_result.reason}")

        review_required = len(review_triggers) > 0 or (rel_decision.decision == "REVIEW_REQUIRED")
        relevance_decision = rel_decision.decision

        return ScreeningResult(
            event_id=self.event_id,
            file_path=str(path),
            file_name=file_name,
            sha256_hash=sha256_hash,
            relevance_decision=relevance_decision,
            is_estimable=(relevance_decision == "ESTIMABLE"),
            decision_reasons=rel_decision.reasons,
            evidence_types=rel_decision.evidence_types,
            decision_mode=rel_decision.decision_mode,
            confidence=rel_decision.confidence,
            duplicate=dup_result.to_dict(),
            temporal=temp_result.to_dict(),
            spatial=spatial_result.to_dict(),
            authenticity=auth_result.to_dict(),
            review_required=review_required,
            review_triggers=review_triggers,
            token_usage=rel_decision.token_usage,
        )
