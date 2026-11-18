"""
Seismological Consistency Critic (PhysicsCritic).

Evaluates whether an estimated Modified Mercalli Intensity (MMI) is physically plausible
given the observation site's finite-fault rupture distance (Rrup) and regional ground-motion characteristics.

Scientific Principles:
1. Non-Coercive Flagging: The critic identifies physical anomalies to trigger expert human review.
   It NEVER mutates, forces, or coercively adjusts the model's reported MMI toward a theoretical curve.
2. Tectonic Rupture vs. Vibratory Shaking: Distinguishes direct tectonic surface fault displacement
   (shear offset, scarp formation, surface rupture along the fault trace where MMI IX-X is physically expected)
   from pure inertial vibratory ground shaking.
3. Provenance Integrity: Preserves Rrup, Repi, and Rhypo separately, clearly noting whether distances
   are derived from a 3D finite-fault rupture mesh or a hypocenter fallback.
"""

from __future__ import annotations
import re
import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Tuple, Union

from .rrup_calculator import RrupCalculator


# Surface rupture keywords indicating primary tectonic displacement
SURFACE_RUPTURE_KEYWORDS = [
    "surface rupture",
    "fault rupture",
    "fault trace",
    "fault offset",
    "fault scarp",
    "surface displacement",
    "lateral offset",
    "strike-slip offset",
    "ground rupture",
    "ground offset",
    "surface break",
    "tectonic displacement",
    "ground displacement",
    "offset trace",
]

# Keywords indicating vibratory ground-shaking induced structural damage
STRUCTURAL_SHAKING_KEYWORDS = [
    "collapse",
    "collapsed",
    "structural failure",
    "shear failure",
    "wall crack",
    "masonry crack",
    "column failure",
    "beam crack",
    "drift",
    "unreinforced masonry",
    "rc frame",
    "reinforced concrete",
    "concrete spalling",
    "roof collapse",
    "plaster fall",
    "inertial damage",
    "shaking damage",
    "vibratory",
    "vibration",
    "destruction of substantial buildings",
]


