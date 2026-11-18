"""
ShakeMap Grid Comparator (Stage 4B Part 1).

Compares official USGS ShakeMap output grids between baseline (unaugmented)
and augmented (agent MMI ingested) model runs:
    ΔMMI = MMI_augmented - MMI_baseline

Supports loading from:
- ShakeMap grid.xml (standard USGS XML raster format)
- ShakeMap shake_result.hdf (HDF5 continuous array format)

Computes spatial difference statistics, affected area metrics in km², tabular CSV,
structured JSON, and publication-ready multi-panel visual difference maps (PNG & PDF).
"""

from __future__ import annotations

import json
import math
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union

import numpy as np


@dataclass
class ShakeMapGrid:
    """Represents a raster grid produced by USGS ShakeMap."""
    event_id: str
    lon_min: float
    lat_min: float
    lon_max: float
    lat_max: float
    dx: float
    dy: float
    nlon: int
    nlat: int
    lons: np.ndarray
    lats: np.ndarray
    mmi: np.ndarray
    source_file: str
    source_format: str
    fields: Dict[str, np.ndarray] = field(default_factory=dict)

    def validate(self) -> None:
        """Validate internal consistency of grid geometry and array shapes."""
        if self.mmi.shape != (self.nlat, self.nlon):
            raise ValueError(
                f"Array shape {self.mmi.shape} does not match (nlat={self.nlat}, nlon={self.nlon})"
            )
        if len(self.lons) != self.nlon:
            raise ValueError(f"Longitude array length {len(self.lons)} != nlon {self.nlon}")
        if len(self.lats) != self.nlat:
            raise ValueError(f"Latitude array length {len(self.lats)} != nlat {self.nlat}")
        if self.lon_min >= self.lon_max:
            raise ValueError(f"lon_min ({self.lon_min}) must be < lon_max ({self.lon_max})")
        if self.lat_min >= self.lat_max:
            raise ValueError(f"lat_min ({self.lat_min}) must be < lat_max ({self.lat_max})")


