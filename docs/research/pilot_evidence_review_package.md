# MMI-Gram Myanmar Mw 7.7 Pilot Evidence-Review Package
**USGS ShakeMap 4.5 Augmented Ingestion Pilot (Event `us7000pn9s`)**  
*Harvard University EPS 55 Final Project & USGS Collaboration (Clara Yoon, Jason Deng)*  
*Document Version: 2.2.0 | Date: November 18, 2026 | Status: PENDING EXPERT REVIEW*

---

## 1. Executive Summary & Review Objectives

This document provides the official, source-grounded expert review package for the **5-observation pilot subset** selected from the 184 candidate evaluations of the March 28, 2025 Mw 7.7 Mandalay, Myanmar earthquake (`us7000pn9s`).

### Scientific Safeguards & Provenance Protocol
1. **Zero Automated Scientific Approval:** Although 157 of the 184 records in `agent_evaluations_myanmar.json` meet basic syntactic and bounding criteria for technical export, **NONE has received seismological human expert review**. All 184 records remain strictly **`PENDING_EXPERT_REVIEW`**.
2. **Separation of Technical Compatibility vs. Scientific Validation:** Generating a GeoJSON file demonstrates technical parser compatibility; it does NOT constitute seismological validation. Only human expert-approved records may be assimilated into a scientific ShakeMap run.
3. **Rigorous Grounding in Primary Reconnaissance Evidence:** Rather than accepting automated model descriptions at face value, this document places the **original Structural Extreme Events Reconnaissance (StEER) virtual field reports, damage photographs, VAST author notes, and source coordinates** side-by-side with prior model estimates.
4. **Source Provenance Clarification:** StEER Virtual Assessment Structural Team (VAST) reports represent **virtual desk assessments of secondary media** (social media videos, news photographs, community posts), **NOT in-situ physical engineering field surveys or independently verified building footprints**.
5. **Differentiation of Shaking, Fault Rupture, and Ground Failure:** Under Wood & Neumann (1931), building collapse alone is not definitive proof of MMI IX. Structural vulnerability (EMS-98 Class A vs. C), primary tectonic fault displacement, and geotechnical slope failure must be accounted for before assigning shaking intensity. The Modified Mercalli Intensity scale evaluates the severity of earthquake ground shaking through observed effects on people, objects, and structures across a range of motion frequencies, rather than permanent tectonic surface fault offset.
6. **No Invented MMI Revisions:** Insufficient support for a high model estimate (e.g., MMI 9.5) does not justify arbitrarily inventing a lower number (e.g., 7.5 or 8.0). If the shaking motion cannot be decoupled from ground failure or surface slip, the shaking intensity must remain **`NOT_ESTIMABLE`** or **`DEFERRED`**. GMPE predictions must NEVER be used to force observed macroseismic intensities toward theoretical values.

---

## 2. Baseline Observation Inventory & DYFI Assimilation Reconciliation

### Reconciliation of the 191-vs-516 DYFI Discrepancy
Earlier preliminary reports stated that 516 macroseismic stations and 5 instrumental stations were assimilated into the USGS baseline ShakeMap. A rigorous audit of `stationlist.json`, the assembled SQLite database in `shake_data.hdf`, and the model output in `shake_result.hdf` clarifies the exact station counts:

1. **Original Station Inventory (`stationlist.json`):**
   - Contains **1,250 total features**:
     - **1,244 DYFI macroseismic stations** (UTM 1-km geocells).
     - **6 seismic stations** (`GE`, `IU`, `MM`, `TM` networks).
   - Across all 1,244 DYFI features in the complete file:
     - **191 DYFI stations** have valid numeric MMI values (based on citizen questionnaires submitted across Southeast Asia).
     - **1,053 DYFI stations** have `intensity: null` and `nresp: null` (unobserved geocells).
2. **Regional Model Domain Ingestion (`shake_data.hdf` & `shake_result.hdf`):**
   - ShakeMap 4.5 filters input stations to the geographic bounding box of the event grid (with regional buffer): Lat ~[14.58°, 25.70°], Lon ~[91.55°, 101.31°].
   - Exactly **521 total stations fall within this regional modeled domain**:
     - **516 DYFI stations**
     - **5 seismic stations** (`TM` in southern Thailand falls outside the box).
   - This explains why `info.json` under `input.event_information` reports:
     `'intensity_observations': '516', 'seismic_stations': '5'` (total 521).
