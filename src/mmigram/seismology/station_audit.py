"""
Station Audit and Distance Reconciliation Utility for USGS ShakeMap Inputs.

Provides reproducible auditing functions to:
1. Parse stationlist.json and classify macroseismic (DYFI) vs. instrumental seismic stations.
2. Separate observations with valid numeric MMI from unobserved (null) geocells.
3. Compute exact Repi (epicentral), Rhypo (hypocentral), and Rrup (finite-fault) distances.
4. Calculate distances to nearest features and nearest actually assimilated observations.
"""

from __future__ import annotations
import json
import math
import os
from typing import Dict, Any, List, Optional, Tuple

from mmigram.seismology.rrup_calculator import RrupCalculator

EARTH_RADIUS_KM = 6371.0088


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle surface distance between two points in km."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def audit_stationlist(
    stationlist_dict: Dict[str, Any],
    bounds: Optional[Tuple[float, float, float, float]] = None,
) -> Dict[str, Any]:
    """
    Audit features in a ShakeMap stationlist GeoJSON FeatureCollection.

    Args:
        stationlist_dict: Parsed stationlist GeoJSON dict.
        bounds: Optional (lat_min, lat_max, lon_min, lon_max) bounding box.

    Returns:
        Dictionary with exact feature counts and breakdowns.
    """
    features = stationlist_dict.get("features", [])
    total_count = len(features)

    dyfi_features = []
    seismic_features = []
    dyfi_valid_mmi = []
    dyfi_null_mmi = []

    for f in features:
        p = f.get("properties", {})
        coords = f.get("geometry", {}).get("coordinates", [])
        if len(coords) < 2:
            continue

        lon, lat = coords[0], coords[1]
        if bounds:
            lat_min, lat_max, lon_min, lon_max = bounds
            if not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max):
                continue

        net = p.get("network")
        is_dyfi = (net == "DYFI" or "DYFI" in str(p.get("source")))

        if is_dyfi:
            dyfi_features.append(f)
            val = p.get("intensity")
            if val is not None and val != "null":
                try:
                    fval = float(val)
                    if fval > 0:
                        dyfi_valid_mmi.append((f, fval))
                    else:
                        dyfi_null_mmi.append(f)
                except (ValueError, TypeError):
                    dyfi_null_mmi.append(f)
            else:
                dyfi_null_mmi.append(f)
        else:
            seismic_features.append(f)

    return {
        "total_stations": total_count if not bounds else len(dyfi_features) + len(seismic_features),
        "dyfi_total": len(dyfi_features),
        "dyfi_valid_mmi_count": len(dyfi_valid_mmi),
        "dyfi_null_mmi_count": len(dyfi_null_mmi),
        "seismic_total": len(seismic_features),
        "dyfi_valid_features": dyfi_valid_mmi,
        "dyfi_null_features": dyfi_null_mmi,
        "seismic_features": seismic_features,
    }


def compute_candidate_metrics(
    candidate_lat: float,
    candidate_lon: float,
    stationlist_dict: Dict[str, Any],
    rrup_calculator: RrupCalculator,
    hypo_depth_km: float = 10.0,
) -> Dict[str, Any]:
    """
    Compute Repi, Rhypo, Rrup, and distances to nearest features and nearest assimilated DYFI observations.
    """
    repi = rrup_calculator.calculate_repi(candidate_lat, candidate_lon)
    rrup = rrup_calculator.calculate_rrup(candidate_lat, candidate_lon)
    rhypo = math.hypot(repi, hypo_depth_km) if repi is not None else None

    features = stationlist_dict.get("features", [])

    closest_any_dist = float("inf")
    closest_any_feat = None

    closest_dyfi_val_dist = float("inf")
    closest_dyfi_val_feat = None
    closest_dyfi_val_mmi = None

    for f in features:
        coords = f.get("geometry", {}).get("coordinates", [])
        if len(coords) < 2:
            continue
        d = haversine_distance(candidate_lat, candidate_lon, coords[1], coords[0])

        if d < closest_any_dist:
            closest_any_dist = d
            closest_any_feat = f

        p = f.get("properties", {})
        is_dyfi = (p.get("network") == "DYFI" or "DYFI" in str(p.get("source")))
        val = p.get("intensity")
        if is_dyfi and val is not None and val != "null":
            try:
                fval = float(val)
                if fval > 0 and d < closest_dyfi_val_dist:
                    closest_dyfi_val_dist = d
                    closest_dyfi_val_feat = f
                    closest_dyfi_val_mmi = fval
            except (ValueError, TypeError):
                pass

    return {
        "candidate_lat": candidate_lat,
        "candidate_lon": candidate_lon,
        "repi_km": round(repi, 3) if repi is not None else None,
        "rhypo_km": round(rhypo, 3) if rhypo is not None else None,
        "rrup_km": round(rrup, 3) if rrup is not None else None,
        "nearest_feature_code": closest_any_feat["properties"].get("code") if closest_any_feat else None,
        "nearest_feature_dist_km": round(closest_any_dist, 3) if closest_any_feat else None,
        "nearest_feature_mmi": closest_any_feat["properties"].get("intensity") if closest_any_feat else None,
        "nearest_assimilated_dyfi_code": closest_dyfi_val_feat["properties"].get("code") if closest_dyfi_val_feat else None,
        "nearest_assimilated_dyfi_dist_km": round(closest_dyfi_val_dist, 3) if closest_dyfi_val_feat else None,
        "nearest_assimilated_dyfi_mmi": closest_dyfi_val_mmi,
    }
