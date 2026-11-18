"""
Offline regression tests for Stage 4B Workflow B: P-02 ShakeMap Sensitivity Experiment.

Verifies:
1. GeoJSON observation format contract and exploratory sensitivity provenance metadata.
2. Isolated workspace preparation, configuration replication, and checksum integrity.
3. Numerical precision and spatial interpolation consistency on regular grids.
4. Distance calculation and radial decay binning logic.
5. Ingestion of single macroseismic observation into ShakeMap result schema (+1 station delta).
"""

import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import xml.etree.ElementTree as ET
import numpy as np
import pytest

from mmigram.seismology.sensitivity_runner import (
    compute_sha256,
    create_scenario_observation_geojson,
    prepare_scenario_workspace,
    interpolate_point_on_grid,
    compute_cell_areas_km2,
    compute_grid_distances_km,
    compute_radial_decay_profile,
    compute_scenario_spatial_metrics,
)


class TestSensitivityObservationContract:
    """Verifies that the sensitivity observation GeoJSON adheres to strict provenance rules."""

    def test_exploratory_metadata_and_safeguards(self):
        obs = create_scenario_observation_geojson(
            scenario_id="us7000pn9s_p02_mmi85",
            target_mmi=8.5,
            stddev=0.50,
            candidate_id="P-02",
            code="71be4246",
        )
        assert obs["type"] == "FeatureCollection"
        meta = obs["metadata"]
        assert meta["dataset_type"] == "exploratory_sensitivity_test"
        assert meta["scientific_use_allowed"] is False
        assert meta["expert_approved"] is False
        assert meta["hypothetical_input_mmi"] == 8.5
        assert meta["experimental_sigma_assumption"] == 0.50
        assert meta["candidate_id"] == "P-02"

        features = obs["features"]
        assert len(features) == 1
        feat = features[0]
        assert feat["type"] == "Feature"
        assert feat["id"] == "MMI.71be4246"
        props = feat["properties"]
        assert props["code"] == "71be4246"
        assert props["network"] == "MMI"
        assert props["station_type"] == "macroseismic"
        assert props["intensity"] == 8.5
        assert props["intensity_stddev"] == 0.50
        assert props["intensity_flag"] == "0"
        assert props["expert_approved"] is False
        assert props["nresp"] is None, "Single reconnaissance observation must have nresp=None, never fabricated response count"
        assert meta["observation_provenance"] == "single_reconnaissance_assessment"
        assert meta["dyfi_response_aggregation"] == "not_applicable"

        # GeoJSON Point coordinates: [longitude, latitude]
        coords = feat["geometry"]["coordinates"]
        assert coords[0] == pytest.approx(96.052420, abs=1e-5)
        assert coords[1] == pytest.approx(20.589678, abs=1e-5)

    def test_no_fabricated_nresp_in_exporter(self, tmp_path):
        """Verifies that ShakeMapExporter sets nresp=None for single macroseismic observations."""
        from mmigram.seismology.shakemap_exporter import ShakeMapExporter
        exporter = ShakeMapExporter(event_id="test_event")
        obs_input = [{
            "file_name": "page-76.pdf",
            "content_id": "test_id",
            "seismic_intensity": {"mmi_estimation": 8.5, "confidence": 0.90},
            "geographic_resolution": {
                "coordinates": {"latitude": 20.589678, "longitude": 96.052420},
                "has_valid_coordinates": True,
                "has_exportable_site_coordinates": True,
                "can_export_to_shakemap": True,
                "precision_level": "site_specific_address",
                "coordinates_disagree": False,
                "location": {"site_name": "KBZ Bank Pyawbwe"},
                "rrup_km": 1.268,
            },
            "screening": {"relevance_decision": "ESTIMABLE"},
            "quality_control": {"status": "PASSED"},
            "human_in_the_loop": {"review_required": False, "review_status": "NOT_ENQUEUED"},
        }]
        res = exporter.export_observations(obs_input, output_dir=tmp_path)
        assert res["exported_count"] == 1, f"Observation was excluded: {res}"
        with open(res["export_file"], "r", encoding="utf-8") as f:
            feat_coll = json.load(f)
        feat = feat_coll["features"][0]
        assert feat["properties"]["nresp"] is None, (
            "ShakeMapExporter must set nresp=None for single reconnaissance observations, "
            "allowing ShakeMap to use a.nresp < 0 without fabricating respondents"
        )
        assert feat["properties"]["intensity_flag"] == "0"


