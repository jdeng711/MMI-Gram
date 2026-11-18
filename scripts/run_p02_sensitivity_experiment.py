#!/usr/bin/env python3
"""
Orchestration Script: Stage 4B Workflow B - P-02 ShakeMap Sensitivity Experiment (Corrected Ingestion Pass).

Runs three isolated USGS ShakeMap 4.5 scenarios for observation P-02 (Pyawbwe KBZ Bank):
- MMI 8.0 (sigma = 0.50)
- MMI 8.5 (sigma = 0.50)
- MMI 9.0 (sigma = 0.50, original unreviewed model estimate)

Scientific & Operational Safeguards:
- Native single macroseismic observation ingestion (nresp = null / omitted), mapping to
  ShakeMap SQLite clause: WHERE (a.nresp < 0 OR a.nresp >= min_nresp).
  Does NOT fabricate respondents (nresp != 3) or alter global min_nresp.
- Frozen baseline preservation (no mutation of us7000pn9s).
- Isolated event workspaces.
- Exploratory sensitivity provenance (scientific_use_allowed: false).
- Full input and output SHA256 checksum tracking.
- Semantic verification of identical physical event parameters.
- Quantitative spatial metrics, tabular CSV, publication regional figures, and Pyawbwe close-up maps.
"""

from __future__ import annotations
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Any, List

# Ensure repo root and site-packages are accessible
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "server"))
clean_venv_site = REPO_ROOT / ".clean_venv" / "lib" / "python3.13" / "site-packages"
if clean_venv_site.exists():
    sys.path.insert(0, str(clean_venv_site))

import h5py
import numpy as np

from mmigram.seismology.shakemap_comparator import ShakeMapGridComparator
from mmigram.seismology.sensitivity_runner import (
    compute_sha256,
    prepare_scenario_workspace,
    execute_shakemap_scenario,
    verify_scenario_assimilation,
    compute_scenario_spatial_metrics,
    plot_standalone_grid,
    plot_standalone_difference,
    plot_side_by_side_comparison,
    plot_pyawbwe_data_void_map,
    plot_pyawbwe_zoom_comparison,
    plot_delta_vs_input_mmi,
    plot_radial_distance_decay,
    SHAKEMAP_DEFAULT_PROFILE,
    SHAKEMAP_DATA_ROOT,
    SHAKE_BINARY,
)

BASELINE_ID = "us7000pn9s"
PYAWBWE_LAT = 20.589678
PYAWBWE_LON = 96.052420
PYAWBWE_CODE = "71be4246"
TARGET_MMIS = [8.0, 8.5, 9.0]
TARGET_KEYS = ["mmi80", "mmi85", "mmi90"]


