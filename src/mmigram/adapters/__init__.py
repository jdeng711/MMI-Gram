"""
Adapters for external models, legacy workflows, and cloud services.
"""

from .crag_adapter import CRAGAdapter, check_live_prerequisites
from .gemini_provider import (
    SUPPORTED_PROVIDERS,
    DEFAULT_PROVIDER,
    get_active_provider,
    set_active_provider,
    validate_provider_configuration,
    create_genai_client,
    get_genai_client,
    set_genai_client,
    load_local_media_part,
    detect_mime_type,
)

__all__ = [
    "CRAGAdapter",
    "check_live_prerequisites",
    "SUPPORTED_PROVIDERS",
    "DEFAULT_PROVIDER",
    "get_active_provider",
    "set_active_provider",
    "validate_provider_configuration",
    "create_genai_client",
    "get_genai_client",
    "set_genai_client",
    "load_local_media_part",
    "detect_mime_type",
]
