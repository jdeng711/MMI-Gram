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


def check_live_prerequisites() -> Tuple[bool, list[str]]:
    """
    Verify whether required live cloud packages and credentials are configured.
    Returns (is_ready, list_of_missing_items).
    """
    missing = []
    
    # Check packages
    for pkg in ["google.cloud.storage", "google.cloud.bigquery", "vertexai"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(f"Python package '{pkg}' not installed")

    # Check credentials
    creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if not creds:
        missing.append("Environment variable GOOGLE_APPLICATION_CREDENTIALS not set")
    elif os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") and not Path(os.environ["GOOGLE_APPLICATION_CREDENTIALS"]).exists():
        missing.append(f"Service account file not found: {os.environ['GOOGLE_APPLICATION_CREDENTIALS']}")

    project_id = os.environ.get("GCS_PROJECT_ID") or os.environ.get("projectID")
    if not project_id:
        missing.append("Environment variable GCS_PROJECT_ID or projectID not set")

    return (len(missing) == 0, missing)


class CRAGAdapter:
    """
    Encapsulates interaction with Clara's legacy CRAG workflow.
    """

    def __init__(self, bucket_name: Optional[str] = None):
        self.bucket_name = bucket_name or os.environ.get("GCS_BUCKET", "quakemap-media-data")

    def run_crag(self, file_path: Path, mime_type: str = "application/pdf") -> Dict[str, Any]:
        """
        Upload media to GCS with unique blob name and invoke Clara's CRAG.
        """
        ready, missing = check_live_prerequisites()
        if not ready:
            raise RuntimeError("Live cloud prerequisites not met:\n  - " + "\n  - ".join(missing))

        # Ensure server directory is accessible for legacy imports
        repo_root = Path(__file__).resolve().parents[3]
        server_dir = repo_root / "server"
        if server_dir.exists() and str(server_dir) not in sys.path:
            sys.path.insert(0, str(server_dir))

        from services.utilities import upload_to_gcs
        from services.crag import MultimodalEarthquakeCRAG

        unique_blob_name = f"steer_{uuid.uuid4().hex[:8]}_{file_path.name}"
        signed_url = upload_to_gcs(str(file_path), bucketname=self.bucket_name, blob_name=unique_blob_name)

        crag = MultimodalEarthquakeCRAG()
        crag_result = crag.analyze_media_and_traverse_states(
            blob_name=unique_blob_name,
            signed_url=signed_url,
            mime_type=mime_type,
        )

        return crag_result
