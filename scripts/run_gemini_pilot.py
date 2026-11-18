#!/usr/bin/env python3
"""
MMI-Gram Gemini 3.8 Flash Pilot & Batch Inference Orchestrator.

Executes unified StEER macroseismic analysis using Google AI Studio:
- 5-Page Pilot Set:
  1. page-76.pdf: Pyawbwe KBZ Bank branch (commercial shaking damage)
  2. page-22.pdf: Thazi surface fault displacement (geotechnical faulting)
  3. page-47.pdf: Pyinmana residential building (residential frame damage)
  4. page-26.pdf: Sagaing mixed shaking/fault rupture (Ava bridge area)
  5. page-8.pdf:  USGS PAGER hazard-model map (non-estimable benchmark control)
- Hard Budget Ceilings ($3.00 pilot, $25.00 full run).
- Idempotent Checkpointing (never charges twice for completed pages).
- Zero paid Google Maps API calls (ENABLE_LIVE_GEOCODING=false).
- Dry-run mode for 100% cost-free simulation.
"""

from __future__ import annotations
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, List

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "server"))

clean_venv_site = REPO_ROOT / ".clean_venv" / "lib" / "python3.13" / "site-packages"
if clean_venv_site.exists():
    sys.path.insert(0, str(clean_venv_site))

from mmigram.adapters.gemini_provider import (
    validate_provider_configuration,
    set_active_provider,
    get_gemini_api_key,
)
from mmigram.workflow.batch_runner import (
    BatchRunner,
    BatchRunnerConfig,
    calculate_cost_usd,
    GEMINI_38_FLASH_PRICING,
)
from mmigram.workflow.general_steer_pipeline import GeneralSteerPipeline


# Five authoritative pilot cases selected for diverse seismic & geotechnical phenomena
PILOT_TARGET_PAGES = [
    "page-76.pdf",  # Pyawbwe KBZ Bank branch: Commercial shaking damage, soft-story collapse investigation
    "page-22.pdf",  # Thapyawa solar farm: Surface fault displacement & geotechnical deformation confounding shaking
    "page-47.pdf",  # Pyinmana: Residential brick-nogging frame collapse; township-coordinate ambiguity
    "page-26.pdf",  # Sagaing Ava Bridge / road-median area: Mixed ground rupture displacement and adjacent structural shaking
    "page-8.pdf",   # USGS PAGER hazard-model map: Negative control non-estimable document (Gate 1/2 screening)
]


def resolve_pages_directory(custom_path: Optional[str] = None) -> Path:
    """Resolve directory containing the authentic Myanmar StEER page PDFs."""
    if custom_path:
        p = Path(custom_path).resolve()
        if p.exists() and p.is_dir():
            return p
        raise FileNotFoundError(f"Specified pages directory not found: {custom_path}")

    # Standard candidate locations
    candidates = [
        REPO_ROOT.parent / "2026_Macroseismic_AI_Myanmar" / "pages",
        REPO_ROOT / "data" / "events" / "us7000pn9s" / "inbound" / "pages",
        REPO_ROOT / "pages",
    ]
    for c in candidates:
        if c.exists() and c.is_dir():
            return c.resolve()

    raise FileNotFoundError(
        "Could not find '2026_Macroseismic_AI_Myanmar/pages' directory. "
        "Please provide --pages-dir /path/to/pages"
    )


def enumerate_source_pdfs(pages_dir: Path) -> List[Dict[str, Any]]:
    """Enumerate and hash all source PDF files in the target directory."""
    pdf_files = sorted([p for p in pages_dir.iterdir() if p.is_file() and p.name.lower().endswith(".pdf")])
    inventory = []
    for p in pdf_files:
        inventory.append({
            "file_name": p.name,
            "file_path": str(p),
            "size_bytes": p.stat().st_size,
        })
    return inventory


