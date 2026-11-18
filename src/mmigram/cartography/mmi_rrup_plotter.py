"""
MMI vs. Rupture Distance (Rrup) Visualization Engine.

Generates presentation-ready scatterplots and empirical attenuation diagnostics
for the Harvard EPS 55 research project, plotting Modified Mercalli Intensity against
finite-fault rupture distance (Rrup).

Scientific Integrity & Protocol:
1. Clear Distinction: Distinguishes accepted (ShakeMap-exportable) observations from
   flagged/review-required observations using distinct marker shapes and outlines.
2. Official USGS Comparison: Supports overlaying official USGS DYFI macroseismic stations
   and GMPE attenuation expectations from ShakeMap stationlist.json and attenuation_curves.json.
3. No Forced Regression: Avoids drawing ungrounded ad-hoc regression curves; GMPE curves are
   explicitly labeled as model expectations, not independent ground-truth observations.
4. Backing Data Export: Generates reproducible CSV and JSON data exports alongside PDF/PNG plots.
"""

from __future__ import annotations
import csv
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union

import matplotlib
matplotlib.use("Agg")  # Headless backend for reliable server/batch execution
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.colors import ListedColormap, BoundaryNorm


# Standard USGS ShakeMap MMI Discrete Color Palette (RGB)
SHAKEMAP_MMI_COLORS = [
    (1.0, 1.0, 1.0),       # MMI I: White
    (0.75, 0.80, 1.0),     # MMI II: Light Blue
    (0.50, 0.75, 1.0),     # MMI III: Sky Blue
    (0.40, 0.90, 0.85),    # MMI IV: Cyan
    (0.40, 0.90, 0.40),    # MMI V: Green
    (1.0, 1.0, 0.20),      # MMI VI: Yellow
    (1.0, 0.70, 0.10),      # MMI VII: Orange
    (1.0, 0.35, 0.10),      # MMI VIII: Red-Orange
    (0.90, 0.10, 0.10),    # MMI IX: Red
    (0.60, 0.05, 0.05),    # MMI X: Dark Red
    (0.45, 0.0, 0.15),     # MMI XI: Maroon
    (0.30, 0.0, 0.25),     # MMI XII: Purple
]

MMI_BOUNDARIES = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0]


def get_mmi_colormap():
    """Return discrete ListedColormap and BoundaryNorm for MMI 1-12."""
    cmap = ListedColormap(SHAKEMAP_MMI_COLORS)
    norm = BoundaryNorm(MMI_BOUNDARIES, cmap.N)
    return cmap, norm


