# 🔬 Antigravity Research Session: Workflow B - Exploratory P-02 ShakeMap Sensitivity Experiment (Audited & Verified)

**Date:** November 18, 2026  
**Researcher:** Jason Deng (Harvard University)  
**Collaborator / Advisor:** Clara Yoon (USGS)  
**Agent Assistant:** Antigravity (Google DeepMind)  
**Active Branch:** `feature/quake-agent-integration`  
**Base Commit:** `c5c994a` (`docs: reconcile Myanmar ShakeMap observations and pilot evidence provenance`)  
**Status:** Completed, Audited & Verified (Awaiting User Review; No Git Commits or Push)

---

## 1. Executive Summary & Context

This research session executed and rigorously verified **Workflow B: Exploratory P-02 ShakeMap Sensitivity Experiment** for the Mw 7.7 Mandalay, Burma (Myanmar) earthquake (`us7000pn9s`, authoritative origin time `2025-03-28T06:20:52.715Z`).

The objective was to perform the first authentic baseline-versus-augmented ShakeMap sensitivity study for observation **P-02** (Pyawbwe KBZ Bank branch, `page-76.pdf`), testing three explicitly hypothetical input intensities:
1. **Scenario 1 (`us7000pn9s_p02_mmi80`):** Hypothetical MMI **8.0** ($\sigma = 0.50$)
2. **Scenario 2 (`us7000pn9s_p02_mmi85`):** Hypothetical MMI **8.5** ($\sigma = 0.50$)
3. **Scenario 3 (`us7000pn9s_p02_mmi90`):** Original unreviewed model estimate MMI **9.0** ($\sigma = 0.50$)

### Key Scientific & Operational Boundaries
- **Exploratory Sensitivity Experiment Only:** This analysis measures the mathematical sensitivity and spatial response of the official USGS ShakeMap 4.5 interpolation algorithm to a single data point in a confirmed 38.005-km baseline void. It does **NOT** constitute scientific validation or endorsement of Gemini's MMI estimate.
- **Strict Provenance Metadata:** Injected GeoJSON data files explicitly state `dataset_type: exploratory_sensitivity_test`, `scientific_use_allowed: false`, and `expert_approved: false`.
- **Baseline Freeze Preservation:** The official reconstructed Myanmar baseline (`us7000pn9s`) was verified, hashed, and preserved completely untouched. All three scenarios were executed in isolated ShakeMap event workspaces.
- **Zero Paid API Calls:** Conducted entirely with local binaries, offline ShakeMap 4.5.0, and existing cached inputs ($0.00 spent).

---

## 2. Critical Audit of Single-Observation Ingestion (`nresp` Provenance)

### 2.1 Investigation of the Preliminary `nresp=3` Handling
In the preliminary turn, the execution script logged `Ran update nresp to 3 in agent_mmi_dat.json`. A deep audit of this behavior was conducted across the codebase and official USGS ShakeMap 4.5 libraries.

#### Findings from `esi-shakelib` Source Code
In `/opt/anaconda3/envs/shakemap45/lib/python3.12/site-packages/esi_shakelib/station.py`:
1. **Station Feature Ingestion (lines 535-538):**
   ```python
   nresp = int(feature["properties"].get("nresp", -1))
   ```
   When the `nresp` field is omitted or set to `null` in GeoJSON, ShakeMap parses it as `-1`.
2. **Macroseismic Amplitude Database Query (lines 1245-1254):**
   ```python
   sql = (
       "SELECT a.id, a.station_id, a.intensity, a.flag, a.nresp "
       "FROM amp as a "
       "WHERE a.flag = '0' AND a.intensity IS NOT NULL "
       "AND (a.nresp < 0 OR a.nresp >= min_nresp)"
   )
   ```
3. **Cause of the Initial Issue:**
   The preliminary exporter had passed `nresp = 1` for a single field report. Because ShakeMap's default configuration sets `min_nresp = 3` for crowdsourced DYFI questionnaires, the condition `(1 < 0 OR 1 >= 3)` evaluated to **False**, causing ShakeMap to filter out the observation (`intensity = null`). To bypass this filter in the preliminary test, `nresp` was set to `3`.
4. **Provenance Evaluation:**
   Setting `nresp = 3` was a provenance error because P-02 is a single reconnaissance structural-damage report, not three aggregated DYFI questionnaire submissions. Manufacturing three respondents violates scientific data integrity.

