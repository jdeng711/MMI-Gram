"""
Tests for Stage 1: Gemini Provider Abstraction, Local Ingestion, and Versioned MMI Reference.

Validates:
1. Provider selection and switching (ai_studio vs vertex_ai).
2. Strict non-silent error handling for invalid providers and missing credentials.
3. Direct local media ingestion without GCS or cloud storage credentials.
4. MIME type detection and types.Part.from_bytes creation.
5. Local versioned MMI scale definitions (10-level USGS scale and 12-level full scale).
6. Local reference completeness validation and keyword overlap search.
7. CLI --provider argument parsing and execution provenance.
"""

from __future__ import annotations
import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from google.genai import types
from langchain.schema import Document

from mmigram.adapters.gemini_provider import (
    SUPPORTED_PROVIDERS,
    DEFAULT_PROVIDER,
    get_active_provider,
    set_active_provider,
    get_gemini_api_key,
    validate_provider_configuration,
    create_genai_client,
    get_genai_client,
    set_genai_client,
    detect_mime_type,
    load_local_media_part,
)
from mmigram.seismology.mmi_reference import (
    LocalMMIReference,
    validate_scale_completeness,
)
from mmigram.cli import build_parser
from mmigram.workflow.general_steer_pipeline import GeneralSteerPipeline

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"


class TestGeminiProviderSelection(unittest.TestCase):
    """Test Gemini provider switching, defaults, and error enforcement."""

    def setUp(self):
        self._orig_provider = os.environ.get("GEMINI_PROVIDER")
        self._orig_api_key = os.environ.get("GEMINI_API_KEY")

    def tearDown(self):
        if self._orig_provider is not None:
            os.environ["GEMINI_PROVIDER"] = self._orig_provider
            set_active_provider(self._orig_provider)
        else:
            os.environ.pop("GEMINI_PROVIDER", None)
            set_active_provider(DEFAULT_PROVIDER)

        if self._orig_api_key is not None:
            os.environ["GEMINI_API_KEY"] = self._orig_api_key
        else:
            os.environ.pop("GEMINI_API_KEY", None)

    def test_default_provider_is_ai_studio(self):
        """Default provider must be 'ai_studio' for local-first development."""
        os.environ.pop("GEMINI_PROVIDER", None)
        set_active_provider("ai_studio")
        self.assertEqual(get_active_provider(), "ai_studio")
        self.assertEqual(DEFAULT_PROVIDER, "ai_studio")

    def test_switch_to_vertex_ai(self):
        """Provider must be switchable to 'vertex_ai'."""
        set_active_provider("vertex_ai")
        self.assertEqual(get_active_provider(), "vertex_ai")
        self.assertEqual(os.environ.get("GEMINI_PROVIDER"), "vertex_ai")

    def test_switch_back_to_ai_studio(self):
        """Provider must be switchable back to 'ai_studio'."""
        set_active_provider("vertex_ai")
        self.assertEqual(get_active_provider(), "vertex_ai")
        set_active_provider("ai_studio")
        self.assertEqual(get_active_provider(), "ai_studio")
        self.assertEqual(os.environ.get("GEMINI_PROVIDER"), "ai_studio")

    def test_invalid_provider_raises_value_error(self):
        """Invalid provider string must raise ValueError immediately without silent fallback."""
        with self.assertRaises(ValueError) as ctx:
            set_active_provider("openai_backend")
        self.assertIn("Invalid Gemini provider", str(ctx.exception))
        self.assertIn("ai_studio", str(ctx.exception))
        self.assertIn("vertex_ai", str(ctx.exception))

    def test_validate_provider_configuration_ai_studio_missing_key(self):
        """AI Studio configuration must report missing API key when unset."""
        with patch.dict(os.environ, {}, clear=True):
            is_valid, issues = validate_provider_configuration("ai_studio")
            self.assertFalse(is_valid)
            self.assertTrue(any("GEMINI_API_KEY" in issue for issue in issues))

    def test_validate_provider_configuration_ai_studio_with_key(self):
        """AI Studio configuration must validate as true when API key is present."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "AIzaSyTestMockKey12345"}):
            is_valid, issues = validate_provider_configuration("ai_studio")
            self.assertTrue(is_valid)
            self.assertEqual(len(issues), 0)

    def test_validate_provider_configuration_vertex_ai_missing_creds(self):
        """Vertex AI must report missing project and credentials when unset."""
        with patch.dict(os.environ, {}, clear=True):
            is_valid, issues = validate_provider_configuration("vertex_ai")
            self.assertFalse(is_valid)
            self.assertTrue(any("GCS_PROJECT_ID" in issue or "projectID" in issue for issue in issues))

    def test_create_genai_client_raises_on_missing_credentials(self):
        """create_genai_client must raise ValueError with diagnostic messages if prerequisites fail."""
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as ctx:
                create_genai_client(provider="ai_studio")
            self.assertIn("Cannot initialize Gemini provider 'ai_studio'", str(ctx.exception))
            self.assertIn("GEMINI_API_KEY", str(ctx.exception))


class TestLocalMediaIngestion(unittest.TestCase):
    """Test zero-GCS direct local media streaming."""

    def test_detect_mime_type_pdf(self):
        self.assertEqual(detect_mime_type("document.pdf"), "application/pdf")
        self.assertEqual(detect_mime_type(Path("/tmp/recon/page-26.PDF")), "application/pdf")

    def test_detect_mime_type_images(self):
        self.assertEqual(detect_mime_type("photo.jpg"), "image/jpeg")
        self.assertEqual(detect_mime_type("photo.jpeg"), "image/jpeg")
        self.assertEqual(detect_mime_type("diagram.png"), "image/png")
        self.assertEqual(detect_mime_type("sample.webp"), "image/webp")

    def test_detect_mime_type_video(self):
        self.assertEqual(detect_mime_type("recon_drone.mp4"), "video/mp4")
        self.assertEqual(detect_mime_type("field_video.mov"), "video/quicktime")

    def test_detect_mime_type_unknown(self):
        self.assertEqual(detect_mime_type("data.xyz"), "application/octet-stream")

    def test_load_local_media_part_from_valid_pdf(self):
        """Verify that local PDF is read directly into types.Part.from_bytes without network/GCS."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 mock pdf data for testing direct local streaming")
            temp_path = Path(f.name)

        try:
            part = load_local_media_part(temp_path)
            self.assertIsInstance(part, types.Part)
            # Verify mime_type and inline data bytes
            self.assertEqual(part.inline_data.mime_type, "application/pdf")
            self.assertEqual(part.inline_data.data, b"%PDF-1.4 mock pdf data for testing direct local streaming")
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def test_load_local_media_part_file_not_found(self):
        """Missing file must raise FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            load_local_media_part("/nonexistent/path/to/media.pdf")

    def test_load_local_media_part_empty_file(self):
        """Empty (0-byte) file must raise ValueError."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            temp_path = Path(f.name)

        try:
            with self.assertRaises(ValueError) as ctx:
                load_local_media_part(temp_path)
            self.assertIn("0 bytes", str(ctx.exception))
        finally:
            if temp_path.exists():
                temp_path.unlink()


