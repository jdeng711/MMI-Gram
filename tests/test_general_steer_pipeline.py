"""
Unit and Integration Tests for General-Purpose StEER Pipeline.

Verifies:
  1. Execution on authentic StEER report (server/test_page1.pdf - Sagaing MMI 9.0).
  2. Execution on second synthetic fixture (synthetic_steer_page2_mandalay.pdf - Mandalay MMI 8.0).
  3. Handling of documents with no coordinates (synthetic_steer_page3_no_coords.pdf).
  4. Strict offline behavior: unregistered PDFs return FIXTURE_NOT_FOUND rather than synthesizing fake MMI.
  5. Image-only/scanned PDF detection (IMAGE_BASED_PDF_NO_TEXT).
  6. Corrupt PDF error handling (INVALID_PDF).
  7. Live mode protection (PermissionError without explicit approval).
"""

import json
import unittest
from pathlib import Path

from mmigram.workflow.general_steer_pipeline import GeneralSteerPipeline
from mmigram.review.queue import HumanReviewQueue
from mmigram.telemetry.tracer import StructuredAgentLogger
from mmigram.qc.rules import FLAG_HIGH_INTENSITY_ANOMALY, FLAG_INVALID_COORDINATES


FIXTURES_DIR = Path(__file__).parent / "fixtures"

def find_real_steer_page1() -> Path:
    candidates = [
        Path(__file__).parents[1] / "data" / "events" / "us7000pn9s" / "inbound" / "test_page1.pdf",
        Path(__file__).parents[1] / "server" / "test_page1.pdf",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]

REAL_STEER_PAGE1 = find_real_steer_page1()


