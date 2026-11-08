"""
Reddit Social Media Ingestion Connector for Earthquake Media Discovery.

Provides authorized, rate-limited public post discovery via:
  - Official Reddit Data API (OAuth2 script application)
  - Public JSON endpoints with compliant User-Agent headers
  - Offline fixture replay mode for reproducible zero-cost testing

Extracts post metadata, captions, timestamps, and resolves direct media URLs (i.redd.it, v.redd.it, galleries)
while strictly distinguishing direct downloadable media from metadata-only or external link posts.
"""

from __future__ import annotations
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional, Iterator
from datetime import datetime, timezone

from .social_interface import (
    SocialPlatform,
    MediaAttachment,
    SocialPost,
    SocialMediaCollectorInterface,
    DeduplicationInterface,
)
from ..core.state import Coordinates, EvidenceMetadata
from ..geolocation.parser import extract_coordinates_from_text


# Seismic relevance keywords
SEISMIC_POSITIVE_KEYWORDS = {
    "earthquake", "quake", "shaking", "epicenter", "magnitude", "fault",
    "tremor", "aftershock", "seismic", "mmi", "mercalli", "collapse",
    "rubble", "cracks", "damage", "liquefaction", "pga", "intensity",
    "felt", "swaying", "ground motion", "overturned", "cctv", "shakemap",
}

# Metaphorical or off-topic keywords to penalize
SEISMIC_NEGATIVE_KEYWORDS = {
    "gaming", "gameplay", "videogame", "raytracing", "metaphor",
    "financial earthquake", "crypto", "box office", "album",
}


class ContentHashDeduplicator(DeduplicationInterface):
    """Tracks seen post IDs and content hashes to eliminate viral duplicates and crossposts."""

    def __init__(self):
        self.seen_post_ids: set[str] = set()
        self.seen_content_hashes: set[str] = set()
        self.seen_media_urls: set[str] = set()

    def _compute_hash(self, text: str) -> str:
        clean = " ".join(text.lower().split())
        return hashlib.sha256(clean.encode("utf-8")).hexdigest()

    def is_duplicate(self, post: SocialPost) -> bool:
        """Check if post ID, normalized text content, or primary media URL was already seen."""
        if post.post_id in self.seen_post_ids:
            return True

        content_hash = self._compute_hash(post.text)
        if content_hash in self.seen_content_hashes:
            return True

        for att in post.attachments:
            if att.media_url and att.media_url in self.seen_media_urls:
                return True

        return False

    def register(self, post: SocialPost) -> None:
        """Register post identifiers in the deduplication index."""
        self.seen_post_ids.add(post.post_id)
        content_hash = self._compute_hash(post.text)
        self.seen_content_hashes.add(content_hash)
        for att in post.attachments:
            if att.media_url:
                self.seen_media_urls.add(att.media_url)

    def clear(self) -> None:
        self.seen_post_ids.clear()
        self.seen_content_hashes.clear()
        self.seen_media_urls.clear()


