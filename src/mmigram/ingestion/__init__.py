"""Ingestion interfaces and data models for MMI-Gram."""

from .social_interface import (
    SocialPlatform,
    MediaAttachment,
    SocialPost,
    SocialMediaCollectorInterface,
    DeduplicationInterface,
)
from .reddit_connector import RedditEarthquakeConnector, ContentHashDeduplicator
from .pdf_extractor import PDFExtractor, PDFContentResult

__all__ = [
    "SocialPlatform",
    "MediaAttachment",
    "SocialPost",
    "SocialMediaCollectorInterface",
    "DeduplicationInterface",
    "RedditEarthquakeConnector",
    "ContentHashDeduplicator",
    "PDFExtractor",
    "PDFContentResult",
]
