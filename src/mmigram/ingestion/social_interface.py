"""
Abstract Interface for Social Media Ingestion and Multimodal Harvesting.
Defines contracts for future platform connectors (X/Twitter, Telegram, Reddit, TikTok)
without implementing live external API connections in Phase 2.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Dict, Any, Optional, Iterator
from dataclasses import dataclass, field
from ..core.state import Coordinates, EvidenceMetadata


class SocialPlatform(str, Enum):
    TWITTER_X = "twitter_x"
    TELEGRAM = "telegram"
    REDDIT = "reddit"
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"
    RECON_REPORT = "recon_report"


@dataclass
class MediaAttachment:
    """An image, video, or document attached to a social post."""
    media_url: str
    mime_type: str
    media_type: str = "image"  # 'image', 'video', 'pdf'
    sha256_hash: Optional[str] = None
    perceptual_hash: Optional[str] = None  # pHash for duplicate image clustering
    width: Optional[int] = None
    height: Optional[int] = None
    duration_seconds: Optional[float] = None
    is_direct_media: bool = True  # True if directly accessible media (e.g. i.redd.it), False if metadata-only
    media_access_status: str = "DIRECT_MEDIA_AVAILABLE"  # 'DIRECT_MEDIA_AVAILABLE', 'METADATA_ONLY', 'EXTERNAL_LINK'

    def to_dict(self) -> Dict[str, Any]:
        return {
            "media_url": self.media_url,
            "mime_type": self.mime_type,
            "media_type": self.media_type,
            "sha256_hash": self.sha256_hash,
            "perceptual_hash": self.perceptual_hash,
            "width": self.width,
            "height": self.height,
            "duration_seconds": self.duration_seconds,
            "is_direct_media": self.is_direct_media,
            "media_access_status": self.media_access_status,
        }


@dataclass
class SocialPost:
    """Standardized representation of a social media post across platforms."""
    post_id: str
    platform: SocialPlatform
    author_id: str
    text: str
    created_at_utc: str
    attachments: List[MediaAttachment] = field(default_factory=list)
    raw_payload: Dict[str, Any] = field(default_factory=dict)
    post_url: Optional[str] = None
    extracted_coordinates: Optional[Coordinates] = None
    hashtags: List[str] = field(default_factory=list)
    has_direct_media: bool = False  # Distinguished from text/link-only posts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "post_id": self.post_id,
            "platform": self.platform.value if hasattr(self.platform, "value") else str(self.platform),
            "author_id": self.author_id,
            "text": self.text,
            "created_at_utc": self.created_at_utc,
            "attachments": [a.to_dict() for a in self.attachments],
            "post_url": self.post_url,
            "extracted_coordinates": self.extracted_coordinates.to_dict() if self.extracted_coordinates else None,
            "hashtags": self.hashtags,
            "has_direct_media": self.has_direct_media,
        }


class SocialMediaCollectorInterface(ABC):
    """
    Contract for social platform harvesting adapters.
    Subclasses will implement platform-specific authentication, rate limiting, and polling.
    """

    @abstractmethod
    def connect(self) -> bool:
        """Establish connection or verify API credentials."""
        pass

    @abstractmethod
    def fetch_historical(
        self,
        keywords: List[str],
        start_time_iso: str,
        end_time_iso: Optional[str] = None,
        max_posts: int = 100,
    ) -> List[SocialPost]:
        """Query platform search endpoints for past earthquake posts."""
        pass

    @abstractmethod
    def stream_live(
        self,
        keywords: List[str],
        bounding_box: Optional[Dict[str, float]] = None,
    ) -> Iterator[SocialPost]:
        """Stream real-time posts matching seismic filter criteria."""
        pass

    @abstractmethod
    def normalize_to_evidence(
        self,
        post: SocialPost,
        attachment: MediaAttachment,
    ) -> EvidenceMetadata:
        """Convert a platform-specific post attachment to MMI-Gram EvidenceMetadata."""
        pass


class DeduplicationInterface(ABC):
    """
    Contract for content deduplication and spam rejection.
    Prevents analyzing the same viral repost multiple times.
    """

    @abstractmethod
    def is_duplicate(self, post: SocialPost) -> bool:
        """Check whether post text or media has already been ingested."""
        pass

    @abstractmethod
    def register(self, post: SocialPost) -> None:
        """Register post hashes in vector or Bloom filter index."""
        pass
