# 📜 Antigravity Research Session: Stage 4B Part 2A - Myanmar Baseline Reconstruction and Experimental Preparation

**Date:** 2026-11-18  
**Researcher:** Jason Deng (Harvard University, EPS 55) in collaboration with Clara Yoon (USGS)  
**Assistant:** Antigravity (Google DeepMind Agentic AI Assistant)  
**Branch:** `feature/quake-agent-integration`  
**Base Commit (Stage 4B Part 1):** `a743530` (`feat: validate ShakeMap 4.5 ingestion and grid comparison`)  
**Status:** Completed & Verified (Ready for Review prior to Stage 4B Part 2B Pilot Augmentation)  
**API Cost / Budget:** $0.00 (Zero paid API calls; all tests offline and mocked)  

---

## 1. Executive Summary

In Stage 4B Part 2A, we successfully:
1. **Committed and preserved Stage 4B Part 1** as commit `a743530` on `feature/quake-agent-integration`, cleanly excluding binary HDF5 products, large grids, and Conda environments via `.gitignore`, while making the synthetic smoke test 100% reproducible on-the-fly.
2. **Audited the Myanmar M7.7 (`us7000pn9s`) baseline dataset**, computing exact SHA256 checksums, timestamps, and source provenance for the official finite-fault rupture (Reitman et al. 2025), station observations (1,250 station features), and attenuation curves.
3. **Established a reproducible local Myanmar baseline** in an isolated ShakeMap profile (`myanmar_recon`) using official event inputs, `active_crustal_nshmp2014` GMPE, `WGRW12` GMICE, and realistic empirical regional site conditions ($V_{s30} = 290.0\text{ m/s}$ based on the 130 near-fault alluvial basin stations) rather than carrying over the synthetic smoke test's 760 m/s rock assumption. The reconstructed baseline grid spans 500,904 cells ($0.0146^\circ \times 0.0137^\circ \approx 1.5\text{ km}$ spacing) with MMI ranging from 3.91 to 10.00 (mean 5.43).
4. **Verified observation assimilation in ShakeMap's internal solver**, examining the internal SQLite database (`station` and `amp` tables in `shake_data.hdf`) and `StationList` columnar arrays, proving that the synthetic observation at `(-118.0000, 34.0000)` was assimilated with amplitude 9.5, retained its standard deviation (0.35), was assigned flag `'0'` (not an outlier), and directly produced the observed $\Delta\text{MMI} = +0.1153$ shift. Enshrined this verification in regression test `test_12`.
5. **Prepared the Myanmar candidate inventory and 5-observation pilot review manifest**, auditing all 184 records from `agent_evaluations_myanmar.json`, identifying 35 spatial clusters, and curating a 5-observation pilot spanning northern, central, and southern segments of the 450-km Sagaing rupture. **All records are strictly marked `PENDING_EXPERT_REVIEW` (none currently approved).**
6. **Prepared the comparison experiment tooling**, generating the baseline intensity map, MMI vs. $R_{\text{rup}}$ scatterplot, CSV/JSON backing datasets, and confirmed that `ShakeMapGridComparator` is ready to evaluate $\Delta\text{MMI} = \text{MMI}_{\text{augmented}} - \text{MMI}_{\text{baseline}}$ on identical grids once the pilot is approved.
7. **Executed the complete offline test suite**, with **205 passed, 1 skipped** in 8.43 seconds.

---

## 2. Input Data Inventory & Checksums (`us7000pn9s`)

| File / Component | Path | Size | SHA256 Checksum | Source Provenance & Description |
| :--- | :--- | :--- | :--- | :--- |
| **Origin XML** | `data/synthetic_smoketest/baseline/event.xml` | 565 B | `121544f8...` | Official origin: M7.7, 2025-03-28T06:20:52Z, (22.011°N, 95.9363°E, 10 km). |
| **Finite Fault Rupture** | `data/events/us7000pn9s/usgs/rupture.json` | 1,681 B | `6e256168653aa263821e227d40e70ef00df73a8a26767c2e7f9c485d7ada6dcb` | Official USGS finite-fault MultiPolygon surface rupture (Reitman et al. 2025, DOI: 10.5066/P1RYMWCK). Length ~450 km. |
| **Station Observations** | `data/events/us7000pn9s/usgs/stationlist.json` | 3,499,574 B | `059dbd803fad41b086ea51f53b4865fd8e1d7ec0cf997067f816b31279f00b87` | Official USGS station list containing 1,250 station features (516 active macroseismic DYFI stations and 5 instrumental seismic stations). |
| **Attenuation Curves** | `data/events/us7000pn9s/usgs/attenuation_curves.json` | 60,500 B | `b4cce8b8402890cbbcd937bf6e3c5a6cfd49e90745bd4263a3cf9ff1577429da` | Published USGS attenuation curves for MMI, PGA, PGV, SA(0.3), SA(0.6), SA(1.0), SA(3.0) for rock and soil. |
| **Event Configuration** | `QuakeLLMmap-reference/.../event_config.json` | 1,052 B | `1c7068ffc4565a71cae20693e37e96b5820d603c41482c32f57c25c7b71e4b57` | Event boundaries: Lat [13.0, 27.0], Lon [91.0, 103.0], regional context, local building typologies. |
| **Raw Candidate Evals** | `tests/fixtures/usgs/agent_evaluations_myanmar.json` | 361,800 B | `f22e49308340eed6312dca0c25d7d750a28d40bfdb3cb347891dc414c73a4754` | 184 raw candidate evaluation records from Clara Yoon's earlier exploration. |

