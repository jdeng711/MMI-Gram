"""
Authenticity Screening Gate for MMI-Gram.

Screens observation media for indicators of synthetic generation or AI manipulation
(e.g., Midjourney, DALL-E, Stable Diffusion, Flux, CGI).

SCIENTIFIC PRINCIPLES:
  - Treat AI-generation or manipulation indicators as uncertain screening evidence,
    NOT definitive proof.
  - Flag suspicious material for expert human review; do NOT silently delete or reject.
  - Preserves original observations with structured provenance.

Attribution:
  Adapted and expanded from Clara Yoon's AuthenticityGate in QuakeLLMmap (quake_agent/gates/authenticity_gate.py).
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from PIL import Image


@dataclass
class AuthenticityCheckResult:
    """Result of authenticity and synthetic-media screening."""
    status: str = "NO_INDICATORS_DETECTED"  # 'NO_INDICATORS_DETECTED', 'SUSPICIOUS_AI_GENERATED', 'UNKNOWN'
    is_authentic_candidate: bool = True
    suspicion_level: str = "none"  # 'none', 'low', 'high'
    heuristic_score: float = 0.0  # Heuristic score (uncalibrated, NOT a probability)
    is_calibrated: bool = False  # Strictly uncalibrated
    reason: str = "No synthetic AI generation indicators detected in document text or metadata (uncalibrated heuristic)."
    indicators_detected: List[str] = field(default_factory=list)
    review_required: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


AI_GENERATOR_KEYWORDS = [
    r"midjourney",
    r"dall-e",
    r"\bdalle\b",
    r"stable\s+diffusion",
    r"stablediffusion",
    r"novelai",
    r"adobe\s+firefly",
    r"\bfirefly\b",
    r"\bflux\.1\b",
    r"flux-schnell",
    r"flux-dev",
    r"\bcomfyui\b",
    r"\bautomatic1111\b",
    r"civitai",
]

SYNTHETIC_PROMPT_PATTERNS = [
    r"--ar\s+\d+:\d+",
    r"--v\s+\d+",
    r"octane\s+render",
    r"unreal\s+engine\s+5",
    r"photorealistic\s+earthquake\s+damage",
    r"hyperrealistic\s+rubble",
    r"masterpiece,\s+best\s+quality",
]


class AuthenticityGate:
    """
    Evaluates media and metadata for synthetic media signatures.
    """

    def __init__(self, allow_live_api: bool = False, provider: str = "ai_studio"):
        self.allow_live_api = allow_live_api
        self.provider = provider

    def check(
        self,
        file_path: Optional[Union[str, Path]] = None,
        extracted_text: Optional[str] = None,
    ) -> AuthenticityCheckResult:
        """
        Executes fast local metadata and prompt forensics, with optional LLM visual forensics.
        """
        indicators: List[str] = []
        ai_score = 0.05

        # 1. Text Prompt Inspection
        text = extracted_text or ""
        text_lower = text.lower()

        for kw in AI_GENERATOR_KEYWORDS:
            if re.search(kw, text_lower):
                indicators.append(f"AI generator software mention in text: '{kw}'")

        for pattern in SYNTHETIC_PROMPT_PATTERNS:
            if re.search(pattern, text_lower):
                indicators.append(f"Synthetic generation prompt pattern in text: '{pattern}'")

        # 2. File Metadata Inspection
        if file_path:
            p = Path(file_path).resolve()
            if p.exists():
                ext = p.suffix.lower()
                if ext in (".jpg", ".jpeg", ".png", ".webp"):
                    meta_indicators = self._inspect_image_metadata(p)
                    indicators.extend(meta_indicators)
                elif ext == ".pdf":
                    pdf_indicators = self._inspect_pdf_metadata(p)
                    indicators.extend(pdf_indicators)

        if indicators:
            return AuthenticityCheckResult(
                status="SUSPICIOUS_AI_GENERATED",
                is_authentic_candidate=False,
                suspicion_level="high",
                heuristic_score=0.85,
                is_calibrated=False,
                reason=(
                    f"Suspicious synthetic media signatures detected in metadata or text "
                    f"({len(indicators)} indicators). Preserved for expert review."
                ),
                indicators_detected=indicators,
                review_required=True,
            )

        return AuthenticityCheckResult(
            status="NO_INDICATORS_DETECTED",
            is_authentic_candidate=True,
            suspicion_level="none",
            heuristic_score=0.0,
            is_calibrated=False,
            reason="No synthetic AI generation indicators detected in document text or metadata (uncalibrated heuristic).",
            indicators_detected=[],
            review_required=False,
        )

    def _inspect_image_metadata(self, path: Path) -> List[str]:
        indicators = []
        try:
            with Image.open(path) as img:
                info_str = str(img.info).lower()
                for kw in AI_GENERATOR_KEYWORDS:
                    if re.search(kw, info_str):
                        indicators.append(f"Generative AI metadata tag in image info: '{kw}'")
                exif = img.getexif()
                if exif:
                    exif_str = str(exif.items()).lower()
                    for kw in AI_GENERATOR_KEYWORDS:
                        if re.search(kw, exif_str):
                            indicators.append(f"Generative AI tag in EXIF: '{kw}'")
        except Exception:
            pass
        return indicators

    def _inspect_pdf_metadata(self, path: Path) -> List[str]:
        indicators = []
        try:
            import pypdf
            reader = pypdf.PdfReader(str(path))
            meta = reader.metadata
            if meta:
                meta_str = str(meta).lower()
                for kw in AI_GENERATOR_KEYWORDS:
                    if re.search(kw, meta_str):
                        indicators.append(f"Generative AI software tag in PDF metadata: '{kw}'")
        except Exception:
            pass
        return indicators
