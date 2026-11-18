"""
Offline Regression Test Suite for Stage 2:
Pre-MMI Input Relevance Screening, Quality Control, and Evidence Filtering.

Covers all required offline regression tests and scientific robustness specifications:
  1. Relevant structural-damage photos (test_page1.pdf -> ESTIMABLE)
  2. Relevant text-only shaking descriptions (no images, detailed macroseismic text -> ESTIMABLE)
  3. Irrelevant title or intro slides (TOC, team roster -> NOT_ESTIMABLE)
  4. Clara's page-8 hazard model map (synthetic fixture & local authentic page-8 -> NOT_ESTIMABLE, mmi_estimation = null)
  5. Unrelated photographs (scenic view / team dinner -> NOT_ESTIMABLE)
  6. Missing timestamps (TIMESTAMP_MISSING -> accepted as valid, no rejection)
  7. Conflicting observation timestamps (predates event origin T0 by >5 min -> PREDATES_EVENT, flagged)
  8. Exact duplicate files (SHA-256 match -> EXACT_DUPLICATE, flagged)
  9. Near-duplicate images (dHash Hamming distance <= 4 -> NEAR_DUPLICATE, flagged)
  10. Ambiguous authenticity classifications (AI generator tags -> SUSPICIOUS_AI_GENERATED, queued for review, not deleted)
  11. Missing coordinates (preserved as null / unknown, spatial gate does NOT substitute epicenter)
  12. Proper QC and human-review routing for flagged / rejected items
  13. Strict enforcement that mmi_estimation is null (None), NEVER 0.0, for NOT_ESTIMABLE
  14. Zero model inference / token usage when relevance screening blocks an input
  15. Preservation of existing AI Studio and Vertex AI providers
  16. Image-only / scanned PDF evidence: returns REVIEW_REQUIRED, NOT rejected as NOT_ESTIMABLE
  17. Surface fault rupture alone: evaluated as REVIEW_REQUIRED, preserving displacement uncertainty
  18. Building damage with fault rupture: evaluated as ESTIMABLE with explicit permanent displacement caution
  19. PDF compilation / creation date predating event: accepted as valid (PDF_METADATA_ONLY), not rejected
  20. Heuristic authenticity terminology: verifies NO_INDICATORS_DETECTED and strictly uncalibrated scoring
"""

import os
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image

from mmigram.screening.relevance_gate import RelevanceGate, RelevanceDecision
from mmigram.screening.temporal_gate import TemporalGate, TemporalCheckResult
from mmigram.screening.recycled_gate import RecycledMediaGate, DuplicateCheckResult, compute_dhash, hamming_distance
from mmigram.screening.authenticity_gate import AuthenticityGate, AuthenticityCheckResult
from mmigram.screening.spatial_gate import SpatialGate, SpatialCheckResult
from mmigram.screening.composite_screener import CompositeScreener, ScreeningResult
from mmigram.workflow.general_steer_pipeline import GeneralSteerPipeline
from mmigram.review.queue import HumanReviewQueue
from mmigram.core.state import Coordinates


FIXTURES_DIR = Path(__file__).parent / "fixtures"
SYNTHETIC_PAGE8_PATH = FIXTURES_DIR / "synthetic_page8_hazard_map.pdf"

def find_authentic_page8() -> Path:
    candidates = [
        FIXTURES_DIR / "page-8.pdf",
        Path(__file__).parents[1] / "data" / "events" / "us7000pn9s" / "inbound" / "page-8.pdf",
        Path(__file__).parents[2] / "2026_Macroseismic_AI_Myanmar" / "pages" / "page-8.pdf",
    ]
    for c in candidates:
        if c.exists():
            return c
    return SYNTHETIC_PAGE8_PATH

AUTHENTIC_PAGE8_PATH = find_authentic_page8()

def find_test_page1() -> Path:
    candidates = [
        Path(__file__).parents[1] / "data" / "events" / "us7000pn9s" / "inbound" / "test_page1.pdf",
        Path(__file__).parents[1] / "server" / "test_page1.pdf",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]

TEST_PAGE1_PATH = find_test_page1()


