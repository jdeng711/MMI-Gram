"""
Regression Test Suite for Geographic Coordinate Comparison & Discrepancy Detection.

Verifies:
1. COORDINATES_AGREE (both valid and within distance threshold)
2. COORDINATES_DISAGREE (both valid but exceeding distance threshold)
3. MODEL_LOCATION_UNAVAILABLE (doc valid, model coords null or unknown; never treated as agreement)
4. COORDINATES_DISAGREE via corrupted/invalid model coords (e.g. Null Island)
5. DOCUMENT_LOCATION_UNAVAILABLE (model valid, doc coords unavailable)
6. BOTH_LOCATIONS_UNAVAILABLE (neither source established coordinates)
7. Integration with evaluate_quality and QualityControlRecord
"""

import unittest
from mmigram.core.state import Coordinates, LocationContext, MMIEstimationResult, StructuralDamageAssessment
from mmigram.geolocation.validator import compare_coordinates, validate_coordinates
from mmigram.qc.checker import evaluate_quality
from mmigram.qc.rules import FLAG_COORDINATES_DISAGREE, FLAG_MODEL_LOCATION_UNAVAILABLE


class TestLocationComparison(unittest.TestCase):
    """Test suite for coordinate discrepancy and comparison status."""

    def test_coordinates_agree(self):
        """Doc and model coords close together (< 10km) should yield COORDINATES_AGREE."""
        doc = Coordinates(latitude=21.8803, longitude=95.9848, is_valid=True)
        # 1 km away
        model = Coordinates(latitude=21.8850, longitude=95.9870, is_valid=True)

        status, disagree, dist, details = compare_coordinates(doc, model, threshold_km=10.0)

        self.assertEqual(status, "COORDINATES_AGREE")
        self.assertFalse(disagree)
        self.assertIsNotNone(dist)
        self.assertLess(dist, 10.0)
        self.assertIn("agree within", details)

    def test_coordinates_disagree(self):
        """Doc and model coords far apart (> 10km) should yield COORDINATES_DISAGREE."""
        doc = Coordinates(latitude=21.8803, longitude=95.9848, is_valid=True)  # Sagaing
        model = Coordinates(latitude=21.9750, longitude=96.0830, is_valid=True)  # Mandalay (~15km away)

        status, disagree, dist, details = compare_coordinates(doc, model, threshold_km=10.0)

        self.assertEqual(status, "COORDINATES_DISAGREE")
        self.assertTrue(disagree)
        self.assertIsNotNone(dist)
        self.assertGreater(dist, 10.0)
        self.assertIn("disagree by", details)

    def test_model_location_unavailable_is_not_agreement(self):
        """
        CRITICAL INVARIANT: Missing/null model coordinates must NEVER be interpreted as agreement.
        Status must be MODEL_LOCATION_UNAVAILABLE and disagree must be False.
        """
        doc = Coordinates(latitude=21.8803, longitude=95.9848, is_valid=True)
        model = None

        status, disagree, dist, details = compare_coordinates(doc, model)

        self.assertEqual(status, "MODEL_LOCATION_UNAVAILABLE")
        self.assertFalse(disagree)
        self.assertIsNone(dist)
        self.assertIn("model location was unavailable", details)

    def test_model_location_invalid_coords_treated_as_disagree(self):
        """If model returns an invalid coordinate (e.g. Null Island), it should be flagged as disagreement."""
        doc = Coordinates(latitude=21.8803, longitude=95.9848, is_valid=True)
        model = validate_coordinates(Coordinates(latitude=0.0, longitude=0.0))  # Null Island

        self.assertFalse(model.is_valid)
        self.assertIsNotNone(model.validation_error)

        status, disagree, dist, details = compare_coordinates(doc, model)

        self.assertEqual(status, "COORDINATES_DISAGREE")
        self.assertTrue(disagree)
        self.assertIn("Null Island", details)

    def test_document_location_unavailable(self):
        """Model provides coordinates but document text had none."""
        doc = None
        model = Coordinates(latitude=21.8803, longitude=95.9848, is_valid=True)

        status, disagree, dist, details = compare_coordinates(doc, model)

        self.assertEqual(status, "DOCUMENT_LOCATION_UNAVAILABLE")
        self.assertFalse(disagree)
        self.assertIsNone(dist)
        self.assertIn("no coordinates were detected in document text", details)

    def test_both_locations_unavailable(self):
        """Neither document text nor model establishes coordinates."""
        status, disagree, dist, details = compare_coordinates(None, None)

        self.assertEqual(status, "BOTH_LOCATIONS_UNAVAILABLE")
        self.assertFalse(disagree)
        self.assertIsNone(dist)
        self.assertIn("Neither document text nor multimodal model", details)

    def test_qc_flags_integration_with_location_context(self):
        """Verify that evaluate_quality sets appropriate QC flags for location context states."""
        # 1. Model Location Unavailable
        loc_unavail = LocationContext(
            coordinates=Coordinates(latitude=21.8803, longitude=95.9848, is_valid=True),
            document_coordinates=Coordinates(latitude=21.8803, longitude=95.9848, is_valid=True),
            model_coordinates=None,
            comparison_status="MODEL_LOCATION_UNAVAILABLE",
            coordinates_disagree=False,
        )
        est = MMIEstimationResult(mmi_value=7.0, confidence=0.85, is_calibrated=False)
        damage = StructuralDamageAssessment(visual_observations="Cracked walls")

        qc_res1 = evaluate_quality(
            coordinates=loc_unavail.coordinates,
            estimation=est,
            damage=damage,
            location=loc_unavail,
        )
        self.assertIn(FLAG_MODEL_LOCATION_UNAVAILABLE, qc_res1.qc_flags)

        # 2. Coordinates Disagree
        loc_disagree = LocationContext(
            coordinates=Coordinates(latitude=21.8803, longitude=95.9848, is_valid=True),
            document_coordinates=Coordinates(latitude=21.8803, longitude=95.9848, is_valid=True),
            model_coordinates=Coordinates(latitude=21.9750, longitude=96.0830, is_valid=True),
            comparison_status="COORDINATES_DISAGREE",
            coordinates_disagree=True,
            discrepancy_details="Distance 15km",
        )
        qc_res2 = evaluate_quality(
            coordinates=loc_disagree.coordinates,
            estimation=est,
            damage=damage,
            location=loc_disagree,
        )
        self.assertIn(FLAG_COORDINATES_DISAGREE, qc_res2.qc_flags)
        self.assertEqual(qc_res2.qc_status, "FLAGGED")

    def test_original_legacy_null_island_rejection(self):
        """
        Verify the original recorded Gemini baseline output:
        Document text parsed Sagaing (21.8804, 95.9849), while original legacy model
        output returned invalid coordinates (0.0, 0.0).
        This must be flagged as COORDINATES_DISAGREE and Null Island must be detected.
        """
        doc = Coordinates(latitude=21.880353, longitude=95.984881, source="dms_parsed", is_valid=True)
        raw_model = Coordinates(latitude=0.0, longitude=0.0, source="model_predicted")
        model = validate_coordinates(raw_model)

        self.assertFalse(model.is_valid)
        self.assertIn("Null Island", model.validation_error)

        status, disagree, dist, details = compare_coordinates(doc, model)
        self.assertEqual(status, "COORDINATES_DISAGREE")
        self.assertTrue(disagree)
        self.assertIn("Null Island", details)

    def test_live_gemini_unknown_location(self):
        """
        Verify the newer live Gemini 2.5 Flash output:
        Document text parsed Sagaing (21.8804, 95.9849), while model returned 'Unknown' / None.
        This must be classified as MODEL_LOCATION_UNAVAILABLE, NOT agreement.
        """
        doc = Coordinates(latitude=21.880353, longitude=95.984881, source="dms_parsed", is_valid=True)
        model = None  # Model returned "Unknown"

        status, disagree, dist, details = compare_coordinates(doc, model)
        self.assertEqual(status, "MODEL_LOCATION_UNAVAILABLE")
        self.assertFalse(disagree)
        self.assertIsNone(dist)
        self.assertIn("model location was unavailable", details)

    def test_model_coordinates_never_populated_from_document_coordinates(self):
        """
        Scientific Integrity Invariant: Model coordinates must NEVER be backfilled
        or copied from document coordinates. If the model produces (0,0) or None,
        model_coordinates must strictly retain that original unverified state.
        """
        doc = Coordinates(latitude=21.880353, longitude=95.984881, source="dms_parsed", is_valid=True)
        raw_model_null = Coordinates(latitude=0.0, longitude=0.0, source="model_predicted", is_valid=False)

        loc = LocationContext(
            address="Sagaing city",
            coordinates=doc,  # Primary candidate coordinates
            document_coordinates=doc,
            model_coordinates=raw_model_null,
            comparison_status="COORDINATES_DISAGREE",
            coordinates_disagree=True,
        )

        # Confirm model_coordinates is NOT equal to document_coordinates
        self.assertNotEqual(loc.model_coordinates.latitude, loc.document_coordinates.latitude)
        self.assertEqual(loc.model_coordinates.latitude, 0.0)
        self.assertFalse(loc.model_coordinates.is_valid)
        self.assertTrue(loc.document_coordinates.is_valid)


if __name__ == "__main__":
    unittest.main()
