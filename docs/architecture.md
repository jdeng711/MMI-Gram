# 🏗️ MMI-Gram System Architecture & Agent Workflow

MMI-Gram is an agentic AI system for estimating Modified Mercalli Intensity (MMI) from post-earthquake reconnaissance reports, field imagery, and social media data. It couples multimodal language models with a rigorous engineering pipeline: deterministic coordinate extraction, multi-rule quality control (QC), and a persistent Human-in-the-Loop (HITL) review queue.

---

## 1. System Overview

```
                      +------------------------------------------+
                      |         Input Reconnaissance PDF          |
                      |   (e.g., StEER Field Briefing Page)      |
                      +--------------------+---------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------------+
| LangGraph State Machine                                                                 |
|                                                                                         |
|  [Node 1: Ingest PDF]                                                                   |
|      * Extract text & metadata using pypdf                                              |
|      * Compute SHA-256 integrity hash                                                   |
|      * Detect image-only scanned PDFs                                                   |
|            |                                                                            |
|            v                                                                            |
|  [Node 2: Extract MMI]                                                                  |
|      * Offline: Load recorded fixture without network or costs                          |
|      * Live: Authorized call via CRAGAdapter (Gemini + Pinecone)                        |
|      * Zero fabrication: Null/malformed model outputs remain null                       |
|            |                                                                            |
|            v                                                                            |
|  [Node 3: Parse Geolocation]                                                            |
|      * Parse DMS & decimal coordinates from document text                               |
|      * Extract coordinates from model output                                            |
|      * Haversine distance comparison between document & model                           |
|      * Preserve both document_coordinates and model_coordinates independently           |
|            |                                                                            |
|            v                                                                            |
|  [Node 4: Quality Control (QC)]                                                         |
|      * Rule 1: Reject Null Island (0.0, 0.0)                                            |
|      * Rule 2: Validate physical MMI range [1.0, 10.0]                                   |
|      * Rule 3: Check confidence threshold (< 0.60 flagged)                              |
|      * Rule 4: Flag coordinate discrepancies (> 10 km)                                  |
|      * Rule 5: Flag unestimated intensity (missing/null MMI)                            |
|      * Rule 6: Flag high intensity anomaly (MMI >= 9.0)                                 |
|            |                                                                            |
|            +-----------------------+-----------------------+                            |
|            | (QC Passed Cleanly)   | (Flagged or Rejected) |                            |
|            v                       v                       |                            |
|      [Auto-Approved]    [Node 5: Human Review Queue]       |                            |
|                                * Persistent JSON storage   |                            |
|                                * Audit reason triggers     |                            |
|                                * Expert review / override  |                            |
+--------------------------------------------+---------------+----------------------------+
                                             |
                                             v
                      +------------------------------------------+
                      | Structured Output (JSON / CSV / Summary) |
                      +------------------------------------------+
```

---

## 2. Implemented LangGraph Workflow & Governance Pipeline

The operational pipeline integrates Stage 1–4B capabilities, managing screening uncertainty, coordinate availability, and strict separation between technical export compatibility and scientific expert validation.

