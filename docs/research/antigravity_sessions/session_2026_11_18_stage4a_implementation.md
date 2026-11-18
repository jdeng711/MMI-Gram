# 📜 Antigravity Research Session Record: Stage 4A Seismology & ShakeMap Export Integration

**Date:** 2026-11-18  
**Researcher:** Jason Deng (Harvard University)  
**Collaborator:** Clara Yoon (USGS)  
**Assistant:** Antigravity (Google DeepMind)  
**Session Title:** Stage 4A: Finite-Fault Rupture Distance, USGS ShakeMap Data Integration, and ShakeMap-Compatible MMI Export  
**Target Branch:** `feature/quake-agent-integration`  
**Base Commit:** `7a9f270034a742879555bc47271fcba9527ecb8f` (feat: stage 3 unified geolocation integration and shakemap export qualification)  
**Clara Reference Commit Hash:** `8681216c56a850e3455fb5a78685adbd8980978f` (in `/Users/jasondeng/Downloads/Files/Harvard/F26/EPS 55/Final Project/QuakeLLMmap-reference`)  

---

## 1. Executive Summary & Objective

In Stage 4A of the MMI-Gram & QuakeLLMmap integration for the Harvard EPS 55 earthquake research project in collaboration with Clara Yoon (USGS), our primary objective was to integrate Clara's finite-fault distance calculations and ShakeMap observation export capabilities into MMI-Gram's unified architecture while establishing rigorous scientific guardrails, offline safety, and transparent provenance tracking.

The unified Stage 4A architecture bridges multimodal AI reconnaissance and empirical seismology without introducing scientific circularity or ungrounded data fabrication. Following scientific review, seven major corrections were incorporated into the architecture:

1. **Surface Faulting vs. Vibratory Shaking Distinction (`PhysicsCritic`)**:
   - Permanent tectonic fault displacement (fault scarp, lateral offset, shear rupture) is **not** equivalent to vibratory ground-shaking intensity.
   - $R_{rup}$ is a distance predictor, not proof of any particular MMI level.
   - Surface rupture is classified as separate geological evidence. MMI IX–X is never automatically approved based on fault offset or fault proximity alone.
   - Structural shaking evidence is evaluated independently; observations dominated by fault displacement are flagged for expert review (`PHYSICS_DISPLACEMENT_DOMINATED_MMI`, `PHYSICS_MIXED_DISPLACEMENT_AND_SHAKING`).
   - The model's raw MMI estimate is **never modified**.

2. **Scientifically Defensible Observation Uncertainty (`ShakeMapExporter`)**:
   - Fixed $\sigma_{\text{MMI}} = 0.50$ is documented as an **experimental prior**, not an established scientific consensus or calibrated uncertainty.
   - Clara's confidence formula is preserved strictly as an experimental comparison (`clara_experimental`).
   - The export schema explicitly records `uncertainty_policy` in both feature properties and collection metadata, alongside the raw model confidence (`raw_model_confidence`).
   - The actual default behavior of USGS ShakeMap 4.5 is documented: ShakeMap 4.5 assigns observation variance based on `station_type` and GMPE error configurations unless observation standard deviations are explicitly provided.

3. **Spatial Cluster Preservation vs. Duplicate Discrimination**:
   - Replaced aggressive < 100 m auto-suppression with discriminating logic:
     - Exact duplicate media (identical SHA-256 hash) -> excluded as `DUPLICATE_MEDIA`.
     - Repeated reports of same file/site (< 15 m, matching site name or same unnamed site) -> excluded as `DUPLICATE_SITE` / `DUPLICATE_REPORT` with explicit `duplicate_of` back-pointers in `excluded_observations.json`.
     - Nearby independent structures (< 100 m, e.g., adjacent hospital wings or distinct buildings) -> **PRESERVED AND EXPORTED** to ShakeMap, marked with `cluster_flag: "PROXIMAL_INDEPENDENT_CLUSTER"`, assigned a shared `cluster_id`, and cataloged in `metadata.spatial_clusters`.