3. **Active Assimilation in Model Interpolation:**
   - Of the 516 DYFI stations within the regional model domain:
     - **91 DYFI stations** have valid, non-null observed MMI values (and `intensity_flag == '0'`).
     - **425 DYFI stations** have `intensity: null` and were unobserved; ShakeMap flagged them (`total_flagged_mi: 425` in `info.json`). These unobserved cells do not contribute data to the Kriging field.
     - The **5 seismic stations** possess instrumental ground motions (PGA, PGV, SA) from which MMI was also derived.
   - For event bias calculation (`bias_stations`), ShakeMap selected **36 stations** within 120 km of the rupture.
4. **Conclusion:**
   - The earlier statement that "516 macroseismic stations were assimilated" conflated the **total regional station entries ingested into the bounding box (516)** with the **stations possessing valid, non-null observed MMI (91)**.
   - The baseline interpolation is actively constrained by **91 observed DYFI macroseismic intensity values** and **5 instrumental seismic stations (measuring PGA, PGV, and SA)** within the Myanmar regional grid, plus 95 DYFI observations further south in Thailand/Bangkok.

---

## 3. Distance Metric Definitions & Authoritative Audit

To eliminate ambiguity, three distinct seismological distance metrics are defined and reported:
- **`Repi` (Epicentral Surface Distance):** Great-circle / Haversine surface distance from the observation coordinates to the USGS epicenter (`22.011° N, 95.9363° E`).
- **`Rhypo` (Hypocentral 3D Distance):** Three-dimensional straight-line distance from the surface observation to the earthquake hypocenter at depth ($Z = 10.0\text{ km}$): $\text{Rhypo} = \sqrt{\text{Repi}^2 + 10.0^2}$.
- **`Rrup` (Finite-Fault 3D Rupture Distance):** Minimum 3D Euclidean distance from the surface observation to the triangulated finite-fault rupture surface (`rupture.json`, 17 segments, top trace depth 0.0 km, down-dip depth 15.0 km), computed via `RrupCalculator`.

### Authoritative Distance & Baseline DYFI Audit Table

| Candidate ID | Reconnaissance Target & Page | Coordinates & Provenance | Repi (km) | Rhypo (km) | Rrup (km) | Nearest Feature in 1,250 Stationlist | Nearest ASSIMILATED DYFI in Baseline Model | Haversine Distance to Nearest Assimilated DYFI | Baseline Observation Void Status |
| :--- | :--- | :--- | :---: | :---: | :---: | :--- | :--- | :---: | :--- |
| **P-01** | Thazi Solar Farm (`page-22.pdf`) | `20.882056° N, 96.035278° E`<br>Site-associated entrance | 125.950 | 126.346 | **0.359** | `UTM:(47Q 0192 2310 1000)`<br>Dist: 1.738 km (MMI: *null*) | `UTM:(46Q 0797 2311 1000)`<br>MMI: **8.5** (nresp: 3, $\sigma$: 0.311) | **18.274 km** | Reconciles earlier `0.81 km` transcription typo. Exact Rrup is 0.359 km. |
| **P-02** | Pyawbwe KBZ Bank (`page-76.pdf`) | `20.589678° N, 96.052420° E`<br>Site-associated POI pin | 158.501 | 158.816 | **1.268** | `UTM:(47Q 0192 2310 1000)`<br>Dist: 31.092 km (MMI: *null*) | `UTM:(46Q 0797 2311 1000)`<br>MMI: **8.5** (nresp: 3, $\sigma$: 0.311) | **38.005 km** | **CONFIRMED 38.0-KM VOID:** Nearest assimilated DYFI is 38.0 km away; nearest seismic station is NPW at 90.6 km. |
| **P-03** | Pyinmana Township (`page-47.pdf`) | `19.738140° N, 96.211570° E`<br>**Township centroid only** | 254.344 | 254.541 | **4.218\***<br>*(from centroid)* | `UTM:(47Q 0207 2184 1000)`<br>Dist: 0.479 km (MMI: *null*) | `UTM:(47Q 0199 2185 1000)`<br>MMI: **8.5** (nresp: 9, $\sigma$: 0.262) | **8.246 km** | Reconciles earlier `14.12 km` typo. Rrup is 4.218 km from centroid, NOT the unlocated damaged house. |
| **P-04** | Satetaya Village (`page-34.pdf`) | `21.890191° N, 96.089906° E`<br>Alluvial village area | 20.771 | 23.053 | **10.841** | `UTM:(47Q 0199 2423 1000)`<br>Dist: 0.207 km (MMI: *null*) | `UTM:(47Q 0199 2424 1000)`<br>MMI: **8.8** (nresp: 3, $\sigma$: 0.311) | **0.997 km** | Co-located within 1.0 km of assimilated DYFI cell (MMI 8.8), but damage is confounded by landslides/subsidence. |
| **P-05** | Sagaing City (`page-26.pdf`) | `21.880353° N, 95.984881° E`<br>Street median on fault | 15.367 | 18.334 | **0.017** | `UTM:(46Q 0808 2422 1000)`<br>Dist: 0.090 km (MMI: 9.1) | `UTM:(46Q 0808 2422 1000)`<br>MMI: **9.1** (nresp: 3, $\sigma$: 0.311) | **0.090 km** | Directly adjacent to assimilated urban DYFI station (MMI 9.1). Provides independent structural cross-validation. |

