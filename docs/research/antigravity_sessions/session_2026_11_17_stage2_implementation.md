# 📜 Antigravity Research Session: Stage 2 Implementation (Pre-MMI Input Relevance Screening, Quality Control, and Evidence Filtering)

**Date:** 2026-11-17  
**Researcher:** Jason Deng (Harvard University, EPS 55) in collaboration with Clara Yoon (USGS)  
**Assistant:** Antigravity (Google DeepMind)  
**Model:** Gemini 3.8 Flash (High Thinking)  
**Repository:** `MMI-Gram-Clean` (Destination)  
**Target Branch:** `feature/quake-agent-integration`  
**Base Commit:** `dbfbc12379e34d2c992dfb5895e9cbfcaa28c1bf` (`dbfbc12`)  
**Status:** Implementation Complete — Verified Offline (152 passed, 1 skipped) — Pending User Review

---

## 1. Executive Summary & Objective

In **Stage 2: Input Relevance Screening, Quality Control, and Evidence Filtering**, we audited, adapted, and integrated the strongest screening components from Clara Yoon's `QuakeLLMmap/quake_agent` repository into MMI-Gram's unified architecture without silently discarding scientifically valuable macroseismic observations.

### Key Objectives Delivered:
1. **Audited & Adapted Clara's Screening Gates:** Reviewed `spatial_gate.py`, `temporal_gate.py`, `recycled_gate.py`, `authenticity_gate.py`, and `mmi_assessor.py` in `QuakeLLMmap-reference/quake_agent/gates/`.
2. **Pre-MMI Evidence Relevance Gate:** Implemented explicit 3-way triage: `ESTIMABLE`, `NOT_ESTIMABLE`, `REVIEW_REQUIRED`. Text-only documents with detailed damage observations are estimable without images; conversely, images alone (e.g. logos, model maps) do not confer estimability.
3. **Strict Null Intensity Enforcement:** Unestimable and review-required inputs strictly set `mmi_estimation = None` (JSON `null`), **NEVER** `0.0`. In macroseismic scaling (Modified Mercalli Intensity I–XII), 0.0 is an unphysical intensity.
4. **Authentic `page-8.pdf` Benchmark:** Located the authentic `page-8.pdf` from the Myanmar StEER reconnaissance report (`/Users/jasondeng/Downloads/Files/Harvard/F26/EPS 55/Final Project/2026_Macroseismic_AI_Myanmar/pages/page-8.pdf`, SHA-256: `0477e0daf7e08f35ff16a7ff6e0f83cc22f4e4d0607412d3d5a0e1219f823269`). Verified as a regional ShakeMap simulation model slide with `Geolocation N/A`. Correctly screened out as `NOT_ESTIMABLE` with `mmi_estimation = null`, 0 LLM calls, and 0 tokens ($0.00 spent).
5. **Temporal Consistency Gate:** Compared against origin time $T_0$ (`2025-03-28T06:20:00Z`). Missing timestamps (`TIMESTAMP_MISSING`) are accepted as valid; timestamps predating $T_0$ by >5 minutes (`PREDATES_EVENT`) are flagged for review.
6. **Recycled Media & Duplicate Gate:** Integrated cryptographic SHA-256 exact matching and pure-Python 64-bit difference hashing (dHash, Hamming distance $\le 4$) without external dependencies. Preserves deduplication provenance rather than silently deleting duplicate records.
7. **Authenticity Gate:** Audited tool signatures and prompt forensics (e.g., Midjourney, DALL-E, Stable Diffusion). Flags suspicious items as `SUSPICIOUS_AI_GENERATED` and routes them to human review rather than silently dropping them.
8. **Spatial Plausibility Gate:** Enforces regional bounds and township matching. Never rejects solely on epicentral distance (preserving valid distant felt reports) and **strictly never substitutes hypocentral or epicentral coordinates** for missing locations.
9. **Pre-MMI Pipeline Wiring:** Placed `CompositeScreener` before Step 3 in `GeneralSteerPipeline`. Early exits on `NOT_ESTIMABLE`, saving 100% of LLM tokens ($0.00 spend).
10. **Offline Regression Suite:** Authored `tests/test_screening_gates.py` covering all 15 required offline regression tests. Ran full pytest suite: **152 passed, 1 skipped, 0 failures**.

---

## 2. Verbatim User Request

