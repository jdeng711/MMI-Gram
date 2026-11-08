# 🌍 MMI-Gram: Agentic AI System for Earthquake Intensity Estimation

**MMI-Gram** is an agentic AI framework designed to estimate Modified Mercalli Intensity (MMI) from post-earthquake reconnaissance reports (e.g., StEER field briefings), multimedia damage observations, and crowdsourced social media data.

The project pairs multimodal LLM reasoning (Gemini & Corrective RAG) with deterministic engineering safeguards: automated coordinate validation with dual preservation, multi-rule quality control (QC), and a persistent Human-in-the-Loop (HITL) review queue.

---

## 🎯 Research Context & Collaboration

MMI-Gram is developed in active collaboration with **Clara Yoon's [`QuakeLLMmap`](https://github.com/claraeyoon/QuakeLLMmap)** (`quake_agent`). 

Both systems analyze the **March 2025 Myanmar Earthquake Sequence (`us7000pn9s`)** using StEER reconnaissance documents:
- **`quake_agent` (QuakeLLMmap)** provides an end-to-end LLM-driven batch analysis pipeline across inbound event directories.
- **`MMI-Gram`** introduces modular **LangGraph** orchestration, deterministic DMS coordinate parsing, automated Null Island rejection, coordinate discrepancy detection (> 10 km threshold), and a persistent expert audit queue.