---

## 3. Reconstructed Local Myanmar Baseline

### 3.1 Profile & Configuration
- **Profile:** `myanmar_recon` in `/Users/jasondeng/shakemap_profiles/myanmar_recon/`
- **GMPE Set:** `active_crustal_nshmp2014` (ASK14, BSSA14, CB14, CY14 with equal weights 0.25)
- **IPE & GMICE:** `VirtualIPE` and `WGRW12` (Worden et al. 2012)
- **Cross-Correlation:** `LothBaker2013`
- **Site Conditions ($V_{s30}$):**
  - Analysis of the 1,250 stations in USGS `stationlist.json` revealed:
    - Global station mean $V_{s30} = 309.3\text{ m/s}$
    - 130 near-fault Myanmar central basin stations (Lat 18–24°N, Lon 95–97.5°E) mean $V_{s30} = 291.5\text{ m/s}$ (median $258.4\text{ m/s}$, minimum $191.7\text{ m/s}$).
  - We set `vs30default = 290.0 m/s` (alluvial valley sediments, NEHRP Class D) in `model.conf`.
  - Silently using 760 m/s (rock) would severely underestimate shaking amplification in the Ayeyarwady alluvial valley.

### 3.2 Baseline Modeling Execution & Output
Executed in ShakeMap 4.5.0:
```bash
shake -c "myanmar_baseline_reconstruction" us7000pn9s assemble
shake us7000pn9s model
shake us7000pn9s gridxml
```
- Runtime: Assemble 0.06s, Model 15.21s, GridXML 1.94s.
- Grid Points: 648 (lon) x 773 (lat) = **500,904 cells**
- Geographic Extent: Longitude [91.6500°E, 101.0963°E], Latitude [15.0121°N, 25.5833°N]
- Grid Spacing: $dx = 0.01460^\circ \approx 1.5\text{ km}$, $dy = 0.01369^\circ \approx 1.5\text{ km}$
- Modeled MMI:
  - Minimum: 3.91 (far-field background)
  - Maximum: 10.00 (near-fault on 450 km Sagaing rupture)
  - Mean: 5.43
- Generated Products:
  - `products/shake_result.hdf` (61 MB)
  - `products/grid.xml` (30 MB)
  - `products/uncertainty.xml` (30 MB)
  - Standalone map: `data/events/us7000pn9s/baseline_recon/myanmar_baseline_reconstruction.png` and `.pdf`
  - Metadata summary: `data/events/us7000pn9s/baseline_recon/myanmar_baseline_summary.json`

### 3.3 Relationship to Published USGS ShakeMap
- **Resemblance:** The reconstructed baseline closely resembles the published ShakeMap pattern: intense near-fault shaking reaching MMI IX–X along the 450-km fault, decaying eastward into Shan Plateau and westward into the Chin Hills, with 516 macroseismic and 5 seismic stations assimilated.
- **Discrepancies:**
  1. The published USGS ShakeMap utilized the internal USGS operational server configuration and a topography-based $V_{s30}$ grid (Wald & Allen 2007 30-arcsecond slope proxy).
  2. Our reconstructed baseline used an empirical uniform regional basin prior ($V_{s30} = 290.0\text{ m/s}$) to avoid downloading 10-GB global topography grids.
  3. Per protocol, this output is strictly labeled **Reconstructed Local Baseline (`us7000pn9s_baseline_recon`)**, not the published USGS map. No model parameters were artificially forced.

---

## 4. Observation Assimilation Verification (Synthetic Smoke Test)

We conducted a forensic inspection of ShakeMap's internal assembled and modeled data:
1. **SQLite Database Dump (`shake_data.hdf`):**
   - The station table contains `('MMI.agent_site_01', 'agent_site_01', ..., 34.0, -118.0, 'MMI')`.
   - The amplitude table contains `(1, 'MMI.agent_site_01', 1, 9.5, 0.35, '0')`.
   - The observation amplitude is exact (`9.5`), the standard deviation is strictly retained (`0.35`), and the flag is `'0'` (valid, unflagged).
2. **Station Predictions (`shake_result.hdf`):**
   - GMPE expectation at the observation site ($R_{\text{rup}} = 10.0\text{ km}$) was MMI 7.02 with $\sigma = 1.16$.
   - Because the observation had observed amplitude 9.5 with uncertainty 0.35, the Kriging weights updated the field positively.
3. **Grid Shift Attributability:**
   - Baseline MMI at observation: `7.3803`
   - Augmented MMI at observation: `7.4956`
   - Signed shift: **`+0.1153` intensity units**.
   - Because the baseline and augmented runs used identical `model.conf` and origin parameters, this shift is 100% attributable to the assimilated observation.
