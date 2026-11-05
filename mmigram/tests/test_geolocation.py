"""
Tests for Geolocation Parsing and Validation.
Includes explicit validation that (0, 0) is flagged as invalid.
"""

import unittest
from server.mmigram.geolocation.parser import (
    dms_to_dd,
    parse_dms_string,
    parse_decimal_coordinates,
    extract_coordinates_from_text,
)
from server.mmigram.geolocation.validator import (
    validate_coordinates,
    haversine_distance_km,
    MYANMAR_BOUNDS,
    CITY_CENTROIDS,
)
from server.mmigram.core.state import Coordinates


class TestGeolocation(unittest.TestCase):

    def test_dms_to_dd_conversion(self):
        # Sagaing DMS: 21° 52' 49.27" N, 95° 59' 5.57" E
        lat = dms_to_dd(21, 52, 49.27, "N")
        lon = dms_to_dd(95, 59, 5.57, "E")

        self.assertAlmostEqual(lat, 21.880352777777777, places=5)
        self.assertAlmostEqual(lon, 95.98488055555556, places=5)

    def test_parse_dms_from_steer_source_text(self):
        source_text = 'Geolocation Address / Coordinates: Sagaing city, 21 52\' 49.27" N, 95 59\' 5.57" E'
        parsed = parse_dms_string(source_text)

        self.assertIsNotNone(parsed)
        lat, lon = parsed
        self.assertAlmostEqual(lat, 21.880353, places=4)
        self.assertAlmostEqual(lon, 95.984881, places=4)

    def test_extract_coordinates_from_text_helper(self):
        raw = "Location: Sagaing city, 21 52' 49.27\" N, 95 59' 5.57\" E. Source: StEER."
        coords = extract_coordinates_from_text(raw)

        self.assertTrue(coords.is_valid)
        self.assertEqual(coords.source, "dms_parsed")
        self.assertAlmostEqual(coords.latitude, 21.880353, places=4)
        self.assertAlmostEqual(coords.longitude, 95.984881, places=4)

    def test_null_island_coordinates_strictly_invalid(self):
        """CRITICAL CHECK: (0, 0) must be identified as INVALID."""
        null_coords = Coordinates(latitude=0.0, longitude=0.0)
        validated = validate_coordinates(null_coords)

        self.assertFalse(validated.is_valid)
        self.assertEqual(validated.confidence, 0.0)
        self.assertIn("Null Island", validated.validation_error)

    def test_near_zero_coordinates_invalid(self):
        near_zero = Coordinates(latitude=0.000001, longitude=-0.000001)
        validated = validate_coordinates(near_zero)

        self.assertFalse(validated.is_valid)
        self.assertIn("Null Island", validated.validation_error)

    def test_missing_coordinates_invalid(self):
        none_coords = Coordinates(latitude=None, longitude=None)
        validated = validate_coordinates(none_coords)

        self.assertFalse(validated.is_valid)
        self.assertIn("Missing", validated.validation_error)

    def test_out_of_world_bounds_invalid(self):
        bad_lat = Coordinates(latitude=95.0, longitude=96.0)
        bad_lon = Coordinates(latitude=21.0, longitude=190.0)

        self.assertFalse(validate_coordinates(bad_lat).is_valid)
        self.assertFalse(validate_coordinates(bad_lon).is_valid)

    def test_regional_bounds_enforcement(self):
        # Coordinates in Myanmar (Sagaing)
        sagaing = Coordinates(latitude=21.88035, longitude=95.98488)
        self.assertTrue(validate_coordinates(sagaing).is_valid)

        # Coordinates outside Myanmar (e.g. San Francisco: 37.77, -122.41)
        sf = Coordinates(latitude=37.77, longitude=-122.41)
        val_sf = validate_coordinates(sf)
        self.assertFalse(val_sf.is_valid)
        self.assertIn("outside regional bounds", val_sf.validation_error)

    def test_haversine_distance_computation(self):
        # Distance between Sagaing and Mandalay centroids should be ~12 to 18 km
        sag_lat, sag_lon = CITY_CENTROIDS["sagaing"]
        man_lat, man_lon = CITY_CENTROIDS["mandalay"]
        dist_km = haversine_distance_km(sag_lat, sag_lon, man_lat, man_lon)

        self.assertGreater(dist_km, 10.0)
        self.assertLess(dist_km, 25.0)


if __name__ == "__main__":
    unittest.main()
