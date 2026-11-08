"""
Unified Command-Line Interface (CLI) for MMI-Gram.

Commands:
  demo       Run the self-contained offline StEER demonstration pipeline (zero credentials).
  analyze    Analyze a single StEER reconnaissance PDF document.
  batch      Process a directory of StEER reconnaissance PDFs for an event.
  check-env  Preflight verification of local dependencies and cloud credentials.
  test       Execute the complete offline test suite.

Examples:
  python -m mmigram.cli demo
  python -m mmigram.cli analyze --pdf data/events/us7000pn9s/inbound/test_page1.pdf
  python -m mmigram.cli batch --event-id us7000pn9s --inbound-dir data/events/us7000pn9s/inbound --pace 2.0
  python -m mmigram.cli check-env
  python -m mmigram.cli test
"""

from __future__ import annotations
import os
import sys
import time
import json
import argparse
from pathlib import Path
from typing import Optional, List

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from mmigram.workflow.general_steer_pipeline import GeneralSteerPipeline
from mmigram.workflow.steer_offline_pipeline import SteerOfflinePipeline
from mmigram.review.queue import HumanReviewQueue, DEFAULT_PERSISTENCE_PATH
from mmigram.telemetry.tracer import StructuredAgentLogger
from mmigram.adapters.crag_adapter import check_live_prerequisites
from mmigram.comparison.comparator import BenchmarkComparator

# Standard verified Vertex AI / Gemini models
VERIFIED_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
]
DEFAULT_MODEL = "gemini-2.5-flash"


def validate_model_identifier(model_name: Optional[str]) -> str:
    """Validate model identifier and display a cautionary note if unverified."""
    if not model_name:
        return DEFAULT_MODEL
    clean_name = model_name.strip()
    if clean_name not in VERIFIED_MODELS:
        print(f"⚠️  Note on Model Identifier: '{clean_name}' is not in the verified Vertex AI model registry.")
        print(f"   Known verified models: {', '.join(VERIFIED_MODELS)}.")
        print("   If live execution fails, override with: --model gemini-2.5-flash\n")
    return clean_name


