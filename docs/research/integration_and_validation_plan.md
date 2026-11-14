# 🔬 Integration, Validation, & Testing Plan: MMI-Gram 2.0

**Project:** Harvard EPS 55 Final Project (in collaboration with Clara Yoon, USGS)  
**Destination Repository:** `MMI-Gram`  
**Date:** November 14, 2026  
**Status:** Verification & Testing Blueprint  

---

## 1. Staged Implementation Plan

The integration is broken into 5 discrete phases, ordered strictly by priority, complexity, and cloud safety:

| Stage | Phase Title | Priority | Complexity | External API Cost | Primary Deliverables & Milestones |
| :---: | :--- | :---: | :---: | :---: | :--- |
| **Stage 1** | **Local Provider & Ingestion Refactoring** | Critical | Low | $0.00 (Zero) | • `GeminiProvider` abstraction (`ai_studio` default, `vertex_ai` optional).<br>• Local media byte streaming (`Part.from_bytes`), removing mandatory GCS upload.<br>• Local MMI scale definition loader (`mmi_reference.py`).<br>• Multi-format inbound scanner supporting sidecar `.txt`/`.json`. |
| **Stage 2** | **Screening Gates & Relevance Gating** | High | Medium | $0.00 (Zero in tests) | • Pre-MMI relevance gate (`page-8.pdf` -> `NOT_ESTIMABLE`).<br>• Temporal, duplicate (pHash/SHA-256), and authenticity screening gates.<br>• Routing fallible screening alerts to Human Review Queue.<br>• Excluded inputs audit logger (`excluded_inputs.json`). |
| **Stage 3** | **Geolocation Engine Unification** | High | Medium | $0.00 (Zero in tests) | • Google Maps URL expansion & parser in `mmigram.geolocation`.<br>• Configurable Google Geocoding API adapter.<br>• Strict prohibition of hypocenter fallback.<br>• Dual coordinate preservation and Haversine discrepancy checking. |
| **Stage 4** | **Finite-Fault Seismology & ShakeMap Export** | High | Medium | $0.00 (Zero) | • Port `rrup_calculator.py` into `mmigram.seismology.rrup`.<br>• Port `PhysicsCritic` into `mmigram.seismology.physics_critic`.<br>• Port `ShakeMapExporter` to output official ShakeMap v4 `*_dat.json`.<br>• Port `ShakeMapComparator` to download ComCat data and compute residuals. |
| **Stage 5** | **Embedded Database & Paired Benchmarking** | Medium | High | Deferred (Requires explicit approval) | • Embedded DuckDB / SQLite repository (`LocalStorageRepository`).<br>• Unified CLI command: `mmigram batch --event-id ...`.<br>• Paired benchmark execution against Clara's reported Myanmar StEER pages (after approval). |

---

## 2. Dependency & Security Migration Plan

### 1. Python Dependencies
The existing virtual environment (`.clean_venv`) already contains core packages (`google-genai`, `langchain`, `langgraph`, `pydantic`, `pypdf`, `numpy`, `pillow`).

To support the integrated capabilities cleanly:
- **`duckdb`**: Optional high-performance analytical storage. If absent, the repository gracefully falls back to standard library `sqlite3`.
- **`imagehash`**: Optional perceptual hashing for recycled media detection. If absent, falls back to SHA-256 of the first 64KB.
- **`google-genai`**: Official Google GenAI SDK (already installed at version `2.34.0`).
- **`urllib` / standard library**: All USGS ComCat queries, Google Maps unshortening, and 3D vector geometry use standard library math and networking, minimizing fragile external dependencies.

### 2. Credential & Secret Safety Protocols
- **Strict Prohibition**: API keys, service account JSON files, `.env` files, and signed URLs **must never be committed to Git**.
- **Supported Environment Variables**:
  - `GEMINI_API_KEY` or `GOOGLE_API_KEY`: Used by AI Studio backend.
  - `GOOGLE_MAPS_API_KEY`: Optional; used for Google Geocoding API.
  - `TAVILY_API_KEY`: Optional; used for web search fallback.
  - `projectID` / `GCS_PROJECT_ID` / `GOOGLE_APPLICATION_CREDENTIALS`: Optional; used only if Vertex AI backend is explicitly selected.
- **Redaction**: All CLI logs, trace files, and exported artifacts pass through `_sanitize_for_display()` to strip sensitive tokens and query parameters.

---

## 3. Scientific Validation Plan: Clara's Myanmar StEER Benchmark

### 1. Reported Benchmark Outputs
Clara reports the following evaluations from her preliminary Myanmar StEER testing (`data/events/us7000pn9s/agent_evaluations.json`):

| Target File | Description / Location | Clara Reported MMI | Reported Confidence | Reported $R_{rup}$ (km) | Building / Damage Type |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **`page-026.pdf`** | Sagaing city | **9.5** | 0.92 (or 0.95 in JSON) | 0.02 km | Surface fault rupture + RC/masonry collapse |
| **`page-034.pdf`** | Mandalay / Sagaing | **9.5** | 0.85 | ~0.05 km | Severe structural damage / collapse |
| **`page-062.pdf`** | Mandalay corridor | **9.0** | 0.85 | ~0.50 km | Commercial/residential failure |
| **`page-070.pdf`** | Sagaing | **8.5** | 0.88 | ~1.20 km | Brick masonry partial collapse |
| **`page-097.pdf`** | Regional corridor | **9.0** | 0.95 | ~0.80 km | High intensity ground deformation |
| **`page-157.pdf`** | Outlying township | **8.0** | 0.85 | ~5.40 km | Moderate-to-severe structural cracking |
| **`page-179.pdf`** | Distant township | **7.0** | 0.85 | ~14.2 km | Negligible structural damage; non-structural cracks |
| **`page-187.pdf`** | Distant township | **6.5** | 0.85 | ~22.0 km | Strong shaking; fallen plaster |

