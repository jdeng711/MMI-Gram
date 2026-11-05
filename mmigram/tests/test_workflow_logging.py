"""
Tests for Workflow Execution and Structured Agent Logging.
Verifies that:
  1. Every agent node emits structured logs with inputs and outputs.
  2. Router decisions are explicitly logged.
  3. The full workflow executes deterministically on the StEER page 1 fixture.
"""

import json
import unittest
from pathlib import Path
from server.mmigram.telemetry.tracer import StructuredAgentLogger, summarize_state
from server.mmigram.workflow.graph import MMIGramWorkflow
from server.mmigram.review.queue import HumanReviewQueue


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "steer_page1_baseline.json"


class TestWorkflowLogging(unittest.TestCase):

    def setUp(self):
        with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
            self.fixture = json.load(f)
        self.logger = StructuredAgentLogger(name="test_logger", console_output=False)
        self.queue = HumanReviewQueue()
        self.workflow = MMIGramWorkflow(
            logger=self.logger,
            review_queue=self.queue,
            offline_fixture=self.fixture,
        )

    def test_state_summarizer(self):
        large_state = {
            "blob_name": "test_page1.pdf",
            "file_bytes": b"x" * 10000,
            "long_text": "A" * 500,
            "mmi_documents": [1, 2, 3, 4],
        }
        summary = summarize_state(large_state, max_len=50)

        self.assertEqual(summary["blob_name"], "test_page1.pdf")
        self.assertEqual(summary["file_bytes"], "<binary_data_omitted>")
        self.assertIn("truncated", summary["long_text"])
        self.assertEqual(summary["mmi_documents"], "<List of 4 reference documents>")

    def test_end_to_end_workflow_execution_and_event_logging(self):
        inputs = {
            "blob_name": "test_page1.pdf",
            "signed_url": "https://storage.googleapis.com/test_bucket/test_page1.pdf",
            "mime_type": "application/pdf",
            "raw_location_string": "Sagaing city, 21 52' 49.27\" N, 95 59' 5.57\" E",
        }

        result = self.workflow.run(inputs)

        # 1. Verify output values match legacy baseline
        self.assertEqual(result["final_analysis"]["mmi_estimation"], 9.0)
        self.assertEqual(result["final_analysis"]["confidence"], 0.90)

        # 2. Verify coordinates parsed and validated
        coords = result["location"]["coordinates"]
        self.assertTrue(coords["is_valid"])
        self.assertAlmostEqual(coords["latitude"], 21.880353, places=4)
        self.assertAlmostEqual(coords["longitude"], 95.984881, places=4)

        # 3. Verify QC and Review Queue interception
        self.assertEqual(result["qc"]["qc_status"], "FLAGGED")
        self.assertTrue(result["review"]["review_required"])
        self.assertEqual(len(self.queue.get_pending()), 1)

        # 4. Verify structured logs captured all nodes
        events = self.logger.get_events()
        self.assertGreater(len(events), 10)

        agent_names = [e.agent_name for e in events]
        self.assertIn("initial_analysis", agent_names)
        self.assertIn("retrieve_docs", agent_names)
        self.assertIn("grade_documents", agent_names)
        self.assertIn("final_analysis", agent_names)
        self.assertIn("validate_geolocation", agent_names)
        self.assertIn("evaluate_qc", agent_names)
        self.assertIn("human_review_gate", agent_names)

        # Verify enter and exit events exist
        enter_events = [e for e in events if e.event_type == "NODE_ENTER"]
        exit_events = [e for e in events if e.event_type == "NODE_EXIT"]
        self.assertEqual(len(enter_events), len(exit_events))

        # Check router event was logged
        router_events = [e for e in events if e.event_type == "ROUTER_DECISION"]
        self.assertGreaterEqual(len(router_events), 1)
        self.assertEqual(router_events[0].outputs["next_node"], "final_analysis")


if __name__ == "__main__":
    unittest.main()
