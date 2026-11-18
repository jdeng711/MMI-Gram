# MMI-Gram Myanmar Mw 7.7 Pilot Evidence Review: Text-Only Summary
**USGS ShakeMap 4.5 Augmented Ingestion Pilot (Event `us7000pn9s`)**  
*Harvard University EPS 55 Final Project & USGS Collaboration (Clara Yoon, Jason Deng)*  
*Document Version: 2.2.0 | Date: November 18, 2026 | Status: PENDING EXPERT REVIEW*

---

## 1. Executive Summary

This shareable, text-only document summarizes the source-grounded expert review for the **five pilot macroseismic observations** selected from the March 28, 2025 Mw 7.7 Mandalay, Myanmar earthquake (`us7000pn9s`). 

This summary contains **no embedded media or third-party photographs**, citing instead the original Structural Extreme Events Reconnaissance (StEER) Virtual Assessment Structural Team (VAST) report pages and source URLs.

### Core Seismological Safeguards & Provenance Protocol
1. **Zero Automated Scientific Approvals:** All 5 pilot records remain strictly **`PENDING_EXPERT_REVIEW`**.
2. **Virtual Assessment Provenance:** StEER VAST reports represent virtual desk evaluations of secondary online media, **NOT in-situ physical engineering inspections or independently verified building footprints**.
3. **Separation of Technical Export vs. Scientific Validity:** Generating ShakeMap input files does not constitute seismological validation.
4. **Differentiation of Shaking, Fault Rupture, and Ground Failure:** Under Wood & Neumann (1931), building collapse alone is not definitive proof of MMI IX. Structural vulnerability, primary fault displacement, and geotechnical slope failure must be accounted for before assigning shaking intensity. MMI evaluates ground shaking severity through observed structural and environmental effects across a range of motion frequencies, rather than permanent fault offset.
5. **No Invented MMI Revisions:** Insufficient evidence for MMI 9.5 does not justify inventing a lower intensity (e.g. 7.5 or 8.0). If shaking motion cannot be decoupled from ground failure or surface slip, the shaking intensity must remain **`NOT_ESTIMABLE`** or **`DEFERRED`**.
6. **Separation of Recommendations and Formal Review:** Provisional screening recommendations are clearly separated from formal human expert review records, which remain blank pending expert action.

---

## 2. Reconciled Baseline Observation Inventory

- **Total Original Features in `stationlist.json`:** 1,250 stations (1,244 DYFI macroseismic, 6 instrumental seismic).
- **Global DYFI Usable Amplitudes:** 191 DYFI stations have valid numeric MMI across Southeast Asia (1,053 had null intensity and null responses).
- **Regional Modeled Grid Domain Ingestion:** ShakeMap 4.5 ingested 521 stations falling within the Myanmar regional bounding box:
  - **516 DYFI stations**
  - **5 seismic stations** (1 station in southern Thailand was outside bounds).
- **Active Model Assimilation:**
  - Of the 516 regional DYFI stations, **91 had valid numeric observed MMI** and actively constrained the Kriging interpolation.
  - **425 DYFI stations had null MMI** and were flagged by ShakeMap as unobserved (`total_flagged_mi: 425`).
  - **5 instrumental seismic stations** provided recorded ground motions (PGA/PGV/SA) from which MMI was also derived.
  - The baseline interpolation field was therefore actively constrained by **91 observed DYFI intensity values + 5 instrumental seismic stations** within the regional map.

---

## 3. Authoritative Distance Metrics & Baseline DYFI Audit

Distances are computed using the authoritative USGS finite-fault model (`rupture.json`, 17 segments, 0–15 km depth) and the official ShakeMap station database (`shake_data.hdf` and `shake_result.hdf`):
- **`Repi`:** Epicentral surface distance to USGS epicenter (`22.011° N, 95.9363° E`).
- **`Rhypo`:** Hypocentral 3D distance ($\sqrt{\text{Repi}^2 + 10.0^2}$).
- **`Rrup`:** Minimum 3D Euclidean distance to the triangulated finite-fault rupture surface.