def generate_full_manifest(
    pages_dir: Path,
    output_dir: Path,
    all_pdfs: List[Dict[str, Any]],
) -> Path:
    """Generate and write the full 222-document inventory manifest with exact checksums."""
    manifest_items = []
    for item in all_pdfs:
        fpath = Path(item["file_path"])
        content_bytes = fpath.read_bytes()
        sha256 = hashlib.sha256(content_bytes).hexdigest()
        manifest_items.append({
            "file_name": item["file_name"],
            "file_path": str(fpath),
            "file_size_bytes": len(content_bytes),
            "sha256": sha256,
            "is_pilot_target": item["file_name"] in PILOT_TARGET_PAGES,
        })

    manifest_doc = {
        "manifest_name": "MMI-Gram Full 222-PDF Dataset Manifest",
        "created_at": "2026-11-18T19:48:00Z",
        "event_id": "us7000pn9s",
        "earthquake_magnitude": 7.7,
        "earthquake_origin_time": "2025-03-28T06:20:52.715Z",
        "target_model": "gemini-3.8-flash",
        "target_provider": "ai_studio",
        "thinking_level": "HIGH",
        "full_run_budget_limit_usd": 25.00,
        "geocoding_policy": "DISABLED (zero paid Google Maps API calls)",
        "total_source_files": len(manifest_items),
        "files": manifest_items,
    }

    manifest_path = output_dir / "full_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_doc, f, indent=2)
    return manifest_path


