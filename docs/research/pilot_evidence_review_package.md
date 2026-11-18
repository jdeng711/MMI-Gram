# MMI-Gram Myanmar Mw 7.7 Pilot Evidence-Review Package
**USGS ShakeMap 4.5 Augmented Ingestion Pilot (Event `us7000pn9s`)**  
*Harvard University EPS 55 Final Project & USGS Collaboration (Clara Yoon, Jason Deng)*  
*Document Version: 1.0.0 | Date: November 18, 2026 | Status: PENDING EXPERT REVIEW*

---

## 1. Executive Summary & Review Objectives

This document provides the official expert review package for the **5-observation pilot subset** selected from the 184 candidate evaluations of the March 28, 2025 Mw 7.7 Mandalay, Myanmar earthquake (`us7000pn9s`).

### Background & Scientific Safeguard Gate
In Stage 4B Part 1, the official USGS ShakeMap 4.5.0 system was successfully installed and validated, demonstrating that ShakeMap can parse, ingest, and assimilate MMI-Gram `*_dat.json` observation files. In Stage 4B Part 2A, the local baseline ShakeMap for the Myanmar Mw 7.7 event was reconstructed using official USGS inputs (`rupture.json`, `stationlist.json`, `active_crustal_nshmp2014` GMPE, `WGRW12` GMICE, and empirical regional site conditions $V_{s30} = 290\text{ m/s}$).

Before performing the augmented ShakeMap experiment (Stage 4B Part 2B), **strict scientific validation is mandatory**:
1. **Zero Automated Scientific Approval:** Although 157 of the 184 records in `agent_evaluations_myanmar.json` meet basic syntactic and bounding criteria for technical export, **NONE has received seismological human expert review**. All 184 records remain strictly **`PENDING_EXPERT_REVIEW`**.
2. **Separation of Technical Compatibility vs. Scientific Validation:** Generating a GeoJSON file demonstrates technical parser compatibility; it does NOT constitute seismological validation. Only human expert-approved records may be assimilated into a scientific ShakeMap run.
3. **Pilot Objective:** Rather than blindly injecting all unreviewed observations, this 5-observation pilot is submitted to expert seismologists (Clara Yoon, USGS) for rigorous verification of shaking intensity, coordinate precision, and differentiation between surface fault offset and inertial shaking.

---

## 2. Seismological Review Guidelines

Reviewers are requested to evaluate each observation against the following key criteria:

1. **Inertial Shaking vs. Primary Fault Rupture Displacement:**
   - *Physical Principle:* Permanent tectonic offset (fault displacement) does NOT equal ground shaking intensity. Near-fault surface rupture alone does not justify MMI IX–X without clear structural shaking damage.
   - *Review Action:* If the damage is dominated purely by fault displacement cutting across a structure without severe inertial shaking damage, consider adjusting the MMI rating or noting the geological offset separately.
2. **Inertial Shaking vs. Geotechnical Ground Failure:**
   - *Physical Principle:* Localized slope failure, liquefaction, or foundation subsidence can cause collapse even at moderate shaking levels.
   - *Review Action:* Distinguish between structural shaking response and foundation failure induced by slope instability.
3. **Coordinate Accuracy & Spatial Redundancy:**
   - Check whether coordinates pinpoint the actual structure or an approximate area.
   - Evaluate whether the observation is co-located with an existing USGS Did You Feel It? (DYFI) 1-km geocoded cell, and whether it provides new spatial resolution or confirms DYFI reports.
4. **Observation Uncertainty Assignment:**
   - The default working prior for single AI-derived reconnaissance observations is $\sigma = 0.50$ (NEHRP Class D regional prior). If the evidence is exceptionally sharp or ambiguous, reviewers may specify an expert uncertainty $\sigma \in [0.30, 0.70]$.

---

## 3. Pilot Observation Overview Table

