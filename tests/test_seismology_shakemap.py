"""
Tests for Seismological Consistency, Finite-Fault Rrup Calculation,
USGS ShakeMap Data Integration, and ShakeMap 4.5 Observation Export (Stage 4A).

All 16 test cases execute strictly offline with ZERO paid API calls, ZERO external network requests,
and 100% mocked / fixture-backed data.
"""

import json
import math
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Any, List
import pytest

from mmigram.core.state import (
    Coordinates,
    LocationContext,
    MMIEstimationResult,
    StructuralDamageAssessment,
    EvidenceMetadata,
)
from mmigram.seismology.usgs_products import USGSProductProvider
from mmigram.seismology.rrup_calculator import (
    RrupCalculator,
    geodetic_to_enu_point,
    point_triangle_distance_3d,
)
from mmigram.seismology.physics_critic import (
    PhysicsCritic,
    SeismologicalConsistencyResult,
)
from mmigram.seismology.shakemap_exporter import (
    ShakeMapExporter,
    UncertaintyStrategy,
    validate_shakemap_geojson,
)
from mmigram.cartography.mmi_rrup_plotter import MMIRrupPlotter
from mmigram.workflow.general_steer_pipeline import GeneralSteerPipeline


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "usgs"


# ─────────────────────────────────────────────────────────────────────────────
# 1. Valid USGS Event Metadata Retrieval & Parsing
# ─────────────────────────────────────────────────────────────────────────────
def test_1_valid_usgs_event_metadata_retrieval_and_parsing(tmp_path):
    """Verify USGSProductProvider parses event metadata and updates local manifest."""
    provider = USGSProductProvider(cache_dir=tmp_path, allow_live_download=False)

    sample_meta = {
        "id": "us7000pn9s",
        "properties": {
            "title": "M 7.7 - 2025 Mandalay, Burma (Myanmar) Earthquake",
            "mag": 7.7,
            "time": 1743142852715,
            "place": "16 km NNW of Mandalay, Myanmar",
        },
        "geometry": {
            "coordinates": [95.9363, 22.011, 10.0]
        }
    }
    provider.register_mock_product("us7000pn9s", "event_summary", sample_meta)
    provider.save_product("us7000pn9s", "event_summary", sample_meta)

    meta = provider.get_event_metadata("us7000pn9s")
    assert meta is not None
    assert meta["event_id"] == "us7000pn9s"
    assert meta["magnitude"] == 7.7
    assert meta["latitude"] == 22.011
    assert meta["longitude"] == 95.9363
    assert meta["depth_km"] == 10.0
    assert "Mandalay" in meta["description"]

    # Verify manifest.json exists and has sha256 checksum
    manifest_file = provider.get_manifest_path("us7000pn9s")
    assert manifest_file.exists()
    with open(manifest_file, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    assert "event_summary.json" in manifest["products"]
    assert "sha256" in manifest["products"]["event_summary.json"]


# ─────────────────────────────────────────────────────────────────────────────
# 2. Missing USGS Products Graceful Handling
# ─────────────────────────────────────────────────────────────────────────────
def test_2_missing_usgs_products_graceful_handling(tmp_path):
    """Verify provider returns None gracefully without crashing when products are missing."""
    provider = USGSProductProvider(cache_dir=tmp_path, allow_live_download=False)

    assert provider.get_event_metadata("non_existent_event_9999") is None
    assert provider.get_rupture("non_existent_event_9999") is None
    assert provider.get_stationlist("non_existent_event_9999") is None
    assert provider.get_attenuation_curves("non_existent_event_9999") is None


# ─────────────────────────────────────────────────────────────────────────────
# 3. Cached Product Reuse Without Extra Requests
# ─────────────────────────────────────────────────────────────────────────────
def test_3_cached_product_reuse_without_extra_requests(tmp_path):
    """Verify that cached products are loaded from disk without re-requesting."""
    provider = USGSProductProvider(cache_dir=tmp_path, allow_live_download=False)

    sample_data = {"type": "FeatureCollection", "features": [{"type": "Feature"}]}
    provider.save_product("us7000pn9s", "rupture.json", sample_data)

    # First fetch from cache
    res1 = provider.get_rupture("us7000pn9s")
    assert res1 is not None

    # Second fetch from cache
    res2 = provider.get_rupture("us7000pn9s")
    assert res2 == res1


# ─────────────────────────────────────────────────────────────────────────────
# 4. Rupture Geometry Parsing (Polygon and MultiPolygon)
# ─────────────────────────────────────────────────────────────────────────────
def test_4_rupture_geometry_parsing():
    """Verify quad-to-triangle mesh decomposition for Polygon and MultiPolygon."""
    # 1. Single Polygon quad
    polygon_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [96.0, 21.0, 0.0],
                            [96.1, 21.0, 0.0],
                            [96.1, 21.1, 10.0],
                            [96.0, 21.1, 10.0],
                            [96.0, 21.0, 0.0],
                        ]
                    ]
                }
            }
        ]
    }
    calc_poly = RrupCalculator(rupture_geojson=polygon_geojson)
    assert calc_poly.has_rupture
    # Exactly 2 triangles from 1 quad
    assert len(calc_poly.mesh_triangles) == 2

    # 2. MultiPolygon (2 quads)
    multipolygon_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [
                            [
                                [96.0, 21.0, 0.0],
                                [96.1, 21.0, 0.0],
                                [96.1, 21.1, 10.0],
                                [96.0, 21.1, 10.0],
                                [96.0, 21.0, 0.0],
                            ]
                        ],
                        [
                            [
                                [96.1, 21.0, 0.0],
                                [96.2, 21.0, 0.0],
                                [96.2, 21.1, 10.0],
                                [96.1, 21.1, 10.0],
                                [96.1, 21.0, 0.0],
                            ]
                        ]
                    ]
                }
            }
        ]
    }
    calc_multi = RrupCalculator(rupture_geojson=multipolygon_geojson)
    assert calc_multi.has_rupture
    assert len(calc_multi.mesh_triangles) == 4


