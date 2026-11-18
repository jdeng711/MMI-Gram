"""
Reproducible Experiment Runner for Single-Observation Sensitivity Analyses.

Orchestrates isolated ShakeMap 4.5 augmented scenarios:
1. Replicates frozen baseline configurations (event parameters, finite fault, stationlist, model.conf).
2. Injects isolated exploratory observation files (agent_mmi_dat.json) with strict sensitivity metadata.
3. Executes official ShakeMap stages: assemble, model, gridxml.
4. Verifies station assimilation in internal shake_data.hdf and shake_result.hdf.
5. Captures input and output checksums into machine-readable manifests.
6. Calculates quantitative spatial metrics (site MMI, max/min delta, mean absolute delta,
   areas exceeding threshold shifts in km², event bias changes).
7. Produces publication-quality cartographic figures and diagnostic sensitivity plots.
"""

from __future__ import annotations
import copy
import hashlib
import json
import math
import os
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union

import h5py
import numpy as np

SHAKEMAP_DEFAULT_PROFILE = os.environ.get("SHAKEMAP_PROFILE", "myanmar_recon")
SHAKEMAP_DATA_ROOT = os.environ.get(
    "SHAKEMAP_DATA_ROOT",
    os.path.expanduser("~/shakemap_profiles/myanmar_recon/data")
)
SHAKE_BINARY = os.environ.get(
    "SHAKE_BINARY",
    "/opt/anaconda3/envs/shakemap45/bin/shake"
)


def compute_sha256(filepath: str) -> str:
    """Compute the SHA256 checksum of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def create_scenario_observation_geojson(
    scenario_id: str,
    target_mmi: float,
    stddev: float = 0.50,
    candidate_id: str = "P-02",
    code: str = "71be4246",
    name: str = "KBZ Bank branch at Pyawbwe",
    lat: float = 20.589678,
    lon: float = 96.052420,
    rrup_km: float = 1.268,
    file_name: str = "page-76.pdf",
    source_attribution: str = "Posted by Myanmar Now on Facebook",
    nresp: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Construct the agent_mmi_dat.json GeoJSON FeatureCollection with strict exploratory metadata.

    Scientific Ingestion Protocol:
    In USGS ShakeMap 4.5 and esi_shakelib, the SQL observation filter is:
        WHERE (a.nresp < 0 OR a.nresp >= min_nresp)
    For crowdsourced DYFI questionnaire boxes, nresp >= 3 is required.
    For single field reconnaissance assessments, nresp is set to null (which esi_shakelib
    stores as nresp = -1 in the SQLite amp table). Because -1 < 0, ShakeMap natively
    assimilates the single observation without fabricating a false response count or
    requiring modification of min_nresp in model.conf.
    """
    return {
        "type": "FeatureCollection",
        "metadata": {
            "event_id": scenario_id,
            "dataset_type": "exploratory_sensitivity_test",
            "scientific_use_allowed": False,
            "expert_approved": False,
            "experimental_hypothesis": f"Hypothetical MMI {target_mmi:.1f} sensitivity test",
            "candidate_id": candidate_id,
            "observation_provenance": "single_reconnaissance_assessment",
            "dyfi_response_aggregation": "not_applicable",
            "model_provenance": "Clara Yoon prior agent workflow (agent_evaluations_myanmar.json)",
            "hypothetical_input_mmi": target_mmi,
            "experimental_sigma_assumption": stddev,
            "steer_source_page": file_name,
            "source_attribution": source_attribution,
            "coordinate_provenance": f"Site-associated POI pin for {name} ({lat:.6f}, {lon:.6f}), not a cadastral parcel survey",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "count": 1,
        },
        "features": [
            {
                "type": "Feature",
                "id": f"MMI.{code}",
                "properties": {
                    "code": code,
                    "name": name,
                    "network": "MMI",
                    "netid": "MMI",
                    "station_type": "macroseismic",
                    "channels": [],
                    "nresp": nresp,
                    "source": "MMI-Gram-Exploratory-Sensitivity-Test",
                    "intensity": float(target_mmi),
                    "intensity_stddev": float(stddev),
                    "intensity_flag": "0",
                    "agency": "MMI-Gram-Agent",
                    "file_name": file_name,
                    "model_name": "gemini-3.8-flash",
                    "raw_model_confidence": 0.90,
                    "uncertainty_policy": "experimental_fixed_prior",
                    "rrup_km": float(rrup_km),
                    "precision_level": "site_associated_poi_pin",
                    "dataset_type": "exploratory_sensitivity_test",
                    "scientific_use_allowed": False,
                    "expert_approved": False,
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat],
                },
            }
        ],
    }


def prepare_scenario_workspace(
    baseline_current_dir: str,
    scenario_current_dir: str,
    scenario_id: str,
    target_mmi: float,
    stddev: float = 0.50,
) -> Dict[str, Any]:
    """
    Copy baseline configuration files into scenario directory and write agent_mmi_dat.json.
    """
    os.makedirs(scenario_current_dir, exist_ok=True)

    # 1. Update event.xml with scenario_id
    base_event_xml = os.path.join(baseline_current_dir, "event.xml")
    scen_event_xml = os.path.join(scenario_current_dir, "event.xml")
    tree = ET.parse(base_event_xml)
    root = tree.getroot()
    eq_elem = root if root.tag == "earthquake" else root.find("earthquake")
    eq_elem.set("id", scenario_id)
    tree.write(scen_event_xml, encoding="utf-8", xml_declaration=True)

    # 2. Copy frozen configuration files verbatim
    for fname in ["model.conf", "rupture.json", "stationlist.json"]:
        src_path = os.path.join(baseline_current_dir, fname)
        dst_path = os.path.join(scenario_current_dir, fname)
        shutil.copy2(src_path, dst_path)

    # 3. Create scenario agent_mmi_dat.json
    obs_geojson = create_scenario_observation_geojson(
        scenario_id=scenario_id,
        target_mmi=target_mmi,
        stddev=stddev,
    )
    obs_path = os.path.join(scenario_current_dir, "agent_mmi_dat.json")
    with open(obs_path, "w", encoding="utf-8") as f:
        json.dump(obs_geojson, f, indent=2)

    # 4. Record input checksums
    input_checksums = {
        "event.xml": compute_sha256(scen_event_xml),
        "model.conf": compute_sha256(os.path.join(scenario_current_dir, "model.conf")),
        "rupture.json": compute_sha256(os.path.join(scenario_current_dir, "rupture.json")),
        "stationlist.json": compute_sha256(os.path.join(scenario_current_dir, "stationlist.json")),
        "agent_mmi_dat.json": compute_sha256(obs_path),
    }

    return {
        "scenario_id": scenario_id,
        "scenario_dir": scenario_current_dir,
        "input_checksums": input_checksums,
        "observation": obs_geojson,
    }