| Pilot ID | Source File | Estimated MMI | Confidence | Lat (°N) | Lon (°E) | $R_{rup}$ (km) | Nearest DYFI (km) | Rupture Segment & Primary Phenomenon |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **P-01** | `page-022.pdf` | **9.5** | 0.90 | 20.88206 | 96.03528 | 0.36 | 1.74 | Central fault trace; dynamic CCTV of surface fault displacement at Thazi solar farm. |
| **P-02** | `page-076.pdf` | **9.0** | 0.90 | 20.58968 | 96.05242 | 1.27 | 31.09 | South-central segment; pancake collapse of engineered RC bank building in Pyawbwe (DYFI gap). |
| **P-03** | `page-047.pdf` | **8.5** | 0.85 | 19.73814 | 96.21157 | 4.22 | 0.48 | Southern segment; near-total collapse of masonry-infill residential homes in Pyinmana / Naypyidaw. |
| **P-04** | `page-034.pdf` | **9.5** | 0.85 | 21.89019 | 96.08991 | 10.84 | 0.21 | Northern segment; severe masonry destruction coupled with localized slope subsidence in Mandalay. |
| **P-05** | `page-026.pdf` | **9.5** | 0.95 | 21.88035 | 95.98488 | 0.02 | 0.09 | Epicentral/Sagaing city; 1-m lateral fault offset across street with adjacent building collapses. |

---

## 4. Detailed Evidence Review Cards

---

### Candidate P-01: Thazi Solar Farm Perimeter Offset
- **Pilot ID:** `P-01`
- **File Name:** `page-022.pdf`
- **Content UUID:** `d6a18bd5-7223-43ef-8902-7222ebaf9604`
- **Model Assessor:** `gemini-3.8-flash`
- **Assigned MMI:** **9.5** (Violent to Disastrous) | **Model Confidence:** 0.90
- **Location Name:** GP Energy Myanmar Thapyawa Solar Farm, Thazi, Myanmar
- **Geographic Coordinates:** Latitude `20.882056° N`, Longitude `96.035278° E`
- **Coordinate Precision:** `site_specific_address` (exact compound perimeter)
- **Finite-Fault Distance ($R_{rup}$):** **0.359 km** (Rupture centroid depth: 5.0 km)
- **Nearest Assimilated USGS DYFI Station:**
  - Station Code: `UTM:(47Q 0192 2310 1000)`
  - Distance: **1.74 km**
  - Existing DYFI Representation: Distinct site; provides high-resolution near-fault ground truth.

#### Building & Infrastructure Typology
- **Facility Type:** Industrial renewable energy compound entrance and perimeter infrastructure.
- **Structural Materials:** Heavy gauge steel wire fencing, structural steel gate posts, concrete footing curbs, compacted gravel roadway, nearby modular panel cabins.

#### Damage Description & Observed Phenomena
Security camera footage from GP Energy Myanmar's Thapyawa solar farm near Thazi, Myanmar, capturing the direct dynamic surface fault rupture along the central Sagaing fault zone. Large, abrupt horizontal strike-slip displacement and surface shearing cut directly across the compound entrance road and perimeter fence line, severely warping the fence and shearing gate posts.

#### Seismological & Physics Critic Evaluation
- **Physics Plausibility:** Consistent with regional attenuation ($R_{rup} = 0.36$ km).
- **Critical Review Question:** The observed damage is dominated by **primary tectonic surface fault displacement** (~1–2 m horizontal offset cutting across the fence) rather than pure inertial shaking damage to buildings. 
- *Seismological Note:* In strict macroseismic intensity scales (Wood & Neumann 1931; ESI-07), fault displacement is a primary environmental effect, whereas MMI evaluates ground shaking effects on structures. Reviewers should consider whether MMI 9.5 accurately represents the ground motion intensity or whether the rating should be adjusted (e.g. MMI VIII–IX) with fault displacement documented separately.

#### Expert Decision & Review Block
```text
Reviewer Decision: [ ] APPROVE   [ ] REVISE   [ ] REJECT   [ ] DEFER
Approved MMI: [      ] (if REVISE, specify adjusted intensity, e.g., 8.5 or 9.0)
Observation Uncertainty (sigma): [ 0.50 ] (default working prior)
Reviewer Name: _________________________________________
Date: ________________________
Seismological Review Notes:
_______________________________________________________________________________
_______________________________________________________________________________
```