```mermaid
flowchart TD
    Start([Input PDF / Observation / Media]) --> Ingest[ingest_pdf<br/>Text/Image extraction & SHA-256]
    
    subgraph Screening ["1. Pre-MMI Screening Gates"]
        Ingest --> GateCheck{Screening Evaluation<br/>Relevance, Temporal, pHash, Authenticity}
        GateCheck -- "Definitively Ineligible<br/>(e.g., pure map/hazard chart)" --> ScreenedOut[NOT_ESTIMABLE / SCREENED_OUT<br/>Audited in excluded_observations.json]
        GateCheck -- "Plausible Evidence<br/>(Subject to Screening Uncertainty)" --> MMI[extract_mmi<br/>Multimodal Intensity Estimation]
        GateCheck -- "Uncertain / Scanned Image" --> FlagScreen[REVIEW_REQUIRED<br/>Preserved with Audit Reason]
        FlagScreen --> MMI
    end

    subgraph EstimationAndGeo ["2. Intensity Estimation & Geolocation"]
        MMI --> GeoResolution{Geolocation Resolver}
        GeoResolution -- "Site Coordinates Identified<br/>(DMS, decimal, marker URL)" --> GeoValid[Validate Coordinates & Bounding Box]
        GeoResolution -- "Missing Coordinates<br/>(Coordinates: null)" --> MissingGeo[Non-Geographic Observation<br/>MMI Estimate Retained & Saved<br/>has_exportable_site_coordinates: False]
        MissingGeo --> HITL_Geo[Enqueued for Manual Geocoding]
        GeoValid --> GeoCompare[Compare Document vs. Model Coords]
        GeoCompare --> RrupPhysics[Finite-Fault Rrup Calculation & Physics Critic]
    end

    subgraph QualityControl ["3. Quality Control & Dual-Track Export"]
        RrupPhysics --> QC[Automated Multi-Rule QC<br/>Range, Attenuation, Conflict Check]
        QC --> GateStatus{QC & Review Gate}
        
        GateStatus -- "Syntax & Bounds Valid<br/>Site Coordinates Present" --> TechEligible{"Export Mode"}
        
        TechEligible -- "Technical Compatibility Mode<br/>(require_expert_approval=False)" --> TechExport[Technical Compatibility Artifact<br/>agent_mmi_dat.json<br/>dataset_type: technical_compatibility_artifact<br/>scientific_use_allowed: False]
        
        GateStatus -- "Flagged / Near Fault /<br/>Unreviewed Observation" --> HITL[Human-in-the-Loop Review Queue<br/>review_status: PENDING_EXPERT_REVIEW]
        
        HITL --> Seismologist[Seismologist Expert Review<br/>Wood & Neumann 1931 / ShakeMap Standards]
        
        Seismologist -- "APPROVE / REVISE" --> ApprovedObs[Scientifically Validated Observation<br/>review_status: APPROVED]
        Seismologist -- "REJECT / DEFER" --> ExcludedAudit[Excluded / Deferred Archive]
        
        ApprovedObs --> TechEligible
        TechEligible -- "Scientific Validation Mode<br/>(require_expert_approval=True)" --> SciExport([Scientifically Validated Dataset<br/>agent_mmi_dat.json<br/>dataset_type: scientifically_validated_observation_dataset<br/>scientific_use_allowed: True<br/>Ready for USGS ShakeMap 4.5 Assimilation])
    end

    classDef implemented fill:#e1f5fe,stroke:#0288d1,stroke-width:2px;
    classDef decision fill:#fff3e0,stroke:#f57c00,stroke-width:2px;
    classDef terminal fill:#e8f5e9,stroke:#388e3c,stroke-width:2px;
    classDef warning fill:#fffde7,stroke:#fbc02d,stroke-width:2px;

    class Ingest,MMI,GeoValid,GeoCompare,RrupPhysics,QC,Seismologist implemented;
    class GateCheck,GeoResolution,GateStatus,TechEligible decision;
    class TechExport,MissingGeo,FlagScreen warning;
    class Start,SciExport,ApprovedObs terminal;
```

---

## 3. Core Data Contracts & State Schemas

The system enforces strict schema definitions defined in `src/mmigram/core/models.py`:

### `ObservationRecord`
```python
class ObservationRecord(BaseModel):
    observation_id: str
    source_type: str                  # "steer_report", "social_media", etc.
    file_path: Optional[str]
    document_text: Optional[str]
    sha256_hash: Optional[str]

    # Seismic Intensity
    seismic_intensity: SeismicIntensity
        mmi_estimation: Optional[float]   # 1.0 - 10.0, or None if unestimated
        confidence: Optional[float]       # 0.0 - 1.0, or None
        is_calibrated: bool               # True only after expert or empirical review
        reasoning: str

    # Geographic Resolution
    geographic_resolution: GeographicResolution
        coordinates: Optional[Coordinates]         # Primary active coordinates
        document_coordinates: Optional[Coordinates]# Parsed from source text
        model_coordinates: Optional[Coordinates]   # Generated by LLM
        comparison_status: str                     # COORDINATES_AGREE, COORDINATES_DISAGREE,
                                                   # MODEL_LOCATION_UNAVAILABLE, DOCUMENT_LOCATION_UNAVAILABLE,
                                                   # BOTH_LOCATIONS_UNAVAILABLE
        coordinates_disagree: bool
        discrepancy_distance_km: Optional[float]
        discrepancy_details: Optional[str]

    # Quality Control & Provenance
    quality_control: QualityControlResult
        status: str                      # "PASSED", "FLAGGED", "REJECTED"
        flags: List[str]
        score: float

    human_in_the_loop: HumanReviewStatus
        review_required: bool
        review_status: str               # "UNREVIEWED", "AUDITED", "OVERRIDDEN"
        triggers: List[str]

    provenance: ProvenanceMetadata
        is_synthetic: bool
        baseline_type: str               # "RECORDED_LEGACY_OUTPUT", "MOCKED_TEST_DATA", etc.
        is_authoritative_ground_truth: bool
```

---

## 4. Key Architectural Subsystems