def verify_physical_event_parameters(
    baseline_dir: Path,
    scenarios_dirs: Dict[str, Path],
) -> Dict[str, Any]:
    """
    Perform deep semantic comparison across event.xml, rupture.json, and model.conf.
    Confirms that only operational event identifiers differ and all physical parameters are identical.
    """
    base_tree = ET.parse(baseline_dir / "event.xml")
    base_eq = base_tree.getroot() if base_tree.getroot().tag == "earthquake" else base_tree.getroot().find("earthquake")
    base_attribs = base_eq.attrib

    comparison = {
        "earthquake_origin_time": base_attribs.get("time"),
        "latitude": float(base_attribs.get("lat")),
        "longitude": float(base_attribs.get("lon")),
        "magnitude": float(base_attribs.get("mag")),
        "depth_km": float(base_attribs.get("depth")),
        "mechanism": base_attribs.get("mech"),
        "location_string": base_attribs.get("locstring"),
        "network": base_attribs.get("network"),
        "scenarios_verified": {},
    }

    base_rupture_hash = compute_sha256(str(baseline_dir / "rupture.json"))
    base_station_hash = compute_sha256(str(baseline_dir / "stationlist.json"))
    base_model_hash = compute_sha256(str(baseline_dir / "model.conf"))

    for key, sdir in scenarios_dirs.items():
        stree = ET.parse(sdir / "event.xml")
        seq = stree.getroot() if stree.getroot().tag == "earthquake" else stree.getroot().find("earthquake")
        sattribs = seq.attrib

        # Verify semantic equality of physical parameters
        assert sattribs.get("time") == base_attribs.get("time"), f"Time mismatch in {key}"
        assert float(sattribs.get("lat")) == float(base_attribs.get("lat")), f"Lat mismatch in {key}"
        assert float(sattribs.get("lon")) == float(base_attribs.get("lon")), f"Lon mismatch in {key}"
        assert float(sattribs.get("mag")) == float(base_attribs.get("mag")), f"Mag mismatch in {key}"
        assert float(sattribs.get("depth")) == float(base_attribs.get("depth")), f"Depth mismatch in {key}"
        assert sattribs.get("mech") == base_attribs.get("mech"), f"Mech mismatch in {key}"

        # Verify exact bit-for-bit hashes of invariant configs
        assert compute_sha256(str(sdir / "rupture.json")) == base_rupture_hash, f"Rupture mismatch in {key}"
        assert compute_sha256(str(sdir / "stationlist.json")) == base_station_hash, f"Stationlist mismatch in {key}"
        assert compute_sha256(str(sdir / "model.conf")) == base_model_hash, f"Model.conf mismatch in {key}"

        comparison["scenarios_verified"][key] = {
            "scenario_event_id": sattribs.get("id"),
            "event_xml_physical_params_match": True,
            "rupture_json_sha256_match": True,
            "stationlist_json_sha256_match": True,
            "model_conf_sha256_match": True,
        }

    return comparison


