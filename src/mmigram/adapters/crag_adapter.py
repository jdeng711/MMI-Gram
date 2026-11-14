"""
Adapter for Clara's legacy MultimodalEarthquakeCRAG.
Wraps the legacy GCS upload and LangGraph CRAG pipeline without altering its prompts or logic.
"""

from __future__ import annotations
import os
import sys
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def check_live_prerequisites(provider: Optional[str] = None) -> Tuple[bool, list[str]]:
    """
    Verify whether required live cloud packages and credentials are configured
    for the selected provider ('ai_studio' or 'vertex_ai').
    Returns (is_ready, list_of_missing_items).
    """
    try:
        from .gemini_provider import get_active_provider, validate_provider_configuration
        target = provider or get_active_provider()
        return validate_provider_configuration(target)
    except Exception:
        target = (provider or os.environ.get("GEMINI_PROVIDER", "ai_studio")).strip().lower()

    missing = []
    if target == "ai_studio":
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            missing.append("GEMINI_API_KEY or GOOGLE_API_KEY not set")
    elif target == "vertex_ai":
        for pkg in ["google.cloud.storage", "google.cloud.bigquery", "vertexai", "google.genai"]:
            try:
                __import__(pkg)
            except ImportError:
                missing.append(f"Python package '{pkg}' not installed")

        creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
        if not creds:
            missing.append("Environment variable GOOGLE_APPLICATION_CREDENTIALS not set")
        elif os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") and not Path(os.environ["GOOGLE_APPLICATION_CREDENTIALS"]).exists():
            missing.append(f"Service account file not found: {os.environ['GOOGLE_APPLICATION_CREDENTIALS']}")

        project_id = os.environ.get("GCS_PROJECT_ID") or os.environ.get("projectID")
        if not project_id:
            missing.append("Environment variable GCS_PROJECT_ID or projectID not set")
    else:
        missing.append(f"Unknown provider: {target}")

    return (len(missing) == 0, missing)


class CRAGAdapter:
    """
    Encapsulates interaction with MultimodalEarthquakeCRAG workflow.
    Supports both local-first Google AI Studio (zero GCS upload) and Google Cloud Vertex AI.
    """

    def __init__(self, bucket_name: Optional[str] = None, provider: Optional[str] = None):
        self.bucket_name = bucket_name or os.environ.get("GCS_BUCKET", "quakemap-media-data")
        self.provider = (provider or os.environ.get("GEMINI_PROVIDER", "ai_studio")).strip().lower()

    def run_crag(
        self,
        file_path: Path,
        mime_type: str = "application/pdf",
        provider: Optional[str] = None,
        use_gcs: bool = False
    ) -> Dict[str, Any]:
        """
        Invokes CRAG workflow for a local or remote media file.
        In 'ai_studio' mode or when use_gcs is False, streams local bytes directly without GCS upload.
        """
        active_provider = provider or self.provider
        ready, missing = check_live_prerequisites(active_provider)
        if not ready:
            raise RuntimeError(f"Live prerequisites for provider '{active_provider}' not met:\n  - " + "\n  - ".join(missing))

        # Set active provider explicitly in environment
        try:
            from .gemini_provider import set_active_provider
            set_active_provider(active_provider)
        except Exception:
            os.environ["GEMINI_PROVIDER"] = active_provider

        # Ensure server directory is accessible for imports
        repo_root = Path(__file__).resolve().parents[3]
        server_dir = repo_root / "server"
        if server_dir.exists() and str(server_dir) not in sys.path:
            sys.path.insert(0, str(server_dir))

        from services.crag import MultimodalEarthquakeCRAG

        resolved_path = Path(file_path).resolve()
        if not resolved_path.exists():
            raise FileNotFoundError(f"Media file not found at: {resolved_path}")

        # Local-first direct media handling (Default):
        if not use_gcs or active_provider == "ai_studio":
            blob_name = resolved_path.name
            signed_url = str(resolved_path)  # Local path is read directly by get_media_part
        else:
            from services.utilities import upload_to_gcs
            unique_blob_name = f"steer_{uuid.uuid4().hex[:8]}_{resolved_path.name}"
            signed_url = upload_to_gcs(str(resolved_path), bucketname=self.bucket_name, blob_name=unique_blob_name)
            blob_name = unique_blob_name

        crag = MultimodalEarthquakeCRAG()
        crag_result = crag.analyze_media_and_traverse_states(
            blob_name=blob_name,
            signed_url=signed_url,
            mime_type=mime_type,
        )

        return crag_result