> [!NOTE]
> **Co-location vs. Duplication Principle:** A DYFI cell aggregates broad subjective questionnaires across a 1 km $\times$ 1 km geocell. A StEER observation represents a virtual engineering assessment of a specific structural asset. Co-location with an existing DYFI cell does **NOT** indicate a duplicated observation, but provides valuable cross-validation between citizen perception and reconnaissance-derived structural-damage evidence.

---

## 4. Multi-Attribute Review Readiness Summary

Each candidate is evaluated across five independent properties:
1. `SOURCE_EVIDENCE_AVAILABLE`: Primary virtual field documentation retrieved.
2. `SHAKING_EVIDENCE_SUFFICIENT_FOR_EXPERT_REVIEW`: Observable physical damage provides clear shaking indicators (not obscured by fault slip or slope failure).
3. `SITE_LOCATION_VERIFIED`: Coordinates identify the exact observed damage site footprint (not a regional centroid).
4. `MMI_PENDING_EXPERT_CALIBRATION`: Final MMI rating and observational uncertainty strictly require human expert decision.
5. `ELIGIBLE_FOR_GEOGRAPHIC_EXPORT`: Validated for site-specific ShakeMap ingestion (`agent_mmi_dat.json`).

| Pilot ID | Source Page | Prior Model MMI | Provisional Screening Recommendation | Source Evidence Available | Shaking Evidence Sufficient | Site Location Verified | MMI Pending Calibration | Eligible for Geographic Export | Primary Physical Phenomenon |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **P-01** | `page-22.pdf` | **9.5** | **PROVISIONAL_GEOLOGICAL_BENCHMARK** (Exclude from Shaking) | **YES** | **NO** (Fault slip dominated) | **YES** (Facility entrance) | **YES** | **NO** (Disqualified from shaking export) | Primary strike-slip fault offset (~1.5 m) shearing gate/fence; solar arrays intact. |
| **P-02** | `page-76.pdf` | **9.0** | **PROVISIONAL_RANGE_8.0_9.0** (Pending Expert Calibration) | **YES** | **YES** (Pancaked lower level) | **YES** (Bank branch POI) | **YES** | **PENDING_APPROVAL** (Requires expert decision) | Multi-story RC bank building with collapsed lower story; potential soft-story failure. |
| **P-03** | `page-47.pdf` | **8.5** | **PROVISIONAL_DEFER** (Township Centroid Ambiguity) | **YES** | **YES** (Brick-nogging collapse) | **NO** (Township centroid) | **YES** | **NO** (Excluded until site is geocoded) | Residential brick-nogging collapse; author noted coordinates are township centroid only. |
| **P-04** | `page-34.pdf` | **9.5** | **PROVISIONAL_DEFER** (Geotechnical Confounding) | **YES** | **NO** (Confounded by subsidence) | **PARTIAL** (Village area) | **YES** | **NO** (Excluded from shaking export) | Riverbank land subsidence, landslides, and flooding; cannot deconvolve shaking motion. |
| **P-05** | `page-26.pdf` | **9.5** | **PROVISIONAL_RANGE_8.5_9.5** (Pending Expert Calibration) | **YES** | **YES** (Urban building collapses) | **YES** (Road median on fault) | **YES** | **PENDING_APPROVAL** (Requires expert decision) | Coexisting ~1 m road median strike-slip offset and complete commercial building collapse. |