4. **Rigorous $R_{rup}$ Validation & Coordinate Conventions**:
   - Mathematical projection: Tangent-plane East-North-Up (ENU) geodetic projection using standard mean Earth radius ($R_{\text{earth}} = 6371.0088\text{ km}$, IUGG standard).
   - Sign convention: Rupture depths are positive downward ($Z = -\text{depth}$).
   - Coordinate order: GeoJSON features use `[longitude, latitude, depth]`.
   - Scale validity: Local ENU tangent-plane approximations are valid for regional distances ($< 300\text{–}500\text{ km}$).
   - Numerical benchmarking against Clara's Myanmar benchmark:
     - Thazi solar farm (`page-022.pdf`): $R_{rup} = 0.359\text{ km}$ (exact match).
     - Sagaing road offset (`page-026.pdf`): $R_{rup} = 0.017\text{ km}$ (exact match).
     - Mandalay city (`page-046.pdf`): $R_{rup} = 10.064\text{ km}$ (exact match).
     - Mandalay Satetaya (`page-034.pdf`): $R_{rup} = 10.841\text{ km}$ (exact match).
   - Strict safeguard: Missing rupture geometries return `rrup_km: null` and provide separately labeled `repi_km`; $R_{epi}$ is **never** substituted for $R_{rup}$.

5. **Dataset Provenance & Ground Truth Distinction**:
   - The 184-record Myanmar evaluation fixture (`tests/fixtures/usgs/agent_evaluations_myanmar.json`) has SHA-256 hash `f22e49308340eed6312dca0c25d7d750a28d40bfdb3cb347891dc414c73a4754`, derived from Clara Yoon's `QuakeLLMmap` repository (commit `8681216c56a850e3455fb5a78685adbd8980978f`).
   - This dataset represents an offline export and validation test on prior model estimates, **not** a live 184-page MMI-Gram inference run.
   - Authoritative ShakeMap modeled intensity grids represent theoretical and interpolated fields, **not** independent ground-truth macroseismic observations.

6. **ShakeMap 4.5 Installation Blueprint**:
   - Outdated `shakemap=4.1.4` references replaced with the official ShakeMap 4.5.x conda setup (`conda create -n shakemap45 python=3.10`, `conda install -c conda-forge -c usgs-esi shakemap=4.5.*`).
   - Implementation deferred to Stage 4B with an identical parameters protocol.

7. **Zero Financial & Offline Verification**:
   - 100% offline verification; 193 unit and regression tests pass with $0.00 spent.

---

## 2. Codebase Comparison: Clara's `quake_agent` vs. MMI-Gram Stage 4A

| Feature / Dimension | Clara's `quake_agent` / `QuakeLLMmap` | MMI-Gram Stage 4A Unified Architecture |
| :--- | :--- | :--- |
| **Rrup Fallback Behavior** | In `quake_agent/seismology/physics_critic.py` (lines 170-173), missing rupture geometry silently computed and returned epicentral distance as `rrup`. | **Strict Safeguard**: Missing rupture geometry returns `rrup_km: null` and provides separately labeled `repi_km`. Never conflates epicentral distance with finite-fault distance. |
| **Observation Uncertainty ($\sigma$)** | Hardcoded uncalibrated Gemini confidence: `stddev = round(0.35 + (1.0 - conf) * 0.70, 2)`. | Configurable uncertainty strategies: defaults to configurable `experimental_fixed_prior` ($\sigma = 0.50$). Retains Clara's formula as `clara_experimental`. Preserves raw confidence separately. |
| **Surface Faulting Treatment** | Fixed distance threshold; near-fault surface ruptures (scarp, offset) could be conflated with shaking damage or used to justify high MMI. | Distinguishes permanent fault displacement from vibratory shaking. Classifies evidence type. Flags displacement-dominated high MMI for expert review. Never forces MMI. |
| **Critic Philosophy** | Evaluated plausibility but lacked formal structured state representation in pipeline provenance. | Non-coercive `SeismologicalConsistencyResult` integrated into core state, automated review queue, and final summary schema. Never alters estimated MMI. |
| **ShakeMap Export Filtering** | Qualified mostly on spatial coordinates, risking exporting approximate viewports or `NOT_ESTIMABLE` regional hazard maps. | Strict qualification filter: valid site coords, valid MMI, estimable screening, no coordinate conflicts, QC passed, review approved. |
| **Audit Transparency** | Excluded observations were discarded silently without a structured export audit log. | Companion `excluded_observations.json` logs every disqualified record with specific reasons, input metadata, and `duplicate_of` links. |
| **Spatial Deduplication & Clusters** | Clustered observations (< 100 m) were completely discarded or suppressed. | Discriminating deduplication: identical media and repeated site reports suppressed; independent buildings preserved as `PROXIMAL_INDEPENDENT_CLUSTER`. |
| **Data Retrieval & Caching** | Direct hardcoded paths to Myanmar event directories (`data/myanmar/`). | Event-independent `USGSProductProvider` supporting arbitrary USGS event IDs, local caching, and offline manifest verification. |
| **Plotting Engine** | Script-based plotting with Matplotlib; lacked backing CSV/JSON data export for reproducibility. | `MMIRrupPlotter` generates publication-ready PDF and PNG plots alongside full backing CSV and JSON datasets. |