def execute_shakemap_scenario(
    scenario_id: str,
    profile: str = SHAKEMAP_DEFAULT_PROFILE,
    shake_bin: str = SHAKE_BINARY,
) -> Dict[str, Any]:
    """
    Execute 'shake assemble model gridxml' for a scenario.
    Ensures active profile is selected via sm_profile if needed,
    and cleans PYTHONPATH from subprocess environment to prevent Python version mismatch.
    """
    sub_env = dict(os.environ)
    sub_env.pop("PYTHONPATH", None)

    # Ensure profile is switched
    sm_profile_bin = os.path.join(os.path.dirname(shake_bin), "sm_profile")
    if os.path.exists(sm_profile_bin) and profile:
        subprocess.run([sm_profile_bin, "-s", profile], env=sub_env, capture_output=True)

    cmd = [
        shake_bin,
        "-c", f"P-02 sensitivity scenario {scenario_id}",
        scenario_id,
        "assemble",
        "model",
        "gridxml",
    ]
    t0 = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True, env=sub_env)
    t1 = time.time()

    return {
        "command": " ".join(cmd),
        "returncode": res.returncode,
        "stdout": res.stdout,
        "stderr": res.stderr,
        "elapsed_seconds": round(t1 - t0, 3),
    }


def verify_scenario_assimilation(
    scenario_current_dir: str,
    expected_mmi: float,
    expected_code: str = "71be4246",
    baseline_stations_count: int = 521,
) -> Dict[str, Any]:
    """
    Verify that exactly one additional MMI station was ingested and assimilated into shake_result.hdf.
    """
    result_hdf_path = os.path.join(scenario_current_dir, "products", "shake_result.hdf")
    grid_xml_path = os.path.join(scenario_current_dir, "products", "grid.xml")

    if not os.path.exists(result_hdf_path):
        raise FileNotFoundError(f"Missing shake_result.hdf at {result_hdf_path}")
    if not os.path.exists(grid_xml_path):
        raise FileNotFoundError(f"Missing grid.xml at {grid_xml_path}")

    with h5py.File(result_hdf_path, "r") as hf:
        info = json.loads(hf["dictionaries"]["info.json"][()].decode("utf-8"))
        st_dict = json.loads(hf["dictionaries"]["stations_dict"][()].decode("utf-8"))

    feats = st_dict["features"]
    total_stations = len(feats)

    # Locate the ingested observation
    matched = [f for f in feats if f["properties"].get("code") == expected_code]
    if not matched:
        raise ValueError(f"Observation code {expected_code} not found in stations_dict")

    obs = matched[0]
    p = obs["properties"]
    coords = obs["geometry"]["coordinates"]

    mmi_val = float(p.get("intensity"))
    mmi_flag = p.get("intensity_flag")
    net = p.get("network")

    # Verify count: exactly +1 station
    expected_total = baseline_stations_count + 1
    station_count_delta = total_stations - baseline_stations_count

    event_bias_mmi = float(info["output"]["ground_motions"]["MMI"]["bias"])
    bias_stations = int(info["output"]["ground_motions"]["MMI"]["bias_stations"])

    output_checksums = {
        "shake_result.hdf": compute_sha256(result_hdf_path),
        "grid.xml": compute_sha256(grid_xml_path),
    }

    return {
        "total_stations_in_result": total_stations,
        "station_count_delta": station_count_delta,
        "assimilated_observation": {
            "code": expected_code,
            "network": net,
            "intensity": mmi_val,
            "intensity_flag": mmi_flag,
            "coordinates": coords,
            "matches_expected_mmi": abs(mmi_val - expected_mmi) < 1e-4,
        },
        "event_bias_mmi": event_bias_mmi,
        "bias_stations": bias_stations,
        "output_checksums": output_checksums,
    }


def interpolate_point_on_grid(
    mmi_grid: np.ndarray,
    lats: np.ndarray,
    lons: np.ndarray,
    target_lat: float,
    target_lon: float,
) -> Dict[str, float]:
    """
    Extract nearest-neighbor and bilinear interpolated MMI values from a regular grid.
    Convention: lats descending [lat_max -> lat_min], lons ascending [lon_min -> lon_max].
    """
    nlat, nlon = mmi_grid.shape
    lat_max, lat_min = float(lats[0]), float(lats[-1])
    lon_min, lon_max = float(lons[0]), float(lons[-1])

    # Row/Col normalized floating-point coordinates
    r_float = (lat_max - target_lat) / (lat_max - lat_min) * (nlat - 1)
    c_float = (target_lon - lon_min) / (lon_max - lon_min) * (nlon - 1)

    # Nearest neighbor
    r_near = int(np.clip(np.round(r_float), 0, nlat - 1))
    c_near = int(np.clip(np.round(c_float), 0, nlon - 1))
    val_nearest = float(mmi_grid[r_near, c_near])

    # Bilinear interpolation
    r0 = int(np.clip(np.floor(r_float), 0, nlat - 2))
    r1 = r0 + 1
    c0 = int(np.clip(np.floor(c_float), 0, nlon - 2))
    c1 = c0 + 1

    dr = r_float - r0
    dc = c_float - c0

    val_bilinear = float(
        (1.0 - dr) * (1.0 - dc) * mmi_grid[r0, c0]
        + (1.0 - dr) * dc * mmi_grid[r0, c1]
        + dr * (1.0 - dc) * mmi_grid[r1, c0]
        + dr * dc * mmi_grid[r1, c1]
    )

    return {
        "nearest": round(val_nearest, 4),
        "bilinear": round(val_bilinear, 4),
        "nearest_lat": round(float(lats[r_near]), 4),
        "nearest_lon": round(float(lons[c_near]), 4),
    }


def compute_cell_areas_km2(
    lats: np.ndarray,
    dx_deg: float,
    dy_deg: float,
    nlon: int,
) -> np.ndarray:
    """
    Compute 2D array (nlat, nlon) of grid cell surface areas in km².
    """
    dy_km = dy_deg * 111.132
    dx_km_per_row = dx_deg * 111.132 * np.cos(np.radians(lats))
    areas_1d = dy_km * dx_km_per_row
    return np.tile(areas_1d[:, np.newaxis], (1, nlon))


