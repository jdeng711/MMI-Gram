"""
Automated Quality Control Evaluator.
"""

from typing import List, Dict, Any, Optional
from ..core.state import (
    MMIGramState,
    QualityControlRecord,
    Coordinates,
    MMIEstimationResult,
    StructuralDamageAssessment,
    LocationContext,
)
from .rules import (
    check_coordinates,
    check_mmi_estimation,
    check_damage_evidence,
    check_coordinate_agreement,
    FLAG_INVALID_COORDINATES,
    FLAG_NULL_ISLAND,
    FLAG_INVALID_MMI_RANGE,
    FLAG_UNESTIMATED_INTENSITY,
    FLAG_HIGH_INTENSITY_ANOMALY,
    FLAG_LOW_CONFIDENCE,
    FLAG_COORDINATE_DISCREPANCY,
    FLAG_MODEL_LOCATION_UNAVAILABLE,
)


def evaluate_quality(
    coordinates: Optional[Coordinates] = None,
    estimation: Optional[MMIEstimationResult] = None,
    damage: Optional[StructuralDamageAssessment] = None,
    confidence_threshold: float = 0.75,
    location: Optional[LocationContext] = None,
) -> QualityControlRecord:
    """
    Run full QC evaluation on extracted parameters.
    Returns QualityControlRecord with status PASSED, FLAGGED, or REJECTED.
    """
    all_flags: List[str] = []
    fatal_errors = 0

    # Resolve coordinates if passed via location context
    active_coords = coordinates
    if active_coords is None and location is not None:
        active_coords = location.coordinates

    # 1. Coordinates check
    coords_ok, coord_flags = check_coordinates(active_coords)
    all_flags.extend(coord_flags)
    if FLAG_INVALID_COORDINATES in coord_flags or FLAG_NULL_ISLAND in coord_flags:
        fatal_errors += 1

    # 2. Coordinate agreement / discrepancy check
    if location is not None:
        agree_ok, agree_flags = check_coordinate_agreement(location)
        all_flags.extend(agree_flags)

    # 3. MMI check
    mmi_ok, mmi_flags = check_mmi_estimation(estimation, confidence_threshold=confidence_threshold)
    all_flags.extend(mmi_flags)
    if FLAG_INVALID_MMI_RANGE in mmi_flags:
        fatal_errors += 1

    # 4. Damage observations check
    damage_ok, damage_flags = check_damage_evidence(damage)
    all_flags.extend(damage_flags)

    # Score calculation (1.0 = perfect, deduct per flag)
    score = 1.0 - (0.25 * len(all_flags))
    score = max(0.0, min(1.0, score))

    if fatal_errors > 0:
        status = "REJECTED"
        is_valid = False
    elif len(all_flags) > 0 and (
        FLAG_HIGH_INTENSITY_ANOMALY in all_flags
        or FLAG_LOW_CONFIDENCE in all_flags
        or FLAG_COORDINATE_DISCREPANCY in all_flags
        or FLAG_MODEL_LOCATION_UNAVAILABLE in all_flags
    ):
        status = "FLAGGED"
        is_valid = True
    else:
        status = "PASSED"
        is_valid = True

    return QualityControlRecord(
        is_valid_evidence=is_valid,
        qc_status=status,
        qc_flags=all_flags,
        qc_score=round(score, 2),
    )


def evaluate_state_quality(state: MMIGramState) -> QualityControlRecord:
    """Convenience wrapper to run QC directly on an MMIGramState dictionary."""
    coords_data = state.get("location", {}).get("coordinates") if isinstance(state.get("location"), dict) else None
    coords = Coordinates.from_dict(coords_data) if coords_data else None

    est_data = state.get("estimation")
    est = MMIEstimationResult.from_dict(est_data) if est_data else None

    damage_data = state.get("damage")
    damage = StructuralDamageAssessment.from_dict(damage_data) if damage_data else None

    # Fallback to legacy keys if modular keys are not yet populated
    if est is None and "final_analysis" in state:
        final = state["final_analysis"]
        est = MMIEstimationResult(
            mmi_value=final.get("mmi_estimation"),
            confidence=final.get("confidence", 0.0),
            reasoning=final.get("reasoning", ""),
        )

    return evaluate_quality(coordinates=coords, estimation=est, damage=damage)