4. **Regression Enshrinement:**
   - Enshrined in `tests/test_shakemap_comparator.py::test_12_synthetic_smoke_observation_assimilation_verification`.

---

## 5. Candidate Myanmar Augmentation Inventory & Pilot Manifest

### 5.1 Full Candidate Inventory
- Total candidate records evaluated: **184**
- Coordinates: 100% contain decimal coordinates from earlier extraction.
- Spatial Clusters: Grouped into **35 distinct spatial clusters** (e.g., Mandalay urban center: 45 records; Sagaing town: 44 records; Pyinmana/Naypyidaw: 27 records).
- Proximity to USGS DYFI: Evaluated distance to all 1,244 DYFI observation centroids. Co-located observations (<1 km) flagged to avoid double-counting.
- **Human Review Status:** All 184 records are marked **`PENDING_EXPERT_REVIEW`**. None is currently approved.
- Staged in: `data/events/us7000pn9s/pilot_candidates/candidate_inventory_full.csv`.

### 5.2 Curated 5-Observation Pilot for Expert Review
We curated a pilot subset of 5 spatially dispersed observations spanning the 450-km Sagaing rupture:

| Pilot ID | Page | Location Name | Lat (°N) | Lon (°E) | $R_{\text{rup}}$ (km) | MMI | Conf | Nearest DYFI | Primary Structural Evidence & Review Note |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **P-01** | `page-022.pdf` | Thazi Solar Farm | 20.8821 | 96.0353 | 0.36 | 9.5 | 0.90 | 12.4 km | Central segment. Video/photo evidence of perimeter infrastructure collapse and severe ground shaking at Thapyawa solar facility. |
| **P-02** | `page-076.pdf` | Pyawbwe KBZ Bank | 20.5897 | 96.0524 | 1.27 | 9.0 | 0.90 | 8.1 km | Central-south segment. Pancake collapse of multi-story reinforced concrete commercial building; column shear failure. |
| **P-03** | `page-047.pdf` | Pyinmana Residential | 19.7381 | 96.2116 | 4.22 | 8.5 | 0.85 | 14.8 km | Southern segment. Residential masonry collapse in Pyinmana township; non-redundant with USGS DYFI. |
| **P-04** | `page-034.pdf` | Mandalay Satetaya | 21.8902 | 96.0899 | 10.84 | 9.5 | 0.85 | 4.9 km | Northern off-fault segment. Severe masonry collapse in peri-urban Mandalay village 10 km east of fault. |
| **P-05** | `page-026.pdf` | Sagaing City Rupture | 21.8804 | 95.9849 | 0.02 | 9.5 | 0.95 | 3.2 km | Northern on-fault segment. Surface fault offset (1.8 m) and adjacent masonry collapse. Flagged by Physics Critic for mixed evidence. |

*Review Manifest Staged at:*
- `data/events/us7000pn9s/pilot_candidates/pilot_expert_review_manifest.json`
- `data/events/us7000pn9s/pilot_candidates/pilot_expert_review_manifest.csv`
- MMI vs $R_{\text{rup}}$ diagnostic plot: `data/events/us7000pn9s/pilot_candidates/myanmar_pilot_mmi_vs_rrup.png` and `.pdf`.

---

## 6. Execution Protocol for Later Pilot Augmentation (Stage 4B Part 2B)

When approved by the researcher and Clara Yoon, the augmented pilot will be executed with the following reproducible steps:
1. Export the reviewed pilot observations into official ShakeMap format:
   ```bash
   python -m mmigram.seismology.shakemap_exporter --input-file data/events/us7000pn9s/pilot_candidates/pilot_approved.json --output-dir /Users/jasondeng/shakemap_profiles/myanmar_recon/data/us7000pn9s_augmented/current
   ```
2. Run augmented model in ShakeMap 4.5.0:
   ```bash
   shake -c "myanmar_augmented_pilot_run" us7000pn9s_augmented assemble model gridxml
   ```
3. Run `ShakeMapGridComparator` to compute exact signed grid difference ($\Delta\text{MMI} = \text{MMI}_{\text{augmented}} - \text{MMI}_{\text{baseline}}$):
   ```python
   from mmigram.seismology import ShakeMapGridComparator
   res = ShakeMapGridComparator.compare_files(baseline_hdf, augmented_hdf)
   res.save_csv("data/events/us7000pn9s/comparison/pilot_diff.csv")
   res.save_json("data/events/us7000pn9s/comparison/pilot_diff.json")
   res.save_plot("data/events/us7000pn9s/comparison/pilot_diff.png", stations=pilot_stations)
   ```

---

## 7. Test Results Summary

Ran full offline test suite across `tests/`:
```bash
PYTHONPATH="src:server:.clean_venv/lib/python3.13/site-packages" /opt/anaconda3/bin/pytest tests
```
- **205 passed, 1 skipped in 8.43 seconds.**
- **0 errors, 0 failures.**
- **$0.00 spent on external APIs.**