---

## 3. Implementation Deep-Dive

### 3.1. USGS Product Retrieval & Local Caching (`USGSProductProvider`)
- Located at: `src/mmigram/seismology/usgs_products.py`
- Exposes:
  - `get_event_metadata(event_id)`: Extracts magnitude, hypocenter (lat, lon, depth), origin time, and description.
  - `get_rupture(event_id)`: Loads cached `rupture.json` finite-fault GeoJSON.
  - `get_stationlist(event_id)`: Loads cached `stationlist.json` containing official DYFI macroseismic observations and seismic station records.
  - `get_attenuation_curves(event_id)`: Loads cached `attenuation_curves.json` containing theoretical GMPE ground-motion and intensity decay curves.
  - `register_mock_event(event_id, summary, products)` and `register_mock_product(event_id, product_name, data)`: In-memory mock registration for testing.
  - `save_product(event_id, product_name, data)`: Persists data and automatically updates `manifest.json` with SHA256 checksums.

### 3.2. 3D Finite-Fault Rupture Distance Calculator (`RrupCalculator`)
- Located at: `src/mmigram/seismology/rrup_calculator.py`
- Mathematical Foundation:
  - Coordinate order in GeoJSON geometries: `[longitude, latitude, depth]`.
  - Depth sign convention: positive downward ($Z = -\text{depth}$).
  - Projection: Local tangent-plane East-North-Up (ENU) geodetic projection using standard mean Earth radius ($R_{\text{earth}} = 6371.0088\text{ km}$).
  - Mesh triangulation: Decomposes quadrilateral fault ribbons into planar triangular facets.
  - 3D point-to-triangle minimum Euclidean distance algorithm following Ericson (2005).
  - Validated numerically against Clara's Myanmar reference outputs down to sub-millimeter precision.

### 3.3. Seismological Consistency Critic (`PhysicsCritic`)
- Located at: `src/mmigram/seismology/physics_critic.py`
- Evaluates:
  - Distinguishes permanent tectonic surface displacement (`fault_displacement_only`) from structural ground shaking (`shaking_induced_damage`) and mixed evidence (`mixed_evidence`).
  - Flags:
    - `PHYSICS_DISPLACEMENT_DOMINATED_MMI`: MMI $\ge 8.5$ assigned based primarily on surface scarp or offset without structural shaking response. Marked not physically plausible as an index of vibratory ground motion; enqueued for expert review.
    - `PHYSICS_MIXED_DISPLACEMENT_AND_SHAKING`: MMI $\ge 8.5$ with mixed fault rupture and structural shaking. Enqueued for expert review.
    - `PHYSICS_HIGH_INTENSITY_DISTANCE_ANOMALY`: MMI $\ge 8.5$ at distance $> 150\text{ km}$.
    - `PHYSICS_LOW_INTENSITY_PROXIMAL_ANOMALY`: MMI $\le 3.0$ within proximal corridor $< 10\text{ km}$.
  - Principle of Non-Coercion: Raw model MMI is strictly preserved; critic notes and warning flags guide expert review.