class MMIRrupPlotter:
    """
    Plots MMI vs Rrup and exports backing tabular datasets.
    """

    def __init__(
        self,
        event_id: str = "us7000pn9s",
        event_name: str = "2025 Mw 7.7 Mandalay, Myanmar Earthquake",
        output_dir: Optional[Union[str, Path]] = None,
    ):
        self.event_id = event_id
        self.event_name = event_name
        self.default_output_dir = Path(output_dir) if output_dir else None

    def plot(
        self,
        observations: List[Dict[str, Any]],
        output_dir: Optional[Union[str, Path]] = None,
        plot_basename: str = "mmi_vs_rrup",
        official_stationlist: Optional[Dict[str, Any]] = None,
        attenuation_curves: Optional[Dict[str, Any]] = None,
        show_surface_rupture_band: bool = True,
        dyfi_stationlist: Optional[Dict[str, Any]] = None,
        base_filename: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Generate MMI vs. Rrup scatterplot and export CSV/JSON data files.

        Returns:
            Dictionary of created file paths: {"pdf": ..., "png": ..., "csv": ..., "json": ...}
        """
        target_dir = Path(output_dir) if output_dir is not None else (self.default_output_dir or Path("."))
        target_dir.mkdir(parents=True, exist_ok=True)

        effective_base = base_filename or plot_basename
        effective_dyfi = dyfi_stationlist or official_stationlist

        pdf_path = target_dir / f"{effective_base}.pdf"
        png_path = target_dir / f"{effective_base}.png"
        csv_path = target_dir / f"{effective_base}.csv"
        json_path = target_dir / f"{effective_base}.json"

        # ──────────────────────────────────────────────────────────────────────
        # Step 1: Filter and Classify Observations
        # ──────────────────────────────────────────────────────────────────────
        accepted_points: List[Dict[str, Any]] = []
        review_points: List[Dict[str, Any]] = []
        all_export_rows: List[Dict[str, Any]] = []

        for obs in observations:
            seis = obs.get("seismic_intensity", {})
            geo = obs.get("geographic_resolution", {})
            hitl = obs.get("human_in_the_loop", {})
            screening = obs.get("screening", {})

            mmi = seis.get("mmi_estimation")
            coords = geo.get("coordinates")
            rrup = geo.get("rrup_km")
            file_name = obs.get("file_name", "unknown")
            conf = seis.get("confidence")

            if mmi is None or rrup is None:
                continue

            can_export = geo.get("can_export_to_shakemap", False)
            review_required = hitl.get("review_required", False)
            review_status = hitl.get("review_status", "NOT_ENQUEUED")

            status = "ACCEPTED" if (can_export or review_status == "APPROVED") else "REVIEW_REQUIRED"

            row = {
                "file_name": file_name,
                "latitude": coords.get("latitude") if coords else None,
                "longitude": coords.get("longitude") if coords else None,
                "mmi_estimation": float(mmi),
                "confidence": float(conf) if conf is not None else None,
                "rrup_km": float(rrup),
                "status": status,
                "precision_level": geo.get("precision_level", "unknown"),
                "relevance_decision": screening.get("relevance_decision", "UNKNOWN"),
            }
            all_export_rows.append(row)

            if status == "ACCEPTED":
                accepted_points.append(row)
            else:
                review_points.append(row)

        # ──────────────────────────────────────────────────────────────────────
        # Step 2: Extract Official USGS DYFI & Seismic Stations if provided
        # ──────────────────────────────────────────────────────────────────────
        dyfi_points: List[Tuple[float, float]] = []  # (rrup, intensity)
        seismic_points: List[Tuple[float, float]] = []

        if effective_dyfi:
            for feat in effective_dyfi.get("features", []):
                props = feat.get("properties", {})
                stype = props.get("station_type", "")
                raw_int = props.get("intensity")
                raw_rrup = props.get("distances", {}).get("rrup") or props.get("distance")

                if raw_int is not None and raw_rrup is not None:
                    try:
                        f_int = float(raw_int)
                        f_rrup = float(raw_rrup)
                        if f_rrup > 0.0 and 1.0 <= f_int <= 12.0:
                            if stype == "macroseismic":
                                dyfi_points.append((f_rrup, f_int))
                            elif stype == "seismic":
                                seismic_points.append((f_rrup, f_int))
                    except (ValueError, TypeError):
                        pass

        # ──────────────────────────────────────────────────────────────────────
        # Step 3: Extract ShakeMap GMPE Attenuation Curve if provided
        # ──────────────────────────────────────────────────────────────────────
        gmpe_rrups: List[float] = []
        gmpe_mmis: List[float] = []

        if attenuation_curves:
            try:
                curves_data = attenuation_curves.get("curves", attenuation_curves)
                dist_array = curves_data.get("distances", {}).get("rrup", [])
                gmpe_mmi_array = (
                    curves_data.get("gmpe", {}).get("soil", {}).get("MMI", {}).get("mean", [])
                    or curves_data.get("mmi", {}).get("mean", [])
                )
                if dist_array and gmpe_mmi_array:
                    for d, m in zip(dist_array, gmpe_mmi_array):
                        if d > 0.0:
                            gmpe_rrups.append(float(d))
                            gmpe_mmis.append(float(m))
            except Exception:
                pass

        # ──────────────────────────────────────────────────────────────────────
        # Step 4: Matplotlib Figure Construction
        # ──────────────────────────────────────────────────────────────────────
        fig, ax = plt.subplots(figsize=(11, 7.5), dpi=300)

        # Subtle surface fault rupture zone highlight (< 1 km)
        if show_surface_rupture_band:
            ax.axvspan(0.05, 1.0, color="#fdf2e9", alpha=0.7, zorder=1, label="Surface Fault Rupture Zone (< 1 km)")

        # Plot GMPE theoretical attenuation curve if present
        if gmpe_rrups and gmpe_mmis:
            ax.plot(
                gmpe_rrups,
                gmpe_mmis,
                color="#4a5568",
                linestyle="--",
                linewidth=2.2,
                label="USGS ShakeMap GMPE (Soil Mean)",
                zorder=2,
            )

        # Plot official USGS DYFI macroseismic reports
        if dyfi_points:
            d_rrup = [p[0] for p in dyfi_points]
            d_mmi = [p[1] for p in dyfi_points]
            ax.scatter(
                d_rrup,
                d_mmi,
                marker="D",
                s=24,
                color="#a0aec0",
                edgecolors="#4a5568",
                linewidths=0.5,
                alpha=0.6,
                label=f"USGS DYFI Reports (n={len(dyfi_points)})",
                zorder=3,
            )

        # Plot Review-Required AI Observations
        if review_points:
            r_rrup = [p["rrup_km"] for p in review_points]
            r_mmi = [p["mmi_estimation"] for p in review_points]
            ax.scatter(
                r_rrup,
                r_mmi,
                marker="^",
                s=80,
                facecolors="#fffaf0",
                edgecolors="#dd6b20",
                linewidths=1.8,
                alpha=0.9,
                label=f"MMI-Gram Review Required (n={len(review_points)})",
                zorder=4,
            )

        # Plot Accepted & Qualified AI Observations
        if accepted_points:
            a_rrup = [p["rrup_km"] for p in accepted_points]
            a_mmi = [p["mmi_estimation"] for p in accepted_points]
            ax.scatter(
                a_rrup,
                a_mmi,
                marker="o",
                s=110,
                c=a_mmi,
                cmap=get_mmi_colormap()[0],
                norm=get_mmi_colormap()[1],
                edgecolors="#1a202c",
                linewidths=1.5,
                alpha=0.95,
                label=f"MMI-Gram Qualified Export (n={len(accepted_points)})",
                zorder=5,
            )

        # Axes Configuration
        ax.set_xscale("log")
        ax.set_xlim(0.08, 1200)
        ax.set_ylim(0.5, 12.5)

        ax.set_xlabel("Rupture Distance, $R_{rup}$ [km] (Closest 3D Distance to Fault Surface)", fontsize=13, labelpad=8)
        ax.set_ylabel("Modified Mercalli Intensity (MMI)", fontsize=13, labelpad=8)
        ax.set_title(f"MMI vs. Rupture Distance: {self.event_name} ({self.event_id})", fontsize=14, fontweight="bold", pad=12)

        # Y-Axis Ticks (Roman Numerals)
        roman_labels = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]
        ax.set_yticks(range(1, 13))
        ax.set_yticklabels([f"{r} ({i})" for i, r in enumerate(roman_labels, start=1)], fontsize=10)

        # Grid lines
        ax.grid(True, which="major", color="#e2e8f0", linestyle="-", linewidth=0.8, alpha=0.8)
        ax.grid(True, which="minor", color="#edf2f7", linestyle=":", linewidth=0.5, alpha=0.6)

        # Legend
        ax.legend(loc="lower left", framealpha=0.92, edgecolor="#cbd5e0", fontsize=10)

        # Save Plots
        plt.tight_layout()
        plt.savefig(pdf_path, format="pdf", bbox_inches="tight")
        plt.savefig(png_path, format="png", dpi=300, bbox_inches="tight")
        plt.close(fig)

        # ──────────────────────────────────────────────────────────────────────
        # Step 5: Export Backing Tabular CSV & JSON
        # ──────────────────────────────────────────────────────────────────────
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["file_name", "latitude", "longitude", "mmi_estimation", "confidence", "rrup_km", "status", "precision_level", "relevance_decision"],
            )
            writer.writeheader()
            for r in all_export_rows:
                writer.writerow(r)

        backing_json = {
            "event_id": self.event_id,
            "event_name": self.event_name,
            "counts": {
                "total_observations": len(all_export_rows),
                "accepted_qualified": len(accepted_points),
                "review_required": len(review_points),
                "usgs_dyfi_stations": len(dyfi_points),
            },
            "observations": all_export_rows,
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(backing_json, f, indent=2)

        return {
            "pdf": str(pdf_path),
            "png": str(png_path),
            "csv": str(csv_path),
            "json": str(json_path),
        }