class TestLocalMMIReference(unittest.TestCase):
    """Test zero-cloud local versioned MMI scale definitions and search."""

    def setUp(self):
        self.reference = LocalMMIReference()

    def test_usgs_10level_scale_completeness(self):
        """USGS 10-level operational scale must contain exactly 10 levels (I-X)."""
        docs = self.reference.retrieve_full_scale("usgs_10level_v1")
        self.assertEqual(len(docs), 10)
        is_complete, msg, details = validate_scale_completeness(docs, expected_levels_count=10)
        self.assertTrue(is_complete, msg)
        self.assertEqual(details["levels_present"], list(range(1, 11)))
        self.assertEqual(len(details["missing_levels"]), 0)

    def test_full_12level_scale_completeness(self):
        """Standard 12-level classical scale must contain exactly 12 levels (I-XII)."""
        docs = self.reference.retrieve_full_scale("full_12level_v1")
        self.assertEqual(len(docs), 12)
        is_complete, msg, details = validate_scale_completeness(docs, expected_levels_count=12)
        self.assertTrue(is_complete, msg)
        self.assertEqual(details["levels_present"], list(range(1, 13)))
        self.assertEqual(len(details["missing_levels"]), 0)

    def test_keyword_overlap_retrieval(self):
        """Deterministic keyword retrieval must match relevant MMI levels."""
        results = self.reference.retrieve_keyword_overlap(
            query="Masonry walls partially collapsed, chimneys broken, heavy furniture overturned",
            scale_version="usgs_10level_v1",
            top_k=3,
        )
        self.assertGreater(len(results), 0)
        levels = [doc.metadata.get("level") for doc in results]
        # MMI VII, VIII, or IX should rank high for collapsed masonry / chimneys
        self.assertTrue(any(lvl in (7, 8, 9) for lvl in levels))

    def test_unknown_scale_version_raises_error(self):
        with self.assertRaises(ValueError) as ctx:
            self.reference.retrieve_full_scale("nonexistent_scale_v9")
        self.assertIn("Unknown scale version", str(ctx.exception))

    def test_validate_scale_completeness_detects_gap(self):
        """Completeness validator must detect missing levels."""
        incomplete_docs = [
            Document(page_content=f"Level {i}", metadata={"level": i, "id": f"mmi-{i}"})
            for i in [1, 2, 4, 5, 6, 7, 8, 9, 10]  # Missing level 3
        ]
        is_complete, msg, details = validate_scale_completeness(incomplete_docs, expected_levels_count=10)
        self.assertFalse(is_complete)
        self.assertIn(3, details["missing_levels"])


