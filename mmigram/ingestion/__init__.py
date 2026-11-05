"""Ingestion interfaces and data models for MMI-Gram."""

from .social_interface import (
    SocialPlatform,
    MediaAttachment,
    SocialPost,
    SocialMediaCollectorInterface,
    DeduplicationInterface,
)
from .reddit_connector import RedditEarthquakeConnector, ContentHashDeduplicator

__all__ = [
    "SocialPlatform",
    "MediaAttachment",
    "SocialPost",
    "SocialMediaCollectorInterface",
    "DeduplicationInterface",
    "RedditEarthquakeConnector",
    "ContentHashDeduplicator",
]