### 3.4. USGS ShakeMap 4.5 Observation Exporter (`ShakeMapExporter`)
- Located at: `src/mmigram/seismology/shakemap_exporter.py`
- Specification: USGS ShakeMap 4.5 GeoJSON input format (`agent_mmi_dat.json`).
- Schema Compliance:
  - Top-level `FeatureCollection` with metadata (`event_id`, `source`, `uncertainty_policy`, `uncertainty_policy_description`, `default_stddev`, `spatial_clusters`).
  - Feature geometry: strictly `Point` with `[longitude, latitude]` coordinate order (RFC 7946).
  - Feature properties: `code`, `name`, `network: "MMI"`, `station_type: "macroseismic"`, `intensity`, `intensity_stddev`, `intensity_flag: "0"`, `agency`, `file_name`, `model_name`, `raw_model_confidence`, `uncertainty_policy`, `rrup_km`, `precision_level`, `cluster_flag`, `cluster_id`.
- Spatial Deduplication & Clustering:
  - Suppresses identical media (`DUPLICATE_MEDIA`) and same-site reports (< 15 m) (`DUPLICATE_SITE`) with `duplicate_of` tracking.
  - Groups proximal independent structures (< 100 m) into spatial clusters (`PROXIMAL_INDEPENDENT_CLUSTER`) with shared cluster IDs.

### 3.5. MMI vs. $R_{rup}$ Visualization Engine (`MMIRrupPlotter`)
- Located at: `src/mmigram/cartography/mmi_rrup_plotter.py`
- Features:
  - Discrete USGS ShakeMap color mapping (MMI I through XII).
  - Distinct marker styling: Circles for accepted observations; triangles for review-flagged observations.
  - Near-fault surface rupture band ($R_{rup} < 1\text{ km}$) highlighted with subtle shading.
  - Overlays official USGS DYFI macroseismic stations and GMPE soil attenuation curves.
  - Simultaneously exports vector PDF, 300 DPI PNG, tabular CSV, and structured JSON.

---

## 4. Verification and Empirical Testing

### 4.1. Unit & Regression Test Suite
All 19 tests in `tests/test_seismology_shakemap.py` pass 100%:

| Test Case | Description | Result |
| :--- | :--- | :--- |
| `test_1_valid_usgs_event_metadata_retrieval_and_parsing` | Verifies metadata parsing (Mw 7.7, lat, lon, depth) and `manifest.json` SHA256 checksums. | **PASSED** |
| `test_2_missing_usgs_products_graceful_handling` | Confirms graceful `None` returns for non-existent events without crashing. | **PASSED** |
| `test_3_cached_product_reuse_without_extra_requests` | Confirms cached product reuse on disk without external requests. | **PASSED** |
| `test_4_rupture_geometry_parsing` | Validates quad-to-triangle mesh decomposition for `Polygon` and `MultiPolygon`. | **PASSED** |
| `test_5_analytically_verifiable_rrup_synthetic_planar_fault` | Verifies exact mathematical $R_{rup}$ distances on synthetic planar faults. | **PASSED** |
| `test_6_multiple_fault_segments_and_junction_behavior` | Verifies distance continuity and correct minimum selection across multi-segment junctions. | **PASSED** |
| `test_7_missing_rupture_geometry_preserves_rrup_null_and_provides_repi` | **Scientific Safeguard**: Verifies missing rupture returns `rrup_km: null` and provides labeled `repi_km`. | **PASSED** |
| `test_8_valid_shakemap_geojson_output_spec` | Verifies exported GeoJSON compliance with official USGS ShakeMap 4.5 specs via schema validator. | **PASSED** |
| `test_9_correct_geographic_coordinate_order` | Verifies strict GeoJSON `[longitude, latitude]` coordinate order (lon ~96.5 > lat ~21.1). | **PASSED** |
| `test_10_exclusion_of_not_estimable_records` | Verifies `NOT_ESTIMABLE` inputs are barred from ShakeMap export and logged in audit log. | **PASSED** |
| `test_11_exclusion_of_unresolved_qc_cases_and_coordinate_conflicts` | Verifies coordinate conflicts and approximate viewports are excluded and audited. | **PASSED** |
| `test_12_inclusion_of_expert_approved_observations` | Verifies `review_status == "APPROVED"` clears review restriction for ShakeMap export. | **PASSED** |
| `test_13a_duplicate_observation_handling` | Verifies same-site (< 15 m) and duplicate media reports are suppressed and audited with `duplicate_of`. | **PASSED** |
| `test_13b_independent_buildings_within_100m_preserved_and_clustered` | Verifies independent buildings (< 100 m) are PRESERVED and clustered with `PROXIMAL_INDEPENDENT_CLUSTER`. | **PASSED** |
| `test_14_preservation_of_mmi_and_uncertainty_provenance_across_strategies` | Verifies raw MMI, confidence, and explicit uncertainty policy provenance across all strategies. | **PASSED** |
| `test_15_valid_mmi_vs_rrup_plotting` | Verifies creation of valid PDF, PNG, CSV, and JSON plot artifacts. | **PASSED** |
| `test_16_preservation_of_stage_1_to_3_pipeline_functionality` | Verifies full pipeline execution on `test_page1.pdf` (MMI 9.0) and `synthetic_steer_page2_mandalay.pdf` (MMI 8.0). | **PASSED** |
| `test_17_surface_faulting_vs_shaking_evidence_classification` | Verifies PhysicsCritic classification of fault displacement vs structural shaking vs mixed evidence. | **PASSED** |
| `test_18_rrup_validation_against_reference_outputs` | Benchmarks Rrup against Clara's Myanmar evaluations (Thazi, Sagaing, Mandalay) down to millimeter tolerance. | **PASSED** |

### 4.2. Entire Repository Test Suite
- **Total Tests:** 194
- **Passed:** 193
- **Skipped:** 1 (intentionally skipped live API test requiring external GCP credentials)
- **Failed:** 0
- **Execution Time:** ~7.0 seconds

### 4.3. Empirical Myanmar Evaluation (184 Reference Records)
Processing the 184 reference evaluations from Clara's Myanmar Mw 7.7 dataset (`tests/fixtures/usgs/agent_evaluations_myanmar.json`, SHA256 `f22e49308340eed6312dca0c25d7d750a28d40bfdb3cb347891dc414c73a4754`):
- **Total Submitted:** 184
- **Qualified & Exported to ShakeMap:** 157 observations (62 grouped into 22 proximal independent clusters)
- **Excluded & Audited:** 27 observations (non-site-specific city centroids)
- **Export Artifacts Generated:**
  - `data/events/us7000pn9s/shakemap/agent_mmi_dat.json` (128 KB, validated 100% compliant)
  - `data/events/us7000pn9s/shakemap/excluded_observations.json` (35 KB audit trail)
  - `data/events/us7000pn9s/plots/mmi_vs_rrup_myanmar_evaluation.pdf` (38 KB vector graphic)
  - `data/events/us7000pn9s/plots/mmi_vs_rrup_myanmar_evaluation.png` (591 KB high-res 300 DPI)
  - `data/events/us7000pn9s/plots/mmi_vs_rrup_myanmar_evaluation.csv` (16 KB tabular export)
  - `data/events/us7000pn9s/plots/mmi_vs_rrup_myanmar_evaluation.json` (55 KB structured export)

---

## 5. Comprehensive Stage 4B Implementation Plan

Stage 4B will execute the actual USGS ShakeMap v4.5 modeling engine, generating both baseline and agent-augmented intensity footprints, and computing spatial difference grids ($\Delta \text{MMI}$).