class TestScreeningGates(unittest.TestCase):
    """Comprehensive offline regression test suite for Stage 2 screening gates."""

    def setUp(self):
        self.relevance_gate = RelevanceGate(allow_live_api=False)
        self.temporal_gate = TemporalGate(origin_time_utc="2025-03-28T06:20:00Z")
        self.recycled_gate = RecycledMediaGate()
        self.authenticity_gate = AuthenticityGate(allow_live_api=False)
        self.spatial_gate = SpatialGate()
        self.composite_screener = CompositeScreener(
            event_id="us7000pn9s",
            origin_time_utc="2025-03-28T06:20:00Z",
            allow_live_api=False,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Test 1: Relevant Structural-Damage Photos (test_page1.pdf -> ESTIMABLE)
    # ──────────────────────────────────────────────────────────────────────────
    def test_01_relevant_structural_damage_photos(self):
        """Verify authentic damage report evaluates to ESTIMABLE with positive damage evidence."""
        self.assertTrue(TEST_PAGE1_PATH.exists(), f"Missing {TEST_PAGE1_PATH}")
        from mmigram.ingestion.pdf_extractor import PDFExtractor

        ext = PDFExtractor().extract(TEST_PAGE1_PATH)
        self.assertTrue(ext.has_extractable_text)

        dec = self.relevance_gate.evaluate(
            file_path=TEST_PAGE1_PATH,
            extracted_text=ext.extracted_text,
            has_extractable_text=ext.has_extractable_text,
            page_count=ext.page_count,
            image_count=2,
        )
        self.assertEqual(dec.decision, "ESTIMABLE")
        self.assertTrue(dec.is_estimable)
        self.assertIn("structural_damage_observation", dec.evidence_types)
        self.assertGreater(len(dec.reasons), 0)

    # ──────────────────────────────────────────────────────────────────────────
    # Test 2: Relevant Text-Only Shaking Descriptions (ESTIMABLE without images)
    # ──────────────────────────────────────────────────────────────────────────
    def test_02_relevant_text_only_shaking_descriptions(self):
        """Verify macroseismic text descriptions are ESTIMABLE without requiring photographs."""
        text = (
            "Field eyewitness report from Pyin Oo Lwin: Severe ground shaking was felt by all residents. "
            "Heavy wardrobes and furniture overturned, dishes broken. Extensive cracking in unreinforced masonry walls, "
            "partial collapse of perimeter fence and chimney fallen. It was difficult to stand during the main shock."
        )
        dec = self.relevance_gate.evaluate(
            file_path="mock_text_report.pdf",
            extracted_text=text,
            has_extractable_text=True,
            page_count=1,
            image_count=0,  # Zero images! Pure text report
        )
        self.assertEqual(dec.decision, "ESTIMABLE")
        self.assertTrue(dec.is_estimable)
        self.assertIn("macroseismic_shaking_observation", dec.evidence_types)
        self.assertIn("structural_damage_observation", dec.evidence_types)
        self.assertNotIn("structural_damage_photo", dec.evidence_types)

    # ──────────────────────────────────────────────────────────────────────────
    # Test 3: Irrelevant Title or Intro Slides (NOT_ESTIMABLE)
    # ──────────────────────────────────────────────────────────────────────────
    def test_03_irrelevant_title_or_intro_slides(self):
        """Verify title slides, rosters, and table of contents evaluate to NOT_ESTIMABLE."""
        text = (
            "StEER: Building Resilience through Reconnaissance\n"
            "Preliminary Virtual Reconnaissance Report (PVRR)\n"
            "Table of Contents\n"
            "Author List and Team Organization\n"
            "VAST Member Names and Acknowledgments"
        )
        dec = self.relevance_gate.evaluate(
            file_path="steer_title_page.pdf",
            extracted_text=text,
            has_extractable_text=True,
            page_count=1,
            image_count=1,  # Organizational logos
        )
        self.assertEqual(dec.decision, "NOT_ESTIMABLE")
        self.assertFalse(dec.is_estimable)
        self.assertIn("title_presentation_slide", dec.evidence_types)
        self.assertTrue(any("title slide" in r.lower() or "table of contents" in r.lower() for r in dec.reasons))

    # ──────────────────────────────────────────────────────────────────────────
    # Test 4: Clara's page-8 Hazard Model Map Example (NOT_ESTIMABLE, mmi = null)
    # ──────────────────────────────────────────────────────────────────────────
    def test_04_clara_page8_example_not_estimable(self):
        """Verify Clara's page-8 hazard model map evaluates to NOT_ESTIMABLE with null intensity."""
        self.assertTrue(SYNTHETIC_PAGE8_PATH.exists(), f"Missing {SYNTHETIC_PAGE8_PATH}")
        pipeline = GeneralSteerPipeline(mode="offline")
        result = pipeline.process_pdf(SYNTHETIC_PAGE8_PATH)

        # 1. Pipeline status
        self.assertEqual(result["pipeline_status"], "NOT_ESTIMABLE")

        # 2. Seismic intensity strictly null
        self.assertIsNone(result["seismic_intensity"]["mmi_estimation"])
        self.assertIsNone(result["seismic_intensity"]["confidence"])
        self.assertFalse(result["seismic_intensity"]["is_calibrated"])

        # 3. Provenance and zero token usage
        self.assertIsNone(result["provenance"]["mmi_result"])
        self.assertEqual(result["provenance"]["baseline_type"], "SCREENED_NOT_ESTIMABLE")
        self.assertEqual(result["provenance"]["token_usage"]["calls"], 0)
        self.assertEqual(result["provenance"]["token_usage"]["total_tokens"], 0)

        # 4. Screening record
        scr = result["screening"]
        self.assertEqual(scr["relevance_decision"], "NOT_ESTIMABLE")
        self.assertFalse(scr["is_estimable"])
        self.assertIn("regional_hazard_model_map", scr["evidence_types"])
        self.assertTrue(any("regional hazard model or contour map" in r for r in scr["decision_reasons"]))

        # 5. Quality Control
        self.assertEqual(result["quality_control"]["status"], "SCREENED_OUT")
        self.assertIn("PRE_MMI_NOT_ESTIMABLE", result["quality_control"]["flags"])

        # Also verify authentic local page-8 if present
        if AUTHENTIC_PAGE8_PATH.exists() and AUTHENTIC_PAGE8_PATH != SYNTHETIC_PAGE8_PATH:
            res_auth = pipeline.process_pdf(AUTHENTIC_PAGE8_PATH)
            self.assertEqual(res_auth["pipeline_status"], "NOT_ESTIMABLE")
            self.assertIsNone(res_auth["seismic_intensity"]["mmi_estimation"])

    # ──────────────────────────────────────────────────────────────────────────
    # Test 5: Unrelated Photographs (NOT_ESTIMABLE)
    # ──────────────────────────────────────────────────────────────────────────
    def test_05_unrelated_photographs_scenic_team_dinner(self):
        """Verify documents with unrelated non-earthquake photos are NOT_ESTIMABLE."""
        text = (
            "Field team dinner in downtown Yangon. Enjoying traditional cuisine and sunset "
            "views over Kandawgyi Lake. Team group photo taken after dinner."
        )
        dec = self.relevance_gate.evaluate(
            file_path="team_dinner.pdf",
            extracted_text=text,
            has_extractable_text=True,
            page_count=1,
            image_count=3,
        )
        self.assertEqual(dec.decision, "NOT_ESTIMABLE")
        self.assertFalse(dec.is_estimable)
        self.assertIn("unrelated_non_seismic_content", dec.evidence_types)

    # ──────────────────────────────────────────────────────────────────────────
    # Test 6: Missing Timestamps (TIMESTAMP_MISSING -> accepted as valid)
    # ──────────────────────────────────────────────────────────────────────────
    def test_06_missing_timestamps_accepted_as_valid(self):
        """Verify missing timestamps are accepted as valid without rejecting the observation."""
        res = self.temporal_gate.check(
            file_path="no_date_doc.pdf",
            extracted_text="Damage observed at site without timestamp information.",
        )
        self.assertTrue(res.is_valid)
        self.assertEqual(res.status, "TIMESTAMP_MISSING")
        self.assertEqual(res.timestamp_source, "none")
        self.assertIn("accepted as valid", res.reason)

    # ──────────────────────────────────────────────────────────────────────────
    # Test 7: Conflicting Observation Timestamps (PREDATES_EVENT -> flagged)
    # ──────────────────────────────────────────────────────────────────────────
    def test_07_conflicting_timestamps_predating_event_flagged(self):
        """Verify observations with reliable timestamps predating T0 by >5 minutes are flagged."""
        # Event T0 is 2025-03-28T06:20:00Z. A report from 2025-03-27 is a contradiction.
        text = "Photograph taken on 2025-03-27 14:00:00 UTC showing structural damage."
        res = self.temporal_gate.check(
            file_path="predating_doc.pdf",
            extracted_text=text,
        )
        self.assertFalse(res.is_valid)
        self.assertEqual(res.status, "PREDATES_EVENT")
        self.assertEqual(res.timestamp_source, "reported_observation")
        self.assertTrue(res.is_observation_time)
        self.assertIn("predates earthquake origin", res.reason)

    # ──────────────────────────────────────────────────────────────────────────
    # Test 8: Exact Duplicate Files (SHA-256 Match -> EXACT_DUPLICATE)
    # ──────────────────────────────────────────────────────────────────────────
    def test_08_exact_duplicate_files_sha256(self):
        """Verify exact identical files are flagged as EXACT_DUPLICATE and not silently deleted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_a = Path(tmpdir) / "obs_a.pdf"
            file_b = Path(tmpdir) / "obs_b.pdf"
            data = b"%PDF-1.4 test duplicate content for sha256"
            file_a.write_bytes(data)
            file_b.write_bytes(data)

            res_a = self.recycled_gate.check(file_a)
            self.assertTrue(res_a.is_unique)
            self.assertEqual(res_a.status, "UNIQUE")

            res_b = self.recycled_gate.check(file_b)
            self.assertFalse(res_b.is_unique)
            self.assertEqual(res_b.status, "EXACT_DUPLICATE")
            self.assertEqual(res_b.duplicate_of, "obs_a.pdf")
            self.assertEqual(res_b.sha256_hash, res_a.sha256_hash)

    # ──────────────────────────────────────────────────────────────────────────
    # Test 9: Near-Duplicate Images (dHash Hamming distance <= 4 -> NEAR_DUPLICATE)
    # ──────────────────────────────────────────────────────────────────────────
    def test_09_near_duplicate_images_perceptual_hash(self):
        """Verify perceptually similar images (Hamming distance <= 4) are flagged."""
        with tempfile.TemporaryDirectory() as tmpdir:
            img_a_path = Path(tmpdir) / "photo_a.jpg"
            img_b_path = Path(tmpdir) / "photo_b.jpg"

            # Create a base grayscale pattern image
            img_a = Image.new("L", (100, 100), color=128)
            for x in range(50):
                for y in range(100):
                    img_a.putpixel((x, y), 200)
            img_a.save(img_a_path)

            # Create slightly modified near-duplicate (1 pixel row changed)
            img_b = img_a.copy()
            for x in range(5):
                img_b.putpixel((x, 0), 205)
            img_b.save(img_b_path)

            hash_a = compute_dhash(img_a)
            hash_b = compute_dhash(img_b)
            dist = hamming_distance(hash_a, hash_b)
            self.assertLessEqual(dist, 4, f"Hamming distance {dist} > 4")

            gate = RecycledMediaGate()
            r_a = gate.check(img_a_path)
            self.assertTrue(r_a.is_unique)

            r_b = gate.check(img_b_path)
            self.assertFalse(r_b.is_unique)
            self.assertIn(r_b.status, ("EXACT_DUPLICATE", "NEAR_DUPLICATE"))
            self.assertEqual(r_b.duplicate_of, "photo_a.jpg")

    # ──────────────────────────────────────────────────────────────────────────
    # Test 10: Ambiguous Authenticity Classifications (SUSPICIOUS_AI_GENERATED)
    # ──────────────────────────────────────────────────────────────────────────
    def test_10_ambiguous_authenticity_ai_tags_queued_for_review(self):
        """Verify media with AI generation tags are flagged for review and NOT deleted."""
        text = (
            "Damage photo generated with Midjourney v6: photorealistic 8k render of destroyed buildings, "
            "hyperrealistic earthquake rubble, unreal engine 5."
        )
        res = self.authenticity_gate.check(
            file_path="ai_render.pdf",
            extracted_text=text,
        )
        self.assertFalse(res.is_authentic_candidate)
        self.assertEqual(res.status, "SUSPICIOUS_AI_GENERATED")
        self.assertEqual(res.suspicion_level, "high")
        self.assertFalse(res.is_calibrated)
        self.assertTrue(res.review_required)
        self.assertGreater(len(res.indicators_detected), 0)
        self.assertTrue(any("midjourney" in ind.lower() for ind in res.indicators_detected))

    # ──────────────────────────────────────────────────────────────────────────
    # Test 11: Missing Coordinates Preserved as Null (No Hypocenter Substitution)
    # ──────────────────────────────────────────────────────────────────────────
    def test_11_missing_coordinates_preserved_as_null(self):
        """Verify missing coordinates remain null and hypocenter is NEVER substituted."""
        res = self.spatial_gate.check(
            latitude=None,
            longitude=None,
            extracted_text="Damage observed in Pyawbwe township, coordinates unavailable.",
        )
        self.assertTrue(res.is_plausible)
        self.assertIsNone(res.latitude)
        self.assertIsNone(res.longitude)
        self.assertTrue(res.review_required)
        self.assertEqual(res.status, "COORDINATES_UNKNOWN")
        self.assertIn("Observation coordinates unknown; not substituted with epicenter", res.reason)
        self.assertIn("Pyawbwe", res.matched_townships)
        # Verify no fake substitution
        self.assertNotEqual(res.latitude, 21.88)
        self.assertNotEqual(res.latitude, 0.0)

    # ──────────────────────────────────────────────────────────────────────────
    # Test 12: Proper QC and Human-Review Routing
    # ──────────────────────────────────────────────────────────────────────────
    def test_12_proper_qc_and_human_review_routing(self):
        """Verify flagged or contradictory observations route to HumanReviewQueue."""
        pipeline = GeneralSteerPipeline(mode="offline")
        # test_page1.pdf has MMI 9.0 and text-extracted unauthoritative coordinates
        result = pipeline.process_pdf(TEST_PAGE1_PATH)

        self.assertTrue(result["human_in_the_loop"]["review_required"])
        self.assertEqual(result["human_in_the_loop"]["review_status"], "UNREVIEWED")
        triggers = result["human_in_the_loop"]["triggers"]
        self.assertTrue(any("High seismic intensity (MMI >= 9.0)" in t for t in triggers))

    # ──────────────────────────────────────────────────────────────────────────
    # Test 13: Strict MMI Null Enforcement (NEVER 0.0 for NOT_ESTIMABLE)
    # ──────────────────────────────────────────────────────────────────────────
    def test_13_strict_mmi_null_enforcement_never_zero(self):
        """Verify unestimable inputs strictly produce null/None, NEVER 0.0 or 0."""
        pipeline = GeneralSteerPipeline(mode="offline")
        result = pipeline.process_pdf(SYNTHETIC_PAGE8_PATH)

        mmi_val = result["seismic_intensity"]["mmi_estimation"]
        self.assertIsNone(mmi_val)
        # Physical scale violation guard: MMI is defined I to XII; 0.0 is unphysical
        self.assertNotEqual(mmi_val, 0.0)
        self.assertNotEqual(mmi_val, 0)
        self.assertNotEqual(mmi_val, "0.0")

    # ──────────────────────────────────────────────────────────────────────────
    # Test 14: Zero Model Inference / Token Usage on Screened-Out Inputs
    # ──────────────────────────────────────────────────────────────────────────
    def test_14_zero_token_usage_when_screening_blocks_input(self):
        """Verify 100% token savings ($0.00 spend) when relevance screening blocks input."""
        pipeline = GeneralSteerPipeline(mode="offline")
        result = pipeline.process_pdf(SYNTHETIC_PAGE8_PATH)

        tokens = result["provenance"]["token_usage"]
        self.assertEqual(tokens["calls"], 0)
        self.assertEqual(tokens["prompt_tokens"], 0)
        self.assertEqual(tokens["candidates_tokens"], 0)
        self.assertEqual(tokens["thoughts_tokens"], 0)
        self.assertEqual(tokens["total_tokens"], 0)

    # ──────────────────────────────────────────────────────────────────────────
    # Test 15: Preservation of Existing AI Studio and Vertex AI Providers
    # ──────────────────────────────────────────────────────────────────────────
    def test_15_provider_preservation_ai_studio_and_vertex(self):
        """Verify pipeline preserves provider selection and compatibility with screening."""
        pipeline_studio = GeneralSteerPipeline(mode="offline", provider="ai_studio")
        self.assertEqual(pipeline_studio.provider, "ai_studio")
        self.assertEqual(pipeline_studio.composite_screener.provider, "ai_studio")

        pipeline_vertex = GeneralSteerPipeline(mode="offline", provider="vertex_ai")
        self.assertEqual(pipeline_vertex.provider, "vertex_ai")
        self.assertEqual(pipeline_vertex.composite_screener.provider, "vertex_ai")

    # ──────────────────────────────────────────────────────────────────────────
    # Test 16: Image-Only / Scanned PDF Evidence -> REVIEW_REQUIRED (Never NOT_ESTIMABLE)
    # ──────────────────────────────────────────────────────────────────────────
    def test_16_image_only_scanned_pdf_returns_review_required(self):
        """Verify scanned or image-only PDFs with genuine damage are not discarded as NOT_ESTIMABLE."""
        dec = self.relevance_gate.evaluate(
            file_path="scanned_damage_photo.pdf",
            extracted_text="",
            has_extractable_text=False,
            page_count=1,
            image_count=1,
        )
        self.assertEqual(dec.decision, "REVIEW_REQUIRED")
        self.assertFalse(dec.is_estimable)
        self.assertIn("unverified_visual_evidence", dec.evidence_types)
        self.assertNotEqual(dec.decision, "NOT_ESTIMABLE")

    # ──────────────────────────────────────────────────────────────────────────
    # Test 17: Surface Fault Rupture Alone -> REVIEW_REQUIRED
    # ──────────────────────────────────────────────────────────────────────────
    def test_17_surface_fault_rupture_alone_is_review_required(self):
        """Verify ground fault rupture alone does not automatically produce an exact MMI estimate."""
        text = "Field survey along rural trace: Surface fault rupture observed with 1.2m lateral offset."
        dec = self.relevance_gate.evaluate(
            file_path="fault_trace.pdf",
            extracted_text=text,
            has_extractable_text=True,
            page_count=1,
            image_count=0,
        )
        self.assertEqual(dec.decision, "REVIEW_REQUIRED")
        self.assertFalse(dec.is_estimable)
        self.assertIn("ground_failure_observation", dec.evidence_types)
        self.assertTrue(any("Surface fault displacement alone cannot reliably constrain" in r for r in dec.reasons))

    # ──────────────────────────────────────────────────────────────────────────
    # Test 18: Building Damage with Fault Rupture -> ESTIMABLE with Caveat
    # ──────────────────────────────────────────────────────────────────────────
    def test_18_building_damage_with_fault_rupture_preserves_uncertainty(self):
        """Verify building damage with ground rupture is estimable but preserves displacement caution."""
        text = (
            "Field survey in Sagaing: Masonry school collapsed and columns buckled. "
            "Surface fault rupture and ground fissure observed adjacent to foundation."
        )
        dec = self.relevance_gate.evaluate(
            file_path="school_damage.pdf",
            extracted_text=text,
            has_extractable_text=True,
            page_count=1,
            image_count=1,
        )
        self.assertEqual(dec.decision, "ESTIMABLE")
        self.assertTrue(dec.is_estimable)
        self.assertIn("structural_damage_observation", dec.evidence_types)
        self.assertIn("ground_failure_observation", dec.evidence_types)
        self.assertTrue(any("permanent displacement rather than vibratory shaking alone" in r for r in dec.reasons))

    # ──────────────────────────────────────────────────────────────────────────
    # Test 19: PDF Template Creation Date Before Event -> Accepted as Valid
    # ──────────────────────────────────────────────────────────────────────────
    def test_19_pdf_template_creation_date_before_event_accepted_as_valid(self):
        """Verify PDF creation date predating event is accepted as template metadata, NOT rejected."""
        from tests.generate_fixtures import create_minimal_pdf
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "template_pdf.pdf"
            create_minimal_pdf(["Damage observations after earthquake."], pdf_path)

            res = self.temporal_gate.check(
                file_path=pdf_path,
                extracted_text="Damage observations after earthquake.",
            )
            # The PDF creation date or missing observation date must NOT reject the file
            self.assertTrue(res.is_valid)
            self.assertNotEqual(res.status, "PREDATES_EVENT")

    # ──────────────────────────────────────────────────────────────────────────
    # Test 20: Heuristic Authenticity Terminology & Calibration Guard
    # ──────────────────────────────────────────────────────────────────────────
    def test_20_authenticity_terminology_no_indicators_detected(self):
        """Verify non-suspicious media is labeled NO_INDICATORS_DETECTED and strictly uncalibrated."""
        res = self.authenticity_gate.check(
            file_path="normal_photo.jpg",
            extracted_text="Photographic survey of cracked residential wall.",
        )
        self.assertEqual(res.status, "NO_INDICATORS_DETECTED")
        self.assertTrue(res.is_authentic_candidate)
        self.assertEqual(res.suspicion_level, "none")
        self.assertFalse(res.is_calibrated)
        self.assertFalse(res.review_required)
        self.assertIn("uncalibrated heuristic", res.reason)


if __name__ == "__main__":
    unittest.main()
