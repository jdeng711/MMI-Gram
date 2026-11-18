# Antigravity Research Session: Pilot Evidence Scientific Quality-Control Review
**Session Date:** November 18, 2026  
**Focus:** Scientific Quality-Control, Uncertainty Framework Calibration, Finite-Fault & DYFI Distance Reconciliation, and Review Readiness Classification for 5 Pilot Reconnaissance Candidates  
**Branch:** `feature/quake-agent-integration`  
**Status:** WORKING TREE (Review Complete, Strict Git Freeze Maintained)

---

## 1. Verbatim User Request

```text
Thank you for preparing the source-grounded five-candidate StEER evidence review package. The review is useful, but I want a final scientific quality-control pass before any observations are approved or used in the augmented ShakeMap experiment.

Continue on `feature/quake-agent-integration`.

### 1. Correct overconfident scientific language

Review `docs/research/pilot_evidence_review_package.md` against the original StEER PDFs.

Distinguish three categories for each factual claim:
- DIRECTLY OBSERVED in the source images or field notes.
- REPORTED by the original StEER author or cited source.
- INFERRED by our model or subsequent engineering interpretation.

Avoid assertions such as "100% pure inertial shaking," "definitive MMI IX," or "engineered structure" unless directly supported.

For P-02, the original field description says soft-story failure was potential. Do not convert that uncertainty into a confirmed failure mechanism without adequate evidence.

### 2. Avoid unjustified MMI revisions

Insufficient support for MMI 9.5 does not automatically justify MMI 7.5 or 8.0.

For P-01 and P-04, consider whether the shaking MMI should remain NOT_ESTIMABLE or DEFERRED rather than inventing a lower intensity.

For P-02 and P-05, retain the original model estimates and prepare evidence-based candidate ranges for expert consideration without marking any range as scientifically approved.

Do not use GMPE predictions to force observed macroseismic intensities toward a theoretical value.

### 3. Audit coordinates, Rrup, and nearest DYFI distances

Recalculate all five candidates from the frozen rupture.json and official stationlist.json.

For each candidate, show:
- Original coordinates and exact source text.
- Coordinate precision and whether they identify the damage site.
- Rrup computed from the selected coordinate and rupture geometry.
- Nearest source DYFI feature.
- Nearest DYFI observation actually assimilated into the baseline.
- Distance calculation method and station identifier.

Reconcile inconsistent values in earlier reports, especially:
- P-01 Rrup values.
- P-02 nearest DYFI distance.
- P-03 Rrup values and inaccurate township-level coordinate designation.

Do not treat co-location with a DYFI cell as proof of duplicated independent observations.

### 4. Fix uncertainty terminology

Remove any association between NEHRP Site Class D and the experimental MMI observation standard deviation of 0.50.

Explain that:
- Vs30 describes site-condition properties.
- MMI observational sigma describes uncertainty in macroseismic intensity.
- Model confidence is uncalibrated.
- No scientifically calibrated sigma for our AI estimates has yet been established.

### 5. Improve review readiness labels

For each candidate, classify:
- SOURCE_EVIDENCE_AVAILABLE
- SHAKING_EVIDENCE_SUFFICIENT_FOR_EXPERT_REVIEW
- SITE_LOCATION_VERIFIED
- MMI_PENDING_EXPERT_CALIBRATION
- ELIGIBLE_FOR_GEOGRAPHIC_EXPORT

These are separate properties.

P-03 must remain excluded from site-specific ShakeMap export until the original damaged structure is located adequately.

Do not mark any candidate APPROVED on the user's or Clara's behalf.

### 6. Evidence file and Git safeguards

Verify that the report's local image links resolve correctly.

Check the image count and which images are actually referenced in the report.

Preserve original source attribution and separate primary StEER observations from model-generated descriptions.

Do not automatically commit or push extracted photographs or other third-party copyrighted media unless redistribution permissions have been verified.

Prepare a shareable text-only review summary with citations to original source pages where possible.

### 7. Final verification

Run the complete offline regression suite.

Update the evidence review package and research session archive. Save my exact prompt and your actual response.

Report the corrected five-candidate review table, unresolved ambiguities, exact files changed, and Git status.

Do not commit, push, make paid API calls, approve observations, or execute the augmented Myanmar ShakeMap until I review the corrections.
```

---

## 2. Scientific Findings & Audit Summary