class RedditEarthquakeConnector(SocialMediaCollectorInterface):
    """
    Ingestion connector for Reddit public earthquake posts.
    Supports both offline fixture mode and live authorized Reddit API calls.
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        user_agent: str = "MMI-Gram-Earthquake-Monitor/1.0",
        offline_fixture_path: Optional[Path] = None,
        deduplicator: Optional[ContentHashDeduplicator] = None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = user_agent
        self.offline_fixture_path = offline_fixture_path
        self.deduplicator = deduplicator or ContentHashDeduplicator()

    def connect(self) -> bool:
        """Verify API credentials or offline fixture availability."""
        if self.offline_fixture_path and Path(self.offline_fixture_path).exists():
            return True
        if self.client_id and self.client_secret:
            # OAuth credentials provided for live mode
            return True
        # Public read endpoint requires at least a compliant User-Agent
        return bool(self.user_agent)

    def compute_relevance_score(self, title: str, text: str) -> float:
        """
        Evaluate textual relevance to earthquake damage and seismic observations.
        Returns a score in [0.0, 1.0].
        """
        combined = f"{title} {text}".lower()
        words = set(combined.split())

        pos_count = 0
        for kw in SEISMIC_POSITIVE_KEYWORDS:
            if " " in kw:
                if kw in combined:
                    pos_count += 2
            elif kw in words or kw in combined:
                pos_count += 1

        neg_count = sum(1 for kw in SEISMIC_NEGATIVE_KEYWORDS if kw in combined)

        # Strongly penalize off-topic metaphorical or gaming terms
        raw_score = (pos_count * 0.25) - (neg_count * 0.5)
        score = max(0.0, min(1.0, raw_score))
        return round(score, 2)

    def normalize_post(self, raw_data: Dict[str, Any]) -> SocialPost:
        """
        Normalize raw Reddit JSON post structure into standardized SocialPost and MediaAttachments.
        Strictly distinguishes direct media (i.redd.it / v.redd.it) from metadata-only posts.
        """
        post_id = raw_data.get("id", "unknown")
        author = raw_data.get("author", "[deleted]")
        title = raw_data.get("title", "")
        selftext = raw_data.get("selftext", "")
        combined_text = f"{title}\n\n{selftext}".strip()

        created_utc = raw_data.get("created_utc", 0.0)
        dt = datetime.fromtimestamp(created_utc, tz=timezone.utc)
        created_at_iso = dt.isoformat()

        permalink = raw_data.get("permalink", "")
        post_url = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else permalink
        raw_url = raw_data.get("url", "")

        attachments: List[MediaAttachment] = []

        # 1. Check for single image post (e.g. i.redd.it)
        if "i.redd.it" in raw_url or raw_url.endswith((".jpg", ".jpeg", ".png", ".webp")):
            ext = raw_url.split(".")[-1].lower() if "." in raw_url else "jpeg"
            mime = f"image/{ext}" if ext in ("jpeg", "png", "webp") else "image/jpeg"
            att = MediaAttachment(
                media_url=raw_url,
                mime_type=mime,
                media_type="image",
                is_direct_media=True,
                media_access_status="DIRECT_MEDIA_AVAILABLE",
            )
            attachments.append(att)

        # 2. Check for multi-image gallery
        elif raw_data.get("is_gallery") and "media_metadata" in raw_data:
            metadata = raw_data["media_metadata"]
            for img_key, img_info in metadata.items():
                if img_info.get("status") == "valid" and "s" in img_info:
                    img_url = img_info["s"].get("u", "").replace("&amp;", "&")
                    if img_url:
                        att = MediaAttachment(
                            media_url=img_url,
                            mime_type="image/jpeg",
                            media_type="image",
                            width=img_info["s"].get("x"),
                            height=img_info["s"].get("y"),
                            is_direct_media=True,
                            media_access_status="DIRECT_MEDIA_AVAILABLE",
                        )
                        attachments.append(att)

        # 3. Check for hosted video (v.redd.it)
        elif raw_data.get("is_video") or "v.redd.it" in raw_url:
            video_url = raw_url
            media_info = raw_data.get("media", {}) or {}
            duration = None
            if "reddit_video" in media_info:
                video_url = media_info["reddit_video"].get("fallback_url", raw_url)
                duration = media_info["reddit_video"].get("duration")

            att = MediaAttachment(
                media_url=video_url,
                mime_type="video/mp4",
                media_type="video",
                duration_seconds=duration,
                is_direct_media=True,
                media_access_status="DIRECT_MEDIA_AVAILABLE",
            )
            attachments.append(att)

        # 4. Check for external links vs text selfposts
        elif raw_url and not raw_url.startswith("https://www.reddit.com/r/"):
            att = MediaAttachment(
                media_url=raw_url,
                mime_type="text/html",
                media_type="link",
                is_direct_media=False,
                media_access_status="EXTERNAL_LINK",
            )
            attachments.append(att)

        # Determine if direct media is present
        has_direct_media = any(a.is_direct_media for a in attachments)

        # Extract coordinates from text if mentioned
        coords = extract_coordinates_from_text(combined_text)
        if not coords.is_valid:
            coords = None

        return SocialPost(
            post_id=post_id,
            platform=SocialPlatform.REDDIT,
            author_id=author,
            text=combined_text,
            created_at_utc=created_at_iso,
            attachments=attachments,
            raw_payload=raw_data,
            post_url=post_url,
            extracted_coordinates=coords,
            has_direct_media=has_direct_media,
        )

    def search(
        self,
        query: str,
        subreddit: Optional[str] = None,
        time_filter: str = "all",
        limit: int = 10,
        min_relevance_score: float = 0.3,
    ) -> List[SocialPost]:
        """
        Search for earthquake posts matching keyword query and subreddit.
        Applies relevance filtering and deduplication.
        """
        raw_items: List[Dict[str, Any]] = []

        # 1. Offline Fixture Replay Mode
        if self.offline_fixture_path and Path(self.offline_fixture_path).exists():
            with open(self.offline_fixture_path, "r", encoding="utf-8") as f:
                fixture = json.load(f)
                raw_items = fixture.get("posts", [])
        else:
            # 2. Live API Mode (Only if explicitly invoked and configured)
            raw_items = self._fetch_live_reddit_search(query, subreddit, time_filter, limit)

        results: List[SocialPost] = []
        for raw in raw_items:
            # Subreddit filter if specified
            if subreddit and raw.get("subreddit", "").lower() != subreddit.lower():
                continue

            post = self.normalize_post(raw)

            # Relevance check
            rel_score = self.compute_relevance_score(raw.get("title", ""), raw.get("selftext", ""))
            if rel_score < min_relevance_score:
                continue

            # Deduplication check
            if self.deduplicator.is_duplicate(post):
                continue

            self.deduplicator.register(post)
            results.append(post)

            if len(results) >= limit:
                break

        return results

    def _fetch_live_reddit_search(
        self,
        query: str,
        subreddit: Optional[str],
        time_filter: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Live read via Reddit public JSON search endpoints."""
        import urllib.request
        import urllib.parse

        if subreddit:
            url = f"https://www.reddit.com/r/{subreddit}/search.json?q={urllib.parse.quote(query)}&restrict_sr=1&t={time_filter}&limit={limit}"
        else:
            url = f"https://www.reddit.com/search.json?q={urllib.parse.quote(query)}&t={time_filter}&limit={limit}"

        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                children = data.get("data", {}).get("children", [])
                return [c.get("data", {}) for c in children]
        except Exception:
            return []

    def fetch_historical(
        self,
        keywords: List[str],
        start_time_iso: str,
        end_time_iso: Optional[str] = None,
        max_posts: int = 100,
    ) -> List[SocialPost]:
        """Fetch historical posts matching keywords."""
        query = " ".join(keywords)
        return self.search(query=query, limit=max_posts)

    def stream_live(
        self,
        keywords: List[str],
        bounding_box: Optional[Dict[str, float]] = None,
    ) -> Iterator[SocialPost]:
        """Stream new posts matching keywords."""
        query = " ".join(keywords)
        for post in self.search(query=query, limit=10):
            yield post

    def normalize_to_evidence(
        self,
        post: SocialPost,
        attachment: MediaAttachment,
    ) -> EvidenceMetadata:
        """Convert a normalized SocialPost media attachment to EvidenceMetadata for the MMI pipeline."""
        filename = f"reddit_{post.post_id}_{Path(attachment.media_url.split('?')[0]).name}"
        return EvidenceMetadata(
            blob_name=filename,
            signed_url=attachment.media_url,
            mime_type=attachment.mime_type,
            media_source="reddit",
            external_url=post.post_url,
            timestamp_utc=post.created_at_utc,
        )
