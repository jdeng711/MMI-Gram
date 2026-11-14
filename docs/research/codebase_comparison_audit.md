# 🔍 Detailed Codebase Comparison Audit: MMI-Gram vs. QuakeLLMmap (`quake_agent`)

**Author:** Harvard EPS 55 Research Team (in collaboration with Clara Yoon, USGS)  
**Date:** November 14, 2026  
**Primary Repository (Destination):** `MMI-Gram` (`MMI-Gram-Clean`)  
**Base Commit:** `f09dc56fa1e1d10f24cf91274bf639dc9eb715f4` (`feature/quake-agent-integration`)  
**Reference Repository (Source):** `QuakeLLMmap` (`QuakeLLMmap-reference`)  
**Reference Commit:** `8681216c56a850e3455fb5a78685adbd8980978f` (`main`)  

---

## 1. Executive Summary & Audit Context

This audit evaluates the actual implementation of **MMI-Gram** (`src/mmigram/`, `server/services/`) and Clara Yoon's **`quake_agent`** (`quake_agent/`, `scripts/`) to design a unified, scientifically defensible earthquake intensity (MMI) estimator.

The audit is strictly grounded in source code inspection, verified line numbers, and behavioral execution. Both systems address the challenge of extracting macroseismic intensity (Modified Mercalli Intensity, MMI) from post-earthquake reconnaissance data—specifically StEER (Structural Extreme Events Reconnaissance) field briefing reports for the **28 March 2025 $M_w$ 7.7 Mandalay, Myanmar earthquake** (`us7000pn9s`).

### Core Design Philosophy Comparison
- **MMI-Gram**: Built on a modular **LangGraph** architecture emphasizing scientific integrity, deterministic quality control, separate preservation of document versus model coordinates, strict offline testability (105 passing unit/regression tests), and a persistent Human-in-the-Loop (HITL) review queue.
- **quake_agent**: Built on an iterative pipeline emphasizing local-first ingestion via Google AI Studio API keys, multi-gate pre-filtering (temporal, spatial, duplicate, authenticity), 3D finite-fault distance ($R_{rup}$) computation, and direct export to the official USGS ShakeMap v4 input format (`*_dat.json`).

---

## 2. Feature-by-Feature Deep Dive (14 Dimensions)

### Feature 1: Input Ingestion & Event Directory Conventions