| Candidate ID | Reconnaissance Target & Page | Coordinates & Provenance | Repi (km) | Rhypo (km) | Rrup (km) | Nearest Feature in 1,250 Stationlist | Nearest ASSIMILATED DYFI in Baseline Model | Haversine Distance to Nearest Assimilated DYFI | Baseline Observation Void Status |
| :--- | :--- | :--- | :---: | :---: | :---: | :--- | :--- | :---: | :--- |
| **P-01** | Thazi Solar Farm (`page-22.pdf`) | `20.882056° N, 96.035278° E`<br>Site-associated entrance | 125.950 | 126.346 | **0.359** | `UTM:(47Q 0192 2310 1000)`<br>Dist: 1.738 km (MMI: *null*) | `UTM:(46Q 0797 2311 1000)`<br>MMI: **8.5** (nresp: 3, $\sigma$: 0.311) | **18.274 km** | Reconciles earlier `0.81 km` transcription typo. Exact Rrup is 0.359 km. |
| **P-02** | Pyawbwe KBZ Bank (`page-76.pdf`) | `20.589678° N, 96.052420° E`<br>Site-associated POI pin | 158.501 | 158.816 | **1.268** | `UTM:(47Q 0192 2310 1000)`<br>Dist: 31.092 km (MMI: *null*) | `UTM:(46Q 0797 2311 1000)`<br>MMI: **8.5** (nresp: 3, $\sigma$: 0.311) | **38.005 km** | **CONFIRMED 38.0-KM VOID:** Nearest assimilated DYFI is 38.0 km away; nearest seismic station is NPW at 90.6 km. |
| **P-03** | Pyinmana Township (`page-47.pdf`) | `19.738140° N, 96.211570° E`<br>**Township centroid only** | 254.344 | 254.541 | **4.218\***<br>*(from centroid)* | `UTM:(47Q 0207 2184 1000)`<br>Dist: 0.479 km (MMI: *null*) | `UTM:(47Q 0199 2185 1000)`<br>MMI: **8.5** (nresp: 9, $\sigma$: 0.262) | **8.246 km** | Reconciles earlier `14.12 km` typo. Rrup is 4.218 km from centroid, NOT the unlocated damaged house. |
| **P-04** | Satetaya Village (`page-34.pdf`) | `21.890191° N, 96.089906° E`<br>Alluvial village area | 20.771 | 23.053 | **10.841** | `UTM:(47Q 0199 2423 1000)`<br>Dist: 0.207 km (MMI: *null*) | `UTM:(47Q 0199 2424 1000)`<br>MMI: **8.8** (nresp: 3, $\sigma$: 0.311) | **0.997 km** | Co-located within 1.0 km of assimilated DYFI cell (MMI 8.8), but damage is confounded by landslides/subsidence. |
| **P-05** | Sagaing City (`page-26.pdf`) | `21.880353° N, 95.984881° E`<br>Street median on fault | 15.367 | 18.334 | **0.017** | `UTM:(46Q 0808 2422 1000)`<br>Dist: 0.090 km (MMI: 9.1) | `UTM:(46Q 0808 2422 1000)`<br>MMI: **9.1** (nresp: 3, $\sigma$: 0.311) | **0.090 km** | Directly adjacent to assimilated urban DYFI station (MMI 9.1). Provides independent structural cross-validation. |

---

## 4. Multi-Attribute Review Readiness Summary

| Pilot ID | Source Page | Prior Model MMI | Provisional Screening Recommendation | Source Evidence Available | Shaking Evidence Sufficient | Site Location Verified | MMI Pending Calibration | Eligible for Geographic Export | Primary Physical Phenomenon |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **P-01** | `page-22.pdf` | **9.5** | **PROVISIONAL_GEOLOGICAL_BENCHMARK** (Exclude from Shaking) | **YES** | **NO** (Fault slip dominated) | **YES** (Facility entrance) | **YES** | **NO** (Disqualified from shaking export) | Primary strike-slip fault offset (~1.5 m) shearing gate/fence; solar arrays intact. |
| **P-02** | `page-76.pdf` | **9.0** | **PROVISIONAL_RANGE_8.0_9.0** (Pending Expert Calibration) | **YES** | **YES** (Pancaked lower level) | **YES** (Bank branch POI) | **YES** | **PENDING_APPROVAL** (Requires expert decision) | Multi-story RC bank building with collapsed lower story; potential soft-story failure. |
| **P-03** | `page-47.pdf` | **8.5** | **PROVISIONAL_DEFER** (Township Centroid Ambiguity) | **YES** | **YES** (Brick-nogging collapse) | **NO** (Township centroid) | **YES** | **NO** (Excluded until site is geocoded) | Residential brick-nogging collapse; author noted coordinates are township centroid only. |
| **P-04** | `page-34.pdf` | **9.5** | **PROVISIONAL_DEFER** (Geotechnical Confounding) | **YES** | **NO** (Confounded by subsidence) | **PARTIAL** (Village area) | **YES** | **NO** (Excluded from shaking export) | Riverbank land subsidence, landslides, and flooding; cannot deconvolve shaking motion. |
| **P-05** | `page-26.pdf` | **9.5** | **PROVISIONAL_RANGE_8.5_9.5** (Pending Expert Calibration) | **YES** | **YES** (Urban building collapses) | **YES** (Road median on fault) | **YES** | **PENDING_APPROVAL** (Requires expert decision) | Coexisting ~1 m road median strike-slip offset and complete commercial building collapse. |