### 2.2 The Sanctioned Single-Observation Solution: `nresp = null`
The authoritative USGS ShakeMap architecture accommodates single expert, reconnaissance, or non-DYFI observations natively:
- When GeoJSON properties specify `"nresp": null`, `esi_shakelib` translates this to `nresp = -1` in SQLite.
- Because `-1 < 0`, the condition `(a.nresp < 0 OR a.nresp >= min_nresp)` evaluates to **True** natively!
- ShakeMap ingests the macroseismic intensity without altering `min_nresp` and without manufacturing fictitious respondent counts.

### 2.3 Verification of Numerical Invariance
We verified both analytically and computationally that ShakeMap 4.5 uses `nresp` strictly for:
1. The ingestion filter `(a.nresp < 0 OR a.nresp >= min_nresp)`
2. Deriving default observation uncertainty $\sigma = \text{stddev} / \sqrt{\text{nresp}}$ **only when** `intensity_stddev` is not provided.

Because our scenario generation explicitly specifies `intensity_stddev = 0.50`, ShakeMap directly adopts $\sigma = 0.50$ into its covariance matrix. Consequently, switching from `nresp = 3` to `nresp = null`:
- Did not change the assimilated intensity ($8.0, 8.5, 9.0$).
- Did not change the observation variance ($\sigma = 0.50$).
- Produced **100% bit-for-bit identical numerical grids, site shifts, and event bias changes**.

Regression tests in `tests/test_sensitivity_experiment.py` now enforce:
- Exporter outputs `"nresp": None` for single reconnaissance observations.
- Rejection of any manufactured `nresp > 1` on single-site assessments.

---

## 3. Physical Event Parameter Verification

To ensure that the three sensitivity scenarios reflect purely the impact of the assimilated macroseismic observation without confounding physical variations, we audited all event parameters across `baseline` and the 3 scenario workspaces.

### Semantic Parameter Comparison

| Parameter | Baseline (`us7000pn9s`) | Scenario 1 (`mmi80`) | Scenario 2 (`mmi85`) | Scenario 3 (`mmi90`) | Semantic Match |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Origin Time (UTC)** | `2025-03-28T06:20:52.715Z` | `2025-03-28T06:20:52.715Z` | `2025-03-28T06:20:52.715Z` | `2025-03-28T06:20:52.715Z` | **Identical** |
| **Epicenter Latitude** | $22.011^\circ\text{ N}$ | $22.011^\circ\text{ N}$ | $22.011^\circ\text{ N}$ | $22.011^\circ\text{ N}$ | **Identical** |
| **Epicenter Longitude** | $95.9363^\circ\text{ E}$ | $95.9363^\circ\text{ E}$ | $95.9363^\circ\text{ E}$ | $95.9363^\circ\text{ E}$ | **Identical** |
| **Focal Depth** | $10.0\text{ km}$ | $10.0\text{ km}$ | $10.0\text{ km}$ | $10.0\text{ km}$ | **Identical** |
| **Magnitude** | $7.7\text{ Mw}$ | $7.7\text{ Mw}$ | $7.7\text{ Mw}$ | $7.7\text{ Mw}$ | **Identical** |
| **Fault Mechanism** | `SS` (Strike-Slip) | `SS` (Strike-Slip) | `SS` (Strike-Slip) | `SS` (Strike-Slip) | **Identical** |
| **Network / Source** | `us` / `US` | `us` / `US` | `us` / `US` | `us` / `US` | **Identical** |
| **Location String** | `2025 Mandalay, Burma (Myanmar) Earthquake` | Same | Same | Same | **Identical** |
| **Finite Rupture Geometry** | `6e256168653a...` | `6e256168653a...` | `6e256168653a...` | `6e256168653a...` | **Bit-for-bit SHA256 Match** |
| **Baseline Stationlist** | `059dbd803fad...` | `059dbd803fad...` | `059dbd803fad...` | `059dbd803fad...` | **Bit-for-bit SHA256 Match** |
| **GMPE Model Config** | `240942c8ebb0...` | `240942c8ebb0...` | `240942c8ebb0...` | `240942c8ebb0...` | **Bit-for-bit SHA256 Match** |
| **Grid Dimensions** | $(773, 648)$ | $(773, 648)$ | $(773, 648)$ | $(773, 648)$ | **Identical** |
| **Grid Resolution** | $dx = 0.01460^\circ, dy = 0.01369^\circ$ | Same | Same | Same | **Identical** |

**Note on Checksums:** The SHA256 hash of `event.xml` differs across scenarios solely because:
1. The operational XML attribute `id` reflects the scenario directory name (`us7000pn9s_p02_mmi80`, etc.), as required by ShakeMap's directory convention.
2. The serialization formatting (DTD doctype declaration).
Every physical, temporal, and geophysical attribute is semantically and numerically identical across all runs.