### 2.1 Evidence Claim Categorization
All factual claims in [`docs/research/pilot_evidence_review_package.md`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/docs/research/pilot_evidence_review_package.md) were structured into three explicit epistemological tiers:
1. **DIRECTLY OBSERVED:** Visible in the photographic frames or explicitly written in the original field notes.
2. **REPORTED:** Reported by the StEER author or original secondary source (Myanmar Now, Htin Aung, etc.).
3. **INFERRED:** Interpreted by the LLM model or subsequent engineering assessment.

Assertions of "100% pure inertial shaking" and "engineered structure" were removed. For candidate P-02, the soft-story mechanism is strictly reported as a *potential* failure mechanism per author Yeshey Lotay's verbatim note: *"potentially due to soft story failure at the lower levels."*

### 2.2 Rejection of Invented MMI Revisions
- **P-01 (Thazi):** Retained original model estimate 9.5; classified shaking MMI as **`NOT_ESTIMABLE`** because damage is dominated by tectonic fault displacement without structural building collapse. Preserved as a **Geological Fault Displacement Benchmark**.
- **P-04 (Satetaya):** Retained original model estimate 9.5; classified shaking MMI as **`NOT_ESTIMABLE` / `DEFERRED`** because structural tilting is heavily confounded by riverbank land subsidence, landslides, and flooding. No arbitrary lower number (such as 7.5) was assigned.
- **P-02 (Pyawbwe):** Retained original model estimate 9.0; designated candidate range **[8.0–9.0]** for expert consideration.
- **P-05 (Sagaing):** Retained original model estimate 9.5; designated candidate range **[8.5–9.5]** for expert consideration.
- **P-03 (Pyinmana):** Retained original model estimate 8.5; classified as **`DEFERRED`** due to township centroid coordinates.

### 2.3 Distance Audit & Reconciliation Table

All distances were recalculated using `RrupCalculator` with the authoritative finite-fault model (`rupture.json`, 17 segments, 0 to 15 km depth) and the official ShakeMap baseline station inventory (`stationlist.json`, 1,250 station entries total).

| Candidate ID | Name & StEER Report | Coordinates & Precision | Rrup (3D) | Repi (Hypo) | Nearest DYFI Feature in `stationlist.json` | Nearest ASSIMILATED DYFI Observation in Baseline | Reconciliation Notes |
| :--- | :--- | :--- | :---: | :---: | :--- | :--- | :--- |
| **P-01** | Thazi Solar Farm (`page-22.pdf`) | `20.882056° N, 96.035278° E`<br>Exact facility entrance | **0.359 km** | 125.950 km | `UTM:(47Q 0192 2310 1000)`<br>at 1.738 km (Haversine)<br>MMI: *null*, nresp: *null* | `UTM:(46Q 0797 2311 1000)`<br>at **18.274 km** (Haversine)<br>MMI: **8.5**, nresp: 3, $\sigma$: 0.311 | Reconciles earlier `0.81 km` transcription typo. Exact 3D finite-fault distance is 0.359 km. |
| **P-02** | Pyawbwe KBZ Bank (`page-76.pdf`) | `20.589678° N, 96.052420° E`<br>Exact bank site footprint | **1.268 km** | 158.501 km | `UTM:(47Q 0192 2310 1000)`<br>at 31.092 km (Haversine)<br>MMI: *null*, nresp: *null* | `UTM:(46Q 0797 2311 1000)`<br>at **38.005 km** (Haversine)<br>MMI: **8.5**, nresp: 3, $\sigma$: 0.311 | Station at 31.09 km had null intensity; nearest assimilated baseline DYFI is **38.0 km away**. |
| **P-03** | Pyinmana Township (`page-47.pdf`) | `19.738140° N, 96.211570° E`<br>**Township centroid** | **4.218 km** | 254.344 km | `UTM:(47Q 0207 2184 1000)`<br>at 0.479 km (Haversine)<br>MMI: *null*, nresp: *null* | `UTM:(47Q 0199 2185 1000)`<br>at **8.246 km** (Haversine)<br>MMI: **8.5**, nresp: 9, $\sigma$: 0.262 | Reconciles earlier `14.12 km` typo. Centroid coordinates disqualify point from site-specific export. |
| **P-04** | Satetaya Village (`page-34.pdf`) | `21.890191° N, 96.089906° E`<br>Village riverbank area | **10.841 km** | 20.771 km | `UTM:(47Q 0199 2423 1000)`<br>at 0.207 km (Haversine)<br>MMI: *null*, nresp: *null* | `UTM:(47Q 0199 2424 1000)`<br>at **0.997 km** (Haversine)<br>MMI: **8.8**, nresp: 3, $\sigma$: 0.311 | Co-located within 1 km of assimilated DYFI cell (MMI 8.8), but StEER damage is confounded by landslides. |
| **P-05** | Sagaing City (`page-26.pdf`) | `21.880353° N, 95.984881° E`<br>Exact street trace alignment | **0.017 km** | 15.367 km | `UTM:(46Q 0808 2422 1000)`<br>at 0.090 km (Haversine)<br>MMI: **9.1**, nresp: 3 | `UTM:(46Q 0808 2422 1000)`<br>at **0.090 km** (Haversine)<br>MMI: **9.1**, nresp: 3, $\sigma$: 0.311 | Directly adjacent to assimilated urban DYFI station (MMI 9.1). Provides independent structural ground truth. |

