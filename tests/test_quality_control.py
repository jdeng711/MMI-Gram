"""
Tests for Quality Control (QC) rules and state evaluation.
"""

import unittest
from mmigram.core.state import (
    Coordinates,
    MMIEstimationResult,
    StructuralDamageAssessment,
    LocationContext,
)
from mmigram.qc.rules import (
    check_coordinates,
    check_mmi_estimation,
    check_damage_evidence,
    FLAG_NULL_ISLAND,
    FLAG_INVALID_COORDINATES,
    FLAG_HIGH_INTENSITY_ANOMALY,
    FLAG_LOW_CONFIDENCE,
    FLAG_UNVERIFIED_ESTIMATE,
    FLAG_UNESTIMATED_INTENSITY,
    FLAG_INVALID_MMI_RANGE,
    FLAG_COORDINATE_DISCREPANCY,
)
from mmigram.qc.checker import evaluate_quality


class TestQualityControl(unittest.TestCase):

    def test_null_island_fails_qc(self):
        null_coords = Coordinates(latitude=0.0, longitude=0.0, is_valid=False)
        qc = evaluate_quality(coordinates=null_coords)

        self.assertEqual(qc.qc_status, "REJECTED")
        self.assertFalse(qc.is_valid_evidence)
        self.assertIn(FLAG_NULL_ISLAND, qc.qc_flags)
        self.assertIn(FLAG_INVALID_COORDINATES, qc.qc_flags)

    def test_high_intensity_anomaly_flagged(self):
        # MMI 9.0 is an extreme intensity that must be flagged for review
        coords = Coordinates(latitude=21.88, longitude=95.98, is_valid=True)
        est = MMIEstimationResult(
            mmi_value=9.0,
            confidence=0.90,
            reasoning="Major masonry collapse.",
            is_calibrated=False,
        )
        damage = StructuralDamageAssessment(
            visual_observations="Unreinforced brick walls collapsed completely."
        )

        qc = evaluate_quality(coordinates=coords, estimation=est, damage=damage)

        self.assertEqual(qc.qc_status, "FLAGGED")
        self.assertTrue(qc.is_valid_evidence)
        self.assertIn(FLAG_HIGH_INTENSITY_ANOMALY, qc.qc_flags)
        self.assertIn(FLAG_UNVERIFIED_ESTIMATE, qc.qc_flags)

    def test_low_confidence_flagged(self):
        coords = Coordinates(latitude=21.88, longitude=95.98, is_valid=True)
        est = MMIEstimationResult(
            mmi_value=6.0,
            confidence=0.50,  # Below 0.75
            reasoning="Slight wall cracks.",
            is_calibrated=False,
        )
        damage = StructuralDamageAssessment(
            visual_observations="Hairline cracks in plaster, dishes displaced."
        )

        qc = evaluate_quality(coordinates=coords, estimation=est, damage=damage)

        self.assertEqual(qc.qc_status, "FLAGGED")
        self.assertIn(FLAG_LOW_CONFIDENCE, qc.qc_flags)

    def test_calibrated_moderate_intensity_passes_cleanly(self):
        coords = Coordinates(latitude=21.88, longitude=95.98, is_valid=True)
        est = MMIEstimationResult(
            mmi_value=6.5,
            confidence=0.85,
            reasoning="Well supported damage indications.",
            is_calibrated=True,
        )
        damage = StructuralDamageAssessment(
            visual_observations="Substantial hairline cracking, chimney damage."
        )

        qc = evaluate_quality(coordinates=coords, estimation=est, damage=damage)

        self.assertEqual(qc.qc_status, "PASSED")
        self.assertEqual(len(qc.qc_flags), 0)
        self.assertEqual(qc.qc_score, 1.0)

    def test_missing_or_unestimated_mmi_flagged(self):
        """Verify that an unestimated/missing MMI is rejected by QC rather than defaulted to 5.0."""
        coords = Coordinates(latitude=21.88, longitude=95.98, is_valid=True)
        est = MMIEstimationResult(mmi_value=None, confidence=None)
        qc = evaluate_quality(coordinates=coords, estimation=est)

        self.assertEqual(qc.qc_status, "REJECTED")
        self.assertFalse(qc.is_valid_evidence)
        self.assertIn(FLAG_UNESTIMATED_INTENSITY, qc.qc_flags)
        self.assertIn(FLAG_INVALID_MMI_RANGE, qc.qc_flags)

    def test_invalid_physical_mmi_range_flagged(self):
        """Verify that out-of-range MMI values (e.g. 15.0 or -2.0) are rejected by QC."""
        coords = Coordinates(latitude=21.88, longitude=95.98, is_valid=True)
        est = MMIEstimationResult(mmi_value=15.0, confidence=0.8)
        qc = evaluate_quality(coordinates=coords, estimation=est)

        self.assertEqual(qc.qc_status, "REJECTED")
        self.assertIn(FLAG_INVALID_MMI_RANGE, qc.qc_flags)

    def test_coordinate_discrepancy_flagged(self):
        """Verify that coordinate discrepancies between document text and model are flagged."""
        coords = Coordinates(latitude=21.88, longitude=95.98, is_valid=True)
        est = MMIEstimationResult(mmi_value=6.0, confidence=0.85, is_calibrated=True)
        damage = StructuralDamageAssessment(visual_observations="Considerable cracked plaster.")
        loc = LocationContext(
            coordinates=coords,
            coordinates_disagree=True,
            discrepancy_details="Document and model coordinates differ by 45.2 km",
        )

        qc = evaluate_quality(coordinates=coords, estimation=est, damage=damage, location=loc)
        self.assertEqual(qc.qc_status, "FLAGGED")
        self.assertIn(FLAG_COORDINATE_DISCREPANCY, qc.qc_flags)


if __name__ == "__main__":
    unittest.main()
