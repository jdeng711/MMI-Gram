"""
Demonstration runner for MMI-Gram LangGraph Workflow with Structured Logging.
Runs an offline replay of server/test_page1.pdf showing turn-by-turn agent tracing.
"""

import os
import sys
import json
from pathlib import Path

# Add server to sys.path
sys.path.insert(0, str(Path(__file__).parents[1]))

from mmigram.telemetry.tracer import StructuredAgentLogger
from mmigram.workflow.graph import MMIGramWorkflow
from mmigram.review.queue import HumanReviewQueue


def main():
    fixture_path = Path(__file__).parent / "tests" / "fixtures" / "steer_page1_baseline.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        fixture = json.load(f)

    logger = StructuredAgentLogger(name="mmigram.demo", console_output=True)
    review_queue = HumanReviewQueue()

    workflow = MMIGramWorkflow(
        logger=logger,
        review_queue=review_queue,
        offline_fixture=fixture,
    )

    initial_input = {
        "blob_name": "test_page1.pdf",
        "signed_url": "https://storage.googleapis.com/quakemap-media-data/test_page1.pdf",
        "mime_type": "application/pdf",
        "raw_location_string": "Sagaing city, 21 52' 49.27\" N, 95 59' 5.57\" E",
    }

    print("\n======================================================================")
    print("🌍 MMI-GRAM: AGENTIC EARTHQUAKE INTENSITY ESTIMATION PIPELINE")
    print("📍 Target: server/test_page1.pdf (2025 Myanmar StEER Report)")
    print("======================================================================")

    final_state = workflow.run(initial_input)

    print("\n" + "=" * 70)
    print("📊 FINAL WORKFLOW EXECUTION SUMMARY:")
    print("=" * 70)
    print(f"File:               {final_state.get('blob_name')}")
    print(f"MMI Estimation:     {final_state.get('final_analysis', {}).get('mmi_estimation')} (Observed AI Baseline)")
    print(f"Confidence:         {final_state.get('final_analysis', {}).get('confidence')}")
    coords = final_state.get("location", {}).get("coordinates", {})
    print(f"Coordinates:        Lat {coords.get('latitude')}, Lon {coords.get('longitude')} (Valid: {coords.get('is_valid')})")
    qc = final_state.get("qc", {})
    print(f"QC Status:          {qc.get('qc_status')} (Flags: {qc.get('qc_flags')})")
    rev = final_state.get("review", {})
    print(f"Human Review:       Required: {rev.get('review_required')} (Triggers: {rev.get('triggers')})")
    print(f"Pending Queue:      {len(review_queue.get_pending())} item(s) awaiting expert verification")
    print("======================================================================\n")


if __name__ == "__main__":
    main()
