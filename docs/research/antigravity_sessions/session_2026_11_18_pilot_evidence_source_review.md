# Antigravity Research Session: Pilot Candidate Source-Grounded Evidence Review & StEER Audit
**Date:** November 18, 2026  
**Repository:** `MMI-Gram-Clean` (Destination: `MMI-Gram`, `jdeng711/MMI-Gram`)  
**Active Branch:** `feature/quake-agent-integration`  
**Status:** Completed Investigation & Visual Review Package Generated (Pending User & Expert Review; Uncommitted per User Instruction)

---

## 1. User Prompt (Verbatim)

```text
Thank you for successfully committing and publishing the integration branch.

Before the augmented Myanmar ShakeMap experiment, let's conduct a source-grounded review of the five pilot candidates.

Continue on `feature/quake-agent-integration`.

1. Locate the actual original StEER PDFs for P-01 through P-05, especially `page-076.pdf` (Pyawbwe KBZ Bank).

2. Create a locally accessible visual evidence-review document containing the original relevant photographs, captions, and supporting text for each candidate. Clearly distinguish actual source evidence from Clara's prior model-generated descriptions.

3. Evaluate whether each candidate's assigned MMI is supported by shaking-related observations according to the documented Modified Mercalli scale. Do not treat building collapse alone as definitive proof of MMI IX, and account for structural vulnerability, permanent fault displacement, and geotechnical failure.

4. Verify that the selected coordinates correspond to the actual observed damage sites, not map centers, epicenters, or nearby named places.

5. Highlight potential overlap with official DYFI and ShakeMap observations.

6. For each candidate, prepare an editable expert-review record with APPROVE, REVISE, REJECT, or DEFER, plus rationale and reviewer identity.

7. Keep every candidate marked PENDING_EXPERT_REVIEW until an actual reviewer makes a decision. Do not generate or infer approvals.

8. Update the research archive and run the complete offline test suite.

Report which candidates have sufficient source evidence for review and which require clarification.

Do not make paid API calls, execute the augmented Myanmar ShakeMap, or automatically process the entire Myanmar dataset.

Do not commit or push further changes until I review the evidence package.
```

---

## 2. Source-Grounded Evidence Investigation & Findings

### 2.1 Original StEER PDF Location & Identification
The original StEER (Structural Extreme Events Reconnaissance) Virtual Assessment Structural Team (VAST) individual page reports and master document were successfully located on disk:
- **Master Repository PDF:** `/Users/jasondeng/Downloads/Files/Harvard/F26/EPS 55/Final Project/2026_Macroseismic_AI_Myanmar/Myanmar 2025 EQ Media Repository.pdf` (61.8 MB)
- **Individual Page Reports:** `/Users/jasondeng/Downloads/Files/Harvard/F26/EPS 55/Final Project/2026_Macroseismic_AI_Myanmar/pages/`
  - `page-22.pdf` (P-01): Thazi solar farm (Carlos Arteta)
  - `page-76.pdf` (P-02): Pyawbwe KBZ Bank branch (Yeshey Lotay via Lalrinpuii Tlau)
  - `page-47.pdf` (P-03): Pyinmana Township residential collapse (Hnin Wai Lwin)
  - `page-34.pdf` (P-04): Satetaya Village, Mandalay (Yeshey Lotay)
  - `page-26.pdf` (P-05): Sagaing city surface rupture (Heidi Stenner and Janise Rodgers)

### 2.2 Image Extraction & Formatting
All embedded JPEG 2000 (`.jp2`) damage photographs from the original StEER PDF pages were extracted using `pypdf` and converted via Pillow into high-resolution standard JPEG files under:
`docs/research/evidence_images/`
These images have been embedded directly into `docs/research/pilot_evidence_review_package.md`.

### 2.3 Detailed Seismological & Forensic Findings per Candidate

1. **Candidate P-01 (`page-022.pdf` / `page-22.pdf`): Thazi Solar Farm**
   - **Original Text:** Carlos Arteta citing CCTV video by Singaporean engineer Htin Aung showing initial shaking followed by surface fault rupture cutting across the entrance and fence line.
   - **Physical Mechanism:** **FAULT-DISPLACEMENT DOMINATED**. Primary tectonic strike-slip shearing of ~1.5 m across fence and gate.
   - **MMI Validity:** Conflates surface fault offset with inertial ground motion. Under Wood & Neumann (1931), structures did not collapse from vibration. MMI 9.5 is unjustified for pure shaking; recommend **REVISE to MMI VII–VIII** or treating strictly as a surface geology offset marker.
   - **Coordinates:** `20.882056° N, 96.035278° E` ($R_{rup} = 0.359\text{ km}$). Site-specific entrance verified.
   - **DYFI Overlap:** Nearest DYFI report is $1.74\text{ km}$ away.