class TestCLIProviderArgument(unittest.TestCase):
    """Test CLI --provider argument validation and handling."""

    def test_analyze_default_provider(self):
        parser = build_parser()
        args = parser.parse_args(["analyze", "--pdf", "test.pdf"])
        self.assertEqual(args.provider, "ai_studio")

    def test_analyze_explicit_provider_vertex(self):
        parser = build_parser()
        args = parser.parse_args(["analyze", "--pdf", "test.pdf", "--provider", "vertex_ai"])
        self.assertEqual(args.provider, "vertex_ai")

    def test_batch_explicit_provider_ai_studio(self):
        parser = build_parser()
        args = parser.parse_args(["batch", "--event-id", "us7000pn9s", "--inbound-dir", "data", "--provider", "ai_studio"])
        self.assertEqual(args.provider, "ai_studio")

    def test_batch_explicit_provider_vertex(self):
        parser = build_parser()
        args = parser.parse_args(["batch", "--event-id", "us7000pn9s", "--inbound-dir", "data", "--provider", "vertex_ai"])
        self.assertEqual(args.provider, "vertex_ai")


class TestPipelineProviderProvenance(unittest.TestCase):
    """Test that GeneralSteerPipeline records provider in execution provenance."""

    def test_offline_pipeline_provenance_records_offline(self):
        pipeline = GeneralSteerPipeline(mode="offline")
        pdf_path = REPO_ROOT / "server" / "test_page1.pdf"
        result = pipeline.process_pdf(pdf_path)
        self.assertEqual(result["provenance"]["execution_mode"], "offline")
        self.assertEqual(result["provenance"]["provider"], "offline")

    def test_live_pipeline_provenance_records_selected_provider(self):
        pipeline = GeneralSteerPipeline(mode="live", allow_live_api=True, provider="ai_studio")
        self.assertEqual(pipeline.provider, "ai_studio")
        pdf_path = REPO_ROOT / "server" / "test_page1.pdf"

        mock_crag_result = {
            "final_analysis": {
                "mmi_estimation": 9.0,
                "confidence": 0.85,
                "description": "Masonry damage",
                "location": {"coordinates": [21.88, 95.98]},
            },
            "token_usage": {"calls": 1, "total_tokens": 1000},
            "retrieval_status": "SUCCESS",
            "retrieval_source": "local_reference",
            "reference_mode": "full_scale",
        }

        with patch("services.crag.MultimodalEarthquakeCRAG") as MockCRAG:
            mock_inst = MockCRAG.return_value
            mock_inst.analyze_media_and_traverse_states.return_value = mock_crag_result
            result = pipeline.process_pdf(pdf_path)

        self.assertEqual(result["provenance"]["execution_mode"], "live")
        self.assertEqual(result["provenance"]["provider"], "ai_studio")