---

## 4. Quantitative Results & Sensitivity Metrics

### 4.1 Comparative Metrics Summary Table

| Metric | Baseline | Scenario 1 (MMI 8.0) | Scenario 2 (MMI 8.5) | Scenario 3 (MMI 9.0) |
| :--- | :---: | :---: | :---: | :---: |
| **Hypothetical Input MMI** | None | **8.0** | **8.5** | **9.0** |
| **Observation Uncertainty ($\sigma$)** | N/A | $0.50$ | $0.50$ | $0.50$ |
| **Modeled MMI at Pyawbwe Site** | 9.95 | **8.82** | **9.11** | **9.40** |
| **Signed Shift at Site ($\Delta\text{MMI}$)** | 0.00 | **-1.13** | **-0.84** | **-0.55** |
| **Peak Grid Decrease ($\min \Delta\text{MMI}$)** | 0.00 | **-1.15** | **-0.86** | **-0.56** |
| **Peak Grid Increase ($\max \Delta\text{MMI}$)** | 0.00 | $+0.00$ | $+0.00$ | $+0.00$ |
| **Mean Absolute $\Delta\text{MMI}$ (Full Grid)** | 0.000 | **0.045** | **0.033** | **0.022** |
| **Surface Area $|\Delta\text{MMI}| \ge 0.1\text{ MMI}$** | $0.0\text{ km}^2$ | **$10,876.0\text{ km}^2$** | **$7,009.8\text{ km}^2$** | **$3,684.9\text{ km}^2$** |
| **Surface Area $|\Delta\text{MMI}| \ge 0.2\text{ MMI}$** | $0.0\text{ km}^2$ | **$3,823.6\text{ km}^2$** | **$2,309.3\text{ km}^2$** | **$966.2\text{ km}^2$** |
| **Surface Area $|\Delta\text{MMI}| \ge 0.5\text{ MMI}$** | $0.0\text{ km}^2$ | **$568.6\text{ km}^2$** | **$217.3\text{ km}^2$** | **$16.2\text{ km}^2$** |
| **Surface Area $|\Delta\text{MMI}| \ge 1.0\text{ MMI}$** | $0.0\text{ km}^2$ | **$23.1\text{ km}^2$** | **$0.0\text{ km}^2$** | **$0.0\text{ km}^2$** |
| **Event MMI Bias** | $+0.9780$ (36 stas) | **$+0.9200$** (37 stas) | **$+0.9350$** (37 stas) | **$+0.9490$** (37 stas) |
| **Event Bias Shift ($\Delta\text{bias}$)** | 0.0000 | **-0.0580** | **-0.0430** | **-0.0290** |
| **ShakeMap Ingestion Filter** | `a.nresp < 0` | `a.nresp < 0` | `a.nresp < 0` | `a.nresp < 0` |

---

## 5. Decomposed Radial Distance Decay Profiles

The spatial influence of the single Pyawbwe observation decomposes into:
1. **Local Spatial Conditioning ($\Delta\text{MMI}_{\text{local}}$):** Decays to zero beyond $\approx 40 - 50\text{ km}$ following the Worden et al. (2018) spatial correlation function.
2. **Uniform Regional Event Bias Shift ($\Delta\text{bias}$):** A spatially uniform scalar shift affecting all grid points globally ($-0.03$ to $-0.06$ MMI units).

$$\Delta\text{MMI}(r) = \Delta\text{MMI}_{\text{local}}(r) + \Delta\text{bias}$$

| Distance Range ($r$) | Midpoint ($r_{mid}$) | Grid Cells | Mean Total $\Delta\text{MMI}$ (8.0) | Local Spatial Shift ($\Delta\text{MMI}_{\text{local}}$) | Uniform Event Bias ($\Delta\text{bias}$) |
| :---: | :---: | :---: | :---: | :---: | :---: |
| **$0.0 - 5.0\text{ km}$** | $2.5\text{ km}$ | 32 | **-0.9589** | -0.9009 | -0.0580 |
| **$5.0 - 10.0\text{ km}$** | $7.5\text{ km}$ | 104 | **-0.7026** | -0.6446 | -0.0580 |
| **$10.0 - 20.0\text{ km}$** | $15.0\text{ km}$ | 407 | **-0.4566** | -0.3986 | -0.0580 |
| **$20.0 - 30.0\text{ km}$** | $25.0\text{ km}$ | 680 | **-0.2896** | -0.2316 | -0.0580 |
| **$30.0 - 50.0\text{ km}$** | $40.0\text{ km}$ | 2,180 | **-0.1650** | -0.1070 | -0.0580 |
| **$50.0 - 75.0\text{ km}$** | $62.5\text{ km}$ | 4,224 | **-0.0940** | -0.0360 | -0.0580 |
| **$75.0 - 100.0\text{ km}$** | $87.5\text{ km}$ | 5,945 | **-0.0626** | -0.0046 | -0.0580 |
| **$100.0 - 150.0\text{ km}$** | $125.0\text{ km}$ | 16,982 | **-0.0496** | +0.0084 | -0.0580 |
| **$150.0 - 200.0\text{ km}$** | $175.0\text{ km}$ | 23,762 | **-0.0517** | +0.0063 | -0.0580 |