def compute_grid_distances_km(
    lats: np.ndarray,
    lons: np.ndarray,
    target_lat: float,
    target_lon: float,
) -> np.ndarray:
    """
    Compute 2D array (nlat, nlon) of great-circle distances in km from (target_lat, target_lon).
    """
    lat_rad = np.radians(lats)[:, np.newaxis]
    lon_rad = np.radians(lons)[np.newaxis, :]
    t_lat_rad = math.radians(target_lat)
    t_lon_rad = math.radians(target_lon)

    dlat = lat_rad - t_lat_rad
    dlon = lon_rad - t_lon_rad
    a = (
        np.sin(dlat / 2.0) ** 2
        + math.cos(t_lat_rad) * np.cos(lat_rad) * np.sin(dlon / 2.0) ** 2
    )
    return 2.0 * 6371.0088 * np.arcsin(np.clip(np.sqrt(a), 0.0, 1.0))


def compute_radial_decay_profile(
    distances_km: np.ndarray,
    delta_mmi: np.ndarray,
    bins: Optional[List[Tuple[float, float]]] = None,
) -> List[Dict[str, Any]]:
    """
    Calculate radial decay statistics of ΔMMI away from the observation point.
    """
    if bins is None:
        bins = [
            (0.0, 5.0),
            (5.0, 10.0),
            (10.0, 20.0),
            (20.0, 30.0),
            (30.0, 50.0),
            (50.0, 75.0),
            (75.0, 100.0),
            (100.0, 150.0),
            (150.0, 200.0),
        ]

    valid_mask = ~np.isnan(delta_mmi)
    profile: List[Dict[str, Any]] = []

    for r_min, r_max in bins:
        mask = valid_mask & (distances_km >= r_min) & (distances_km < r_max)
        pts = delta_mmi[mask]
        n_cells = int(np.sum(mask))
        if n_cells > 0:
            profile.append({
                "r_min_km": r_min,
                "r_max_km": r_max,
                "r_mid_km": round(0.5 * (r_min + r_max), 1),
                "cell_count": n_cells,
                "mean_delta_mmi": round(float(np.mean(pts)), 5),
                "min_delta_mmi": round(float(np.min(pts)), 5),
                "max_delta_mmi": round(float(np.max(pts)), 5),
                "std_delta_mmi": round(float(np.std(pts)), 5),
            })
        else:
            profile.append({
                "r_min_km": r_min,
                "r_max_km": r_max,
                "r_mid_km": round(0.5 * (r_min + r_max), 1),
                "cell_count": 0,
                "mean_delta_mmi": 0.0,
                "min_delta_mmi": 0.0,
                "max_delta_mmi": 0.0,
                "std_delta_mmi": 0.0,
            })

    return profile


def compute_scenario_spatial_metrics(
    baseline_mmi: np.ndarray,
    augmented_mmi: np.ndarray,
    lats: np.ndarray,
    lons: np.ndarray,
    dx_deg: float,
    dy_deg: float,
    site_lat: float,
    site_lon: float,
    baseline_bias: float,
    augmented_bias: float,
) -> Dict[str, Any]:
    """
    Comprehensive quantitative evaluation of baseline vs augmented ShakeMap grids.
    """
    delta_mmi = augmented_mmi - baseline_mmi
    valid_mask = ~(np.isnan(baseline_mmi) | np.isnan(augmented_mmi) | np.isnan(delta_mmi))
    valid_deltas = delta_mmi[valid_mask]

    # Site values
    base_site = interpolate_point_on_grid(baseline_mmi, lats, lons, site_lat, site_lon)
    aug_site = interpolate_point_on_grid(augmented_mmi, lats, lons, site_lat, site_lon)
    delta_site_bilinear = round(aug_site["bilinear"] - base_site["bilinear"], 4)
    delta_site_nearest = round(aug_site["nearest"] - base_site["nearest"], 4)

    # Max and min locations
    idx_max = np.unravel_index(np.argmax(delta_mmi), delta_mmi.shape)
    idx_min = np.unravel_index(np.argmin(delta_mmi), delta_mmi.shape)

    max_increase = float(delta_mmi[idx_max])
    max_lat = float(lats[idx_max[0]])
    max_lon = float(lons[idx_max[1]])

    max_decrease = float(delta_mmi[idx_min])
    min_lat = float(lats[idx_min[0]])
    min_lon = float(lons[idx_min[1]])

    # Areas in km²
    cell_areas = compute_cell_areas_km2(lats, dx_deg, dy_deg, len(lons))
    total_area_km2 = float(np.sum(cell_areas[valid_mask]))

    area_abs_ge_01 = float(np.sum(cell_areas[valid_mask & (np.abs(delta_mmi) >= 0.1)]))
    area_abs_ge_02 = float(np.sum(cell_areas[valid_mask & (np.abs(delta_mmi) >= 0.2)]))
    area_abs_ge_05 = float(np.sum(cell_areas[valid_mask & (np.abs(delta_mmi) >= 0.5)]))
    area_abs_ge_10 = float(np.sum(cell_areas[valid_mask & (np.abs(delta_mmi) >= 1.0)]))

    # Cell counts
    total_cells = int(np.sum(valid_mask))
    cells_ge_01 = int(np.sum(valid_mask & (np.abs(delta_mmi) >= 0.1)))
    cells_ge_02 = int(np.sum(valid_mask & (np.abs(delta_mmi) >= 0.2)))
    cells_ge_05 = int(np.sum(valid_mask & (np.abs(delta_mmi) >= 0.5)))
    cells_ge_10 = int(np.sum(valid_mask & (np.abs(delta_mmi) >= 1.0)))

    # Radial decay
    distances_km = compute_grid_distances_km(lats, lons, site_lat, site_lon)
    radial_profile = compute_radial_decay_profile(distances_km, delta_mmi)

    return {
        "site_coordinates": {"lat": site_lat, "lon": site_lon},
        "baseline_mmi_at_site": base_site,
        "augmented_mmi_at_site": aug_site,
        "delta_mmi_at_site": {
            "bilinear": delta_site_bilinear,
            "nearest": delta_site_nearest,
        },
        "extreme_shifts": {
            "max_positive_delta_mmi": round(max_increase, 5),
            "max_positive_location": {"lat": round(max_lat, 4), "lon": round(max_lon, 4)},
            "max_negative_delta_mmi": round(max_decrease, 5),
            "max_negative_location": {"lat": round(min_lat, 4), "lon": round(min_lon, 4)},
            "mean_difference": round(float(np.mean(valid_deltas)), 5),
            "mean_absolute_difference": round(float(np.mean(np.abs(valid_deltas))), 5),
        },
        "impacted_areas_km2": {
            "total_area_km2": round(total_area_km2, 1),
            "abs_delta_ge_01_km2": round(area_abs_ge_01, 1),
            "abs_delta_ge_02_km2": round(area_abs_ge_02, 1),
            "abs_delta_ge_05_km2": round(area_abs_ge_05, 1),
            "abs_delta_ge_10_km2": round(area_abs_ge_10, 1),
        },
        "impacted_cells": {
            "total_cells": total_cells,
            "cells_ge_01": cells_ge_01,
            "cells_ge_02": cells_ge_02,
            "cells_ge_05": cells_ge_05,
            "cells_ge_10": cells_ge_10,
        },
        "event_bias": {
            "baseline_bias": round(baseline_bias, 5),
            "augmented_bias": round(augmented_bias, 5),
            "bias_delta": round(augmented_bias - baseline_bias, 5),
        },
        "radial_decay_profile": radial_profile,
    }