---

## 5. Source-Grounded Evidence Review Cards

---

### Candidate P-01: Thazi Solar Farm Perimeter Offset

#### A. Original StEER Virtual Assessment Evidence & Metadata
- **Source Document:** StEER Virtual Assessment Structural Team (VAST) Report Page 22
- **Local File Path:** [`2026_Macroseismic_AI_Myanmar/pages/page-22.pdf`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/2026_Macroseismic_AI_Myanmar/pages/page-22.pdf)
- **VAST Author:** Carlos Arteta
- **StEER Geolocation Entry:** `GP Energy Myanmar's Thapyawa solar farm, located near the town of Thazi, Myanmar (Coordinates: 20°52'55.4"N 96°02'07.0"E)`
- **Original Source Attribution:** Singaporean engineer Htin Aung (YouTube `https://www.youtube.com/watch?v=77ubC4bcgRM`)
- **StEER Short Description (Verbatim):**
  > *"As reported by Singaporean engineer Htin Aung, video shows initial shaking from the earthquake, followed at about 14 sec, the Sagaing fault ruptures the ground surface, possibly the first time that fault rupture has been recorded in video. The fault line traverses the video from upper left to middle right. Land on either side shifts abruptly as the fault ruptures through the scene."*

#### B. Primary Photographic Evidence
![P-01 CCTV Fault Rupture](evidence_images/page_022_img_3_Im2.jpg)  
*Figure P-01.1: Security camera frame showing primary surface fault rupture traversing the compound entrance and fence line at GP Energy Thapyawa solar farm.*

#### C. Categorized Evidence Claims
- **DIRECTLY OBSERVED:** Security camera video shows horizontal ground displacement cutting across entrance gate and fence line; fence fabric is distorted and gate posts displaced; solar panel support frames and prefabricated cabins visible in the compound remain standing without collapsed frames.
- **REPORTED:** Author Carlos Arteta reports video was recorded at GP Energy Myanmar's Thapyawa solar farm near Thazi, posted by Singaporean engineer Htin Aung; reports fault rupture traverses the video from upper left to middle right at approximately 14 seconds into shaking.
- **INFERRED:** Horizontal offset across the fault trace is approximately 1.0–2.0 m strike-slip. Ground shaking intensity cannot be reliably evaluated from this footage because the primary dramatic impact is surface fault displacement rather than structural failure of calibrated buildings.

#### D. Prior Model-Generated Assessment (`agent_evaluations_myanmar.json`)
- **Assigned MMI:** **9.5** (Preserved model estimate) | **Confidence:** 0.90
- **Model Typology:** Industrial utility compound entrance with perimeter infrastructure and modular cabins.
- **Model Reasoning:** Direct primary surface rupture through built facilities corresponds to MMI IX to X.

#### E. Provisional Screening Recommendation
- **Recommendation:** **`PROVISIONAL_GEOLOGICAL_BENCHMARK_EXCLUDE_SHAKING`**.
- **Rationale:** The observed deformation is dominated by tectonic surface fault offset. The Modified Mercalli Intensity scale evaluates the severity of ground shaking through observed effects on structures across a range of motion frequencies, rather than permanent fault offset. Permanent ground displacement is an environmental surface rupture parameter (ESI-07 scale), not a measure of vibrational ground motion. Pure ground shaking MMI is **`NOT_ESTIMABLE`** from the available evidence. Retain model estimate 9.5 as uncalibrated baseline; classify observation as a Geological Fault Displacement Benchmark; do NOT export to ShakeMap as a ground shaking observation.

