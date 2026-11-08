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
   - The observed legacy output for StEER Page 1 (`MMI 9.0`, `confidence 0.90`) is preserved as a software regression baseline, **not** certified as authoritative scientific ground truth.
   - High-intensity estimates (MMI $\ge$ 9.0) are automatically flagged for engineering audit.
2. **Zero-Fabrication Policy**:
   - If model output is missing, malformed, or outside physical ranges, MMI-Gram records `mmi_estimation = None` and routes it to human review. It **never** defaults missing values to arbitrary fallbacks.
3. **Dual Coordinate Preservation**:
   - Document-parsed coordinates and model-generated coordinates are preserved separately in the output schema. MMI-Gram detects discrepancies (> 10 km) rather than silently overwriting either.
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
# Offline mode (default, uses recorded fixtures):
python3 -m mmigram.cli analyze --pdf server/test_page1.pdf

# Live mode (requires GCP credentials and user approval):
python3 -m mmigram.cli analyze --pdf server/test_page1.pdf --live
```

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
│   ├── test_*.py                 # 53 offline unit & regression tests
│   └── generate_fixtures.py      # Reproducible synthetic test PDF generator
├── pyproject.toml                # Standard PEP 517/518 build specification
├── setup.py                      # Package setup configuration
├── .env.example                  # Environment configuration template
└── README.md                     # This documentation
```

---

## 🧪 Testing & Verification

The test suite covers unit logic, coordinate parsing, QC edge cases, queue persistence, and end-to-end LangGraph workflows without making external network calls.

```bash
# Run tests with unittest discovery:
python3 -m unittest discover -v -s tests -p "test_*.py"
```

**Results**: 53 tests (52 passed, 1 skipped for live API opt-in) running in ~0.02s.

---

## 📄 License & Attribution

Distributed under the Apache 2.0 License. See `LICENSE` for details.

- Multimodal CRAG implementation adapted from Clara Yoon's earthquake assessment research.
- Reconnaissance reports courtesy of the Structural Extreme Events Reconnaissance (StEER) Network.
