---
name: mmi-gram-workflow
description: Engineering and architectural guidelines for developing, testing, and extending MMI-Gram (Agentic Earthquake Intensity Estimation). Instructs AI coding agents on project conventions, schema contracts, offline safety, and test procedures.
---

# 🤖 MMI-Gram Coding Agent Skill & Development Protocol

> **IMPORTANT DISTINCTION**: This skill is a developer/coding agent meta-skill intended to instruct AI pair programmers and maintainers working on this codebase. It is NOT invoked at runtime by the LangGraph state machine. Runtime state traversal is governed by LangGraph in `src/mmigram/workflow/`.

---

## 1. Architectural Roles & Responsibilities

When developing or extending MMI-Gram, respect the strict separation of concerns across subpackages:

1. **`mmigram.core`**:
   - Contains immutable Pydantic models and data contracts (`ObservationRecord`, `Coordinates`, `QualityControlResult`, etc.).
   - All state transitions between pipeline stages must conform to these schemas.
2. **`mmigram.ingestion`**:
   - Handles physical data acquisition (PDF parsing, text extraction, checksum calculation).
   - Must handle corrupted files and image-only scanned PDFs without throwing unhandled exceptions.
3. **`mmigram.adapters`**:
   - Isolates external model and API dependencies (e.g. `CRAGAdapter` wrapping Clara's Gemini/Pinecone backend).
   - Enforces pre-flight credential checks (`check_live_prerequisites`) and gates live network calls behind explicit permission flags.
4. **`mmigram.geolocation`**:
   - Deterministic spatial extraction and validation.
   - Parses DMS / decimal coordinates from text, computes Haversine distances, and detects coordinate discrepancies.
   - **Crucial Rule**: Always preserve `document_coordinates` and `model_coordinates` separately. Never overwrite one with the other.
5. **`mmigram.qc`**:
   - Evaluates multi-rule data quality (Null Island, physical MMI range [1.0, 10.0], confidence thresholds, unestimated intensity).
   - Produces deterministic statuses: `PASSED`, `FLAGGED`, or `REJECTED`.
6. **`mmigram.review`**:
   - Implements the Human-in-the-Loop review queue.
   - Manages atomic JSON persistence so queued items survive process restarts.
   - Never auto-approve unverified high-intensity records (MMI >= 9.0).
7. **`mmigram.workflow`**:
   - Assembles components into LangGraph state graphs (`SteerOfflinePipeline`, `GeneralSteerPipeline`).
   - Replays offline fixtures in offline mode and routes live execution through adapters.
8. **`mmigram.telemetry`**:
   - Structured logging (`StructuredAgentLogger`) for node start/finish events and execution latencies.
9. **`mmigram.comparison`**:
   - Formats and exports benchmark results to standardized JSON and CSV tables.

---

## 2. Core Data Flow & Schema Contracts

```
[Input Document] 
       │
       ▼
[ingest_pdf] ──> Extracted text, page count, SHA-256 hash
       │
       ▼
[extract_mmi] ──> SeismicIntensity: {mmi_estimation, confidence, is_calibrated, reasoning}
       │
       ▼
[parse_geolocation] ──> GeographicResolution: {document_coordinates, model_coordinates, coordinates_disagree, discrepancy_distance_km}
       │
       ▼
[quality_control] ──> QualityControlResult: {status, flags, score}
       │
       ├── (PASSED) ──────────> [Auto-Approved Observation]
       └── (FLAGGED/REJECTED) ─> [human_review] ──> HumanReviewStatus: {review_required: True, triggers: [...]}
```

---

## 3. Strict Offline-First & Scientific Rigor Rules

Any agent modifying this repository MUST adhere to these non-negotiable rules:

1. **Zero Unauthorized API Calls**:
   - Default execution must ALWAYS be offline (`mode="offline"`).
   - Never call Vertex AI, Gemini, Pinecone, or GCS without explicit user opt-in (`--live` flag or `allow_live_api=True`).
   - All tests in `tests/` must run 100% offline without network dependencies.
2. **Zero Fabricated Model Estimates**:
   - Never invent or fabricate MMI estimates. If a model output is missing, malformed, or out of range, record `mmi_estimation = None` and flag as `UNESTIMATED_INTENSITY`.
   - Never fall back to arbitrary default numbers (e.g. do NOT default missing MMI to 5.0).
3. **No Synthetic Ground Truth**:
   - Clearly distinguish authentic field documents (`server/test_page1.pdf`) from synthetic test fixtures (`tests/fixtures/synthetic_*.pdf`).
   - Never present a synthetic fixture output as an authoritative scientific ground truth.
4. **Preserve Legacy Recorded Baselines**:
   - Keep the recorded StEER Page 1 baseline (`MMI 9.0`, `confidence 0.90`) intact as an observed software regression baseline.
   - Keep baseline regression tests strictly separated from scientific accuracy tests.
5. **Null Island Rejection**:
   - Coordinates at `(0.0, 0.0)` are invalid and must be flagged with `FLAG_NULL_ISLAND` and rejected.
6. **Credential Safety**:
   - Never print, log, or commit API keys or service account JSON files.
   - All credential paths and keys must be loaded via environment variables or gitignored local files.

---

## 4. Test Suite Execution & Verification

Run the full offline test suite from the repository root:

```bash
# Run all tests using unittest discovery:
python3 -m unittest discover -v -s tests -p "test_*.py"

# Or run using the unified CLI:
python3 -m mmigram.cli test
```

### Verification Checklist:
- All 53 tests must pass (52 passed, 1 skipped for live API opt-in).
- Test execution time must be under 0.5 seconds.
- No network requests should be attempted during test runs.

---

## 5. How to Extend the Pipeline for New Data Sources

To integrate a new data source (e.g., social media platforms like Reddit, Twitter/X, or Telegram):

1. **Implement Collector Interface** in `src/mmigram/ingestion/`:
   - Inherit from the base collector or social media interface.
   - Normalize ingested posts into `SocialPost` and `MediaAttachment` schemas (`src/mmigram/core/social_models.py`).
2. **Offline Fixture First**:
   - Create realistic, anonymized offline fixtures in `tests/fixtures/` with explicit `_metadata: {is_synthetic: true}` provenance.
   - Implement an offline replay mode in the connector before connecting any live API.
3. **Connect to Existing QC & Geolocation**:
   - Convert `SocialPost` attachments into standard `ObservationRecord` objects.
   - Pass through the existing `QualityControlEngine` and `GeolocationParser`.
   - Do NOT duplicate QC or coordinate parsing logic.
4. **Add Offline Integration Tests**:
   - Verify post normalization, deduplication, caption coordinate extraction, and QC routing.
