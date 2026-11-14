"""
Gemini Provider Abstraction for MMI-Gram.

Supports:
  1. Google AI Studio (default local development via GEMINI_API_KEY).
  2. Google Cloud Vertex AI (optional enterprise / institutional backend).
  3. Direct local media ingestion without GCS bucket upload.

SCIENTIFIC INTEGRITY RULE:
Never silently switch providers or models. All provider selections are explicit.
"""

from __future__ import annotations
import os
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union

try:
    from dotenv import load_dotenv
    load_dotenv()
    if Path("server/.env").exists():
        load_dotenv("server/.env")
except ImportError:
    pass

from google import genai
from google.genai import types

SUPPORTED_PROVIDERS = ("ai_studio", "vertex_ai")
DEFAULT_PROVIDER = "ai_studio"

# Global cached client
_cached_client: Optional[genai.Client] = None
_cached_provider: Optional[str] = None


def get_active_provider() -> str:
    """
    Returns the currently active Gemini provider.
    Defaults to 'ai_studio' unless explicitly set via GEMINI_PROVIDER env or set_active_provider.
    """
    global _cached_provider
    if _cached_provider:
        return _cached_provider
    raw = os.environ.get("GEMINI_PROVIDER", DEFAULT_PROVIDER).strip().lower()
    if raw not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unsupported Gemini provider '{raw}'. "
            f"Supported providers are: {list(SUPPORTED_PROVIDERS)}"
        )
    _cached_provider = raw
    return _cached_provider


def set_active_provider(provider: str):
    """
    Explicitly sets the active Gemini provider and resets client instance.
    Never silently falls back.
    """
    global _cached_client, _cached_provider
    clean = provider.strip().lower()
    if clean not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Invalid Gemini provider '{provider}'. "
            f"Must be one of: {list(SUPPORTED_PROVIDERS)}"
        )
    _cached_provider = clean
    os.environ["GEMINI_PROVIDER"] = clean
    _cached_client = None

    # Synchronously reset manage_model client cache if loaded
    try:
        from services import manage_model
        manage_model._client = None
    except Exception:
        pass


def get_gemini_api_key() -> Optional[str]:
    """Retrieves AI Studio API key from environment."""
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if key:
        return key.strip().strip('"').strip("'")
    return None


def validate_provider_configuration(provider: Optional[str] = None) -> Tuple[bool, List[str]]:
    """
    Validates whether the environment has required credentials for the requested provider.
    Returns (is_valid, list_of_missing_items).
    """
    target = (provider or get_active_provider()).strip().lower()
    missing: List[str] = []

    if target == "ai_studio":
        key = get_gemini_api_key()
        if not key:
            missing.append(
                "GEMINI_API_KEY or GOOGLE_API_KEY is not set in environment or .env file. "
                "Get an API key at https://aistudio.google.com/app/apikey"
            )
    elif target == "vertex_ai":
        project_id = os.environ.get("projectID") or os.environ.get("GCS_PROJECT_ID")
        if not project_id:
            missing.append("Environment variable GCS_PROJECT_ID or projectID not set for Vertex AI")

        creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
        if not creds:
            missing.append("GOOGLE_APPLICATION_CREDENTIALS not set for Vertex AI authentication")
        elif os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") and not Path(os.environ["GOOGLE_APPLICATION_CREDENTIALS"]).exists():
            missing.append(f"Vertex AI credentials file not found: {os.environ['GOOGLE_APPLICATION_CREDENTIALS']}")
    else:
        missing.append(f"Unrecognized provider '{target}'. Choose from {list(SUPPORTED_PROVIDERS)}")

    return (len(missing) == 0, missing)


def create_genai_client(
    provider: Optional[str] = None,
    timeout_seconds: float = 60.0
) -> genai.Client:
    """
    Factory creating a google-genai Client configured for the specified provider.
    Explicitly validates prerequisites and raises informative error messages without silent fallbacks.
    """
    target = (provider or get_active_provider()).strip().lower()
    is_valid, issues = validate_provider_configuration(target)

    if not is_valid:
        raise ValueError(
            f"❌ Cannot initialize Gemini provider '{target}':\n  - " + "\n  - ".join(issues)
        )

    if target == "ai_studio":
        api_key = get_gemini_api_key()
        return genai.Client(
            api_key=api_key,
            http_options={"timeout": int(timeout_seconds * 1000)}
        )
    elif target == "vertex_ai":
        project_id = os.environ.get("projectID") or os.environ.get("GCS_PROJECT_ID")
        location = os.environ.get("GCS_REGION", "us-central1")
        # Attempt to load credentials safely if helper exists
        credentials = None
        try:
            from services.utilities import load_credentials
            credentials = load_credentials()
        except Exception:
            pass

        return genai.Client(
            vertexai=True,
            project=project_id,
            location=location,
            credentials=credentials,
            http_options={"timeout": int(timeout_seconds * 1000)}
        )
    else:
        raise ValueError(f"Unsupported provider '{target}'")


def get_genai_client() -> genai.Client:
    """Returns singleton client instance for active provider."""
    global _cached_client
    if _cached_client is None:
        _cached_client = create_genai_client()
    return _cached_client


def set_genai_client(client: Optional[genai.Client]):
    """Injects or resets custom client instance (for mock testing)."""
    global _cached_client
    _cached_client = client


def detect_mime_type(file_path: Union[str, Path]) -> str:
    """Detects standard MIME type from file extension."""
    ext = Path(file_path).suffix.lower()
    mime_map = {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".txt": "text/plain",
        ".json": "application/json",
    }
    return mime_map.get(ext, "application/octet-stream")


def load_local_media_part(
    file_path: Union[str, Path],
    mime_type: Optional[str] = None
) -> types.Part:
    """
    Directly reads local file bytes from disk into google.genai types.Part.from_bytes.
    Completely eliminates mandatory GCS uploads and cloud signed URLs.
    """
    p = Path(file_path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"Media file not found at: {p}")

    detected_mime = mime_type or detect_mime_type(p)
    raw_bytes = p.read_bytes()

    if not raw_bytes:
        raise ValueError(f"Media file at {p} is empty (0 bytes)")

    return types.Part.from_bytes(data=raw_bytes, mime_type=detected_mime)