# ──────────────────────────────────────────────────────────────────────────────
# Subcommand: demo
# ──────────────────────────────────────────────────────────────────────────────
def cmd_demo(args: argparse.Namespace) -> int:
    """Run the offline demonstration pipeline."""
    print("=" * 80)
    print("🌍 MMI-GRAM: OFFLINE STEER LANGGRAPH DEMONSTRATION")
    print("⚙️ Mode: Self-contained offline replay (Zero cloud credentials required)")
    print("=" * 80)

    logger = StructuredAgentLogger(name="mmigram.demo", console_output=True)
    pipeline = SteerOfflinePipeline(logger=logger)
    result = pipeline.execute()
    summary = result.get("structured_summary", {})
    seis = summary.get("seismic_intensity", {})
    geo = summary.get("geographic_resolution", {})
    qc = summary.get("quality_control_audit", {})
    hitl = summary.get("human_in_the_loop", {})

    print("\n" + "=" * 80)
    print("📋 DEMONSTRATION WORKFLOW COMPLETED")
    print("=" * 80)
    print(f"Observation ID:     {summary.get('observation_id')}")
    print(f"MMI Estimation:     {seis.get('mmi_estimation')} (Confidence: {seis.get('confidence'):.2f})")
    print(f"Calibration Status: {'Calibrated' if seis.get('is_calibrated') else 'Uncalibrated (AI Estimate)'}")
    print(f"Coordinates:        Lat {geo.get('latitude'):.4f}, Lon {geo.get('longitude'):.4f}")
    print(f"Coordinate Origin:  Source: {geo.get('coordinate_source')} (Authoritative: {geo.get('is_authoritative')})")
    print(f"QC Status:          {qc.get('final_status')} | Flags: {qc.get('active_flags')}")
    print(f"Review Gate:        Status: {hitl.get('review_status')} | Triggers: {hitl.get('review_triggers')}")
    print("=" * 80)
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Subcommand: analyze
# ──────────────────────────────────────────────────────────────────────────────
def cmd_analyze(args: argparse.Namespace) -> int:
    """Analyze a single StEER PDF."""
    mode = "live" if args.live else "offline"
    model = validate_model_identifier(args.model)

    if args.live and not args.confirm_live_api:
        print("\n❌ Live Execution Blocked: Running with '--live' requires explicit user authorization via '--confirm-live-api'.")
        print("This prevents accidental paid cloud invocations (Google Cloud Storage / Vertex AI / Pinecone).")
        return 1

    print("=" * 80)
    print("🌍 MMI-GRAM: STEER RECONNAISSANCE ANALYSIS")
    print(f"📄 Input File:  {args.pdf}")
    print(f"⚙️ Mode:        {mode.upper()} {'(Offline Fixtures Only)' if mode == 'offline' else f'(Live Vertex AI: {model})'}")
    print("=" * 80)

    # Set model in environment if live
    if args.live:
        os.environ["GEMINI_MODEL"] = model

    logger = StructuredAgentLogger(name="mmigram.cli", console_output=not args.quiet)
    review_queue = HumanReviewQueue(persistence_file=args.review_db)

    pipeline = GeneralSteerPipeline(
        mode=mode,
        logger=logger,
        review_queue=review_queue,
        allow_live_api=(args.live and args.confirm_live_api),
    )

    t0 = time.time()
    try:
        result = pipeline.process_pdf(args.pdf)
    except PermissionError as pe:
        print(f"\n❌ Execution Blocked: {pe}")
        return 1
    except Exception as e:
        print(f"\n❌ Pipeline Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    duration_ms = (time.time() - t0) * 1000.0

    print("\n" + "=" * 80)
    print("📊 STRUCTURED ANALYSIS SUMMARY:")
    print("=" * 80)

    status = result.get("pipeline_status", "COMPLETED")
    if status == "FIXTURE_NOT_FOUND":
        print("⚠️ Status: FIXTURE_NOT_FOUND")
        print(f"File:    {result.get('file_name')}")
        print(f"Message: {result.get('message')}")
    elif status == "INVALID_PDF":
        print("❌ Status: INVALID_PDF")
        print(f"File:    {result.get('file_name')}")
        print(f"Error:   {result.get('error_message')}")
    else:
        prov = result.get("provenance", {})
        prov_label = "SYNTHETIC TEST FIXTURE" if prov.get("is_synthetic") else "AUTHENTIC STEER REPORT"
        print(f"Artifact Provenance:   {prov_label} (Baseline: {prov.get('baseline_type')})")
        sha_str = prov.get('source_sha256', 'N/A')
        short_sha = sha_str[:12] + "..." if len(sha_str) > 12 else sha_str
        print(f"Execution Provenance:  Mode: {prov.get('execution_mode', mode).upper()} | Model: {prov.get('model_identifier', 'N/A')} | SHA256: {short_sha}")
        print(f"Document Text Status:  {result.get('document_extraction', {}).get('extraction_status')}")

        seis = result.get("seismic_intensity", {})
        mmi_display = seis.get('mmi_estimation') if seis.get('mmi_estimation') is not None else "UNESTIMATED (Requires Human Expert)"
        conf_display = f"{seis.get('confidence'):.2f}" if seis.get('confidence') is not None else "N/A"
        print(f"MMI Estimation:        {mmi_display} (Confidence: {conf_display})")
        print(f"Calibration Status:    {'Calibrated' if seis.get('is_calibrated') else 'Uncalibrated (AI Estimate)'}")

        geo = result.get("geographic_resolution", {})
        coords = geo.get("coordinates")
        doc_c = geo.get("document_coordinates")
        model_c = geo.get("model_coordinates")

        if coords and coords.get("latitude") is not None:
            print(f"Candidate Coords:      Lat {coords.get('latitude'):.4f}, Lon {coords.get('longitude'):.4f} (Source: {coords.get('source')})")
        else:
            print("Candidate Coords:      UNKNOWN (Coordinates could not be established)")

        if doc_c and doc_c.get("latitude") is not None:
            if not doc_c.get("is_valid", True) and doc_c.get("validation_error"):
                doc_str = f"Lat {doc_c.get('latitude'):.4f}, Lon {doc_c.get('longitude'):.4f} [INVALID: {doc_c.get('validation_error')}]"
            else:
                doc_str = f"Lat {doc_c.get('latitude'):.4f}, Lon {doc_c.get('longitude'):.4f}"
        else:
            doc_str = "None (No coordinates detected in document text)"

        if model_c and model_c.get("latitude") is not None:
            if not model_c.get("is_valid", True) and model_c.get("validation_error"):
                model_str = f"Lat {model_c.get('latitude'):.4f}, Lon {model_c.get('longitude'):.4f} [INVALID: {model_c.get('validation_error')}]"
            else:
                model_str = f"Lat {model_c.get('latitude'):.4f}, Lon {model_c.get('longitude'):.4f}"
        else:
            model_str = "Unknown (Model provided no coordinates)"

        print(f"Document Coords:       {doc_str}")
        print(f"Model Coords:          {model_str}")
        print(f"Location Status:       {geo.get('comparison_status', 'LOCATION_UNKNOWN')}")

        if geo.get("coordinates_disagree"):
            print(f"⚠️ Coordinate Conflict: {geo.get('discrepancy_details')}")

        qc = result.get("quality_control", {})
        print(f"Quality Control:       Status: {qc.get('status')} | Score: {qc.get('score')} | Flags: {qc.get('flags')}")

        hitl = result.get("human_in_the_loop", {})
        print(f"Human Review Queue:    Required: {hitl.get('review_required')} | Status: {hitl.get('review_status')}")
        if hitl.get("triggers"):
            print(f"Review Triggers:       {hitl.get('triggers')}")
        print(f"Queue Storage:         {args.review_db} (Pending in queue: {len(review_queue.get_pending())})")

    print(f"⏱️ Execution Time:      {duration_ms:.1f} ms")
    print("=" * 80)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(f"💾 Results saved to: {out_path}")

    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Subcommand: batch
# ──────────────────────────────────────────────────────────────────────────────
def cmd_batch(args: argparse.Namespace) -> int:
    """Process a batch of StEER PDFs from an inbound directory."""
    inbound_dir = Path(args.inbound_dir)
    if not inbound_dir.exists() or not inbound_dir.is_dir():
        print(f"❌ Error: Inbound directory not found: {inbound_dir}")
        return 1

    pdf_files = sorted(list(inbound_dir.glob("*.pdf")))
    if not pdf_files:
        print(f"⚠️ Warning: No PDF files found in inbound directory: {inbound_dir}")
        return 0

    mode = "live" if args.live else "offline"
    model = validate_model_identifier(args.model)
    pace = max(0.0, float(args.pace))

    if args.live and not args.confirm_live_api:
        print("\n❌ Live Batch Execution Blocked: Running with '--live' requires explicit user authorization via '--confirm-live-api'.")
        return 1

    print("=" * 80)
    print("🌍 MMI-GRAM: BATCH RECONNAISSANCE PROCESSING")
    print(f"📍 Event ID:       {args.event_id}")
    print(f"📁 Inbound Dir:    {inbound_dir} ({len(pdf_files)} documents found)")
    print(f"⚙️ Mode:           {mode.upper()} {'(Strict Offline Fixtures)' if mode == 'offline' else f'(Live Model: {model})'}")
    if pace > 0:
        print(f"⏱️ Request Pacing: {pace:.1f}s between documents")
    print("=" * 80)

    comparator = BenchmarkComparator(event_id=args.event_id)
    review_queue = HumanReviewQueue(persistence_file=args.review_db)
    logger = StructuredAgentLogger(name="mmigram.batch", console_output=False)

    pipeline = GeneralSteerPipeline(
        mode=mode,
        logger=logger,
        review_queue=review_queue,
        allow_live_api=(args.live and args.confirm_live_api),
    )

    out_dir = Path(args.output_dir) if args.output_dir else inbound_dir.parent / "results"
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, pdf_path in enumerate(pdf_files, 1):
        print(f"[{i}/{len(pdf_files)}] Processing: {pdf_path.name} ... ", end="", flush=True)
        t0 = time.time()
        try:
            result = pipeline.process_pdf(pdf_path)
            duration_ms = (time.time() - t0) * 1000.0
            comparator.add_mmigram_result(result, duration_ms=duration_ms, model_name=model)

            status = result.get("pipeline_status", "COMPLETED")
            seis = result.get("seismic_intensity", {})
            mmi = seis.get("mmi_estimation")
            mmi_str = f"MMI {mmi}" if mmi is not None else "UNESTIMATED"
            print(f"Done ({duration_ms:.0f}ms) | {mmi_str} | Status: {status}")
        except Exception as e:
            duration_ms = (time.time() - t0) * 1000.0
            print(f"FAILED: {e}")

        if i < len(pdf_files) and pace > 0:
            time.sleep(pace)

    # Export batch results
    json_path = out_dir / f"{args.event_id}_mmigram_results.json"
    csv_path = out_dir / f"{args.event_id}_mmigram_summary.csv"
    comparator.export_json(json_path)
    comparator.export_csv(csv_path)

    print("\n" + "=" * 80)
    print("📊 BATCH PROCESSING COMPLETE")
    print(f"Processed:         {len(pdf_files)} documents")
    print(f"Results Exported:  {json_path}")
    print(f"Summary Table:     {csv_path}")
    print(f"Pending Reviews:   {len(review_queue.get_pending())} items in queue ({args.review_db})")
    print("=" * 80)
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Subcommand: check-env
# ──────────────────────────────────────────────────────────────────────────────
def cmd_check_env(args: argparse.Namespace) -> int:
    """Preflight check on environment configuration and credentials."""
    print("=" * 80)
    print("🔍 MMI-GRAM: ENVIRONMENT PREFLIGHT VERIFICATION")
    print("=" * 80)

    # Offline capability check
    try:
        import pypdf
        print(f"✅ pypdf installed (Version: {pypdf.__version__}) — Offline PDF parsing is operational.")
    except ImportError:
        print("❌ pypdf NOT installed — Run: pip install pypdf")

    # Cloud live prerequisites
    ready, missing = check_live_prerequisites()
    print("\n☁️ Live Cloud Integration Status:")
    if ready:
        print("✅ All live cloud prerequisites are configured.")
    else:
        print("⚠️  Live cloud prerequisites are NOT complete (Offline mode is fully operational):")
        for m in missing:
            print(f"   - {m}")

    print("\n🤖 Supported Verified Gemini Models:")
    for m in VERIFIED_MODELS:
        print(f"   • {m}")

    print("\n💾 Review Queue Persistent Location:")
    print(f"   • {DEFAULT_PERSISTENCE_PATH}")
    print("=" * 80)
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Subcommand: test
# ──────────────────────────────────────────────────────────────────────────────
def cmd_test(args: argparse.Namespace) -> int:
    """Run the offline test suite."""
    import unittest
    repo_root = Path(__file__).resolve().parents[2]
    tests_dir = repo_root / "tests"

    print("=" * 80)
    print("🧪 MMI-GRAM: RUNNING OFFLINE TEST SUITE")
    print(f"📂 Directory: {tests_dir}")
    print("=" * 80)

    loader = unittest.TestLoader()
    suite = loader.discover(str(tests_dir), pattern="test_*.py")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return 0 if result.wasSuccessful() else 1


# ──────────────────────────────────────────────────────────────────────────────
# Main Argument Parser
# ──────────────────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mmigram",
        description="MMI-Gram: Agentic AI System for Earthquake Intensity Estimation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # demo
    p_demo = subparsers.add_parser("demo", help="Run the self-contained offline demonstration")
    p_demo.set_defaults(func=cmd_demo)

    # analyze
    p_analyze = subparsers.add_parser("analyze", help="Analyze a single StEER reconnaissance PDF")
    p_analyze.add_argument("--pdf", "-p", required=True, type=str, help="Path to the PDF file")
    p_mode = p_analyze.add_mutually_exclusive_group()
    p_mode.add_argument("--offline", action="store_true", default=True, help="Run in strict offline mode (default)")
    p_mode.add_argument("--live", action="store_true", default=False, help="Run in live cloud mode")
    p_analyze.add_argument("--confirm-live-api", action="store_true", default=False, help="Explicit confirmation for paid live cloud calls")
    p_analyze.add_argument("--model", type=str, default=DEFAULT_MODEL, help=f"Gemini model ID (default: {DEFAULT_MODEL})")
    p_analyze.add_argument("--review-db", type=str, default=str(DEFAULT_PERSISTENCE_PATH), help="Path to review queue storage")
    p_analyze.add_argument("--output", "-o", type=str, default=None, help="Path to export JSON output")
    p_analyze.add_argument("--quiet", "-q", action="store_true", help="Quiet mode")
    p_analyze.set_defaults(func=cmd_analyze)

    # batch
    p_batch = subparsers.add_parser("batch", help="Batch process StEER reconnaissance PDFs for an event")
    p_batch.add_argument("--event-id", required=True, type=str, help="USGS ComCat event ID (e.g. us7000pn9s)")
    p_batch.add_argument("--inbound-dir", required=True, type=str, help="Path to directory containing inbound PDFs")
    p_mode_b = p_batch.add_mutually_exclusive_group()
    p_mode_b.add_argument("--offline", action="store_true", default=True, help="Run in strict offline mode (default)")
    p_mode_b.add_argument("--live", action="store_true", default=False, help="Run in live cloud mode")
    p_batch.add_argument("--confirm-live-api", action="store_true", default=False, help="Explicit confirmation for paid live cloud calls")
    p_batch.add_argument("--model", type=str, default=DEFAULT_MODEL, help=f"Gemini model ID (default: {DEFAULT_MODEL})")
    p_batch.add_argument("--pace", type=float, default=0.0, help="Seconds to sleep between documents (e.g. 2.0)")
    p_batch.add_argument("--review-db", type=str, default=str(DEFAULT_PERSISTENCE_PATH), help="Path to review queue storage")
    p_batch.add_argument("--output-dir", type=str, default=None, help="Directory to export batch results and summary")
    p_batch.set_defaults(func=cmd_batch)

    # check-env
    p_check = subparsers.add_parser("check-env", help="Preflight check on dependencies and cloud setup")
    p_check.set_defaults(func=cmd_check_env)

    # test
    p_test = subparsers.add_parser("test", help="Execute the complete offline test suite")
    p_test.set_defaults(func=cmd_test)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