#### F. Editable Expert-Review Record
```text
Reviewer Decision: [ ] APPROVE   [ ] REVISE   [ ] REJECT   [ ] DEFER
Approved Shaking MMI: [      ]
Eligible for ShakeMap Shaking Export: [ ] YES   [ ] NO
Assigned Observation Uncertainty (sigma): [      ]
Reviewer Identity: _________________________________________
Date of Review: ________________________
Scientific Rationale & Review Notes:
_______________________________________________________________________________
```

---

### Candidate P-02: KBZ Bank Branch (Pyawbwe)

#### A. Original StEER Virtual Assessment Evidence & Metadata
- **Source Document:** StEER Virtual Assessment Structural Team (VAST) Report Page 76
- **Local File Path:** [`2026_Macroseismic_AI_Myanmar/pages/page-76.pdf`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/2026_Macroseismic_AI_Myanmar/pages/page-76.pdf)
- **VAST Authors:** Yeshey Lotay (via Lalrinpuii Tlau)
- **StEER Geolocation Entry:** `KBZ Bank branch at Pyawbwe (20.589678, 96.05242)`
- **Original Source Attribution:** Posted by Myanmar Now on Facebook
- **StEER Short Description (Verbatim):**
  > *"5-story KBZ Bank branch at Pyawbwe collapsed, potentially due to soft story failure at the lower levels."*

#### B. Primary Photographic Evidence
| Main Elevation: Collapsed Lower Stories | Column Failure Detail | Streetscape Context & Backward Tilt |
| :---: | :---: | :---: |
| ![P-02 Main Elevation](evidence_images/page_076_img_3_Im2.jpg) | ![P-02 Column Shear](evidence_images/page_076_img_4_Im3.jpg) | ![P-02 Context](evidence_images/page_076_img_5_Im4.jpg) |
| *Figure P-02.1: Collapsed lower level with upper stories resting tilted backward.* | *Figure P-02.2: Severely fractured ground-floor columns with exposed reinforcement.* | *Figure P-02.3: Overall street elevation showing building tilt and surrounding debris.* |

#### C. Categorized Evidence Claims
- **DIRECTLY OBSERVED:** Multi-story commercial building with ground floor columns fractured, crushed, and pancaked; upper stories are structurally intact but tilted backward; commercial bank signage ("KBZ BANK") visible; ground surface immediately in front of building shows rubble but no visible surface fault rupture scarp.
- **REPORTED:** StEER authors report the structure is a 5-story KBZ Bank branch in Pyawbwe; that it collapsed; and that collapse was *"potentially due to soft story failure at the lower levels."* Source attributed to Myanmar Now. Coordinates provided: `(20.589678, 96.05242)`.
- **INFERRED:** Structural framing is consistent with a reinforced concrete frame with masonry infill. While failure geometry is consistent with an open ground banking hall soft-story irregularity, construction drawings, confinement detailing, and reinforcement ratios are unverified. Retain model estimate 9.0; candidate range for expert consideration is [8.0–9.0].

#### D. Prior Model-Generated Assessment (`agent_evaluations_myanmar.json`)
- **Assigned MMI:** **9.0** (Preserved model estimate) | **Confidence:** 0.90
- **Model Typology:** Multi-story commercial reinforced concrete frame building with masonry infill.
- **Model Reasoning:** MMI IX criteria: 'Damage great in substantial buildings, with partial or complete collapse; well-designed frame structures thrown out of plumb.'

#### E. Provisional Screening Recommendation
- **Recommendation:** **`PROVISIONAL_RANGE_8.0_9.0_PENDING_EXPERT`**.
- **Rationale:** Photographs document severe structural distress without through-going surface fault scarp. If non-ductile detailing precipitated ground-floor collapse under moderate shaking, MMI 8.0–8.5 is plausible; if substantial framing with adequate detailing failed, MMI 9.0 is supported.
- **Data Gap Verification:** The nearest assimilated DYFI station in the baseline model is `UTM:(46Q 0797 2311 1000)` at **38.005 km**, and the nearest seismic station is `NPW` at **90.585 km**. This confirms an immense **38.0-km observation void** along the southern rupture.