class TestWorkspaceIsolationAndIntegrity:
    """Tests isolated scenario workspace creation without mutating baseline files."""

    def test_prepare_scenario_workspace_isolation(self, tmp_path):
        base_dir = tmp_path / "baseline"
        scen_dir = tmp_path / "scenario_mmi80"
        base_dir.mkdir()

        # Create dummy baseline files
        event_xml_content = (
            '<?xml version="1.0" encoding="US-ASCII" standalone="yes"?>\n'
            '<earthquake id="us7000pn9s" lat="22.011" lon="95.9363" mag="7.7" '
            'time="2025-03-28T06:20:52.715Z" depth="10.0" locstring="Myanmar" '
            'mech="SS" netid="us" network="US" />'
        )
        (base_dir / "event.xml").write_text(event_xml_content)
        (base_dir / "model.conf").write_text("[gmpe]\ngmpe = active_crustal_nshmp2014\n")
        (base_dir / "rupture.json").write_text('{"type": "FeatureCollection", "features": []}')
        (base_dir / "stationlist.json").write_text('{"type": "FeatureCollection", "features": []}')

        base_event_hash_before = compute_sha256(str(base_dir / "event.xml"))

        res = prepare_scenario_workspace(
            baseline_current_dir=str(base_dir),
            scenario_current_dir=str(scen_dir),
            scenario_id="us7000pn9s_p02_mmi80",
            target_mmi=8.0,
            stddev=0.50,
        )

        # Baseline must remain completely unchanged
        assert compute_sha256(str(base_dir / "event.xml")) == base_event_hash_before

        # Scenario event.xml must have new scenario id
        tree = ET.parse(str(scen_dir / "event.xml"))
        root = tree.getroot()
        eq = root if root.tag == "earthquake" else root.find("earthquake")
        assert eq.attrib["id"] == "us7000pn9s_p02_mmi80"
        assert eq.attrib["time"] == "2025-03-28T06:20:52.715Z"

        # Checksum tracking returned
        checksums = res["input_checksums"]
        assert "event.xml" in checksums
        assert "agent_mmi_dat.json" in checksums
        assert "model.conf" in checksums
        assert os.path.exists(str(scen_dir / "agent_mmi_dat.json"))


class TestSpatialInterpolationAndMetrics:
    """Verifies bilinear and nearest interpolation and spatial area computations."""

    def test_interpolate_point_on_grid(self):
        # 3x3 grid spanning lat [22, 20], lon [95, 97]
        lats = np.array([22.0, 21.0, 20.0])
        lons = np.array([95.0, 96.0, 97.0])
        mmi = np.array([
            [6.0, 7.0, 8.0],
            [7.0, 8.0, 9.0],
            [8.0, 9.0, 10.0],
        ])

        # Point exactly on center cell (21.0, 96.0)
        pt_center = interpolate_point_on_grid(mmi, lats, lons, 21.0, 96.0)
        assert pt_center["nearest"] == pytest.approx(8.0, abs=1e-3)
        assert pt_center["bilinear"] == pytest.approx(8.0, abs=1e-3)

        # Point halfway between center and bottom right (20.5, 96.5)
        pt_mid = interpolate_point_on_grid(mmi, lats, lons, 20.5, 96.5)
        # In bilinear: (8.0 + 9.0 + 9.0 + 10.0) / 4 = 9.0
        assert pt_mid["bilinear"] == pytest.approx(9.0, abs=1e-3)

    def test_grid_distances_and_radial_decay(self):
        lats = np.array([21.0, 20.0])
        lons = np.array([96.0, 97.0])
        dist = compute_grid_distances_km(lats, lons, 21.0, 96.0)
        assert dist.shape == (2, 2)
        assert dist[0, 0] == pytest.approx(0.0, abs=1e-2)
        # 1 degree of latitude is ~111 km
        assert dist[1, 0] == pytest.approx(111.19, abs=1.5)

        # Radial decay profile
        delta = np.array([[-1.0, -0.5], [-0.3, 0.0]])
        bins = [(0.0, 10.0), (10.0, 160.0)]
        profile = compute_radial_decay_profile(dist, delta, bins=bins)
        assert len(profile) == 2
        assert profile[0]["cell_count"] == 1
        assert profile[0]["mean_delta_mmi"] == -1.0
        assert profile[1]["cell_count"] == 3