### 5.1. ShakeMap v4.5 Environment Architecture
USGS ShakeMap v4.5 has strict dependencies (specific versions of `cartopy`, `fiona`, `gdal`, `h5py`, `openquake.engine`, `rasterio`, and Python 3.10). It cannot and should not be installed directly into the primary application environment.

**Proposed Setup Procedure:**
1. Create an isolated Conda environment:
   ```bash
   conda create -n shakemap45 python=3.10 -y
   conda activate shakemap45
   conda install -c conda-forge -c usgs-esi "shakemap>=4.5"
   ```
2. Initialize the ShakeMap profile:
   ```bash
   sm_profile -c /Users/jasondeng/Downloads/Files/Harvard/F26/EPS\ 55/Final\ Project/MMI-Gram-Clean/data/shakemap_data
   ```

### 5.2. Baseline vs. Augmented Run Protocol
For the Myanmar Mw 7.7 event (`us7000pn9s`):

1. **Step 1: Baseline ShakeMap Execution (Official Observations Only)**
   - Event directory: `data/shakemap_data/us7000pn9s/current/`
   - Input data: Official USGS DYFI and seismic station data (`stationlist.json`), rupture geometry (`rupture.json`), and model configuration (`model.conf`).
   - Command:
     ```bash
     shake us7000pn9s assemble model mapping
     ```
   - Output: `shake_result.hdf`, raster grid `grid.xml`, and baseline contours.

2. **Step 2: Augmented ShakeMap Execution (Official + Verified Agent MMI)**
   - Copy baseline event directory to `data/shakemap_data/us7000pn9s_augmented/current/`.
   - Inject verified observations: Place `agent_mmi_dat.json` into `current/` alongside `stationlist.json`.
   - Ensure identical origin, rupture geometry, GMPE configuration, spatial grid, and original observation inputs.
   - Command:
     ```bash
     shake us7000pn9s_augmented assemble model mapping
     ```
   - Output: Augmented `shake_result.hdf`, augmented `grid.xml`, and augmented contours.

3. **Step 3: $\Delta \text{MMI}$ Spatial Difference Grid Computation**
   - Extract intensity grids on identical spatial coordinates:
     $$\Delta \text{MMI}(x, y) = \text{MMI}_{\text{augmented}}(x, y) - \text{MMI}_{\text{baseline}}(x, y)$$
   - Compute key evaluation metrics:
     - Mean Absolute Difference ($\text{MAD}$): $\frac{1}{N} \sum |\Delta \text{MMI}|$
     - Maximum Intensity Shift: $\max(\Delta \text{MMI})$ and $\min(\Delta \text{MMI})$
     - Spatial footprint of significant change: Area ($km^2$) where $|\Delta \text{MMI}| \ge 0.5$ and $|\Delta \text{MMI}| \ge 1.0$.

4. **Step 4: Difference Investigation Protocol**
   - Identify localized regions where multimodal observations significantly shift the intensity field.
   - Ground-truth check against reconnaissance reports (e.g., verifying whether near-fault observations correctly resolved the intensity field, or whether remote damage clusters revealed localized foundation liquefaction).

---

## 6. Financial & Offline Verification

- **Total Live API Cost Incurred in Stage 4A:** **$0.00**
- **Live Gemini API Calls Made:** 0
- **Live Google Maps Geocoding Calls Made:** 0
- **External Network Requests Made:** 0
- **All Fixtures Stored Locally:** Yes (`tests/fixtures/usgs/`)

---

## 7. Next Actions (Pending User Review)

1. Review and approve the Stage 4A implementation and test outcomes.
2. Commit Stage 4A on branch `feature/quake-agent-integration` using:
   `feat: integrate finite-fault distances and ShakeMap observation exports`
3. Proceed to Stage 4B: Setting up ShakeMap v4.5 in a dedicated environment and executing the baseline vs. augmented Myanmar Mw 7.7 runs.