---

### Candidate P-02: KBZ Bank Branch Soft-Story Pancake Collapse (Pyawbwe)
- **Pilot ID:** `P-02`
- **File Name:** `page-076.pdf`
- **Content UUID:** `b0eaab44-9e9b-40bc-94de-fe2d211e8fec`
- **Model Assessor:** `gemini-3.8-flash`
- **Assigned MMI:** **9.0** (Violent) | **Model Confidence:** 0.90
- **Location Name:** KBZ Bank branch, Pyawbwe Township, Mandalay Division
- **Geographic Coordinates:** Latitude `20.589678° N`, Longitude `96.052420° E`
- **Coordinate Precision:** `site_specific_address` (exact building footprint)
- **Finite-Fault Distance ($R_{rup}$):** **1.268 km**
- **Nearest Assimilated USGS DYFI Station:**
  - Station Code: `UTM:(47Q 0192 2310 1000)`
  - Distance: **31.09 km**
  - Existing DYFI Representation: **NONE (Critical DYFI Data Gap)**. This observation fills a major 31-km data void along the south-central fault rupture.

#### Building & Infrastructure Typology
- **Facility Type:** Multi-story commercial engineered building (commercial bank branch).
- **Structural Materials:** Cast-in-place reinforced concrete (RC) frame, steel deformed rebar reinforcement, clay brick masonry infill walls, glass storefront facade.

#### Damage Description & Observed Phenomena
Severe structural collapse of a multi-story reinforced concrete building. The ground and lower commercial banking levels suffered catastrophic pancake collapse / soft-story failure. The reinforced concrete columns at the ground level experienced shear/hinge failure, leaving the intact upper stories severely tilted and collapsed onto the lower footprint amid heavily fractured concrete and bent rebar cages.

#### Seismological & Physics Critic Evaluation
- **Physics Plausibility:** Highly consistent with near-field strong motion ($R_{rup} = 1.27$ km).
- **Critical Review Question:** This observation represents **pure inertial shaking structural response** in an engineered building, completely free of direct surface fault offset.
- *Seismological Note:* Under MMI standards, *"Damage great in substantial buildings, with partial or complete collapse; well-designed frame structures thrown out of plumb"* directly defines MMI IX. Given the pancake failure of an engineered RC frame and the 31 km gap to the nearest DYFI station, this observation carries exceptional scientific value for ShakeMap interpolation.

#### Expert Decision & Review Block
```text
Reviewer Decision: [ ] APPROVE   [ ] REVISE   [ ] REJECT   [ ] DEFER
Approved MMI: [      ] (if REVISE, specify adjusted intensity)
Observation Uncertainty (sigma): [ 0.50 ]
Reviewer Name: _________________________________________
Date: ________________________
Seismological Review Notes:
_______________________________________________________________________________
_______________________________________________________________________________
```

---

### Candidate P-03: Pyinmana Residential Masonry Collapse (Naypyidaw)
- **Pilot ID:** `P-03`
- **File Name:** `page-047.pdf`
- **Content UUID:** `e026cd5c-9022-4c0f-9475-625bb05cb56d`
- **Model Assessor:** `gemini-3.8-flash`
- **Assigned MMI:** **8.5** (Severe to Violent) | **Model Confidence:** 0.85
- **Location Name:** Pyinmana Township residential quarter, Naypyidaw Union Territory
- **Geographic Coordinates:** Latitude `19.738140° N`, Longitude `96.211570° E`
- **Coordinate Precision:** `site_specific_address`
- **Finite-Fault Distance ($R_{rup}$):** **4.218 km**
- **Nearest Assimilated USGS DYFI Station:**
  - Station Code: `UTM:(47Q 0207 2184 1000)`
  - Distance: **0.48 km**
  - Existing DYFI Representation: Co-located near DYFI geocoded cell.