#### F. Editable Expert-Review Record
```text
Reviewer Decision: [ ] APPROVE   [ ] REVISE   [ ] REJECT   [ ] DEFER
Approved Shaking MMI: [      ]
Eligible for ShakeMap Shaking Export: [ ] YES   [ ] NO
Assigned Observation Uncertainty (sigma): [      ]
Reviewer Identity: _________________________________________
Date of Review: ________________________
Scientific Rationale & Review Notes:
_______________________________________________________________________________
```

---

### Candidate P-03: Pyinmana Residential Masonry Collapse (Naypyidaw)

#### A. Original StEER Virtual Assessment Evidence & Metadata
- **Source Document:** StEER Virtual Assessment Structural Team (VAST) Report Page 47
- **Local File Path:** [`2026_Macroseismic_AI_Myanmar/pages/page-47.pdf`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/2026_Macroseismic_AI_Myanmar/pages/page-47.pdf)
- **VAST Author:** Hnin Wai Lwin
- **StEER Geolocation Entry (CRITICAL CAVEAT):**
  > `Pyinmana Township, Naypyidaw, Myanmar (19.73814,96.21157)`  
  > **`(Only mentioned township coordinate, not accurate location)`**
- **Original Source Attribution:** Facebook Pyinmana Update News Page
- **StEER Short Description (Verbatim):**
  > *"Photo showing the collapse of single-family houses. Brick-nogging houses collapsed due to the failure of masonry infilled walls"*

#### B. Primary Photographic Evidence
| Collapsed Residential Structure | Infill Wall Failure Detail |
| :---: | :---: |
| ![P-03 Residential Collapse](evidence_images/page_047_img_3_Im2.jpg) | ![P-03 Rubble Heap](evidence_images/page_047_img_4_Im3.jpg) |
| *Figure P-03.1: Collapsed timber-framed brick-nogging single-family home.* | *Figure P-03.2: Complete blowout and rubble collapse of unreinforced brick masonry walls.* |

#### C. Categorized Evidence Claims
- **DIRECTLY OBSERVED:** Collapse of residential structures; fallen timber roof beams and unreinforced red clay brick debris; timber framing joints separated.
- **REPORTED:** Author Hnin Wai Lwin reports single-family brick-nogging houses collapsed due to failure of masonry infilled walls in Pyinmana Township; explicitly documented: `"(Only mentioned township coordinate, not accurate location)"`.
- **INFERRED:** High seismic vulnerability (EMS-98 Class A/B). Collapse of brick-nogging can occur under moderate shaking (MMI VII–VIII). Model labeled coordinates as `"exact"`, directly contradicting the author's explicit caveat.

#### D. Prior Model-Generated Assessment (`agent_evaluations_myanmar.json`)
- **Assigned MMI:** **8.5** (Preserved model estimate) | **Confidence:** 0.85
- **Model Typology:** Single-family residential buildings; timber frame with brick-nogging masonry infill.
- **Model Reasoning:** Near-total collapse of residential dwellings with thrown out brick walls.

#### E. Provisional Screening Recommendation
- **Recommendation:** **`PROVISIONAL_DEFER_TOWNSHIP_CENTROID`**.
- **Rationale:** The coordinates `(19.73814, 96.21157)` represent the approximate administrative centroid of Pyinmana Township ($R_{rup} = 4.218\text{ km}$ from centroid), NOT the damage site. Ingesting township centroids into ShakeMap as site-specific observations violates spatial QC standards. Excluded from site-specific ShakeMap export until specific building coordinates are recovered.

#### F. Editable Expert-Review Record
```text
Reviewer Decision: [ ] APPROVE   [ ] REVISE   [ ] REJECT   [ ] DEFER
Approved Shaking MMI: [      ]
Eligible for ShakeMap Shaking Export: [ ] YES   [ ] NO
Assigned Observation Uncertainty (sigma): [      ]
Reviewer Identity: _________________________________________
Date of Review: ________________________
Scientific Rationale & Review Notes:
_______________________________________________________________________________
```

---

### Candidate P-04: Satetaya Village Structural & Geotechnical Failure (Mandalay)