> [!IMPORTANT]
> **Scientific Caveat**:
> These reported values are preserved strictly as **benchmark reference outputs** from Clara's research prototype, **NOT as authoritative ground truth**. In seismic engineering, an LLM's output cannot serve as ground truth for itself. Ground truth requires independent post-earthquake field reconnaissance by licensed structural engineers or USGS macroseismic consensus.

### 2. Paired Comparison Methodology
When live testing is authorized by the user, the validation experiment will run under identical, tightly controlled conditions:
- **Same Input Files**: Identical StEER PDF pages from `data/events/us7000pn9s/inbound/`.
- **Same Model Version**: `gemini-3.8-flash`.
- **Same Thinking Level**: `HIGH` thinking.
- **Provider**: Google AI Studio backend (`provider="ai_studio"`).
- **Retrieval Mode**: Deterministic local full-scale MMI definitions (I to X).
- **Evaluation Metrics**:
  1. $\Delta\text{MMI} = \text{MMI}_{\text{unified}} - \text{MMI}_{\text{Clara}}$
  2. Discrepancy in extracted coordinates (km).
  3. Consistency of $R_{rup}$ distance calculation.
  4. Accuracy in distinguishing surface fault rupture vs. inertial shaking damage.

### 3. Negative, Adversarial, & Edge Case Testing Plan
To prove scientific defensibility, the pipeline will be tested on challenging negative cases:
- **Case 1: Administrative / Irrelevant Slide (`page-8.pdf`)**:
  - Contains overview text, maps, or methodology without damage photos.
  - **Expected Outcome**: `status: "NOT_ESTIMABLE"`, `mmi_estimation: None`, `reason: "NO_OBSERVABLE_DAMAGE_PHOTOS"`.
  - **Failure Condition**: Inventing a numeric MMI (e.g. 0.0, 5.0, or 6.0).
- **Case 2: Missing Observation Location (`synthetic_steer_page3_no_coords.pdf`)**:
  - StEER report describing severe shaking but omitting coordinates and mapping links.
  - **Expected Outcome**: `coordinates: None`, `location: "Unknown"`, flagged with `COORDINATES_UNAVAILABLE`, enqueued in Human Review Queue.
  - **Failure Condition**: Defaulting to hypocenter $(21.95, 96.10)$ or Null Island $(0.0, 0.0)$.
- **Case 3: Malformed / Corrupted PDF (`synthetic_corrupt.pdf`)**:
  - Non-PDF or truncated byte stream.
  - **Expected Outcome**: `status: "INVALID_PDF"`, logged gracefully without crashing.
- **Case 4: Scanned Image-Only PDF (`synthetic_image_only_scanned.pdf`)**:
  - PDF without embedded text layer.
  - **Expected Outcome**: Successfully falls back to OCR/multimodal image analysis, preserving document coordinates as unavailable.

---

## 4. Testing Strategy: Preserving 105 Passing Tests

MMI-Gram currently has 105 passing tests in `tests/`:
- `tests/test_gemini_38_migration.py` (12 tests)
- `tests/test_general_steer_pipeline.py` (9 tests)
- `tests/test_geolocation.py` (9 tests)
- `tests/test_human_review_queue.py` (7 tests)
- `tests/test_location_comparison.py` (10 tests)
- `tests/test_mmi_retrieval.py` (21 tests)
- `tests/test_quality_control.py` (7 tests)
- `tests/test_reddit_connector.py` (7 tests)
- `tests/test_regression_page1.py` (8 tests)
- `tests/test_security_redaction.py` (9 tests)
- `tests/test_social_interface.py` (2 tests)
- `tests/test_steer_offline_pipeline.py` (3 tests)
- `tests/test_workflow_logging.py` (2 tests)

### Testing Strategy Rules:
1. **Zero Breaking Changes to Existing Test Suite**: Every existing test must continue to pass with 0 regressions.
2. **Offline-First Fixture Verification**: All new tests must use offline mocks, synthetic GeoJSON fault fixtures, or recorded baseline JSON fixtures.
3. **Execution Command**:
   ```bash
   PYTHONPATH="src:server:.clean_venv/lib/python3.13/site-packages" /opt/anaconda3/bin/pytest tests
   ```
4. **New Test Modules to Add**:
   - `tests/test_rrup_calculator.py`: Validates 3D finite-fault point-to-triangle calculations against known synthetic geometries.
   - `tests/test_shakemap_exporter.py`: Validates USGS ShakeMap v4 GeoJSON formatting and intensity standard deviation calculations.
   - `tests/test_google_maps_resolver.py`: Validates URL unshortening and regex coordinate extraction.
   - `tests/test_relevance_gate.py`: Validates that non-damage slides (`page-8.pdf`) yield `NOT_ESTIMABLE` without invoking the model.
