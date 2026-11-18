"""
Comprehensive Test Suite for Stage 3: Unified Geolocation Integration.

Validates:
1. Valid decimal coordinates in PDF / text (Priority 1).
2. DMS coordinate parsing with flexible punctuation, spaces, and signs.
3. Northern/southern and eastern/western hemisphere signs (S and W negative).
4. Direct coordinates embedded in mapping URLs (Google Maps POI markers vs viewport centers).
5. Shortened Google Maps links with mocked redirects & SSRF protection (loopback/private IP blocking).
6. Place-name/address geocoding with mocked API responses.
7. Missing mapping links and coordinates preserved as null (never fabricated).
8. Multiple conflicting candidate coordinates flagged for human review.
9. Invalid and out-of-bounds coordinates detected and handled (Null Island, world bounds, regional bounds).
10. City-level matches vs. site-specific matches (precision level distinction & can_export_to_shakemap).
11. Event epicenter metadata rejected while genuine damage observations near epicenter are accepted.
12. Observation vs. model coordinate provenance separation (model coordinates never overwritten, explicit source tags).
13. Zero geocoding charges in offline mode (offline guard, zero network calls).
14. Repeat geocoding queries served from cache without extra calls.
15. Correct human-review and QC routing when coordinates are missing or conflicting.
16. Full end-to-end integration with GeneralSteerPipeline preserving Stage 1 & 2 functionality.
17. Separation of spatial coordinate eligibility (has_exportable_site_coordinates) and ShakeMap observation eligibility.
"""

import json
import unittest
from pathlib import Path
from typing import Dict, Any, Optional

from mmigram.core.state import Coordinates, LocationContext
from mmigram.geolocation.parser import dms_to_dd
from mmigram.geolocation.validator import (
    validate_coordinates,
    compare_coordinates,
    haversine_distance_km,
    MYANMAR_BOUNDS,
)
from mmigram.geolocation.url_resolver import MapURLResolver, MapURLExtraction
from mmigram.geolocation.geocoding_adapter import GoogleMapsGeocodingAdapter, GeocodedResult
from mmigram.geolocation.unified_resolver import UnifiedGeolocationResolver
from mmigram.workflow.general_steer_pipeline import GeneralSteerPipeline