#### 1. MMI-Gram Current Implementation
- **Source Files:** [`src/mmigram/ingestion/pdf_extractor.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/src/mmigram/ingestion/pdf_extractor.py#L33-L145), [`src/mmigram/workflow/general_steer_pipeline.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/src/mmigram/workflow/general_steer_pipeline.py#L90-L143)
- **Mechanism:** Ingestion handles PDFs using `pypdf.PdfReader`. Computes cryptographic SHA-256 integrity hashes for every file. Detects scanned image-only PDFs (`min_text_threshold=25` characters) and flags them as `SCANNED_IMAGE_ONLY` without throwing unhandled exceptions.
- **Directory Structure:** Organizes data under `data/events/<event_id>/` with `inbound/`, `baseline/`, and `results/`.
- **Limitations:** Focuses primarily on PDFs; lacks automated ingestion for standalone images, videos, and sidecar text/metadata files.

#### 2. quake_agent Current Implementation
- **Source Files:** [`quake_agent/harvesters/pdf_extractor.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/harvesters/pdf_extractor.py#L1-L105), [`quake_agent/harvesters/local_watcher.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/harvesters/local_watcher.py#L1-L77), [`quake_agent/config.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/config.py#L24-L74)
- **Mechanism:** Scans `data/events/<event_id>/inbound/` for `.pdf`, `.jpg`, `.png`, `.mp4`, `.mov`, and `.txt`. Crucially, checks for accompanying sidecar text/metadata files (e.g., `photo.jpg` + `photo.txt` or `photo.json`). Reads an explicit `event_config.json` containing hypocenter, magnitude, bounding box, regional languages, townships, and fault trace files.
- **Limitations:** Does not compute cryptographic hashes; does not flag image-only scanned PDFs as a structured data state.

#### 3. Strength Assessment & Recommendation
- **Stronger Implementation:** **Combine**. MMI-Gram's `PDFExtractor` is much stronger for PDF integrity, scanned-document detection, and hash provenance. `quake_agent`'s `event_config.json` and sidecar text/metadata scanner provide superior multimodal event flexibility.
- **Action:** Adapt `quake_agent`'s `EventConfig` and sidecar scanner into MMI-Gram's `mmigram.ingestion`, retaining MMI-Gram's SHA-256 hashing and scanned-PDF detection.
- **Required Regression Tests:** Tests verifying PDF extraction, image-only detection, corrupted file handling, sidecar `.txt`/`.json` reading, and `EventConfig` loading.

---

### Feature 2: Google AI Studio vs. Vertex AI Authentication

#### 1. MMI-Gram Current Implementation
- **Source Files:** [`server/services/manage_model.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/server/services/manage_model.py#L24-L37), [`server/services/utilities.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/server/services/utilities.py#L11-L40)
- **Mechanism:** Strictly configured for Google Cloud Vertex AI:
  ```python
  _client = genai.Client(
      vertexai=True,
      project=project_id,
      location=location,
      credentials=credentials,
  )
```
- **Limitations:** Requires active GCP service account JSON, Google Cloud project ID, billing, and IAM permissions. Makes local open-source setup cumbersome for collaborators like Clara without access to the same GCP project.

#### 2. quake_agent Current Implementation
- **Source Files:** [`quake_agent/seismology/gemini_bridge.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/seismology/gemini_bridge.py#L25-L59), [`quake_agent/config.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/config.py#L90-L101)
- **Mechanism:** Configured for Google AI Studio API-key authentication:
  ```python
  client = genai.Client(
      api_key=self.api_key, http_options={"timeout": int(self.timeout * 1000)}
  )
```
  Loads `GEMINI_API_KEY` or `GOOGLE_API_KEY` from `.env`. Includes a raw HTTP REST fallback via `urllib.request`.
- **Limitations:** Silent HTTP REST fallback lacks granular telemetry; mixing AI Studio and Vertex AI ad-hoc leads to configuration confusion.

#### 3. Strength Assessment & Recommendation
- **Stronger Implementation:** **Adapt & Unify**. Google AI Studio API-key authentication is vastly superior for local development, reproducible science, and researcher onboarding. Vertex AI must be preserved as an explicit enterprise/cloud backend.
- **Action:** Build a clean `GeminiProvider` abstraction:
  - Default: `provider="ai_studio"` using `GEMINI_API_KEY`.
  - Optional: `provider="vertex_ai"` using ADC / Service Account.
  - **Rule:** Explicit selection only; never silently switch providers or authenticate without user opt-in.
- **Required Regression Tests:** Mocked credential loader tests verifying AI Studio client construction, Vertex AI client construction, missing key error messaging, and zero network calls when credentials are absent.

---

### Feature 3: Gemini Model Configuration, HIGH Thinking, & Generation Parameters

#### 1. MMI-Gram Current Implementation
- **Source Files:** [`server/services/manage_model.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/server/services/manage_model.py#L68-L130), [`tests/test_gemini_38_migration.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/tests/test_gemini_38_migration.py#L35-L95)
- **Mechanism:** Implements state-of-the-art configuration for Gemini 3.8 Flash HIGH thinking:
  - `SUPPORTED_THINKING_LEVELS_38 = {"HIGH", "MEDIUM", "LOW"}` (rejects invalid levels like `MINIMAL`).
  - Sets `thinking_config = types.ThinkingConfig(thinking_level="HIGH")`.
  - Strictly omits deprecated sampling parameters (`temperature`, `top_p`, `top_k`, `candidate_count`) when extended thinking is enabled, avoiding API contract violations.
  - Tracks thought token usage (`thoughts_tokens`) separately from output tokens.
- **Limitations:** None; rigorous and validated by 12 dedicated tests.

#### 2. quake_agent Current Implementation
- **Source Files:** [`quake_agent/seismology/gemini_bridge.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/seismology/gemini_bridge.py#L32-L38, #L61-L106, #L146-L155)
- **Mechanism:** Sets `thinking_level="low"` by default. Sets `temperature=0.2`.
- **Critical Flaw:** If an upstream rate limit (429) or overload (503) occurs, it **silently fails over** to other models:
  ```python
  models_to_try = [
      self.model_name,
      candidate,
      "gemini-3.6-flash",
      "gemini-3.5-flash-lite",
  ]
```
  Furthermore, if media processing fails, it silently retries with text-only prompts, stripping the visual damage evidence!
- **Scientific Impact:** Silent model switching and payload degradation destroy scientific reproducibility. An MMI estimate produced by `gemini-3.5-flash-lite` with low thinking on text-only captions is not comparable to one produced by `gemini-3.8-flash` HIGH thinking on multimodal imagery!

#### 3. Strength Assessment & Recommendation
- **Stronger Implementation:** **MMI-Gram is far superior**. MMI-Gram's strict adherence to Gemini 3.8 Flash HIGH thinking, explicit thinking config, and rejection of silent failover protects scientific defensibility.
- **Action:** Retain MMI-Gram's `manage_model.py` generation configuration. Enforce `gemini-3.8-flash` with HIGH thinking as the primary scientific standard. Require explicit configuration flags if fallback models are tested.
- **Required Regression Tests:** Preserve all 12 tests in `tests/test_gemini_38_migration.py`.

---

### Feature 4: Local PDF/Image Processing vs. Cloud GCS Uploads

#### 1. MMI-Gram Current Implementation
- **Source Files:** [`server/services/crag.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/server/services/crag.py#L206-L208, #L244-L281), [`src/mmigram/workflow/general_steer_pipeline.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/src/mmigram/workflow/general_steer_pipeline.py#L206-L208)
- **Mechanism:** Uploads each local PDF to a Google Cloud Storage bucket (`quakemap-media-data`) via `upload_to_gcs()`, generating a signed URL before Vertex AI can process it.
- **Limitations:** Creates a mandatory dependency on GCS bucket write permissions, generates cloud billing, requires network upload latency, and introduces URL redaction complexity.

#### 2. quake_agent Current Implementation
- **Source Files:** [`quake_agent/seismology/gemini_bridge.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/seismology/gemini_bridge.py#L135-L139, #L199-L201)
- **Mechanism:** Reads local file bytes directly from disk:
  ```python
  data = Path(media_path).read_bytes()
  mime_type = self._detect_mime(media_path)
  contents.append(types.Part.from_bytes(data=data, mime_type=mime_type))
```
- **Limitations:** None for local files under standard Gemini upload limits (up to 20MB inline, or Gemini File API for larger videos).

#### 3. Strength Assessment & Recommendation
- **Stronger Implementation:** **quake_agent is superior**. Inlining bytes directly into `types.Part.from_bytes()` eliminates GCS entirely from the local path.
- **Action:** Replace mandatory GCS uploads with direct local file reading via `types.Part.from_bytes()` in the primary workflow. Retain GCS upload utilities as an optional cloud adapter.
- **Required Regression Tests:** Unit tests verifying `Part.from_bytes` creation for local PDFs and images without GCS client initialization.

---

### Feature 5: LangGraph Agent Architecture & Prompts

#### 1. MMI-Gram Current Implementation
- **Source Files:** [`src/mmigram/workflow/graph.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/src/mmigram/workflow/graph.py#L33-L151), [`server/services/crag.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/server/services/crag.py#L138-L163)
- **Mechanism:** Implements a formal LangGraph StateGraph:
  - Node 1: `initial_analysis` (multimodal media inspection)
  - Node 2: `retrieve_docs` (MMI reference retrieval)
  - Node 3: `grade_documents` (evaluates reference relevance)
  - Conditional Edge: routes to `transform_query` -> `web_search` if references are inadequate, or directly to `final_analysis`
  - Node 6: `final_analysis` (structured seismic synthesis)
  - Node 7: `validate_geolocation`
  - Node 8: `evaluate_qc`
  - Node 9: `human_review_gate`
- **Limitations:** Legacy CRAG components in `server/services/crag.py` were tightly coupled with Vertex AI and Pinecone.

#### 2. quake_agent Current Implementation
- **Source Files:** [`quake_agent/core/orchestrator.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/core/orchestrator.py#L28-L245), [`quake_agent/seismology/mmi_assessor.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/seismology/mmi_assessor.py#L42-L137)
- **Mechanism:** Implements a linear procedural script: Harvester -> Gates -> MMIAssessor -> PhysicsCritic -> DuckDB -> ShakeMap.
  - In `mmi_assessor.py`, it executes a 2-pass prompt:
    1. Pass 1: Visual/auditory description prompt with explicit instruction to extract "Geolocation (Address/Coordinates)".
    2. Pass 2: Final synthesis prompt with structured JSON schema (`SEISMIC_ANALYSIS_SCHEMA`).
- **Prompt Differences:**
  - `quake_agent` prompt explicitly instructs:
    ```
    CRITICAL GEOLOCATION EXTRACTION:
    - Inspect the file for any section labeled "Geolocation (Address/Coordinates)".
    - Look for any latitude/longitude coordinates (DMS or decimal) or map links.
    - Relevant damage photos (has_damage_photos): Set to True if the file contains actual photographs/visuals of earthquake damage. Set to False if the file is only a title slide, author credits, or overview text.
    ```
  - `MMI-Gram` prompt focused heavily on structural collapse vs. shaking damage, but lacked explicit instruction on the StEER "Geolocation (Address/Coordinates)" header format and the explicit `has_damage_photos` flag.

#### 3. Strength Assessment & Recommendation
- **Stronger Implementation:** **Combine**. MMI-Gram's LangGraph state machine is architecturally far superior (modular, inspectable, conditional, replayable). `quake_agent`'s refined prompts for StEER report conventions (`has_damage_photos`, Geolocation block extraction) are more effective at extracting StEER-specific cues.
- **Action:** Embed `quake_agent`'s refined system prompts and schemas into MMI-Gram's LangGraph nodes.
- **Required Regression Tests:** Workflow graph traversal tests verifying state transitions, node execution, and prompt formatting.

---

### Feature 6: Input Filtering, Timestamp Checks, Synthetic Media, & Relevance Assessment

#### 1. MMI-Gram Current Implementation
- **Source Files:** [`src/mmigram/ingestion/pdf_extractor.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/src/mmigram/ingestion/pdf_extractor.py#L80-L115), [`src/mmigram/qc/checker.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/src/mmigram/qc/checker.py#L40-L125)
- **Mechanism:** Filters corrupted PDFs and image-only scanned PDFs at ingestion. Filters Null Island and invalid ranges at QC.
- **Limitations:** Lacks pre-filtering for publication timestamps, duplicate images, or synthetic media before invoking the LLM. Does not have a dedicated pre-MMI relevance gate to screen out briefing cover slides (e.g., Clara's `page-8.pdf`).

#### 2. quake_agent Current Implementation
- **Source Files:** [`quake_agent/gates/temporal_gate.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/gates/temporal_gate.py#L8-L57), [`quake_agent/gates/spatial_gate.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/gates/spatial_gate.py#L5-L39), [`quake_agent/gates/recycled_gate.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/gates/recycled_gate.py#L6-L45), [`quake_agent/gates/authenticity_gate.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/gates/authenticity_gate.py#L21-L65), [`quake_agent/core/orchestrator.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/core/orchestrator.py#L164-L220)
- **Mechanism:** Implements 4 distinct verification gates:
  1. `TemporalGate`: Extracts EXIF `DateTimeOriginal` from images; checks timestamp against earthquake origin time $T_0$ (allows 5-min drift).
  2. `RecycledMediaGate`: Computes perceptual hash (pHash) or SHA-256 to detect duplicate media.
  3. `AuthenticityGate`: Forensic Gemini prompt checking for AI diffusion artifacts, impossible architectural geometries, and pseudotext.
  4. `SpatialGate`: Checks bounding box $[-90, 90] \times [-180, 180]$ and regional township keywords.
  - Step 5b: Checks `has_damage_photos`.
- **Critical Flaws in quake_agent:**
  1. Irrelevant files (like `page-8.pdf`) are evaluated *after* running two expensive Gemini calls! It sets `mmi_estimation: 0.0`, wasting money, time, and tokens.
  2. Gate failures unconditionally drop items (`status == REJECTED; continue`), losing provenance and preventing human review.
  3. Automated authenticity checks are treated as binary truth, which can falsely reject authentic field photos.

#### 3. Strength Assessment & Recommendation
- **Stronger Implementation:** **Combine & Elevate**.
  - Move the relevance gate **before** MMI estimation. If a document page is a title slide, map index, or methodology page without observable damage, immediately classify it as `NOT_ESTIMABLE` with reason `NO_OBSERVABLE_DAMAGE_PHOTOS`.
  - Treat authenticity and temporal gates as **fallible screening indicators**, recording audit metrics and routing ambiguous cases to MMI-Gram's Human Review Queue.
- **Required Regression Tests:** Tests verifying:
  - Irrelevant page detection (`page-8.pdf`) yielding `NOT_ESTIMABLE`.
  - Duplicate detection via hash.
  - Pre-origin timestamp detection.
  - Enqueueing flagged items into the review queue.

---

### Feature 7: MMI Reference Retrieval & Full-Scale Definitions

#### 1. MMI-Gram Current Implementation
- **Source Files:** [`server/services/MMIRetriever.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/server/services/MMIRetriever.py#L14-L77, #L111-L167), [`tests/test_mmi_retrieval.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/tests/test_mmi_retrieval.py#L25-L120)
- **Mechanism:** Supports two modes:
  1. `full_scale`: Deterministically fetches all 10 MMI definitions (I to X) in read-only mode, with strict completeness validation (`validate_scale_completeness`).
  2. `vector_search`: Pinecone Serverless embedding search (`llama-text-embed-v2`, 1024 dims).
- **Limitation:** In `MMIRetriever.py`, `full_scale` currently calls `self.index.fetch(ids=ids)` against Pinecone! If Pinecone credentials are not configured, it returns an empty list, triggering web search or failing.

#### 2. quake_agent Current Implementation
- **Source Files:** [`quake_agent/seismology/local_mmi_kb.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/seismology/local_mmi_kb.py#L5-L92), [`quake_agent/seismology/pinecone_retriever.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/seismology/pinecone_retriever.py#L1-L70)
- **Mechanism:** Implements `LocalMMIKnowledgeBase` with `USGS_MMI_DEFINITIONS` embedded directly in Python code (covering MMI I through XII). Computes local keyword overlap scoring without any network calls.

#### 3. Strength Assessment & Recommendation
- **Stronger Implementation:** **Combine**.
  - Local asset `server/assets/mmi_definitions.txt` already exists in MMI-Gram!
  - By loading the full 10-level (or 12-level) MMI definitions directly from `server/assets/mmi_definitions.txt` or a versioned JSON resource, full-scale retrieval becomes **100% offline, zero-cost, and deterministic**, completely eliminating the mandatory dependency on Pinecone!
  - Retain Pinecone as an optional adapter for research experiments comparing full-scale prompting against semantic RAG.
- **Required Regression Tests:** Tests verifying local scale completeness (I-X or I-XII), keyword retrieval, and graceful offline fallback.

---

### Feature 8: Geolocation from PDF Text, Coordinates, & Google Maps URLs

#### 1. MMI-Gram Current Implementation
- **Source Files:** [`src/mmigram/geolocation/parser.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/src/mmigram/geolocation/parser.py#L10-L141), [`src/mmigram/geolocation/validator.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/src/mmigram/geolocation/validator.py#L42-L177), [`tests/test_geolocation.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/tests/test_geolocation.py#L20-L115)
- **Mechanism:**
  - Robust regex parsing for DMS (`21°52'49.27"N, 95°59'5.57"E`) and decimal degrees with cardinal directions.
  - Strict validation: rejects Null Island `(0.0, 0.0)`, enforces regional bounds (Myanmar: `[9, 29] N`, `[91, 102] E`).
  - **Core Architectural Invariant:** Strictly preserves `document_coordinates` and `model_coordinates` as separate schema fields. Computes Haversine distance and detects discrepancies (> 10 km).
- **Limitations:** Lacks extraction for Google Maps shortened URLs (`maps.app.goo.gl`) and Google Geocoding API integration.

#### 2. quake_agent Current Implementation
- **Source Files:** [`quake_agent/seismology/geolocation_resolver.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/seismology/geolocation_resolver.py#L23-L250, #L400-L719), [`quake_agent/seismology/mmi_assessor.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/seismology/mmi_assessor.py#L157-L182)
- **Mechanism:**
  - Extracts coordinates from text (DMS, directional decimal, plain decimal).
  - Inspects Google Maps, OpenStreetMap, Apple Maps, Bing Maps, and `geo:` URIs.
  - Unshortens `maps.app.goo.gl` links and queries the Google Geocoding API using `GOOGLE_MAPS_API_KEY`.
  - Extracts EXIF GPS from local JPEG images.
  - Extracts surrounding address strings preceding the map link.
- **Critical Flaw in quake_agent:**
  - In `mmi_assessor.py` lines 170-176:
    ```python
    else:
      lat = self.event.hypocenter.get("latitude")
      lon = self.event.hypocenter.get("longitude")
      loc_name = (
          self.event.townships[0]
          if self.event.townships
          else "Epicentral Area"
      )
      loc_precision = "hypocenter_fallback"
```
    **Substituting the earthquake hypocenter for missing observation coordinates is scientifically unacceptable.** An observation with unknown location placed at the epicenter will artificially bias ShakeMap ground motion interpolation.

#### 3. Strength Assessment & Recommendation
- **Stronger Implementation:** **Combine**.
  - Adopt `quake_agent`'s Google Maps link extractor, URL unshortener, and Google Geocoding API integration (as an optional external service).
  - Strictly enforce MMI-Gram's invariant: **Never substitute the event epicenter for missing observation coordinates.** If coordinates cannot be resolved, record `latitude: None`, `longitude: None`, flag as `COORDINATES_UNAVAILABLE`, and route to Human Review.
  - Preserve `document_coordinates` and `model_coordinates` separately.
- **Required Regression Tests:** Tests verifying DMS extraction, decimal extraction, Google Maps URL unshortening, geocoding mock fallback, Null Island rejection, and no-hypocenter substitution.

---

### Feature 9: Output Schema & Event/Site-Level Observation Identifiers

#### 1. MMI-Gram Current Implementation
- **Source Files:** [`src/mmigram/core/state.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/src/mmigram/core/state.py#L30-L240), [`src/mmigram/comparison/comparator.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/src/mmigram/comparison/comparator.py#L20-L150)
- **Mechanism:** Immutable Pydantic models: `Coordinates`, `MMIEstimationResult`, `StructuralDamageAssessment`, `LocationContext`, `QualityControlRecord`, `ObservationRecord`. Exports to standardized JSON and tabular CSV.
- **Limitations:** Does not have a native method to export to the USGS ShakeMap v4 non-instrumented macroseismic observation JSON format (`*_dat.json`).

#### 2. quake_agent Current Implementation
- **Source Files:** [`quake_agent/core/models.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/core/models.py#L63-L144), [`quake_agent/shakemap/exporter.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/shakemap/exporter.py#L7-L36)
- **Mechanism:** Implements `SeismicEvaluation.to_shakemap_feature()`:
  ```python
  return {
      "type": "Feature",
      "id": f"MMI.{code}",
      "properties": {
          "code": code,
          "name": self.location_name or "AI Eyewitness Observation",
          "network": "MMI",
          "netid": "MMI",
          "station_type": "macroseismic",
          "channels": [],
          "nresp": 1,
          "source": "QuakeLLMmap Agentic Reconnaissance",
          "intensity": round(self.mmi_estimation, 1),
          "intensity_stddev": stddev,
          "intensity_flag": "0",
          "file_name": self.file_name,
          "model_name": self.model_name,
          "rrup_km": round(self.rrup_km, 2)
          if self.rrup_km is not None
          else None,
          "building_type": self.building_type,
      },
      "geometry": {
          "type": "Point",
          "coordinates": [self.longitude, self.latitude],
      },
  }
```
  Directly compatible with USGS ShakeMap v4 `shake assemble`.

#### 3. Strength Assessment & Recommendation
- **Stronger Implementation:** **Combine**. MMI-Gram's core state models provide superior type-safety and field validation. `quake_agent`'s ShakeMap v4 feature mapping is the exact standard required for USGS integration.
- **Action:** Add `to_shakemap_feature()` and `export_shakemap_dat_json()` to MMI-Gram's export pipeline.
- **Required Regression Tests:** Tests verifying GeoJSON FeatureCollection structure, coordinate order (`[lon, lat]`), station properties, and schema conformity.

---

### Feature 10: MMI Confidence & Scientific Uncertainty

#### 1. MMI-Gram Current Implementation
- **Source Files:** [`src/mmigram/core/state.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/src/mmigram/core/state.py#L90-L115), [`src/mmigram/qc/checker.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/src/mmigram/qc/checker.py#L80-L95)
- **Mechanism:** Explicitly tags raw model confidence with `is_calibrated=False`. Flags raw confidence $< 0.60$ as `LOW_CONFIDENCE`. Strictly separates LLM self-reported confidence from empirical ground-motion uncertainty.

#### 2. quake_agent Current Implementation
- **Source Files:** [`quake_agent/core/models.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/core/models.py#L93-L94)
- **Mechanism:** Computes observation standard deviation (`intensity_stddev`) from model confidence:
  $$\sigma_{\text{MMI}} = 0.35 + (1.0 - \text{confidence}) \times 0.70$$
  This scales uncertainty smoothly between $\sigma = 0.35$ (for $\text{confidence} = 1.0$) and $\sigma = 1.05$ (for $\text{confidence} = 0.0$), matching the uncertainty range expected by ShakeMap v4 point-observation weighting.

#### 3. Strength Assessment & Recommendation
- **Stronger Implementation:** **Combine**.
  - Keep MMI-Gram's explicit disclaimer that raw model confidence is uncalibrated.
  - Adopt Clara's uncertainty formula for generating `intensity_stddev` in ShakeMap exports.
- **Required Regression Tests:** Tests verifying stddev bounds $[0.35, 1.05]$ across varying confidence levels.

---

### Feature 11: Automated QC, Human Review, & Error Handling

#### 1. MMI-Gram Current Implementation
- **Source Files:** [`src/mmigram/qc/checker.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/src/mmigram/qc/checker.py#L40-L125), [`src/mmigram/review/queue.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/src/mmigram/review/queue.py#L30-L245)
- **Mechanism:** Multi-rule deterministic engine:
  - Null Island rejection `(0.0, 0.0)`
  - Physical MMI range verification $[1.0, 10.0]$
  - Low confidence flagging ($< 0.60$)
  - Spatial discrepancy check (> 10 km)
  - Missing/unestimated MMI check
  - High-intensity anomaly verification ($\text{MMI} \ge 9.0$)
  - Persistent JSON review queue (`data/review_queue.json`) with atomic write replacements surviving process restarts.
  - Review queue audit actions: `approve`, `override`, `reject`.

#### 2. quake_agent Current Implementation
- **Source Files:** [`quake_agent/core/orchestrator.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/core/orchestrator.py#L203-L207)
- **Mechanism:** Prints console messages when a gate rejects an item. No persistent review queue or interactive resolution mechanism.

#### 3. Strength Assessment & Recommendation
- **Stronger Implementation:** **MMI-Gram is vastly superior**. A production-grade scientific pipeline must not drop uncertain observations silently. MMI-Gram's QC and review queue must remain the foundational verification backbone.
- **Action:** Retain MMI-Gram's QC and review queue unchanged, feeding newly gated items into it.
- **Required Regression Tests:** Preserve all tests in `tests/test_quality_control.py` and `tests/test_human_review_queue.py`.

---

### Feature 12: Caching, Batching, Rate Limits, Token Accounting, & API Cost

#### 1. MMI-Gram Current Implementation
- **Source Files:** [`server/services/manage_model.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/server/services/manage_model.py#L12-L22, #L180-L230), [`src/mmigram/telemetry/tracer.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/src/mmigram/telemetry/tracer.py#L1-L150)
- **Mechanism:** Cumulative token telemetry:
  - Tracks `calls`, `prompt_tokens`, `candidates_tokens`, `thoughts_tokens`, `total_tokens`.
  - Exponential backoff retry on `ResourceExhausted` and `TooManyRequests`.
  - Turn-by-turn latency measurement.
- **Limitations:** Legacy CRAG traversal made multiple sequential LLM calls (initial analysis, document grading for each document with 1-second sleeps, query transform, final analysis), creating significant latency and quota consumption.

#### 2. quake_agent Current Implementation
- **Source Files:** [`quake_agent/seismology/mmi_assessor.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/seismology/mmi_assessor.py#L88-L144), [`quake_agent/cli.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/cli.py#L30-L75)
- **Mechanism:**
  - Optimized to 2 Gemini calls: (1) Freeform media description, (2) Final structured synthesis.
  - Step 3 (final synthesis) passes only text context (initial analysis + reference documents), avoiding redundant multi-megabyte PDF re-uploads!
  - CLI includes `--pace` (sleep delay between documents) to avoid bursting rate limits.
- **Limitations:** Does not track token accounting or cost metrics.

#### 3. Strength Assessment & Recommendation
- **Stronger Implementation:** **Combine**. Adopt `quake_agent`'s streamlined 2-pass prompting and single media upload pattern, while retaining MMI-Gram's detailed token telemetry and rate-limit backoff.
- **Required Regression Tests:** Tests verifying token usage accumulation, backoff retries, and pacing delays.

---

### Feature 13: USGS Event Retrieval, Rupture Geometry, Rrup Calculation, & ShakeMap Export

#### 1. MMI-Gram Current Implementation
- **Source Files:** [`server/services/generateMap.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/server/services/generateMap.py#L1-L85), [`server/assets/plot.sh`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/server/assets/plot.sh)
- **Mechanism:** Calls GMT (Generic Mapping Tools) shell scripts to plot records on a map canvas. Lacks USGS ComCat event querying and finite-fault rupture distance calculations.

#### 2. quake_agent Current Implementation
- **Source Files:** [`scripts/rrup_calculator.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/scripts/rrup_calculator.py#L1-L295), [`quake_agent/seismology/physics_critic.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/seismology/physics_critic.py#L10-L202), [`quake_agent/shakemap/comparator.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/shakemap/comparator.py#L8-L96), [`quake_agent/shakemap/runner.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/shakemap/runner.py#L7-L58)
- **Mechanism:**
  - `rrup_calculator.py` & `PhysicsCritic`: Reads USGS finite-fault `rupture.json`. Triangulates 3D fault quadrilaterals into ENU triangles and computes the exact minimum 3D Euclidean distance ($R_{rup}$) from the site to the rupture plane using Ericson (2005) point-to-triangle algorithms.
  - `PhysicsCritic`: Flags physically impossible reports (e.g. $\text{MMI} \ge 8.5$ at $R_{rup} > 150\text{ km}$, or $\text{MMI} \le 3.0$ within $10\text{ km}$ of rupture).
  - `ShakeMapComparator`: Queries USGS ComCat API (`fdsnws/event/1/query?eventid=...`) to download official ShakeMap products (`grid.xml`, `stationlist.json`, `intensity.jpg`) and computes residuals ($\Delta\text{MMI} = \text{MMI}_{\text{agent}} - \text{MMI}_{\text{official}}$).
  - `ShakeMapRunner`: Prepares the `current/` event folder for USGS ShakeMap v4 CLI execution (`shake assemble`, `shake model`).

#### 3. Strength Assessment & Recommendation
- **Stronger Implementation:** **quake_agent is vastly superior**. This is high-value seismological engineering directly aligned with USGS ShakeMap standards.
- **Action:** Port `rrup_calculator.py`, `PhysicsCritic`, `ShakeMapComparator`, and `ShakeMapExporter` into MMI-Gram under `src/mmigram/seismology/` and `src/mmigram/shakemap/`. Generalize event fetching to accept arbitrary USGS event IDs.
- **Required Regression Tests:** Offline mathematical unit tests for 3D point-to-triangle distance, ENU coordinate conversion, and GeoJSON ShakeMap formatting.

---

### Feature 14: Regression Tests, Documentation, & SKILL.md Instructions

#### 1. MMI-Gram Current Implementation
- **Source Files:** [`tests/`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/tests/), [`.agents/skills/mmi-gram-workflow/SKILL.md`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/.agents/skills/mmi-gram-workflow/SKILL.md), [`docs/architecture.md`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/docs/architecture.md)
- **Mechanism:**
  - 105 automated unit and regression tests running 100% offline in ~10 seconds with 100% pass rate.
  - Dedicated coding agent meta-skill in `.agents/skills/mmi-gram-workflow/SKILL.md` enforcing architectural invariants, offline test rules, and schema contracts.
  - Complete documentation of architecture, state graphs, and comparison guides.

#### 2. quake_agent Current Implementation
- **Source Files:** [`quake_agent/test_agent.py`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/QuakeLLMmap-reference/quake_agent/test_agent.py)
- **Mechanism:** Contains a single 54-line manual test script (`test_agent.py`) that makes live API calls. No offline unit test suite.

#### 3. Strength Assessment & Recommendation
- **Stronger Implementation:** **MMI-Gram is vastly superior**. MMI-Gram's 105 passing tests and coding agent instructions ensure zero regressions.
- **Action:** Preserve all 105 existing MMI-Gram tests. Expand the suite to cover the integrated features (Rrup calculator, Google Maps resolver, ShakeMap exporter).
- **Required Regression Tests:** Run full pytest suite across both legacy and new test modules.