#### Building & Infrastructure Typology
- **Facility Type:** Single-family residential dwellings.
- **Structural Materials:** Traditional brick-nogging (timber framing with unreinforced brick infill), unreinforced clay brick masonry perimeter walls, timber roof trusses with corrugated galvanized iron (CGI) sheets and clay tiles.

#### Damage Description & Observed Phenomena
Near-total collapse and heavy structural failure of single-family residences. Unreinforced masonry infill walls were violently thrown out of their frames, load-bearing brick walls collapsed into rubble heaps, and roof trusses collapsed downward onto the residential floors.

#### Seismological & Physics Critic Evaluation
- **Physics Plausibility:** Consistent with regional attenuation at 4.2 km.
- **Critical Review Question:** The structural vulnerability of traditional brick-nogging and unreinforced masonry (EMS-98 Vulnerability Class A/B) means complete collapse can occur at MMI VIII–IX.
- *Seismological Note:* Reviewers should evaluate whether the 8.5 rating is appropriate for Class A/B residential structures, or whether the high damage was driven primarily by building fragility rather than ground motion exceeding MMI VIII.

#### Expert Decision & Review Block
```text
Reviewer Decision: [ ] APPROVE   [ ] REVISE   [ ] REJECT   [ ] DEFER
Approved MMI: [      ] (if REVISE, specify adjusted intensity)
Observation Uncertainty (sigma): [ 0.50 ]
Reviewer Name: _________________________________________
Date: ________________________
Seismological Review Notes:
_______________________________________________________________________________
_______________________________________________________________________________
```

---

### Candidate P-04: Satetaya Village Structural & Geotechnical Failure (Mandalay)
- **Pilot ID:** `P-04`
- **File Name:** `page-034.pdf`
- **Content UUID:** `4a24c5ae-6a58-421c-9bca-9a6a4749da4a`
- **Model Assessor:** `gemini-3.8-flash`
- **Assigned MMI:** **9.5** (Violent to Disastrous) | **Model Confidence:** 0.85
- **Location Name:** Satetaya Village, Mandalay perimeter
- **Geographic Coordinates:** Latitude `21.890191° N`, Longitude `96.089906° E`
- **Coordinate Precision:** `site_specific_address`
- **Finite-Fault Distance ($R_{rup}$):** **10.841 km**
- **Nearest Assimilated USGS DYFI Station:**
  - Station Code: `UTM:(47Q 0199 2423 1000)`
  - Distance: **0.21 km**
  - Existing DYFI Representation: Near DYFI cell in southern Mandalay urban fringe.

#### Building & Infrastructure Typology
- **Facility Type:** Low-rise mixed residential dwellings and rural structures.
- **Structural Materials:** Unreinforced brick masonry, timber posts, bamboo and thatch partitions, corrugated metal roofing on alluvial soil/riverbank embankment.

#### Damage Description & Observed Phenomena
Severe structural destruction coupled with geotechnical slope failure and foundation ground deformation. The documentation depicts total collapse of masonry homes, heavily tilted timber-framed buildings, and profound ground subsidence scarps where buildings slipped into slumping ground depressions.

#### Seismological & Physics Critic Evaluation
- **Physics Plausibility:** At $R_{rup} = 10.8$ km, an MMI of 9.5 is near the upper bound of active crustal GMPE/IPE predictions (mean expected MMI ~7.5–8.2).
- **Critical Review Question:** The assigned MMI 9.5 appears to be influenced by **localized geotechnical failure (slope slumping / riverbank subsidence)**.
- *Seismological Note:* When foundations fail due to slope movement, building damage is secondary to geotechnical displacement. If pure ground motion was MMI VIII, assigning MMI 9.5 to ShakeMap might artificially bias the regional Kriging field upwards at 10.8 km distance. Reviewers should determine whether to revise MMI down (e.g. 8.0–8.5) or assign higher observation variance ($\sigma = 0.65$).

