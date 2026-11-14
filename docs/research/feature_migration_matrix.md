# 📋 Feature Migration Matrix: MMI-Gram & QuakeLLMmap Integration

**Project:** Harvard EPS 55 Final Project (in collaboration with Clara Yoon, USGS)  
**Destination Repository:** `MMI-Gram`  
**Date:** November 14, 2026  
**Integration Branch:** `feature/quake-agent-integration`  

---

## 1. Migration Decision Summary

| ID | Feature / Component | MMI-Gram Current Status | QuakeLLMmap (`quake_agent`) Status | Migration Decision | Primary Rationale & Code Action |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **F01** | **PDF Ingestion & SHA-256 Hashing** | Strong (`mmigram.ingestion.pdf_extractor`) | Basic (`harvesters.pdf_extractor`) | **KEEP MMI-Gram** | Preserves SHA-256 checksums, page counting, and corrupted/scanned PDF handling. |
| **F02** | **Event Directory Conventions & Config** | Minimal (`data/events/<id>/inbound`) | Rich (`EventConfig`, `event_config.json`, sidecar txt/json) | **ADAPT from Clara** | Adopt `EventConfig` dataclass and sidecar `.txt`/`.json` file discovery for multimodal pairing. |
| **F03** | **LLM Authentication Provider** | Vertex AI only (`manage_model.py`) | Google AI Studio (`GEMINI_API_KEY`) + REST fallback | **COMBINE & ABSTRACT** | Implement `GeminiProvider`: AI Studio (default local) + Vertex AI (optional cloud). Never silently switch. |
| **F04** | **Model Selection & Thinking Level** | Gemini 3.8 Flash HIGH thinking strictly enforced | Defaults to "low", silent failover to 3.6/3.5 | **KEEP MMI-Gram** | Preserve Gemini 3.8 Flash HIGH thinking. Prohibit silent model failovers or silent media dropping. |
| **F05** | **Media Payload Delivery** | Mandatory GCS upload (`upload_to_gcs`) | Direct byte reading (`Part.from_bytes`) | **REPLACE with Clara's** | Stream local file bytes directly to `google-genai` SDK; eliminate mandatory GCS bucket upload for local runs. |
| **F06** | **Workflow Engine & Observability** | LangGraph StateGraph + StructuredAgentLogger | Procedural for-loop in CLI | **KEEP MMI-Gram** | LangGraph provides superior modularity, conditional routing, offline replay, and state inspectability. |
| **F07** | **Prompting Strategy** | Complex 4-call CRAG graph | Streamlined 2-pass prompt (Description + Final Report) | **ADAPT from Clara** | Embed Clara's refined StEER prompts and single-pass media upload into LangGraph nodes to slash token latency. |
| **F08** | **Relevance Gating (`page-8.pdf`)** | Post-estimation evaluation | Post-estimation evaluation (`has_damage_photos`) | **COMBINE & ELEVATE** | Move relevance gate **before** MMI estimation. Output `NOT_ESTIMABLE` with clear reason for non-damage briefing slides. |
| **F09** | **Pre-Filtering Gates (Time, Hash, AI-Fake)** | Not implemented | 4 gates (`temporal`, `spatial`, `recycled`, `authenticity`) | **ADAPT & INTEGRATE** | Adapt gates as screening filters; route ambiguous/suspicious items to Human Review rather than silently dropping. |
| **F10** | **MMI Reference Retrieval** | Full-scale I-X via Pinecone Serverless | Embedded `USGS_MMI_DEFINITIONS` (I-XII) in code | **COMBINE & LOCAL-FIRST** | Load official MMI scale definitions from versioned local file (`server/assets/mmi_definitions.txt`). Pinecone optional. |
| **F11** | **Geolocation Parsing & Google Maps** | DMS & decimal regex; no URL expansion | Google Maps URL unshortening & Geocoding API | **COMBINE** | Add Clara's Google Maps link parser and Geocoding API resolver into MMI-Gram's `mmigram.geolocation`. |
| **F12** | **Epicentral Fallback Policy** | Prohibited (null island / missing rejected) | Replaced missing coords with hypocenter (CRITICAL FLAW) | **KEEP MMI-Gram** | **Strictly prohibit substituting hypocenter for observation coordinates.** Record null and route to review. |
| **F13** | **Dual Coordinate Preservation** | Preserves `doc_coords` & `model_coords` | Single coordinate field in evaluation | **KEEP MMI-Gram** | Maintain strict separation of document-extracted vs model-predicted coordinates and compute Haversine discrepancy. |
| **F14** | **Uncertainty & ShakeMap Feature Schema** | Pydantic models; uncalibrated confidence | `to_shakemap_feature()` + `intensity_stddev` formula | **COMBINE** | Retain MMI-Gram data contracts; add `to_shakemap_feature()` matching official USGS ShakeMap v4 `*_dat.json` specs. |
| **F15** | **Automated Quality Control** | Deterministic multi-rule engine (`qc.checker`) | Basic spatial bounding check | **KEEP MMI-Gram** | Preserves Null Island rejection, physical range checks, confidence thresholds, and discrepancy detection. |
| **F16** | **Human-in-the-Loop Review Queue** | Persistent atomic JSON queue with audit actions | None (console warnings only) | **KEEP MMI-Gram** | Retain persistent review queue (`data/review_queue.json`) for unverified high-intensity ($\ge 9.0$) or ambiguous reports. |
| **F17** | **Finite-Fault Rupture Geometry & $R_{rup}$** | Epicentral distance only | 3D mesh point-to-triangle $R_{rup}$ calculation | **ADAPT from Clara** | Port `rrup_calculator.py` and `PhysicsCritic` into MMI-Gram for rigorous distance to 3D rupture surface. |
| **F18** | **USGS ComCat Downloader & Comparison** | None (GMT plot script only) | `ShakeMapComparator` queries ComCat API | **ADAPT from Clara** | Port `ShakeMapComparator` to download official USGS ShakeMap grids and compute residual statistics ($\Delta\text{MMI}$). |
| **F19** | **Embedded Analytics Database** | Flat JSON / CSV / BigQuery | Embedded DuckDB / SQLite (`LocalStorageRepository`) | **ADAPT from Clara** | Add DuckDB embedded repository for local high-performance SQL querying across harvested events. |
| **F20** | **Automated Test Suite & Regression** | 105 passing unit/regression tests (100% offline) | Single manual live script (`test_agent.py`) | **KEEP MMI-Gram** | Retain 100% passing offline test suite; expand suite to cover ported seismology and geolocation modules. |

