"""
Unit and Regression Tests for Gemini 3.8 Flash Migration & Google Gen AI SDK Integration.

Verifies:
  1. Gemini 3.8 Flash configuration sets explicit thinking_level=HIGH and include_thoughts=True.
  2. Deprecated generation parameters (temperature, top_p, top_k, candidate_count) are omitted for 3.8.
  3. Legacy fallback (gemini-2.5-flash) retains sampling parameters without thinking_config.
  4. PartCompat wrapper transparently supports legacy and modern keyword/positional signatures.
  5. Scientific integrity: NEVER silently switch models on quota or rate limits.
  6. Token usage tracking accurately collects input, output, and thinking tokens.
  7. CLI defaults to gemini-3.8-flash with HIGH thinking.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure server and src directories are in path
REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = REPO_ROOT / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from google.genai import types
from services.manage_model import (
    build_generation_config,
    Part,
    PartCompat,
    get_response,
    get_last_telemetry,
    get_session_telemetry,
    reset_session_telemetry,
    set_genai_client,
)
from mmigram.cli import DEFAULT_MODEL, DEFAULT_THINKING_LEVEL, VERIFIED_MODELS, validate_model_identifier
from mmigram.workflow.general_steer_pipeline import GeneralSteerPipeline


class TestGemini38Configuration(unittest.TestCase):
    """Verifies generation configuration logic for Gemini 3.8 Flash vs legacy models."""

    def test_gemini_38_flash_thinking_config_and_parameter_omission(self):
        """Gemini 3.8 Flash must have thinking_level=HIGH and omit deprecated parameters."""
        config = build_generation_config(
            model_name="gemini-3.8-flash",
            json_mode=True,
            thinking_level="HIGH"
        )

        # 1. Thinking config verification
        self.assertIsNotNone(config.thinking_config, "Gemini 3.8 Flash must have thinking_config")
        self.assertEqual(config.thinking_config.thinking_level, types.ThinkingLevel.HIGH)
        self.assertTrue(config.thinking_config.include_thoughts)

        # 2. Strict omission of deprecated parameters
        self.assertIsNone(config.temperature, "temperature must be omitted for Gemini 3.8")
        self.assertIsNone(config.top_p, "top_p must be omitted for Gemini 3.8")
        self.assertIsNone(config.top_k, "top_k must be omitted for Gemini 3.8")
        self.assertIsNone(config.candidate_count, "candidate_count must be omitted for Gemini 3.8")

        # 3. JSON mode and safety settings
        self.assertEqual(config.response_mime_type, "application/json")
        self.assertEqual(len(config.safety_settings), 4)

    def test_gemini_38_flash_thinking_level_variations(self):
        """Test supported thinking level variations (HIGH, MEDIUM, LOW)."""
        for level_str in ["HIGH", "MEDIUM", "LOW"]:
            config = build_generation_config(
                model_name="gemini-3.8-flash",
                json_mode=False,
                thinking_level=level_str
            )
            expected_enum = getattr(types.ThinkingLevel, level_str)
            self.assertEqual(config.thinking_config.thinking_level, expected_enum)
            self.assertIsNone(config.response_mime_type)

    def test_gemini_38_flash_rejects_minimal_thinking_level(self):
        """MINIMAL is not supported by Google for Gemini 3.8 Flash and must be rejected."""
        with self.assertRaises(ValueError) as ctx:
            build_generation_config(
                model_name="gemini-3.8-flash",
                json_mode=True,
                thinking_level="MINIMAL"
            )
        self.assertIn("Unsupported thinking level 'MINIMAL'", str(ctx.exception))
        self.assertIn("MINIMAL is not supported", str(ctx.exception))

    def test_legacy_gemini_25_flash_parameter_preservation(self):
        """Gemini 2.5 Flash must preserve legacy parameters and omit thinking_config."""
        config = build_generation_config(
            model_name="gemini-2.5-flash",
            json_mode=True
        )

        self.assertIsNone(config.thinking_config, "Gemini 2.5 Flash must not have thinking_config")
        self.assertEqual(config.temperature, 0.4)
        self.assertEqual(config.top_p, 0.95)
        self.assertEqual(config.top_k, 20)
        self.assertEqual(config.candidate_count, 1)
        self.assertEqual(config.response_mime_type, "application/json")


class TestPartCompatWrapper(unittest.TestCase):
    """Verifies that PartCompat supports both positional and keyword argument styles."""

    def test_from_text_positional_and_keyword(self):
        p_pos = Part.from_text("Hello Seismology")
        self.assertEqual(p_pos.text, "Hello Seismology")

        p_kw = Part.from_text(text="Hello Seismology")
        self.assertEqual(p_kw.text, "Hello Seismology")

    def test_from_data_and_from_bytes(self):
        dummy_bytes = b"%PDF-1.4 test data"
        p_data = Part.from_data(dummy_bytes, "application/pdf")
        self.assertEqual(p_data.inline_data.data, dummy_bytes)
        self.assertEqual(p_data.inline_data.mime_type, "application/pdf")

        p_data_kw = Part.from_data(data=dummy_bytes, mime_type="application/pdf")
        self.assertEqual(p_data_kw.inline_data.data, dummy_bytes)

        p_bytes = Part.from_bytes(dummy_bytes, "image/jpeg")
        self.assertEqual(p_bytes.inline_data.mime_type, "image/jpeg")

    def test_from_uri(self):
        uri = "gs://quakemap-media-data/test.pdf"
        p_uri_pos = Part.from_uri(uri, "application/pdf")
        self.assertEqual(p_uri_pos.file_data.file_uri, uri)

        p_uri_kw = Part.from_uri(file_uri=uri, mime_type="application/pdf")
        self.assertEqual(p_uri_kw.file_data.file_uri, uri)

        p_uri_legacy = Part.from_uri(uri=uri, mime_type="application/pdf")
        self.assertEqual(p_uri_legacy.file_data.file_uri, uri)


class TestScientificIntegrityAndRateLimits(unittest.TestCase):
    """Verifies strict adherence to scientific integrity: no silent model switching."""

    def tearDown(self):
        set_genai_client(None)

    def test_never_silently_switch_models_on_rate_limit(self):
        """
        Verify that hitting 429 / ResourceExhausted retries the requested model,
        and NEVER silently downgrades from gemini-3.8-flash to another model.
        """
        mock_client = MagicMock()
        from google.api_core.exceptions import ResourceExhausted

        # Simulate 2 rate limit failures, then success
        mock_resp = MagicMock()
        mock_resp.text = '{"mmi_estimation": 9.5, "confidence": 0.92, "reasoning": "High damage observed."}'
        mock_resp.usage_metadata = types.GenerateContentResponseUsageMetadata(
            prompt_token_count=100,
            candidates_token_count=50,
            thoughts_token_count=200,
            total_token_count=350,
        )

        mock_client.models.generate_content.side_effect = [
            ResourceExhausted("Resource exhausted: 429 Quota Exceeded"),
            ResourceExhausted("Resource exhausted: 429 Quota Exceeded"),
            mock_resp
        ]
        set_genai_client(mock_client)

        with patch("time.sleep", return_value=None):
            result_text = get_response(
                contents=[Part.from_text("Analyze")],
                model_name="gemini-3.8-flash",
                max_retries=3
            )

        self.assertIn("mmi_estimation", result_text)
        # Verify that all 3 calls requested gemini-3.8-flash
        self.assertEqual(mock_client.models.generate_content.call_count, 3)
        for call_args in mock_client.models.generate_content.call_args_list:
            self.assertEqual(
                call_args.kwargs.get("model"),
                "gemini-3.8-flash",
                "Model must never be silently changed across retries"
            )


class TestTokenUsageAndTelemetry(unittest.TestCase):
    """Verifies tracking of prompt, candidates, and thinking tokens."""

    def setUp(self):
        reset_session_telemetry()

    def tearDown(self):
        set_genai_client(None)
        reset_session_telemetry()

    def test_token_telemetry_collection_with_thinking_tokens(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = '{"mmi_estimation": 8.0}'
        mock_resp.usage_metadata = types.GenerateContentResponseUsageMetadata(
            prompt_token_count=150,
            candidates_token_count=60,
            thoughts_token_count=420,
            total_token_count=630,
        )
        mock_client.models.generate_content.return_value = mock_resp
        set_genai_client(mock_client)

        get_response(
            contents=[Part.from_text("Assess")],
            model_name="gemini-3.8-flash",
            thinking_level="HIGH"
        )

        last = get_last_telemetry()
        self.assertIsNotNone(last)
        self.assertEqual(last["model_identifier"], "gemini-3.8-flash")
        self.assertEqual(last["thinking_level"], "HIGH")
        self.assertEqual(last["prompt_tokens"], 150)
        self.assertEqual(last["candidates_tokens"], 60)
        self.assertEqual(last["thoughts_tokens"], 420)
        self.assertEqual(last["total_tokens"], 630)

        session = get_session_telemetry()
        self.assertEqual(session["calls"], 1)
        self.assertEqual(session["total_tokens"], 630)
        self.assertEqual(session["thoughts_tokens"], 420)

    def test_telemetry_counts_every_crag_workflow_call(self):
        """
        Verifies that model usage telemetry counts EVERY Gemini call made during
        the CRAG workflow (initial analysis, grading documents, and final analysis).
        """
        mock_client = MagicMock()
        
        # Simulate responses for: 1 initial analysis, 3 document gradings, 1 final analysis (5 calls total)
        def create_mock_resp(prompt_tok, cand_tok, thought_tok):
            r = MagicMock()
            r.text = '{"binary_score": "yes", "mmi_estimation": 10.0}'
            r.usage_metadata = types.GenerateContentResponseUsageMetadata(
                prompt_token_count=prompt_tok,
                candidates_token_count=cand_tok,
                thoughts_token_count=thought_tok,
                total_token_count=prompt_tok + cand_tok + thought_tok
            )
            return r

        mock_responses = [
            create_mock_resp(500, 100, 300),  # Call 1: initial_analysis
            create_mock_resp(150, 20, 100),   # Call 2: grade doc 1
            create_mock_resp(150, 20, 100),   # Call 3: grade doc 2
            create_mock_resp(150, 20, 100),   # Call 4: grade doc 3
            create_mock_resp(800, 200, 600),  # Call 5: final_analysis
        ]
        mock_client.models.generate_content.side_effect = mock_responses
        set_genai_client(mock_client)

        # Execute 5 calls matching a full CRAG session
        for i in range(5):
            get_response(
                contents=[Part.from_text(f"Call {i+1}")],
                model_name="gemini-3.8-flash",
                thinking_level="HIGH"
            )

        session = get_session_telemetry()
        self.assertEqual(session["calls"], 5, "Session telemetry must count all 5 CRAG calls")
        self.assertEqual(session["prompt_tokens"], 500 + 150*3 + 800)      # 1750
        self.assertEqual(session["candidates_tokens"], 100 + 20*3 + 200)   # 360
        self.assertEqual(session["thoughts_tokens"], 300 + 100*3 + 600)    # 1200
        self.assertEqual(session["total_tokens"], 1750 + 360 + 1200)       # 3310
        self.assertEqual(len(session["invocations"]), 5)


class TestCLIDefaultsAndPipeline(unittest.TestCase):
    """Verifies CLI defaults and GeneralSteerPipeline integration."""

    def test_cli_defaults_to_gemini_38_flash_high(self):
        self.assertEqual(DEFAULT_MODEL, "gemini-3.8-flash")
        self.assertEqual(DEFAULT_THINKING_LEVEL, "HIGH")
        self.assertEqual(VERIFIED_MODELS[0], "gemini-3.8-flash")
        self.assertEqual(validate_model_identifier(None), "gemini-3.8-flash")
        self.assertEqual(validate_model_identifier("gemini-2.5-flash"), "gemini-2.5-flash")

    def test_pipeline_offline_mode_initializes_provenance(self):
        fixtures_dir = REPO_ROOT / "tests" / "fixtures"
        pipeline = GeneralSteerPipeline(mode="offline", fixtures_dir=fixtures_dir)
        test_pdf = fixtures_dir / "test_page1.pdf"
        if not test_pdf.exists():
            test_pdf = REPO_ROOT / "server" / "test_page1.pdf"

        result = pipeline.process_pdf(test_pdf)
        prov = result["provenance"]
        self.assertIn("thinking_level", prov)
        self.assertIn("token_usage", prov)
        self.assertEqual(prov["model_identifier"], "offline-fixture")


if __name__ == "__main__":
    unittest.main()