*Beyond the 38.005-km data void boundary, the local spatial correlation decays to zero, and the residual field matches the global event bias change.*

---

## 6. Scientific Interpretation & Answers to Key Model Behaviors

### 6.1 Why does the Reconstructed Baseline Predict ~MMI 9.95 at Pyawbwe?
In the unaugmented baseline, Pyawbwe is situated directly adjacent to the southern terminus of the finite fault rupture:
- Closest rupture distance: $R_{rup} = 1.268\text{ km}$.
- Epicentral distance: $R_{epi} = 158.501\text{ km}$.
- Nearest assimilated baseline station: $38.005\text{ km}$ away (DYFI UTM zone 46Q, CDI 8.5).

Because no seismic stations or DYFI reports existed within $38\text{ km}$, ShakeMap's Multivariate Normal (MVN) conditional mean reverted entirely to the unconditioned Ground Motion Prediction Equation (GMPE):
$$\mu_{baseline} = \mu_{GMPE}(M 7.7, R_{rup} = 1.27\text{ km}, V_{S30}) + \Delta B_{baseline}$$
For an active crustal strike-slip Mw 7.7 event at $R_{rup} \approx 1.3\text{ km}$, the NSHMP 2014 active crustal GMPE predicts an unadjusted MMI of approximately $8.97$. Because the 36 distant DYFI stations on average experienced stronger shaking than the median GMPE, ShakeMap calculated a positive regional event bias of **$\Delta B = +0.9780$**. Adding this bias to the near-fault GMPE prediction yields:
$$\mu_{baseline} \approx 8.97 + 0.98 = \mathbf{9.95}$$
Thus, the baseline MMI of ~9.95 was not an empirical observation; it was a theoretical near-fault extrapolation conditioned by a strong regional positive bias.

### 6.2 Why Does Modeled Output MMI Not Equal Hypothetical Input MMI?
In Bayesian / MVN kriging, an observation does not overwrite the grid. Instead, the posterior intensity $\hat{Y}(x)$ at observation location $x_0$ is:
$$\hat{Y}(x_0) = \mu_{prior}(x_0) + \Sigma_{obs, prior} \left( \Sigma_{obs, obs} + \sigma_\epsilon^2 I \right)^{-1} (Y_{obs} - \mu_{prior}(x_0))$$
Because we specified observation error $\sigma_\epsilon = 0.50$ ($\sigma_\epsilon^2 = 0.25$), the diagonal of the covariance matrix is inflated by measurement uncertainty. This creates **Bayesian shrinkage** (attenuation toward the prior):
- For Input MMI 8.0: Modeled MMI = **8.82** (pulls baseline down by $-1.13$, but shrinks toward prior ~9.95).
- For Input MMI 8.5: Modeled MMI = **9.11** (pulls baseline down by $-0.84$).
- For Input MMI 9.0: Modeled MMI = **9.40** (pulls baseline down by $-0.55$).

This proves ShakeMap 4.5's statistical robustness: a single macroseismic report cannot override physical GMPE constraints, even when placed directly on the fault.

### 6.3 Local Observation Conditioning vs Regional Event Bias Shifts
The total intensity shift at any location consists of two distinct components:
1. **Local Kriging Residual:** Controlled by the spatial covariance matrix $\Sigma(h) = \exp(-3h / d_{corr})$. It drops from $-1.08$ at the site to zero within $40 - 50\text{ km}$.
2. **Regional Event Bias Shift:** ShakeMap recalculates the inter-event term $\Delta B$ using all available stations. Adding P-02 (which reported lower intensity than the $+0.98$ baseline prediction) pulls the global event bias down from $+0.9780$ to $+0.9200$ ($\Delta\text{bias} = -0.0580$). This $-0.058$ shift is uniformly applied across all $500,904$ grid cells.

