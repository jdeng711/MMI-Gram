"""
End-to-End Offline Integration Tests for MMI-Gram StEER Pipeline.

Verifies:
  1. Full offline LangGraph pipeline execution on StEER Page 1.
  2. Null Island (0,0) detection in Stage 2.
  3. Geolocation resolution to candidate Sagaing coordinates in Stage 3 without automatic ground-truth promotion.
  4. High intensity (MMI 9.0) treated as requiring review rather than an error in Stage 4.
  5. Human review queue routing without automatic approval in Stage 5.
  6. Expert override and review provenance tracking.
  7. Exported Mermaid diagram integrity.
"""

import unittest
from pathlib import Path
from mmigram.workflow.steer_offline_pipeline import (
    SteerOfflinePipeline,
    get_steer_pipeline_mermaid,
)
from mmigram.review.queue import HumanReviewQueue
from mmigram.telemetry.tracer import StructuredAgentLogger
from mmigram.qc.rules import FLAG_NULL_ISLAND, FLAG_HIGH_INTENSITY_ANOMALY


class TestSteerOfflinePipeline(unittest.TestCase):

    def setUp(self):
        self.logger = StructuredAgentLogger(name="test.steer_pipeline", console_output=False)
        self.review_queue = HumanReviewQueue()
        self.pipeline = SteerOfflinePipeline(
            logger=self.logger,
            review_queue=self.review_queue,
        )

    def test_end_to_end_pipeline_execution(self):
        final_state = self.pipeline.execute()
        summary = final_state["structured_summary"]

        # 1. Pipeline status
        self.assertEqual(summary["final_pipeline_decision"], "HELD_IN_HUMAN_REVIEW_QUEUE")
        self.assertEqual(summary["observation_id"], "test_page1.pdf")

        # 2. Stage 1 Baseline check
        self.assertEqual(summary["seismic_intensity"]["mmi_estimation"], 9.0)
        self.assertEqual(summary["seismic_intensity"]["confidence"], 0.90)
        self.assertFalse(summary["seismic_intensity"]["is_calibrated"])

        # 3. Stage 2 Initial QC check (Null Island rejection)
        stage_records = summary["stages_executed"]
        self.assertEqual(len(stage_records), 5)

        stage2 = next(s for s in stage_records if s["stage_number"] == 2)
        self.assertEqual(stage2["qc_status"], "REJECTED")
        self.assertIn(FLAG_NULL_ISLAND, stage2["qc_flags"])

        # 4. Stage 3 Geolocation resolution
        stage3 = next(s for s in stage_records if s["stage_number"] == 3)
        self.assertAlmostEqual(stage3["resolved_latitude"], 21.880353, places=4)
        self.assertAlmostEqual(stage3["resolved_longitude"], 95.984881, places=4)
        self.assertTrue(stage3["is_valid"])
        # CRITICAL REQUIREMENT: Must not treat extracted coords as independently verified ground truth
        self.assertFalse(stage3["is_authoritative"])

        # 5. Stage 4 Secondary QC check (High MMI treated as requiring review, not error)
        stage4 = next(s for s in stage_records if s["stage_number"] == 4)
        self.assertEqual(stage4["qc_status"], "FLAGGED")
        self.assertIn(FLAG_HIGH_INTENSITY_ANOMALY, stage4["qc_flags"])
        self.assertNotIn(FLAG_NULL_ISLAND, stage4["qc_flags"])  # Null Island resolved

        # 6. Stage 5 Human Review Routing (Not auto-approved)
        stage5 = next(s for s in stage_records if s["stage_number"] == 5)
        self.assertEqual(stage5["status"], "QUEUED_FOR_EXPERT_REVIEW")
        self.assertEqual(len(self.review_queue.get_pending()), 1)

        review_info = summary["human_in_the_loop"]
        self.assertTrue(review_info["review_required"])
        self.assertEqual(review_info["review_status"], "UNREVIEWED")

    def test_expert_intervention_workflow(self):
        """
        Verify that a queued observation can be audited and overridden by an expert
        without breaking provenance.
        """
        final_state = self.pipeline.execute()
        blob_name = final_state["structured_summary"]["observation_id"]

        # Expert reviews the observation
        item = self.review_queue.get_item(blob_name)
        self.assertIsNotNone(item)
        self.assertEqual(item.status, "UNREVIEWED")

        # Expert calibrates MMI down from AI estimate 9.0 to 8.0 based on masonry failure criteria
        overridden = self.review_queue.override_mmi(
            item_id=blob_name,
            reviewer_id="seismologist_steer_lead",
            new_mmi=8.0,
            notes="Calibrated from 9.0 to 8.0. Unreinforced masonry failure corresponds to severe shaking, not violent ground displacement.",
        )

        self.assertEqual(overridden.status, "OVERRIDDEN")
        self.assertEqual(overridden.overridden_mmi, 8.0)
        self.assertEqual(overridden.reviewer_id, "seismologist_steer_lead")
        self.assertIsNotNone(overridden.reviewed_at_utc)
        self.assertEqual(len(self.review_queue.get_pending()), 0)

    def test_mermaid_diagram_export(self):
        mermaid = get_steer_pipeline_mermaid()
        self.assertIsInstance(mermaid, str)
        self.assertIn("MMI-Gram StEER Offline LangGraph Pipeline", mermaid)
        self.assertIn("Agent 1: load_observation_baseline", mermaid)
        self.assertIn("Agent 2: initial_qc_check", mermaid)
        self.assertIn("Agent 3: resolve_geolocation", mermaid)
        self.assertIn("Agent 4: secondary_qc_check", mermaid)
        self.assertIn("Agent 5: route_to_human_review", mermaid)
        self.assertIn("Planned Future Capabilities", mermaid)


if __name__ == "__main__":
    unittest.main()