class TestGeneralSteerPipeline(unittest.TestCase):

    def setUp(self):
        self.logger = StructuredAgentLogger(name="test.general_steer", console_output=False)
        self.review_queue = HumanReviewQueue()
        self.pipeline = GeneralSteerPipeline(
            mode="offline",
            fixtures_dir=FIXTURES_DIR,
            logger=self.logger,
            review_queue=self.review_queue,
            allow_live_api=False,
        )

    def test_authentic_steer_page1_execution(self):
        """
        Verify execution on real authentic StEER document (server/test_page1.pdf).
        Extracts Sagaing coordinates dynamically and verifies MMI 9.0 recorded baseline.
        """
        self.assertTrue(REAL_STEER_PAGE1.exists(), f"Missing {REAL_STEER_PAGE1}")

        result = self.pipeline.process_pdf(REAL_STEER_PAGE1)

        # 1. Provenance check
        self.assertFalse(result["provenance"]["is_synthetic"])
        self.assertEqual(result["provenance"]["baseline_type"], "RECORDED_LEGACY_OUTPUT")

        # 2. Document extraction
        doc = result["document_extraction"]
        self.assertEqual(doc["extraction_status"], "SUCCESS")
        self.assertTrue(doc["has_extractable_text"])

        # 3. Dynamic coordinate extraction from PDF text
        coords = result["geographic_resolution"]["coordinates"]
        self.assertIsNotNone(coords)
        self.assertAlmostEqual(coords["latitude"], 21.880353, places=4)
        self.assertAlmostEqual(coords["longitude"], 95.984881, places=4)
        self.assertTrue(coords["is_valid"])
        # Protocol: Text-extracted coordinates are candidate, not independently verified
        self.assertFalse(coords["is_authoritative"])

        # 4. Model output check
        seis = result["seismic_intensity"]
        self.assertEqual(seis["mmi_estimation"], 9.0)
        self.assertEqual(seis["confidence"], 0.90)

        # 5. QC and Human Review check
        qc = result["quality_control"]
        self.assertEqual(qc["status"], "FLAGGED")
        self.assertIn(FLAG_HIGH_INTENSITY_ANOMALY, qc["flags"])
        self.assertTrue(result["human_in_the_loop"]["review_required"])

    def test_second_synthetic_steer_fixture_mandalay(self):
        """
        Verify execution on second fixture (synthetic_steer_page2_mandalay.pdf).
        Verifies dynamic coordinates parse to Mandalay (~21.978 N, ~96.088 E), NOT Sagaing!
        """
        pdf_path = FIXTURES_DIR / "synthetic_steer_page2_mandalay.pdf"
        self.assertTrue(pdf_path.exists())

        result = self.pipeline.process_pdf(pdf_path)

        # 1. Provenance check (must be explicitly marked synthetic)
        self.assertTrue(result["provenance"]["is_synthetic"])
        self.assertEqual(result["provenance"]["baseline_type"], "MOCKED_TEST_DATA")

        # 2. Dynamic coordinate extraction (Mandalay locus)
        coords = result["geographic_resolution"]["coordinates"]
        self.assertIsNotNone(coords)
        self.assertAlmostEqual(coords["latitude"], 21.978361, places=4)
        self.assertAlmostEqual(coords["longitude"], 96.088972, places=4)
        self.assertFalse(coords["is_authoritative"])

        # 3. MMI estimation check (Mandalay MMI 8.0)
        seis = result["seismic_intensity"]
        self.assertEqual(seis["mmi_estimation"], 8.0)
        self.assertEqual(seis["confidence"], 0.85)

    def test_no_coordinates_pdf_handling(self):
        """
        Verify that a PDF without coordinates keeps them strictly null/unknown
        rather than inventing or assuming a location.
        """
        pdf_path = FIXTURES_DIR / "synthetic_steer_page3_no_coords.pdf"
        self.assertTrue(pdf_path.exists())

        result = self.pipeline.process_pdf(pdf_path)

        coords = result["geographic_resolution"]["coordinates"]
        self.assertIsNone(coords)
        self.assertFalse(result["geographic_resolution"]["has_valid_coordinates"])

        # QC must reject observation due to missing coordinates
        qc = result["quality_control"]
        self.assertEqual(qc["status"], "REJECTED")
        self.assertIn(FLAG_INVALID_COORDINATES, qc["flags"])
        self.assertTrue(result["human_in_the_loop"]["review_required"])

    def test_strict_offline_mode_rejects_unregistered_pdf(self):
        """
        STRICT REQUIREMENT: Unregistered PDFs in offline mode must return FIXTURE_NOT_FOUND.
        The pipeline must NOT synthesize or fabricate fake MMI estimates from PDF text.
        """
        # Create a temporary unrecorded PDF file
        temp_pdf = FIXTURES_DIR / "unregistered_new_earthquake.pdf"
        from tests.generate_fixtures import create_minimal_pdf
        create_minimal_pdf(["Unrecorded earthquake report in Taunggyi", "No fixture exists."], temp_pdf)

        try:
            result = self.pipeline.process_pdf(temp_pdf)
            self.assertEqual(result["pipeline_status"], "FIXTURE_NOT_FOUND")
            self.assertIn("No offline recorded CRAG fixture found", result["message"])
            self.assertNotIn("seismic_intensity", result)
        finally:
            if temp_pdf.exists():
                temp_pdf.unlink()

    def test_image_only_scanned_pdf_detection(self):
        """
        Verify that image-based PDFs without text layers are detected as IMAGE_BASED_PDF_NO_TEXT.
        """
        pdf_path = FIXTURES_DIR / "synthetic_image_only_scanned.pdf"
        self.assertTrue(pdf_path.exists())

        result = self.pipeline.process_pdf(pdf_path)
        self.assertEqual(result["extraction_status"], "IMAGE_BASED_PDF_NO_TEXT")
        self.assertFalse(result["has_extractable_text"])
        self.assertEqual(result["pipeline_status"], "FIXTURE_NOT_FOUND")

    def test_corrupt_pdf_handling(self):
        """
        Verify that invalid or corrupt non-PDF files return INVALID_PDF status gracefully.
        """
        pdf_path = FIXTURES_DIR / "synthetic_corrupt.pdf"
        self.assertTrue(pdf_path.exists())

        result = self.pipeline.process_pdf(pdf_path)
        self.assertEqual(result["pipeline_status"], "INVALID_PDF")
        self.assertEqual(result["extraction_status"], "CORRUPTED_PDF")

    def test_live_mode_blocked_without_permission(self):
        """
        Verify that attempting to execute live mode without allow_live_api=True
        raises PermissionError.
        """
        live_pipeline = GeneralSteerPipeline(
            mode="live",
            allow_live_api=False,  # Unapproved
        )
        with self.assertRaises(PermissionError):
            live_pipeline.process_pdf(REAL_STEER_PAGE1)

    def test_pipeline_handles_missing_or_malformed_mmi_without_fabrication(self):
        """
        Verify that missing, null, or malformed MMI values from model output
        remain strictly None/unestimated and are NOT fabricated as 5.0.
        """
        import tempfile
        from tests.generate_fixtures import create_minimal_pdf
        from mmigram.qc.rules import FLAG_UNESTIMATED_INTENSITY

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_dir = Path(tmpdir)
            temp_pdf = temp_dir / "synthetic_missing_mmi.pdf"
            temp_fixture_json = temp_dir / "synthetic_missing_mmi.json"

            create_minimal_pdf(["StEER Report with unparseable model response.", "Damage observations present."], temp_pdf)

            fixture_data = {
                "_metadata": {"is_synthetic": True, "baseline_type": "MOCKED_TEST_DATA"},
                "observed_mocked_output": {
                    "mmi_estimation": None,       # Missing/null MMI
                    "confidence": None,
                    "reasoning": "Model failed to extract numeric intensity.",
                    "visual_observation": "Collapsed masonry wall and cracks.",
                }
            }
            with open(temp_fixture_json, "w", encoding="utf-8") as f:
                json.dump(fixture_data, f)

            test_pipeline = GeneralSteerPipeline(mode="offline", fixtures_dir=temp_dir)
            test_pipeline.fixture_registry["synthetic_missing_mmi.pdf"] = "synthetic_missing_mmi.json"

            result = test_pipeline.process_pdf(temp_pdf)

            # Assert NO fabricated 5.0 fallback
            self.assertIsNone(result["seismic_intensity"]["mmi_estimation"])
            self.assertIsNone(result["seismic_intensity"]["confidence"])
            self.assertEqual(result["quality_control"]["status"], "REJECTED")
            self.assertIn(FLAG_UNESTIMATED_INTENSITY, result["quality_control"]["flags"])
            self.assertTrue(result["human_in_the_loop"]["review_required"])
            self.assertTrue(any("requires human expert estimation" in t for t in result["human_in_the_loop"]["triggers"]))

    def test_pipeline_detects_coordinate_discrepancy_and_preserves_both(self):
        """
        Verify that when document text and model output disagree on coordinates,
        both are preserved separately and flagged for human review.
        """
        import tempfile
        from tests.generate_fixtures import create_minimal_pdf
        from mmigram.qc.rules import FLAG_COORDINATE_DISCREPANCY

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_dir = Path(tmpdir)
            temp_pdf = temp_dir / "synthetic_coord_discrepancy.pdf"
            temp_fixture_json = temp_dir / "synthetic_coord_discrepancy.json"

            # Document text has Sagaing coordinates
            create_minimal_pdf([
                "Field Inspection: Sagaing Region.",
                "Coordinates: 21°52'49.3\"N, 95°59'05.6\"E.",
                "Extensive collapse of URM structures.",
            ], temp_pdf)

            # Model outputs Naypyidaw coordinates (>200 km away)
            fixture_data = {
                "_metadata": {"is_synthetic": True, "baseline_type": "MOCKED_TEST_DATA"},
                "observed_mocked_output": {
                    "mmi_estimation": 8.0,
                    "confidence": 0.85,
                    "location": {
                        "address": "Naypyidaw",
                        "coordinates": [19.7633, 96.0785],  # Discrepant model output
                    },
                    "visual_observation": "Heavy damage to brick structures.",
                }
            }
            with open(temp_fixture_json, "w", encoding="utf-8") as f:
                json.dump(fixture_data, f)

            test_pipeline = GeneralSteerPipeline(mode="offline", fixtures_dir=temp_dir)
            test_pipeline.fixture_registry["synthetic_coord_discrepancy.pdf"] = "synthetic_coord_discrepancy.json"

            result = test_pipeline.process_pdf(temp_pdf)
            geo = result["geographic_resolution"]

            # Both coordinates preserved separately
            self.assertIsNotNone(geo["document_coordinates"])
            self.assertAlmostEqual(geo["document_coordinates"]["latitude"], 21.880353, places=3)
            self.assertIsNotNone(geo["model_coordinates"])
            self.assertAlmostEqual(geo["model_coordinates"]["latitude"], 19.7633, places=3)

            # Discrepancy detected and flagged
            self.assertTrue(geo["coordinates_disagree"])
            self.assertGreater(geo["discrepancy_distance_km"], 200.0)
            self.assertIn(FLAG_COORDINATE_DISCREPANCY, result["quality_control"]["flags"])
            self.assertTrue(result["human_in_the_loop"]["review_required"])
            self.assertTrue(any("Coordinate discrepancy" in t for t in result["human_in_the_loop"]["triggers"]))

            # Neither coordinate treated as authoritative ground truth
            self.assertFalse(geo["document_coordinates"]["is_authoritative"])
            self.assertFalse(geo["model_coordinates"]["is_authoritative"])


if __name__ == "__main__":
    unittest.main()