#### Expert Decision & Review Block
```text
Reviewer Decision: [ ] APPROVE   [ ] REVISE   [ ] REJECT   [ ] DEFER
Approved MMI: [      ] (if REVISE, specify adjusted intensity, e.g., 8.0 or 8.5)
Observation Uncertainty (sigma): [ 0.50 ] (or suggest elevated sigma, e.g., 0.65)
Reviewer Name: _________________________________________
Date: ________________________
Seismological Review Notes:
_______________________________________________________________________________
_______________________________________________________________________________
```

---

### Candidate P-05: Sagaing City Surface Rupture & Urban Structural Devastation
- **Pilot ID:** `P-05`
- **File Name:** `page-026.pdf`
- **Content UUID:** `c78e534e-7b81-48e3-98fa-67d3d426f2f7`
- **Model Assessor:** `gemini-3.8-flash`
- **Assigned MMI:** **9.5** (Violent to Disastrous) | **Model Confidence:** 0.95
- **Location Name:** Sagaing city central urban thoroughfare
- **Geographic Coordinates:** Latitude `21.880353° N`, Longitude `95.984881° E`
- **Coordinate Precision:** `site_specific_address` (exact street offset)
- **Finite-Fault Distance ($R_{rup}$):** **0.017 km** (Directly on surface trace)
- **Nearest Assimilated USGS DYFI Station:**
  - Station Code: `UTM:(46Q 0808 2422 1000)`
  - Distance: **0.09 km**
  - Existing DYFI Representation: Within high-density urban DYFI cluster (24 reports).

#### Building & Infrastructure Typology
- **Facility Type:** Multi-story commercial street corridor and mixed-use urban buildings.
- **Structural Materials:** Reinforced concrete frame with masonry infill, unreinforced brick masonry, asphalt street pavement, concrete road medians, steel utility poles.

#### Damage Description & Observed Phenomena
Post-earthquake reconnaissance documentation showing clear tectonic surface fault rupture and massive urban destruction. An apparent right-lateral strike-slip offset of approximately 1 meter cuts directly across the urban street, evidenced by sharply sheared red-and-white road medians and buckled pavement. Along both sides of the street, multi-story masonry and reinforced concrete buildings suffered partial or complete collapse with heavy masonry debris blocking the thoroughfare.

#### Seismological & Physics Critic Evaluation
- **Physics Plausibility:** Located directly on the active rupture ($R_{rup} = 0.017$ km).
- **Critical Review Question:** Both **primary surface fault offset (~1 m lateral)** AND **severe inertial structural collapse of multiple buildings** are simultaneously present in this view.
- *Seismological Note:* In contrast to P-01 (where only the fence was displaced), P-05 shows genuine catastrophic structural collapse of substantial buildings along the street corridor, which independently fulfills MMI IX criteria. Because both phenomena coexist, reviewers must decide whether MMI 9.5 is justified by the structural collapse alone, or whether MMI 9.0 is more representative of shaking ground motion.

#### Expert Decision & Review Block
```text
Reviewer Decision: [ ] APPROVE   [ ] REVISE   [ ] REJECT   [ ] DEFER
Approved MMI: [      ] (if REVISE, specify adjusted intensity)
Observation Uncertainty (sigma): [ 0.50 ]
Reviewer Name: _________________________________________
Date: ________________________
Seismological Review Notes:
_______________________________________________________________________________
_______________________________________________________________________________
```

---

## 5. Review Execution & Assimilation Protocol

Once Clara Yoon / USGS experts complete the review decisions:
1. Update `pilot_expert_review_manifest.json` with the approved MMI values and review status (`APPROVED`, `REVISED`, or `REJECTED`).
2. Export the approved observations using the strict verification flag:
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
3. Execute the augmented ShakeMap run:
   ```bash
   conda activate shakemap45
   shake --profile myanmar_recon us7000pn9s_augmented assemble model gridxml
   ```
4. Run the differential grid comparator (`ShakeMapGridComparator`) to calculate $\Delta\text{MMI}$, spatial impact extent ($km^2$), and correlation with distance to fault.