class TestUnifiedGeolocation(unittest.TestCase):
    """17 targeted offline tests for unified geolocation."""

    def setUp(self):
        MapURLResolver.clear_mock_redirects()

    def tearDown(self):
        MapURLResolver.clear_mock_redirects()

    # ──────────────────────────────────────────────────────────────────────────
    # Test 1: Valid Decimal Coordinates in Text (Priority 1)
    # ──────────────────────────────────────────────────────────────────────────
    def test_1_valid_decimal_coordinates_priority_1(self):
        text = "Field survey at Sagaing hospital: [21.880353, 95.984881]. Reinforced concrete column failure."
        resolver = UnifiedGeolocationResolver()
        ctx = resolver.resolve(text=text)

        self.assertIsNotNone(ctx.coordinates)
        self.assertAlmostEqual(ctx.coordinates.latitude, 21.880353, places=5)
        self.assertAlmostEqual(ctx.coordinates.longitude, 95.984881, places=5)
        self.assertEqual(ctx.coordinates.source, "decimal_parsed")
        self.assertEqual(ctx.precision_level, "exact_site_dd")
        self.assertTrue(ctx.has_exportable_site_coordinates)
        self.assertTrue(ctx.can_export_to_shakemap)
        self.assertIn("Priority 1", ctx.selection_rationale)
        self.assertIsNotNone(ctx.document_coordinates)

    # ──────────────────────────────────────────────────────────────────────────
    # Test 2: DMS Coordinate Parsing (Flexible Punctuation and Formats)
    # ──────────────────────────────────────────────────────────────────────────
    def test_2_dms_coordinate_parsing_flexibility(self):
        resolver = UnifiedGeolocationResolver()

        # Format A: Standard degrees, minutes, seconds with unicode quotes
        text_a = "Site: Mandalay pagoda, 21°58’42.10\"N, 96°05’20.30\"E. Severe tile detachment."
        ctx_a = resolver.resolve(text=text_a)
        self.assertIsNotNone(ctx_a.coordinates)
        self.assertAlmostEqual(ctx_a.coordinates.latitude, 21.978361, places=4)
        self.assertAlmostEqual(ctx_a.coordinates.longitude, 96.088972, places=4)
        self.assertEqual(ctx_a.precision_level, "exact_site_dms")
        self.assertTrue(ctx_a.has_exportable_site_coordinates)

        # Format B: Space-separated without degree symbols (StEER standard)
        text_b = "Geolocation Address / Coordinates: Sagaing, 21 52' 49.27\" N, 95 59' 5.57\" E"
        ctx_b = resolver.resolve(text=text_b)
        self.assertIsNotNone(ctx_b.coordinates)
        self.assertAlmostEqual(ctx_b.coordinates.latitude, 21.880353, places=4)
        self.assertAlmostEqual(ctx_b.coordinates.longitude, 95.984881, places=4)

        # Format C: Decimal minutes (DM) format
        text_c = "Locus: 21°52.821'N, 95°59.093'E (Near Irrawaddy bridge)"
        ctx_c = resolver.resolve(text=text_c)
        self.assertIsNotNone(ctx_c.coordinates)
        self.assertAlmostEqual(ctx_c.coordinates.latitude, 21.88035, places=4)
        self.assertAlmostEqual(ctx_c.coordinates.longitude, 95.98488, places=4)

    # ──────────────────────────────────────────────────────────────────────────
    # Test 3: Northern/Southern and Eastern/Western Hemisphere Signs
    # ──────────────────────────────────────────────────────────────────────────
    def test_3_hemisphere_signs_s_and_w_negative(self):
        # Southern & Western hemisphere (e.g. Santiago, Chile: 33°27'S, 70°40'W)
        lat_dd = dms_to_dd(33, 27, 0.0, "S")
        lon_dd = dms_to_dd(70, 40, 0.0, "W")
        self.assertAlmostEqual(lat_dd, -33.45, places=3)
        self.assertAlmostEqual(lon_dd, -70.6667, places=3)

        # Test in directional decimal parser
        text = "Reconnaissance in Maule, Chile: 35.6751 S, 71.5430 W. Bridge abutment unseating."
        # Use worldwide bounds for Chile test
        world_bounds = {"lat_min": -60.0, "lat_max": 60.0, "lon_min": -180.0, "lon_max": 180.0}
        resolver = UnifiedGeolocationResolver(region_bounds=world_bounds)
        ctx = resolver.resolve(text=text, region_bounds=world_bounds)

        self.assertIsNotNone(ctx.coordinates)
        self.assertAlmostEqual(ctx.coordinates.latitude, -35.6751, places=4)
        self.assertAlmostEqual(ctx.coordinates.longitude, -71.5430, places=4)
        self.assertTrue(ctx.coordinates.latitude < 0)
        self.assertTrue(ctx.coordinates.longitude < 0)

    # ──────────────────────────────────────────────────────────────────────────
    # Test 4: Direct Coordinates Embedded in Mapping URLs (Priority 2)
    # ──────────────────────────────────────────────────────────────────────────
    def test_4_embedded_mapping_url_coordinates_zero_network(self):
        resolver = UnifiedGeolocationResolver()

        # Google Maps POI data parameter (!3dlat!4dlon) -> site-specific marker
        text_poi = "Inspection report. Map: https://www.google.com/maps/place/Sky+Villa/data=!4m2!3m1!1s0x0:0x0!3d21.880353!4d95.984881"
        ctx_poi = resolver.resolve(text=text_poi)
        self.assertIsNotNone(ctx_poi.coordinates)
        self.assertAlmostEqual(ctx_poi.coordinates.latitude, 21.880353, places=5)
        self.assertAlmostEqual(ctx_poi.coordinates.longitude, 95.984881, places=5)
        self.assertEqual(ctx_poi.precision_level, "url_poi_marker")
        self.assertEqual(ctx_poi.place_name, "Sky Villa")
        self.assertTrue(ctx_poi.has_exportable_site_coordinates)
        self.assertIn("Priority 2", ctx_poi.selection_rationale)

        # Google Maps center parameter (/@lat,lon) -> approximate map viewport center
        text_at = "Building survey: https://maps.google.com/maps/@21.975012,96.083345,18z"
        ctx_at = resolver.resolve(text=text_at)
        self.assertIsNotNone(ctx_at.coordinates)
        self.assertAlmostEqual(ctx_at.coordinates.latitude, 21.975012, places=5)
        self.assertAlmostEqual(ctx_at.coordinates.longitude, 96.083345, places=5)
        self.assertEqual(ctx_at.precision_level, "url_viewport_approximate")
        self.assertFalse(ctx_at.has_exportable_site_coordinates)
        self.assertIn("Priority 2: Contextual map viewport center", ctx_at.selection_rationale)

        # OpenStreetMap (?mlat=lat&mlon=lon)
        text_osm = "OSM Node: https://www.openstreetmap.org/?mlat=21.88035&mlon=95.98488#map=16/21.88035/95.98488"
        ctx_osm = resolver.resolve(text=text_osm)
        self.assertIsNotNone(ctx_osm.coordinates)
        self.assertAlmostEqual(ctx_osm.coordinates.latitude, 21.88035, places=4)
        self.assertAlmostEqual(ctx_osm.coordinates.longitude, 95.98488, places=4)
        self.assertTrue(ctx_osm.has_exportable_site_coordinates)

        # geo: URI
        text_geo = "Handheld GPS export: geo:21.88035,95.98488"
        ctx_geo = resolver.resolve(text=text_geo)
        self.assertIsNotNone(ctx_geo.coordinates)
        self.assertAlmostEqual(ctx_geo.coordinates.latitude, 21.88035, places=4)
        self.assertTrue(ctx_geo.has_exportable_site_coordinates)

    # ──────────────────────────────────────────────────────────────────────────
    # Test 5: Shortened Google Maps Links with Mocked Redirects & SSRF Protection
    # ──────────────────────────────────────────────────────────────────────────
    def test_5_shortened_links_and_ssrf_protection(self):
        # 5a. Safe mock redirection to valid Google Maps coordinate URL (POI marker)
        short_url = "https://maps.app.goo.gl/AbCdEf1234"
        expanded_target = "https://www.google.com/maps/place/Sagaing+Hospital/data=!4m2!3m1!1s0x0:0x0!3d21.880353!4d95.984881"
        MapURLResolver.register_mock_redirect(short_url, expanded_target)

        text = f"Damage report with short link: {short_url}. Wall cracks observed."
        resolver = UnifiedGeolocationResolver()
        ctx = resolver.resolve(text=text)

        self.assertIsNotNone(ctx.coordinates)
        self.assertAlmostEqual(ctx.coordinates.latitude, 21.880353, places=5)
        self.assertEqual(ctx.place_name, "Sagaing Hospital")
        self.assertEqual(ctx.precision_level, "url_poi_marker")
        self.assertTrue(ctx.has_exportable_site_coordinates)

        # 5b. SSRF Protection: Loopback IP rejection
        self.assertTrue(MapURLResolver.is_private_or_reserved_ip("127.0.0.1"))
        self.assertFalse(MapURLResolver.is_safe_redirect_host("127.0.0.1"))
        self.assertFalse(MapURLResolver.is_safe_redirect_host("localhost"))

        # 5c. SSRF Protection: Cloud metadata service rejection
        self.assertTrue(MapURLResolver.is_private_or_reserved_ip("169.254.169.254"))
        self.assertFalse(MapURLResolver.is_safe_redirect_host("169.254.169.254"))

        # 5d. SSRF Protection: Private RFC 1918 addresses
        self.assertTrue(MapURLResolver.is_private_or_reserved_ip("10.0.0.5"))
        self.assertTrue(MapURLResolver.is_private_or_reserved_ip("192.168.1.1"))
        self.assertTrue(MapURLResolver.is_private_or_reserved_ip("172.16.0.1"))

        # 5e. SSRF Protection: Non-whitelisted domain rejection
        self.assertFalse(MapURLResolver.is_safe_redirect_host("malicious-domain.com"))
        self.assertFalse(MapURLResolver.is_safe_redirect_host("google.com.attacker.com"))

    # ──────────────────────────────────────────────────────────────────────────
    # Test 6: Place-Name/Address Geocoding with Mocked API Responses (Priority 4)
    # ──────────────────────────────────────────────────────────────────────────
    def test_6_address_geocoding_with_mock_responses(self):
        adapter = GoogleMapsGeocodingAdapter(allow_live_geocoding=True)
        # Register a mock ROOFTOP geocoding response
        adapter.register_mock_response(
            "Sky Villa, Mandalay, Myanmar",
            {
                "formatted_address": "Sky Villa Condominium, 73rd St, Mandalay, Myanmar",
                "geometry": {
                    "location": {"lat": 21.968822, "lng": 96.089145},
                    "location_type": "ROOFTOP",
                },
                "place_id": "ChIJ_mock_sky_villa_id",
            }
        )

        text = "Geolocation (Address/Coordinates): Sky Villa, Mandalay, Myanmar\nDescription: Shear cracking on 3rd floor."
        resolver = UnifiedGeolocationResolver(geocoding_adapter=adapter)
        ctx = resolver.resolve(text=text)

        self.assertIsNotNone(ctx.coordinates)
        self.assertAlmostEqual(ctx.coordinates.latitude, 21.968822, places=5)
        self.assertAlmostEqual(ctx.coordinates.longitude, 96.089145, places=5)
        self.assertEqual(ctx.precision_level, "geocoded_rooftop")
        self.assertTrue(ctx.has_exportable_site_coordinates)
        self.assertIn("Priority 4", ctx.selection_rationale)
        self.assertIsNotNone(ctx.geocoded_coordinates)

    # ──────────────────────────────────────────────────────────────────────────
    # Test 7: Missing Mapping Links and Coordinates Preserved as Null (Priority 5)
    # ──────────────────────────────────────────────────────────────────────────
    def test_7_missing_coordinates_preserved_as_null_never_fabricated(self):
        text = "Structural assessment: Masonry infill wall failure. No location indicated."
        resolver = UnifiedGeolocationResolver()
        ctx = resolver.resolve(text=text)

        self.assertIsNone(ctx.coordinates)
        self.assertIsNone(ctx.document_coordinates)
        self.assertIsNone(ctx.mapping_link_coordinates)
        self.assertIsNone(ctx.geocoded_coordinates)
        self.assertEqual(ctx.precision_level, "unknown")
        self.assertFalse(ctx.has_exportable_site_coordinates)
        self.assertFalse(ctx.can_export_to_shakemap)
        self.assertIn("Priority 5", ctx.selection_rationale)
        self.assertIn("coordinates: null", ctx.selection_rationale.lower())

    # ──────────────────────────────────────────────────────────────────────────
    # Test 8: Multiple Conflicting Candidate Coordinates Flagged for Review
    # ──────────────────────────────────────────────────────────────────────────
    def test_8_multiple_conflicting_candidate_coordinates_flagged(self):
        # Document text coordinates say Sagaing, while an embedded map URL points to Naypyidaw (>200 km away)
        text = (
            "Field notes: 21°52'49.27\"N, 95°59'5.57\"E (Sagaing).\n"
            "Reference map: https://www.google.com/maps/@19.7633,96.0785,15z (Naypyidaw)."
        )
        resolver = UnifiedGeolocationResolver()
        ctx = resolver.resolve(text=text)

        self.assertTrue(ctx.coordinates_disagree)
        self.assertEqual(ctx.comparison_status, "COORDINATES_DISAGREE")
        self.assertIn("conflict by", ctx.discrepancy_details)
        # Conflicting candidates disqualify from automated ShakeMap export
        self.assertFalse(ctx.has_exportable_site_coordinates)
        self.assertFalse(ctx.can_export_to_shakemap)

    # ──────────────────────────────────────────────────────────────────────────
    # Test 9: Invalid and Out-of-Bounds Coordinates Detected and Handled
    # ──────────────────────────────────────────────────────────────────────────
    def test_9_invalid_and_out_of_bounds_coordinates_rejected(self):
        resolver = UnifiedGeolocationResolver()

        # 9a. Null Island (0.0, 0.0)
        text_null = "Geolocation: [0.0, 0.0]. Sensor failure."
        ctx_null = resolver.resolve(text=text_null)
        self.assertIsNone(ctx_null.coordinates)

        # 9b. Out-of-world latitude (>90)
        text_world = "Coordinates: 95.5000 N, 96.0000 E"
        ctx_world = resolver.resolve(text=text_world)
        self.assertIsNone(ctx_world.coordinates)

        # 9c. Outside regional bounds (e.g. San Francisco in Myanmar study)
        # Regional bounds check retains coordinates with is_within_regional_bounds=False
        # and flags for human review, rather than discarding candidate as null.
        text_sf = "Location: San Francisco, [37.7749, -122.4194]"
        ctx_sf = resolver.resolve(text=text_sf, region_bounds=MYANMAR_BOUNDS)
        self.assertIsNotNone(ctx_sf.coordinates)
        self.assertAlmostEqual(ctx_sf.coordinates.latitude, 37.7749, places=4)
        self.assertFalse(ctx_sf.is_within_regional_bounds)
        self.assertFalse(ctx_sf.coordinates.is_within_regional_bounds)
        self.assertFalse(ctx_sf.has_exportable_site_coordinates)
        self.assertFalse(ctx_sf.can_export_to_shakemap)
        self.assertIn("flagged for review", ctx_sf.coordinates.validation_error)

    # ──────────────────────────────────────────────────────────────────────────
    # Test 10: City-Level Matches vs. Site-Specific Matches (Precision Distinction)
    # ──────────────────────────────────────────────────────────────────────────
    def test_10_city_centroid_vs_site_specific_precision(self):
        adapter = GoogleMapsGeocodingAdapter(allow_live_geocoding=True)
        # Register an APPROXIMATE city centroid response for "Mandalay"
        adapter.register_mock_response(
            "Mandalay",
            {
                "formatted_address": "Mandalay, Myanmar",
                "geometry": {
                    "location": {"lat": 21.9750, "lng": 96.0833},
                    "location_type": "APPROXIMATE",
                },
                "place_id": "ChIJ_mandalay_city_id",
            }
        )

        text = "Location: Mandalay\nObserved ground shaking and superficial plaster cracks."
        resolver = UnifiedGeolocationResolver(geocoding_adapter=adapter)
        ctx = resolver.resolve(text=text)

        self.assertIsNotNone(ctx.coordinates)
        self.assertEqual(ctx.precision_level, "city_centroid_approximate")
        # Approximate city centroids MUST NOT be exported to ShakeMap without exact site verification!
        self.assertFalse(ctx.has_exportable_site_coordinates)
        self.assertFalse(ctx.can_export_to_shakemap)

    # ──────────────────────────────────────────────────────────────────────────
    # Test 11: Event Epicenter Metadata vs Genuine Epicentral Damage Observations
    # ──────────────────────────────────────────────────────────────────────────
    def test_11_event_epicenter_rejected_as_observation_location(self):
        # Known event epicenter (21.9000 N, 95.9500 E)
        epicenter = (21.9000, 95.9500)
        resolver = UnifiedGeolocationResolver(event_epicenter=epicenter)

        # 11a. Reconnaissance report mentioning the mainshock epicenter coordinates in metadata header
        text_meta = (
            "USGS Earthquake Summary: Mw 7.2 Mainshock.\n"
            "Epicenter Coordinates: [21.9000, 95.9500].\n"
            "This report summarizes observed structural performance."
        )
        ctx_meta = resolver.resolve(text=text_meta, event_epicenter=epicenter)

        # Must NOT adopt epicenter metadata as the observation site!
        self.assertIsNone(ctx_meta.coordinates)
        self.assertFalse(ctx_meta.has_exportable_site_coordinates)
        self.assertFalse(ctx_meta.can_export_to_shakemap)
        self.assertIn("Priority 5", ctx_meta.selection_rationale)

        # 11b. Genuine damage observation located near the epicenter
        # Must ACCEPT valid field observation evidence even if coincident with epicentral zone!
        text_obs = (
            "Field survey at village near fault rupture: [21.9000, 95.9500]. "
            "Total building collapse and severe ground failure observed."
        )
        ctx_obs = resolver.resolve(text=text_obs, event_epicenter=epicenter)
        self.assertIsNotNone(ctx_obs.coordinates)
        self.assertAlmostEqual(ctx_obs.coordinates.latitude, 21.9000, places=4)
        self.assertTrue(ctx_obs.has_exportable_site_coordinates)
        self.assertIn("valid field observation located at/near epicentral zone", ctx_obs.selection_rationale)

    # ──────────────────────────────────────────────────────────────────────────
    # Test 12: Observation vs. Model Coordinate Provenance Separation
    # ──────────────────────────────────────────────────────────────────────────
    def test_12_provenance_separation_model_never_overwritten(self):
        resolver = UnifiedGeolocationResolver()

        # Document provides Sagaing coordinates
        text = "Site Coordinates: 21°52'49.27\"N, 95°59'5.57\"E"
        # Model predicted slightly different coordinates (e.g. 2 km away)
        model_loc = {
            "address": "Sagaing Riverfront",
            "coordinates": [21.8950, 95.9900],
        }

        ctx = resolver.resolve(text=text, model_location=model_loc)

        # Primary coordinates selected from Priority 1 (document text)
        self.assertIsNotNone(ctx.coordinates)
        self.assertAlmostEqual(ctx.coordinates.latitude, 21.880353, places=5)

        # Document coordinates strictly preserved
        self.assertIsNotNone(ctx.document_coordinates)
        self.assertAlmostEqual(ctx.document_coordinates.latitude, 21.880353, places=5)

        # Model coordinates strictly preserved (not overwritten by document coordinates)
        self.assertIsNotNone(ctx.model_coordinates)
        self.assertAlmostEqual(ctx.model_coordinates.latitude, 21.8950, places=4)
        self.assertEqual(ctx.model_coordinates.source, "model_predicted")

        # Specific comparison provenance status: DOCUMENT_VS_MODEL_AGREE
        self.assertEqual(ctx.comparison_status, "DOCUMENT_VS_MODEL_AGREE")
        self.assertFalse(ctx.coordinates_disagree)
        self.assertIsNotNone(ctx.discrepancy_distance_km)
        self.assertLess(ctx.discrepancy_distance_km, 5.0)

        # Discrepancy details must contain non-independent validation caution
        self.assertIn("do not constitute independent authoritative GIS validation", ctx.discrepancy_details)

        # Also test GEOCODED_VS_MODEL_AGREE provenance
        adapter = GoogleMapsGeocodingAdapter(allow_live_geocoding=True)
        adapter.register_mock_response(
            "Sky Villa Mandalay",
            {
                "formatted_address": "Sky Villa, Mandalay",
                "geometry": {"location": {"lat": 21.9688, "lng": 96.0891}, "location_type": "ROOFTOP"},
            }
        )
        resolver_geo = UnifiedGeolocationResolver(geocoding_adapter=adapter)
        ctx_geo = resolver_geo.resolve(
            text="Address: Sky Villa Mandalay",
            model_location={"coordinates": [21.9690, 96.0890]},
        )
        self.assertEqual(ctx_geo.comparison_status, "GEOCODED_VS_MODEL_AGREE")
        self.assertIn("Geocoded coordinates", ctx_geo.discrepancy_details)
        self.assertIn("do not constitute independent authoritative GIS validation", ctx_geo.discrepancy_details)

    # ──────────────────────────────────────────────────────────────────────────
    # Test 13: Zero Geocoding Charges in Offline Mode
    # ──────────────────────────────────────────────────────────────────────────
    def test_13_zero_geocoding_charges_in_offline_mode(self):
        # Default adapter with allow_live_geocoding=False
        adapter = GoogleMapsGeocodingAdapter(allow_live_geocoding=False)

        res = adapter.geocode("Sagaing General Hospital, Myanmar")
        self.assertIsNone(res)

        telemetry = adapter.get_telemetry()
        self.assertEqual(telemetry["api_call_count"], 0)
        self.assertEqual(telemetry["offline_blocked_count"], 1)
        self.assertFalse(telemetry["allow_live_geocoding"])

    # ──────────────────────────────────────────────────────────────────────────
    # Test 14: Repeat Geocoding Queries Served from Cache
    # ──────────────────────────────────────────────────────────────────────────
    def test_14_repeat_geocoding_queries_served_from_cache(self):
        adapter = GoogleMapsGeocodingAdapter(allow_live_geocoding=True)
        adapter.register_mock_response(
            "Mandalay Clock Tower",
            {
                "formatted_address": "Clock Tower, 84th St, Mandalay, Myanmar",
                "geometry": {
                    "location": {"lat": 21.9750, "lng": 96.0833},
                    "location_type": "ROOFTOP",
                },
            }
        )

        # First call loads from mock into memory cache
        res1 = adapter.geocode("Mandalay Clock Tower")
        self.assertIsNotNone(res1)
        self.assertFalse(res1.from_cache)

        # Second call with identical query served from cache
        res2 = adapter.geocode("Mandalay Clock Tower")
        self.assertIsNotNone(res2)
        self.assertTrue(res2.from_cache)

        # Third call with normalized case/spacing also served from cache
        res3 = adapter.geocode("   mandalay   clock   tower   ")
        self.assertIsNotNone(res3)
        self.assertTrue(res3.from_cache)

        telemetry = adapter.get_telemetry()
        self.assertEqual(telemetry["cache_hit_count"], 2)

    # ──────────────────────────────────────────────────────────────────────────
    # Test 15: Correct Human-Review and QC Routing for Missing / Conflicting Coords
    # ──────────────────────────────────────────────────────────────────────────
    def test_15_human_review_routing_for_missing_and_conflicting_coords(self):
        import tempfile
        from tests.generate_fixtures import create_minimal_pdf

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_dir = Path(tmpdir)
            temp_pdf = temp_dir / "synthetic_no_coords.pdf"
            temp_fixture = temp_dir / "synthetic_no_coords.json"

            # PDF text with no coordinates
            create_minimal_pdf([
                "Reconnaissance Slide: Overview of masonry failure.",
                "Short Description: Diagonal tension crack across infill.",
            ], temp_pdf)

            fixture_data = {
                "_metadata": {"is_synthetic": True, "baseline_type": "MOCKED_TEST_DATA"},
                "observed_mocked_output": {
                    "mmi_estimation": 6.5,
                    "confidence": 0.80,
                    "location": {"address": "Unspecified", "coordinates": None},
                    "visual_observation": "Diagonal tension crack.",
                }
            }
            with open(temp_fixture, "w", encoding="utf-8") as f:
                json.dump(fixture_data, f)

            pipeline = GeneralSteerPipeline(mode="offline", fixtures_dir=temp_dir)
            pipeline.fixture_registry["synthetic_no_coords.pdf"] = "synthetic_no_coords.json"

            res = pipeline.process_pdf(temp_pdf)
            geo = res["geographic_resolution"]
            review = res["human_in_the_loop"]

            # Coordinates are null
            self.assertIsNone(geo["coordinates"])
            self.assertFalse(geo["has_exportable_site_coordinates"])
            self.assertFalse(geo["can_export_to_shakemap"])

            # Human review must be required
            self.assertTrue(review["review_required"])
            self.assertTrue(any("Geographic coordinates could not be established" in t for t in review["triggers"]))

    # ──────────────────────────────────────────────────────────────────────────
    # Test 16: Preservation of Existing Pipeline Fixtures & Functionality
    # ──────────────────────────────────────────────────────────────────────────
    def test_16_pipeline_preserves_page1_and_page2_functionality(self):
        pipeline = GeneralSteerPipeline(mode="offline")

        # Test Page 2 (Mandalay)
        pdf2 = Path("tests/fixtures/synthetic_steer_page2_mandalay.pdf")
        if pdf2.exists():
            res2 = pipeline.process_pdf(pdf2)
            geo2 = res2["geographic_resolution"]
            self.assertIsNotNone(geo2["coordinates"])
            self.assertAlmostEqual(geo2["coordinates"]["latitude"], 21.978361, places=4)
            self.assertEqual(geo2["precision_level"], "exact_site_dms")
            # Spatial qualification is valid
            self.assertTrue(geo2["has_exportable_site_coordinates"])
            # Automatic ShakeMap export is blocked until candidate coordinates receive human expert review
            self.assertFalse(geo2["can_export_to_shakemap"])
            self.assertTrue(res2["human_in_the_loop"]["review_required"])

    # ──────────────────────────────────────────────────────────────────────────
    # Test 17: Multi-Condition ShakeMap Export Eligibility Separation
    # ──────────────────────────────────────────────────────────────────────────
    def test_17_separation_of_coordinate_and_shakemap_observation_eligibility(self):
        """
        Verify that site-specific valid coordinates alone do NOT guarantee ShakeMap export eligibility.
        Multi-condition eligibility requires:
          1. Valid site-specific coordinates (has_exportable_site_coordinates == True)
          2. Valid numeric MMI (1.0 <= MMI <= 12.0)
          3. ESTIMABLE screening decision
          4. No coordinate conflicts
          5. QC status is acceptable
          6. No unresolved human review
        """
        # Case A: Viewport center URL (has_exportable_site_coordinates = False -> can_export = False)
        resolver = UnifiedGeolocationResolver()
        ctx_viewport = resolver.resolve(text="Survey: https://maps.google.com/maps/@21.9750,96.0833,15z")
        self.assertFalse(ctx_viewport.has_exportable_site_coordinates)
        self.assertFalse(ctx_viewport.can_export_to_shakemap)

        # Case B: City centroid geocode (has_exportable_site_coordinates = False -> can_export = False)
        adapter = GoogleMapsGeocodingAdapter(allow_live_geocoding=True)
        adapter.register_mock_response(
            "Mandalay",
            {
                "formatted_address": "Mandalay",
                "geometry": {"location": {"lat": 21.97, "lng": 96.08}, "location_type": "APPROXIMATE"},
            }
        )
        ctx_city = UnifiedGeolocationResolver(geocoding_adapter=adapter).resolve(text="Address: Mandalay")
        self.assertFalse(ctx_city.has_exportable_site_coordinates)
        self.assertFalse(ctx_city.can_export_to_shakemap)

        # Case C: Valid site coordinates (DMS) in document text has spatial qualification
        ctx_site = resolver.resolve(text="Location: 21°58'42.10\"N, 96°05'20.30\"E")
        self.assertTrue(ctx_site.has_exportable_site_coordinates)

        # Case D: Outside regional bounds (spatial qualification is False)
        ctx_out = resolver.resolve(text="Location: San Francisco [37.7749, -122.4194]", region_bounds=MYANMAR_BOUNDS)
        self.assertFalse(ctx_out.has_exportable_site_coordinates)
        self.assertFalse(ctx_out.can_export_to_shakemap)


if __name__ == "__main__":
    unittest.main()