def seed_full_checkpoint_from_pilot(
    full_checkpoint_path: Path,
    pilot_checkpoint_path: Path,
) -> int:
    """
    Seed full-run checkpoint with verified 5-page pilot outputs to prevent duplicate API spend.
    Returns the count of seeded documents.
    """
    if full_checkpoint_path.exists():
        return 0

    if not pilot_checkpoint_path.exists():
        return 0

    try:
        with open(pilot_checkpoint_path, "r", encoding="utf-8") as f:
            pilot_data = json.load(f)

        completed = pilot_data.get("completed_pages", {})
        if not completed:
            return 0

        acc = pilot_data.get("token_accounting", {})
        seed_data = {
            "checkpoint_updated_at": "2026-11-18T19:48:00Z",
            "dry_run": False,
            "run_mode": "full",
            "budget_limit_usd": 25.00,
            "token_accounting": acc,
            "completed_count": len(completed),
            "failed_count": 0,
            "skipped_count": 0,
            "completed_pages": completed,
            "failed_pages": {},
            "skipped_pages": {},
        }
        full_checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        with open(full_checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(seed_data, f, indent=2)
        print(f"[Checkpoint Seed] Successfully seeded {len(completed)} verified pilot documents into {full_checkpoint_path.name}")
        return len(completed)
    except Exception as e:
        print(f"[Warning] Could not seed full checkpoint from pilot: {e}")
        return 0


def generate_pilot_manifest(
    pages_dir: Path,
    output_dir: Path,
    pilot_filenames: List[str] = PILOT_TARGET_PAGES,
) -> Path:
    """Generate and write the five-PDF pilot manifest with exact checksums."""
    manifest_items = []
    for fname in pilot_filenames:
        fpath = pages_dir / fname
        if not fpath.exists():
            raise FileNotFoundError(f"Pilot target file '{fname}' not found in {pages_dir}")

        content_bytes = fpath.read_bytes()
        sha256 = hashlib.sha256(content_bytes).hexdigest()
        phenomenon_map = {
            "page-76.pdf": {
                "phenomenon_type": "commercial_structural_damage",
                "scientific_description": "Pyawbwe KBZ Bank branch: Commercial RC frame shaking damage; investigation of potential soft-story collapse mechanism.",
                "confounding_factors": "Potential soft-story vulnerability; single-structure commercial site.",
                "coordinate_notes": "Site-associated coordinates (20.601, 96.050) located ~38 km from nearest baseline DYFI station.",
                "expected_screening_gate": "PASSED (ESTIMABLE)",
            },
            "page-22.pdf": {
                "phenomenon_type": "surface_fault_displacement",
                "scientific_description": "Thapyawa solar plant: Surface fault rupture and ground displacement offsetting fence lines and racking.",
                "confounding_factors": "Primary fault displacement confounding pure inertial shaking; MMI scale measures ground shaking rather than surface rupture.",
                "coordinate_notes": "Site-specific coordinates at solar farm rupture trace.",
                "expected_screening_gate": "PASSED (ESTIMABLE with surface faulting flag)",
            },
            "page-47.pdf": {
                "phenomenon_type": "residential_structural_damage",
                "scientific_description": "Pyinmana: Brick-nogging residential building collapse.",
                "confounding_factors": "High unreinforced masonry/brick-nogging vulnerability; township-level centroid coordinate ambiguity.",
                "coordinate_notes": "Township centroid coordinates; requires precision qualification.",
                "expected_screening_gate": "PASSED (ESTIMABLE)",
            },
            "page-26.pdf": {
                "phenomenon_type": "mixed_shaking_and_rupture",
                "scientific_description": "Sagaing Ava Bridge / road-median area: Mixed ground rupture offset and adjacent structural collapse.",
                "confounding_factors": "Co-located strike-slip displacement and severe ground motion.",
                "coordinate_notes": "Near Ava Bridge fault trace.",
                "expected_screening_gate": "PASSED (ESTIMABLE)",
            },
            "page-8.pdf": {
                "phenomenon_type": "regional_hazard_model_map_negative_control",
                "scientific_description": "USGS PAGER regional macroseismic hazard model map. Contains no observable physical building damage or field reconnaissance photos.",
                "confounding_factors": "Non-reconnaissance overview map; must be screened out prior to MMI estimation.",
                "coordinate_notes": "Regional map view with no point-source field site.",
                "expected_screening_gate": "NOT_ESTIMABLE (Gate 1/2 screening, $0.00 API spend)",
            },
        }

        p_info = phenomenon_map.get(fname, {
            "phenomenon_type": "unknown",
            "scientific_description": "Uncharacterized StEER document",
            "confounding_factors": "None documented",
            "coordinate_notes": "Unverified coordinates",
            "expected_screening_gate": "UNKNOWN",
        })

        manifest_items.append({
            "file_name": fname,
            "file_path": str(fpath),
            "file_size_bytes": len(content_bytes),
            "sha256": sha256,
            "phenomenon_type": p_info["phenomenon_type"],
            "scientific_description": p_info["scientific_description"],
            "confounding_factors": p_info["confounding_factors"],
            "coordinate_notes": p_info["coordinate_notes"],
            "expected_screening_gate": p_info["expected_screening_gate"],
        })

    manifest_doc = {
        "manifest_name": "MMI-Gram Five-PDF Live Pilot Manifest",
        "created_at": "2026-11-18T19:00:00Z",
        "event_id": "us7000pn9s",
        "earthquake_magnitude": 7.7,
        "earthquake_origin_time": "2025-03-28T06:20:52.715Z",
        "target_model": "gemini-3.8-flash",
        "target_provider": "ai_studio",
        "thinking_level": "HIGH",
        "pilot_budget_limit_usd": 3.00,
        "geocoding_policy": "DISABLED (zero paid Google Maps API calls)",
        "total_pilot_files": len(manifest_items),
        "files": manifest_items,
    }

    manifest_path = output_dir / "pilot_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_doc, f, indent=2)
    return manifest_path


def main():
    parser = argparse.ArgumentParser(
        description="MMI-Gram Gemini 3.8 Flash Batch Inference Orchestrator"
    )
    group_mode = parser.add_mutually_exclusive_group()
    group_mode.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Simulate execution without making any live API calls (Default: True)",
    )
    group_mode.add_argument(
        "--live",
        action="store_true",
        help="Execute live Gemini API calls via Google AI Studio (Requires GEMINI_API_KEY)",
    )

    group_scope = parser.add_mutually_exclusive_group()
    group_scope.add_argument(
        "--pilot",
        action="store_true",
        default=True,
        help="Run 5-page pilot set (Default: True)",
    )
    group_scope.add_argument(
        "--full",
        action="store_true",
        help="Target all source PDFs in pages directory (Requires explicit approval)",
    )

    parser.add_argument(
        "--pages-dir",
        type=str,
        default=None,
        help="Path to Myanmar pages directory",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/events/us7000pn9s/live_pilot_results",
        help="Directory where output JSON artifacts and inventory are written",
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=None,
        help="Override spending budget limit in USD (Default: $3.00 for pilot, $25.00 for full)",
    )
    parser.add_argument(
        "--reset-checkpoint",
        action="store_true",
        help="Discard previous checkpoint file and restart from scratch",
    )
    parser.add_argument(
        "--authorize-full-run",
        action="store_true",
        help="Explicit user authorization required to execute the full 222-document paid run",
    )

    args = parser.parse_args()

    # Determine live mode
    is_live = bool(args.live)
    dry_run = not is_live

    # Resolve pages directory
    pages_dir = resolve_pages_directory(args.pages_dir)
    all_pdfs = enumerate_source_pdfs(pages_dir)
    total_available_pdfs = len(all_pdfs)

    # Determine target list
    is_full = bool(args.full)
    run_mode = "full" if is_full else "pilot"

    if args.output_dir == "data/events/us7000pn9s/live_pilot_results" and is_full:
        output_dir = (REPO_ROOT / "data" / "events" / "us7000pn9s" / "full_dataset_results").resolve()
    else:
        output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if is_full:
        target_paths = [Path(p["file_path"]) for p in all_pdfs]
        default_budget = 25.00
        full_manifest_path = generate_full_manifest(pages_dir, output_dir, all_pdfs)
        print(f"Generated full 222-PDF manifest at: {full_manifest_path}")
    else:
        # 5-page pilot
        target_paths = [pages_dir / f for f in PILOT_TARGET_PAGES]
        default_budget = 3.00

    budget_limit = args.budget if args.budget is not None else default_budget

    # Generate pilot manifest
    manifest_path = generate_pilot_manifest(pages_dir, output_dir, PILOT_TARGET_PAGES)
    print(f"Generated pilot manifest with SHA256 checksums at: {manifest_path}")
    print(f"Total source PDFs available in '{pages_dir}': {total_available_pdfs}")

    # Safety confirmation for live full run
    if is_live and is_full and not args.authorize_full_run:
        print("\n================================================================================")
        print("[SAFETY GUARD] Full dataset live execution was requested.")
        print(f"Target count: {len(target_paths)} documents. Spending ceiling: ${budget_limit:.2f} USD.")
        print("To protect against unintended spend, full execution is blocked until explicitly authorized.")
        print("Run with '--authorize-full-run' once approved by the researcher.")
        print("To run a 100% cost-free dry run across all 222 documents, run:")
        print("  python scripts/run_gemini_pilot.py --dry-run --full")
        print("================================================================================\n")
        sys.exit(0)

    # Configure checkpoint with strict separation between live and dry-run files
    mode_suffix = "live" if is_live else "dryrun"
    checkpoint_file = output_dir / f"batch_checkpoint_{run_mode}_{mode_suffix}.json"
    if args.reset_checkpoint and checkpoint_file.exists():
        checkpoint_file.unlink()
        print(f"Reset checkpoint file: {checkpoint_file}")

    # For full runs, automatically seed completed pages from pilot checkpoint if available
    if is_full and not checkpoint_file.exists():
        pilot_chk = (
            REPO_ROOT / "data" / "events" / "us7000pn9s" / "live_pilot_results" / f"batch_checkpoint_pilot_{mode_suffix}.json"
        )
        seed_full_checkpoint_from_pilot(checkpoint_file, pilot_chk)

    # Build runner configuration
    config = BatchRunnerConfig(
        run_mode=run_mode,
        budget_limit_usd=budget_limit,
        checkpoint_path=checkpoint_file,
        output_dir=output_dir,
    )

    # Preflight provider checks if live
    if is_live:
        set_active_provider("ai_studio")
        is_valid, missing = validate_provider_configuration("ai_studio")
        if not is_valid:
            print("\n[PREFLIGHT FAILED] Google AI Studio configuration is invalid:")
            for m in missing:
                print(f"  - {m}")
            sys.exit(1)

        key = get_gemini_api_key()
        masked_key = f"{key[:6]}...{key[-4:]}" if key and len(key) > 10 else "***"
        print(f"[Preflight OK] Active Provider: ai_studio, Model: gemini-3.8-flash, Key: {masked_key}")

        # Ensure live geocoding remains explicitly disabled
        os.environ["ENABLE_LIVE_GEOCODING"] = "false"

    # Pipeline factory
    def create_pipeline():
        return GeneralSteerPipeline(
            mode="live",
            provider="ai_studio",
            model_name="gemini-3.8-flash",
            thinking_level="HIGH",
            allow_live_api=True,
            allow_live_geocoding=False,
            origin_time_utc="2025-03-28T06:20:52.715Z",
        )

    # Execute batch
    runner = BatchRunner(config=config, dry_run=dry_run)
    inventory = runner.process_batch(
        file_paths=target_paths,
        pipeline_factory=create_pipeline,
    )

    print(f"\nExecution finished cleanly.")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'} ({run_mode.upper()})")
    print(f"Completed: {len(runner.completed_pages)} / {len(target_paths)}")
    print(f"Total Estimated Cost: ${runner.accounting.estimated_cost_usd:.5f} USD")
    print(f"Inventory saved at: {output_dir / 'batch_execution_inventory.json'}\n")


if __name__ == "__main__":
    main()