#### A. Original StEER Virtual Assessment Evidence & Metadata
- **Source Document:** StEER Virtual Assessment Structural Team (VAST) Report Page 34
- **Local File Path:** [`2026_Macroseismic_AI_Myanmar/pages/page-34.pdf`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/2026_Macroseismic_AI_Myanmar/pages/page-34.pdf)
- **VAST Author:** Yeshey Lotay
- **StEER Geolocation Entry:** `Satetaya Village in Plague city, Mandalay, 21.890191, 96.089906`
- **Original Source Attribution:** World Forum & DVB TV News Facebook; location shared by phoophoo TikTok (`@phoophoo891997`)
- **StEER Short Description (Verbatim):**
  > *"Houses were damaged and submerged due to surface rupture. It is mentioned that 30 villages were submerged as it is near to the epicenter. It seems there was land subsidence, and DVB TV news mentioned there were landslides in this area."*

#### B. Primary Photographic Evidence
| Submerged Tilted Dwellings | Embankment Landslide Scarp | Flooded Settlement Roadway |
| :---: | :---: | :---: |
| ![P-04 Submerged Homes](evidence_images/page_034_img_3_Im2.jpg) | ![P-04 Landslide Scarp](evidence_images/page_034_img_4_Im3.jpg) | ![P-04 Fissures Roadway](evidence_images/page_034_img_5_Im4.jpg) |
| *Figure P-04.1: Timber homes tilted into flooded, subsided ground.* | *Figure P-04.2: Large ground subsidence scarp along embankment.* | *Figure P-04.3: Ground fissures and submerged alluvial plain.* |

#### C. Categorized Evidence Claims
- **DIRECTLY OBSERVED:** Wooden and masonry houses tilted and partially submerged in standing water; large arcuate ground scarps and ground fissures along river embankment; waterlogged alluvial terrain.
- **REPORTED:** Author Yeshey Lotay reports 30 villages were submerged, citing land subsidence and DVB TV news reports of landslides.
- **INFERRED:** Structural tilting and collapse were caused or heavily exacerbated by geotechnical ground failure (lateral spreading, slope slumping, liquefaction) along the alluvial floodplain. Shaking intensity cannot be separated from ground failure.

#### D. Prior Model-Generated Assessment (`agent_evaluations_myanmar.json`)
- **Assigned MMI:** **9.5** (Preserved model estimate) | **Confidence:** 0.85
- **Model Typology:** Low-rise residential; unreinforced masonry and timber structures.
- **Model Reasoning:** Assigned MMI 9.5 based on foundation shifting and ground subsidence.

#### E. Provisional Screening Recommendation
- **Recommendation:** **`PROVISIONAL_DEFER_GEOTECHNICAL_FAILURE`**.
- **Rationale:** Macroseismic scales require that shaking intensity be derived from inertial vibratory response, not soil liquefaction or slope failure. Assigned MMI 9.5 at $R_{rup} = 10.841\text{ km}$ would distort ShakeMap's regional Kriging field. Shaking intensity is **`NOT_ESTIMABLE`** / **`DEFERRED`**. Do NOT invent an arbitrary lower intensity (e.g. 7.5); catalog as a secondary geotechnical liquefaction/landslide feature. Excluded from shaking export.

#### F. Editable Expert-Review Record
```text
Reviewer Decision: [ ] APPROVE   [ ] REVISE   [ ] REJECT   [ ] DEFER
Approved Shaking MMI: [      ]
Eligible for ShakeMap Shaking Export: [ ] YES   [ ] NO
Assigned Observation Uncertainty (sigma): [      ]
Reviewer Identity: _________________________________________
Date of Review: ________________________
Scientific Rationale & Review Notes:
_______________________________________________________________________________
```

---

### Candidate P-05: Sagaing City Surface Rupture & Urban Structural Devastation

#### A. Original StEER Virtual Assessment Evidence & Metadata
- **Source Document:** StEER Virtual Assessment Structural Team (VAST) Report Page 26
- **Local File Path:** [`2026_Macroseismic_AI_Myanmar/pages/page-26.pdf`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/2026_Macroseismic_AI_Myanmar/pages/page-26.pdf)
- **VAST Authors:** Heidi Stenner and Janise Rodgers
- **StEER Geolocation Entry:** `Sagaing city, 21°52'49.27"N, 95°59'5.57"E`
- **Original Source Attribution:** Heung Min Son (`@heungburma`, Twitter/X)
- **StEER Short Description (Verbatim):**
  > *"Screenshots from video showing severely damaged and collapsed buildings affected by / adjacent to apparent surface fault rupture in Sagaing town. Note right lateral offset of central red and white curb. See next slide for location info. As this offset is not large ( ~1m?), this site may be on a small strand in the overall fault zone."*