```text
Stage 1 has been successfully verified and committed as dbfbc12, with 137 tests passing and 1 intentionally skipped.

I approve proceeding with Stage 2: Input Relevance Screening, Quality Control, and Evidence Filtering.

Continue working on feature/quake-agent-integration. Preserve the completed Stage 1 functionality and all existing tests.

Our goal is to integrate the strongest screening components from Clara Yoon's quake_agent into MMI-Gram without silently discarding scientifically useful observations.

1. Audit and reuse Clara's existing screening gates:
Inspect the implementations in QuakeLLMmap-reference/quake_agent, especially:
- spatial_gate.py
- temporal_gate.py
- recycled_gate.py
- authenticity_gate.py
- Any existing relevance-checking logic in the assessor or orchestration code.
Determine which components can be reused directly and which need modifications.
Preserve attribution and clearly document any algorithms or thresholds carried over from Clara's repository.
Do not copy the entire quake_agent pipeline or create a second independent estimator.

2. Implement a pre-MMI evidence relevance gate:
The unified pipeline must determine whether an input contains information that can support Modified Mercalli Intensity estimation.
Potentially usable evidence includes:
- Photographs or videos of earthquake shaking effects.
- Visible damage to buildings, roads, infrastructure, or other structures.
- Credible textual descriptions of shaking effects or earthquake damage.
- Eyewitness descriptions of physical effects relevant to the MMI scale.
Insufficient evidence includes:
- Title or introduction slides without substantive damage observations.
- General event descriptions containing no site-specific shaking information.
- Unrelated photographs.
- Material whose relevance cannot be established from available content.
Use the following explicit outcomes:
- ESTIMABLE: Enough relevant evidence to proceed to MMI estimation.
- NOT_ESTIMABLE: Insufficient relevant evidence; do not compute MMI.
- REVIEW_REQUIRED: Uncertain evidence relevance; defer automatic MMI estimation pending review.
For NOT_ESTIMABLE and REVIEW_REQUIRED, set mmi_estimation = null, not 0.
Every decision must include structured reasons and evidence provenance.
Crucially, a page with no images may still be estimable from sufficiently detailed textual observations. Conversely, the presence of images alone does not make a page relevant.

3. Test Clara's page-8.pdf example:
Locate the actual page-8.pdf in the Myanmar StEER dataset.
Clara identified this page as an example that should not receive an MMI estimate.
Inspect the document and verify the expected classification from its actual content.
Add it as a regression fixture or test input if available.
If the page cannot be found, explain why and construct an equivalent test fixture based on Clara's documented description.

4. Temporal consistency screening:
- Verify that observation timestamps are consistent with the event origin time.
- Distinguish between missing timestamps and contradictory timestamps. Missing timestamps should be accepted as valid. A timestamp predating origin by > 5 minutes is a contradiction and must be flagged for review.

5. Duplicate and recycled media detection:
- Identify exact duplicate files via SHA-256 and visually similar or reused imagery across documents via perceptual hashing.
- Preserve deduplication relationships rather than silently deleting duplicates.

6. Authenticity screening:
- Incorporate checks for synthetic or AI-generated media, suspicious metadata, and known generative-tool signatures.
- Classify items with uncertain authenticity as requiring review rather than silently dropping them.

7. Spatial plausibility screening:
- Verify that observations fall within a plausible bounding region for the event.
- Flag observations outside this area for review, but do not reject solely because they are far from the epicenter, as long-distance felt reports may be scientifically valid.
- Never substitute an earthquake hypocenter or epicenter for missing observation coordinates.

8. Pre-MMI execution:
- Execute the relevance gate before model inference.
- Inputs classified as NOT_ESTIMABLE must stop immediately, preventing unnecessary API costs and ensuring downstream ShakeMap exports only receive authentic, estimable observations.

9. Offline tests & verification:
- 15 specific offline regression tests across all edge cases.
- Zero paid Gemini API calls during Stage 2 development.
- Do not commit, push, or merge yet.
```

---

## 3. Technical Audit & Adaptation of Clara's Gates