### A. Geolocation Parsing & Location Status Taxonomy (`src/mmigram/geolocation/`)
- **Document coordinate extraction**: Scans raw document text using high-precision regex matching Degrees Minutes Seconds (DMS), Degrees Decimal Minutes (DDM), and Decimal Degrees (DD).
- **Coordinate discrepancy detection**: Calculates the great-circle distance (Haversine formula) between document coordinates and model-generated coordinates. If distance exceeds `10.0 km`, `coordinates_disagree` is set to `True`.
- **Location Status Taxonomy**:
  - `COORDINATES_AGREE`: Both sources valid, separation $\le$ 10.0 km.
  - `COORDINATES_DISAGREE`: Both sources valid, separation > 10.0 km (or model returned corrupted/invalid coordinates).
  - `MODEL_LOCATION_UNAVAILABLE`: Document text established valid coordinates, but model location was null/Unknown. *CRITICAL INVARIANT*: Missing model coordinates are never interpreted as agreement.
  - `DOCUMENT_LOCATION_UNAVAILABLE`: Model predicted coordinates, but document text lacked coordinates.
  - `BOTH_LOCATIONS_UNAVAILABLE`: Neither source established coordinates; candidate coordinates remain null.
- **Dual preservation**: Document coordinates and model coordinates are preserved separately in the output schema. MMI-Gram does not silently overwrite or assume either is ground truth without expert verification.

### B. Multi-Rule Quality Control (`src/mmigram/qc/`)
Rules are evaluated deterministically in `src/mmigram/qc/checker.py`:
1. `FLAG_NULL_ISLAND`: Triggers if latitude and longitude are both exactly `0.0`. Status set to `REJECTED`.
2. `FLAG_INVALID_MMI_RANGE`: Triggers if MMI < 1.0 or MMI > 12.0. Status set to `REJECTED`.
3. `FLAG_UNESTIMATED_INTENSITY`: Triggers if MMI is missing/null. Status set to `FLAGGED` (requires human review).
4. `FLAG_COORDINATE_DISCREPANCY`: Triggers when document and model coordinates disagree by > 10 km. Status set to `FLAGGED`.
5. `FLAG_MODEL_LOCATION_UNAVAILABLE`: Triggers when model coordinates were unavailable. Status set to `FLAGGED`.
6. `FLAG_HIGH_INTENSITY_ANOMALY`: Triggers when MMI >= 9.0. Status set to `FLAGGED` (requires expert corroboration).
7. `FLAG_LOW_CONFIDENCE`: Triggers when confidence < 0.75. Status set to `FLAGGED`.

### C. Persistent Human-in-the-Loop Review Queue (`src/mmigram/review/queue.py`)
- Observations failing QC or requiring validation are automatically routed to the review queue.
- Persists state to a structured local JSON file (`data/review_queue.json`) with file-locking and atomic writes.
- Survives process restarts and CLI runs.
- Tracks expert audit history, review status (`UNREVIEWED`, `AUDITED`, `OVERRIDDEN`), and override rationale.
- **Security-Sanitized**: Enqueued states scrub signed GCS URLs and API credentials before writing to disk.

### D. Structured Telemetry & Credential Redaction (`src/mmigram/telemetry/tracer.py`)
- Emits structured events whenever a LangGraph node starts or completes.
- Logs node execution timestamp (UTC), input state snapshot, output payload, and duration in milliseconds.
- **Security Redaction Engine**: Recursively filters GCS V4 signed URLs (`https://storage.googleapis.com/...?[REDACTED_SIGNATURE]`), Bearer tokens, and sensitive query parameters from terminal streaming, LangGraph node dumps, and persisted traces.

### E. Google Gen AI SDK & Gemini 3.8 Flash Upgrade
- **Unified SDK**: Model invocations use the modern `google-genai` SDK (`from google import genai`) configured for Vertex AI mode (`vertexai=True`, `project=...`, `location=...`, using existing authorized Google Cloud Application Default Credentials).
- **Primary Model**: `gemini-3.8-flash` with explicit `thinking_level=HIGH` (`types.ThinkingConfig(thinking_level=types.ThinkingLevel.HIGH, include_thoughts=True)`). Supported thinking levels are `HIGH`, `MEDIUM`, and `LOW` (`MINIMAL` is not supported for Gemini 3.8 Flash).
- **Parameter Adaptation**: Deprecated sampling parameters (`temperature`, `top_p`, `top_k`, `candidate_count`) are omitted for Gemini 3.8 Flash, as required by the Gemini 3 API specification.
- **Comparative Benchmarking**: Legacy models such as `gemini-2.5-flash` remain fully supported as explicit CLI arguments (`--model gemini-2.5-flash`) with their standard parameters preserved for comparative experiments.
- **Scientific Integrity Guardrail**: The pipeline **never** silently switches models on rate limits or errors. Retries use exponential backoff on the requested model exclusively.
- **Comprehensive Workflow Token Tracking**: Captures input tokens (`prompt_tokens`), output tokens (`candidates_tokens`), thinking tokens (`thoughts_tokens`), and total token consumption across **every** Gemini invocation made throughout the CRAG workflow (initial analysis, document grading passes, and final analysis).

