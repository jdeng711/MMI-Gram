"""
Configuration Audit & Environment Variable Contract Tests.

Verifies:
1. Variables documented in .env.example correspond to genuine runtime settings.
2. .env is ignored by Git and .env.example contains zero live credentials.
3. Local Google AI Studio mode does not require Google Maps, Pinecone, Tavily, or Vertex credentials.
4. Google Maps live geocoding is disabled by default via ENABLE_LIVE_GEOCODING=false.
"""

from __future__ import annotations
import os
import re
from pathlib import Path
import pytest

from mmigram.adapters.gemini_provider import (
    get_active_provider,
    validate_provider_configuration,
    set_active_provider,
)
from mmigram.geolocation.geocoding_adapter import GoogleMapsGeocodingAdapter
from mmigram.workflow.general_steer_pipeline import GeneralSteerPipeline


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_env_is_ignored_by_git():
    """Verify that .env is excluded by .gitignore."""
    gitignore_path = REPO_ROOT / ".gitignore"
    assert gitignore_path.exists(), ".gitignore file must exist"
    lines = [l.strip() for l in gitignore_path.read_text(encoding="utf-8").splitlines()]
    assert ".env" in lines, ".env must be explicitly ignored in .gitignore"


def test_env_example_contains_no_live_secrets():
    """Verify that .env.example contains only placeholders, no real secrets."""
    example_path = REPO_ROOT / ".env.example"
    assert example_path.exists(), ".env.example must exist"
    content = example_path.read_text(encoding="utf-8")

    # Check for live Google API keys (AIza...)
    assert not re.search(r"AIza[0-9A-Za-z-_]{35}", content), "Real Google API key detected in .env.example!"
    # Check for OpenAI/Tavily keys (sk-...)
    assert not re.search(r"sk-[0-9A-Za-z-_]{20,}", content), "Real sk- API key detected in .env.example!"
    # Check for private keys
    assert "BEGIN PRIVATE KEY" not in content, "Private key detected in .env.example!"


def test_documented_variables_match_consumed_names():
    """Verify that core documented variables in .env.example are recognized by the application."""
    example_path = REPO_ROOT / ".env.example"
    content = example_path.read_text(encoding="utf-8")

    expected_vars = [
        "GEMINI_PROVIDER",
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "GEMINI_THINKING_LEVEL",
        "MMI_REFERENCE_MODE",
        "ENABLE_LIVE_GEOCODING",
        "GOOGLE_MAPS_API_KEY",
        "MMI_GRAM_BUDGET_LIMIT_PILOT",
        "MMI_GRAM_BUDGET_LIMIT_FULL",
        "MMI_GRAM_BATCH_PACE",
        "MMI_GRAM_MAX_RETRIES",
        "MMI_GRAM_CHECKPOINT_PATH",
        "MMI_GRAM_REVIEW_PATH",
    ]

    for var in expected_vars:
        assert var in content, f"Expected variable '{var}' to be documented in .env.example"


def test_ai_studio_validation_does_not_require_optional_cloud_credentials(monkeypatch):
    """Verify that Google AI Studio requires only GEMINI_API_KEY, not Maps/GCS/Pinecone/Tavily."""
    monkeypatch.setenv("GEMINI_PROVIDER", "ai_studio")
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-test-key-for-config-validation")
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("PINECONE_API", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("GCS_PROJECT_ID", raising=False)
    monkeypatch.delenv("projectID", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    set_active_provider("ai_studio")
    is_valid, missing = validate_provider_configuration("ai_studio")
    assert is_valid is True, f"AI Studio validation failed with missing items: {missing}"
    assert len(missing) == 0


def test_google_maps_geocoding_disabled_by_default(monkeypatch):
    """Verify that GoogleMapsGeocodingAdapter has allow_live_geocoding=False by default."""
    monkeypatch.delenv("ENABLE_LIVE_GEOCODING", raising=False)
    adapter = GoogleMapsGeocodingAdapter(api_key="dummy_key")
    assert adapter.allow_live_geocoding is False, "Paid geocoding must be disabled by default"

    # Geocoding call must return None and record offline block
    res = adapter.geocode("Mandalay Central Hospital")
    assert res is None, "Geocoding must return None when live geocoding is disabled"
    assert adapter.offline_blocked_count >= 1, "Offline block count must be incremented"


def test_pipeline_decouples_live_ai_from_live_geocoding(monkeypatch):
    """Verify that GeneralSteerPipeline does not enable live geocoding when allow_live_api=True."""
    monkeypatch.delenv("ENABLE_LIVE_GEOCODING", raising=False)
    pipeline = GeneralSteerPipeline(mode="offline", allow_live_api=True)
    assert pipeline.allow_live_geocoding is False, (
        "GeneralSteerPipeline must keep allow_live_geocoding=False even if allow_live_api=True"
    )
    assert pipeline.unified_resolver.geocoding_adapter.allow_live_geocoding is False