| Gate / Component | Clara's `quake_agent` Implementation | Identified Limitations in `quake_agent` | MMI-Gram Stage 2 Adaptation | Scientific & Architectural Justification |
| :--- | :--- | :--- | :--- | :--- |
| **Relevance Assessor** | Checked `has_damage_photos` in Step 3 after already making 2 LLM calls + Pinecone search. Set `mmi_estimation: 0.0`. | Wasted tokens on non-damage slides; required photos (discarded valid text observations); 0.0 is unphysical on MMI I–XII scale. | Implemented `RelevanceGate` before Step 3. Explicit `ESTIMABLE`, `NOT_ESTIMABLE`, `REVIEW_REQUIRED`. Text-only observations supported. `mmi_estimation = None`. | Saves 100% of LLM cost ($0.00). Adheres to macroseismic scaling conventions (null vs unphysical 0). |
| **Temporal Gate** | `temporal_gate.py` checked image EXIF against origin $T_0$. Rejected files with missing timestamps. | Discarded valid citizen and field reports that had stripped EXIF or missing date metadata. | `TemporalGate` checks EXIF, PDF metadata, and text timestamps. Missing timestamp (`TIMESTAMP_MISSING`) accepted as valid; contradictions (`PREDATES_EVENT` by >5 min) flagged. | Reconnaissance PDFs and social media frequently strip EXIF; missing timestamps are common and scientifically admissible. |
| **Recycled Media Gate** | `recycled_gate.py` used `imagehash` library (uninstalled external dependency) and exact hash. | Failed when third-party `imagehash` was absent; silently dropped duplicates. | Pure-Python 64-bit dHash via `PIL.Image` (9x8 grayscale adjacent gradient evaluation). Retains deduplication graph/provenance. | Zero external dependencies; preserves observation lineage for multi-source ShakeMap reconciliation. |
| **Authenticity Gate** | `authenticity_gate.py` checked for AI generation keywords. | Dropped suspicious items silently without giving human reviewers visibility. | `AuthenticityGate` detects metadata tags (Midjourney, DALL-E, SD, Stable Diffusion, ComfyUI, etc.) and routes to `HumanReviewQueue` with provenance. | Prevents silent data loss while safeguarding ShakeMap against deepfakes and AI hallucinations. |
| **Spatial Gate** | `spatial_gate.py` checked bounding box and distance from epicenter. | Risk of substituting epicenter for unknown coordinates or dropping long-distance felt reports. | `SpatialGate` checks regional bounds and township matching. Strictly preserves missing coordinates as `null`; never substitutes epicenter. | Epicenter substitution produces severe false-positive ShakeMap bullseyes. Distant felt reports are physically valid. |

---

## 4. Benchmark Verification: Clara's `page-8.pdf` Example

### Document Provenance:
- **Source File:** `/Users/jasondeng/Downloads/Files/Harvard/F26/EPS 55/Final Project/2026_Macroseismic_AI_Myanmar/pages/page-8.pdf`
- **SHA-256 Hash:** `0477e0daf7e08f35ff16a7ff6e0f83cc22f4e4d0607412d3d5a0e1219f823269`
- **Staged In:** `tests/fixtures/page-8.pdf` and `data/events/us7000pn9s/inbound/page-8.pdf`
- **Actual Content:**
  - Header: *StEER: Building Resilience through Reconnaissance*
  - Author: *Heidi Stenner (Source: USGS)*
  - Title: *USGS ShakeMap liquefaction estimate and PGA contours*
  - Observations: *Innermost (dark orange) PGA contour is 50%g. Liquefaction susceptibility model.*
  - Geolocation: `Geolocation (Address/Coordinates): N/A`

### Screening Outcome:
- **Decision:** `NOT_ESTIMABLE`
- **Evidence Types:** `["regional_hazard_model_map"]`
- **Reasoning:** *"Document contains regional hazard model or contour map (shakemap, pga contours) rather than site-specific structural damage or physical shaking observations."*
- **Seismic Intensity:** `{"mmi_estimation": null, "confidence": null, "is_calibrated": false}`
- **Quality Control:** `{"status": "SCREENED_OUT", "flags": ["PRE_MMI_NOT_ESTIMABLE"], "score": 0.0}`
- **LLM Token Usage:** `0 calls, 0 prompt tokens, 0 candidates tokens, 0 total tokens ($0.00 spent)`

---

## 5. Files Changed & Created