MMI-Gram's batch interface matches Clara's event folder layout (`data/events/<event_id>/inbound/`) and CLI argument conventions (`--event-id`, `--inbound-dir`, `--pace`), enabling seamless comparative benchmarking and cross-pipeline evaluation. *(Note: This comparative framework is designed using the shared initial CRAG research code and reported CLI conventions. Clara's newest internal `quake_agent` implementation in QuakeLLMmap has not been independently reviewed, and no assumptions are made regarding its comparative scientific accuracy.)*

---

## 🏗️ Core Architecture

```
                      +------------------------------------------+
                      |         Input Reconnaissance PDF          |
                      |   (e.g., StEER Field Briefing Page)      |
                      +--------------------+---------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------------+
| LangGraph State Machine (src/mmigram/workflow/)                                         |
|                                                                                         |
|  [Node 1: Ingest PDF]                                                                   |
|      * Extract text & metadata using pypdf                                              |
|      * Compute SHA-256 integrity hash                                                   |
|      * Detect image-only scanned PDFs                                                   |
|            |                                                                            |
|            v                                                                            |
|  [Node 2: Extract MMI]                                                                  |
|      * Offline: Replay recorded fixture without network access or cloud costs           |
|      * Live: Authorized call via CRAGAdapter (Gemini + Pinecone)                        |
|      * Zero fabrication: Null/malformed model outputs remain strictly null              |
|            |                                                                            |
|            v                                                                            |
|  [Node 3: Parse Geolocation]                                                            |
|      * Parse DMS & decimal coordinates from document text                               |
|      * Extract coordinates from model output                                            |
|      * Great-circle Haversine discrepancy detection                                     |
|      * Preserve both document_coordinates and model_coordinates independently           |
|            |                                                                            |
|            v                                                                            |
|  [Node 4: Quality Control (QC)]                                                         |
|      * Rejects Null Island (0.0, 0.0)                                                   |
|      * Validates physical MMI range [1.0, 10.0]                                          |
|      * Flags low confidence (< 0.60) & unestimated intensities                          |
|      * Flags coordinate discrepancies (> 10.0 km)                                       |
|      * Flags extreme intensity anomalies (MMI >= 9.0) for expert review                 |
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

## 🔬 Scientific Integrity & Safety Principles

1. **Strict Separation of Baselines vs. Ground Truth**:
   - The observed legacy output for StEER Page 1 (`MMI 9.0`, `confidence 0.90`) is preserved as a software regression baseline, **not** certified as authoritative scientific ground truth. In this legacy baseline, the model returned invalid Null Island `(0.0, 0.0)` coordinates, which MMI-Gram flags as `COORDINATES_DISAGREE` against document coordinates.
   - High-intensity estimates (MMI $\ge$ 9.0) are automatically flagged for engineering audit.
2. **Zero-Fabrication Policy**:
   - If model output is missing, malformed, or outside physical ranges, MMI-Gram records `mmi_estimation = None` and routes it to human review. It **never** defaults missing values to arbitrary fallbacks.
3. **Dual Coordinate Preservation & Anti-Leakage Invariant**:
   - Document-parsed coordinates and model-generated coordinates are preserved separately in the output schema. Model coordinates are **never** populated or backfilled from document coordinates. MMI-Gram detects discrepancies (> 10 km or invalid coords) rather than silently overwriting either. `COORDINATES_AGREE` is emitted only when both sources independently supply valid coordinates within the threshold.
4. **Offline-First & Zero Unexpected Cloud Costs**:
   - All tests and development workflows execute 100% offline using deterministic fixtures. Live cloud API calls require explicit user authorization.
5. **Unverified Status of Live Gemini Predictions**:
   - Offline mode relies strictly on replay of recorded test fixtures. Live multimodal inferences from Gemini models remain uncalibrated and unverified against ground truth until expert seismological review is performed.

---

## 🚀 Quick Start & Installation

### 1. Clone & Set Up Virtual Environment

```bash
# Clone the repository
git clone https://github.com/jdeng711/MMI-Gram.git
cd MMI-Gram

# Create and activate a Python 3.10+ virtual environment
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Package

```bash
# Install in editable mode
pip install -e .
```

### 3. Environment Configuration (Optional for Live Execution)

MMI-Gram runs completely offline out of the box. If you have authorized Google Cloud credentials and wish to test live Vertex AI / Gemini integration:

```bash
cp .env.example .env
# Edit .env with your GCS_PROJECT_ID, GOOGLE_APPLICATION_CREDENTIALS, and PINECONE_API
```

---

## 💻 CLI Usage

MMI-Gram provides a unified CLI under `mmigram.cli`:

### Check Environment & Live Readiness
```bash
python3 -m mmigram.cli check-env
```

### Run End-to-End Offline Demo
Executes the full LangGraph pipeline on the recorded StEER Page 1 observation, demonstrating text extraction, QC evaluation, and review queue routing:
```bash
python3 -m mmigram.cli demo
```

### Analyze a Specific PDF Document
```bash
# Offline mode (default, strictly deterministic replay of recorded fixtures):
python3 -m mmigram.cli analyze --pdf server/test_page1.pdf

# Live mode with full-scale reference calibration (Default & Recommended: all 10 MMI definitions):
python3 -m mmigram.cli analyze --pdf server/test_page1.pdf --live --confirm-live-api

# Live mode with vector similarity search (top-k candidate search):
python3 -m mmigram.cli analyze --pdf server/test_page1.pdf --live --confirm-live-api --reference-mode vector_search
```

#### Verified Live Empirical Run Results (`server/test_page1.pdf`):
- **Model Invocated**: `gemini-2.5-flash` via Vertex AI CRAG
- **Observed MMI**: `10.0`
- **Observed Confidence**: `0.95` (Uncalibrated AI estimate; strictly distinguished from ground truth)
- **Document Coordinates**: `21.880353° N, 95.984881° E` (Sagaing City, extracted from DMS text)
- **Model Coordinates**: `Unknown` / Not Provided
- **Location Status**: `MODEL_LOCATION_UNAVAILABLE` (Candidate coords rely on document text; missing model coordinates are explicitly never interpreted as agreement)
- **Quality Control**: `FLAGGED` (`HIGH_INTENSITY_MMI`, `MODEL_LOCATION_UNAVAILABLE`, `UNVERIFIED_ESTIMATE`)
- **Human Review**: `UNREVIEWED` (Automatically enqueued into persistent review storage)
- **Execution Time**: ~33 seconds
- **Security & Privacy**: Zero credentials or raw signed URLs appear in logs, traces, or persistent records. Sensitive parameters are sanitized to `[REDACTED_SIGNATURE]`.

### Batch Inbound Directory Analysis (Compatible with Clara's `quake_agent`)
Process an entire directory of incoming earthquake reconnaissance reports:
```bash
python3 -m mmigram.cli batch \
    --event-id us7000pn9s \
    --inbound-dir data/events/us7000pn9s/inbound \
    --pace 2.0
```
Results are saved to `data/events/us7000pn9s/results/` as structured JSON and CSV summary tables.

### Run Full Test Suite
```bash
python3 -m mmigram.cli test
```

---

## 📁 Repository Structure

```
MMI-Gram/
├── .agents/
│   └── skills/
│       └── mmi-gram-workflow/    # Coding agent conventions & development rules
├── data/
│   └── events/
│       └── us7000pn9s/           # Event us7000pn9s (2025 Myanmar Earthquake)
│           ├── inbound/          # Inbound reconnaissance PDFs
│           ├── baseline/         # Recorded baseline fixtures
│           └── results/          # Batch output JSON and CSV tables
├── docs/
│   ├── architecture.md           # Detailed LangGraph state machine & schemas
│   └── comparison.md             # In-depth benchmark guide vs. QuakeLLMmap
├── src/
│   └── mmigram/
│       ├── __init__.py           # Package version (0.2.0)
│       ├── cli.py                # Unified CLI (demo, analyze, batch, test, check-env)
│       ├── adapters/             # CRAGAdapter & live prerequisite checks
│       ├── cartography/          # Mapping interface (GMT / GIS integration)
│       ├── comparison/           # BenchmarkComparator & standardized schemas
│       ├── core/                 # Immutable Pydantic models & observation records
│       ├── geolocation/          # DMS/DD regex parser & Haversine discrepancy detector
│       ├── ingestion/            # PDF ingestion, SHA-256 integrity, social connectors
│       ├── qc/                   # Multi-rule Quality Control engine
│       ├── review/               # Persistent Human-in-the-Loop review queue
│       ├── telemetry/            # StructuredAgentLogger & latency tracers
│       └── workflow/             # LangGraph state machine & pipeline graphs
├── tests/
│   ├── fixtures/                 # Authentic & synthetic test fixtures
│   ├── test_*.py                 # 67 offline unit, security, & regression tests
│   └── generate_fixtures.py      # Reproducible synthetic test PDF generator
├── pyproject.toml                # Standard PEP 517/518 build specification
├── setup.py                      # Package setup configuration
├── .env.example                  # Environment configuration template
└── README.md                     # This documentation
```

---

## 🧪 Testing & Verification

The test suite covers unit logic, coordinate parsing, Haversine discrepancy detection, security redaction, QC edge cases, queue persistence, full-scale reference completeness validation, CRAG grading relevance, and end-to-end LangGraph workflows without making external network calls.

```bash
# Run tests with unittest discovery:
python3 -m unittest discover -v -s tests -p "test_*.py"
```

**Results**: 104 tests (103 passed offline, 1 skipped for live API opt-in) running in ~5.4s.

---

## 📚 MMI Reference Retrieval Modes (`full_scale` vs. `vector_search`)

MMI-Gram supports two scientifically distinct reference retrieval modes:
- **`full_scale` (Default & Recommended)**: Deterministically supplies all 10 official Modified Mercalli Intensity scale definitions ($I$ through $X$) via read-only fetch from Pinecone, without arbitrary vector-ranking exclusions. Validates scale completeness (ensuring all 10 integer levels are present and non-empty) and routes incomplete scale definitions to human review.
- **`vector_search`**: Retrieves top-$k$ candidate definitions via semantic similarity (`search_records` or inference embedding fallback). Relevance grading substantively verifies damage correlation rather than treating all references as automatically relevant just for mentioning "MMI".
- **Cosine Metric Interpretation**: Explains that `mmi-idx` calculates cosine dot products ($[-1.0, 1.0]$). Slight negative cosine values represent vector angles $>90^\circ$ in 1024-dimensional semantic space, which is mathematically standard rather than an API error.

---

## 📦 Unified Google Gen AI SDK & Gemini 3.8 Flash Upgrade

- **Unified SDK**: Modernized from deprecated `vertexai.generative_models` to the official **Google Gen AI SDK** (`google-genai>=2.30.0`, `from google import genai`), authenticated via Google Cloud Vertex AI using authorized Application Default Credentials.
- **Default Live Model**: `gemini-3.8-flash` with explicit `thinking_level=HIGH` (`types.ThinkingConfig(thinking_level=types.ThinkingLevel.HIGH, include_thoughts=True)`). Supported thinking levels are `HIGH`, `MEDIUM`, and `LOW` (`MINIMAL` is not supported for Gemini 3.8 Flash).
- **Parameter Adaptation**: Deprecated generation parameters (`temperature`, `top_p`, `top_k`, `candidate_count`) are automatically omitted when calling Gemini 3.8 Flash, in adherence to the Gemini 3 API specification.
- **Comparative Benchmarking Support**: `gemini-2.5-flash` is preserved as a selectable option (`--model gemini-2.5-flash`) with legacy parameters maintained for scientific comparison with earlier baselines.
- **No Silent Model Switching**: Invocations strictly enforce model identity. Rate limits trigger exponential backoff on the requested model; the pipeline never silently downgrades or switches models.
- **Full Workflow Token Telemetry**: Aggregates token usage (`prompt_tokens`, `candidates_tokens`, `thoughts_tokens`, `total_tokens`) across **every** Gemini call made during the CRAG workflow (initial analysis, document grading, query transformation, and final analysis).

*(Note: Any token usage values shown in documentation or test fixtures are **illustrative examples** of the output schema, not actual empirical measurements from Gemini 3.8 Flash.)*

---

## 📄 License & Attribution

Distributed under the Apache 2.0 License. See `LICENSE` for details.

- Multimodal CRAG implementation adapted from Clara Yoon's earthquake assessment research.
- Reconnaissance reports courtesy of the Structural Extreme Events Reconnaissance (StEER) Network.