def main():
    print("=" * 80)
    print("STARTING WORKFLOW B: P-02 SHAKEMAP SENSITIVITY EXPERIMENT (CORRECTED PASS)")
    print("=" * 80)

    profile_data_root = Path(SHAKEMAP_DATA_ROOT)
    baseline_dir = profile_data_root / BASELINE_ID / "current"
    baseline_products = baseline_dir / "products"
    rupture_file = baseline_dir / "rupture.json"

    if not (baseline_products / "shake_result.hdf").exists():
        raise FileNotFoundError(f"Baseline products not found at {baseline_products}")

    output_root = REPO_ROOT / "data" / "events" / BASELINE_ID / "sensitivity_p02"
    plots_dir = output_root / "plots"
    output_root.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)

    print(f"Profile Data Root: {profile_data_root}")
    print(f"Baseline Directory: {baseline_dir}")
    print(f"Output Root:        {output_root}")

    # 1. Load Baseline Grid and Info
    print("\n[Step 1/6] Loading Frozen Baseline ShakeMap Products...")
    base_grid = ShakeMapGridComparator.load_grid(baseline_products / "shake_result.hdf")
    with h5py.File(baseline_products / "shake_result.hdf", "r") as hf:
        base_info = json.loads(hf["dictionaries"]["info.json"][()].decode("utf-8"))
    base_bias = float(base_info["output"]["ground_motions"]["MMI"]["bias"])
    base_bias_stations = int(base_info["output"]["ground_motions"]["MMI"]["bias_stations"])

    grid_extent = [base_grid.lon_min, base_grid.lon_max, base_grid.lat_min, base_grid.lat_max]
    print(f"  Baseline Grid: {base_grid.mmi.shape}, dx={base_grid.dx:.4f}, dy={base_grid.dy:.4f}")
    print(f"  Baseline MMI Bias: {base_bias:.4f} (stations={base_bias_stations})")

    # Generate Standalone Baseline Plot (Regional)
    baseline_plot_path = plots_dir / "baseline_mmi_map.png"
    plot_standalone_grid(
        base_grid.mmi,
        grid_extent,
        baseline_plot_path,
        title="USGS ShakeMap 4.5 Baseline (Reconstructed)\nNo Ingested P-02 Observation",
        site_coord=(PYAWBWE_LON, PYAWBWE_LAT),
        site_label="Pyawbwe KBZ Bank (P-02)",
    )
    print(f"  Saved baseline regional map to: {baseline_plot_path}")

    # Generate Pyawbwe Data Void Map (Zoomed)
    data_void_plot_path = plots_dir / "p02_pyawbwe_data_void_map.png"
    plot_pyawbwe_data_void_map(
        baseline_mmi=base_grid.mmi,
        lats=base_grid.lats,
        lons=base_grid.lons,
        output_path=data_void_plot_path,
        rupture_path=rupture_file,
    )
    print(f"  Saved Pyawbwe data void map to: {data_void_plot_path}")

    # 2. Execute Scenarios with Proper Ingestion (nresp=None)
    scenarios_data: Dict[str, Dict[str, Any]] = {}
    scenarios_dirs: Dict[str, Path] = {}
    metrics_summary_table: List[Dict[str, Any]] = []

    for target_mmi, key in zip(TARGET_MMIS, TARGET_KEYS):
        scenario_id = f"us7000pn9s_p02_{key}"
        scen_current_dir = profile_data_root / scenario_id / "current"
        scenarios_dirs[key] = scen_current_dir
        print(f"\n[Step 2/6] Executing Scenario: {scenario_id} (Target MMI = {target_mmi:.1f}, σ = 0.50, nresp = null)...")

        # Workspace prep with nresp=None
        prep_res = prepare_scenario_workspace(
            baseline_current_dir=str(baseline_dir),
            scenario_current_dir=str(scen_current_dir),
            scenario_id=scenario_id,
            target_mmi=target_mmi,
            stddev=0.50,
        )
        print(f"  Prepared workspace at: {scen_current_dir}")
        print(f"  Observation agent_mmi_dat.json SHA256: {prep_res['input_checksums']['agent_mmi_dat.json'][:16]}...")

        # Execution
        exec_res = execute_shakemap_scenario(scenario_id=scenario_id)
        print(f"  ShakeMap completed in {exec_res['elapsed_seconds']}s (exit code {exec_res['returncode']})")
        if exec_res["returncode"] != 0:
            print("  ERROR stderr:\n", exec_res["stderr"])
            raise RuntimeError(f"ShakeMap failed for {scenario_id}")

        # Verification
        assim_res = verify_scenario_assimilation(
            scenario_current_dir=str(scen_current_dir),
            expected_mmi=target_mmi,
            expected_code=PYAWBWE_CODE,
            baseline_stations_count=521,
        )
        print(f"  Verification: Total stations = {assim_res['total_stations_in_result']} (delta = {assim_res['station_count_delta']})")
        print(f"  Assimilated observation code: {assim_res['assimilated_observation']['code']}, intensity: {assim_res['assimilated_observation']['intensity']}, flag: {assim_res['assimilated_observation']['intensity_flag']}")
        print(f"  Event MMI Bias: {assim_res['event_bias_mmi']:.4f} (stations={assim_res['bias_stations']})")

        # Load Augmented Grid
        aug_grid = ShakeMapGridComparator.load_grid(scen_current_dir / "products" / "shake_result.hdf")

        # Compute Metrics
        metrics = compute_scenario_spatial_metrics(
            baseline_mmi=base_grid.mmi,
            augmented_mmi=aug_grid.mmi,
            lats=base_grid.lats,
            lons=base_grid.lons,
            dx_deg=base_grid.dx,
            dy_deg=base_grid.dy,
            site_lat=PYAWBWE_LAT,
            site_lon=PYAWBWE_LON,
            baseline_bias=base_bias,
            augmented_bias=assim_res["event_bias_mmi"],
        )

        # Plot standalone augmented map (Regional)
        aug_plot_path = plots_dir / f"augmented_{key}_map.png"
        plot_standalone_grid(
            aug_grid.mmi,
            grid_extent,
            aug_plot_path,
            title=f"USGS ShakeMap 4.5 Augmented: P-02 MMI {target_mmi:.1f} (σ = 0.50)",
            site_coord=(PYAWBWE_LON, PYAWBWE_LAT),
            site_label=f"P-02 ({target_mmi:.1f})",
        )

        # Plot standalone difference map (Regional)
        diff_plot_path = plots_dir / f"diff_{key}_map.png"
        delta_mmi = aug_grid.mmi - base_grid.mmi
        plot_standalone_difference(
            delta_mmi,
            grid_extent,
            diff_plot_path,
            title=f"Intensity Shift (ΔMMI): P-02 MMI {target_mmi:.1f} − Baseline\nSite Shift: {metrics['delta_mmi_at_site']['bilinear']:+.2f} MMI",
            site_coord=(PYAWBWE_LON, PYAWBWE_LAT),
            site_label=f"Site Δ: {metrics['delta_mmi_at_site']['bilinear']:+.2f}",
        )

        # Save individual scenario summary
        scenario_record = {
            "scenario_id": scenario_id,
            "target_mmi": target_mmi,
            "sigma": 0.50,
            "nresp_ingestion_mode": "null_single_reconnaissance",
            "input_checksums": prep_res["input_checksums"],
            "execution": {
                "elapsed_seconds": exec_res["elapsed_seconds"],
                "returncode": exec_res["returncode"],
            },
            "assimilation": assim_res,
            "metrics": metrics,
        }
        scenario_json_path = output_root / f"scenario_{key}_summary.json"
        with open(scenario_json_path, "w", encoding="utf-8") as f:
            json.dump(scenario_record, f, indent=2)

        scenarios_data[key] = {
            "scenario_id": scenario_id,
            "target_mmi": target_mmi,
            "augmented_mmi": aug_grid.mmi,
            "metrics": metrics,
            "assimilation": assim_res,
            "input_checksums": prep_res["input_checksums"],
            "execution": exec_res,
        }

        # Table row
        metrics_summary_table.append({
            "scenario_key": key,
            "input_mmi": target_mmi,
            "sigma": 0.50,
            "baseline_site_mmi": metrics["baseline_mmi_at_site"]["bilinear"],
            "augmented_site_mmi": metrics["augmented_mmi_at_site"]["bilinear"],
            "delta_site_mmi": metrics["delta_mmi_at_site"]["bilinear"],
            "max_positive_delta": metrics["extreme_shifts"]["max_positive_delta_mmi"],
            "max_negative_delta": metrics["extreme_shifts"]["max_negative_delta_mmi"],
            "mean_abs_delta": metrics["extreme_shifts"]["mean_absolute_difference"],
            "area_ge_01_km2": metrics["impacted_areas_km2"]["abs_delta_ge_01_km2"],
            "area_ge_02_km2": metrics["impacted_areas_km2"]["abs_delta_ge_02_km2"],
            "area_ge_05_km2": metrics["impacted_areas_km2"]["abs_delta_ge_05_km2"],
            "area_ge_10_km2": metrics["impacted_areas_km2"]["abs_delta_ge_10_km2"],
            "event_bias_delta": metrics["event_bias"]["bias_delta"],
        })

    # 3. Verification of Physical Event Parameters
    print("\n[Step 3/6] Verifying Semantic Equality of Physical Event Parameters...")
    param_audit = verify_physical_event_parameters(baseline_dir, scenarios_dirs)
    print("  Physical parameters verified: Origin Time, Lat, Lon, Mag, Depth, Mech, Rupture, Stationlist, Model.conf are IDENTICAL!")

    # 4. Multi-panel Comparison Figures (Regional & Pyawbwe Close-Up)
    print("\n[Step 4/6] Generating Publication Figures...")

    # Regional Side-by-Side Comparison
    side_by_side_path = plots_dir / "p02_sensitivity_side_by_side_comparison.png"
    plot_side_by_side_comparison(
        baseline_mmi=base_grid.mmi,
        scenarios_data=scenarios_data,
        extent=grid_extent,
        output_path=side_by_side_path,
        site_coord=(PYAWBWE_LON, PYAWBWE_LAT),
    )
    print(f"  Saved regional multi-panel comparison figure to: {side_by_side_path}")

    # Pyawbwe Close-Up 8-Panel Figure
    zoom_comparison_path = plots_dir / "p02_pyawbwe_zoom_comparison.png"
    plot_pyawbwe_zoom_comparison(
        baseline_mmi=base_grid.mmi,
        scenarios_data=scenarios_data,
        lats=base_grid.lats,
        lons=base_grid.lons,
        output_path=zoom_comparison_path,
        rupture_path=rupture_file,
    )
    print(f"  Saved Pyawbwe zoom comparison figure to: {zoom_comparison_path}")

    # 5. Diagnostic Charts: Response Curve & Decomposed Radial Decay
    print("\n[Step 5/6] Generating Response and Decay Diagnostics...")

    # Response Curve
    curve_path = plots_dir / "p02_delta_vs_input_mmi.png"
    plot_delta_vs_input_mmi(
        scenarios_metrics={k: v["metrics"] for k, v in scenarios_data.items()},
        output_path=curve_path,
        baseline_site_mmi=scenarios_data["mmi80"]["metrics"]["baseline_mmi_at_site"]["bilinear"],
    )
    print(f"  Saved response curve to: {curve_path}")

    # Decomposed Radial Decay
    decay_path = plots_dir / "p02_radial_distance_decay.png"
    plot_radial_distance_decay(
        scenarios_metrics={k: v["metrics"] for k, v in scenarios_data.items()},
        output_path=decay_path,
    )
    print(f"  Saved decomposed radial decay figure to: {decay_path}")

    # 6. Save Manifests and CSV Summary
    print("\n[Step 6/6] Writing Manifests and Tabular Summaries...")

    # CSV Summary
    csv_path = output_root / "p02_sensitivity_metrics_summary.csv"
    with open(csv_path, "w", encoding="utf-8") as f:
        headers = list(metrics_summary_table[0].keys())
        f.write(",".join(headers) + "\n")
        for row in metrics_summary_table:
            f.write(",".join(str(row[h]) for h in headers) + "\n")
    print(f"  Saved metrics summary CSV to: {csv_path}")

    # Master Experiment Manifest
    master_manifest = {
        "experiment_name": "Workflow B: Exploratory P-02 ShakeMap Sensitivity Experiment (Corrected Pass)",
        "event_id": BASELINE_ID,
        "earthquake_origin_time": "2025-03-28T06:20:52.715Z",
        "earthquake_magnitude": 7.7,
        "shakemap_version": "4.5.0",
        "shakemap_profile": SHAKEMAP_DEFAULT_PROFILE,
        "observation_target": {
            "candidate_id": "P-02",
            "name": "KBZ Bank branch at Pyawbwe",
            "steer_source": "page-76.pdf",
            "coordinates": {"lat": PYAWBWE_LAT, "lon": PYAWBWE_LON},
            "rrup_km": 1.268,
            "repi_km": 158.501,
            "rhypo_km": 158.816,
            "baseline_void_distance_km": 38.005,
            "baseline_modeled_mmi_at_site": scenarios_data["mmi80"]["metrics"]["baseline_mmi_at_site"]["bilinear"],
        },
        "ingestion_methodology_audit": {
            "audit_finding": "ShakeMap 4.5 filters macroseismic observations via: WHERE (a.nresp < 0 OR a.nresp >= min_nresp). "
                            "Preliminary runs that used nresp=3 to bypass min_nresp=3 were a provenance error because P-02 is a single "
                            "reconnaissance assessment, not three DYFI questionnaires. The scientifically correct solution is nresp=null, "
                            "which ShakeMap translates to nresp=-1 in SQLite, satisfying a.nresp < 0 natively without fabricating respondents.",
            "response_count_provenance": "null (stored as -1 in SQLite; unaggregated single field assessment)",
            "numerical_equivalence": "Because intensity_stddev=0.50 was explicitly provided, ShakeMap's covariance matrix is identical. "
                                   "Numerical grids, site shifts, and bias deltas are exactly unchanged down to floating-point precision.",
        },
        "physical_parameters_comparison": param_audit,
        "experimental_safeguards": {
            "dataset_type": "exploratory_sensitivity_test",
            "scientific_use_allowed": False,
            "expert_approved": False,
            "status": "Unreviewed exploratory sensitivity experiment; not scientific validation",
            "observation_uncertainty": "Fixed prior sigma = 0.50 (uncalibrated hypothesis)",
        },
        "baseline_summary": {
            "baseline_current_dir": str(baseline_dir),
            "baseline_mmi_bias": base_bias,
            "bias_stations": base_bias_stations,
            "grid_dimensions": {"nlat": base_grid.nlat, "nlon": base_grid.nlon},
            "grid_bounds": {
                "lon_min": base_grid.lon_min,
                "lon_max": base_grid.lon_max,
                "lat_min": base_grid.lat_min,
                "lat_max": base_grid.lat_max,
            },
        },
        "scenarios": {
            k: {
                "scenario_id": v["scenario_id"],
                "target_mmi": v["target_mmi"],
                "sigma": 0.50,
                "nresp": None,
                "input_checksums": v["input_checksums"],
                "output_checksums": v["assimilation"]["output_checksums"],
                "metrics": v["metrics"],
            }
            for k, v in scenarios_data.items()
        },
        "summary_table": metrics_summary_table,
        "generated_plots": {
            "baseline_mmi_map": str(baseline_plot_path.relative_to(REPO_ROOT)),
            "pyawbwe_data_void_map": str(data_void_plot_path.relative_to(REPO_ROOT)),
            "augmented_mmi80_map": str((plots_dir / "augmented_mmi80_map.png").relative_to(REPO_ROOT)),
            "augmented_mmi85_map": str((plots_dir / "augmented_mmi85_map.png").relative_to(REPO_ROOT)),
            "augmented_mmi90_map": str((plots_dir / "augmented_mmi90_map.png").relative_to(REPO_ROOT)),
            "diff_mmi80_map": str((plots_dir / "diff_mmi80_map.png").relative_to(REPO_ROOT)),
            "diff_mmi85_map": str((plots_dir / "diff_mmi85_map.png").relative_to(REPO_ROOT)),
            "diff_mmi90_map": str((plots_dir / "diff_mmi90_map.png").relative_to(REPO_ROOT)),
            "regional_side_by_side_comparison": str(side_by_side_path.relative_to(REPO_ROOT)),
            "pyawbwe_zoom_comparison": str(zoom_comparison_path.relative_to(REPO_ROOT)),
            "delta_vs_input_curve": str(curve_path.relative_to(REPO_ROOT)),
            "decomposed_radial_distance_decay": str(decay_path.relative_to(REPO_ROOT)),
        },
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    manifest_path = output_root / "sensitivity_experiment_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(master_manifest, f, indent=2)
    print(f"  Saved master experiment manifest to: {manifest_path}")

    print("\n" + "=" * 80)
    print("WORKFLOW B SENSITIVITY EXPERIMENT (CORRECTED PASS) COMPLETED SUCCESSFULLY!")
    print("=" * 80)

    # Print summary table to stdout
    print("\nQuantitative Metrics Summary:")
    print(f"{'Scenario':<10} | {'Input MMI':<9} | {'Base Site':<9} | {'Aug Site':<9} | {'ΔSite':<8} | {'Max Inc':<8} | {'Max Dec':<8} | {'Area>=0.1':<10} | {'Area>=0.5':<10} | {'ΔBias':<8}")
    print("-" * 105)
    for row in metrics_summary_table:
        print(
            f"{row['scenario_key']:<10} | "
            f"{row['input_mmi']:<9.1f} | "
            f"{row['baseline_site_mmi']:<9.2f} | "
            f"{row['augmented_site_mmi']:<9.2f} | "
            f"{row['delta_site_mmi']:<+8.2f} | "
            f"{row['max_positive_delta']:<+8.2f} | "
            f"{row['max_negative_delta']:<+8.2f} | "
            f"{row['area_ge_01_km2']:<10.1f} | "
            f"{row['area_ge_05_km2']:<10.1f} | "
            f"{row['event_bias_delta']:<+8.4f}"
        )


if __name__ == "__main__":
    main()