2. **Candidate P-02 (`page-076.pdf` / `page-76.pdf`): Pyawbwe KBZ Bank Branch**
   - **Original Text:** Yeshey Lotay documenting collapse of 5-story reinforced concrete KBZ Bank branch in Pyawbwe due to soft-story failure.
   - **Visual Evidence:** 3 photographs showing pancake collapse of ground/second banking levels and column plastic hinge shear failures, with upper levels tilted backward.
   - **Physical Mechanism:** **PURE INERTIAL SHAKING STRUCTURAL RESPONSE**. Zero surface fault rupture.
   - **MMI Validity:** Engineered RC frame (EMS-98 Class C) suffered classic soft-story collapse under extreme shaking. Strongly supports **MMI 8.5 to 9.0**.
   - **Coordinates:** `(20.589678, 96.052420)` ($R_{rup} = 1.268\text{ km}$). Exact bank footprint on Pyawbwe main commercial road.
   - **DYFI Overlap (CRITICAL FINDING):** Nearest USGS DYFI observation is **31.09 km away** (`UTM:(47Q 0192 2310 1000)`). This site fills a **major 31-km data gap** in the official USGS ShakeMap baseline.
   - **Review Readiness:** **HIGHEST SUITABILITY FOR SHAKEMAP ASSIMILATION**.

3. **Candidate P-03 (`page-047.pdf` / `page-47.pdf`): Pyinmana Township Residential Collapse**
   - **Original Text:** Hnin Wai Lwin documenting collapse of single-family brick-nogging homes.
   - **CRITICAL DISCOVERY:** StEER author explicitly wrote in the source text: **`"(Only mentioned township coordinate, not accurate location)"`**!
   - **Coordinate Provenance Issue:** In `agent_evaluations_myanmar.json`, this record was incorrectly tagged with `location_precision = "exact"`. The source proves the coordinates `(19.73814, 96.21157)` are an approximate township centroid. Under MMI-Gram Stage 3 rules, approximate centroids must not be exported to ShakeMap.
   - **Structural Vulnerability:** Traditional brick-nogging (timber framing with unreinforced brick infill) is EMS-98 Vulnerability Class A/B. Complete wall blowout can occur at MMI VII–VIII; does not prove MMI 8.5.
   - **Review Readiness:** **REQUIRES CLARIFICATION / DEFER**. Disqualified from site-specific ShakeMap export until precise building coordinates are resolved.

4. **Candidate P-04 (`page-034.pdf` / `page-34.pdf`): Satetaya Village (Mandalay)**
   - **Original Text:** Yeshey Lotay documenting that houses were damaged and submerged, with significant land subsidence and landslides along river courses.
   - **Physical Mechanism:** **MIXED SHAKING & GEOTECHNICAL GROUND FAILURE**. Riverbank embankment subsidence and slope failure caused dwellings to tilt into water and fissures.
   - **Distance Attenuation Inconsistency:** Located at $R_{rup} = 10.841\text{ km}$, where median expected active-crustal GMPE shaking is MMI ~7.5–8.2. An MMI of 9.5 at ~11 km is an extreme outlier driven by soil failure. Ingesting MMI 9.5 would distort regional ShakeMap Kriging over southern Mandalay.
   - **Review Readiness:** **REQUIRES SCRUTINY / REVISE**. Recommend revising down to **MMI 7.5–8.0** or increasing observation uncertainty to $\sigma = 0.70$.

5. **Candidate P-05 (`page-026.pdf` / `page-26.pdf`): Sagaing City Urban Devastation**
   - **Original Text:** Heidi Stenner and Janise Rodgers documenting ~1 m right-lateral offset of central red-and-white curb with severely damaged and collapsed roadside buildings.
   - **Visual Evidence:** 2 video frames showing median shearing across street and total collapse of adjacent multi-story commercial structures into rubble.
   - **Physical Mechanism:** **COEXISTING PRIMARY FAULT RUPTURE & CATASTROPHIC BUILDING COLLAPSE**.
   - **MMI Validity:** Substantial multi-story building collapse independently supports MMI IX (9.0). Reviewers must determine whether ground motion was MMI 9.0 or 9.5 after accounting for foundation shearing across fault strand.
   - **Coordinates:** `21.880353° N, 95.984881° E` ($R_{rup} = 0.017\text{ km}$). Exact street alignment on active fault trace.
   - **DYFI Overlap:** Located within dense urban DYFI cluster (24 reports, $0.09\text{ km}$ to nearest cell).
   - **Review Readiness:** **SUFFICIENT SOURCE EVIDENCE**. Highly valuable near-fault observation.

---

## 3. Test Suite Execution

- **Command:** `PYTHONPATH="src:server:.clean_venv/lib/python3.13/site-packages" /opt/anaconda3/bin/pytest tests`
- **Result:** **207 passed, 1 skipped** (100% offline, zero paid API calls, $0.00 spent).
- **Working Tree State:** All modifications preserved in working tree. Zero commits or pushes performed, strictly adhering to user instructions.