---

## 2. Detailed Action Plan by Subsystem

### A. Ingestion & Event Management
- **Keep:** `src/mmigram/ingestion/pdf_extractor.py` (SHA-256 calculation, `pypdf` extraction, image-only detection).
- **Incorporate from Clara:** `quake_agent/config.py` (`EventConfig` parser) and `quake_agent/harvesters/local_watcher.py` (sidecar `.txt` and `.json` handling).
- **Target Location:** `src/mmigram/ingestion/` and `src/mmigram/core/config.py`.

### B. Gemini Provider & Model Management
- **Keep:** `server/services/manage_model.py` (Gemini 3.8 Flash HIGH thinking parameter enforcement, token accounting telemetry, exponential backoff).
- **Incorporate from Clara:** Direct `types.Part.from_bytes()` local media reading from `quake_agent/seismology/gemini_bridge.py`.
- **Target Location:** `src/mmigram/adapters/gemini_provider.py` (abstracting AI Studio and Vertex AI).

### C. Seismology & Physics
- **Keep:** MMI-Gram's uncalibrated confidence labeling and StEER structural damage damage modeling.
- **Incorporate from Clara:**
  - `scripts/rrup_calculator.py` -> `src/mmigram/seismology/rrup.py` (3D finite-fault distance).
  - `quake_agent/seismology/physics_critic.py` -> `src/mmigram/seismology/physics_critic.py` (attenuation curve checking).
  - `quake_agent/seismology/local_mmi_kb.py` -> `src/mmigram/seismology/mmi_reference.py` (local versioned definitions).
  - `quake_agent/shakemap/comparator.py` -> `src/mmigram/comparison/shakemap_comparator.py` (USGS ComCat querying).
  - `quake_agent/shakemap/exporter.py` -> `src/mmigram/comparison/shakemap_exporter.py` (USGS ShakeMap v4 `*_dat.json` export).

### D. Geolocation Engine
- **Keep:** `src/mmigram/geolocation/parser.py` (DMS/decimal regex) and `src/mmigram/geolocation/validator.py` (Null Island rejection, dual coordinate preservation, Haversine discrepancy check).
- **Incorporate from Clara:** `quake_agent/seismology/geolocation_resolver.py` (Google Maps URL unshortening, Google Geocoding API caller, EXIF GPS extractor).
- **Strictly Reject from Clara:** Hypocenter fallback for missing observation coordinates (lines 170-176 of `mmi_assessor.py`).
- **Target Location:** `src/mmigram/geolocation/`.

### E. Quality Control & Human-in-the-Loop
- **Keep:** `src/mmigram/qc/` and `src/mmigram/review/queue.py`. All gate outputs from Clara's pre-filtering (temporal drift, duplicate hash, AI-fake suspicion) will map into MMI-Gram QC flags (`FLAG_TEMPORAL_DRIFT`, `FLAG_DUPLICATE_MEDIA`, `FLAG_SYNTHETIC_SUSPECT`) and trigger Human Review if ambiguous.