@dataclass
class SeismologicalConsistencyResult:
    """Structured assessment of seismological and physical consistency."""
    is_physically_plausible: bool = True
    rrup_km: Optional[float] = None
    repi_km: Optional[float] = None
    rhypo_km: Optional[float] = None
    rupture_distance_source: str = "unavailable"  # "finite_fault_mesh", "hypocenter_alternative", "unavailable"
    surface_faulting_observed: bool = False
    geological_evidence_type: str = "undetermined"  # "shaking_induced_damage", "fault_displacement_only", "mixed_evidence", "undetermined"
    requires_expert_review: bool = False
    plausibility_flags: List[str] = field(default_factory=list)
    critic_notes: str = ""
    expected_mmi_range: Optional[Tuple[float, float]] = None
    mmi_estimate: Optional[float] = None

    @property
    def warning_flags(self) -> List[str]:
        """Convenience alias for plausibility_flags."""
        return self.plausibility_flags

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PhysicsCritic:
    """
    Evaluates physical plausibility of MMI observations against 3D finite-fault geometry.
    """

    def __init__(
        self,
        rrup_calculator: Optional[RrupCalculator] = None,
        rupture_geojson: Optional[Dict[str, Any]] = None,
        attenuation_curves_path: Optional[Union[str, Path]] = None,
        epicenter: Optional[Tuple[float, float, Optional[float]]] = None,
    ):
        if rrup_calculator:
            self.calculator = rrup_calculator
        else:
            self.calculator = RrupCalculator(rupture_geojson=rupture_geojson, epicenter=epicenter)

        self.attenuation_curves: Dict[str, Any] = {}
        if attenuation_curves_path and Path(attenuation_curves_path).exists():
            try:
                with open(attenuation_curves_path, "r", encoding="utf-8") as f:
                    self.attenuation_curves = json.load(f)
            except Exception:
                pass

    @classmethod
    def detects_surface_faulting(cls, text: Optional[str]) -> bool:
        """Detect whether evidence text documents direct tectonic surface fault rupture."""
        if not text:
            return False
        clean = text.lower()
        return any(kw in clean for kw in SURFACE_RUPTURE_KEYWORDS)

    @classmethod
    def detects_structural_shaking(cls, text: Optional[str]) -> bool:
        """Detect whether evidence text documents vibratory structural ground-shaking response."""
        if not text:
            return False
        clean = text.lower()
        return any(kw in clean for kw in STRUCTURAL_SHAKING_KEYWORDS)

    @classmethod
    def classify_geological_evidence_type(cls, text: Optional[str]) -> str:
        """
        Classify evidence into shaking-induced damage, fault displacement only, mixed, or undetermined.
        """
        has_displacement = cls.detects_surface_faulting(text)
        has_shaking = cls.detects_structural_shaking(text)

        if has_displacement and has_shaking:
            return "mixed_evidence"
        elif has_displacement and not has_shaking:
            return "fault_displacement_only"
        elif not has_displacement and has_shaking:
            return "shaking_induced_damage"
        else:
            return "undetermined"

    def evaluate_observation(
        self,
        mmi: Optional[float],
        latitude: Optional[float],
        longitude: Optional[float],
        evidence_text: Optional[str] = None,
        site_depth_km: float = 0.0,
    ) -> SeismologicalConsistencyResult:
        """
        Evaluate physical consistency of an observation site MMI estimate.

        Scientific Principles:
        1. Permanent fault displacement (fault rupture/offset/scarp) is NOT equivalent to shaking intensity.
        2. Rrup is a distance predictor, not proof of any particular MMI level.
        3. Do NOT automatically approve MMI IX–X based on fault offset or proximity alone.
        4. Ambiguous displacement-dominated observations are flagged for expert review.
        5. Never modify the raw model MMI estimation.
        """
        if latitude is None or longitude is None:
            return SeismologicalConsistencyResult(
                is_physically_plausible=True,
                rrup_km=None,
                repi_km=None,
                rhypo_km=None,
                rupture_distance_source="unavailable",
                critic_notes="Observation coordinates are null; distance-based physical critique skipped.",
            )

        distances = self.calculator.calculate_distances(latitude, longitude, site_depth_km)
        rrup = distances["rrup_km"]
        repi = distances["repi_km"]
        rhypo = distances["rhypo_km"]
        dist_source = distances["distance_source"]

        # Primary distance to evaluate attenuation: use Rrup if finite fault exists, else Repi
        effective_dist = rrup if rrup is not None else repi
        surface_faulting = self.detects_surface_faulting(evidence_text)
        evidence_type = self.classify_geological_evidence_type(evidence_text)

        flags: List[str] = []
        notes: List[str] = []
        is_plausible = True
        requires_review = False

        # Contextual geological notes (Rrup is a distance predictor, NOT proof of MMI)
        if rrup is not None:
            notes.append(f"Finite-fault rupture distance Rrup = {rrup:.2f} km (distance predictor only, not proof of intensity)")
            if rrup <= 1.0:
                notes.append("Observation site lies within proximal fault corridor (Rrup <= 1.0 km)")
        elif repi is not None:
            notes.append(f"Epicentral distance Repi = {repi:.2f} km (finite-fault rupture mesh unavailable)")

        if surface_faulting:
            notes.append(f"Direct tectonic surface faulting observed (evidence classification: {evidence_type})")

        if mmi is not None:
            # 1. Displacement-dominated or ambiguous surface rupture vs. vibratory shaking evaluation
            if mmi >= 8.5:
                if evidence_type == "fault_displacement_only":
                    # Severe intensity assigned solely or primarily on ground displacement/offset
                    is_plausible = False
                    requires_review = True
                    flags.append("PHYSICS_DISPLACEMENT_DOMINATED_MMI")
                    notes.append(
                        f"High intensity (MMI {mmi:.1f}) assigned based primarily on permanent tectonic surface fault displacement/offset "
                        "without documented structural shaking response. Permanent ground displacement is not an index of vibratory ground shaking."
                    )
                elif evidence_type == "mixed_evidence":
                    # Mixed: contains both surface rupture and structural response
                    requires_review = True
                    flags.append("PHYSICS_MIXED_DISPLACEMENT_AND_SHAKING")
                    notes.append(
                        f"High intensity (MMI {mmi:.1f}) with mixed evidence containing both surface fault offset and structural damage. "
                        "Requires seismological review to verify that MMI reflects vibratory shaking rather than ground shearing."
                    )

            # 2. Distant High Intensity Anomaly: MMI >= 8.5 at distance > 150 km
            if effective_dist is not None and effective_dist > 150.0 and mmi >= 8.5:
                is_plausible = False
                requires_review = True
                flags.append("PHYSICS_HIGH_INTENSITY_DISTANCE_ANOMALY")
                notes.append(
                    f"Physically anomalous: MMI {mmi:.1f} (violent destruction) reported at distance = {effective_dist:.1f} km "
                    "without documented extreme sedimentary basin amplification or localized foundation liquefaction."
                )

            # 3. Proximal Low Intensity Anomaly: MMI <= 3.0 at distance < 10 km
            elif effective_dist is not None and effective_dist < 10.0 and mmi <= 3.0:
                is_plausible = False
                requires_review = True
                flags.append("PHYSICS_LOW_INTENSITY_PROXIMAL_ANOMALY")
                notes.append(
                    f"Physically anomalous: MMI {mmi:.1f} (barely felt / not felt) reported within {effective_dist:.1f} km "
                    "of the active earthquake rupture zone."
                )

            # 4. Moderate Distance Anomaly: MMI >= 9.5 at distance > 80 km
            elif effective_dist is not None and effective_dist > 80.0 and mmi >= 9.5:
                is_plausible = False
                requires_review = True
                flags.append("PHYSICS_EXTREME_INTENSITY_DISTANCE_ANOMALY")
                notes.append(
                    f"Physically improbable: Extreme intensity MMI {mmi:.1f} reported at distance = {effective_dist:.1f} km."
                )

        if not flags:
            if rrup is not None:
                dist_str = f"Rrup = {rrup:.2f} km"
            elif repi is not None:
                dist_str = f"Repi = {repi:.2f} km"
            else:
                dist_str = "distance unknown"
            notes.append(f"Consistent with physical attenuation expectations ({dist_str}).")

        return SeismologicalConsistencyResult(
            is_physically_plausible=is_plausible,
            rrup_km=rrup,
            repi_km=repi,
            rhypo_km=rhypo,
            rupture_distance_source=dist_source,
            surface_faulting_observed=surface_faulting,
            geological_evidence_type=evidence_type,
            requires_expert_review=requires_review,
            plausibility_flags=flags,
            critic_notes="; ".join(notes),
            mmi_estimate=mmi,
        )