### New Modules Created (`src/mmigram/screening/`):
1. `src/mmigram/screening/__init__.py`: Package exports for screening subsystem.
2. `src/mmigram/screening/relevance_gate.py`: Pre-MMI Evidence Relevance Gate (deterministic keyword dictionaries, text-only macroseismic support, metered live visual fallback).
3. `src/mmigram/screening/temporal_gate.py`: Temporal Consistency Gate (EXIF, PDF creation date, text parsing, 5-minute clock drift margin, missing timestamp acceptance).
4. `src/mmigram/screening/recycled_gate.py`: Recycled Media & Duplicate Gate (SHA-256 exact matching, pure-Python 64-bit dHash perceptual hashing, Hamming distance calculation).
5. `src/mmigram/screening/authenticity_gate.py`: Authenticity Screening Gate (AI generation metadata, forensic prompt pattern matching, review queue routing).
6. `src/mmigram/screening/spatial_gate.py`: Spatial Plausibility Gate (regional bounding box, township regex extraction, strict no-epicenter-substitution policy).
7. `src/mmigram/screening/composite_screener.py`: Composite Screener orchestrating all 5 gates before model inference.

### Modified Existing Core Files:
1. `src/mmigram/core/state.py`:
   - Added `ScreeningRecord` dataclass.
   - Added `screening: Dict[str, Any]` field to `MMIGramState` TypedDict.
2. `src/mmigram/workflow/general_steer_pipeline.py`:
   - Added `CompositeScreener` initialization in `__init__`.
   - Wired Step 2b (Pre-MMI Relevance & Evidence Screening) right after coordinate parsing.
   - Wired immediate early exit on `NOT_ESTIMABLE` (`pipeline_status = "NOT_ESTIMABLE"`, `mmi_estimation = None`, 0 tokens).
   - Wired early exit on `REVIEW_REQUIRED` (defers automatic MMI estimation, routes to `HumanReviewQueue`, `mmi_estimation = None`).
   - Propagated screening review triggers to Step 6 Human Review Gate for estimable documents with warnings.
   - Enriched `final_summary` with comprehensive `"screening"` block.

### Test Fixtures & Test Suite:
1. `tests/fixtures/page-8.pdf`: Authentic Myanmar StEER ShakeMap simulation slide.
2. `data/events/us7000pn9s/inbound/page-8.pdf`: Inbound event staging copy.
3. `tests/test_screening_gates.py`: 15 comprehensive offline regression tests covering all requirements.

---

## 6. Test Suite Results (152 Passed, 1 Skipped, 0 Failures)

```text
============================= test session starts ==============================
platform darwin -- Python 3.13.9, pytest-8.4.2, pluggy-1.5.0
rootdir: /Users/jasondeng/Downloads/Files/Harvard/F26/EPS 55/Final Project/MMI-Gram-Clean
configfile: pyproject.toml
plugins: langsmith-0.14.17, anyio-4.16.0
collected 153 items

tests/test_gemini_38_migration.py ............                           [  7%]
tests/test_gemini_provider.py ................................           [ 28%]
tests/test_general_steer_pipeline.py .........                           [ 34%]
tests/test_geolocation.py .........                                      [ 40%]
tests/test_human_review_queue.py .......                                 [ 45%]
tests/test_location_comparison.py ..........                             [ 51%]
tests/test_mmi_retrieval.py .....................                        [ 65%]
tests/test_quality_control.py .......                                    [ 69%]
tests/test_reddit_connector.py .......                                   [ 74%]
tests/test_regression_page1.py .......s                                  [ 79%]
tests/test_screening_gates.py ...............                            [ 89%]
tests/test_security_redaction.py .........                               [ 95%]
tests/test_social_interface.py ..                                        [ 96%]
tests/test_steer_offline_pipeline.py ...                                 [ 98%]
tests/test_workflow_logging.py ..                                        [100%]

================== 152 passed, 1 skipped, 2 warnings in 6.02s ==================
```

