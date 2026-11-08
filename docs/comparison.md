# 🔬 MMI-Gram vs. QuakeLLMmap (`quake_agent`) Comparison Guide

This document provides a comparative technical evaluation between **MMI-Gram** and Clara Yoon's **`QuakeLLMmap` (`quake_agent`)** workflow for the Myanmar earthquake event (`us7000pn9s`).

---

## 1. Overview & Shared Mission

Both systems aim to automate the extraction of seismic damage assessments and Modified Mercalli Intensity (MMI) estimates from post-earthquake reconnaissance reports (such as StEER field briefings) for the **March 2025 Myanmar Earthquake Sequence (`us7000pn9s`)**:

- **`quake_agent` (QuakeLLMmap)** provides an end-to-end LLM batch analysis workflow across inbound event directories. *(Note: This comparison is based on the shared initial CRAG research code and Clara's reported CLI interface. Clara's newest `quake_agent` implementation has not been independently inspected, and this document does not make assertions regarding `quake_agent`'s internal validation mechanisms or comparative scientific accuracy.)*
- **`MMI-Gram`** emphasizes modular **LangGraph** orchestration, automated Quality Control (QC), dual coordinate preservation (preserving document-extracted coordinates and model-generated coordinates separately), and a persistent Human-in-the-Loop (HITL) review queue.

> [!IMPORTANT]
> **Scientific Caveat on Offline Replay vs. Live Inference**:
> MMI-Gram's default offline mode executes deterministic **fixture replay** of recorded or synthetic outputs for software regression testing. It does **not** perform live model inference or reflect validated scientific ground truth. Live Gemini execution via `CRAGAdapter` remains experimental and uncalibrated until formal expert seismological review is completed.

---

## 2. Architectural Design Comparison

The table below contrasts MMI-Gram's design features with the shared baseline:

| Architectural Dimension | Shared CRAG / CLI Baseline | MMI-Gram (`mmigram`) |
| :--- | :--- | :--- |
| **Workflow Engine** | Custom iterative batch loop in CLI | Modular **LangGraph StateGraph** state machine |
| **Input Ingestion** | Iterates through PDF directory | `pypdf` text extraction + SHA-256 integrity + corrupt/scanned PDF detection |
| **Intensity Estimation** | Gemini LLM with CRAG prompt traversal | Modular `extract_mmi` node with offline fixture replay and live `CRAGAdapter` |
| **Fallback Handling** | Unstructured error on failure | **Strict zero-fabrication**: malformed/missing MMI remains `null` and routed to review |
| **Coordinate Extraction** | Extracted from LLM generation | **Dual Extraction**: DMS regex extraction from text + LLM extraction |
| **Coordinate Validation** | Basic validity check | **Haversine discrepancy detection**; flags if distance > 10 km |
| **Coordinate Preservation** | Single coordinate field | Preserves `document_coordinates` and `model_coordinates` independently |
| **Quality Control** | Basic output validation | **Deterministic Multi-Rule Engine** (Null Island, range, confidence, discrepancy) |
| **Review & Audit** | Unresolved cases logged or dropped | **Persistent Review Queue** (`data/review_queue.json`) surviving restarts |
| **Offline Testing** | Requires active API access & credentials | **100% Offline Test Suite** (53 tests, 0.02s execution, 0 cloud cost) |
| **Telemetry & Observability** | Console print statements | **StructuredAgentLogger** (start/end events, payload snapshots, durations) |
| **Data Organization** | `data/events/<event_id>/inbound/` | Fully aligned: `data/events/<event_id>/inbound/`, `baseline/`, `results/` |

---

## 3. Drop-in Command Compatibility

MMI-Gram's CLI is designed to accept identical parameters to Clara's `quake_agent` for batch processing inbound event folders:

### Clara's `quake_agent` Command:
```bash
python3 -m quake_agent.cli run \
    --event-id us7000pn9s \
    --inbound-dir data/events/us7000pn9s/inbound \
    --model gemini-2.5-flash \
    --pace 2.0
```

### MMI-Gram Equivalent Command:
```bash
python3 -m mmigram.cli batch \
    --event-id us7000pn9s \
    --inbound-dir data/events/us7000pn9s/inbound \
    --pace 2.0
```

*(Note: In offline mode, MMI-Gram processes files against recorded fixtures without incurring API costs. In `--live` mode with authorized credentials, it calls the Gemini API via Clara's CRAG backend.)*

---

## 4. Standardized Output Schema & Benchmark Export

MMI-Gram includes a `BenchmarkComparator` (`src/mmigram/comparison/comparator.py`) that exports standardized records in both JSON and CSV format:

### Standardized CSV Columns:
- `observation_id`: Unique identifier for the observation
- `source_file`: File name of the processed PDF report
- `mmi_estimation`: Estimated MMI value (1.0 - 10.0, or empty if unestimated)
- `confidence`: Confidence score (0.0 - 1.0, or empty)
- `latitude`: Selected primary latitude
- `longitude`: Selected primary longitude
- `coordinate_source`: Origin of primary coordinates (`dms_parsed`, `model_predicted`, etc.)
- `document_latitude`: Latitude parsed from document text
- `document_longitude`: Longitude parsed from document text
- `model_latitude`: Latitude predicted by model
- `model_longitude`: Longitude predicted by model
- `coordinates_disagree`: Boolean flag (`true`/`false`)
- `discrepancy_km`: Great-circle distance between document and model locations
- `qc_status`: Quality control outcome (`PASSED`, `FLAGGED`, `REJECTED`)
- `qc_flags`: Semicolon-delimited list of triggered QC flags
- `review_required`: Whether the record was routed to human review
- `review_status`: Review queue status (`UNREVIEWED`, `AUDITED`, `OVERRIDDEN`)
- `is_synthetic`: Whether the input is synthetic test data
- `is_calibrated`: Whether the intensity has undergone expert calibration

### Output File Locations:
When running batch analysis on event `us7000pn9s`, results are automatically written to:
- `data/events/us7000pn9s/results/batch_results_<timestamp>.json`
- `data/events/us7000pn9s/results/batch_summary_<timestamp>.csv`

---

## 5. Running a Comparative Evaluation

To run a side-by-side benchmark comparison between both workflows:

1. **Place shared event PDFs** in `data/events/us7000pn9s/inbound/`.
2. **Execute MMI-Gram**:
   ```bash
   python3 -m mmigram.cli batch --event-id us7000pn9s --inbound-dir data/events/us7000pn9s/inbound
   ```
3. **Execute QuakeLLMmap**:
   ```bash
   python3 -m quake_agent.cli run --event-id us7000pn9s --inbound-dir data/events/us7000pn9s/inbound --pace 2.0
   ```
4. **Compare Key Quality Indicators**:
   - **Coordinate Accuracy**: Compare the coordinates against the ground truth document text.
   - **Discrepancy Catch Rate**: Did the model hallucinate coordinates outside the affected region? (MMI-Gram flags discrepancies > 10 km).
   - **Null Island Rejection**: Did either pipeline produce `(0,0)` coordinates? (MMI-Gram strictly rejects `(0,0)`).
   - **High-Intensity Auditing**: Were extreme intensity estimates (MMI >= 9.0) appropriately intercepted for human engineering review?