> [!NOTE]
> **Illustrative Example Schema (Not an Empirical Gemini 3.8 Measurement)**:
> The JSON block below is a structural reference showing how cumulative token usage is logged in provenance. It does not represent an actual live test measurement:
> ```json
> "provenance": {
>   "model_identifier": "gemini-3.8-flash",
>   "thinking_level": "HIGH",
>   "execution_mode": "live",
>   "source_sha256": "...",
>   "mmi_result": 10.0,
>   "uncalibrated_confidence": 0.95,
>   "token_usage": {
>     "calls": 4,
>     "prompt_tokens": 1845,
>     "candidates_tokens": 312,
>     "thoughts_tokens": 1280,
>     "total_tokens": 3437
>   },
>   "execution_duration_ms": 32800.5
> }
> ```

### F. MMI Reference Retrieval & Scale Selection Architecture
MMI-Gram supports two scientifically distinct reference retrieval modes:
1. **Full-Scale Mode (`MMI_REFERENCE_MODE=full_scale`, Default & Recommended)**:
   - Deterministically fetches all ten official Modified Mercalli Intensity scale definitions ($I$ through $X$) via Pinecone read-only `fetch(ids=['mmi-1'..'mmi-10'])`.
   - Supplies the complete, unclipped reference scale to the final analysis prompt without arbitrary vector-ranking exclusions.
   - **Completeness Validator** (`validate_scale_completeness`): Verifies that each of the 10 integer levels ($1..10$) is present exactly once with substantive text. If any level is missing, duplicated, or empty, sets status to `INCOMPLETE`, triggering QC flag `REFERENCE_RETRIEVAL_FAILED` and routing the observation to the Human Review Queue.
   - **Grading In Full-Scale**: Validates scale completeness and retains all 10 standard definitions for comprehensive comparison (`web_search="No"`).
2. **Vector-Search Mode (`MMI_REFERENCE_MODE=vector_search`)**:
   - Retrieves top-$k$ candidate definitions using Pinecone Serverless Integrated Embeddings (`llama-text-embed-v2`, 1024 dimensions) or inference embedding fallback.
   - **Relevance Grading**: Evaluates whether retrieved definitions describe shaking effects or damage levels substantively relevant to characterizing the observed damage. Rejects unrelated definitions (e.g., MMI 1 "Not Felt" for severe structural collapse) rather than treating all references as automatically relevant.
3. **Investigation of Negative Cosine Scores**:
   - The `mmi-idx` Pinecone index uses the `cosine` distance metric ($u \cdot v \in [-1.0, 1.0]$).
   - In 1024-dimensional semantic embedding space, query and passage vectors with angles slightly greater than $90^\circ$ produce small negative cosine dot products (e.g., $-0.0057$, $-0.0150$).
   - Negative scores are mathematically valid cosine similarities, not an API error or index malfunction.
4. **Data Immutability**:
   - All retrieval operations are strictly read-only. No vectors or metadata in Pinecone are upserted, modified, or deleted.

---

## 5. Distinction: Implemented vs. Planned Components

| Component | Status | Location | Notes |
| :--- | :--- | :--- | :--- |
| **PDF Ingestion & Text Extraction** | Implemented | `src/mmigram/ingestion/` | Uses `pypdf`, handles text and scanned PDFs |
| **Offline Fixture Replay** | Implemented | `src/mmigram/workflow/` | Zero-cost, 100% offline reproducible |
| **Live CRAG Adapter** | Implemented | `src/mmigram/adapters/` | Reuses Clara's CRAG, gated by explicit flag |
| **DMS Geolocation Parser** | Implemented | `src/mmigram/geolocation/` | Regex-based DMS/DD extraction |
| **Coordinate Discrepancy Detection** | Implemented | `src/mmigram/geolocation/` | Haversine distance, dual preservation |
| **Multi-Rule QC Engine** | Implemented | `src/mmigram/qc/` | 6 deterministic rules |
| **Persistent Review Queue** | Implemented | `src/mmigram/review/` | Local JSON atomic persistence |
| **Structured Telemetry** | Implemented | `src/mmigram/telemetry/` | Node timing & state logging |
| **Unified CLI** | Implemented | `src/mmigram/cli.py` | `demo`, `analyze`, `batch`, `test`, `check-env` |
| **Benchmark Comparator** | Implemented | `src/mmigram/comparison/` | JSON & CSV export for workflow comparison |
| **Reddit Social Connector** | Implemented (Offline) | `src/mmigram/ingestion/` | Normalization to `SocialPost` & metadata |
| **Live Social Discovery** | Planned | Future milestone | Gated on API credentials & platform terms |
| **Python-native GIS Mapping** | Planned | Future milestone | Geopandas/Folium/PyGMT layer |