### Coverage of 15 Required Offline Tests:
- **Test 1 (`test_01_relevant_structural_damage_photos`):** `test_page1.pdf` -> `ESTIMABLE`, `structural_damage_observation`.
- **Test 2 (`test_02_relevant_text_only_shaking_descriptions`):** Text-only macroseismic report without photos -> `ESTIMABLE`, `macroseismic_shaking_observation`.
- **Test 3 (`test_03_irrelevant_title_or_intro_slides`):** PVRR title/roster slide -> `NOT_ESTIMABLE`.
- **Test 4 (`test_04_clara_page8_example_not_estimable`):** Clara's `page-8.pdf` -> `NOT_ESTIMABLE`, `mmi_estimation = null`, 0 tokens.
- **Test 5 (`test_05_unrelated_photographs_scenic_team_dinner`):** Non-seismic social/dinner content -> `NOT_ESTIMABLE`.
- **Test 6 (`test_06_missing_timestamps_accepted_as_valid`):** Stripped timestamp -> `TIMESTAMP_MISSING`, valid.
- **Test 7 (`test_07_conflicting_timestamps_predating_event_flagged`):** Date predating $T_0$ by >5 min -> `PREDATES_EVENT`, flagged for review.
- **Test 8 (`test_08_exact_duplicate_files_sha256`):** Exact file match -> `EXACT_DUPLICATE`, recorded, not deleted.
- **Test 9 (`test_09_near_duplicate_images_perceptual_hash`):** dHash Hamming distance $\le 4$ -> `NEAR_DUPLICATE`.
- **Test 10 (`test_10_ambiguous_authenticity_ai_tags_queued_for_review`):** AI generator prompt/tags -> `SUSPICIOUS_AI_GENERATED`, queued for review.
- **Test 11 (`test_11_missing_coordinates_preserved_as_null`):** Unknown coordinates -> strictly `null`, no epicenter substitution.
- **Test 12 (`test_12_proper_qc_and_human_review_routing`):** MMI $\ge 9.0$ or flagged items route to `HumanReviewQueue`.
- **Test 13 (`test_13_strict_mmi_null_enforcement_never_zero`):** Unestimable inputs strictly produce `null`, never `0.0` or `0`.
- **Test 14 (`test_14_zero_token_usage_when_screening_blocks_input`):** `page-8.pdf` uses `calls = 0`, `total_tokens = 0`.
- **Test 15 (`test_15_provider_preservation_ai_studio_and_vertex`):** Both `ai_studio` and `vertex_ai` preserved and compatible with screener.

---

## 7. Current Git Status

```text
On branch feature/quake-agent-integration
Changes not staged for commit:
	modified:   docs/research/antigravity_sessions/README.md
	modified:   src/mmigram/core/state.py
	modified:   src/mmigram/workflow/general_steer_pipeline.py

Untracked files:
	data/events/us7000pn9s/inbound/page-8.pdf
	docs/research/antigravity_sessions/session_2026_11_17_stage2_implementation.md
	src/mmigram/screening/
	tests/fixtures/page-8.pdf
	tests/test_screening_gates.py
```

---

## 8. Final Scientific Robustness Review & Verification

### User Feedback & Action Taken:
1. **Image-only evidence:** Verified that scanned or image-based PDFs without extractable text evaluate to `REVIEW_REQUIRED` (`is_estimable: False`, `evidence_types: ["unverified_visual_evidence"]`), never discarded as `NOT_ESTIMABLE`. Multimodal screening call in `_evaluate_with_model` features explicit token accounting and `decision_mode: "model_inferred"`.
2. **Timestamp provenance:** Updated `TemporalGate` to distinguish `REPORTED_OBSERVATION` (high reliability), `EXIF_CAPTURE` (high reliability), `PDF_CREATION` (low reliability), and `PDF_MODIFICATION` (never used as observation time). Only reliable observation timestamps predating $T_0$ by >5 min trigger `PREDATES_EVENT`. Older PDF templates predating the event evaluate to `PDF_METADATA_ONLY` with `is_valid: True` and are accepted without contradiction.
3. **Authenticity terminology:** Replaced definitive `AUTHENTIC` status with scientifically defensible `NO_INDICATORS_DETECTED`. Replaced probability claims with `suspicion_level` and strictly uncalibrated heuristic scores (`is_calibrated: False`). Suspicious media is preserved in state and routed to `HumanReviewQueue`, never deleted.
4. **Scientific relevance & fault rupture:** Explicitly separated ground failure/fault rupture from vibratory shaking. Surface fault rupture alone without structural damage or felt shaking evaluates to `REVIEW_REQUIRED` because displacement alone cannot constrain MMI. Structural damage with fault rupture evaluates to `ESTIMABLE` with a permanent displacement caution.
5. **Dataset and Git hygiene:** Excluded inbound research datasets (`data/events/*/inbound/`) and proprietary PDF fixtures (`tests/fixtures/page-8.pdf`) in `.gitignore`. Generated permanent synthetic fixture `tests/fixtures/synthetic_page8_hazard_map.pdf` for version control.

### Final Pytest Suite Results:
```text
================== 157 passed, 1 skipped, 2 warnings in 6.07s ==================
```
- All 158 collected tests across the codebase execute with 157 passed, 1 skipped (live network guard), 0 failures.
- Zero paid API calls made during Stage 2 ($0.00 spend).
- Zero secrets or signed URLs in Git working tree.

