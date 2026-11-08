"""
Tests for Human-in-the-Loop (HITL) Review Queue and Overrides.
"""

import unittest
from mmigram.review.queue import HumanReviewQueue
from mmigram.core.state import Coordinates, MMIEstimationResult, QualityControlRecord


class TestHumanReviewQueue(unittest.TestCase):

    def setUp(self):
        self.queue = HumanReviewQueue()

    def test_auto_enqueue_on_high_intensity(self):
        state = {
            "estimation": {"mmi_value": 9.0, "confidence": 0.90},
            "qc": {"qc_flags": ["HIGH_INTENSITY_ANOMALY"]},
        }
        item = self.queue.check_and_enqueue("obs-001", state)

        self.assertIsNotNone(item)
        self.assertEqual(item.status, "UNREVIEWED")
        self.assertTrue(any("High seismic intensity" in t for t in item.triggers))
        self.assertEqual(len(self.queue.get_pending()), 1)

    def test_auto_enqueue_on_low_confidence(self):
        state = {
            "estimation": {"mmi_value": 5.5, "confidence": 0.55},
            "qc": {"qc_flags": ["LOW_CONFIDENCE"]},
        }
        item = self.queue.check_and_enqueue("obs-002", state)

        self.assertIsNotNone(item)
        self.assertEqual(item.status, "UNREVIEWED")

    def test_approve_item(self):
        state = {"estimation": {"mmi_value": 8.0, "confidence": 0.85}}
        self.queue.check_and_enqueue("obs-003", state, force=True)

        approved = self.queue.approve("obs-003", reviewer_id="dr_seismo", notes="Confirmed URM damage.")
        self.assertEqual(approved.status, "APPROVED")
        self.assertEqual(approved.reviewer_id, "dr_seismo")
        self.assertEqual(len(self.queue.get_pending()), 0)

    def test_reject_item(self):
        state = {"estimation": {"mmi_value": 4.0, "confidence": 0.40}}
        self.queue.check_and_enqueue("obs-004", state, force=True)

        rejected = self.queue.reject("obs-004", reviewer_id="dr_seismo", reason="Irrelevant non-earthquake photo.")
        self.assertEqual(rejected.status, "REJECTED")
        self.assertEqual(len(self.queue.get_pending()), 0)

    def test_override_mmi(self):
        state = {"estimation": {"mmi_value": 9.0, "confidence": 0.90}}
        self.queue.check_and_enqueue("obs-005", state, force=True)

        overridden = self.queue.override_mmi(
            "obs-005", reviewer_id="dr_seismo", new_mmi=7.5, notes="Downgraded due to poor masonry quality."
        )
        self.assertEqual(overridden.status, "OVERRIDDEN")
        self.assertEqual(overridden.overridden_mmi, 7.5)

    def test_override_coordinates(self):
        state = {"location": {"coordinates": {"latitude": 0.0, "longitude": 0.0}}}
        self.queue.check_and_enqueue("obs-006", state, force=True)

        overridden = self.queue.override_coordinates(
            "obs-006", reviewer_id="dr_seismo", latitude=21.88035, longitude=95.98488, notes="Set Sagaing ground coordinates."
        )
        self.assertEqual(overridden.status, "OVERRIDDEN")
        self.assertEqual(overridden.overridden_coordinates["latitude"], 21.88035)

    def test_queue_persistence_across_process_restart(self):
        """
        Verify that review items, approval statuses, and notes survive process restarts
        when using persistent JSON storage.
        """
        import tempfile
        import os
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_review_queue.json"

            # 1. First session: Create queue and enqueue observations
            queue1 = HumanReviewQueue(persistence_file=db_path)
            queue1.check_and_enqueue(
                "obs-persist-01",
                {"estimation": {"mmi_value": 9.5}, "qc": {"qc_flags": ["HIGH_INTENSITY_ANOMALY"]}},
                force=True,
            )
            queue1.check_and_enqueue(
                "obs-persist-02",
                {"estimation": {"mmi_value": None}, "qc": {"qc_flags": ["UNESTIMATED_INTENSITY"]}},
                force=True,
            )
            queue1.approve("obs-persist-01", reviewer_id="expert_seismo", notes="Verified structural collapse.")

            self.assertEqual(len(queue1.get_pending()), 1)
            self.assertTrue(db_path.exists())

            # 2. Simulate process exit
            del queue1

            # 3. Second session: Restart process and reload queue from file
            queue2 = HumanReviewQueue(persistence_file=db_path)

            # Assert records persisted completely
            self.assertEqual(len(queue2.items), 2)
            item1 = queue2.get_item("obs-persist-01")
            self.assertIsNotNone(item1)
            self.assertEqual(item1.status, "APPROVED")
            self.assertEqual(item1.reviewer_id, "expert_seismo")
            self.assertEqual(item1.reviewer_notes, "Verified structural collapse.")

            item2 = queue2.get_item("obs-persist-02")
            self.assertIsNotNone(item2)
            self.assertEqual(item2.status, "UNREVIEWED")
            self.assertEqual(len(queue2.get_pending()), 1)


if __name__ == "__main__":
    unittest.main()