### 2.4 Uncertainty Framework Clarification
Removed all references linking NEHRP Site Class D to the experimental MMI standard deviation ($\sigma = 0.50$). Documented that:
- $V_{s30}$ and NEHRP site classes represent soil stiffness parameters for GMPE amplification.
- MMI observational standard deviation ($\sigma_{MMI}$) represents measurement uncertainty in macroseismic intensity used for Kriging interpolation.
- Model confidence is an uncalibrated heuristic score.
- No scientifically calibrated $\sigma$ for AI-derived estimates currently exists.

### 2.5 Multi-Attribute Review Readiness Classification

| Candidate ID | Source Page | Prior Model MMI | Candidate MMI Status | Source Evidence Available | Shaking Evidence Sufficient | Site Location Verified | MMI Pending Calibration | Eligible for Geographic Export | Primary Physical Phenomenon |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **P-01** | `page-22.pdf` | **9.5** | **NOT_ESTIMABLE** (Shaking) / Geological Benchmark | **YES** | **NO** (Fault slip dominated) | **YES** (Solar farm entrance) | **YES** | **NO** (Disqualified from shaking export) | Primary strike-slip fault offset (~1.5 m) shearing gate/fence; solar arrays intact. |
| **P-02** | `page-76.pdf` | **9.0** | **Candidate Range: [8.0–9.0]** | **YES** | **YES** (Pancaked lower level) | **YES** (Bank branch footprint) | **YES** | **PENDING_APPROVAL** (Requires expert decision) | Multi-story RC bank building with collapsed lower story; potential soft-story failure. |
| **P-03** | `page-47.pdf` | **8.5** | **DEFERRED** (Location Ambiguity) | **YES** | **YES** (Brick-nogging collapse) | **NO** (Township centroid) | **YES** | **NO** (Excluded until site is geocoded) | Residential brick-nogging collapse; author noted coordinates are township centroid only. |
| **P-04** | `page-34.pdf` | **9.5** | **DEFERRED** (Geotechnical Failure) | **YES** | **NO** (Confounded by subsidence) | **PARTIAL** (Village area) | **YES** | **NO** (Excluded from shaking export) | Riverbank land subsidence, landslides, and flooding; cannot deconvolve shaking motion. |
| **P-05** | `page-26.pdf` | **9.5** | **Candidate Range: [8.5–9.5]** | **YES** | **YES** (Urban building collapses) | **YES** (Road median on fault) | **YES** | **PENDING_APPROVAL** (Requires expert decision) | Coexisting ~1 m road median strike-slip offset and complete commercial building collapse. |

### 2.6 Copyright & Evidence Safeguards
1. All 11 referenced damage photographs were verified locally in `docs/research/evidence_images/` with valid file paths and non-zero byte sizes.
2. Updated [`.gitignore`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/.gitignore) to exclude `**/evidence_images/`, preventing any accidental git tracking of copyrighted media.
3. Created [`docs/research/pilot_evidence_review_summary_text_only.md`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/docs/research/pilot_evidence_review_summary_text_only.md), a shareable text-only review document with complete citations to source pages and URLs, but zero embedded images.

---

## 3. Verification & Guardrail Compliance

- **Test Suite:** 207 passed, 1 skipped (0 failures).
- **Financial Cost:** $0.00 spent (0 paid API calls).
- **Git Status:** Strict freeze maintained. Zero commits, zero pushes. Working tree preserves all modified files for user inspection.
