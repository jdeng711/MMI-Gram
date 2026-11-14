"""
Local versioned MMI reference knowledge base for offline-first seismic estimation.

Provides deterministic access to official Modified Mercalli Intensity (MMI)
scale definitions without requiring Pinecone or external cloud vector databases.
Supports both the USGS 10-level operational scale (I-X) and the full 12-level
classical scale (I-XII).
"""

from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from langchain.schema import Document

logger = logging.getLogger(__name__)

# Primary asset location
DEFAULT_ASSET_PATH = Path(__file__).resolve().parents[1] / "assets" / "mmi_scale_definitions.json"
FALLBACK_TEXT_PATH = Path(__file__).resolve().parents[3] / "server" / "assets" / "mmi_definitions.txt"


def validate_scale_completeness(
    docs: List[Document],
    expected_levels_count: int = 10
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Validates that a collection of MMI reference documents contains exactly
    expected_levels_count unique, non-empty definitions starting from level 1.
    """
    expected_levels = set(range(1, expected_levels_count + 1))
    seen_levels = set()
    duplicate_levels = set()
    empty_levels = set()

    for doc in docs:
        meta = doc.metadata or {}
        level = meta.get("level")
        doc_id = meta.get("id", "")
        if level is None and "-" in doc_id:
            try:
                level = int(doc_id.split("-")[-1])
            except ValueError:
                level = None

        if level is not None and 1 <= level <= expected_levels_count:
            if level in seen_levels:
                duplicate_levels.add(level)
            seen_levels.add(level)
            if not doc.page_content or not doc.page_content.strip():
                empty_levels.add(level)

    missing_levels = sorted(list(expected_levels - seen_levels))
    duplicates = sorted(list(duplicate_levels))
    empties = sorted(list(empty_levels))

    is_complete = (
        len(seen_levels) == expected_levels_count
        and not duplicates
        and not empties
        and len(docs) == expected_levels_count
    )

    details = {
        "expected_count": expected_levels_count,
        "actual_count": len(docs),
        "levels_present": sorted(list(seen_levels)),
        "missing_levels": missing_levels,
        "duplicate_levels": duplicates,
        "empty_levels": empties,
        "is_complete": is_complete,
    }

    if is_complete:
        return True, f"Full MMI scale (1-{expected_levels_count}) is complete and verified.", details
    else:
        issues = []
        if missing_levels:
            issues.append(f"missing levels {missing_levels}")
        if duplicates:
            issues.append(f"duplicate levels {duplicates}")
        if empties:
            issues.append(f"empty definitions for levels {empties}")
        if len(docs) != expected_levels_count:
            issues.append(f"expected {expected_levels_count} documents but got {len(docs)}")
        return False, f"Incomplete MMI scale: {'; '.join(issues)}.", details


class LocalMMIReference:
    """
    Zero-cloud, versioned local reference knowledge base for MMI definitions.
    """

    def __init__(self, asset_path: Optional[Path] = None):
        self.asset_path = asset_path or DEFAULT_ASSET_PATH
        self._cache: Dict[str, Any] = {}
        self._load_asset()

    def _load_asset(self):
        if self.asset_path.exists():
            try:
                with open(self.asset_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._cache = data.get("scales", {})
                    return
            except Exception as e:
                logger.warning(f"Error reading JSON MMI asset at {self.asset_path}: {e}")

        # Fallback to server/assets/mmi_definitions.txt if JSON asset is missing
        if FALLBACK_TEXT_PATH.exists():
            try:
                defs = []
                lines = FALLBACK_TEXT_PATH.read_text(encoding="utf-8").splitlines()
                for idx, line in enumerate(lines, 1):
                    line_s = line.strip()
                    if line_s:
                        defs.append({
                            "level": idx,
                            "mmi": float(idx),
                            "roman": self._to_roman(idx),
                            "label": f"MMI {idx}",
                            "description": line_s,
                        })
                self._cache["usgs_10level_v1"] = {
                    "version": "1.0-fallback-txt",
                    "levels_count": len(defs),
                    "definitions": defs
                }
            except Exception as e:
                logger.warning(f"Error reading text MMI fallback: {e}")

    @staticmethod
    def _to_roman(num: int) -> str:
        roman_map = [
            (10, "X"), (9, "IX"), (8, "VIII"), (7, "VII"), (6, "VI"),
            (5, "V"), (4, "IV"), (3, "III"), (2, "II"), (1, "I")
        ]
        result = []
        for val, rom in roman_map:
            while num >= val:
                result.append(rom)
                num -= val
        return "".join(result)

    def get_supported_scales(self) -> List[str]:
        return list(self._cache.keys())

    def retrieve_full_scale(self, scale_version: str = "usgs_10level_v1") -> List[Document]:
        """
        Deterministically returns all MMI definitions for the selected scale.
        Defaults to 'usgs_10level_v1' (MMI I-X).
        """
        scale_data = self._cache.get(scale_version)
        if not scale_data:
            available = list(self._cache.keys())
            raise ValueError(f"Unknown scale version '{scale_version}'. Available: {available}")

        raw_defs = scale_data.get("definitions", [])
        expected_count = scale_data.get("levels_count", len(raw_defs))

        results: List[Document] = []
        for d in raw_defs:
            lvl = int(d.get("level", 1))
            lbl = d.get("label", f"MMI {lvl}")
            desc = d.get("description", "")
            roman = d.get("roman", self._to_roman(lvl))
            struct_ind = d.get("structural_indicators")
            ground_ind = d.get("ground_indicators")

            # Format rich page content
            content_parts = [f"{lbl}: {desc}"]
            if struct_ind:
                content_parts.append(f"Structural Indicators: {struct_ind}")
            if ground_ind:
                content_parts.append(f"Ground Indicators: {ground_ind}")
            content = "\n".join(content_parts)

            results.append(
                Document(
                    page_content=content,
                    metadata={
                        "id": f"mmi-{lvl}",
                        "level": lvl,
                        "roman": roman,
                        "source": "local_versioned_asset",
                        "scale_version": scale_version,
                        "is_authoritative_reference": True,
                        "reference_mode": "full_scale",
                    }
                )
            )

        # Validate completeness
        is_comp, msg, _ = validate_scale_completeness(results, expected_levels_count=expected_count)
        if not is_comp:
            logger.warning(f"Local scale completeness warning for '{scale_version}': {msg}")

        return results

    def retrieve_keyword_overlap(
        self,
        query: str,
        top_k: int = 3,
        scale_version: str = "usgs_10level_v1"
    ) -> List[Document]:
        """
        Retrieves top-k closest MMI definitions based on keyword term overlap.
        Reuses Clara's proven local overlap algorithm.
        """
        all_docs = self.retrieve_full_scale(scale_version=scale_version)
        if not query or not query.strip():
            # Default to middle of scale (MMI V-VII)
            mid = len(all_docs) // 2
            return all_docs[max(0, mid - 1): min(len(all_docs), mid + 2)]

        query_terms = set(query.lower().split())

        scored: List[Tuple[int, Document]] = []
        for doc in all_docs:
            text = doc.page_content.lower()
            text_terms = set(text.split())
            overlap = len(query_terms.intersection(text_terms))
            scored.append((overlap, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored[:top_k]]
