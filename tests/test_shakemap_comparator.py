"""
Unit and regression tests for ShakeMapGridComparator (Stage 4B Part 1).

Tests parsing of ShakeMap grid.xml and shake_result.hdf, geometry validation,
mismatch detection, signed intensity difference calculation (augmented - baseline),
summary metrics, area calculations in km², and CSV/JSON/PNG/PDF exports.

All tests run strictly offline with zero paid API calls and zero network requests.
"""

import json
import math
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Any, List

import numpy as np
import pytest

from mmigram.seismology.shakemap_comparator import (
    ShakeMapGrid,
    GridComparisonResult,
    ShakeMapGridComparator,
)

SMOKE_DATA_DIR = Path(__file__).parent.parent / "data" / "synthetic_smoketest"


def _generate_synthetic_grid_xml(
    path: Path,
    event_id: str,
    mmi_2d: np.ndarray,
    lon_min: float = -118.5,
    lon_max: float = -117.5,
    lat_min: float = 33.5,
    lat_max: float = 34.5,
    dx: float = 0.02,
    dy: float = 0.02,
) -> None:
    """Generate a standard ShakeMap grid.xml file on the fly for reproducible offline testing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    nlat, nlon = mmi_2d.shape
    lons = np.linspace(lon_min, lon_max, nlon)
    lats = np.linspace(lat_max, lat_min, nlat)

    lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        f'<shakemap_grid xmlns="http://earthquake.usgs.gov/eqcenter/shakemap" event_id="{event_id}" shakemap_id="{event_id}" shakemap_version="1" code_version="4.5.0">',
        f'<event event_id="{event_id}" magnitude="6.0" depth="10.0" lat="34.0000" lon="-118.0000" />',
        f'<grid_specification lon_min="{lon_min:.4f}" lat_min="{lat_min:.4f}" lon_max="{lon_max:.4f}" lat_max="{lat_max:.4f}" nominal_lon_spacing="{dx:.4f}" nominal_lat_spacing="{dy:.4f}" nlon="{nlon}" nlat="{nlat}"/>',
        '<grid_field index="1" name="LON" units="dd" />',
        '<grid_field index="2" name="LAT" units="dd" />',
        '<grid_field index="3" name="MMI" units="intensity" />',
        '<grid_field index="4" name="PGA" units="%g" />',
        '<grid_field index="5" name="PGV" units="cm/s" />',
        '<grid_data>',
    ]
    for i in range(nlat):
        lat_v = lats[i]
        for j in range(nlon):
            lon_v = lons[j]
            mmi_v = mmi_2d[i, j]
            lines.append(f"{lon_v:.4f} {lat_v:.4f} {mmi_v:.2f} 3.00 2.50")
    lines.append("</grid_data>")
    lines.append("</shakemap_grid>")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _generate_synthetic_hdf(
    path: Path,
    event_id: str,
    mmi_2d: np.ndarray,
    lon_min: float = -118.5,
    lon_max: float = -117.5,
    lat_min: float = 33.5,
    lat_max: float = 34.5,
    dx: float = 0.02,
    dy: float = 0.02,
) -> None:
    """Generate a standard ShakeMap shake_result.hdf file on the fly for reproducible offline testing."""
    import h5py
    path.parent.mkdir(parents=True, exist_ok=True)
    nlat, nlon = mmi_2d.shape

    with h5py.File(path, "w") as hf:
        ds = hf.create_dataset(
            "arrays/imts/GREATER_OF_TWO_HORIZONTAL/MMI/mean",
            data=mmi_2d.astype(np.float32),
        )
        ds.attrs["nx"] = nlon
        ds.attrs["ny"] = nlat
        ds.attrs["xmin"] = lon_min
        ds.attrs["xmax"] = lon_max
        ds.attrs["ymin"] = lat_min
        ds.attrs["ymax"] = lat_max
        ds.attrs["dx"] = dx
        ds.attrs["dy"] = dy
        ds.attrs["units"] = "intensity"

        info_payload = {
            "input": {
                "event_information": {
                    "event_id": event_id,
                    "magnitude": 6.0,
                    "depth": 10.0,
                }
            }
        }
        hf.create_dataset("dictionaries/info.json", data=json.dumps(info_payload).encode("utf-8"))


@pytest.fixture
def smoke_fixtures(tmp_path):
    """
    Returns paths to baseline and augmented products.
    Uses existing SMOKE_DATA_DIR products if present, or generates them on-the-fly in tmp_path.
    """
    base_hdf = SMOKE_DATA_DIR / "baseline" / "products" / "shake_result.hdf"
    aug_hdf = SMOKE_DATA_DIR / "augmented" / "products" / "shake_result.hdf"
    base_xml = SMOKE_DATA_DIR / "baseline" / "products" / "grid.xml"
    aug_xml = SMOKE_DATA_DIR / "augmented" / "products" / "grid.xml"

    if base_hdf.exists() and aug_hdf.exists() and base_xml.exists():
        return {
            "base_hdf": base_hdf,
            "aug_hdf": aug_hdf,
            "base_xml": base_xml,
            "aug_xml": aug_xml,
            "base_dir": SMOKE_DATA_DIR / "baseline",
            "aug_dir": SMOKE_DATA_DIR / "augmented",
        }

    # Dynamically generate fixtures in tmp_path
    base_dir = tmp_path / "baseline"
    aug_dir = tmp_path / "augmented"
    b_hdf = base_dir / "products" / "shake_result.hdf"
    a_hdf = aug_dir / "products" / "shake_result.hdf"
    b_xml = base_dir / "products" / "grid.xml"
    a_xml = aug_dir / "products" / "grid.xml"

    # Base grid: distance-decaying MMI around center (34.0, -118.0)
    lons = np.linspace(-118.5, -117.5, 51)
    lats = np.linspace(34.5, 33.5, 51)
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    dist = np.sqrt((lon_grid - (-118.0))**2 + (lat_grid - 34.0)**2)
    mmi_base = np.maximum(4.0, 7.38 - 5.0 * dist)

    # Augmented grid: add +0.115 bump near center
    mmi_aug = mmi_base.copy()
    mmi_aug[25, 25] += 0.1153

    _generate_synthetic_grid_xml(b_xml, "synth_smoke_baseline", mmi_base)
    _generate_synthetic_grid_xml(a_xml, "synth_smoke_augmented", mmi_aug)
    _generate_synthetic_hdf(b_hdf, "synth_smoke_baseline", mmi_base)
    _generate_synthetic_hdf(a_hdf, "synth_smoke_augmented", mmi_aug)

    return {
        "base_hdf": b_hdf,
        "aug_hdf": a_hdf,
        "base_xml": b_xml,
        "aug_xml": a_xml,
        "base_dir": base_dir,
        "aug_dir": aug_dir,
    }


def _create_mock_grid(
    event_id: str = "test_event",
    lon_min: float = -118.5,
    lon_max: float = -117.5,
    lat_min: float = 33.5,
    lat_max: float = 34.5,
    dx: float = 0.02,
    dy: float = 0.02,
    nlon: int = 51,
    nlat: int = 51,
    base_mmi: float = 5.0,
    mmi_offset: float = 0.0,
) -> ShakeMapGrid:
    """Helper to generate an in-memory ShakeMapGrid for fast deterministic unit tests."""
    lons = np.linspace(lon_min, lon_max, nlon)
    lats = np.linspace(lat_max, lat_min, nlat)
    mmi = np.full((nlat, nlon), base_mmi + mmi_offset, dtype=float)
    return ShakeMapGrid(
        event_id=event_id,
        lon_min=lon_min,
        lat_min=lat_min,
        lon_max=lon_max,
        lat_max=lat_max,
        dx=dx,
        dy=dy,
        nlon=nlon,
        nlat=nlat,
        lons=lons,
        lats=lats,
        mmi=mmi,
        source_file="mock://memory",
        source_format="memory",
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. XML Grid Parsing & Validation
# ─────────────────────────────────────────────────────────────────────────────
def test_1_load_grid_xml(smoke_fixtures):
    """Verify ShakeMapGridComparator parses grid.xml correctly."""
    xml_path = smoke_fixtures["base_xml"]
    assert xml_path.exists(), f"Missing smoke test grid.xml: {xml_path}"

    grid = ShakeMapGridComparator.load_grid_xml(xml_path)

    assert grid.event_id == "synth_smoke_baseline"
    assert grid.source_format == "xml"
    assert grid.nlon == 51
    assert grid.nlat == 51
    assert grid.mmi.shape == (51, 51)
    assert abs(grid.lon_min - (-118.5)) < 1e-4
    assert abs(grid.lon_max - (-117.5)) < 1e-4
    assert abs(grid.lat_min - 33.5) < 1e-4
    assert abs(grid.lat_max - 34.5) < 1e-4
    assert abs(grid.dx - 0.02) < 1e-4
    assert abs(grid.dy - 0.02) < 1e-4
    assert len(grid.lons) == 51
    assert len(grid.lats) == 51
    assert grid.mmi.min() >= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# 2. HDF5 shake_result.hdf Parsing
# ─────────────────────────────────────────────────────────────────────────────
def test_2_load_shake_result_hdf(smoke_fixtures):
    """Verify ShakeMapGridComparator parses shake_result.hdf correctly."""
    hdf_path = smoke_fixtures["base_hdf"]
    assert hdf_path.exists(), f"Missing smoke test shake_result.hdf: {hdf_path}"

    grid = ShakeMapGridComparator.load_shake_result_hdf(hdf_path)

    assert grid.source_format == "hdf"
    assert grid.nlon == 51
    assert grid.nlat == 51
    assert grid.mmi.shape == (51, 51)
    assert abs(grid.lon_min - (-118.5)) < 1e-4
    assert abs(grid.lon_max - (-117.5)) < 1e-4
    assert abs(grid.lat_min - 33.5) < 1e-4
    assert abs(grid.lat_max - 34.5) < 1e-4
    # HDF5 floating-point fidelity
    assert 4.0 <= grid.mmi.min() <= 5.5
    assert 7.0 <= grid.mmi.max() <= 8.0


# ─────────────────────────────────────────────────────────────────────────────
# 3. Auto-Discovery & Path Resolution
# ─────────────────────────────────────────────────────────────────────────────
def test_3_load_grid_auto_discovery(smoke_fixtures):
    """Verify load_grid auto-discovers products in directories or direct paths."""
    base_dir = smoke_fixtures["base_dir"]
    grid = ShakeMapGridComparator.load_grid(base_dir)
    assert grid.nlon == 51

    # Direct XML path
    xml_p = smoke_fixtures["base_xml"]
    grid_xml = ShakeMapGridComparator.load_grid(xml_p)
    assert grid_xml.source_format == "xml"

    # Non-existent path raises FileNotFoundError
    with pytest.raises(FileNotFoundError):
        ShakeMapGridComparator.load_grid("non_existent_dir_12345")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Dimension & Bounds Matching Validation
# ─────────────────────────────────────────────────────────────────────────────
def test_4_validate_matching_grids_mismatches():
    """Verify validate_matching_grids rejects dimension, bound, or resolution differences."""
    base = _create_mock_grid(event_id="base")

    # A: Dimension mismatch
    dim_mismatch = _create_mock_grid(nlon=52)
    with pytest.raises(ValueError, match="Grid dimension mismatch"):
        ShakeMapGridComparator.validate_matching_grids(base, dim_mismatch)

    # B: Bounds mismatch (lon_min)
    bound_mismatch = _create_mock_grid(lon_min=-119.0)
    with pytest.raises(ValueError, match="Grid extent mismatch in lon_min"):
        ShakeMapGridComparator.validate_matching_grids(base, bound_mismatch)

    # C: Bounds mismatch (lat_max)
    lat_mismatch = _create_mock_grid(lat_max=35.0)
    with pytest.raises(ValueError, match="Grid extent mismatch in lat_max"):
        ShakeMapGridComparator.validate_matching_grids(base, lat_mismatch)

    # D: Resolution mismatch (dx)
    res_mismatch = _create_mock_grid(dx=0.04)
    with pytest.raises(ValueError, match="Grid resolution mismatch"):
        ShakeMapGridComparator.validate_matching_grids(base, res_mismatch)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Strict Signed Difference Direction: Augmented - Baseline
# ─────────────────────────────────────────────────────────────────────────────
def test_5_signed_difference_direction():
    """
    Verify that signed intensity difference is strictly defined as:
        ΔMMI = MMI_augmented - MMI_baseline
    An intensity increase in the augmented model MUST yield positive ΔMMI.
    """
    base = _create_mock_grid(event_id="base", base_mmi=6.0)
    aug = _create_mock_grid(event_id="aug", base_mmi=6.0)

    # Augment central cell with +1.5 intensity
    aug.mmi[25, 25] = 7.5

    # Suppress outer cell by -0.8 intensity
    aug.mmi[0, 0] = 5.2

    res = ShakeMapGridComparator.compare_grids(base, aug)

    assert res.delta_mmi[25, 25] == pytest.approx(1.5, abs=1e-5)
    assert res.delta_mmi[0, 0] == pytest.approx(-0.8, abs=1e-5)
    assert res.metrics["max_increase"] == pytest.approx(1.5, abs=1e-5)
    assert res.metrics["max_decrease"] == pytest.approx(-0.8, abs=1e-5)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Spatial Metrics & Surface Area Calculations
# ─────────────────────────────────────────────────────────────────────────────
def test_6_summary_metrics_and_area_calculation():
    """Verify cell counts, area calculations in km², and quantiles."""
    base = _create_mock_grid(nlon=10, nlat=10, base_mmi=5.0)
    aug = _create_mock_grid(nlon=10, nlat=10, base_mmi=5.0)

    # Set 4 cells with |ΔMMI| >= 0.5 (2 positive, 2 negative)
    aug.mmi[0, 0] = 5.6   # +0.6
    aug.mmi[0, 1] = 5.7   # +0.7
    aug.mmi[1, 0] = 4.4   # -0.6
    aug.mmi[1, 1] = 3.9   # -1.1 (also >= 1.0)

    res = ShakeMapGridComparator.compare_grids(base, aug)

    assert res.metrics["cell_count_total"] == 100
    assert res.metrics["cell_count_ge_05"] == 4
    assert res.metrics["cell_count_ge_10"] == 1
    assert res.metrics["pct_cells_ge_05"] == 4.0
    assert res.metrics["pct_cells_ge_10"] == 1.0

    # Area calculations
    assert res.metrics["total_area_km2"] > 0
    assert res.metrics["area_abs_ge_05_km2"] > 0
    assert res.metrics["area_abs_ge_10_km2"] > 0
    assert res.metrics["area_abs_ge_05_km2"] >= res.metrics["area_abs_ge_10_km2"]


# ─────────────────────────────────────────────────────────────────────────────
# 7. NaN and Invalid Data Handling
# ─────────────────────────────────────────────────────────────────────────────
def test_7_nan_handling():
    """Verify NaN cells in either grid are cleanly masked without raising exceptions."""
    base = _create_mock_grid(nlon=5, nlat=5, base_mmi=6.0)
    aug = _create_mock_grid(nlon=5, nlat=5, base_mmi=6.0)

    # Set NaNs in baseline and augmented
    base.mmi[0, 0] = np.nan
    aug.mmi[4, 4] = np.nan
    aug.mmi[2, 2] = 7.0  # +1.0 shift

    res = ShakeMapGridComparator.compare_grids(base, aug)

    # Total cells = 25, 2 have NaNs -> valid = 23
    assert res.metrics["cell_count_total"] == 23
    assert np.isnan(res.delta_mmi[0, 0])
    assert np.isnan(res.delta_mmi[4, 4])
    assert res.delta_mmi[2, 2] == pytest.approx(1.0, abs=1e-5)
    assert res.metrics["max_increase"] == pytest.approx(1.0, abs=1e-5)


# ─────────────────────────────────────────────────────────────────────────────
# 8. Export CSV, JSON, PNG, and PDF
# ─────────────────────────────────────────────────────────────────────────────
def test_8_export_csv_json_and_plots(tmp_path):
    """Verify export methods produce valid CSV, JSON, PNG, and PDF files."""
    base = _create_mock_grid(event_id="base_test", nlon=10, nlat=10, base_mmi=5.0)
    aug = _create_mock_grid(event_id="aug_test", nlon=10, nlat=10, base_mmi=5.0)
    aug.mmi[5, 5] = 6.2

    res = ShakeMapGridComparator.compare_grids(base, aug)

    # A: JSON export
    json_path = tmp_path / "test_diff.json"
    res.save_json(json_path)
    assert json_path.exists()
    with open(json_path, "r", encoding="utf-8") as f:
        jdata = json.load(f)
    assert jdata["formula"] == "delta_mmi = mmi_augmented - mmi_baseline"
    assert jdata["baseline_event_id"] == "base_test"
    assert jdata["metrics"]["max_increase"] == pytest.approx(1.2, abs=1e-4)

    # B: CSV export
    csv_path = tmp_path / "test_diff.csv"
    res.save_csv(csv_path)
    assert csv_path.exists()
    with open(csv_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    assert lines[0].strip() == "lon,lat,mmi_baseline,mmi_augmented,delta_mmi"
    assert len(lines) == 101  # 1 header + 100 data rows

    # C: PNG export
    png_path = tmp_path / "test_diff.png"
    res.save_plot(png_path, title="Unit Test Difference Map")
    assert png_path.exists()
    with open(png_path, "rb") as f:
        header = f.read(8)
    assert header.startswith(b"\x89PNG"), "Generated file is not a valid PNG"

    # D: PDF export
    pdf_path = tmp_path / "test_diff.pdf"
    res.save_plot(pdf_path, title="Unit Test Vector Difference Map")
    assert pdf_path.exists()
    with open(pdf_path, "rb") as f:
        pdf_header = f.read(5)
    assert pdf_header == b"%PDF-", "Generated file is not a valid PDF"


# ─────────────────────────────────────────────────────────────────────────────
# 9. Station Overlay Handling in Difference Plot
# ─────────────────────────────────────────────────────────────────────────────
def test_9_station_overlay_handling(tmp_path):
    """Verify that station overlays can be passed as GeoJSON file or list of dicts."""
    base = _create_mock_grid(nlon=10, nlat=10, base_mmi=5.0)
    aug = _create_mock_grid(nlon=10, nlat=10, base_mmi=5.0)
    res = ShakeMapGridComparator.compare_grids(base, aug)

    # Dict overlay
    stations_list = [
        {"lon": -118.0, "lat": 34.0, "mmi": 8.0, "name": "Station A"},
        {"longitude": -118.2, "latitude": 34.2, "intensity": 6.5, "name": "Station B"},
    ]
    png_from_list = tmp_path / "overlay_list.png"
    res.save_plot(png_from_list, stations=stations_list)
    assert png_from_list.exists()

    # GeoJSON file overlay
    geojson_path = tmp_path / "stations.json"
    geojson_data = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-118.0, 34.0]},
                "properties": {"intensity": 8.0, "station_name": "Obs 1"},
            }
        ],
    }
    with open(geojson_path, "w", encoding="utf-8") as f:
        json.dump(geojson_data, f)

    png_from_file = tmp_path / "overlay_file.png"
    res.save_plot(png_from_file, stations=geojson_path)
    assert png_from_file.exists()


# ─────────────────────────────────────────────────────────────────────────────
# 10. Synthetic Smoke Test Grid Comparison (End-to-End)
# ─────────────────────────────────────────────────────────────────────────────
def test_10_smoke_test_end_to_end_verification(smoke_fixtures):
    """
    Run end-to-end grid comparison on the actual outputs from the USGS ShakeMap 4.5
    synthetic smoke test run (synth_smoke_baseline vs synth_smoke_augmented).
    """
    base_prod = smoke_fixtures["base_hdf"]
    aug_prod = smoke_fixtures["aug_hdf"]
    assert base_prod.exists()
    assert aug_prod.exists()

    res = ShakeMapGridComparator.compare_files(base_prod, aug_prod)

    # The synthetic observation at (-118.0, 34.0) with MMI 9.5 was added to baseline
    assert res.metrics["max_increase"] > 0.10, "Augmented model should produce positive intensity increase"
    assert res.metrics["cell_count_total"] == 2601
    assert abs(res.bounds["lon_min"] - (-118.5)) < 1e-4
    assert abs(res.bounds["lon_max"] - (-117.5)) < 1e-4

    # The peak increase must be near the synthetic observation site (-118.0, 34.0)
    # Row 25, Col 25 corresponds to (-118.0, 34.0)
    peak_diff = res.delta_mmi[25, 25]
    assert peak_diff > 0.10, f"Expected peak near observation, got {peak_diff}"


# ─────────────────────────────────────────────────────────────────────────────
# 11. ShakeMap Observation Uncertainty Ingestion Preservation Contract
# ─────────────────────────────────────────────────────────────────────────────
def test_11_shakemap_observation_uncertainty_contract():
    """
    Verify that exported agent_mmi_dat.json strictly preserves per-observation
    standard deviation (intensity_stddev) conforming to ShakeMap's internal
    station parser requirements (StationList._parse_shakemap_json).
    """
    agent_mmi_path = SMOKE_DATA_DIR / "augmented" / "agent_mmi_dat.json"
    assert agent_mmi_path.exists(), f"Missing {agent_mmi_path}"

    with open(agent_mmi_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["type"] == "FeatureCollection"
    features = data["features"]
    assert len(features) >= 1

    for feat in features:
        props = feat["properties"]
        assert "intensity" in props
        assert "intensity_stddev" in props
        assert props["network"].lower() == "mmi"
        # Verify valid numerical uncertainty
        assert isinstance(props["intensity_stddev"], (int, float))
        assert props["intensity_stddev"] > 0
