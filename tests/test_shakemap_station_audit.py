"""
Tests for ShakeMap Station Inventory & Baseline DYFI Assimilation Reconciliation.

Verifies:
1. Exact parsing and categorization of USGS ShakeMap stationlist.json (macroseismic vs seismic).
2. Distinction between total station entries, entries in model bounds, and entries with valid observed MMI.
3. Repi (epicentral), Rhypo (hypocentral), and Rrup (finite-fault) distance calculations.
4. Correct identification of nearest assimilated macroseismic observations versus unobserved (null) geocells.
5. Functions in mmigram.seismology.station_audit module.
"""

import json
import math
import os
import pytest
from mmigram.seismology.rrup_calculator import RrupCalculator
from mmigram.seismology.station_audit import audit_stationlist, compute_candidate_metrics, haversine_distance


def test_stationlist_reconciliation_total_and_types():
    """Verify the exact breakdown of features in data/events/us7000pn9s/usgs/stationlist.json."""
    sta_path = "data/events/us7000pn9s/usgs/stationlist.json"
    if not os.path.exists(sta_path):
        pytest.skip("Local stationlist.json not available")

    with open(sta_path) as f:
        data = json.load(f)

    audit_res = audit_stationlist(data)
    assert audit_res["total_stations"] == 1250
    assert audit_res["dyfi_total"] == 1244
    assert audit_res["seismic_total"] == 6
    assert audit_res["dyfi_valid_mmi_count"] == 191
    assert audit_res["dyfi_null_mmi_count"] == 1053


def test_distance_metrics_repi_rhypo_rrup():
    """Verify distinct definitions and values for Repi, Rhypo, and Rrup."""
    rup_path = "data/events/us7000pn9s/usgs/rupture.json"
    if not os.path.exists(rup_path):
        pytest.skip("Local rupture.json not available")

    with open(rup_path) as f:
        rup_geo = json.load(f)

    rrup_calc = RrupCalculator(rupture_geojson=rup_geo)

    # Hypocenter from rupture metadata: lat=22.011, lon=95.9363, depth=10.0 km
    hypo_depth = 10.0

    # Test candidate P-02: Pyawbwe (20.589678, 96.05242)
    lat, lon = 20.589678, 96.05242
    repi = rrup_calc.calculate_repi(lat, lon)
    rrup = rrup_calc.calculate_rrup(lat, lon)
    rhypo = math.hypot(repi, hypo_depth)

    # Repi is epicentral surface distance (~158.5 km)
    assert 158.0 < repi < 159.0
    # Rhypo is 3D distance to hypocenter (> Repi)
    assert rhypo > repi
    assert 158.5 < rhypo < 159.5
    # Rrup is finite-fault distance to nearest point on 450-km rupture surface (~1.27 km)
    assert rrup < 2.0
    assert abs(rrup - 1.268) < 0.05

    # Test candidate P-03: Pyinmana Township centroid (19.73814, 96.21157)
    repi_p03 = rrup_calc.calculate_repi(19.73814, 96.21157)
    rrup_p03 = rrup_calc.calculate_rrup(19.73814, 96.21157)
    assert 253.0 < repi_p03 < 255.0
    assert 4.0 < rrup_p03 < 4.5


def test_nearest_assimilated_dyfi_identification():
    """Verify that unobserved (null MMI) DYFI geocells are not treated as assimilated observations."""
    sta_path = "data/events/us7000pn9s/usgs/stationlist.json"
    rup_path = "data/events/us7000pn9s/usgs/rupture.json"
    if not os.path.exists(sta_path) or not os.path.exists(rup_path):
        pytest.skip("Local stationlist.json or rupture.json not available")

    with open(sta_path) as f:
        sta_data = json.load(f)
    with open(rup_path) as f:
        rup_geo = json.load(f)

    rrup_calc = RrupCalculator(rupture_geojson=rup_geo)

    # Candidate P-02: Pyawbwe (20.589678, 96.05242)
    metrics_p02 = compute_candidate_metrics(20.589678, 96.05242, sta_data, rrup_calc)

    # Closest feature is UTM:(47Q 0192 2310 1000) at ~31.092 km with intensity: null
    assert metrics_p02["nearest_feature_code"] == "UTM:(47Q 0192 2310 1000)"
    assert metrics_p02["nearest_feature_mmi"] in [None, "null"]
    assert 31.0 < metrics_p02["nearest_feature_dist_km"] < 31.2

    # Closest ASSIMILATED DYFI feature is UTM:(46Q 0797 2311 1000) at 38.005 km with valid MMI 8.5
    assert metrics_p02["nearest_assimilated_dyfi_code"] == "UTM:(46Q 0797 2311 1000)"
    assert metrics_p02["nearest_assimilated_dyfi_mmi"] == 8.5
    assert 37.9 < metrics_p02["nearest_assimilated_dyfi_dist_km"] < 38.1
