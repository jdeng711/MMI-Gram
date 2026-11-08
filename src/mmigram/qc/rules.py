"""
Quality Control rules and heuristics for earthquake MMI observations.
"""

from typing import List, Tuple, Dict, Any, Optional
from ..core.state import Coordinates, MMIEstimationResult, StructuralDamageAssessment, LocationContext

# QC Flag constants
FLAG_INVALID_COORDINATES = "INVALID_COORDINATES"
FLAG_NULL_ISLAND = "NULL_ISLAND_COORDINATES"
FLAG_OUT_OF_REGION = "COORDINATES_OUT_OF_REGION"
FLAG_INVALID_MMI_RANGE = "INVALID_MMI_RANGE"
FLAG_UNESTIMATED_INTENSITY = "UNESTIMATED_INTENSITY"
FLAG_HIGH_INTENSITY_ANOMALY = "HIGH_INTENSITY_ANOMALY"
FLAG_LOW_CONFIDENCE = "LOW_CONFIDENCE"
FLAG_SPARSE_EVIDENCE = "SPARSE_DAMAGE_EVIDENCE"
FLAG_UNVERIFIED_ESTIMATE = "UNVERIFIED_ESTIMATE"
FLAG_COORDINATE_DISCREPANCY = "COORDINATE_DISCREPANCY"
FLAG_COORDINATES_DISAGREE = "COORDINATE_DISCREPANCY"
FLAG_MODEL_LOCATION_UNAVAILABLE = "MODEL_LOCATION_UNAVAILABLE"
FLAG_REFERENCE_RETRIEVAL_FAILED = "REFERENCE_RETRIEVAL_FAILED"


def check_coordinates(coords: Optional[Coordinates]) -> Tuple[bool, List[str]]:
    """Check coordinates for validity, null island, or missing data."""
    flags = []
    if coords is None or coords.latitude is None or coords.longitude is None:
        flags.append(FLAG_INVALID_COORDINATES)
        return False, flags

    if abs(coords.latitude) < 1e-5 and abs(coords.longitude) < 1e-5:
        flags.append(FLAG_NULL_ISLAND)
        flags.append(FLAG_INVALID_COORDINATES)
        return False, flags

    if not coords.is_valid:
        if coords.validation_error and "regional bounds" in coords.validation_error.lower():
            flags.append(FLAG_OUT_OF_REGION)
        else:
            flags.append(FLAG_INVALID_COORDINATES)
        return False, flags

    return True, flags


def check_mmi_estimation(
    estimation: Optional[MMIEstimationResult],
    confidence_threshold: float = 0.75,
) -> Tuple[bool, List[str]]:
    """
    Validate MMI value range and check for high-intensity anomalies.
    Note: MMI >= 9.0 represents extreme destruction and must be flagged for review.
    Missing or malformed MMI values are flagged as UNESTIMATED_INTENSITY and INVALID_MMI_RANGE.
    """
    flags = []
    if estimation is None or estimation.mmi_value is None:
        flags.append(FLAG_UNESTIMATED_INTENSITY)
        flags.append(FLAG_INVALID_MMI_RANGE)
        return False, flags

    mmi = estimation.mmi_value
    if not (1.0 <= mmi <= 12.0):
        flags.append(FLAG_INVALID_MMI_RANGE)
        return False, flags

    # Check for extreme intensity requiring manual scrutiny
    if mmi >= 9.0:
        flags.append(FLAG_HIGH_INTENSITY_ANOMALY)

    # Check analytical confidence
    if estimation.confidence is None or estimation.confidence < confidence_threshold:
        flags.append(FLAG_LOW_CONFIDENCE)

    # Distinguish between generated estimate and authoritative ground truth
    if not estimation.is_calibrated:
        flags.append(FLAG_UNVERIFIED_ESTIMATE)

    is_clean = len(flags) == 0 or (len(flags) == 1 and flags[0] == FLAG_UNVERIFIED_ESTIMATE)
    return is_clean, flags


def check_coordinate_agreement(location: Optional[LocationContext]) -> Tuple[bool, List[str]]:
    """Check whether document-extracted and model-predicted coordinates disagree or are unavailable."""
    flags = []
    if not location:
        return True, flags
    if location.coordinates_disagree:
        flags.append(FLAG_COORDINATE_DISCREPANCY)
    if location.comparison_status == FLAG_MODEL_LOCATION_UNAVAILABLE:
        flags.append(FLAG_MODEL_LOCATION_UNAVAILABLE)
    return len(flags) == 0, flags


def check_damage_evidence(damage: Optional[StructuralDamageAssessment]) -> Tuple[bool, List[str]]:
    """Check that structural observations are present and substantive."""
    flags = []
    if damage is None or not damage.visual_observations or len(damage.visual_observations.strip()) < 20:
        flags.append(FLAG_SPARSE_EVIDENCE)
        return False, flags
    return True, flags


def check_reference_retrieval(retrieval_status: Optional[str]) -> Tuple[bool, List[str]]:
    """Check that authoritative seismic reference documents were successfully retrieved."""
    flags = []
    if retrieval_status is not None and retrieval_status.upper() in ("UNRETRIEVED", "FAILED", "INCOMPLETE"):
        flags.append(FLAG_REFERENCE_RETRIEVAL_FAILED)
        return False, flags
    return True, flags
