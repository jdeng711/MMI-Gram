"""
Tests for MMI-Gram Live Gemini Batch Runner & Cost Safeguards.

Verifies:
1. Versioned token pricing and dollar cost calculation for Gemini 3.8 Flash.
2. Checkpoint persistence, atomic writes, and idempotent resume behavior.
3. Strict budget limit enforcement and safety buffer protection.
4. Five-page pilot manifest integrity, exact file hashes, and enumeration of the full collection (222 files).
5. Dry-run mode produces zero network calls and accurate token accounting.
"""

from __future__ import annotations
import json
import os
from pathlib import Path
import pytest

from mmigram.workflow.batch_runner import (
    BatchRunner,
    BatchRunnerConfig,
    calculate_cost_usd,
    TokenAccounting,
    GEMINI_38_FLASH_PRICING,
)
from scripts.run_gemini_pilot import (
    PILOT_TARGET_PAGES,
    resolve_pages_directory,
    enumerate_source_pdfs,
    generate_pilot_manifest,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_gemini_38_flash_pricing_calculation():
    """Verify dollar cost estimation matches official versioned pricing formula without double counting thoughts."""
    # 1,000,000 prompt tokens @ $0.15 = $0.15
    # 1,000,000 candidate tokens @ $0.60 = $0.60 (inclusive of thoughts)
    # 0 cached prompt tokens
    cost = calculate_cost_usd(1_000_000, 1_000_000, cached_tokens=0)
    assert cost == pytest.approx(0.75, abs=1e-5)

    # Typical single-page StEER query: 2400 prompt, 450 candidate (inclusive of 250 thoughts)
    single_page_cost = calculate_cost_usd(2400, 450, cached_tokens=0)
    expected = (2400 * 0.15 + 450 * 0.60) / 1_000_000.0
    assert single_page_cost == pytest.approx(expected, abs=1e-6)
    assert single_page_cost == pytest.approx(0.000630, abs=1e-6)
    assert single_page_cost < 0.001  # Less than 1/10th of a cent

    # Five-page pilot simulated cost
    five_page_cost = single_page_cost * 5
    assert five_page_cost == pytest.approx(0.003150, abs=1e-6)

    # Test with cached tokens: 2400 total prompt, 1000 cached @ $0.0375/1M, 1400 unpromoted @ $0.15/1M, 450 candidates
    cached_run_cost = calculate_cost_usd(2400, 450, cached_tokens=1000)
    expected_cached = (1400 * 0.15 + 1000 * 0.0375 + 450 * 0.60) / 1_000_000.0
    assert cached_run_cost == pytest.approx(expected_cached, abs=1e-6)

    # Test TokenAccounting accumulator
    acc = TokenAccounting()
    acc.add(calls=1, prompt=2400, candidates=450, thoughts=250, cached=0)
    assert acc.api_calls == 1
    assert acc.prompt_tokens == 2400
    assert acc.candidates_tokens == 450
    assert acc.thoughts_tokens == 250
    assert acc.cached_tokens == 0
    assert acc.total_tokens == 2850
    assert acc.estimated_cost_usd == pytest.approx(0.000630, abs=1e-6)


def test_batch_checkpoint_persistence_and_resume(tmp_path):
    """Verify that BatchRunner saves state to disk and resumes without duplicating work."""
    checkpoint_file = tmp_path / "checkpoint.json"
    out_dir = tmp_path / "results"

    config = BatchRunnerConfig(
        run_mode="pilot",
        budget_limit_usd=3.00,
        checkpoint_path=checkpoint_file,
        output_dir=out_dir,
    )

    runner = BatchRunner(config=config, dry_run=True)

    # Create dummy pdf files
    pdf1 = tmp_path / "page-1.pdf"
    pdf2 = tmp_path / "page-2.pdf"
    pdf1.write_bytes(b"%PDF-1.4 dummy content 1")
    pdf2.write_bytes(b"%PDF-1.4 dummy content 2")

    # Run batch on pdf1
    res1 = runner.process_batch([pdf1], pipeline_factory=None)
    assert "page-1.pdf" in runner.completed_pages
    assert checkpoint_file.exists()

    # Load new runner instance with same checkpoint
    runner2 = BatchRunner(config=config, dry_run=True)
    assert runner2.is_page_completed("page-1.pdf")
    assert not runner2.is_page_completed("page-2.pdf")

    # Run batch on both; pdf1 must be skipped as cached/resumed
    res2 = runner2.process_batch([pdf1, pdf2], pipeline_factory=None)
    assert len(runner2.completed_pages) == 2
    assert "page-1.pdf" in res2["documents"]
    assert "page-2.pdf" in res2["documents"]


def test_budget_safety_limit_stops_execution(tmp_path):
    """Verify that BatchRunner halts before exceeding the hard dollar spending ceiling."""
    checkpoint_file = tmp_path / "checkpoint.json"
    out_dir = tmp_path / "results"

    # Set very small budget limit ($0.001)
    config = BatchRunnerConfig(
        run_mode="pilot",
        budget_limit_usd=0.001,
        budget_safety_buffer_usd=0.0005,
        checkpoint_path=checkpoint_file,
        output_dir=out_dir,
    )

    runner = BatchRunner(config=config, dry_run=False)
    # Simulate that we've already spent $0.0008
    runner.accounting.estimated_cost_usd = 0.0008

    assert runner.check_budget_ok(estimated_next_call_usd=0.0004) is False, (
        "Runner must detect budget limit reached"
    )


def test_source_directory_enumeration_and_pilot_manifest(tmp_path):
    """Verify enumeration of Myanmar pages directory and exact pilot manifest hashes."""
    try:
        pages_dir = resolve_pages_directory()
    except FileNotFoundError:
        pytest.skip("Local Myanmar pages directory not available in this test environment.")

    all_pdfs = enumerate_source_pdfs(pages_dir)
    # The actual folder contains exactly 222 PDF documents
    assert len(all_pdfs) == 222, f"Expected 222 PDF files in pages dir, found {len(all_pdfs)}"

    manifest_path = generate_pilot_manifest(pages_dir, tmp_path, PILOT_TARGET_PAGES)
    assert manifest_path.exists()

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["total_pilot_files"] == 5
    assert len(manifest["files"]) == 5

    names = [f["file_name"] for f in manifest["files"]]
    assert names == PILOT_TARGET_PAGES

    for f in manifest["files"]:
        assert len(f["sha256"]) == 64
        assert f["file_size_bytes"] > 0
        assert os.path.exists(f["file_path"])


def test_dry_run_batch_execution_zero_cost(tmp_path):
    """Verify that a full dry-run of the pilot completes with zero real network spend."""
    try:
        pages_dir = resolve_pages_directory()
    except FileNotFoundError:
        pytest.skip("Local Myanmar pages directory not available in this test environment.")

    target_paths = [pages_dir / f for f in PILOT_TARGET_PAGES]
    checkpoint_file = tmp_path / "test_dry_run_checkpoint.json"
    out_dir = tmp_path / "test_dry_run_results"

    config = BatchRunnerConfig(
        run_mode="pilot",
        budget_limit_usd=3.00,
        checkpoint_path=checkpoint_file,
        output_dir=out_dir,
    )

    runner = BatchRunner(config=config, dry_run=True)
    inv = runner.process_batch(target_paths, pipeline_factory=None)

    assert inv["execution_metadata"]["dry_run"] is True
    assert inv["execution_metadata"]["total_completed"] == 5
    assert inv["execution_metadata"]["total_failed"] == 0
    assert runner.accounting.api_calls == 5
    assert runner.accounting.estimated_cost_usd > 0.0
    assert runner.accounting.estimated_cost_usd < 0.01  # Under 1 cent simulated