@dataclass
class GridComparisonResult:
    """Detailed results of baseline vs. augmented ShakeMap grid comparison."""
    baseline_event_id: str
    augmented_event_id: str
    bounds: Dict[str, float]
    resolution: Dict[str, float]
    dimensions: Dict[str, int]
    metrics: Dict[str, Any]
    lons: np.ndarray
    lats: np.ndarray
    mmi_baseline: np.ndarray
    mmi_augmented: np.ndarray
    delta_mmi: np.ndarray

    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata and summary metrics to a serializable dictionary."""
        return {
            "comparison_type": "baseline_vs_augmented",
            "formula": "delta_mmi = mmi_augmented - mmi_baseline",
            "baseline_event_id": self.baseline_event_id,
            "augmented_event_id": self.augmented_event_id,
            "bounds": self.bounds,
            "resolution": self.resolution,
            "dimensions": self.dimensions,
            "metrics": self.metrics,
        }

    def save_json(self, output_path: Union[Path, str], indent: int = 2) -> Path:
        """Save comparison summary metrics to JSON."""
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=indent)
        return out_p

    def save_csv(self, output_path: Union[Path, str]) -> Path:
        """
        Export tabular CSV with columns:
        lon, lat, mmi_baseline, mmi_augmented, delta_mmi
        """
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        nlat, nlon = self.delta_mmi.shape
        with open(out_p, "w", encoding="utf-8") as f:
            f.write("lon,lat,mmi_baseline,mmi_augmented,delta_mmi\n")
            for i in range(nlat):
                lat = self.lats[i]
                for j in range(nlon):
                    lon = self.lons[j]
                    b_val = self.mmi_baseline[i, j]
                    a_val = self.mmi_augmented[i, j]
                    d_val = self.delta_mmi[i, j]
                    b_str = "" if np.isnan(b_val) else f"{b_val:.4f}"
                    a_str = "" if np.isnan(a_val) else f"{a_val:.4f}"
                    d_str = "" if np.isnan(d_val) else f"{d_val:.4f}"
                    f.write(f"{lon:.4f},{lat:.4f},{b_str},{a_str},{d_str}\n")
        return out_p

    def save_plot(
        self,
        output_path: Union[Path, str],
        stations: Optional[Union[List[Dict[str, Any]], Path, str]] = None,
        title: Optional[str] = None,
        dpi: int = 300,
    ) -> Path:
        """
        Generate publication-quality 3-panel difference figure:
        [Baseline MMI] | [Augmented MMI] | [ΔMMI (Augmented - Baseline)]

        Saves to PNG or PDF depending on file extension.
        """
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors

        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        # Parse station overlays if provided
        overlay_pts: List[Tuple[float, float, Optional[float], str]] = []
        if stations is not None:
            if isinstance(stations, (str, Path)):
                st_path = Path(stations)
                if st_path.exists():
                    try:
                        with open(st_path, "r", encoding="utf-8") as sf:
                            sdata = json.load(sf)
                            if sdata.get("type") == "FeatureCollection":
                                for feat in sdata.get("features", []):
                                    geom = feat.get("geometry", {})
                                    props = feat.get("properties", {})
                                    coords = geom.get("coordinates", [])
                                    if len(coords) >= 2:
                                        overlay_pts.append((
                                            coords[0],
                                            coords[1],
                                            props.get("intensity") or props.get("mmi"),
                                            props.get("station_name") or props.get("code") or "Station",
                                        ))
                    except Exception as e:
                        print(f"Warning: could not parse stations file {st_path}: {e}")
            elif isinstance(stations, list):
                for st in stations:
                    lon = st.get("lon") or st.get("longitude")
                    lat = st.get("lat") or st.get("latitude")
                    if lon is not None and lat is not None:
                        overlay_pts.append((
                            float(lon),
                            float(lat),
                            st.get("mmi") or st.get("intensity"),
                            st.get("name") or "Station",
                        ))

        fig, axes = plt.subplots(1, 3, figsize=(18, 5.5), constrained_layout=True)

        extent = [
            self.bounds["lon_min"],
            self.bounds["lon_max"],
            self.bounds["lat_min"],
            self.bounds["lat_max"],
        ]

        # Determine MMI color scale
        all_mmi = np.concatenate([
            self.mmi_baseline[~np.isnan(self.mmi_baseline)],
            self.mmi_augmented[~np.isnan(self.mmi_augmented)],
        ])
        if len(all_mmi) > 0:
            mmi_vmin = max(1.0, math.floor(all_mmi.min()))
            mmi_vmax = min(12.0, math.ceil(all_mmi.max()))
        else:
            mmi_vmin, mmi_vmax = 1.0, 10.0

        # Subplot 1: Baseline MMI
        im1 = axes[0].imshow(
            self.mmi_baseline,
            extent=extent,
            origin="upper",
            cmap="turbo",
            vmin=mmi_vmin,
            vmax=mmi_vmax,
            aspect="auto",
        )
        axes[0].set_title(f"Baseline ShakeMap (MMI)\nID: {self.baseline_event_id}", fontsize=12, fontweight="bold")
        axes[0].set_xlabel("Longitude (°E)", fontsize=10)
        axes[0].set_ylabel("Latitude (°N)", fontsize=10)
        cbar1 = fig.colorbar(im1, ax=axes[0], orientation="horizontal", pad=0.08, shrink=0.85)
        cbar1.set_label("Modeled MMI", fontsize=9)

        # Subplot 2: Augmented MMI
        im2 = axes[1].imshow(
            self.mmi_augmented,
            extent=extent,
            origin="upper",
            cmap="turbo",
            vmin=mmi_vmin,
            vmax=mmi_vmax,
            aspect="auto",
        )
        axes[1].set_title(f"Augmented ShakeMap (MMI)\nID: {self.augmented_event_id}", fontsize=12, fontweight="bold")
        axes[1].set_xlabel("Longitude (°E)", fontsize=10)
        cbar2 = fig.colorbar(im2, ax=axes[1], orientation="horizontal", pad=0.08, shrink=0.85)
        cbar2.set_label("Modeled MMI", fontsize=9)

        # Subplot 3: Difference (ΔMMI = Augmented - Baseline)
        valid_diff = self.delta_mmi[~np.isnan(self.delta_mmi)]
        if len(valid_diff) > 0:
            abs_max_diff = max(abs(valid_diff.min()), abs(valid_diff.max()))
            # Ensure minimum symmetric scale of 0.2 for visual readability
            diff_limit = max(0.2, math.ceil(abs_max_diff * 10) / 10.0)
        else:
            diff_limit = 0.5

        norm_diff = mcolors.TwoSlopeNorm(vmin=-diff_limit, vcenter=0.0, vmax=diff_limit)
        im3 = axes[2].imshow(
            self.delta_mmi,
            extent=extent,
            origin="upper",
            cmap="coolwarm",
            norm=norm_diff,
            aspect="auto",
        )
        axes[2].set_title(
            f"Signed Intensity Shift (ΔMMI)\nAugmented − Baseline (Max: +{self.metrics.get('max_increase', 0):.2f})",
            fontsize=12,
            fontweight="bold",
        )
        axes[2].set_xlabel("Longitude (°E)", fontsize=10)
        cbar3 = fig.colorbar(im3, ax=axes[2], orientation="horizontal", pad=0.08, shrink=0.85)
        cbar3.set_label("ΔMMI (Intensity Units)", fontsize=9)

        # Overlay observation stations on panel 3 if present
        if overlay_pts:
            pts_x = [p[0] for p in overlay_pts]
            pts_y = [p[1] for p in overlay_pts]
            axes[2].scatter(
                pts_x,
                pts_y,
                c="black",
                marker="^",
                s=60,
                edgecolors="white",
                linewidths=1.2,
                label=f"Ingested MMI Observations (N={len(overlay_pts)})",
                zorder=5,
            )
            axes[2].legend(loc="upper right", fontsize=8, framealpha=0.85)

        for ax in axes:
            ax.grid(True, linestyle="--", alpha=0.4, color="grey")

        main_title = title or f"MMI-Gram USGS ShakeMap 4.5 Impact Comparison: {self.baseline_event_id}"
        fig.suptitle(main_title, fontsize=14, fontweight="bold", y=1.02)

        fig.savefig(out_p, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        return out_p


class ShakeMapGridComparator:
    """
    Seismological validator and comparator for USGS ShakeMap raster outputs.
    """

    @staticmethod
    def load_grid_xml(xml_path: Union[Path, str]) -> ShakeMapGrid:
        """
        Parse USGS ShakeMap grid.xml file into a ShakeMapGrid.
        Handles both namespaced and non-namespaced ShakeMap XML.
        """
        path = Path(xml_path)
        if not path.exists():
            raise FileNotFoundError(f"ShakeMap grid.xml not found at: {path}")

        tree = ET.parse(path)
        root = tree.getroot()

        # Handle namespaces dynamically
        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0] + "}"

        event_elem = root.find(f"{ns}event")
        event_id = (
            root.attrib.get("event_id")
            or root.attrib.get("shakemap_id")
            or (event_elem.attrib.get("event_id") if event_elem is not None else "unknown_event")
        )

        gspec = root.find(f"{ns}grid_specification")
        if gspec is None:
            raise ValueError(f"Missing <grid_specification> in ShakeMap XML: {path}")

        lon_min = float(gspec.attrib["lon_min"])
        lat_min = float(gspec.attrib["lat_min"])
        lon_max = float(gspec.attrib["lon_max"])
        lat_max = float(gspec.attrib["lat_max"])
        dx = float(gspec.attrib.get("nominal_lon_spacing") or gspec.attrib.get("lon_spacing", 0.0))
        dy = float(gspec.attrib.get("nominal_lat_spacing") or gspec.attrib.get("lat_spacing", 0.0))
        nlon = int(gspec.attrib["nlon"])
        nlat = int(gspec.attrib["nlat"])

        # Discover field names and indices
        field_elems = root.findall(f"{ns}grid_field")
        fields_map: Dict[int, str] = {}
        for fe in field_elems:
            idx = int(fe.attrib["index"]) - 1  # 1-based index in XML
            fields_map[idx] = fe.attrib["name"].upper()

        data_elem = root.find(f"{ns}grid_data")
        if data_elem is None or not data_elem.text:
            raise ValueError(f"Missing or empty <grid_data> in ShakeMap XML: {path}")

        lines = [line.strip() for line in data_elem.text.strip().split("\n") if line.strip()]
        if len(lines) != nlon * nlat:
            raise ValueError(
                f"grid_data rows ({len(lines)}) != nlon * nlat ({nlon * nlat}) in {path}"
            )

        # Parse numerical lines
        raw_rows: List[List[float]] = []
        for line in lines:
            raw_rows.append([float(val) for val in line.split()])

        data_matrix = np.array(raw_rows)  # shape: (nlat * nlon, num_fields)

        # Determine MMI column index
        mmi_col = None
        for col_idx, col_name in fields_map.items():
            if col_name == "MMI":
                mmi_col = col_idx
                break
        if mmi_col is None:
            # Fallback: by ShakeMap convention, column 2 is MMI (0: LON, 1: LAT, 2: MMI)
            mmi_col = 2

        # In ShakeMap grid.xml, data is ordered row-by-row:
        # Row 0 is lat_max, down to row nlat-1 (lat_min)
        # Within each row, col 0 is lon_min to col nlon-1 (lon_max)
        mmi_2d = data_matrix[:, mmi_col].reshape((nlat, nlon))

        # Generate coordinate vectors matching row/col convention
        lons = np.linspace(lon_min, lon_max, nlon)
        lats = np.linspace(lat_max, lat_min, nlat)  # descending from north to south

        # Store other fields if available
        parsed_fields: Dict[str, np.ndarray] = {}
        for col_idx, col_name in fields_map.items():
            if col_idx < data_matrix.shape[1]:
                parsed_fields[col_name] = data_matrix[:, col_idx].reshape((nlat, nlon))

        grid = ShakeMapGrid(
            event_id=str(event_id),
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
            mmi=mmi_2d,
            source_file=str(path),
            source_format="xml",
            fields=parsed_fields,
        )
        grid.validate()
        return grid

    @staticmethod
    def load_shake_result_hdf(hdf_path: Union[Path, str]) -> ShakeMapGrid:
        """
        Parse USGS ShakeMap shake_result.hdf file into a ShakeMapGrid.
        Extracts continuous MMI ground motion raster and metadata.
        """
        try:
            import h5py
        except ImportError:
            raise ImportError(
                "h5py is required to parse shake_result.hdf. Install with 'pip install h5py'."
            )

        path = Path(hdf_path)
        if not path.exists():
            raise FileNotFoundError(f"ShakeMap shake_result.hdf not found at: {path}")

        with h5py.File(path, "r") as hf:
            # Locate MMI mean dataset
            # Canonical path: arrays/imts/GREATER_OF_TWO_HORIZONTAL/MMI/mean
            mmi_ds = None
            for candidate in [
                "arrays/imts/GREATER_OF_TWO_HORIZONTAL/MMI/mean",
                "arrays/imts/MMI/mean",
            ]:
                if candidate in hf:
                    mmi_ds = hf[candidate]
                    break

            if mmi_ds is None:
                raise ValueError(
                    f"Could not locate MMI mean dataset in {path}. "
                    f"Available groups: {list(hf.keys())}"
                )

            attrs = mmi_ds.attrs
            nlon = int(attrs.get("nx", mmi_ds.shape[1]))
            nlat = int(attrs.get("ny", mmi_ds.shape[0]))
            lon_min = float(attrs.get("xmin", 0.0))
            lon_max = float(attrs.get("xmax", 0.0))
            lat_min = float(attrs.get("ymin", 0.0))
            lat_max = float(attrs.get("ymax", 0.0))
            dx = float(attrs.get("dx", 0.0))
            dy = float(attrs.get("dy", 0.0))

            mmi_arr = mmi_ds[...].astype(float)

            # Discover event_id from dictionaries/info.json if present
            event_id = "unknown_event"
            if "dictionaries/info.json" in hf:
                try:
                    info_raw = hf["dictionaries/info.json"][()]
                    if isinstance(info_raw, bytes):
                        info_raw = info_raw.decode("utf-8")
                    info_dict = json.loads(info_raw)
                    event_id = (
                        info_dict.get("input", {}).get("event_information", {}).get("event_id")
                        or info_dict.get("event_id")
                        or event_id
                    )
                except Exception:
                    pass

        # In ShakeMap HDF5, row 0 is lat_max, row -1 is lat_min
        lons = np.linspace(lon_min, lon_max, nlon)
        lats = np.linspace(lat_max, lat_min, nlat)

        grid = ShakeMapGrid(
            event_id=str(event_id),
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
            mmi=mmi_arr,
            source_file=str(path),
            source_format="hdf",
        )
        grid.validate()
        return grid

    @classmethod
    def load_grid(cls, path_or_dir: Union[Path, str]) -> ShakeMapGrid:
        """
        Auto-detect and load ShakeMap grid from either a file path or directory.
        Prefers shake_result.hdf for floating-point fidelity, then grid.xml.
        """
        target = Path(path_or_dir)
        if target.is_dir():
            candidates = [
                target / "products" / "shake_result.hdf",
                target / "current" / "products" / "shake_result.hdf",
                target / "shake_result.hdf",
                target / "products" / "grid.xml",
                target / "current" / "products" / "grid.xml",
                target / "grid.xml",
            ]
            for c in candidates:
                if c.exists():
                    target = c
                    break

        if not target.exists():
            raise FileNotFoundError(f"Could not find valid ShakeMap product in: {path_or_dir}")

        if target.suffix.lower() in (".hdf", ".h5"):
            return cls.load_shake_result_hdf(target)
        elif target.suffix.lower() == ".xml":
            return cls.load_grid_xml(target)
        else:
            raise ValueError(f"Unsupported ShakeMap raster file format: {target.suffix} ({target})")

    @classmethod
    def validate_matching_grids(
        cls,
        baseline: ShakeMapGrid,
        augmented: ShakeMapGrid,
        tol: float = 1e-4,
    ) -> None:
        """
        Verify that two ShakeMap grids have identical dimensions, resolutions,
        and geographic extents within tolerance.

        Raises ValueError with explicit diagnostics if geometries differ.
        """
        if baseline.nlon != augmented.nlon or baseline.nlat != augmented.nlat:
            raise ValueError(
                f"Grid dimension mismatch: baseline is ({baseline.nlat}x{baseline.nlon}), "
                f"augmented is ({augmented.nlat}x{augmented.nlon})"
            )

        bounds_diffs = {
            "lon_min": abs(baseline.lon_min - augmented.lon_min),
            "lon_max": abs(baseline.lon_max - augmented.lon_max),
            "lat_min": abs(baseline.lat_min - augmented.lat_min),
            "lat_max": abs(baseline.lat_max - augmented.lat_max),
        }
        for bname, diff in bounds_diffs.items():
            if diff > tol:
                raise ValueError(
                    f"Grid extent mismatch in {bname}: baseline={getattr(baseline, bname)}, "
                    f"augmented={getattr(augmented, bname)} (diff={diff:.6f} > tol={tol})"
                )

        if abs(baseline.dx - augmented.dx) > tol or abs(baseline.dy - augmented.dy) > tol:
            raise ValueError(
                f"Grid resolution mismatch: baseline (dx={baseline.dx}, dy={baseline.dy}) vs "
                f"augmented (dx={augmented.dx}, dy={augmented.dy})"
            )

    @classmethod
    def compare_grids(
        cls,
        baseline: ShakeMapGrid,
        augmented: ShakeMapGrid,
        tol: float = 1e-4,
    ) -> GridComparisonResult:
        """
        Compare two validated ShakeMap grids:
            ΔMMI = MMI_augmented - MMI_baseline

        Calculates spatial metrics, quantiles, and surface area impacts.
        """
        cls.validate_matching_grids(baseline, augmented, tol=tol)

        # Compute signed intensity shift
        delta_mmi = augmented.mmi - baseline.mmi

        # Identify valid non-NaN cells
        valid_mask = ~(np.isnan(baseline.mmi) | np.isnan(augmented.mmi) | np.isnan(delta_mmi))
        valid_deltas = delta_mmi[valid_mask]

        cell_count_total = int(np.sum(valid_mask))
        if cell_count_total == 0:
            raise ValueError("No valid overlapping grid cells found between baseline and augmented grids.")

        mean_diff = float(np.mean(valid_deltas))
        mean_abs_diff = float(np.mean(np.abs(valid_deltas)))
        max_increase = float(np.max(valid_deltas))
        max_decrease = float(np.min(valid_deltas))

        # Count threshold exceedances
        cell_count_ge_05 = int(np.sum(np.abs(valid_deltas) >= 0.5))
        cell_count_ge_10 = int(np.sum(np.abs(valid_deltas) >= 1.0))

        # Calculate cell surface areas in km²
        # Latitudinal cell height dy_km: dy * 111.132 km/deg
        # Longitudinal cell width dx_km(lat): dx * 111.132 * cos(lat)
        dy_km = baseline.dy * 111.132
        lat_rads = np.radians(baseline.lats)
        dx_km_per_row = baseline.dx * 111.132 * np.cos(lat_rads)
        # 2D cell area grid (nlat, nlon)
        cell_areas_km2 = dy_km * dx_km_per_row[:, np.newaxis]
        cell_areas_km2 = np.broadcast_to(cell_areas_km2, delta_mmi.shape)

        valid_areas = cell_areas_km2[valid_mask]
        total_area_km2 = float(np.sum(valid_areas))

        mask_ge_05 = valid_mask & (np.abs(delta_mmi) >= 0.5)
        area_abs_ge_05_km2 = float(np.sum(cell_areas_km2[mask_ge_05]))

        mask_ge_10 = valid_mask & (np.abs(delta_mmi) >= 1.0)
        area_abs_ge_10_km2 = float(np.sum(cell_areas_km2[mask_ge_10]))

        # Quantiles of absolute difference
        p10, p25, p50, p75, p90, p99 = [
            float(q) for q in np.percentile(np.abs(valid_deltas), [10, 25, 50, 75, 90, 99])
        ]

        metrics = {
            "mean_difference": round(mean_diff, 5),
            "mean_absolute_difference": round(mean_abs_diff, 5),
            "max_increase": round(max_increase, 5),
            "max_decrease": round(max_decrease, 5),
            "cell_count_total": cell_count_total,
            "cell_count_ge_05": cell_count_ge_05,
            "cell_count_ge_10": cell_count_ge_10,
            "pct_cells_ge_05": round(100.0 * cell_count_ge_05 / cell_count_total, 3),
            "pct_cells_ge_10": round(100.0 * cell_count_ge_10 / cell_count_total, 3),
            "total_area_km2": round(total_area_km2, 2),
            "area_abs_ge_05_km2": round(area_abs_ge_05_km2, 2),
            "area_abs_ge_10_km2": round(area_abs_ge_10_km2, 2),
            "quantiles_abs_delta": {
                "p10": round(p10, 5),
                "p25": round(p25, 5),
                "p50": round(p50, 5),
                "p75": round(p75, 5),
                "p90": round(p90, 5),
                "p99": round(p99, 5),
            },
        }

        bounds = {
            "lon_min": baseline.lon_min,
            "lon_max": baseline.lon_max,
            "lat_min": baseline.lat_min,
            "lat_max": baseline.lat_max,
        }
        resolution = {
            "dx": baseline.dx,
            "dy": baseline.dy,
        }
        dimensions = {
            "nlon": baseline.nlon,
            "nlat": baseline.nlat,
        }

        return GridComparisonResult(
            baseline_event_id=baseline.event_id,
            augmented_event_id=augmented.event_id,
            bounds=bounds,
            resolution=resolution,
            dimensions=dimensions,
            metrics=metrics,
            lons=baseline.lons,
            lats=baseline.lats,
            mmi_baseline=baseline.mmi,
            mmi_augmented=augmented.mmi,
            delta_mmi=delta_mmi,
        )

    @classmethod
    def compare_files(
        cls,
        baseline_path: Union[Path, str],
        augmented_path: Union[Path, str],
        tol: float = 1e-4,
    ) -> GridComparisonResult:
        """
        Load two ShakeMap grid files/directories and compute their comparison.
        """
        base_grid = cls.load_grid(baseline_path)
        aug_grid = cls.load_grid(augmented_path)
        return cls.compare_grids(base_grid, aug_grid, tol=tol)