# ─────────────────────────────────────────────────────────────────────────────
# 5. Analytically Verifiable Rrup Calculations on Simple Planar Faults
# ─────────────────────────────────────────────────────────────────────────────
def test_5_analytically_verifiable_rrup_synthetic_planar_fault():
    """
    Test Rrup on synthetic faults where the exact mathematical distance is known analytically.
    """
    # Create a synthetic vertical surface-rupturing fault along longitude 96.0000,
    # from latitude 21.0000 to 22.0000, dipping vertically from depth 0 to 15 km.
    vert_fault = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [96.0000, 21.0000, 0.0],
                            [96.0000, 22.0000, 0.0],
                            [96.0000, 22.0000, 15.0],
                            [96.0000, 21.0000, 15.0],
                            [96.0000, 21.0000, 0.0],
                        ]
                    ]
                }
            }
        ]
    }
    calc = RrupCalculator(rupture_geojson=vert_fault)

    # Point A: Exactly on the surface trace at (21.5000, 96.0000)
    # Expected Rrup = 0.0 km
    rrup_a = calc.calculate_rrup(21.5000, 96.0000)
    assert rrup_a is not None
    assert abs(rrup_a - 0.0) < 0.001

    # Point B: Offset horizontally along latitude 21.5000 by 10 km to the east
    # At latitude 21.5, 1 deg lon = cos(21.5 * pi / 180) * 111.3195 km = 103.559 km
    # Offset of 10 km = 10.0 / 103.559 = 0.09656 degrees
    lon_offset = 96.0000 + (10.0 / (111.3195 * math.cos(math.radians(21.5))))
    rrup_b = calc.calculate_rrup(21.5000, lon_offset)
    assert rrup_b is not None
    assert abs(rrup_b - 10.0) < 0.05  # Within 50 meters

    # Now test a horizontal fault buried at depth = 10.0 km, from (21.0, 96.0) to (22.0, 97.0)
    horiz_fault = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [96.0000, 21.0000, 10.0],
                            [97.0000, 21.0000, 10.0],
                            [97.0000, 22.0000, 10.0],
                            [96.0000, 22.0000, 10.0],
                            [96.0000, 21.0000, 10.0],
                        ]
                    ]
                }
            }
        ]
    }
    calc_horiz = RrupCalculator(rupture_geojson=horiz_fault)

    # Point C: Surface point directly above the center of the buried fault (depth = 0.0 km)
    # Expected Rrup = exactly 10.0 km
    rrup_c = calc_horiz.calculate_rrup(21.5000, 96.5000, site_depth_km=0.0)
    assert rrup_c is not None
    assert abs(rrup_c - 10.0) < 0.05

    # Point D: Subsurface point at depth 10.0 km on the buried fault
    # Expected Rrup = exactly 0.0 km
    rrup_d = calc_horiz.calculate_rrup(21.5000, 96.5000, site_depth_km=10.0)
    assert rrup_d is not None
    assert abs(rrup_d - 0.0) < 0.001


# ─────────────────────────────────────────────────────────────────────────────
# 6. Multiple Fault Segments & Segment Junction Behavior
# ─────────────────────────────────────────────────────────────────────────────
def test_6_multiple_fault_segments_and_junction_behavior():
    """Verify continuous distance computation across multi-segment faults."""
    # Two connected segments sharing a junction node at (21.5, 96.0)
    two_segments = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        # Segment 1 (South): from 21.0 to 21.5
                        [
                            [
                                [96.0, 21.0, 0.0],
                                [96.0, 21.5, 0.0],
                                [96.0, 21.5, 10.0],
                                [96.0, 21.0, 10.0],
                                [96.0, 21.0, 0.0],
                            ]
                        ],
                        # Segment 2 (North): from 21.5 to 22.0 (bending slightly east)
                        [
                            [
                                [96.0, 21.5, 0.0],
                                [96.2, 22.0, 0.0],
                                [96.2, 22.0, 10.0],
                                [96.0, 21.5, 10.0],
                                [96.0, 21.5, 0.0],
                            ]
                        ]
                    ]
                }
            }
        ]
    }
    calc = RrupCalculator(rupture_geojson=two_segments)
    assert calc.has_rupture

    # Point exactly at the junction: Rrup must be 0.0
    rrup_junc = calc.calculate_rrup(21.5, 96.0)
    assert rrup_junc is not None
    assert abs(rrup_junc - 0.0) < 0.001

    # Point near both segments selects minimum without discontinuities
    rrup_p = calc.calculate_rrup(21.55, 96.05)
    assert rrup_p is not None
    assert rrup_p > 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 7. Missing Rupture Geometry Preserves rrup_km: null and Provides repi_km
