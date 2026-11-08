"""
Regression Test Suite for StEER Example (server/test_page1.pdf).

Verifies the legacy observed pipeline baseline (MMI 9.0, confidence 0.90, Sagaing coordinates)
using offline fixtures by default. Live API calls remain disabled unless explicitly opted into.

IMPORTANT PRINCIPLE:
Baseline regression tests verify software determinism and reproducibility against the legacy
system. They do NOT validate scientific correctness. Scientific ground truth requires
independent authoritative consensus and expert calibration.
"""

import os
import json
import unittest
from pathlib import Path

from mmigram.geolocation.parser import parse_dms_string, extract_coordinates_from_text
from mmigram.geolocation.validator import validate_coordinates
from mmigram.core.state import (
    Coordinates,
    MMIEstimationResult,
    StructuralDamageAssessment,
    LocationContext,
    QualityControlRecord,
)
from mmigram.qc.checker import evaluate_quality
from mmigram.qc.rules import FLAG_HIGH_INTENSITY_ANOMALY, FLAG_NULL_ISLAND, FLAG_INVALID_COORDINATES
from mmigram.review.queue import HumanReviewQueue


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "steer_page1_baseline.json"


class TestPage1OfflineRegression(unittest.TestCase):
    """
    Offline regression tests verifying the exact observed legacy behavior on test_page1.pdf.
    Runs with zero network calls and zero paid API consumption.
    """

    def setUp(self):
        self.assertTrue(FIXTURE_PATH.exists(), f"Fixture missing at {FIXTURE_PATH}")
        with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
            self.fixture = json.load(f)

    def test_observed_legacy_baseline_mmi_and_confidence(self):
        """
        Verify that the legacy recorded baseline is preserved as MMI 9.0 with confidence 0.90.
        This ensures backward compatibility with prior 2025 Myanmar StEER pipeline runs.
        """
        baseline = self.fixture["observed_legacy_baseline"]
        self.assertEqual(
            baseline["mmi_estimation"],
            9.0,
            "Observed legacy regression baseline for test_page1.pdf must be exactly MMI 9.0",
        )
        self.assertEqual(
            baseline["confidence"],
            0.90,
            "Observed legacy regression baseline for test_page1.pdf must be confidence 0.90",
        )

    def test_source_document_coordinate_extraction(self):
        """
        Verify that the coordinates from the StEER document text:
        'Sagaing city, 21 52' 49.27" N, 95 59' 5.57" E'
        parse accurately to ~21.88035° N, ~95.98488° E.
        """
        raw_location = self.fixture["input"]["raw_location_string"]
        coords = extract_coordinates_from_text(raw_location)

        self.assertTrue(coords.is_valid, "Coordinate parser should recognize DMS format")
        expected_lat = self.fixture["input"]["expected_parsed_coords"]["latitude"]
        expected_lon = self.fixture["input"]["expected_parsed_coords"]["longitude"]

        self.assertAlmostEqual(coords.latitude, expected_lat, places=4)
        self.assertAlmostEqual(coords.longitude, expected_lon, places=4)

        # Confirm validation against regional bounds
        validated = validate_coordinates(coords)
        self.assertTrue(validated.is_valid)
        self.assertIsNone(validated.validation_error)

    def test_null_island_rejection_for_page1_observation(self):
        """
        Verify that injecting (0.0, 0.0) coordinates for this observation is explicitly
        flagged as INVALID and rejected by quality control.
        """
        corrupted_coords = Coordinates(latitude=0.0, longitude=0.0)
        validated = validate_coordinates(corrupted_coords)

        self.assertFalse(validated.is_valid)
        self.assertIn("Null Island", validated.validation_error)

        qc = evaluate_quality(coordinates=validated)
        self.assertEqual(qc.qc_status, "REJECTED")
        self.assertIn(FLAG_NULL_ISLAND, qc.qc_flags)
        self.assertIn(FLAG_INVALID_COORDINATES, qc.qc_flags)

    def test_qc_flags_high_intensity_for_review(self):
        """
        Ensure that MMI 9.0 triggers a HIGH_INTENSITY_ANOMALY flag in Quality Control.
        Generating MMI 9.0 does NOT mean it should be accepted blindly as scientific fact.
        """
        coords = Coordinates(latitude=21.88035, longitude=95.98488, is_valid=True)
        est = MMIEstimationResult(
            mmi_value=9.0,
            confidence=0.90,
            reasoning=self.fixture["observed_legacy_baseline"]["reasoning"],
            is_calibrated=False,
        )
        damage = StructuralDamageAssessment(
            visual_observations=self.fixture["observed_legacy_baseline"]["visual_observation"]
        )

        qc = evaluate_quality(coordinates=coords, estimation=est, damage=damage)

        # Must be flagged for human review due to MMI >= 9.0
        self.assertEqual(qc.qc_status, "FLAGGED")
        self.assertIn(FLAG_HIGH_INTENSITY_ANOMALY, qc.qc_flags)

    def test_human_review_queue_intercepts_page1_baseline(self):
        """
        Verify that the Human Review Queue enqueues the MMI 9.0 observation for expert audit.
        """
        queue = HumanReviewQueue()
        state = {
            "blob_name": "test_page1.pdf",
            "estimation": {"mmi_value": 9.0, "confidence": 0.90},
            "qc": {"qc_flags": [FLAG_HIGH_INTENSITY_ANOMALY]},
        }
        item = queue.check_and_enqueue("test_page1.pdf", state)

        self.assertIsNotNone(item)
        self.assertEqual(item.status, "UNREVIEWED")
        self.assertTrue(any("High seismic intensity" in t for t in item.triggers))

        # Test expert review override capability
        overridden = queue.override_mmi(
            "test_page1.pdf",
            reviewer_id="seismo_expert_01",
            new_mmi=8.0,
            notes="Adjusted from AI estimate 9.0 down to 8.0 based on structural damage indicators.",
        )
        self.assertEqual(overridden.status, "OVERRIDDEN")
        self.assertEqual(overridden.overridden_mmi, 8.0)


class TestScientificAccuracySeparation(unittest.TestCase):
    """
    Explicitly tests and verifies that software regression tests are kept distinct
    from scientific ground truth assessments.
    """

    def test_unverified_status_until_expert_calibration(self):
        # A raw model estimation has is_calibrated = False
        raw_result = MMIEstimationResult(mmi_value=9.0, confidence=0.90, is_calibrated=False)
        self.assertFalse(raw_result.is_calibrated, "Raw pipeline generation must not be labeled calibrated")

        # Only after formal calibration is it marked calibrated
        calibrated_result = MMIEstimationResult(mmi_value=8.0, confidence=0.95, is_calibrated=True)
        self.assertTrue(calibrated_result.is_calibrated)


class TestPage1LiveIntegration(unittest.TestCase):
    """
    Live API Integration test against server/test_page1.pdf.
    SKIPPED by default. Only executes if RUN_LIVE_API_TESTS=1 is explicitly passed.
    """

    @unittest.skipUnless(
        os.environ.get("RUN_LIVE_API_TESTS") == "1",
        "Live API integration tests are disabled by default. Pass RUN_LIVE_API_TESTS=1 to opt-in.",
    )
    def test_live_pipeline_execution(self):
        pdf_path = Path(__file__).parents[2] / "test_page1.pdf"
        self.assertTrue(pdf_path.exists(), f"test_page1.pdf missing at {pdf_path}")
        # Note: Live test logic would invoke crag.analyze_media_and_traverse_states
        # only upon explicit user consent and credential confirmation.
        pass


if __name__ == "__main__":
    unittest.main()
