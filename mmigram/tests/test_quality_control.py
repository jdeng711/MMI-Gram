"""
Tests for Quality Control (QC) rules and state evaluation.
"""

import unittest
from server.mmigram.core.state import (
    Coordinates,
    MMIEstimationResult,
    StructuralDamageAssessment,
)
from server.mmigram.qc.rules import (
    check_coordinates,
    check_mmi_estimation,
    check_damage_evidence,
    FLAG_NULL_ISLAND,
    FLAG_INVALID_COORDINATES,
    FLAG_HIGH_INTENSITY_ANOMALY,
    FLAG_LOW_CONFIDENCE,
    FLAG_UNVERIFIED_ESTIMATE,
)
from server.mmigram.qc.checker import evaluate_quality


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


if __name__ == "__main__":
    unittest.main()
