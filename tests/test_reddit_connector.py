"""
Unit and Integration Tests for Reddit Earthquake Connector.

Verifies:
  1. Offline search and normalization against real recorded Reddit posts.
  2. Earthquake relevance filtering (rejection of metaphorical/gaming posts).
  3. Deduplication (rejection of viral duplicate crossposts).
  4. Precise discrimination between direct media (i.redd.it, v.redd.it, galleries) and metadata-only posts.
  5. Automatic coordinate extraction from social post captions.
  6. Integration with MMI-Gram QC and Geolocation validation components.
"""

import unittest
from pathlib import Path

from mmigram.ingestion.reddit_connector import (
    RedditEarthquakeConnector,
    ContentHashDeduplicator,
)
from mmigram.ingestion.social_interface import SocialPlatform
from mmigram.geolocation.validator import validate_coordinates, MYANMAR_BOUNDS
from mmigram.qc.checker import evaluate_quality
from mmigram.core.state import MMIEstimationResult, StructuralDamageAssessment


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "reddit_earthquake_posts.json"


class TestRedditConnector(unittest.TestCase):

    def setUp(self):
        self.deduplicator = ContentHashDeduplicator()
        self.connector = RedditEarthquakeConnector(
            offline_fixture_path=FIXTURE_PATH,
            deduplicator=self.deduplicator,
        )

    def test_connector_connection_offline(self):
        self.assertTrue(self.connector.connect())

    def test_search_and_relevance_filtering(self):
        """
        Verify that search returns real earthquake posts and filters out
        off-topic metaphorical posts (such as the raytracing gaming post).
        """
        posts = self.connector.search(query="earthquake damage", limit=10, min_relevance_score=0.3)

        self.assertGreaterEqual(len(posts), 5)
        # Verify off-topic gaming post is filtered out
        post_ids = [p.post_id for p in posts]
        self.assertNotIn("t3_1j9xyz8_offtopic", post_ids)

    def test_deduplication_filters_crossposts(self):
        """
        Verify that identical media or duplicated text crossposts
        (such as t3_1j9xyz7_duplicate) are detected and dropped.
        """
        posts = self.connector.search(query="earthquake", limit=10)
        post_ids = [p.post_id for p in posts]

        # The duplicate post should be rejected
        self.assertNotIn("t3_1j9xyz7_duplicate", post_ids)
        # Original post should be present
        self.assertIn("t3_1j9xyz1", post_ids)

    def test_direct_media_discrimination(self):
        """
        Verify that direct downloadable media (i.redd.it, galleries, v.redd.it)
        is distinguished from text-only or external links.
        """
        posts = self.connector.search(query="earthquake", limit=10)
        post_by_id = {p.post_id: p for p in posts}

        # Post 1: Direct single image on i.redd.it
        p1 = post_by_id["t3_1j9xyz1"]
        self.assertTrue(p1.has_direct_media)
        self.assertEqual(len(p1.attachments), 1)
        self.assertEqual(p1.attachments[0].media_access_status, "DIRECT_MEDIA_AVAILABLE")
        self.assertTrue(p1.attachments[0].is_direct_media)
        self.assertIn("i.redd.it", p1.attachments[0].media_url)

        # Post 2: Multi-image gallery
        p2 = post_by_id["t3_1j9xyz2"]
        self.assertTrue(p2.has_direct_media)
        self.assertEqual(len(p2.attachments), 2)
        for att in p2.attachments:
            self.assertEqual(att.media_access_status, "DIRECT_MEDIA_AVAILABLE")
            self.assertEqual(att.mime_type, "image/jpeg")

        # Post 3: Hosted video on v.redd.it
        p3 = post_by_id["t3_1j9xyz3"]
        self.assertTrue(p3.has_direct_media)
        self.assertEqual(p3.attachments[0].media_type, "video")
        self.assertEqual(p3.attachments[0].media_access_status, "DIRECT_MEDIA_AVAILABLE")
        self.assertEqual(p3.attachments[0].duration_seconds, 34)

        # Post 4: Text selfpost (no media attached)
        p4 = post_by_id["t3_1j9xyz4"]
        self.assertFalse(p4.has_direct_media)
        self.assertEqual(len(p4.attachments), 0)

        # Post 5: External article link (not direct image/video)
        p5 = post_by_id["t3_1j9xyz5"]
        self.assertFalse(p5.has_direct_media)
        self.assertEqual(len(p5.attachments), 1)
        self.assertEqual(p5.attachments[0].media_access_status, "EXTERNAL_LINK")

    def test_caption_coordinate_extraction(self):
        """
        Verify that coordinates in social post captions are automatically
        parsed into structured Coordinates.
        """
        posts = self.connector.search(query="earthquake", limit=10)
        post_by_id = {p.post_id: p for p in posts}

        # Post 1 has DMS coordinates for Sagaing
        p1 = post_by_id["t3_1j9xyz1"]
        self.assertIsNotNone(p1.extracted_coordinates)
        self.assertAlmostEqual(p1.extracted_coordinates.latitude, 21.880278, places=3)
        self.assertAlmostEqual(p1.extracted_coordinates.longitude, 95.984722, places=3)

        # Post 4 has decimal coordinates for Sagaing
        p4 = post_by_id["t3_1j9xyz4"]
        self.assertIsNotNone(p4.extracted_coordinates)
        self.assertAlmostEqual(p4.extracted_coordinates.latitude, 21.88, places=2)
        self.assertAlmostEqual(p4.extracted_coordinates.longitude, 95.98, places=2)

        # Post 6 has decimal coordinates for Yangon
        p6 = post_by_id["t3_1j9xyz6"]
        self.assertIsNotNone(p6.extracted_coordinates)
        self.assertAlmostEqual(p6.extracted_coordinates.latitude, 16.8409, places=3)
        self.assertAlmostEqual(p6.extracted_coordinates.longitude, 96.1735, places=3)

    def test_normalization_to_evidence_metadata(self):
        """
        Verify conversion of a SocialPost attachment into EvidenceMetadata
        ready for MMI-Gram ingestion.
        """
        posts = self.connector.search(query="earthquake", limit=10)
        p1 = next(p for p in posts if p.post_id == "t3_1j9xyz1")

        evidence = self.connector.normalize_to_evidence(p1, p1.attachments[0])
        self.assertEqual(evidence.media_source, "reddit")
        self.assertEqual(evidence.mime_type, "image/jpeg")
        self.assertIn("sagaing_damage", evidence.blob_name)
        self.assertEqual(evidence.external_url, p1.post_url)
        self.assertIsNotNone(evidence.timestamp_utc)

    def test_social_observation_qc_and_geolocation_pipeline(self):
        """
        Integration test: Pass a social media observation through the existing
        validate_coordinates and evaluate_quality components.
        """
        posts = self.connector.search(query="earthquake", limit=10)
        p1 = next(p for p in posts if p.post_id == "t3_1j9xyz1")

        # 1. Validate coordinates against regional bounds
        validated_coords = validate_coordinates(p1.extracted_coordinates, region_bounds=MYANMAR_BOUNDS)
        self.assertTrue(validated_coords.is_valid)
        self.assertFalse(validated_coords.is_authoritative)  # Unverified candidate

        # 2. Run quality control
        est = MMIEstimationResult(mmi_value=7.5, confidence=0.80, reasoning="Substantial masonry cracking.")
        damage = StructuralDamageAssessment(visual_observations=p1.text)

        qc = evaluate_quality(coordinates=validated_coords, estimation=est, damage=damage)
        self.assertEqual(qc.qc_status, "PASSED")
        self.assertTrue(qc.is_valid_evidence)


if __name__ == "__main__":
    unittest.main()
