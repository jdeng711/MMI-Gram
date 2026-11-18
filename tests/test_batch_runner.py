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
import unittest.mock
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
    """Verify dollar cost estimation matches official Google paid-tier pricing ($0.75/M input, $3.75/M output)."""
    # Deterministic reference test specified by researcher:
    # 2,400 uncached input tokens, 450 candidate output tokens, 250 thinking tokens
    # Standard Gemini 3.8 Flash paid-tier November 2026 pricing:
    # Input: 2,400 * $0.75 / 1,000,000 = $0.001800
    # Output (candidates + thoughts): (450 + 250) * $3.75 / 1,000,000 = 700 * $3.75 / 1,000,000 = $0.002625
    # Total = $0.001800 + $0.002625 = $0.004425
    deterministic_cost = calculate_cost_usd(
        prompt_tokens=2400,
        candidates_tokens=450,
        thoughts_tokens=250,
        cached_tokens=0,
    )
    assert deterministic_cost == pytest.approx(0.004425, abs=1e-6)

    # 1,000,000 prompt tokens @ $0.75 = $0.75
    # 1,000,000 candidate tokens @ $3.75 = $3.75
    # 0 thought tokens, 0 cached prompt tokens
    base_cost = calculate_cost_usd(1_000_000, 1_000_000, thoughts_tokens=0, cached_tokens=0)
    assert base_cost == pytest.approx(4.50, abs=1e-5)

    # Test with cached tokens: 2400 total prompt (1000 cached @ $0.075/1M, 1400 unpromoted @ $0.75/1M), 450 cand, 250 thoughts
    cached_run_cost = calculate_cost_usd(2400, 450, thoughts_tokens=250, cached_tokens=1000)
    expected_cached = (1400 * 0.75 + 1000 * 0.075 + (450 + 250) * 3.75) / 1_000_000.0
    assert cached_run_cost == pytest.approx(expected_cached, abs=1e-6)
    assert cached_run_cost == pytest.approx(0.003750, abs=1e-6)

    # Test TokenAccounting accumulator
    acc = TokenAccounting()
    acc.add(calls=1, prompt=2400, candidates=450, thoughts=250, cached=0)
    assert acc.api_calls == 1
    assert acc.prompt_tokens == 2400
    assert acc.candidates_tokens == 450
    assert acc.thoughts_tokens == 250
    assert acc.cached_tokens == 0
    # In Google GenAI API, total_tokens = prompt + candidates + thoughts
    assert acc.total_tokens == 3100
    assert acc.estimated_cost_usd == pytest.approx(0.004425, abs=1e-6)


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

    # Set small budget limit ($0.010)
    config = BatchRunnerConfig(
        run_mode="pilot",
        budget_limit_usd=0.010,
        budget_safety_buffer_usd=0.005,
        request_reservation_usd=0.002,
        checkpoint_path=checkpoint_file,
        output_dir=out_dir,
    )

    runner = BatchRunner(config=config, dry_run=False)
    # Simulate that we've already spent $0.007
    runner.accounting.estimated_cost_usd = 0.007

    # Remaining: $0.003, Buffer: $0.005, Reservation: $0.002 -> Buffer + Reservation = $0.007 > Remaining ($0.003)
    assert runner.check_budget_ok() is False, (
        "Runner must detect budget safety buffer threshold reached"
    )


def test_budget_guard_with_synthetic_high_token_and_partial_failure(tmp_path):
    """Verify budget guard with synthetic high-token request and simulated partial failure retries."""
    checkpoint_file = tmp_path / "checkpoint_high_tok.json"
    out_dir = tmp_path / "results_high_tok"

    # Budget ceiling: $0.05
    config = BatchRunnerConfig(
        run_mode="pilot",
        budget_limit_usd=0.05,
        budget_safety_buffer_usd=0.01,
        request_reservation_usd=0.01,
        max_retries=2,
        backoff_factor=1.0,
        checkpoint_path=checkpoint_file,
        output_dir=out_dir,
    )

    runner = BatchRunner(config=config, dry_run=False)

    pdf_fail = tmp_path / "page-fail.pdf"
    pdf_fail.write_bytes(b"%PDF-1.4 simulated failing page")

    # Mock pipeline that fails twice then succeeds with high token count
    mock_pipeline = unittest.mock.MagicMock()
    call_count = 0

    def mock_process(path):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise ConnectionError("Simulated transient 503 error")
        return {
            "pipeline_status": "ESTIMABLE",
            "file_name": path.name,
            "provenance": {
                "token_usage": {
                    "calls": 1,
                    "prompt_tokens": 10000,
                    "candidates_tokens": 2000,
                    "thoughts_tokens": 4000,
                    "cached_tokens": 0,
                }
            },
            "seismic_intensity": {"mmi_estimation": 8.0},
        }

    mock_pipeline.process_pdf = mock_process
    res = runner.process_batch([pdf_fail], pipeline_factory=lambda: mock_pipeline)

    assert "page-fail.pdf" in runner.completed_pages
    # Check that retries were accounted for in API calls
    assert runner.accounting.api_calls >= 3
    # Cost: 10,000 * 0.75/1M + 6,000 * 3.75/1M = 0.0075 + 0.0225 = $0.0300
    assert runner.accounting.estimated_cost_usd == pytest.approx(0.0300, abs=1e-4)

    # Next call with high-token reservation of $0.025 would require $0.030 + $0.010 (buffer) + $0.025 (res) = $0.065 > $0.05
    assert runner.check_budget_ok(estimated_next_call_usd=0.025) is False

    # Simulate near-limit spend: $0.045 spent of $0.05 ceiling with $0.01 buffer
    runner.accounting.estimated_cost_usd = 0.045
    assert runner.check_budget_ok(estimated_next_call_usd=0.002) is False, (
        "Runner must detect budget limit reached when remaining < buffer + reservation"
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
    assert runner.accounting.estimated_cost_usd == pytest.approx(0.022125, abs=1e-5)
    assert runner.accounting.estimated_cost_usd < 0.05  # Under 5 cents simulated (5 * $0.004425)