#### B. Primary Photographic Evidence
| Road Median Lateral Shearing | Roadside Multi-Story Building Collapse |
| :---: | :---: |
| ![P-05 Fault Offset Median](evidence_images/page_026_img_3_Im2.jpg) | ![P-05 Urban Building Collapse](evidence_images/page_026_img_4_Im3.jpg) |
| *Figure P-05.1: ~1 m right-lateral strike-slip offset of red-and-white road median.* | *Figure P-05.2: Multi-story commercial building collapsed into roadway debris.* |

#### C. Categorized Evidence Claims
- **DIRECTLY OBSERVED:** Offset of painted road curb/median by ~1 m horizontally; complete collapse of adjacent multi-story concrete/masonry commercial buildings into heaps of rubble extending into the street.
- **REPORTED:** Authors Heidi Stenner and Janise Rodgers report collapsed buildings adjacent to apparent surface fault rupture in Sagaing town, noting right-lateral offset of central curb (~1 m).
- **INFERRED:** Co-occurrence of surface fault rupture ($R_{rup} = 0.017\text{ km}$) and severe structural collapse. While structural collapse demonstrates violent motion, fault displacement across foundations may have contributed to structural failure.

#### D. Prior Model-Generated Assessment (`agent_evaluations_myanmar.json`)
- **Assigned MMI:** **9.5** (Preserved model estimate) | **Confidence:** 0.95
- **Model Typology:** Multi-story commercial and mixed-use urban buildings.
- **Model Reasoning:** Observed damage aligns with MMI IX (Violent) and MMI X criteria.

#### E. Provisional Screening Recommendation
- **Recommendation:** **`PROVISIONAL_RANGE_8.5_9.5_PENDING_EXPERT`**.
- **Rationale:** Unlike P-01 (where structures remained intact), P-05 exhibits catastrophic structural collapse directly adjacent to the fault. Candidate range for expert consideration is [8.5–9.5]. Retain model estimate 9.5 pending expert evaluation of the contribution of ground shearing to collapse.

#### F. Editable Expert-Review Record
```text
Reviewer Decision: [ ] APPROVE   [ ] REVISE   [ ] REJECT   [ ] DEFER
Approved Shaking MMI: [      ]
Eligible for ShakeMap Shaking Export: [ ] YES   [ ] NO
Assigned Observation Uncertainty (sigma): [      ]
Reviewer Identity: _________________________________________
Date of Review: ________________________
Scientific Rationale & Review Notes:
_______________________________________________________________________________
```

---

## 6. Review Execution & Next Steps

Reviewers can record decisions in the review blocks above or directly in [`data/events/us7000pn9s/pilot_candidates/pilot_expert_review_manifest.json`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/data/events/us7000pn9s/pilot_candidates/pilot_expert_review_manifest.json).

Once decisions are approved by a human expert:
1. Export the approved observations using the strict verification flag:
   ```bash
   PYTHONPATH="src:server:.clean_venv/lib/python3.13/site-packages" /opt/anaconda3/bin/python \
     -m mmigram.seismology.shakemap_exporter \
     --input data/events/us7000pn9s/pilot_candidates/pilot_expert_review_manifest.json \
     --output-dir /Users/jasondeng/shakemap_profiles/myanmar_recon/data/us7000pn9s_augmented/current/ \
     --event-id us7000pn9s \
     --require-expert-approval \
     --uncertainty-strategy experimental_fixed_prior \
     --default-stddev 0.50
   ```
2. Execute the augmented ShakeMap run:
   ```bash
   conda activate shakemap45
   shake --profile myanmar_recon us7000pn9s_augmented assemble model gridxml
   ```
3. Run the differential grid comparator (`ShakeMapGridComparator`) to calculate $\Delta\text{MMI}$, spatial impact extent ($km^2$), and correlation with distance to fault.
