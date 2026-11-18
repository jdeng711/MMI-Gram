"""
Pre-MMI Evidence Relevance Gate for MMI-Gram.

Determines whether an input document or media item contains usable physical evidence
capable of supporting Modified Mercalli Intensity (MMI) estimation before running
expensive model inference.

Explicit Decisions:
  1. ESTIMABLE:
     Contains sufficient site-specific structural damage, ground failure, or macroseismic
     shaking observations (from photographs, video, or credible textual reports).
  2. NOT_ESTIMABLE:
     Lacks substantive site-specific damage/shaking evidence (e.g., presentation title
     slides, table of contents, author rosters, or regional hazard model simulation maps
     such as USGS ShakeMap PGA contours in Clara's page-8.pdf).
     CRITICAL: mmi_estimation is strictly set to null (None), NEVER 0.0.
  3. REVIEW_REQUIRED:
     Evidence is ambiguous, sparse, or conflicting, requiring expert seismological review.
     CRITICAL: mmi_estimation is strictly set to null (None) pending human review.

SCIENTIFIC PRINCIPLES:
  - Text-only documents with detailed damage/shaking observations ARE estimable (images not required).
  - Presence of images alone does NOT make a page estimable (e.g. logos, model maps, author portraits).
  - First applies fast, deterministic local text/layout analysis (zero LLM calls, $0.00).
  - Separately metered multimodal screening call can be invoked if text is absent/scanned.

Attribution:
  Incorporates and refines relevance criteria discussed with Clara Yoon (USGS) and
  the Harvard EPS 55 Macroseismic AI Research Group.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Literal, Union


@dataclass
class RelevanceDecision:
    """Structured decision output from the Pre-MMI Relevance Gate."""
    decision: Literal["ESTIMABLE", "NOT_ESTIMABLE", "REVIEW_REQUIRED"] = "ESTIMABLE"
    is_estimable: bool = True
    reasons: List[str] = field(default_factory=list)
    evidence_types: List[str] = field(default_factory=list)
    decision_mode: Literal["deterministic_local", "model_inferred", "manually_verified"] = "deterministic_local"
    confidence: float = 1.0
    token_usage: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RelevanceDecision:
        if not data:
            return cls()
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ──────────────────────────────────────────────────────────────────────────────
# Keyword & Pattern Dictionaries for Macroseismic Screening
# ──────────────────────────────────────────────────────────────────────────────

# Indicators of regional modeling / simulations / contours (NOT site ground truth)
MODEL_MAP_PATTERNS = [
    r"shakemap",
    r"pga\s+contour",
    r"pga\s+contours",
    r"liquefaction\s+estimate",
    r"liquefaction\s+susceptibility",
    r"ground\s+motion\s+model",
    r"gmpe",
    r"simulated\s+shaking",
    r"hazard\s+model",
    r"instrumental\s+intensity",
    r"scenario\s+contour",
    r"contour\s+is\s+\d+",
]

# Indicators of presentation title slides / TOC / team rosters (No field observations)
TITLE_PRESENTATION_PATTERNS = [
    r"preliminary\s+virtual\s+reconnaissance\s+report",
    r"virtual\s+reconnaissance",
    r"table\s+of\s+contents",
    r"author\s+list",
    r"team\s+organization",
    r"vast\s+member\s+name",
    r"acknowledgment[s]?",
    r"executive\s+summary",
    r"presentation\s+overview",
]

# Indicators of non-seismic, social, tourist, or unrelated content (Positive exclusion)
UNRELATED_CONTENT_PATTERNS = [
    r"team\s+dinner",
    r"traditional\s+cuisine",
    r"kandawgyi\s+lake",
    r"sunset\s+view",
    r"group\s+photo",
    r"sightseeing",
    r"\btourism\b",
    r"\bvacation\b",
    r"\bbanquet\b",
]

# Substantive physical structural damage indicators (Positive evidence)
STRUCTURAL_DAMAGE_PATTERNS = [
    r"\bcollapse[ds]?\b",
    r"partial\s+collapse",
    r"soft-story",
    r"pancake\s+collapse",
    r"\brubble\b",
    r"\bdebris\b",
    r"\bcrack(?:ed|ing|s)?\b",
    r"structural\s+damage",
    r"damage\s+observation[s]?",
    r"observed\s+damage",
    r"building\s+damage",
    r"masonry\s+failure",
    r"fallen\s+chimney",
    r"chimney\s+damaged",
    r"broken\s+chimney",
    r"roof\s+collapse",
    r"\bspalling\b",
    r"exposed\s+rebar",
    r"column[s]?\s+(?:sheared|buckled|failed)",
    r"foundation\s+(?:shifted|failure|damaged)",
    r"tilted\s+(?:building|structure)",
    r"\bdestroyed\b",
    r"heavily\s+damaged",
    r"extensive\s+damage",
    r"moderate\s+damage",
    r"slight\s+damage",
    r"broken\s+windows",
    r"unreinforced\s+masonry",
]

# Substantive ground failure indicators (Positive evidence)
GROUND_FAILURE_PATTERNS = [
    r"\bliquefaction\b",
    r"sand\s+boil[s]?",
    r"ground\s+fissure[s]?",
    r"fissures\s+in\s+ground",
    r"lateral\s+spread(?:ing)?",
    r"surface\s+rupture",
    r"fault\s+rupture",
    r"\blandslide[s]?\b",
    r"\brockfall[s]?\b",
    r"ground\s+crack[s]?",
    r"settlement\s+of\s+ground",
]

# Credible macroseismic shaking effects (Positive evidence - text observations!)
MACROSEISMIC_SHAKING_PATTERNS = [
    r"felt\s+by\s+all",
    r"felt\s+strongly",
    r"felt\s+noticeably",
    r"difficult\s+to\s+stand",
    r"furniture\s+overturned",
    r"awakened",
    r"dishes\s+broken",
    r"alarmed",
    r"ran\s+outdoors",
    r"hanging\s+objects\s+swing",
    r"swayed\s+violently",
    r"shaking\s+was\s+felt",
    r"strong\s+shaking",
    r"violent\s+shaking",
    r"heavy\s+truck\s+sensation",
    r"cracking\s+sound\s+in\s+walls",
]


class RelevanceGate:
    """
    Evaluates whether input document or media is suitable for MMI estimation.
    Applies deterministic local heuristics first, with optional metered model inference.
    """

    def __init__(self, allow_live_api: bool = False, provider: str = "ai_studio"):
        self.allow_live_api = allow_live_api
        self.provider = provider.lower()

    def evaluate(
        self,
        file_path: Union[str, Path],
        extracted_text: Optional[str] = None,
        has_extractable_text: bool = True,
        page_count: int = 1,
        image_count: int = 0,
        coordinates_raw: Optional[str] = None,
    ) -> RelevanceDecision:
        """
        Main entry point for pre-MMI relevance evaluation.
        """
        path = Path(file_path).resolve()
        text = (extracted_text or "").strip()
        text_lower = text.lower()

        reasons: List[str] = []
        evidence_types: List[str] = []

        # ──────────────────────────────────────────────────────────────────────
        # Pattern 1: Regional Hazard Model Map / ShakeMap Simulation Contours
        # (Clara's page-8.pdf archetype)
        # ──────────────────────────────────────────────────────────────────────
        model_matches = [p for p in MODEL_MAP_PATTERNS if re.search(p, text_lower)]
        damage_matches = [p for p in STRUCTURAL_DAMAGE_PATTERNS if re.search(p, text_lower)]
        ground_matches = [p for p in GROUND_FAILURE_PATTERNS if re.search(p, text_lower)]
        shaking_matches = [p for p in MACROSEISMIC_SHAKING_PATTERNS if re.search(p, text_lower)]

        has_na_coordinates = bool(
            re.search(r"geolocation\s*\(address/coordinates\):\s*n/a", text_lower)
            or (coordinates_raw and coordinates_raw.strip().upper() == "N/A")
        )

        if model_matches and not damage_matches and not shaking_matches:
            # Clear model simulation map without site damage observations
            evidence_types.append("regional_hazard_model_map")
            reasons.append(
                f"Document contains regional hazard model or contour map "
                f"({', '.join(model_matches[:3])}) rather than site-specific structural damage or physical shaking observations."
            )
            if has_na_coordinates:
                reasons.append("Geolocation is explicitly marked N/A.")

            return RelevanceDecision(
                decision="NOT_ESTIMABLE",
                is_estimable=False,
                reasons=reasons,
                evidence_types=evidence_types,
                decision_mode="deterministic_local",
                confidence=0.98,
            )

        # ──────────────────────────────────────────────────────────────────────
        # Pattern 2: Title Slide / Table of Contents / Administrative Cover
        # ──────────────────────────────────────────────────────────────────────
        title_matches = [p for p in TITLE_PRESENTATION_PATTERNS if re.search(p, text_lower)]
        if title_matches and not damage_matches and not shaking_matches:
            evidence_types.append("title_presentation_slide")
            reasons.append(
                f"Document is an overview, title slide, or table of contents "
                f"({', '.join(title_matches[:2])}) lacking site-specific shaking or damage evidence."
            )
            return RelevanceDecision(
                decision="NOT_ESTIMABLE",
                is_estimable=False,
                reasons=reasons,
                evidence_types=evidence_types,
                decision_mode="deterministic_local",
                confidence=0.95,
            )

        # ──────────────────────────────────────────────────────────────────────
        # Pattern 2b: Unrelated Non-Seismic Content (Social / Tourism / Scenery)
        # ──────────────────────────────────────────────────────────────────────
        unrelated_matches = [p for p in UNRELATED_CONTENT_PATTERNS if re.search(p, text_lower)]
        if unrelated_matches and not damage_matches and not shaking_matches and not ground_matches:
            evidence_types.append("unrelated_non_seismic_content")
            reasons.append(
                f"Document describes non-seismic activities or scenery ({', '.join(unrelated_matches[:2])}) "
                "lacking earthquake structural damage or physical shaking observations."
            )
            return RelevanceDecision(
                decision="NOT_ESTIMABLE",
                is_estimable=False,
                reasons=reasons,
                evidence_types=evidence_types,
                decision_mode="deterministic_local",
                confidence=0.96,
            )

        # ──────────────────────────────────────────────────────────────────────
        # Pattern 3: Substantive Physical Structural Damage & Shaking Observations
        # (Photos and/or Text)
        # ──────────────────────────────────────────────────────────────────────
        if damage_matches:
            evidence_types.append("structural_damage_observation")
            if image_count > 0:
                evidence_types.append("structural_damage_photo")
            reasons.append(
                f"Document contains documented physical structural damage observations "
                f"({', '.join(damage_matches[:3])}) capable of supporting macroseismic scaling."
            )

        if shaking_matches:
            evidence_types.append("macroseismic_shaking_observation")
            evidence_types.append("macroseismic_shaking_effect")
            reasons.append(
                f"Document contains credible macroseismic shaking effect descriptions "
                f"({', '.join(shaking_matches[:2])})."
            )

        # Ground failure / fault rupture handling:
        # Ground failure alone (without structural damage or felt shaking) cannot reliably
        # constrain vibratory shaking intensity, so defer to expert review.
        if ground_matches and not damage_matches and not shaking_matches:
            evidence_types.append("ground_failure_observation")
            reasons.append(
                f"Document reports surface ground failure or fault rupture ({', '.join(ground_matches[:2])}) "
                "without structural damage or felt shaking descriptions. Surface fault displacement alone "
                "cannot reliably constrain vibratory shaking intensity without expert geological review; "
                "deferred for human review."
            )
            return RelevanceDecision(
                decision="REVIEW_REQUIRED",
                is_estimable=False,
                reasons=reasons,
                evidence_types=evidence_types,
                decision_mode="deterministic_local",
                confidence=0.70,
            )

        if ground_matches and (damage_matches or shaking_matches):
            evidence_types.append("ground_failure_observation")
            reasons.append(
                f"Document contains surface ground failure/fault rupture observations ({', '.join(ground_matches[:2])}) "
                "alongside building damage or shaking reports. Note: structural damage proximal to fault rupture "
                "may reflect permanent displacement rather than vibratory shaking alone."
            )

        # If substantive physical structural damage or felt shaking was found, it is ESTIMABLE!
        if damage_matches or shaking_matches:
            return RelevanceDecision(
                decision="ESTIMABLE",
                is_estimable=True,
                reasons=reasons,
                evidence_types=evidence_types,
                decision_mode="deterministic_local",
                confidence=0.92,
            )

        # ──────────────────────────────────────────────────────────────────────
        # Pattern 4: Image-Based / Scanned PDF with No Extractable Text
        # ──────────────────────────────────────────────────────────────────────
        if not has_extractable_text or len(text) < 25:
            # If live model screening is requested and enabled, execute metered visual screening call
            if self.allow_live_api:
                return self._evaluate_with_model(path)

            # Offline mode: mark REVIEW_REQUIRED for visual inspection
            evidence_types.append("unverified_visual_evidence")
            reasons.append(
                "Document is image-based or lacks an embedded text layer; "
                "requires visual screening to verify earthquake damage relevance."
            )
            return RelevanceDecision(
                decision="REVIEW_REQUIRED",
                is_estimable=False,
                reasons=reasons,
                evidence_types=evidence_types,
                decision_mode="deterministic_local",
                confidence=0.50,
            )

        # ──────────────────────────────────────────────────────────────────────
        # Pattern 5: Generic / Ambiguous Content without Specific Damage
        # ──────────────────────────────────────────────────────────────────────
        # If text is present but contains neither damage keywords nor model keywords
        evidence_types.append("ambiguous_text_content")
        reasons.append(
            "Document text does not contain recognized structural damage, ground failure, "
            "or macroseismic shaking indicators."
        )
        return RelevanceDecision(
            decision="REVIEW_REQUIRED",
            is_estimable=False,
            reasons=reasons,
            evidence_types=evidence_types,
            decision_mode="deterministic_local",
            confidence=0.60,
        )

    def _evaluate_with_model(self, file_path: Path) -> RelevanceDecision:
        """
        Executes a lightweight, separately metered Gemini multimodal screening call.
        Only invoked when live API execution is explicitly permitted and local heuristics are ambiguous.
        """
        try:
            import json
            from services.manage_model import get_response, Part

            screening_schema = {
                "type": "object",
                "properties": {
                    "is_estimable": {"type": "boolean"},
                    "relevance_decision": {
                        "type": "string",
                        "enum": ["ESTIMABLE", "NOT_ESTIMABLE", "REVIEW_REQUIRED"]
                    },
                    "evidence_types": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "reasons": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "confidence": {"type": "number"}
                },
                "required": ["is_estimable", "relevance_decision", "evidence_types", "reasons", "confidence"]
            }

            prompt = f"""
            You are a triage seismologist screening earthquake reconnaissance documents.
            Does this file contain site-specific physical damage, structural cracking, ground failure,
            or macroseismic shaking observations capable of estimating Modified Mercalli Intensity?
            
            Respond with JSON matching this schema:
            {json.dumps(screening_schema, indent=2)}
            """

            # Direct local file streaming
            from mmigram.adapters.gemini_provider import load_local_media_part
            media_part = load_local_media_part(file_path)

            contents = [Part.from_text(prompt), media_part]
            raw_text = get_response(contents, json_mode=True)
            data = json.loads(raw_text)

            decision_str = data.get("relevance_decision", "REVIEW_REQUIRED")
            is_estimable = (decision_str == "ESTIMABLE")

            return RelevanceDecision(
                decision=decision_str,
                is_estimable=is_estimable,
                reasons=data.get("reasons", ["Model-inferred screening decision"]),
                evidence_types=data.get("evidence_types", ["model_inferred"]),
                decision_mode="model_inferred",
                confidence=float(data.get("confidence", 0.85)),
            )
        except Exception as e:
            return RelevanceDecision(
                decision="REVIEW_REQUIRED",
                is_estimable=False,
                reasons=[f"Model screening call encountered error ({e}); routing to human review"],
                evidence_types=["screening_error"],
                decision_mode="deterministic_local",
                confidence=0.30,
            )