---

## 5. Candidate Evidence Briefs

### Candidate P-01: Thazi Solar Farm Perimeter Offset
- **StEER Virtual Assessment:** Report Page 22 | Author: Carlos Arteta
- **Attribution:** Singaporean engineer Htin Aung (YouTube `https://www.youtube.com/watch?v=77ubC4bcgRM`)
- **Coordinates:** `20°52'55.4"N, 96°02'07.0"E` (`20.882056° N, 96.035278° E`) | Repi: 125.950 km, Rhypo: 126.346 km, Rrup: 0.359 km
- **Provisional Recommendation:** `PROVISIONAL_GEOLOGICAL_BENCHMARK_EXCLUDE_SHAKING`. Video captures primary fault rupture shearing compound fence; solar panels remain standing. Pure shaking MMI is `NOT_ESTIMABLE`.

### Candidate P-02: KBZ Bank Branch (Pyawbwe)
- **StEER Virtual Assessment:** Report Page 76 | Authors: Yeshey Lotay (via Lalrinpuii Tlau)
- **Attribution:** Posted by Myanmar Now on Facebook
- **Coordinates:** `20.589678° N, 96.052420° E` (Site-associated POI pin) | Repi: 158.501 km, Rhypo: 158.816 km, Rrup: 1.268 km
- **Provisional Recommendation:** `PROVISIONAL_RANGE_8.0_9.0_PENDING_EXPERT`. 5-story reinforced concrete building with collapsed lower story ("potentially due to soft story failure"). **Confirmed 38.0-km baseline DYFI void**. Retain model estimate 9.0; candidate range [8.0–9.0] for expert calibration.

### Candidate P-03: Pyinmana Residential Masonry Collapse (Naypyidaw)
- **StEER Virtual Assessment:** Report Page 47 | Author: Hnin Wai Lwin
- **Attribution:** Facebook Pyinmana Update News Page
- **Coordinates:** `19.738140° N, 96.211570° E` (Township centroid only; author noted: `"(Only mentioned township coordinate, not accurate location)"`) | Repi: 254.344 km, Rhypo: 254.541 km, Rrup: 4.218 km (from centroid)
- **Provisional Recommendation:** `PROVISIONAL_DEFER_TOWNSHIP_CENTROID`. Excluded from site-specific ShakeMap export until building coordinates are recovered.

### Candidate P-04: Satetaya Village Structural & Geotechnical Failure (Mandalay)
- **StEER Virtual Assessment:** Report Page 34 | Author: Yeshey Lotay
- **Attribution:** World Forum & DVB TV News Facebook, TikTok (`@phoophoo891997`)
- **Coordinates:** `21.890191° N, 96.089906° E` | Repi: 20.771 km, Rhypo: 23.053 km, Rrup: 10.841 km
- **Provisional Recommendation:** `PROVISIONAL_DEFER_GEOTECHNICAL_FAILURE`. Damage is confounded by riverbank subsidence, lateral spreading, and landslides. Pure shaking intensity is `NOT_ESTIMABLE` / `DEFERRED`.

### Candidate P-05: Sagaing City Surface Rupture & Urban Structural Devastation
- **StEER Virtual Assessment:** Report Page 26 | Authors: Heidi Stenner & Janise Rodgers
- **Attribution:** Heung Min Son (`@heungburma`, Twitter/X)
- **Coordinates:** `21°52'49.27"N, 95°59'5.57"E` (`21.880353° N, 95.984881° E`) | Repi: 15.367 km, Rhypo: 18.334 km, Rrup: 0.017 km
- **Provisional Recommendation:** `PROVISIONAL_RANGE_8.5_9.5_PENDING_EXPERT`. Coexisting ~1 m road median strike-slip offset and complete commercial building collapse directly on fault trace. Candidate range [8.5–9.5] for expert calibration.