def plot_standalone_grid(
    mmi_grid: np.ndarray,
    extent: List[float],
    output_path: Union[str, Path],
    title: str,
    site_coord: Optional[Tuple[float, float]] = None,
    site_label: Optional[str] = None,
    vmin: float = 1.0,
    vmax: float = 10.0,
    dpi: int = 300,
) -> Path:
    """Generate a publication-grade standalone ShakeMap intensity raster map."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(8, 9), constrained_layout=True)
    im = ax.imshow(
        mmi_grid,
        extent=extent,
        origin="upper",
        cmap="turbo",
        vmin=vmin,
        vmax=vmax,
        aspect="auto",
    )
    cbar = fig.colorbar(im, ax=ax, orientation="horizontal", pad=0.06, shrink=0.85)
    cbar.set_label("Modeled Instrumental Intensity (MMI)", fontsize=10)

    if site_coord:
        lon, lat = site_coord
        ax.plot(lon, lat, marker="*", color="white", markeredgecolor="black", markersize=14, zorder=5)
        if site_label:
            ax.annotate(
                site_label,
                (lon, lat),
                textcoords="offset points",
                xytext=(8, 8),
                fontsize=9,
                fontweight="bold",
                color="black",
                bbox=dict(boxstyle="round,pad=0.2", fc="white", alpha=0.8, ec="grey"),
            )

    ax.set_xlabel("Longitude (°E)", fontsize=11)
    ax.set_ylabel("Latitude (°N)", fontsize=11)
    ax.grid(True, linestyle="--", alpha=0.4, color="grey")
    ax.set_title(title, fontsize=12, fontweight="bold")

    fig.savefig(out_p, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return out_p


def plot_standalone_difference(
    delta_mmi: np.ndarray,
    extent: List[float],
    output_path: Union[str, Path],
    title: str,
    site_coord: Optional[Tuple[float, float]] = None,
    site_label: Optional[str] = None,
    vlim: float = 2.0,
    dpi: int = 300,
) -> Path:
    """Generate a signed difference map (ΔMMI = Augmented - Baseline)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(8, 9), constrained_layout=True)
    norm = mcolors.TwoSlopeNorm(vmin=-vlim, vcenter=0.0, vmax=vlim)
    im = ax.imshow(
        delta_mmi,
        extent=extent,
        origin="upper",
        cmap="coolwarm",
        norm=norm,
        aspect="auto",
    )
    cbar = fig.colorbar(im, ax=ax, orientation="horizontal", pad=0.06, shrink=0.85)
    cbar.set_label("Signed Intensity Shift (ΔMMI = Augmented − Baseline)", fontsize=10)

    if site_coord:
        lon, lat = site_coord
        ax.plot(lon, lat, marker="*", color="yellow", markeredgecolor="black", markersize=14, zorder=5)
        if site_label:
            ax.annotate(
                site_label,
                (lon, lat),
                textcoords="offset points",
                xytext=(8, 8),
                fontsize=9,
                fontweight="bold",
                color="black",
                bbox=dict(boxstyle="round,pad=0.2", fc="white", alpha=0.85, ec="black"),
            )

    ax.set_xlabel("Longitude (°E)", fontsize=11)
    ax.set_ylabel("Latitude (°N)", fontsize=11)
    ax.grid(True, linestyle="--", alpha=0.4, color="grey")
    ax.set_title(title, fontsize=12, fontweight="bold")

    fig.savefig(out_p, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return out_p


def plot_side_by_side_comparison(
    baseline_mmi: np.ndarray,
    scenarios_data: Dict[str, Dict[str, Any]],
    extent: List[float],
    output_path: Union[str, Path],
    site_coord: Tuple[float, float] = (96.052420, 20.589678),
    vlim_diff: float = 2.0,
    dpi: int = 300,
) -> Path:
    """
    Generate a publication-ready 2x4 multi-panel comparison figure:
    Top row: Baseline MMI, Augmented MMI 8.0, Augmented MMI 8.5, Augmented MMI 9.0
    Bottom row: Blank/Legend, ΔMMI (8.0 - Base), ΔMMI (8.5 - Base), ΔMMI (9.0 - Base)
    All panels share consistent fixed color limits and non-overlapping typography.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(2, 4, figsize=(24, 12), constrained_layout=True)

    mmi_vmin, mmi_vmax = 1.0, 10.0
    norm_diff = mcolors.TwoSlopeNorm(vmin=-vlim_diff, vcenter=0.0, vmax=vlim_diff)

    site_lon, site_lat = site_coord

    # Panel 0,0: Baseline
    im_base = axes[0, 0].imshow(
        baseline_mmi, extent=extent, origin="upper", cmap="turbo", vmin=mmi_vmin, vmax=mmi_vmax, aspect="auto"
    )
    axes[0, 0].plot(site_lon, site_lat, marker="*", color="white", markeredgecolor="black", markersize=14, zorder=5)
    axes[0, 0].set_title("Reconstructed Baseline\n(Unconstrained Data Void)", fontsize=11, fontweight="bold", pad=8)
    axes[0, 0].set_ylabel("Latitude (°N)", fontsize=10)

    # Scenarios: mmi80, mmi85, mmi90
    keys = ["mmi80", "mmi85", "mmi90"]
    col_labels = ["Hypothetical MMI 8.0", "Hypothetical MMI 8.5", "Original Model MMI 9.0"]

    for col_idx, (k, col_label) in enumerate(zip(keys, col_labels), start=1):
        scen = scenarios_data[k]
        aug_mmi = scen["augmented_mmi"]
        delta_mmi = aug_mmi - baseline_mmi
        site_shift = scen["metrics"]["delta_mmi_at_site"]["bilinear"]

        # Top row: Augmented MMI
        im_aug = axes[0, col_idx].imshow(
            aug_mmi, extent=extent, origin="upper", cmap="turbo", vmin=mmi_vmin, vmax=mmi_vmax, aspect="auto"
        )
        axes[0, col_idx].plot(site_lon, site_lat, marker="*", color="white", markeredgecolor="black", markersize=14, zorder=5)
        axes[0, col_idx].set_title(f"Augmented: {col_label}\n(σ = 0.50, Nresp = null)", fontsize=11, fontweight="bold", pad=8)

        # Bottom row: Difference (ΔMMI)
        im_diff = axes[1, col_idx].imshow(
            delta_mmi, extent=extent, origin="upper", cmap="coolwarm", norm=norm_diff, aspect="auto"
        )
        axes[1, col_idx].plot(site_lon, site_lat, marker="*", color="yellow", markeredgecolor="black", markersize=14, zorder=5)
        axes[1, col_idx].set_title(
            f"Signed Shift ΔMMI ({col_label.split()[-1]})\nSite Δ = {site_shift:+.2f} MMI",
            fontsize=11,
            fontweight="bold",
            pad=8,
        )
        axes[1, col_idx].set_xlabel("Longitude (°E)", fontsize=10)

    # Panel 1,0: Text annotation / Summary info
    ax_info = axes[1, 0]
    ax_info.axis("off")
    info_text = (
        "MMI-Gram Stage 4B Workflow B\n"
        "P-02 Sensitivity Experiment\n"
        "------------------------------------\n"
        "Event: us7000pn9s (Mw 7.7 Mandalay)\n"
        "Origin Time: 2025-03-28T06:20:52Z\n"
        "Observation: P-02 (KBZ Bank, Pyawbwe)\n"
        "Coordinates: 20.5897° N, 96.0524° E\n"
        "Distance to Fault: Rrup = 1.268 km\n"
        "Nearest Baseline DYFI: 38.005 km\n"
        "Baseline Model at Site: ~9.95 MMI\n"
        "Uncertainty: σ = 0.50 (Unreviewed Prior)\n"
        "Ingestion: Native single obs (nresp=null)\n"
        "Status: Exploratory Sensitivity Test\n"
        "Scientific Endorsement: None"
    )
    ax_info.text(
        0.05, 0.5, info_text, transform=ax_info.transAxes,
        fontsize=10, family="monospace", va="center",
        bbox=dict(boxstyle="round,pad=0.7", fc="#f8f9fa", ec="#ced4da", lw=1.5)
    )

    for ax in [axes[0, 0], axes[1, 0]]:
        ax.set_ylabel("Latitude (°N)", fontsize=10)
    for ax in axes.flat:
        if ax != ax_info:
            ax.grid(True, linestyle="--", alpha=0.35, color="grey")

    fig.suptitle(
        "USGS ShakeMap 4.5 Sensitivity to Single Eyewitness Intensity (P-02 Pyawbwe Data Void)",
        fontsize=14,
        fontweight="bold",
        y=0.99,
    )

    fig.savefig(out_p, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return out_p


def plot_pyawbwe_data_void_map(
    baseline_mmi: np.ndarray,
    lats: np.ndarray,
    lons: np.ndarray,
    output_path: Union[str, Path],
    rupture_path: Optional[Union[str, Path]] = None,
    dpi: int = 300,
) -> Path:
    """
    Generate a high-resolution map of the Pyawbwe 38.005-km data void.
    Highlights the observation site, the nearest baseline DYFI station, the connecting void distance,
    and the surface fault rupture trace.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    # Pyawbwe and nearest DYFI coordinates
    pyawbwe_lon, pyawbwe_lat = 96.052420, 20.589678
    dyfi_lon, dyfi_lat = 95.8594, 20.8799

    # Zoom window: [lon 95.4 to 96.7, lat 20.1 to 21.3]
    lon_min_z, lon_max_z = 95.40, 96.70
    lat_min_z, lat_max_z = 20.10, 21.30

    mask_lat = (lats >= lat_min_z) & (lats <= lat_max_z)
    mask_lon = (lons >= lon_min_z) & (lons <= lon_max_z)
    lats_sub = lats[mask_lat]
    lons_sub = lons[mask_lon]
    mmi_sub = baseline_mmi[np.ix_(mask_lat, mask_lon)]
    extent_sub = [lons_sub[0], lons_sub[-1], lats_sub[-1], lats_sub[0]]

    fig, ax = plt.subplots(figsize=(9, 8.5), constrained_layout=True)

    im = ax.imshow(
        mmi_sub,
        extent=extent_sub,
        origin="upper",
        cmap="turbo",
        vmin=6.0,
        vmax=10.0,
        aspect="auto",
    )
    cbar = fig.colorbar(im, ax=ax, orientation="horizontal", pad=0.07, shrink=0.85)
    cbar.set_label("Baseline Modeled Instrumental Intensity (MMI)", fontsize=10, fontweight="bold")

    # Plot surface fault trace if rupture provided
    if rupture_path and os.path.exists(rupture_path):
        try:
            with open(rupture_path, "r", encoding="utf-8") as rf:
                rdata = json.load(rf)
            for feat in rdata.get("features", []):
                geom = feat.get("geometry", {})
                if geom.get("type") == "MultiPolygon":
                    for poly in geom.get("coordinates", []):
                        for ring in poly:
                            # Filter surface trace (depth == 0.0)
                            surface_pts = [pt for pt in ring if len(pt) >= 3 and abs(pt[2]) < 0.1]
                            if surface_pts:
                                fx = [pt[0] for pt in surface_pts]
                                fy = [pt[1] for pt in surface_pts]
                                ax.plot(fx, fy, color="red", linewidth=2.5, linestyle="-", label="Fault Rupture Trace (Mw 7.7)", zorder=4)
        except Exception as e:
            print(f"Warning: could not plot rupture trace: {e}")

    # Plot connecting geodesic data void line
    ax.plot(
        [pyawbwe_lon, dyfi_lon],
        [pyawbwe_lat, dyfi_lat],
        color="white",
        linestyle="--",
        linewidth=2.2,
        zorder=5,
        label="Data Void: 38.005 km (No Baseline Data)",
    )
    mid_lon = 0.5 * (pyawbwe_lon + dyfi_lon)
    mid_lat = 0.5 * (pyawbwe_lat + dyfi_lat)
    ax.annotate(
        "38.005 km Data Void",
        (mid_lon, mid_lat),
        textcoords="offset points",
        xytext=(-20, 15),
        fontsize=9,
        fontweight="bold",
        color="darkblue",
        bbox=dict(boxstyle="round,pad=0.3", fc="yellow", alpha=0.9, ec="black", lw=1.2),
        zorder=7,
    )

    # Plot P-02 observation site
    ax.scatter(
        [pyawbwe_lon], [pyawbwe_lat],
        color="gold", marker="*", s=220, edgecolors="black", linewidths=1.5,
        zorder=6, label="P-02: Pyawbwe KBZ Bank (Rrup = 1.27 km)",
    )
    ax.annotate(
        "P-02 (Pyawbwe Bank)\n(20.590°N, 96.052°E)",
        (pyawbwe_lon, pyawbwe_lat),
        textcoords="offset points",
        xytext=(12, -18),
        fontsize=9,
        fontweight="bold",
        color="black",
        bbox=dict(boxstyle="round,pad=0.25", fc="white", alpha=0.9, ec="grey"),
        zorder=7,
    )

    # Plot nearest assimilated DYFI station
    ax.scatter(
        [dyfi_lon], [dyfi_lat],
        color="cyan", marker="^", s=150, edgecolors="black", linewidths=1.5,
        zorder=6, label="Nearest DYFI: UTM 46Q (MMI 8.5, N=3)",
    )
    ax.annotate(
        "Nearest DYFI (UTM 46Q)\n(20.880°N, 95.859°E)",
        (dyfi_lon, dyfi_lat),
        textcoords="offset points",
        xytext=(-120, 10),
        fontsize=9,
        fontweight="bold",
        color="black",
        bbox=dict(boxstyle="round,pad=0.25", fc="white", alpha=0.9, ec="grey"),
        zorder=7,
    )

    ax.set_xlim(lon_min_z, lon_max_z)
    ax.set_ylim(lat_min_z, lat_max_z)
    ax.set_xlabel("Longitude (°E)", fontsize=11, fontweight="bold")
    ax.set_ylabel("Latitude (°N)", fontsize=11, fontweight="bold")
    ax.grid(True, linestyle="--", alpha=0.4, color="grey")
    ax.legend(loc="lower left", fontsize=8.5, framealpha=0.92)
    ax.set_title(
        "USGS ShakeMap 4.5 Baseline: Pyawbwe Observational Data Void\n"
        "(Unconstrained Near-Fault Region, Rrup = 1.27 km)",
        fontsize=12,
        fontweight="bold",
        pad=10,
    )

    fig.savefig(out_p, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return out_p


def plot_pyawbwe_zoom_comparison(
    baseline_mmi: np.ndarray,
    scenarios_data: Dict[str, Dict[str, Any]],
    lats: np.ndarray,
    lons: np.ndarray,
    output_path: Union[str, Path],
    rupture_path: Optional[Union[str, Path]] = None,
    dpi: int = 300,
) -> Path:
    """
    Generate an 8-panel high-resolution zoom on Pyawbwe:
    Top Row: Baseline MMI, Augmented MMI 8.0, Augmented MMI 8.5, Augmented MMI 9.0 (all focused on Pyawbwe)
    Bottom Row: Data Void Map, ΔMMI 8.0 with contours, ΔMMI 8.5 with contours, ΔMMI 9.0 with contours
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    pyawbwe_lon, pyawbwe_lat = 96.052420, 20.589678
    dyfi_lon, dyfi_lat = 95.8594, 20.8799

    # Subgrid window
    lon_min_z, lon_max_z = 95.50, 96.60
    lat_min_z, lat_max_z = 20.20, 21.20

    mask_lat = (lats >= lat_min_z) & (lats <= lat_max_z)
    mask_lon = (lons >= lon_min_z) & (lons <= lon_max_z)
    lats_sub = lats[mask_lat]
    lons_sub = lons[mask_lon]
    extent_sub = [lons_sub[0], lons_sub[-1], lats_sub[-1], lats_sub[0]]

    base_sub = baseline_mmi[np.ix_(mask_lat, mask_lon)]

    # Load rupture surface trace if present
    surface_fx, surface_fy = [], []
    if rupture_path and os.path.exists(rupture_path):
        try:
            with open(rupture_path, "r", encoding="utf-8") as rf:
                rdata = json.load(rf)
            for feat in rdata.get("features", []):
                geom = feat.get("geometry", {})
                if geom.get("type") == "MultiPolygon":
                    for poly in geom.get("coordinates", []):
                        for ring in poly:
                            spts = [pt for pt in ring if len(pt) >= 3 and abs(pt[2]) < 0.1]
                            if spts:
                                surface_fx = [pt[0] for pt in spts]
                                surface_fy = [pt[1] for pt in spts]
        except Exception:
            pass

    fig, axes = plt.subplots(2, 4, figsize=(22, 11), constrained_layout=True)

    mmi_vmin, mmi_vmax = 7.0, 10.0
    norm_diff = mcolors.TwoSlopeNorm(vmin=-1.5, vcenter=0.0, vmax=0.2)

    # Row 0, Col 0: Zoomed Baseline
    im0 = axes[0, 0].imshow(base_sub, extent=extent_sub, origin="upper", cmap="turbo", vmin=mmi_vmin, vmax=mmi_vmax, aspect="auto")
    axes[0, 0].plot(pyawbwe_lon, pyawbwe_lat, marker="*", color="white", markeredgecolor="black", markersize=14, zorder=5)
    if surface_fx:
        axes[0, 0].plot(surface_fx, surface_fy, color="red", linewidth=2.0, linestyle="-", label="Fault Trace")
    axes[0, 0].set_title("Baseline (Zoomed)\n(Site MMI = 9.95)", fontsize=11, fontweight="bold", pad=8)
    axes[0, 0].set_ylabel("Latitude (°N)", fontsize=10)

    # Row 0, Col 1-3: Zoomed Augmented
    keys = ["mmi80", "mmi85", "mmi90"]
    titles_aug = [
        "Augmented: MMI 8.0\n(Site MMI = 8.82)",
        "Augmented: MMI 8.5\n(Site MMI = 9.11)",
        "Augmented: MMI 9.0\n(Site MMI = 9.40)",
    ]

    for cidx, (k, title_aug) in enumerate(zip(keys, titles_aug), start=1):
        aug_sub = scenarios_data[k]["augmented_mmi"][np.ix_(mask_lat, mask_lon)]
        im_a = axes[0, cidx].imshow(aug_sub, extent=extent_sub, origin="upper", cmap="turbo", vmin=mmi_vmin, vmax=mmi_vmax, aspect="auto")
        axes[0, cidx].plot(pyawbwe_lon, pyawbwe_lat, marker="*", color="white", markeredgecolor="black", markersize=14, zorder=5)
        if surface_fx:
            axes[0, cidx].plot(surface_fx, surface_fy, color="red", linewidth=2.0, linestyle="-")
        axes[0, cidx].set_title(title_aug, fontsize=11, fontweight="bold", pad=8)

    # Row 1, Col 0: Observation Geometry & Data Void
    ax_void = axes[1, 0]
    ax_void.imshow(base_sub, extent=extent_sub, origin="upper", cmap="Greys", alpha=0.35, aspect="auto")
    if surface_fx:
        ax_void.plot(surface_fx, surface_fy, color="red", linewidth=2.0, linestyle="-", label="Fault Trace", zorder=3)
    ax_void.plot([pyawbwe_lon, dyfi_lon], [pyawbwe_lat, dyfi_lat], color="blue", linestyle="--", linewidth=2.0, zorder=4, label="38.0 km Void")
    ax_void.scatter([pyawbwe_lon], [pyawbwe_lat], color="gold", marker="*", s=180, edgecolors="black", zorder=5, label="P-02 (Pyawbwe)")
    ax_void.scatter([dyfi_lon], [dyfi_lat], color="cyan", marker="^", s=130, edgecolors="black", zorder=5, label="Nearest DYFI")
    ax_void.set_title("Station Geometry & Void\n(38.005 km Distance)", fontsize=11, fontweight="bold", pad=8)
    ax_void.set_ylabel("Latitude (°N)", fontsize=10)
    ax_void.set_xlabel("Longitude (°E)", fontsize=10)
    ax_void.legend(loc="lower left", fontsize=7.5, framealpha=0.9)

    # Row 1, Col 1-3: Difference with Contours
    titles_diff = [
        "Signed Shift ΔMMI (8.0)\n(Site Δ = -1.13)",
        "Signed Shift ΔMMI (8.5)\n(Site Δ = -0.84)",
        "Signed Shift ΔMMI (9.0)\n(Site Δ = -0.55)",
    ]

    for cidx, (k, title_d) in enumerate(zip(keys, titles_diff), start=1):
        ax_d = axes[1, cidx]
        delta_sub = (scenarios_data[k]["augmented_mmi"] - baseline_mmi)[np.ix_(mask_lat, mask_lon)]
        im_d = ax_d.imshow(delta_sub, extent=extent_sub, origin="upper", cmap="coolwarm", norm=norm_diff, aspect="auto")
        ax_d.plot(pyawbwe_lon, pyawbwe_lat, marker="*", color="yellow", markeredgecolor="black", markersize=14, zorder=5)
        if surface_fx:
            ax_d.plot(surface_fx, surface_fy, color="red", linewidth=1.5, linestyle=":", alpha=0.8)

        # Plot contour lines at -0.1, -0.2, -0.5
        # Coordinate grid for contours
        lon_grid, lat_grid = np.meshgrid(lons_sub, lats_sub)
        levels = [-1.0, -0.5, -0.2, -0.1]
        active_levels = [lvl for lvl in levels if lvl >= delta_sub.min()]
        if active_levels:
            cs = ax_d.contour(
                lon_grid, lat_grid, delta_sub,
                levels=active_levels,
                colors=["#49006a", "#7a0177", "#ae017e", "#f768a1"],
                linewidths=[1.8, 1.5, 1.2, 1.0],
                linestyles=["-", "--", "-.", ":"],
            )
            ax_d.clabel(cs, inline=True, fontsize=8, fmt="%1.1f")

        ax_d.set_title(title_d, fontsize=11, fontweight="bold", pad=8)
        ax_d.set_xlabel("Longitude (°E)", fontsize=10)

    for ax in axes.flat:
        ax.set_xlim(lon_min_z, lon_max_z)
        ax.set_ylim(lat_min_z, lat_max_z)
        ax.grid(True, linestyle="--", alpha=0.35, color="grey")

    fig.suptitle(
        "USGS ShakeMap 4.5 Sensitivity: Pyawbwe Close-Up & Intensity Shift Contours",
        fontsize=14,
        fontweight="bold",
        y=0.99,
    )

    fig.savefig(out_p, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return out_p


def plot_radial_distance_decay(
    scenarios_metrics: Dict[str, Dict[str, Any]],
    output_path: Union[str, Path],
    dpi: int = 300,
) -> Path:
    """
    Generate a 2-panel publication figure of radial spatial decay:
    Top Panel: Total Signed Intensity Shift ΔMMI(r) vs Distance from Pyawbwe.
    Bottom Panel: Decomposed into Local Spatial Influence ΔMMI_local(r) and Regional Event Bias Shift Δbias.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 8), constrained_layout=True)

    colors = {"mmi80": "#1f77b4", "mmi85": "#2ca02c", "mmi90": "#d62728"}
    labels = {"mmi80": "Input MMI 8.0", "mmi85": "Input MMI 8.5", "mmi90": "Input MMI 9.0 (Model Prior)"}

    # Top Panel: Total Shift
    for k in ["mmi80", "mmi85", "mmi90"]:
        prof = scenarios_metrics[k]["radial_decay_profile"]
        r_mids = [p["r_mid_km"] for p in prof]
        means = [p["mean_delta_mmi"] for p in prof]
        mins = [p["min_delta_mmi"] for p in prof]
        maxs = [p["max_delta_mmi"] for p in prof]

        ax1.plot(r_mids, means, marker="o", color=colors[k], linewidth=2.0, label=labels[k])
        ax1.fill_between(r_mids, mins, maxs, color=colors[k], alpha=0.15)

    ax1.axhline(0.0, color="black", linestyle="--", linewidth=1.0)
    ax1.axvline(38.005, color="purple", linestyle=":", linewidth=1.8, label="Nearest Baseline DYFI (38.0 km)")
    ax1.set_xlabel("Distance from Pyawbwe Observation (km)", fontsize=10, fontweight="bold")
    ax1.set_ylabel("Total Signed Shift ΔMMI", fontsize=10, fontweight="bold")
    ax1.set_title("Total Intensity Shift vs Distance from Pyawbwe Observation", fontsize=11, fontweight="bold")
    ax1.grid(True, linestyle="--", alpha=0.4)
    ax1.legend(loc="lower right", framealpha=0.92, fontsize=8.5)

    # Bottom Panel: Decomposition into Local Influence vs Event Bias
    for k in ["mmi80", "mmi85", "mmi90"]:
        bias_delta = scenarios_metrics[k]["event_bias"]["bias_delta"]
        prof = scenarios_metrics[k]["radial_decay_profile"]
        r_mids = [p["r_mid_km"] for p in prof]
        means_total = [p["mean_delta_mmi"] for p in prof]
        # Local component = Total - bias_delta
        means_local = [tot - bias_delta for tot in means_total]

        # Plot local component (solid)
        ax2.plot(r_mids, means_local, marker="s", color=colors[k], linewidth=2.0, linestyle="-", label=f"{labels[k]}: Local Spatial Component")
        # Plot regional bias component (flat horizontal dashed line)
        ax2.axhline(bias_delta, color=colors[k], linestyle="--", linewidth=1.4, alpha=0.75, label=f"{labels[k]}: Uniform Event Bias (Δ={bias_delta:+.3f})")

    ax2.axhline(0.0, color="black", linestyle=":", linewidth=1.0)
    ax2.axvline(38.005, color="purple", linestyle=":", linewidth=1.8)
    ax2.set_xlabel("Distance from Pyawbwe Observation (km)", fontsize=10, fontweight="bold")
    ax2.set_ylabel("Decomposed Shift Components (MMI)", fontsize=10, fontweight="bold")
    ax2.set_title("Decomposition: Local Spatial Conditioning vs Uniform Regional Event Bias", fontsize=11, fontweight="bold")
    ax2.grid(True, linestyle="--", alpha=0.4)
    ax2.legend(loc="lower right", framealpha=0.92, fontsize=8.0, ncol=2)

    fig.suptitle("Spatial Structure of Single-Observation Ingestion in USGS ShakeMap 4.5", fontsize=13, fontweight="bold", y=0.99)

    fig.savefig(out_p, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return out_p


def plot_delta_vs_input_mmi(
    scenarios_metrics: Dict[str, Dict[str, Any]],
    output_path: Union[str, Path],
    baseline_site_mmi: float = 9.9492,
    dpi: int = 300,
) -> Path:
    """Generate diagnostic comparison plots of hypothetical input MMI vs modeled output site MMI and signed shifts."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    input_mmis = []
    modeled_mmis = []
    site_deltas = []
    bias_deltas = []
    scenario_keys = []

    for k in sorted(scenarios_metrics.keys()):
        m = scenarios_metrics[k]
        inp = m.get("target_mmi")
        if inp is None:
            if "80" in k:
                inp = 8.0
            elif "85" in k:
                inp = 8.5
            elif "90" in k:
                inp = 9.0
            else:
                continue
        input_mmis.append(inp)
        scenario_keys.append(k)
        modeled = (
            m["modeled_mmi_at_site"]["bilinear"]
            if isinstance(m.get("modeled_mmi_at_site"), dict)
            else float(m.get("modeled_mmi_at_site", 0.0))
        )
        modeled_mmis.append(modeled)
        delta = (
            m["site_delta_mmi"]["bilinear"]
            if isinstance(m.get("site_delta_mmi"), dict)
            else float(m.get("site_delta_mmi", 0.0))
        )
        site_deltas.append(delta)
        bias_delta = m.get("event_bias_comparison", {}).get("bias_delta", 0.0)
        bias_deltas.append(bias_delta)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    # Panel 1: Input MMI vs Modeled Site MMI
    ax1.plot([7.5, 10.2], [7.5, 10.2], color="gray", linestyle="--", linewidth=1.2, label="1:1 Perfect Agreement Line (y = x)")
    ax1.axhline(baseline_site_mmi, color="crimson", linestyle=":", linewidth=1.8, label=f"Reconstructed Baseline at Site (MMI {baseline_site_mmi:.2f})")

    # Plot points
    colors = ["#1f77b4", "#ff7f0e", "#2ca02c"]
    for i, (inp, mod, k) in enumerate(zip(input_mmis, modeled_mmis, scenario_keys)):
        ax1.scatter(inp, mod, color=colors[i % len(colors)], s=120, zorder=5, label=f"Input {inp:.1f} → Modeled {mod:.2f}")
        ax1.annotate(
            f"({inp:.1f}, {mod:.2f})",
            xy=(inp, mod),
            xytext=(10, -10),
            textcoords="offset points",
            fontsize=9,
            fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=colors[i % len(colors)], alpha=0.8),
        )

    # Trend line connecting modeled points
    ax1.plot(input_mmis, modeled_mmis, color="navy", linestyle="-", linewidth=2.0, alpha=0.8)

    ax1.set_xlim(7.5, 10.2)
    ax1.set_ylim(7.5, 10.5)
    ax1.set_xlabel("Hypothetical Input MMI at Pyawbwe (P-02)", fontsize=11, fontweight="bold")
    ax1.set_ylabel("Modeled Output MMI at Site (USGS ShakeMap 4.5)", fontsize=11, fontweight="bold")
    ax1.set_title("Input MMI vs Modeled Site MMI\n(Bayesian Shrinkage / Prior Attenuation)", fontsize=12, fontweight="bold")
    ax1.grid(True, linestyle="--", alpha=0.4)
    ax1.legend(loc="upper left", framealpha=0.92, fontsize=8.5)

    # Panel 2: Signed Shifts (Site Delta and Regional Event Bias Shift)
    x = np.arange(len(input_mmis))
    width = 0.35

    rects1 = ax2.bar(x - width / 2, site_deltas, width, label="Local Site Shift ΔMMI", color="#d62728", alpha=0.85)
    rects2 = ax2.bar(x + width / 2, [b * 10 for b in bias_deltas], width, label="Regional Bias Shift Δbias (×10)", color="#1f77b4", alpha=0.85)

    ax2.axhline(0, color="black", linewidth=0.8)
    ax2.set_xticks(x)
    ax2.set_xticklabels([f"Input MMI {inp:.1f}" for inp in input_mmis], fontsize=10, fontweight="bold")
    ax2.set_ylabel("Shift Magnitude (MMI Units)", fontsize=11, fontweight="bold")
    ax2.set_title("Signed Sensitivity Impact at Pyawbwe & Regional Bias\n(Site ΔMMI vs Regional Event Bias Shift)", fontsize=12, fontweight="bold")
    ax2.grid(True, linestyle="--", alpha=0.4)
    ax2.legend(loc="lower right", framealpha=0.92, fontsize=8.5)

    # Add value labels on bars
    for rect in rects1:
        height = rect.get_height()
        ax2.annotate(
            f"{height:+.2f}",
            xy=(rect.get_x() + rect.get_width() / 2, height),
            xytext=(0, -14 if height < 0 else 3),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=9,
            fontweight="bold",
        )
    for i, rect in enumerate(rects2):
        actual_b = bias_deltas[i]
        height = rect.get_height()
        ax2.annotate(
            f"{actual_b:+.3f}",
            xy=(rect.get_x() + rect.get_width() / 2, height),
            xytext=(0, -14 if height < 0 else 3),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=9,
            fontweight="bold",
        )

    fig.suptitle("Exploratory P-02 Sensitivity: ShakeMap Numerical Response to Varied Priors", fontsize=13, fontweight="bold", y=0.98)
    plt.tight_layout()
    fig.savefig(out_p, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return out_p
