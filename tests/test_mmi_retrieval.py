"""
Unit and Regression Tests for Pinecone MMI Reference Retrieval & Web Search Fallbacks.

Verifies:
  1. Full-scale retrieval deterministically fetches all 10 MMI definitions (I to X).
  2. Scale completeness validator detects missing levels, duplicates, and empty definitions.
  3. Incomplete full-scale retrieval sets status INCOMPLETE and triggers QC flags.
  4. Vector-search mode retrieves candidate definitions by semantic similarity.
  5. CRAG grading in full-scale mode preserves all 10 definitions without vector exclusions.
  6. CRAG grading in vector-search mode rejects unrelated definitions (e.g. MMI 1 for collapse)
     without marking all references as automatically relevant.
  7. Empty or whitespace web-search fallback results are rejected.
  8. QC flags REFERENCE_RETRIEVAL_FAILED when retrieval is UNRETRIEVED, FAILED, or INCOMPLETE.
  9. Pipeline and CLI provenance records retrieval mode, status, source, and document count.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from langchain.schema import Document

# Ensure server and src directories are in path
REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = REPO_ROOT / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from services.MMIRetriever import MMIRetriever, validate_scale_completeness
from mmigram.qc.checker import evaluate_quality
from mmigram.qc.rules import FLAG_REFERENCE_RETRIEVAL_FAILED
from mmigram.core.state import Coordinates, MMIEstimationResult, StructuralDamageAssessment
from mmigram.workflow.general_steer_pipeline import GeneralSteerPipeline


class TestFullScaleMMIRetrieval(unittest.TestCase):
    """Verifies deterministic full-scale (I-X) retrieval and completeness validation."""

    def _create_mock_full_scale_vectors(self, omit_ids=None, empty_ids=None):
        omit_ids = set(omit_ids or [])
        empty_ids = set(empty_ids or [])
        vectors = {}
        for i in range(1, 11):
            key = f"mmi-{i}"
            if key in omit_ids:
                continue
            text = "" if key in empty_ids else f"Official definition text for MMI {i} describing shaking effects."
            vec = MagicMock()
            vec.id = key
            vec.metadata = {"text": text}
            vectors[key] = vec
        return vectors

    def test_full_scale_retrieval_success(self):
        """Full-scale mode must fetch all 10 definitions in order with authoritative metadata."""
        retriever = MMIRetriever()
        mock_index = MagicMock()
        mock_res = MagicMock()
        mock_res.vectors = self._create_mock_full_scale_vectors()
        mock_index.fetch.return_value = mock_res
        retriever.index = mock_index

        docs = retriever.retrieveDocs(reference_mode="full_scale")

        self.assertEqual(len(docs), 10)
        self.assertEqual(retriever.last_retrieval_status, "SUCCESS")
        self.assertEqual(retriever.last_retrieval_mode, "full_scale")

        for i, doc in enumerate(docs, 1):
            self.assertEqual(doc.metadata["id"], f"mmi-{i}")
            self.assertEqual(doc.metadata["level"], i)
            self.assertEqual(doc.metadata["reference_mode"], "full_scale")
            self.assertEqual(doc.metadata["source"], "pinecone_mmi_idx")
            self.assertTrue(doc.metadata["is_authoritative_reference"])
            self.assertIn(f"MMI {i}", doc.page_content)

        is_complete, msg, details = validate_scale_completeness(docs)
        self.assertTrue(is_complete)
        self.assertEqual(details["missing_levels"], [])
        self.assertEqual(details["empty_levels"], [])

    def test_full_scale_detects_missing_levels(self):
        """When any MMI level is missing from the index, status must be INCOMPLETE."""
        retriever = MMIRetriever()
        mock_index = MagicMock()
        mock_res = MagicMock()
        # Omit mmi-8 and mmi-9
        mock_res.vectors = self._create_mock_full_scale_vectors(omit_ids=["mmi-8", "mmi-9"])
        mock_index.fetch.return_value = mock_res
        retriever.index = mock_index

        docs = retriever.retrieveDocs(reference_mode="full_scale")

        self.assertEqual(len(docs), 8)
        self.assertEqual(retriever.last_retrieval_status, "INCOMPLETE")

        is_complete, msg, details = validate_scale_completeness(docs)
        self.assertFalse(is_complete)
        self.assertEqual(details["missing_levels"], [8, 9])
        self.assertIn("missing levels [8, 9]", msg)

    def test_full_scale_detects_empty_definitions(self):
        """When a definition text is empty or whitespace, status must be INCOMPLETE."""
        retriever = MMIRetriever()
        mock_index = MagicMock()
        mock_res = MagicMock()
        # Make mmi-4 empty
        mock_res.vectors = self._create_mock_full_scale_vectors(empty_ids=["mmi-4"])
        mock_index.fetch.return_value = mock_res
        retriever.index = mock_index

        docs = retriever.retrieveDocs(reference_mode="full_scale")

        self.assertEqual(len(docs), 10)
        self.assertEqual(retriever.last_retrieval_status, "INCOMPLETE")

        is_complete, msg, details = validate_scale_completeness(docs)
        self.assertFalse(is_complete)
        self.assertEqual(details["empty_levels"], [4])
        self.assertIn("empty definitions for levels [4]", msg)

    def test_scale_completeness_detects_duplicates(self):
        """Validator must flag duplicate levels."""
        docs = [
            Document(page_content=f"Def {i}", metadata={"id": f"mmi-{i}", "level": i})
            for i in range(1, 10)
        ]
        # Append duplicate mmi-3 instead of mmi-10
        docs.append(Document(page_content="Dup Def 3", metadata={"id": "mmi-3", "level": 3}))

        is_complete, msg, details = validate_scale_completeness(docs)
        self.assertFalse(is_complete)
        self.assertEqual(details["duplicate_levels"], [3])
        self.assertEqual(details["missing_levels"], [10])

    def test_full_scale_index_unavailable(self):
        """Uninitialized index returns empty list and UNAVAILABLE status."""
        retriever = MMIRetriever()
        retriever.index = None

        docs = retriever.retrieveDocs(reference_mode="full_scale")
        self.assertEqual(docs, [])
        self.assertEqual(retriever.last_retrieval_status, "UNAVAILABLE")


class TestVectorSearchMMIRetriever(unittest.TestCase):
    """Verifies vector-search retrieval behavior using search_records and inference."""

    def test_search_records_successful_retrieval(self):
        """Vector search must return candidate Document objects with scores, IDs, and vector_search mode."""
        retriever = MMIRetriever()
        mock_index = MagicMock()

        mock_hit1 = MagicMock()
        mock_hit1.id = "mmi-9"
        mock_hit1.score = 0.88
        mock_hit1.fields = {"text": "MMI 9 (Violent): General panic. Damage considerable in specially designed structures."}

        mock_hit2 = MagicMock()
        mock_hit2.id = "mmi-10"
        mock_hit2.score = 0.82
        mock_hit2.fields = {"text": "MMI 10 (Very Violent / Extreme): Most masonry structures destroyed with foundations."}

        mock_response = MagicMock()
        mock_response.result.hits = [mock_hit1, mock_hit2]
        mock_index.search_records.return_value = mock_response
        retriever.index = mock_index

        docs = retriever.retrieveDocs("Severe masonry collapse", reference_mode="vector_search")

        self.assertEqual(len(docs), 2)
        self.assertEqual(docs[0].metadata["id"], "mmi-9")
        self.assertEqual(docs[0].metadata["level"], 9)
        self.assertEqual(docs[0].metadata["score"], 0.88)
        self.assertEqual(docs[0].metadata["reference_mode"], "vector_search")
        self.assertTrue(docs[0].metadata["is_authoritative_reference"])
        self.assertEqual(docs[0].metadata["source"], "pinecone_mmi_idx")
        self.assertIn("General panic", docs[0].page_content)
        self.assertEqual(retriever.last_retrieval_status, "SUCCESS")

    def test_fallback_to_inference_embed_when_search_records_unavailable(self):
        """When search_records raises AttributeError, fallback to pc.inference.embed with llama-text-embed-v2."""
        retriever = MMIRetriever()
        mock_index = MagicMock()
        mock_index.search_records.side_effect = AttributeError("search_records not supported on this client")

        mock_pc = MagicMock()
        mock_emb = MagicMock()
        mock_emb.values = [0.1] * 1024
        mock_pc.inference.embed.return_value = [mock_emb]

        mock_match = MagicMock()
        mock_match.id = "mmi-8"
        mock_match.score = 0.79
        mock_match.metadata = {"text": "MMI 8 (Destructive): Damage slight in specially designed structures; considerable in ordinary buildings."}
        
        mock_query_res = MagicMock()
        mock_query_res.matches = [mock_match]
        mock_index.query.return_value = mock_query_res

        retriever.index = mock_index
        retriever.pc = mock_pc

        docs = retriever.retrieveDocs("Considerable damage in ordinary buildings", reference_mode="vector_search")

        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].metadata["id"], "mmi-8")
        self.assertEqual(docs[0].metadata["level"], 8)
        self.assertEqual(docs[0].metadata["score"], 0.79)
        self.assertEqual(docs[0].metadata["reference_mode"], "vector_search")
        self.assertTrue(docs[0].metadata["is_authoritative_reference"])

    def test_empty_query_in_vector_search(self):
        """Empty query in vector search returns EMPTY status."""
        retriever = MMIRetriever()
        retriever.index = MagicMock()

        self.assertEqual(retriever.retrieveDocs("", reference_mode="vector_search"), [])
        self.assertEqual(retriever.last_retrieval_status, "EMPTY")

    def test_retriever_legacy_retrieve_helper(self):
        """retrieve() helper should parse numerical scores from document IDs."""
        retriever = MMIRetriever()
        mock_doc = MagicMock()
        mock_doc.metadata = {"id": "mmi-9"}
        with patch.object(retriever, "retrieveDocs", return_value=[mock_doc]):
            scores = retriever.retrieve("violent shaking")
            self.assertEqual(scores, [9])


class TestCRAGGradingBehavior(unittest.TestCase):
    """Verifies CRAG grading behavior under full_scale and vector_search modes."""

    def test_grade_documents_full_scale_preserves_all_ten_definitions(self):
        """In full_scale mode, all 10 verified definitions are preserved without exclusions."""
        from services.crag import MultimodalEarthquakeCRAG

        crag = MultimodalEarthquakeCRAG()
        docs = [
            Document(page_content=f"Official MMI {i} definition text", metadata={"id": f"mmi-{i}", "level": i})
            for i in range(1, 11)
        ]

        state = {
            "context_summary": "Observed severe structural damage and partial collapse",
            "mmi_documents": docs,
            "reference_mode": "full_scale",
            "retrieval_status": "SUCCESS",
            "retrieval_source": "pinecone_mmi_idx",
        }

        # In full-scale mode, grading validates completeness and does NOT drop definitions
        result = crag.grade_documents(state)

        self.assertEqual(len(result["mmi_documents"]), 10)
        self.assertEqual(result["web_search"], "No")
        self.assertEqual(result["retrieval_status"], "SUCCESS")

    def test_grade_documents_full_scale_incomplete_triggers_web_search(self):
        """In full_scale mode with missing definitions, grading triggers search fallback."""
        from services.crag import MultimodalEarthquakeCRAG

        crag = MultimodalEarthquakeCRAG()
        # Only 5 documents provided
        docs = [
            Document(page_content=f"Official MMI {i} definition text", metadata={"id": f"mmi-{i}", "level": i})
            for i in range(1, 6)
        ]

        state = {
            "context_summary": "Observed severe structural damage",
            "mmi_documents": docs,
            "reference_mode": "full_scale",
            "retrieval_status": "SUCCESS",
            "retrieval_source": "pinecone_mmi_idx",
        }

        result = crag.grade_documents(state)

        self.assertEqual(result["web_search"], "Yes")
        self.assertEqual(result["retrieval_status"], "INCOMPLETE")

    def test_grade_documents_vector_search_rejects_unrelated_definition(self):
        """In vector-search mode, non-damage definition (MMI 1) is rejected, while damage definition (MMI 9) is retained."""
        from services.crag import MultimodalEarthquakeCRAG

        crag = MultimodalEarthquakeCRAG()
        doc_mmi1 = Document(
            page_content="MMI 1 (Not Felt): Not felt except by a very few people. No damage to structures.",
            metadata={"id": "mmi-1", "level": 1}
        )
        doc_mmi9 = Document(
            page_content="MMI 9 (Violent): General panic. Damage great in substantial buildings, partial collapse.",
            metadata={"id": "mmi-9", "level": 9}
        )

        state = {
            "context_summary": "Substantial failure of masonry walls, partial collapse, violent shaking in Sagaing",
            "mmi_documents": [doc_mmi1, doc_mmi9],
            "reference_mode": "vector_search",
            "retrieval_status": "SUCCESS",
            "retrieval_source": "pinecone_mmi_idx",
        }

        # Mock structured response from Gemini:
        # doc_mmi1 -> binary_score: "no"
        # doc_mmi9 -> binary_score: "yes"
        def mock_grading_response(contents, schema):
            text_prompt = contents[0].text if hasattr(contents[0], "text") else str(contents[0])
            if "Retrieved Reference Document (mmi-1)" in text_prompt:
                return {"binary_score": "no"}
            elif "Retrieved Reference Document (mmi-9)" in text_prompt:
                return {"binary_score": "yes"}
            return {"binary_score": "no"}

        with patch.object(crag, "get_structured_response", side_effect=mock_grading_response):
            result = crag.grade_documents(state)

        # MMI 1 must be filtered out, MMI 9 retained
        self.assertEqual(len(result["mmi_documents"]), 1)
        self.assertEqual(result["mmi_documents"][0].metadata["id"], "mmi-9")
        # Because at least 1 relevant document was retained, web_search must be "No"
        self.assertEqual(result["web_search"], "No")


class TestWebSearchRejectionAndProvenance(unittest.TestCase):
    """Verifies that empty web-search results are rejected and cannot pose as reference documents."""

    def test_reject_empty_or_whitespace_web_search(self):
        """CRAG web_search node must reject empty or whitespace-only results."""
        from services.crag import MultimodalEarthquakeCRAG

        crag = MultimodalEarthquakeCRAG()
        mock_tool = MagicMock()
        mock_tool.invoke.return_value = [
            {"content": ""},
            {"content": "   \n\t  "},
            {"content": "short"}
        ]
        crag.web_search_tool = mock_tool

        initial_state = {
            "context_summary": "damage assessment query",
            "mmi_documents": [],
            "retrieval_status": "UNRETRIEVED",
            "retrieval_source": "none",
        }

        result_state = crag.web_search(initial_state)

        self.assertEqual(len(result_state["mmi_documents"]), 0)
        self.assertEqual(result_state["retrieval_status"], "UNRETRIEVED")
        self.assertEqual(result_state["retrieval_source"], "none")

    def test_accept_substantive_web_search_as_unauthoritative_fallback(self):
        """Substantive web content is accepted as fallback, but marked as non-authoritative."""
        from services.crag import MultimodalEarthquakeCRAG

        crag = MultimodalEarthquakeCRAG()
        mock_tool = MagicMock()
        mock_tool.invoke.return_value = [
            {"content": "USGS MMI Scale definitions indicate severe masonry fracture and chimneys toppled."}
        ]
        crag.web_search_tool = mock_tool

        initial_state = {
            "context_summary": "masonry collapse",
            "mmi_documents": [],
            "retrieval_status": "UNRETRIEVED",
            "retrieval_source": "none",
        }

        result_state = crag.web_search(initial_state)

        self.assertEqual(len(result_state["mmi_documents"]), 1)
        doc = result_state["mmi_documents"][0]
        self.assertFalse(doc.metadata["is_authoritative_reference"])
        self.assertEqual(doc.metadata["source"], "web_search_fallback")
        self.assertEqual(result_state["retrieval_status"], "FALLBACK_WEB")


class TestQCRetrievalRules(unittest.TestCase):
    """Verifies Quality Control flagging when reference retrieval fails or is incomplete."""

    def test_qc_flags_when_reference_retrieval_unretrieved(self):
        """QC status must be FLAGGED and contain REFERENCE_RETRIEVAL_FAILED when retrieval is UNRETRIEVED."""
        coords = Coordinates(latitude=21.88, longitude=95.98, is_valid=True)
        est = MMIEstimationResult(mmi_value=8.0, confidence=0.85, is_calibrated=False)
        damage = StructuralDamageAssessment(visual_observations="Considerable damage to brick masonry structures.")

        qc = evaluate_quality(
            coordinates=coords,
            estimation=est,
            damage=damage,
            retrieval_status="UNRETRIEVED"
        )

        self.assertEqual(qc.qc_status, "FLAGGED")
        self.assertIn(FLAG_REFERENCE_RETRIEVAL_FAILED, qc.qc_flags)

    def test_qc_flags_when_reference_retrieval_incomplete(self):
        """QC status must be FLAGGED and contain REFERENCE_RETRIEVAL_FAILED when retrieval is INCOMPLETE."""
        coords = Coordinates(latitude=21.88, longitude=95.98, is_valid=True)
        est = MMIEstimationResult(mmi_value=8.0, confidence=0.85, is_calibrated=False)
        damage = StructuralDamageAssessment(visual_observations="Considerable damage to brick masonry structures.")

        qc = evaluate_quality(
            coordinates=coords,
            estimation=est,
            damage=damage,
            retrieval_status="INCOMPLETE"
        )

        self.assertEqual(qc.qc_status, "FLAGGED")
        self.assertIn(FLAG_REFERENCE_RETRIEVAL_FAILED, qc.qc_flags)

    def test_qc_clean_when_reference_retrieval_success(self):
        """QC status must NOT include REFERENCE_RETRIEVAL_FAILED when retrieval is SUCCESS."""
        coords = Coordinates(latitude=21.88, longitude=95.98, is_valid=True)
        est = MMIEstimationResult(mmi_value=8.0, confidence=0.85, is_calibrated=False)
        damage = StructuralDamageAssessment(visual_observations="Considerable damage to brick masonry structures.")

        qc = evaluate_quality(
            coordinates=coords,
            estimation=est,
            damage=damage,
            retrieval_status="SUCCESS"
        )

        self.assertNotIn(FLAG_REFERENCE_RETRIEVAL_FAILED, qc.qc_flags)


class TestPipelineReferenceModeProvenance(unittest.TestCase):
    """Verifies that the general StEER pipeline captures reference mode in provenance."""

    def test_pipeline_provenance_captures_full_scale_mode(self):
        """Offline pipeline records full_scale reference mode in provenance."""
        pipeline = GeneralSteerPipeline(mode="offline", reference_mode="full_scale")
        pdf_path = REPO_ROOT / "server" / "test_page1.pdf"
        result = pipeline.process_pdf(pdf_path)

        prov = result["provenance"]
        ret = prov["retrieval"]
        self.assertEqual(ret["reference_mode"], "full_scale")
        self.assertEqual(ret["status"], "SUCCESS")
        self.assertEqual(ret["document_count"], 10)
        self.assertTrue(ret["has_authoritative_reference"])

    def test_pipeline_provenance_captures_vector_search_mode(self):
        """Offline pipeline records vector_search reference mode in provenance."""
        pipeline = GeneralSteerPipeline(mode="offline", reference_mode="vector_search")
        pdf_path = REPO_ROOT / "server" / "test_page1.pdf"
        result = pipeline.process_pdf(pdf_path)

        prov = result["provenance"]
        ret = prov["retrieval"]
        self.assertEqual(ret["reference_mode"], "vector_search")
        self.assertEqual(ret["status"], "SUCCESS")
        self.assertEqual(ret["document_count"], 3)
        self.assertTrue(ret["has_authoritative_reference"])

    def test_live_pipeline_document_count_accurately_reflects_ten_definitions(self):
        """Live CRAG execution must record document_count == 10 (not 0) when 10 definitions are retrieved."""
        pipeline = GeneralSteerPipeline(mode="live", allow_live_api=True, reference_mode="full_scale")
        pdf_path = REPO_ROOT / "server" / "test_page1.pdf"

        # Mock 10 full-scale documents returned from CRAG traversal
        ten_docs = [
            Document(page_content=f"MMI {i} description", metadata={"id": f"mmi-{i}", "level": i})
            for i in range(1, 11)
        ]
        mock_crag_result = {
            "final_analysis": {
                "mmi_estimation": 9.5,
                "confidence": 0.90,
                "description": "Substantial failure of masonry and panel walls",
                "location": "21.88, 95.98",
                "building_type": "Masonry",
                "building_materials": "Brick and mortar",
            },
            "mmi_documents": ten_docs,
            "mmi_documents_count": 10,
            "retrieval_status": "SUCCESS",
            "retrieval_source": "pinecone_mmi_idx",
            "reference_mode": "full_scale",
            "token_usage": {"calls": 3, "total_tokens": 5000},
        }

        with patch("services.utilities.upload_to_gcs", return_value="https://storage.googleapis.com/test-bucket/test.pdf"), \
             patch("services.crag.MultimodalEarthquakeCRAG") as MockCRAG:
            mock_instance = MockCRAG.return_value
            mock_instance.analyze_media_and_traverse_states.return_value = mock_crag_result

            result = pipeline.process_pdf(pdf_path)

        prov_ret = result["provenance"]["retrieval"]
        self.assertEqual(prov_ret["document_count"], 10)
        self.assertNotEqual(prov_ret["document_count"], 0)
        self.assertEqual(prov_ret["status"], "SUCCESS")
        self.assertEqual(prov_ret["reference_mode"], "full_scale")
        self.assertTrue(prov_ret["has_authoritative_reference"])

    def test_cli_model_and_thinking_settings_override_env(self):
        """CLI arguments for --model and --thinking-level must strictly override .env settings."""
        from mmigram.cli import build_parser

        # Set environment variables to legacy values
        os.environ["GEMINI_MODEL"] = "gemini-2.5-flash"
        os.environ["GEMINI_THINKING_LEVEL"] = "LOW"
        os.environ["MMI_REFERENCE_MODE"] = "vector_search"

        parser = build_parser()
        args = parser.parse_args([
            "analyze",
            "--pdf", str(REPO_ROOT / "server" / "test_page1.pdf"),
            "--model", "gemini-3.8-flash",
            "--thinking-level", "HIGH",
            "--reference-mode", "full_scale",
        ])

        with patch("mmigram.cli.GeneralSteerPipeline") as MockPipeline:
            mock_instance = MockPipeline.return_value
            mock_instance.process_pdf.return_value = {
                "pipeline_status": "COMPLETED",
                "provenance": {
                    "is_synthetic": False,
                    "baseline_type": "RECORDED_LEGACY_OUTPUT",
                    "model_identifier": "gemini-3.8-flash",
                    "thinking_level": "HIGH",
                    "execution_mode": "offline",
                    "source_sha256": "abc123",
                    "retrieval": {"status": "SUCCESS", "source": "offline_fixture", "reference_mode": "full_scale", "document_count": 10, "has_authoritative_reference": True},
                },
                "document_extraction": {"extraction_status": "SUCCESS"},
                "seismic_intensity": {"mmi_estimation": 9.5, "confidence": 0.90, "is_calibrated": False},
                "geographic_resolution": {"location": {}, "comparison_status": "COORDINATES_AGREE"},
                "quality_control": {"status": "PASSED", "flags": [], "score": 1.0},
                "human_in_the_loop": {"review_required": False, "review_status": "NOT_REQUIRED"},
            }

            from mmigram.cli import cmd_analyze
            exit_code = cmd_analyze(args)

            self.assertEqual(exit_code, 0)
            # Environment variables must be overridden to the CLI values
            self.assertEqual(os.environ["GEMINI_MODEL"], "gemini-3.8-flash")
            self.assertEqual(os.environ["GEMINI_THINKING_LEVEL"], "HIGH")
            self.assertEqual(os.environ["MMI_REFERENCE_MODE"], "full_scale")

            # Pipeline was instantiated with overridden CLI arguments
            MockPipeline.assert_called_once()
            call_kwargs = MockPipeline.call_args[1]
            self.assertEqual(call_kwargs["model_name"], "gemini-3.8-flash")
            self.assertEqual(call_kwargs["thinking_level"], "HIGH")
            self.assertEqual(call_kwargs["reference_mode"], "full_scale")


if __name__ == "__main__":
    unittest.main()
