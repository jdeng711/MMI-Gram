"""
Batch Runner for MMI-Gram Live Gemini Inference.

Orchestrates multi-document StEER ingestion, screening, live Gemini 3.8 Flash inference,
and quality control with strict safety mechanisms:
- Checkpointing and idempotent resume (never duplicate paid calls).
- Token usage and dollar cost accounting with versioned pricing.
- Hard spending limits ($3.00 for pilot, $25.00 for full dataset).
- Bounded retries with exponential backoff for transient API errors.
- Dry-run simulation mode (zero paid calls, zero network).
- Zero paid Google Maps geocoding.
"""

from __future__ import annotations
import datetime
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union

# Official versioned pricing for Gemini 3.8 Flash (USD per 1M tokens)
# Reflects standard Google AI Studio pricing tiers with conservative upper bound
GEMINI_38_FLASH_PRICING = {
    "model": "gemini-3.8-flash",
    "version": "2026-03-pricing-v2",
    "prompt_per_million": 0.15,          # $0.15 per 1,000,000 unpromoted input tokens
    "cached_prompt_per_million": 0.0375, # $0.0375 per 1,000,000 cached input tokens
    "candidates_per_million": 0.60,      # $0.60 per 1,000,000 response tokens (inclusive of thinking tokens)
}


@dataclass
class TokenAccounting:
    api_calls: int = 0
    prompt_tokens: int = 0
    candidates_tokens: int = 0
    thoughts_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0

    def add(
        self,
        calls: int,
        prompt: int,
        candidates: int,
        thoughts: int = 0,
        cached: int = 0,
    ) -> None:
        self.api_calls += calls
        self.prompt_tokens += prompt
        self.candidates_tokens += candidates
        self.thoughts_tokens += thoughts
        self.cached_tokens += cached
        # In Gemini usage_metadata, candidates_tokens already includes thoughts_tokens
        self.total_tokens += (prompt + candidates)
        self.estimated_cost_usd = calculate_cost_usd(
            self.prompt_tokens, self.candidates_tokens, self.cached_tokens
        )


def calculate_cost_usd(
    prompt_tokens: int,
    candidates_tokens: int,
    cached_tokens: int = 0,
    pricing: Optional[Dict[str, Any]] = None,
) -> float:
    """
    Calculate estimated API cost in USD based on official versioned Gemini 3.8 Flash pricing.

    CRITICAL BILLING RECONCILIATION:
    In the Google GenAI SDK usage_metadata, candidates_token_count ALREADY includes
    thoughts_token_count (thinking tokens). Therefore, candidates_tokens is billed
    at candidates_per_million ($0.60/1M). thoughts_tokens is collected for telemetry
    and observation transparency, but is NOT added as a separate billing term,
    preventing double-counting.
    """
    p_info = pricing or GEMINI_38_FLASH_PRICING
    unpromoted_prompt = max(0, prompt_tokens - cached_tokens)
    p_cost = (unpromoted_prompt / 1_000_000.0) * p_info["prompt_per_million"]
    cached_cost = (cached_tokens / 1_000_000.0) * p_info.get("cached_prompt_per_million", 0.0375)
    out_cost = (candidates_tokens / 1_000_000.0) * p_info["candidates_per_million"]
    return round(p_cost + cached_cost + out_cost, 6)


@dataclass
class BatchRunnerConfig:
    run_mode: str = "pilot"                       # 'pilot' or 'full'
    budget_limit_usd: float = 3.00                # Hard limit ($3 for pilot, $25 for full)
    budget_safety_buffer_usd: float = 0.20        # Stop if remaining budget < safety buffer
    request_reservation_usd: float = 0.05         # Conservative reservation for single in-flight call
    batch_pace_seconds: float = 2.0               # Delay between sequential calls
    max_retries: int = 3                          # Maximum retry attempts
    backoff_factor: float = 2.0                   # Multiplier for exponential backoff
    checkpoint_path: Optional[Path] = None        # Dynamically set per mode (live vs dry-run)
    output_dir: Path = Path("data/events/us7000pn9s/live_pilot_results")
    pricing: Dict[str, Any] = field(default_factory=lambda: GEMINI_38_FLASH_PRICING)