# ─────────────────────────────────────────────────────────────────────────────
def test_7_missing_rupture_geometry_preserves_rrup_null_and_provides_repi():
    """
    CRITICAL SCIENTIFIC SAFEGUARD:
    When finite-fault rupture is unavailable, RrupCalculator must NEVER substitute
    epicentral distance for Rrup. It must return rrup_km: None and separately labeled repi_km.
    """
    calc = RrupCalculator(rupture_geojson=None, origin_lat=22.0000, origin_lon=96.0000)
    assert not calc.has_rupture

    distances = calc.calculate_distances(22.5000, 96.0000)
    assert distances["rrup_km"] is None  # Must NOT be fabricated
    assert distances["repi_km"] is not None
    assert abs(distances["repi_km"] - 55.6) < 1.0  # ~0.5 deg lat is ~55.6 km
    assert distances["distance_source"] == "hypocenter_alternative"

    # Physics critic should also preserve this
    critic = PhysicsCritic(rrup_calculator=calc)
    crit_res = critic.evaluate_observation(mmi=7.0, latitude=22.5, longitude=96.0)
    assert crit_res.rrup_km is None
    assert crit_res.repi_km is not None
    assert crit_res.rupture_distance_source == "hypocenter_alternative"


# ─────────────────────────────────────────────────────────────────────────────
# 8. Valid ShakeMap GeoJSON Output Conforming to ShakeMap 4.5 Specs
# ─────────────────────────────────────────────────────────────────────────────
def test_8_valid_shakemap_geojson_output_spec(tmp_path):
    """Verify exported agent_mmi_dat.json complies with USGS ShakeMap 4.5 GeoJSON standard."""
    exporter = ShakeMapExporter(output_dir=tmp_path, event_id="us7000pn9s", agency_name="MMI-Gram-Agent")

    sample_results = [
        {
            "file_name": "obs_01.pdf",
            "seismic_intensity": {"mmi_estimation": 7.5, "confidence": 0.85},
            "geographic_resolution": {
                "coordinates": {"latitude": 21.95, "longitude": 96.08},
                "has_valid_coordinates": True,
                "has_exportable_site_coordinates": True,
                "can_export_to_shakemap": True,
                "precision_level": "site_specific_address",
                "coordinates_disagree": False,
                "location": {"site_name": "Mandalay Central Hospital", "address": "78th St, Mandalay"},
            },
            "screening": {"relevance_decision": "ESTIMABLE"},
            "quality_control": {"status": "PASSED"},
            "human_in_the_loop": {"review_required": False, "review_status": "NOT_ENQUEUED"},
        }
    ]

    export_res = exporter.export_observations(sample_results)
    assert export_res["exported_count"] == 1
    assert export_res["excluded_count"] == 0

    out_file = tmp_path / "agent_mmi_dat.json"
    assert out_file.exists()

    with open(out_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Validate schema
    is_valid, errors = validate_shakemap_geojson(data)
    assert is_valid, f"ShakeMap GeoJSON validation failed: {errors}"

    feature = data["features"][0]
    assert feature["geometry"]["type"] == "Point"
    assert feature["properties"]["intensity"] == 7.5
    assert feature["properties"]["intensity_stddev"] == 0.50
    assert feature["properties"]["agency"] == "MMI-Gram-Agent"
    assert feature["properties"]["station_type"] == "macroseismic"


# ─────────────────────────────────────────────────────────────────────────────
# 9. Correct Geographic Coordinate Order [longitude, latitude]
# ─────────────────────────────────────────────────────────────────────────────
def test_9_correct_geographic_coordinate_order(tmp_path):
    """Verify coordinate order in ShakeMap GeoJSON is strictly [longitude, latitude]."""
    exporter = ShakeMapExporter(output_dir=tmp_path, event_id="us7000pn9s")

    sample = [
        {
            "file_name": "site_test.pdf",
            "seismic_intensity": {"mmi_estimation": 8.0, "confidence": 0.90},
            "geographic_resolution": {
                "coordinates": {"latitude": 21.1234, "longitude": 96.5678},
                "has_valid_coordinates": True,
                "has_exportable_site_coordinates": True,
                "can_export_to_shakemap": True,
                "precision_level": "site_specific_address",
                "coordinates_disagree": False,
            },
            "screening": {"relevance_decision": "ESTIMABLE"},
            "quality_control": {"status": "PASSED"},
            "human_in_the_loop": {"review_required": False},
        }
    ]

    exporter.export_observations(sample)
    with open(tmp_path / "agent_mmi_dat.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    coords = data["features"][0]["geometry"]["coordinates"]
    # RFC 7946 / GeoJSON: index 0 is Longitude, index 1 is Latitude
    assert coords[0] == 96.5678  # Longitude
    assert coords[1] == 21.1234  # Latitude


# ─────────────────────────────────────────────────────────────────────────────
# 10. Exclusion of NOT_ESTIMABLE Records from ShakeMap Export
# ─────────────────────────────────────────────────────────────────────────────
def test_10_exclusion_of_not_estimable_records(tmp_path):
    """Verify NOT_ESTIMABLE documents are barred from ShakeMap export and audited."""
    exporter = ShakeMapExporter(output_dir=tmp_path, event_id="us7000pn9s")

    records = [
        {
            "file_name": "page-8_hazard_map.pdf",
            "seismic_intensity": {"mmi_estimation": None},
            "geographic_resolution": {
                "coordinates": {"latitude": 21.95, "longitude": 96.08},
                "has_exportable_site_coordinates": False,
                "can_export_to_shakemap": False,
            },
            "screening": {"relevance_decision": "NOT_ESTIMABLE"},
            "quality_control": {"status": "SCREENED_OUT"},
            "human_in_the_loop": {"review_required": False},
        }
    ]

    export_res = exporter.export_observations(records)
    assert export_res["exported_count"] == 0
    assert export_res["excluded_count"] == 1

    # Check excluded_observations.json
    audit_file = tmp_path / "excluded_observations.json"
    assert audit_file.exists()
    with open(audit_file, "r", encoding="utf-8") as f:
        audit = json.load(f)
    items = audit.get("excluded_observations", [])
    assert len(items) == 1
    assert items[0]["file_name"] == "page-8_hazard_map.pdf"
    assert "NOT_ESTIMABLE" in items[0]["reason"]


# ─────────────────────────────────────────────────────────────────────────────
# 11. Exclusion of Unresolved QC Cases and Coordinate Conflicts
# ─────────────────────────────────────────────────────────────────────────────
def test_11_exclusion_of_unresolved_qc_cases_and_coordinate_conflicts(tmp_path):
    """Verify coordinate conflicts and approximate viewports are excluded."""
    exporter = ShakeMapExporter(output_dir=tmp_path, event_id="us7000pn9s")

    records = [
        # Case A: Coordinate conflict (document vs model disagree by > 5 km)
        {
            "file_name": "conflict.pdf",
            "seismic_intensity": {"mmi_estimation": 7.0, "confidence": 0.8},
            "geographic_resolution": {
                "coordinates": {"latitude": 21.9, "longitude": 96.0},
                "has_valid_coordinates": True,
                "has_exportable_site_coordinates": False,
                "can_export_to_shakemap": False,
                "coordinates_disagree": True,
                "precision_level": "site_specific_address",
            },
            "screening": {"relevance_decision": "ESTIMABLE"},
            "quality_control": {"status": "FLAGGED"},
            "human_in_the_loop": {"review_required": True, "review_status": "PENDING_REVIEW"},
        },
        # Case B: Viewport / city centroid (not site-specific)
        {
            "file_name": "viewport.pdf",
            "seismic_intensity": {"mmi_estimation": 6.5, "confidence": 0.8},
            "geographic_resolution": {
                "coordinates": {"latitude": 21.9, "longitude": 96.0},
                "has_valid_coordinates": True,
                "has_exportable_site_coordinates": False,
                "can_export_to_shakemap": False,
                "coordinates_disagree": False,
                "precision_level": "approximate_viewport",
            },
            "screening": {"relevance_decision": "ESTIMABLE"},
            "quality_control": {"status": "PASSED"},
            "human_in_the_loop": {"review_required": False},
        }
    ]

    export_res = exporter.export_observations(records)
    assert export_res["exported_count"] == 0
    assert export_res["excluded_count"] == 2

    with open(tmp_path / "excluded_observations.json", "r", encoding="utf-8") as f:
        audit = json.load(f)
    items = audit.get("excluded_observations", [])
    assert any("coordinate conflict" in item["reason"].lower() for item in items)
    assert any("precision level" in item["reason"].lower() for item in items)


# ─────────────────────────────────────────────────────────────────────────────
# 12. Inclusion of Expert-Approved Observations
# ─────────────────────────────────────────────────────────────────────────────
def test_12_inclusion_of_expert_approved_observations(tmp_path):
    """Verify that observations with review_status == 'APPROVED' clear the review block."""
    exporter = ShakeMapExporter(output_dir=tmp_path, event_id="us7000pn9s")

    records = [
        {
            "file_name": "sky_villa_condo.pdf",
            "seismic_intensity": {"mmi_estimation": 8.5, "confidence": 0.90},
            "geographic_resolution": {
                "coordinates": {"latitude": 21.9845, "longitude": 96.0821},
                "has_valid_coordinates": True,
                "has_exportable_site_coordinates": True,
                "can_export_to_shakemap": True,
                "coordinates_disagree": False,
                "precision_level": "site_specific_address",
                "location": {"site_name": "Sky Villa Condominium"},
            },
            "screening": {"relevance_decision": "ESTIMABLE"},
            "quality_control": {"status": "FLAGGED"},
            "human_in_the_loop": {
                "review_required": True,
                "review_status": "APPROVED",  # Expert has approved!
            },
        }
    ]

    export_res = exporter.export_observations(records)
    assert export_res["exported_count"] == 1
    assert export_res["excluded_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 13a. Duplicate Observation Handling (Same-Site / Media Suppression)
# ─────────────────────────────────────────────────────────────────────────────
def test_13a_duplicate_observation_handling(tmp_path):
    """
    Verify duplicate observations (same site < 15 m, same report, or identical SHA256)
    are suppressed and audited in excluded_observations.json with duplicate_of code.
    """
    exporter = ShakeMapExporter(output_dir=tmp_path, event_id="us7000pn9s")

    records = [
        {
            "file_name": "first_report.pdf",
            "content_sha256": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            "seismic_intensity": {"mmi_estimation": 7.0, "confidence": 0.85},
            "geographic_resolution": {
                "coordinates": {"latitude": 21.97500, "longitude": 96.08500},
                "has_valid_coordinates": True,
                "has_exportable_site_coordinates": True,
                "can_export_to_shakemap": True,
                "coordinates_disagree": False,
                "precision_level": "site_specific_address",
                "place_name": "Mandalay Central Market",
            },
            "screening": {"relevance_decision": "ESTIMABLE"},
            "quality_control": {"status": "PASSED"},
            "human_in_the_loop": {"review_required": False},
        },
        {
            "file_name": "second_report_same_site.pdf",
            "seismic_intensity": {"mmi_estimation": 7.5, "confidence": 0.90},
            "geographic_resolution": {
                # Offset by 10 meters (< 15 m same-site duplicate threshold)
                "coordinates": {"latitude": 21.97505, "longitude": 96.08505},
                "has_valid_coordinates": True,
                "has_exportable_site_coordinates": True,
                "can_export_to_shakemap": True,
                "coordinates_disagree": False,
                "precision_level": "site_specific_address",
                "place_name": "Mandalay Central Market",
            },
            "screening": {"relevance_decision": "ESTIMABLE"},
            "quality_control": {"status": "PASSED"},
            "human_in_the_loop": {"review_required": False},
        },
        {
            "file_name": "third_report_identical_media.pdf",
            "content_sha256": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            "seismic_intensity": {"mmi_estimation": 7.0, "confidence": 0.85},
            "geographic_resolution": {
                # 30 m away, but exact same photo/PDF hash
                "coordinates": {"latitude": 21.97520, "longitude": 96.08520},
                "has_valid_coordinates": True,
                "has_exportable_site_coordinates": True,
                "can_export_to_shakemap": True,
                "coordinates_disagree": False,
                "precision_level": "site_specific_address",
                "place_name": "Adjacent Alley",
            },
            "screening": {"relevance_decision": "ESTIMABLE"},
            "quality_control": {"status": "PASSED"},
            "human_in_the_loop": {"review_required": False},
        }
    ]

    export_res = exporter.export_observations(records)
    assert export_res["exported_count"] == 1
    assert export_res["excluded_count"] == 2

    with open(tmp_path / "excluded_observations.json", "r", encoding="utf-8") as f:
        audit = json.load(f)
    items = audit.get("excluded_observations", [])
    assert len(items) == 2
    assert any("DUPLICATE_SITE" in item["reason"] for item in items)
    assert any("DUPLICATE_MEDIA" in item["reason"] for item in items)
    for item in items:
        assert "duplicate_of" in item
        assert item["duplicate_of"] is not None


# ─────────────────────────────────────────────────────────────────────────────
# 13b. Independent Buildings Within 100 m Preserved and Clustered
# ─────────────────────────────────────────────────────────────────────────────
def test_13b_independent_buildings_within_100m_preserved_and_clustered(tmp_path):
    """
    Verify that independent buildings within 100 m are NOT suppressed, but rather
    PRESERVED, exported to ShakeMap, and grouped into spatial clusters.
    """
    exporter = ShakeMapExporter(output_dir=tmp_path, event_id="us7000pn9s")

    records = [
        {
            "file_name": "mgh_ward_a.pdf",
            "content_sha256": "1111111111111111111111111111111111111111111111111111111111111111",
            "seismic_intensity": {"mmi_estimation": 8.0, "confidence": 0.85},
            "geographic_resolution": {
                "coordinates": {"latitude": 21.97500, "longitude": 96.08500},
                "has_valid_coordinates": True,
                "has_exportable_site_coordinates": True,
                "can_export_to_shakemap": True,
                "coordinates_disagree": False,
                "precision_level": "site_specific_address",
                "place_name": "Mandalay General Hospital - Ward A",
            },
            "screening": {"relevance_decision": "ESTIMABLE"},
            "quality_control": {"status": "PASSED"},
            "human_in_the_loop": {"review_required": False},
        },
        {
            "file_name": "mgh_emergency_annex.pdf",
            "content_sha256": "2222222222222222222222222222222222222222222222222222222222222222",
            "seismic_intensity": {"mmi_estimation": 8.5, "confidence": 0.90},
            "geographic_resolution": {
                # ~55 meters away from Ward A (distinct independent structure on hospital campus)
                "coordinates": {"latitude": 21.97540, "longitude": 96.08530},
                "has_valid_coordinates": True,
                "has_exportable_site_coordinates": True,
                "can_export_to_shakemap": True,
                "coordinates_disagree": False,
                "precision_level": "site_specific_address",
                "place_name": "Mandalay General Hospital - Emergency Annex",
            },
            "screening": {"relevance_decision": "ESTIMABLE"},
            "quality_control": {"status": "PASSED"},
            "human_in_the_loop": {"review_required": False},
        }
    ]

    export_res = exporter.export_observations(records)
    # Both independent observations must be exported!
    assert export_res["exported_count"] == 2
    assert export_res["excluded_count"] == 0

    with open(tmp_path / "agent_mmi_dat.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    feats = data["features"]
    assert len(feats) == 2

    # Both must be marked as part of a proximal independent cluster
    for feat in feats:
        assert feat["properties"]["cluster_flag"] == "PROXIMAL_INDEPENDENT_CLUSTER"
        assert feat["properties"]["cluster_id"] is not None

    # Both must share the same cluster ID
    assert feats[0]["properties"]["cluster_id"] == feats[1]["properties"]["cluster_id"]
    cid = feats[0]["properties"]["cluster_id"]

    # Metadata must track the cluster members
    clusters = data["metadata"]["spatial_clusters"]
    assert cid in clusters
    assert len(clusters[cid]) == 2
    assert feats[0]["properties"]["code"] in clusters[cid]
    assert feats[1]["properties"]["code"] in clusters[cid]


# ─────────────────────────────────────────────────────────────────────────────
# 14. Preservation of MMI and Uncertainty Across Uncertainty Strategies
# ─────────────────────────────────────────────────────────────────────────────
def test_14_preservation_of_mmi_and_uncertainty_provenance_across_strategies(tmp_path):
    """Verify MMI is never altered and uncertainty strategies behave as specified."""
    sample = [
        {
            "file_name": "test_uncertainty.pdf",
            "seismic_intensity": {"mmi_estimation": 8.0, "confidence": 0.80},
            "geographic_resolution": {
                "coordinates": {"latitude": 21.90, "longitude": 96.10},
                "has_valid_coordinates": True,
                "has_exportable_site_coordinates": True,
                "can_export_to_shakemap": True,
                "coordinates_disagree": False,
                "precision_level": "site_specific_address",
            },
            "screening": {"relevance_decision": "ESTIMABLE"},
            "quality_control": {"status": "PASSED"},
            "human_in_the_loop": {"review_required": False},
        }
    ]

    # 1. standard_consensus / experimental_fixed_prior
    exp_std = ShakeMapExporter(output_dir=tmp_path / "std", uncertainty_strategy="experimental_fixed_prior")
    exp_std.export_observations(sample)
    with open(tmp_path / "std" / "agent_mmi_dat.json", "r", encoding="utf-8") as f:
        d_std = json.load(f)
    feat_std = d_std["features"][0]
    assert feat_std["properties"]["intensity"] == 8.0
    assert feat_std["properties"]["intensity_stddev"] == 0.50
    assert feat_std["properties"]["raw_model_confidence"] == 0.80
    assert feat_std["properties"]["uncertainty_policy"] == "experimental_fixed_prior"
    assert d_std["metadata"]["uncertainty_policy"] == "experimental_fixed_prior"
    assert "experimental prior" in d_std["metadata"]["uncertainty_policy_description"].lower()

    # 2. expert_specified
    exp_exp = ShakeMapExporter(output_dir=tmp_path / "exp", uncertainty_strategy="expert_specified", expert_uncertainty=0.65)
    exp_exp.export_observations(sample)
    with open(tmp_path / "exp" / "agent_mmi_dat.json", "r", encoding="utf-8") as f:
        d_exp = json.load(f)
    feat_exp = d_exp["features"][0]
    assert feat_exp["properties"]["intensity"] == 8.0
    assert feat_exp["properties"]["intensity_stddev"] == 0.65
    assert feat_exp["properties"]["raw_model_confidence"] == 0.80
    assert feat_exp["properties"]["uncertainty_policy"] == "expert_specified"
    assert d_exp["metadata"]["uncertainty_policy"] == "expert_specified"

    # 3. clara_experimental: 0.35 + (1.0 - 0.80) * 0.70 = 0.35 + 0.14 = 0.49
    exp_clara = ShakeMapExporter(output_dir=tmp_path / "clara", uncertainty_strategy="clara_experimental")
    exp_clara.export_observations(sample)
    with open(tmp_path / "clara" / "agent_mmi_dat.json", "r", encoding="utf-8") as f:
        d_clara = json.load(f)
    feat_clara = d_clara["features"][0]
    assert feat_clara["properties"]["intensity"] == 8.0
    assert feat_clara["properties"]["intensity_stddev"] == 0.49
    assert feat_clara["properties"]["raw_model_confidence"] == 0.80
    assert feat_clara["properties"]["uncertainty_policy"] == "clara_experimental"
    assert d_clara["metadata"]["uncertainty_policy"] == "clara_experimental"


# ─────────────────────────────────────────────────────────────────────────────
# 15. Valid MMI vs. Rrup Plotting
# ─────────────────────────────────────────────────────────────────────────────
def test_15_valid_mmi_vs_rrup_plotting(tmp_path):
    """Verify MMIRrupPlotter produces PDF, PNG, CSV, and JSON outputs."""
    plotter = MMIRrupPlotter(output_dir=tmp_path, event_id="us7000pn9s")

    # Sample observation data
    observations = [
        {
            "file_name": "obs_near.pdf",
            "seismic_intensity": {"mmi_estimation": 9.5},
            "geographic_resolution": {"rrup_km": 0.5, "surface_faulting_observed": True},
            "screening": {"relevance_decision": "ESTIMABLE"},
            "human_in_the_loop": {"review_required": False},
        },
        {
            "file_name": "obs_mid.pdf",
            "seismic_intensity": {"mmi_estimation": 7.0},
            "geographic_resolution": {"rrup_km": 25.0, "surface_faulting_observed": False},
            "screening": {"relevance_decision": "ESTIMABLE"},
            "human_in_the_loop": {"review_required": False},
        },
        {
            "file_name": "obs_review.pdf",
            "seismic_intensity": {"mmi_estimation": 8.0},
            "geographic_resolution": {"rrup_km": 80.0, "surface_faulting_observed": False},
            "screening": {"relevance_decision": "ESTIMABLE"},
            "human_in_the_loop": {"review_required": True, "review_status": "PENDING_REVIEW"},
        }
    ]

    # Load DYFI compact fixture and attenuation curves fixture if present
    dyfi_path = FIXTURES_DIR / "stationlist_compact.json"
    att_path = FIXTURES_DIR / "attenuation_curves.json"
    dyfi_data = None
    att_data = None
    if dyfi_path.exists():
        with open(dyfi_path, "r", encoding="utf-8") as f:
            dyfi_data = json.load(f)
    if att_path.exists():
        with open(att_path, "r", encoding="utf-8") as f:
            att_data = json.load(f)

    outputs = plotter.plot(
        observations=observations,
        dyfi_stationlist=dyfi_data,
        attenuation_curves=att_data,
        base_filename="test_mmi_rrup",
    )

    assert "pdf" in outputs and Path(outputs["pdf"]).exists()
    assert "png" in outputs and Path(outputs["png"]).exists()
    assert "csv" in outputs and Path(outputs["csv"]).exists()
    assert "json" in outputs and Path(outputs["json"]).exists()

    # Verify CSV content
    with open(outputs["csv"], "r", encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 4  # Header + 3 observations
    assert "obs_near.pdf" in lines[1]
    assert "9.5" in lines[1]


# ─────────────────────────────────────────────────────────────────────────────
# 16. Preservation of Stage 1–3 Pipeline Functionality
# ─────────────────────────────────────────────────────────────────────────────
def test_16_preservation_of_stage_1_to_3_pipeline_functionality():
    """Verify GeneralSteerPipeline preserves all Stage 1-3 behavior and incorporates Stage 4A."""
    pipeline = GeneralSteerPipeline(mode="offline", allow_live_api=False)

    cand_p1 = [
        Path("data/events/us7000pn9s/inbound/test_page1.pdf"),
        Path("server/test_page1.pdf"),
    ]
    p1_file = next((p for p in cand_p1 if p.exists()), None)
    assert p1_file is not None

    p1 = pipeline.process_pdf(p1_file)
    assert p1["file_name"] == "test_page1.pdf"
    assert p1["seismic_intensity"]["mmi_estimation"] == 9.0
    assert "geographic_resolution" in p1
    assert "rrup_km" in p1["geographic_resolution"]
    assert "seismological_assessment" in p1
    assert p1["seismological_assessment"]["is_physically_plausible"] is True

    cand_p2 = [
        Path("tests/fixtures/synthetic_steer_page2_mandalay.pdf"),
    ]
    p2_file = next((p for p in cand_p2 if p.exists()), None)
    assert p2_file is not None

    p2 = pipeline.process_pdf(p2_file)
    assert p2["file_name"] == "synthetic_steer_page2_mandalay.pdf"
    assert p2["seismic_intensity"]["mmi_estimation"] == 8.0
    assert "seismological_assessment" in p2
    assert p2["seismological_assessment"]["is_physically_plausible"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 17. Surface Faulting vs. Shaking Evidence Classification in PhysicsCritic
# ─────────────────────────────────────────────────────────────────────────────
def test_17_surface_faulting_vs_shaking_evidence_classification():
    """
    Verify PhysicsCritic distinguishes permanent fault displacement from vibratory ground shaking.
    Fault displacement alone must NOT justify MMI IX-X and must be flagged for expert review.
    """
    critic = PhysicsCritic()

    # Case A: Fault displacement only with high MMI (e.g., 9.5)
    disp_text = (
        "Ground rupture observed across asphalt roadway. Surface fault scarp shows 2.3 meters "
        "of lateral strike-slip displacement. En-echelon tension cracks in agricultural field. "
        "No structural building damage observed in nearby area."
    )
    res_a = critic.evaluate_observation(
        mmi=9.5,
        latitude=21.88,
        longitude=95.98,
        evidence_text=disp_text,
    )
    assert res_a.geological_evidence_type == "fault_displacement_only"
    assert res_a.is_physically_plausible is False
    assert res_a.requires_expert_review is True
    assert "PHYSICS_DISPLACEMENT_DOMINATED_MMI" in res_a.warning_flags
    # Raw MMI must NEVER be modified
    assert res_a.mmi_estimate == 9.5

    # Case B: Shaking-induced structural damage with high MMI (e.g., 9.5) near fault (Rrup <= 1 km)
    shaking_text = (
        "Total structural collapse of four-story reinforced concrete commercial building. "
        "Complete pancake collapse of intermediate floor slabs, column shear failure, "
        "foundation intact. Intense ground shaking threw heavy furniture across rooms."
    )
    res_b = critic.evaluate_observation(
        mmi=9.5,
        latitude=21.88,
        longitude=95.98,
        evidence_text=shaking_text,
    )
    assert res_b.geological_evidence_type == "shaking_induced_damage"
    assert res_b.is_physically_plausible is True
    assert "PHYSICS_DISPLACEMENT_DOMINATED_MMI" not in res_b.warning_flags
    assert res_b.surface_faulting_observed is False
    assert res_b.mmi_estimate == 9.5

    # Case C: Mixed evidence (both surface offset and structural collapse)
    mixed_text = (
        "Surface fault rupture offset fence line and road by 1.8 meters. Adjacent unreinforced "
        "brick masonry structure suffered partial wall collapse and roof failure due to violent shaking."
    )
    res_c = critic.evaluate_observation(
        mmi=9.0,
        latitude=21.88,
        longitude=95.98,
        evidence_text=mixed_text,
    )
    assert res_c.geological_evidence_type == "mixed_evidence"
    assert res_c.requires_expert_review is True
    assert "PHYSICS_MIXED_DISPLACEMENT_AND_SHAKING" in res_c.warning_flags
    assert res_c.mmi_estimate == 9.0


# ─────────────────────────────────────────────────────────────────────────────
# 18. Rigorous Rrup Validation Against Independent Reference Outputs
# ─────────────────────────────────────────────────────────────────────────────
def test_18_rrup_validation_against_reference_outputs():
    """
    Validate RrupCalculator numerically against independent reference evaluations
    from Clara Yoon's Myanmar earthquake benchmark (QuakeLLMmap commit 8681216).
    """
    rupture_file = FIXTURES_DIR / "rupture.json"
    assert rupture_file.exists(), f"Missing reference rupture fixture: {rupture_file}"

    with open(rupture_file, "r", encoding="utf-8") as f:
        rupture_geojson = json.load(f)

    calc = RrupCalculator(rupture_geojson=rupture_geojson, origin_lat=22.011, origin_lon=95.9363)
    assert calc.has_rupture

    # 1. Thazi solar farm (page-022.pdf): lat = 20.8820556, lon = 96.0352778
    # Clara's reference calculation: Rrup = 0.359 km
    rrup_thazi = calc.calculate_rrup(20.882055555555556, 96.03527777777778)
    assert rrup_thazi is not None
    assert abs(rrup_thazi - 0.359) < 0.05, f"Thazi Rrup {rrup_thazi:.3f} km differs from reference 0.359 km"

    # 2. Sagaing road offset (page-026.pdf): lat = 21.8803528, lon = 95.9848806
    # Clara's reference calculation: Rrup = 0.017 km (directly on surface rupture)
    rrup_sagaing = calc.calculate_rrup(21.880352777777777, 95.98488055555556)
    assert rrup_sagaing is not None
    assert abs(rrup_sagaing - 0.017) < 0.05, f"Sagaing Rrup {rrup_sagaing:.3f} km differs from reference 0.017 km"

    # 3. Mandalay city site (page-046.pdf): lat = 21.975, lon = 96.083
    # Clara's reference calculation: Rrup = 10.064 km
    rrup_mandalay_46 = calc.calculate_rrup(21.975, 96.083)
    assert rrup_mandalay_46 is not None
    assert abs(rrup_mandalay_46 - 10.064) < 0.05, f"Mandalay Rrup {rrup_mandalay_46:.3f} km differs from reference 10.064 km"

    # 4. Mandalay Satetaya Village (page-034.pdf): lat = 21.890191, lon = 96.089906
    # Clara's reference calculation: Rrup = 10.841 km
    rrup_mandalay_34 = calc.calculate_rrup(21.890191, 96.089906)
    assert rrup_mandalay_34 is not None
    assert abs(rrup_mandalay_34 - 10.841) < 0.05, f"Mandalay Rrup {rrup_mandalay_34:.3f} km differs from reference 10.841 km"

    # 5. Strictly preserve rrup_km: None when rupture geometry is omitted
    calc_no_rup = RrupCalculator(rupture_geojson=None, origin_lat=21.975, origin_lon=96.085)
    dists = calc_no_rup.calculate_distances(21.975, 96.085)
    assert dists["rrup_km"] is None
    assert dists["repi_km"] == 0.0
    assert dists["distance_source"] == "hypocenter_alternative"


# ─────────────────────────────────────────────────────────────────────────────
# 17. Scientific Expert Approval Enforcement vs. Technical Compatibility Export
# ─────────────────────────────────────────────────────────────────────────────
def test_17_expert_approval_enforcement_for_scientific_datasets(tmp_path):
    """
    Verify that ShakeMapExporter distinguishes technical compatibility artifacts
    from scientifically validated datasets, and enforces that PENDING_EXPERT_REVIEW
    records cannot be exported as a scientific dataset without explicit expert approval.
    """
    exporter = ShakeMapExporter(output_dir=tmp_path, event_id="us7000pn9s")

    sample_pending_obs = {
        "file_name": "page-022.pdf",
        "seismic_intensity": {"mmi_estimation": 9.5, "confidence": 0.90},
        "geographic_resolution": {
            "coordinates": {"latitude": 20.882056, "longitude": 96.035278},
            "has_valid_coordinates": True,
            "has_exportable_site_coordinates": True,
            "can_export_to_shakemap": True,
            "coordinates_disagree": False,
            "precision_level": "site_specific_address",
            "place_name": "Thazi solar farm",
        },
        "screening": {"relevance_decision": "ESTIMABLE"},
        "quality_control": {"status": "PASSED"},
        "human_in_the_loop": {
            "review_required": True,
            "review_status": "PENDING_EXPERT_REVIEW",  # Awaiting expert review
            "triggers": ["high_intensity_mmi_9"],
        },
    }

    sample_approved_obs = {
        "file_name": "page-076.pdf",
        "seismic_intensity": {"mmi_estimation": 9.0, "confidence": 0.90},
        "geographic_resolution": {
            "coordinates": {"latitude": 20.589678, "longitude": 96.052420},
            "has_valid_coordinates": True,
            "has_exportable_site_coordinates": True,
            "can_export_to_shakemap": True,
            "coordinates_disagree": False,
            "precision_level": "site_specific_address",
            "place_name": "KBZ Bank Pyawbwe",
        },
        "screening": {"relevance_decision": "ESTIMABLE"},
        "quality_control": {"status": "PASSED"},
        "human_in_the_loop": {
            "review_required": True,
            "review_status": "APPROVED",  # Seismologist has reviewed & approved
        },
    }

    # 1. Enforcement mode: require_expert_approval=True
    strict_dir = tmp_path / "strict_export"
    res_strict = exporter.export_observations(
        [sample_pending_obs, sample_approved_obs],
        output_dir=strict_dir,
        require_expert_approval=True,
    )

    assert res_strict["exported_count"] == 1
    assert res_strict["excluded_count"] == 1

    with open(strict_dir / "agent_mmi_dat.json", "r", encoding="utf-8") as f:
        strict_geo = json.load(f)
    assert strict_geo["metadata"]["dataset_type"] == "scientifically_validated_observation_dataset"
    assert strict_geo["metadata"]["expert_reviewed"] is True
    assert len(strict_geo["features"]) == 1
    assert strict_geo["features"][0]["properties"]["file_name"] == "page-076.pdf"
    assert strict_geo["features"][0]["properties"]["expert_approved"] is True

    with open(strict_dir / "excluded_observations.json", "r", encoding="utf-8") as f:
        strict_audit = json.load(f)
    assert len(strict_audit["excluded_observations"]) == 1
    assert strict_audit["excluded_observations"][0]["file_name"] == "page-022.pdf"
    assert "scientific expert approval" in strict_audit["excluded_observations"][0]["reason"]

    # 2. Technical compatibility mode: require_expert_approval=False, review_required=False
    compat_obs = dict(sample_pending_obs)
    compat_obs["human_in_the_loop"] = {"review_required": False, "review_status": "NOT_ENQUEUED"}
    compat_dir = tmp_path / "compat_export"
    res_compat = exporter.export_observations(
        [compat_obs],
        output_dir=compat_dir,
        require_expert_approval=False,
    )
    assert res_compat["exported_count"] == 1
    with open(compat_dir / "agent_mmi_dat.json", "r", encoding="utf-8") as f:
        compat_geo = json.load(f)
    assert compat_geo["metadata"]["dataset_type"] == "technical_compatibility_artifact"
    assert compat_geo["metadata"]["expert_reviewed"] is False


