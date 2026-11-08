"""
Tests for Social Media Ingestion Data Models and Contract Definitions.
"""

import unittest
from mmigram.ingestion.social_interface import (
    SocialPlatform,
    MediaAttachment,
    SocialPost,
    SocialMediaCollectorInterface,
    DeduplicationInterface,
)
from mmigram.core.state import Coordinates


class MockCollector(SocialMediaCollectorInterface):
    """Mock collector verifying interface conformance."""

    def connect(self) -> bool:
        return True

    def fetch_historical(self, keywords, start_time_iso, end_time_iso=None, max_posts=100):
        return []

    def stream_live(self, keywords, bounding_box=None):
        return iter([])

    def normalize_to_evidence(self, post, attachment):
        from mmigram.core.state import EvidenceMetadata
        return EvidenceMetadata(
            blob_name=f"{post.post_id}_media.jpg",
            media_source=post.platform.value,
            external_url=post.post_url,
        )


class TestSocialMediaInterface(unittest.TestCase):

    def test_social_post_structure(self):
        post = SocialPost(
            post_id="1905986787698458947",
            platform=SocialPlatform.TWITTER_X,
            author_id="heungburma",
            text="Earthquake damage in Sagaing city #MyanmarEarthquake",
            created_at_utc="2025-07-03T18:57:27Z",
            post_url="https://x.com/heungburma/status/1905986787698458947",
            extracted_coordinates=Coordinates(latitude=21.88035, longitude=95.98488, is_valid=True),
        )

        attachment = MediaAttachment(
            media_url="https://pbs.twimg.com/media/test_image.jpg",
            mime_type="image/jpeg",
            media_type="image",
            sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )
        post.attachments.append(attachment)

        self.assertEqual(post.platform, SocialPlatform.TWITTER_X)
        self.assertEqual(len(post.attachments), 1)
        self.assertEqual(post.extracted_coordinates.latitude, 21.88035)

    def test_collector_interface_contract(self):
        collector = MockCollector()
        self.assertTrue(collector.connect())

        post = SocialPost(
            post_id="test-123",
            platform=SocialPlatform.TELEGRAM,
            author_id="news_channel",
            text="Shaking reported in Mandalay",
            created_at_utc="2025-07-03T19:00:00Z",
        )
        att = MediaAttachment(media_url="https://t.me/media.jpg", mime_type="image/jpeg")
        evidence = collector.normalize_to_evidence(post, att)

        self.assertEqual(evidence.blob_name, "test-123_media.jpg")
        self.assertEqual(evidence.media_source, "telegram")


if __name__ == "__main__":
    unittest.main()