class BatchRunner:
    """
    Production-grade batch inference coordinator for MMI-Gram.
    """

    def __init__(
        self,
        config: Optional[BatchRunnerConfig] = None,
        dry_run: bool = False,
    ):
        self.config = config or BatchRunnerConfig()
        self.dry_run = dry_run
        self.accounting = TokenAccounting()
        self.completed_pages: Dict[str, Dict[str, Any]] = {}
        self.failed_pages: Dict[str, Dict[str, Any]] = {}
        self.skipped_pages: Dict[str, Dict[str, Any]] = {}

        self.config.output_dir.mkdir(parents=True, exist_ok=True)

        # Enforce strict separation between live and dry-run checkpoint files
        mode_suffix = "dryrun" if self.dry_run else "live"
        if self.config.checkpoint_path is None:
            self.checkpoint_path = (
                self.config.output_dir / f"batch_checkpoint_{self.config.run_mode}_{mode_suffix}.json"
            )
        else:
            self.checkpoint_path = self.config.checkpoint_path

        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_checkpoint()

    def _load_checkpoint(self) -> None:
        """Load persistent checkpoint if available."""
        if self.checkpoint_path.exists():
            try:
                with open(self.checkpoint_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.completed_pages = data.get("completed_pages", {})
                    self.failed_pages = data.get("failed_pages", {})
                    self.skipped_pages = data.get("skipped_pages", {})
                    acc_data = data.get("token_accounting", {})
                    self.accounting.api_calls = acc_data.get("api_calls", 0)
                    self.accounting.prompt_tokens = acc_data.get("prompt_tokens", 0)
                    self.accounting.candidates_tokens = acc_data.get("candidates_tokens", 0)
                    self.accounting.thoughts_tokens = acc_data.get("thoughts_tokens", 0)
                    self.accounting.cached_tokens = acc_data.get("cached_tokens", 0)
                    self.accounting.total_tokens = acc_data.get("total_tokens", 0)
                    self.accounting.estimated_cost_usd = acc_data.get("estimated_cost_usd", 0.0)
            except Exception as e:
                print(f"[Warning] Failed to load checkpoint: {e}")

    def _save_checkpoint(self) -> None:
        """Atomically persist batch state to disk."""
        data = {
            "checkpoint_updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "dry_run": self.dry_run,
            "run_mode": self.config.run_mode,
            "budget_limit_usd": self.config.budget_limit_usd,
            "token_accounting": asdict(self.accounting),
            "completed_count": len(self.completed_pages),
            "failed_count": len(self.failed_pages),
            "skipped_count": len(self.skipped_pages),
            "completed_pages": self.completed_pages,
            "failed_pages": self.failed_pages,
            "skipped_pages": self.skipped_pages,
        }
        tmp_path = self.checkpoint_path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, self.checkpoint_path)

    def is_page_completed(self, file_name: str) -> bool:
        """Check if page was already successfully processed."""
        return file_name in self.completed_pages

    def check_budget_ok(self, estimated_next_call_usd: Optional[float] = None) -> bool:
        """Verify remaining budget is sufficient for next operation."""
        reservation = (
            estimated_next_call_usd
            if estimated_next_call_usd is not None
            else self.config.request_reservation_usd
        )
        remaining = self.config.budget_limit_usd - self.accounting.estimated_cost_usd
        return remaining >= (self.config.budget_safety_buffer_usd + reservation)

    def process_batch(
        self,
        file_paths: List[Path],
        pipeline_factory: Any,
    ) -> Dict[str, Any]:
        """
        Execute batch over provided list of PDF file paths.
        """
        results: Dict[str, Any] = {}
        total_target = len(file_paths)

        print(f"\n================================================================================")
        print(f"MMI-Gram Batch Runner: {'[DRY RUN SIMULATION]' if self.dry_run else '[LIVE INFERENCE EXECUTION]'}")
        print(f"Run Mode:          {self.config.run_mode.upper()}")
        print(f"Total Documents:   {total_target}")
        print(f"Budget Limit:      ${self.config.budget_limit_usd:.2f} USD")
        print(f"Spent So Far:      ${self.accounting.estimated_cost_usd:.4f} USD")
        print(f"Output Directory:  {self.config.output_dir}")
        print(f"Checkpoint File:   {self.config.checkpoint_path}")
        print(f"================================================================================\n")

        pipeline = None
        if not self.dry_run:
            pipeline = pipeline_factory()

        for idx, path in enumerate(file_paths, 1):
            file_name = path.name
            print(f"[{idx}/{total_target}] Processing: {file_name} ...", end=" ", flush=True)

            # 1. Idempotency Check: Skip already completed documents
            if self.is_page_completed(file_name):
                print(f"[CACHED / RESUMED] (Previously analyzed, skipping duplicate call)")
                results[file_name] = self.completed_pages[file_name]
                continue

            # 2. Budget Safety Gate
            if not self.dry_run and not self.check_budget_ok():
                msg = (
                    f"\n[BUDGET LIMIT REACHED] Stopping execution safely. "
                    f"Spent ${self.accounting.estimated_cost_usd:.4f} USD against limit ${self.config.budget_limit_usd:.2f} USD."
                )
                print(msg)
                break

            # 3. Dry-Run Mode (Zero API calls, Zero Network)
            if self.dry_run:
                sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
                size_bytes = path.stat().st_size
                # Estimate tokens based on typical StEER single-page PDF
                sim_prompt_tokens = 2400
                sim_output_tokens = 450
                sim_thought_tokens = 250
                sim_cost = calculate_cost_usd(
                    prompt_tokens=sim_prompt_tokens,
                    candidates_tokens=sim_output_tokens,
                    cached_tokens=0,
                )

                sim_result = {
                    "file_name": file_name,
                    "file_path": str(path),
                    "file_size_bytes": size_bytes,
                    "sha256": sha256,
                    "status": "SIMULATED_SUCCESS",
                    "dry_run": True,
                    "simulated_token_usage": {
                        "prompt_tokens": sim_prompt_tokens,
                        "candidates_tokens": sim_output_tokens,
                        "thoughts_tokens": sim_thought_tokens,
                        "total_tokens": sim_prompt_tokens + sim_output_tokens,
                    },
                    "estimated_cost_usd": sim_cost,
                }
                self.accounting.add(
                    calls=1,
                    prompt=sim_prompt_tokens,
                    candidates=sim_output_tokens,
                    thoughts=sim_thought_tokens,
                    cached=0,
                )
                self.completed_pages[file_name] = sim_result
                results[file_name] = sim_result
                print(f"[DRY-RUN OK] Size: {size_bytes} B, Sim Cost: ${sim_cost:.5f}")
                self._save_checkpoint()
                continue

            # 4. Live Execution with Bounded Retries & Backoff
            retries = 0
            page_success = False
            last_err = None

            while retries <= self.config.max_retries and not page_success:
                try:
                    # Reset per-document telemetry so each document's provenance is exact
                    try:
                        from services.manage_model import reset_session_telemetry
                        reset_session_telemetry()
                    except ImportError:
                        pass

                    res = pipeline.process_pdf(path)

                    # Extract usage metadata
                    prov = res.get("provenance", {})
                    tokens = prov.get("token_usage", {})
                    calls = tokens.get("calls", 1)
                    p_tok = tokens.get("prompt_tokens", 0)
                    c_tok = tokens.get("candidates_tokens", 0)
                    t_tok = tokens.get("thoughts_tokens", 0)
                    cached_tok = tokens.get("cached_tokens", 0)

                    self.accounting.add(
                        calls=calls,
                        prompt=p_tok,
                        candidates=c_tok,
                        thoughts=t_tok,
                        cached=cached_tok,
                    )

                    # Save single-page output artifact
                    out_page_path = self.config.output_dir / f"{path.stem}_result.json"
                    with open(out_page_path, "w", encoding="utf-8") as f:
                        json.dump(res, f, indent=2)

                    res["result_file"] = str(out_page_path)
                    self.completed_pages[file_name] = res
                    results[file_name] = res
                    page_success = True

                    status = res.get("pipeline_status", "UNKNOWN")
                    mmi_est = res.get("seismic_intensity", {}).get("mmi_estimation")
                    mmi_str = f"MMI {mmi_est}" if mmi_est is not None else "No MMI (Screened/Deferred)"
                    print(f"[{status}] {mmi_str} | Cost So Far: ${self.accounting.estimated_cost_usd:.4f}")

                    self._save_checkpoint()

                    # Batch pacing delay
                    if self.config.batch_pace_seconds > 0 and idx < total_target:
                        time.sleep(self.config.batch_pace_seconds)

                except Exception as e:
                    last_err = str(e)
                    retries += 1
                    if retries <= self.config.max_retries:
                        delay = self.config.backoff_factor ** retries
                        print(f"[RETRY {retries}/{self.config.max_retries} in {delay:.1f}s] Error: {e}")
                        time.sleep(delay)
                    else:
                        print(f"[FAILED after {self.config.max_retries} retries] Error: {e}")
                        fail_record = {
                            "file_name": file_name,
                            "error": last_err,
                            "retries": retries,
                            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        }
                        self.failed_pages[file_name] = fail_record
                        results[file_name] = fail_record
                        self._save_checkpoint()

        # 5. Generate Batch Summary Inventory
        inventory = self._write_inventory(results)
        return inventory

    def _write_inventory(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Compile and save final research inventory."""
        inventory_path = self.config.output_dir / "batch_execution_inventory.json"
        inventory = {
            "execution_metadata": {
                "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "run_mode": self.config.run_mode,
                "dry_run": self.dry_run,
                "budget_limit_usd": self.config.budget_limit_usd,
                "total_documents_targeted": len(results),
                "total_completed": len(self.completed_pages),
                "total_failed": len(self.failed_pages),
                "token_accounting": asdict(self.accounting),
                "pricing_version": GEMINI_38_FLASH_PRICING["version"],
            },
            "documents": results,
        }
        with open(inventory_path, "w", encoding="utf-8") as f:
            json.dump(inventory, f, indent=2)
        print(f"\n[Done] Saved final batch inventory to: {inventory_path}")
        return inventory