---

## 7. Cartographic and Diagnostic Visualizations

The experiment produced publication-ready cartographic products under `data/events/us7000pn9s/sensitivity_p02/plots/`:

1. **Pyawbwe High-Resolution Data Void Map:**
   [`plots/p02_pyawbwe_data_void_map.png`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/data/events/us7000pn9s/sensitivity_p02/plots/p02_pyawbwe_data_void_map.png)  
   Shows the Pyawbwe observation ($R_{rup} = 1.268\text{ km}$), the 3D finite fault surface projection, and the $38.005\text{ km}$ void connecting P-02 to the nearest assimilated DYFI station (`UTM:(46Q 0797 2311 1000)` at `[95.8594, 20.8799]`, CDI 8.5).
2. **Pyawbwe 8-Panel Zoomed Comparison:**
   [`plots/p02_pyawbwe_zoom_comparison.png`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/data/events/us7000pn9s/sensitivity_p02/plots/p02_pyawbwe_zoom_comparison.png)  
   Focused on the Pyawbwe sub-region ($\text{lon} \in [95.5, 96.6]^\circ$, $\text{lat} \in [20.2, 21.2]^\circ$):
   - Row 1: Baseline, Scenario 1 (8.0), Scenario 2 (8.5), Scenario 3 (9.0).
   - Row 2: 38.005-km data void geometry, followed by 3 difference maps ($\Delta\text{MMI}$) with explicit contour lines at $\Delta\text{MMI} = -0.1, -0.2, -0.5$.
3. **Multi-panel Regional Comparison:**
   [`plots/p02_sensitivity_side_by_side_comparison.png`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/data/events/us7000pn9s/sensitivity_p02/plots/p02_sensitivity_side_by_side_comparison.png)  
   Expanded $(24 \times 12\text{ in})$ publication layout with non-overlapping typography, comparing the full regional grids on standardized colorbars.
4. **Decomposed Radial Distance Decay Chart:**
   [`plots/p02_radial_distance_decay.png`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/data/events/us7000pn9s/sensitivity_p02/plots/p02_radial_distance_decay.png)  
   Two-panel vertical layout decomposing total $\Delta\text{MMI}(r)$ into the localized spatial conditioning curve and the uniform global event bias shift, with the $38.005\text{ km}$ data void callout.
5. **Modeled Site MMI vs. Input Prior Response Curve:**
   [`plots/p02_delta_vs_input_mmi.png`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/data/events/us7000pn9s/sensitivity_p02/plots/p02_delta_vs_input_mmi.png)  
   Shows input MMI vs modeled output site MMI against the 1:1 line and baseline reference, alongside bar charts of signed site and regional bias shifts.

---

## 8. Preserved Machine-Readable Artifacts

All experiment metadata, manifests, and CSVs are archived in:
- Master Manifest: [`data/events/us7000pn9s/sensitivity_p02/sensitivity_experiment_manifest.json`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/data/events/us7000pn9s/sensitivity_p02/sensitivity_experiment_manifest.json)
- Summary Metrics CSV: [`data/events/us7000pn9s/sensitivity_p02/p02_sensitivity_metrics_summary.csv`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/data/events/us7000pn9s/sensitivity_p02/p02_sensitivity_metrics_summary.csv)
- Baseline Freeze Manifest: [`data/events/us7000pn9s/baseline_recon/baseline_freeze_manifest.json`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/data/events/us7000pn9s/baseline_recon/baseline_freeze_manifest.json)
- Scenarios JSON:
  - [`scenario_mmi80_summary.json`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/data/events/us7000pn9s/sensitivity_p02/scenario_mmi80_summary.json)
  - [`scenario_mmi85_summary.json`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/data/events/us7000pn9s/sensitivity_p02/scenario_mmi85_summary.json)
  - [`scenario_mmi90_summary.json`](file:///Users/jasondeng/Downloads/Files/Harvard/F26/EPS%2055/Final%20Project/MMI-Gram-Clean/data/events/us7000pn9s/sensitivity_p02/scenario_mmi90_summary.json)

---

## 9. Verification & Test Suite Status

The complete offline test suite passes:
- **Command:** `PYTHONPATH="src:server:.clean_venv/lib/python3.13/site-packages" /opt/anaconda3/bin/python -m pytest tests`
- **Result:** **217 passed, 1 skipped** (1 intentional live-network test skipped).
- **Git State:** On branch `feature/quake-agent-integration`, clean working tree with only untracked sensitivity files and no commits or pushes staged, awaiting user final review.