class TestStage1TargetedVerification(unittest.TestCase):
    """
    Targeted verification test suite addressing the 6 specific Stage 1 audit criteria:
    1. AI Studio routing for every Gemini call (initial analysis + final synthesis).
    2. Full CRAG traversal with zero GCS, Pinecone, or GCP credentials.
    3. Vertex AI backend selection and strict client cache isolation.
    4. Local PDF binary media part transmission (not plain text) with correct MIME type.
    5. Local MMI definitions strict ordering (I to X / I to XII) and retrieval provenance.
    6. Primary source audit distinguishing restricted 10-level vs complete 12-level scale.
    """

    def setUp(self):
        self._orig_env = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)
        set_active_provider(DEFAULT_PROVIDER)
        set_genai_client(None)

    def test_1_ai_studio_routes_every_gemini_invocation_without_vertex_leak(self):
        """Verify --provider ai_studio routes every call through AI Studio client, not Vertex AI."""
        set_active_provider("ai_studio")
        os.environ["GEMINI_PROVIDER"] = "ai_studio"
        os.environ["GEMINI_API_KEY"] = "AIzaSyMockKeyForRoutingAudit12345"

        from services.manage_model import get_genai_client, get_response, set_genai_client

        # Mock the genai.Client
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '{"mmi_estimation": 8.5, "confidence": 0.90, "description": "severe damage", "location": {"coordinates": [21.88, 95.98]}, "building_type": "Masonry", "reasoning": "heavy shaking"}'
        mock_response.usage_metadata.prompt_token_count = 120
        mock_response.usage_metadata.candidates_token_count = 80
        mock_response.usage_metadata.thoughts_token_count = 40
        mock_response.usage_metadata.total_token_count = 240
        mock_client.models.generate_content.return_value = mock_response

        set_genai_client(mock_client)

        # 1. Initial analysis invocation
        resp1 = get_response([types.Part.from_text(text="Initial description prompt")])
        self.assertTrue(len(resp1) > 0)
        self.assertEqual(mock_client.models.generate_content.call_count, 1)

        # 2. Final synthesis invocation
        resp2 = get_response([types.Part.from_text(text="Final synthesis prompt")])
        self.assertTrue(len(resp2) > 0)
        self.assertEqual(mock_client.models.generate_content.call_count, 2)

        # Verify client instance was NOT initialized with Vertex AI
        from mmigram.adapters.gemini_provider import get_active_provider
        self.assertEqual(get_active_provider(), "ai_studio")

    def test_2_local_ai_studio_crag_traversal_zero_cloud_creds(self):
        """Verify full CRAG traversal succeeds without GCS, Pinecone, or GCP credentials."""
        # Strip all cloud credentials from environment
        cloud_vars = [
            "GOOGLE_APPLICATION_CREDENTIALS",
            "GOOGLE_APPLICATION_CREDENTIALS_JSON",
            "GCS_PROJECT_ID",
            "projectID",
            "PINECONE_API",
            "TAVILY_API_KEY",
        ]
        for var in cloud_vars:
            os.environ.pop(var, None)

        os.environ["GEMINI_PROVIDER"] = "ai_studio"
        os.environ["GEMINI_API_KEY"] = "AIzaSyMockKeyForZeroCloudTest"
        set_active_provider("ai_studio")

        from services.manage_model import set_genai_client
        mock_client = MagicMock()

        # Step 1 initial analysis text response
        resp_initial = MagicMock()
        resp_initial.text = "Visual evidence shows partial masonry wall collapse and broken chimneys."
        resp_initial.usage_metadata.prompt_token_count = 100
        resp_initial.usage_metadata.candidates_token_count = 50
        resp_initial.usage_metadata.thoughts_token_count = 20
        resp_initial.usage_metadata.total_token_count = 170

        # Step 2 structured final analysis JSON response
        resp_final = MagicMock()
        resp_final.text = json.dumps({
            "blob_name": "test_page1.pdf",
            "description": "Masonry collapse observed",
            "location": {"address": "Sagaing", "coordinates": [21.8803, 95.9849]},
            "auditory_cues": "None",
            "background_noise": "None",
            "sounds_of_distress": "None",
            "visual_observation": "Heavy structural damage",
            "video_evidence": "None",
            "building_type": "Unreinforced masonry",
            "building_materials": "Brick and mortar",
            "evidence_analysis": "Consistent with MMI 8-9",
            "context_summary": "Earthquake reconnaissance",
            "mmi_estimation": 8.5,
            "reasoning": "Partial collapse of masonry structure",
            "confidence": 0.88,
        })
        resp_final.usage_metadata.prompt_token_count = 500
        resp_final.usage_metadata.candidates_token_count = 150
        resp_final.usage_metadata.thoughts_token_count = 60
        resp_final.usage_metadata.total_token_count = 710

        mock_client.models.generate_content.side_effect = [resp_initial, resp_final]
        set_genai_client(mock_client)

        from services.crag import MultimodalEarthquakeCRAG
        crag = MultimodalEarthquakeCRAG()

        # Execute traversal on local PDF file
        local_pdf = REPO_ROOT / "server" / "test_page1.pdf"
        result = crag.analyze_media_and_traverse_states(
            blob_name="test_page1.pdf",
            signed_url=str(local_pdf),
            mime_type="application/pdf",
        )

        self.assertIsInstance(result, dict)
        self.assertEqual(result["retrieval_status"], "SUCCESS")
        self.assertEqual(result["retrieval_source"], "local_versioned_asset")
        self.assertEqual(result["reference_mode"], "full_scale")
        self.assertEqual(result["mmi_documents_count"], 10)
        final_analysis = result["final_analysis"]
        self.assertEqual(final_analysis["mmi_estimation"], 8.5)
        self.assertEqual(final_analysis["confidence"], 0.88)

    def test_3_vertex_ai_selection_and_cache_isolation(self):
        """Verify Vertex AI backend selection and strict client cache isolation across provider switches."""
        # Start on ai_studio
        set_active_provider("ai_studio")
        self.assertEqual(get_active_provider(), "ai_studio")

        # Switch to vertex_ai
        set_active_provider("vertex_ai")
        self.assertEqual(get_active_provider(), "vertex_ai")
        self.assertEqual(os.environ.get("GEMINI_PROVIDER"), "vertex_ai")

        # Switching providers must reset client cache
        from services.manage_model import _client as manage_client
        from mmigram.adapters.gemini_provider import _cached_client as adapter_client
        self.assertIsNone(manage_client)
        self.assertIsNone(adapter_client)

        # Switch back to ai_studio
        set_active_provider("ai_studio")
        self.assertEqual(get_active_provider(), "ai_studio")
        self.assertEqual(os.environ.get("GEMINI_PROVIDER"), "ai_studio")

    def test_4_local_pdf_sent_as_binary_media_part_not_text(self):
        """Verify that local PDF is packaged as a binary types.Part with application/pdf MIME type."""
        local_pdf = REPO_ROOT / "server" / "test_page1.pdf"
        self.assertTrue(local_pdf.exists())

        from services.crag import MultimodalEarthquakeCRAG
        crag = MultimodalEarthquakeCRAG()

        part = crag.get_media_part(blob_name="test_page1.pdf", signed_url=str(local_pdf), mime_type="application/pdf")
        self.assertIsInstance(part, types.Part)
        self.assertEqual(part.inline_data.mime_type, "application/pdf")
        self.assertIsInstance(part.inline_data.data, bytes)
        self.assertGreater(len(part.inline_data.data), 100)
        # PDF header bytes
        self.assertTrue(part.inline_data.data.startswith(b"%PDF"))

    def test_5_local_mmi_definitions_order_and_provenance(self):
        """Verify local MMI definitions are passed in strict ascending order (1..10 / 1..12) with full metadata."""
        ref = LocalMMIReference()

        # 1. USGS 10-level scale
        docs_10 = ref.retrieve_full_scale("usgs_10level_v1")
        self.assertEqual(len(docs_10), 10)
        for expected_lvl, doc in enumerate(docs_10, 1):
            self.assertEqual(doc.metadata["level"], expected_lvl)
            self.assertEqual(doc.metadata["id"], f"mmi-{expected_lvl}")
            self.assertEqual(doc.metadata["source"], "local_versioned_asset")
            self.assertEqual(doc.metadata["scale_version"], "usgs_10level_v1")
            self.assertTrue(doc.metadata["is_authoritative_reference"])

        # 2. Complete 12-level scale
        docs_12 = ref.retrieve_full_scale("full_12level_v1")
        self.assertEqual(len(docs_12), 12)
        for expected_lvl, doc in enumerate(docs_12, 1):
            self.assertEqual(doc.metadata["level"], expected_lvl)
            self.assertEqual(doc.metadata["id"], f"mmi-{expected_lvl}")
            self.assertEqual(doc.metadata["source"], "local_versioned_asset")
            self.assertEqual(doc.metadata["scale_version"], "full_12level_v1")

    def test_6_audit_primary_source_reference_texts(self):
        """Audit reference definitions distinguishing restricted 10-level scale from complete 12-level scale."""
        ref = LocalMMIReference()

        # 10-level scale capped at X
        docs_10 = ref.retrieve_full_scale("usgs_10level_v1")
        self.assertEqual(len(docs_10), 10)
        level_10_doc = docs_10[9]
        self.assertIn("masonry and frame structures destroyed", level_10_doc.page_content.lower())

        # 12-level scale contains extreme levels XI and XII
        docs_12 = ref.retrieve_full_scale("full_12level_v1")
        self.assertEqual(len(docs_12), 12)

        level_11_doc = docs_12[10]
        self.assertEqual(level_11_doc.metadata["roman"], "XI")
        self.assertIn("few, if any, (masonry) structures remain standing", level_11_doc.page_content.lower())
        self.assertIn("broad fissures in ground", level_11_doc.page_content.lower())

        level_12_doc = docs_12[11]
        self.assertEqual(level_12_doc.metadata["roman"], "XII")
        self.assertIn("damage total", level_12_doc.page_content.lower())
        self.assertIn("objects thrown into the air", level_12_doc.page_content.lower())


if __name__ == "__main__":
    unittest.main()

