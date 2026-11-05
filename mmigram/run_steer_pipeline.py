"""
Executable Demo Command for the MMI-Gram Offline StEER Pipeline.

Executes turn-by-turn LangGraph orchestration across:
  - Baseline Loading (MMI 9.0, Confidence 0.90, Coordinates 0,0)
  - Initial Quality Control (Null Island detection)
  - Geolocation DMS Parsing & Regional Validation
  - Secondary Quality Control & High-Intensity Anomaly Flagging
  - Human-in-the-Loop Review Queue Routing
  - Structured Stage-by-Stage Summary
  - Mermaid Architecture Export

Usage:
  .venv/bin/python server/mmigram/run_steer_pipeline.py
"""

import sys
import json
from pathlib import Path

# Add server directory to sys.path
sys.path.insert(0, str(Path(__file__).parents[1]))

from mmigram.workflow.steer_offline_pipeline import (
    SteerOfflinePipeline,
    get_steer_pipeline_mermaid,
)
from mmigram.telemetry.tracer import StructuredAgentLogger
from mmigram.review.queue import HumanReviewQueue


def main():
    print("=" * 80)
    print("🌍 MMI-GRAM: OFFLINE LANGGRAPH END-TO-END PIPELINE DEMO")
    print("📍 Case Study: 2025 Myanmar Earthquake StEER Reconnaissance (server/test_page1.pdf)")
    print("=" * 80)

    logger = StructuredAgentLogger(name="mmigram.steer_demo", console_output=True)
    review_queue = HumanReviewQueue()

    pipeline = SteerOfflinePipeline(
        logger=logger,
        review_queue=review_queue,
    )

    print("\n🚀 Executing Offline LangGraph State Machine...\n")
    final_state = pipeline.execute()
    summary = final_state["structured_summary"]

    print("\n" + "=" * 80)
    print("📋 STAGE-BY-STAGE EXECUTION AUDIT:")
    print("=" * 80)
    for stage in summary["stages_executed"]:
        stage_num = stage["stage_number"]
        stage_name = stage["stage_name"]
        status = stage.get("status") or stage.get("qc_status")
        notes = stage.get("notes", "")
        print(f"▶ Stage {stage_num}: [{stage_name.upper():<24}] -> Status: {status}")
        print(f"  Details: {notes}")
        if "flags" in stage:
            print(f"  Flags:   {stage['flags']}")
        if "triggers" in stage:
            print(f"  Review Triggers: {stage['triggers']}")
        print("-" * 80)

    print("\n" + "=" * 80)
    print("🎯 STRUCTURED FINAL PIPELINE OUTPUT:")
    print("=" * 80)
    print(json.dumps(summary, indent=2))
    print("=" * 80)

    # Export Mermaid Diagram
    mermaid_diagram = get_steer_pipeline_mermaid()
    diagram_path = Path(__file__).parent / "steer_pipeline_graph.mermaid"
    with open(diagram_path, "w", encoding="utf-8") as f:
        f.write(mermaid_diagram.strip() + "\n")
    print(f"\n✅ Mermaid diagram exported to: {diagram_path}\n")


if __name__ == "__main__":
    main()