class TestCompletedSensitivityArtifacts:
    """Verifies existence and consistency of generated experiment artifacts if present."""

    def test_master_manifest_integrity_if_completed(self):
        manifest_path = "data/events/us7000pn9s/sensitivity_p02/sensitivity_experiment_manifest.json"
        if not os.path.exists(manifest_path):
            pytest.skip("Sensitivity experiment has not been executed yet in this workspace.")

        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["event_id"] == "us7000pn9s"
        assert data["earthquake_origin_time"] == "2025-03-28T06:20:52.715Z"
        assert data["observation_target"]["candidate_id"] == "P-02"
        assert data["experimental_safeguards"]["scientific_use_allowed"] is False
        assert "scenarios" in data
        assert "mmi80" in data["scenarios"]
        assert "mmi85" in data["scenarios"]
        assert "mmi90" in data["scenarios"]

        # Check monotonicity at site
        s80 = data["scenarios"]["mmi80"]["metrics"]["augmented_mmi_at_site"]["bilinear"]
        s85 = data["scenarios"]["mmi85"]["metrics"]["augmented_mmi_at_site"]["bilinear"]
        s90 = data["scenarios"]["mmi90"]["metrics"]["augmented_mmi_at_site"]["bilinear"]
        assert s80 < s85 < s90, f"Expected monotonic response: {s80} < {s85} < {s90}"

    def test_semantic_event_parameters_matching(self):
        manifest_path = "data/events/us7000pn9s/sensitivity_p02/sensitivity_experiment_manifest.json"
        if not os.path.exists(manifest_path):
            pytest.skip("Sensitivity experiment has not been executed yet in this workspace.")

        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert "physical_parameters_comparison" in data
        params = data["physical_parameters_comparison"]
        assert params["earthquake_origin_time"] == "2025-03-28T06:20:52.715Z"
        assert params["latitude"] == pytest.approx(22.011, abs=1e-4)
        assert params["longitude"] == pytest.approx(95.9363, abs=1e-4)
        assert params["magnitude"] == pytest.approx(7.7, abs=1e-2)
        assert params["depth_km"] == pytest.approx(10.0, abs=1e-2)
        assert params["mechanism"] == "SS"

        for k in ["mmi80", "mmi85", "mmi90"]:
            assert params["scenarios_verified"][k]["event_xml_physical_params_match"] is True
            assert params["scenarios_verified"][k]["rupture_json_sha256_match"] is True
            assert params["scenarios_verified"][k]["stationlist_json_sha256_match"] is True
            assert params["scenarios_verified"][k]["model_conf_sha256_match"] is True

    def test_shakemap_internal_assimilation_nresp_minus_one(self):
        """
        Integration test verifying ShakeMap 4.5's internal SQLite amplitude database
        and products/shake_result.hdf store nresp=-1 for the single unaggregated
        macroseismic reconnaissance observation (satisfying a.nresp < 0 natively).
        """
        import h5py
        profile_root = Path(os.path.expanduser("~/shakemap_profiles/myanmar_recon/data"))
        scenario_dir = profile_root / "us7000pn9s_p02_mmi80" / "current"
        shake_data_file = scenario_dir / "shake_data.hdf"
        shake_result_file = scenario_dir / "products" / "shake_result.hdf"

        if not shake_data_file.exists() or not shake_result_file.exists():
            pytest.skip("ShakeMap scenario HDF files not present in local profile environment.")

        # 1. Verify shake_data.hdf SQLite dump contains nresp = -1 in amp table
        with h5py.File(shake_data_file, "r") as h5:
            sql_text = h5["strings"]["stations"][()].decode("utf-8")

        amp_lines = [l for l in sql_text.splitlines() if "MMI.71be4246" in l and "amp" in l]
        assert len(amp_lines) == 1, f"Expected 1 amp record for P-02, found: {amp_lines}"
        # Expected: INSERT INTO "amp" VALUES(1,'MMI.71be4246',3,'mmi','h',8.0,0.5,-1,'0');
        amp_record = amp_lines[0]
        assert "8.0,0.5,-1,'0'" in amp_record, (
            f"Expected intensity 8.0, sigma 0.5, nresp -1, flag '0'. Found: {amp_record}"
        )

        # 2. Verify products/shake_result.hdf stations_dict
        with h5py.File(shake_result_file, "r") as h5:
            stations_raw = h5["dictionaries"]["stations_dict"][()].decode("utf-8")
            stations_json = json.loads(stations_raw)

        p02_stations = [
            f for f in stations_json["features"]
            if f.get("properties", {}).get("code") == "71be4246" or "71be4246" in f.get("id", "")
        ]
        assert len(p02_stations) == 1, "P-02 station not found in shake_result.hdf stations_dict"
        props = p02_stations[0]["properties"]
        assert props["intensity"] == 8.0
        assert props["intensity_stddev"] == 0.5
        assert props["intensity_flag"] == "0"
        assert props["nresp"] == -1, f"Expected nresp=-1, got {props.get('nresp')}"
        assert props["station_type"] == "macroseismic"
        assert len(stations_json["features"]) == 522, "Expected exactly 522 stations (521 baseline + 1 P-02)"
