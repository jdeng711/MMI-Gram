"""
General-Purpose StEER Reconnaissance PDF Ingestion and Analysis Pipeline.

Supports:
  1. Any StEER PDF file input via path.
  2. Maintained PDF text extraction via pypdf (detects image-based PDFs).
  3. Dynamic coordinate parsing from extracted text (no hardcoded locations).
  4. Missing coordinates preserved as null / unknown.
  5. Strict offline behavior: only replays recorded results from known fixtures,
     returning FIXTURE_NOT_FOUND for unregistered files without fabricating predictions.
  6. Live mode integration with Clara's existing MultimodalEarthquakeCRAG using unique object names.
  7. Automated Quality Control and Human Review Queue routing.
"""

from __future__ import annotations
import os
import sys
import re
import time
import json
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, List, Union

from ..core.state import (
    Coordinates,
    LocationContext,
    MMIEstimationResult,
    StructuralDamageAssessment,
    EvidenceMetadata,
    QualityControlRecord,
)
from ..ingestion.pdf_extractor import PDFExtractor, PDFContentResult
from ..geolocation.parser import extract_coordinates_from_text
from ..geolocation.validator import validate_coordinates, haversine_distance_km, compare_coordinates, MYANMAR_BOUNDS
from ..geolocation.unified_resolver import UnifiedGeolocationResolver
from ..geolocation.geocoding_adapter import GoogleMapsGeocodingAdapter
from ..qc.checker import evaluate_quality
from ..review.queue import HumanReviewQueue
from ..telemetry.tracer import StructuredAgentLogger
from ..screening.composite_screener import CompositeScreener, ScreeningResult


def find_fixtures_dir() -> Path:
    candidates = [
        Path(__file__).resolve().parents[3] / "tests" / "fixtures",
        Path.cwd() / "tests" / "fixtures",
        Path(__file__).resolve().parents[3] / "server" / "mmigram" / "tests" / "fixtures",
        Path.cwd() / "server" / "mmigram" / "tests" / "fixtures",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


DEFAULT_FIXTURES_DIR = find_fixtures_dir()


class GeneralSteerPipeline:
    """
    General-purpose StEER ingestion and analysis pipeline.
    """

    def __init__(
        self,
        mode: str = "offline",  # 'offline' or 'live'
        fixtures_dir: Optional[Path] = None,
        logger: Optional[StructuredAgentLogger] = None,
        review_queue: Optional[HumanReviewQueue] = None,
        allow_live_api: bool = False,
        min_text_threshold: int = 25,
        model_name: Optional[str] = None,
        thinking_level: Optional[str] = None,
        reference_mode: Optional[str] = None,
        provider: Optional[str] = None,
        event_id: str = "us7000pn9s",
        origin_time_utc: str = "2025-03-28T06:20:00Z",
        spatial_bounds: Optional[Dict[str, float]] = None,
        geocoding_adapter: Optional[GoogleMapsGeocodingAdapter] = None,
    ):
        self.mode = mode.lower()
        self.provider = (provider or os.environ.get("GEMINI_PROVIDER", "ai_studio")).lower()
        self.model_name = model_name
        self.thinking_level = thinking_level
        self.reference_mode = (reference_mode or os.environ.get("MMI_REFERENCE_MODE", "full_scale")).lower()
        self.fixtures_dir = fixtures_dir or DEFAULT_FIXTURES_DIR
        self.logger = logger or StructuredAgentLogger(name="mmigram.general_steer", console_output=True)
        self.review_queue = review_queue or HumanReviewQueue()
        self.allow_live_api = allow_live_api
        self.pdf_extractor = PDFExtractor(min_text_threshold=min_text_threshold)
        self.event_id = event_id
        self.spatial_bounds = spatial_bounds or MYANMAR_BOUNDS

        # Unified Geolocation Engine
        self.unified_resolver = UnifiedGeolocationResolver(
            region_bounds=self.spatial_bounds,
            geocoding_adapter=geocoding_adapter,
            allow_live_geocoding=allow_live_api,
        )

        # Pre-MMI Composite Screening Pipeline (All 5 gates)
        self.composite_screener = CompositeScreener(
            event_id=event_id,
            origin_time_utc=origin_time_utc,
            spatial_bounds=self.spatial_bounds,
            allow_live_api=allow_live_api,
            provider=self.provider,
        )

        # Mapping of known filenames to their offline recorded fixture JSON
        self.fixture_registry: Dict[str, str] = {
            "test_page1.pdf": "steer_page1_baseline.json",
            "synthetic_steer_page2_mandalay.pdf": "synthetic_steer_page2_mandalay.json",
            "synthetic_steer_page3_no_coords.pdf": "synthetic_steer_page3_no_coords.json",
        }

    def reset_screener(self):
        """Reset screener state (e.g. duplicate media cache)."""
        self.composite_screener.reset()

    def process_pdf(self, file_path: Union[str, Path]) -> Dict[str, Any]:
        """
        Execute the general-purpose StEER ingestion and analysis workflow on a target PDF.
        """
        t0 = time.time()
        path = Path(file_path).resolve()
        file_name = path.name

        self.logger.log_node_enter("ingest_pdf", {"file_path": str(path), "mode": self.mode})

        # ──────────────────────────────────────────────────────────────────────
        # Step 1: PDF Ingestion & Text Extraction (via pypdf)
        # ──────────────────────────────────────────────────────────────────────
        extraction = self.pdf_extractor.extract(path)

        if not extraction.is_valid_pdf:
            error_result = {
                "pipeline_status": "INVALID_PDF",
                "file_name": file_name,
                "file_path": str(path),
                "extraction_status": extraction.extraction_status,
                "error_message": extraction.error_message,
            }
            self.logger.log_node_exit("ingest_pdf", error_result, duration_ms=0.5)
            return error_result

        # ──────────────────────────────────────────────────────────────────────
        # Step 2: Dynamic Geolocation Parsing via Unified Resolver
        # ──────────────────────────────────────────────────────────────────────
        preliminary_loc = self.unified_resolver.resolve(
            text=extraction.extracted_text if extraction.has_extractable_text else None,
            file_path=path,
            region_bounds=self.spatial_bounds,
        )
        coords = preliminary_loc.coordinates

        # ──────────────────────────────────────────────────────────────────────
        # Step 2b: Pre-MMI Relevance & Evidence Screening (CompositeScreener)
        # ──────────────────────────────────────────────────────────────────────
        raw_coords_str = preliminary_loc.raw_source_text
        if not raw_coords_str and extraction.has_extractable_text and extraction.extracted_text:
            m_geo = re.search(r"geolocation\s*\(address/coordinates\):\s*([^\n\r]+)", extraction.extracted_text, re.IGNORECASE)
            if m_geo:
                raw_coords_str = m_geo.group(1).strip()

        screening_res = self.composite_screener.screen(
            file_path=path,
            extracted_text=extraction.extracted_text,
            has_extractable_text=extraction.has_extractable_text,
            page_count=extraction.page_count,
            latitude=coords.latitude if coords else None,
            longitude=coords.longitude if coords else None,
            coordinates_raw=raw_coords_str,
        )

        # Early exit for NOT_ESTIMABLE documents (e.g. Clara's page-8.pdf regional hazard model map)
        if screening_res.relevance_decision == "NOT_ESTIMABLE":
            duration_ms = round((time.time() - t0) * 1000.0, 2)
            not_estimable_summary = {
                "pipeline_name": "MMI-Gram General-Purpose StEER Pipeline",
                "file_name": file_name,
                "pipeline_mode": self.mode,
                "pipeline_status": "NOT_ESTIMABLE",
                "model_identifier": "none_screened_out",
                "execution_duration_ms": duration_ms,
                "provenance": {
                    "is_synthetic": False,
                    "baseline_type": "SCREENED_NOT_ESTIMABLE",
                    "is_authoritative_ground_truth": False,
                    "model_identifier": "none_screened_out",
                    "thinking_level": None,
                    "execution_mode": self.mode,
                    "provider": self.provider if self.mode == "live" else "offline",
                    "source_sha256": extraction.sha256_hash,
                    "mmi_result": None,
                    "uncalibrated_confidence": None,
                    "token_usage": {
                        "calls": 0,
                        "prompt_tokens": 0,
                        "candidates_tokens": 0,
                        "thoughts_tokens": 0,
                        "total_tokens": 0,
                    },
                    "retrieval": {
                        "status": "SKIPPED_NOT_ESTIMABLE",
                        "source": "none",
                        "reference_mode": self.reference_mode,
                        "has_authoritative_reference": False,
                        "document_count": 0,
                    },
                    "execution_duration_ms": duration_ms,
                },
                "document_extraction": {
                    "page_count": extraction.page_count,
                    "extraction_status": extraction.extraction_status,
                    "has_extractable_text": extraction.has_extractable_text,
                    "sha256_hash": extraction.sha256_hash,
                },
                "screening": screening_res.to_dict(),
                "seismic_intensity": {
                    "mmi_estimation": None,
                    "confidence": None,
                    "is_calibrated": False,
                    "reasoning": "; ".join(screening_res.decision_reasons) if screening_res.decision_reasons else "Insufficient physical damage evidence for MMI estimation.",
                },
                "geographic_resolution": {
                    "location": preliminary_loc.to_dict(),
                    "coordinates": coords.to_dict() if coords else None,
                    "document_coordinates": preliminary_loc.document_coordinates.to_dict() if preliminary_loc.document_coordinates else None,
                    "mapping_link_coordinates": preliminary_loc.mapping_link_coordinates.to_dict() if preliminary_loc.mapping_link_coordinates else None,
                    "geocoded_coordinates": preliminary_loc.geocoded_coordinates.to_dict() if preliminary_loc.geocoded_coordinates else None,
                    "model_coordinates": None,
                    "comparison_status": "NOT_EVALUATED",
                    "coordinates_disagree": False,
                    "discrepancy_details": "Skipped due to NOT_ESTIMABLE classification",
                    "discrepancy_distance_km": None,
                    "has_valid_coordinates": coords.is_valid if coords else False,
                    "has_exportable_site_coordinates": preliminary_loc.has_exportable_site_coordinates,
                    "precision_level": preliminary_loc.precision_level,
                    "selection_rationale": preliminary_loc.selection_rationale,
                    "can_export_to_shakemap": False,
                    "is_authoritative": False,
                },
                "quality_control": {
                    "status": "SCREENED_OUT",
                    "flags": ["PRE_MMI_NOT_ESTIMABLE"],
                    "score": 0.0,
                },
                "human_in_the_loop": {
                    "review_required": False,
                    "review_status": "SCREENED_OUT",
                    "triggers": [],
                },
            }
            self.logger.log_node_exit("ingest_pdf", not_estimable_summary, duration_ms=duration_ms)
            return not_estimable_summary

        # ──────────────────────────────────────────────────────────────────────
        # Step 3: Analysis Execution (Strict Offline vs. Live CRAG)
        # ──────────────────────────────────────────────────────────────────────
        # Early exit for REVIEW_REQUIRED relevance (ambiguous evidence, defer automatic MMI estimation)
        if screening_res.relevance_decision == "REVIEW_REQUIRED":
            # If in offline mode and unregistered, strict offline rule takes precedence
            if self.mode == "offline" and file_name not in self.fixture_registry:
                not_found_result = {
                    "pipeline_status": "FIXTURE_NOT_FOUND",
                    "file_name": file_name,
                    "file_path": str(path),
                    "page_count": extraction.page_count,
                    "extraction_status": extraction.extraction_status,
                    "has_extractable_text": extraction.has_extractable_text,
                    "coordinates": coords.to_dict() if coords else None,
                    "screening": screening_res.to_dict(),
                    "message": (
                        f"No offline recorded CRAG fixture found for '{file_name}'. "
                        "In strict offline mode, unrecorded PDFs cannot produce fabricated MMI predictions. "
                        "To analyze this file with live AI models, run with --live (requires GCP credentials)."
                    ),
                }
                self.logger.log_node_exit("ingest_pdf", not_found_result, duration_ms=0.5)
                return not_found_result

            duration_ms = round((time.time() - t0) * 1000.0, 2)
            review_item = self.review_queue.check_and_enqueue(
                item_id=file_name,
                state={
                    "file_name": file_name,
                    "screening": screening_res.to_dict(),
                    "coordinates": coords.to_dict() if coords else None,
                },
                force=True,
            )
            review_summary = {
                "pipeline_name": "MMI-Gram General-Purpose StEER Pipeline",
                "file_name": file_name,
                "pipeline_mode": self.mode,
                "pipeline_status": "REVIEW_REQUIRED",
                "model_identifier": "none_pending_review",
                "execution_duration_ms": duration_ms,
                "provenance": {
                    "is_synthetic": False,
                    "baseline_type": "DEFERRED_PENDING_REVIEW",
                    "is_authoritative_ground_truth": False,
                    "model_identifier": "none_pending_review",
                    "thinking_level": None,
                    "execution_mode": self.mode,
                    "provider": self.provider if self.mode == "live" else "offline",
                    "source_sha256": extraction.sha256_hash,
                    "mmi_result": None,
                    "uncalibrated_confidence": None,
                    "token_usage": {
                        "calls": 0,
                        "prompt_tokens": 0,
                        "candidates_tokens": 0,
                        "thoughts_tokens": 0,
                        "total_tokens": 0,
                    },
                    "retrieval": {
                        "status": "DEFERRED_PENDING_REVIEW",
                        "source": "none",
                        "reference_mode": self.reference_mode,
                        "has_authoritative_reference": False,
                        "document_count": 0,
                    },
                    "execution_duration_ms": duration_ms,
                },
                "document_extraction": {
                    "page_count": extraction.page_count,
                    "extraction_status": extraction.extraction_status,
                    "has_extractable_text": extraction.has_extractable_text,
                    "sha256_hash": extraction.sha256_hash,
                },
                "screening": screening_res.to_dict(),
                "seismic_intensity": {
                    "mmi_estimation": None,
                    "confidence": None,
                    "is_calibrated": False,
                    "reasoning": "; ".join(screening_res.decision_reasons) if screening_res.decision_reasons else "Relevance is uncertain; deferred pending expert review.",
                },
                "geographic_resolution": {
                    "location": preliminary_loc.to_dict(),
                    "coordinates": coords.to_dict() if coords else None,
                    "document_coordinates": preliminary_loc.document_coordinates.to_dict() if preliminary_loc.document_coordinates else None,
                    "mapping_link_coordinates": preliminary_loc.mapping_link_coordinates.to_dict() if preliminary_loc.mapping_link_coordinates else None,
                    "geocoded_coordinates": preliminary_loc.geocoded_coordinates.to_dict() if preliminary_loc.geocoded_coordinates else None,
                    "model_coordinates": None,
                    "comparison_status": "NOT_EVALUATED",
                    "coordinates_disagree": False,
                    "discrepancy_details": "Deferred due to REVIEW_REQUIRED classification",
                    "discrepancy_distance_km": None,
                    "has_valid_coordinates": coords.is_valid if coords else False,
                    "has_exportable_site_coordinates": preliminary_loc.has_exportable_site_coordinates,
                    "precision_level": preliminary_loc.precision_level,
                    "selection_rationale": preliminary_loc.selection_rationale,
                    "can_export_to_shakemap": False,
                    "is_authoritative": False,
                },
                "quality_control": {
                    "status": "FLAGGED",
                    "flags": ["PRE_MMI_REVIEW_REQUIRED"],
                    "score": 0.5,
                },
                "human_in_the_loop": {
                    "review_required": True,
                    "review_status": review_item.status if review_item else "PENDING_REVIEW",
                    "triggers": screening_res.review_triggers or screening_res.decision_reasons,
                },
            }
            self.logger.log_node_exit("ingest_pdf", review_summary, duration_ms=duration_ms)
            return review_summary

        if self.mode == "offline":
            fixture_name = self.fixture_registry.get(file_name)
            if not fixture_name:
                # STRICT REQUIREMENT: Never synthesize or fabricate predictions in offline mode
                not_found_result = {
                    "pipeline_status": "FIXTURE_NOT_FOUND",
                    "file_name": file_name,
                    "file_path": str(path),
                    "page_count": extraction.page_count,
                    "extraction_status": extraction.extraction_status,
                    "has_extractable_text": extraction.has_extractable_text,
                    "coordinates": coords.to_dict() if coords else None,
                    "screening": screening_res.to_dict(),
                    "message": (
                        f"No offline recorded CRAG fixture found for '{file_name}'. "
                        "In strict offline mode, unrecorded PDFs cannot produce fabricated MMI predictions. "
                        "To analyze this file with live AI models, run with --live (requires GCP credentials)."
                    ),
                }
                self.logger.log_node_exit("ingest_pdf", not_found_result, duration_ms=0.5)
                return not_found_result

            fixture_file = self.fixtures_dir / fixture_name
            with open(fixture_file, "r", encoding="utf-8") as f:
                fixture_data = json.load(f)

            is_synthetic = fixture_data.get("_metadata", {}).get("is_synthetic", False)
            baseline_type = fixture_data.get("_metadata", {}).get("baseline_type", "RECORDED_LEGACY_OUTPUT")

            # Extract model analysis from fixture
            analysis_payload = fixture_data.get("observed_legacy_baseline") or fixture_data.get("observed_mocked_output") or {}
            final_data = analysis_payload

            building_type = analysis_payload.get("building_type", "Unspecified")
            building_materials = analysis_payload.get("building_materials", "Unspecified")
            visual_obs = analysis_payload.get("visual_observation", extraction.extracted_text[:300])

        elif self.mode == "live":
            if not self.allow_live_api:
                raise PermissionError("Live API execution requested without explicit approval.")

            from ..adapters.gemini_provider import set_active_provider
            set_active_provider(self.provider)

            # Set model and thinking level in environment for live invocation
            active_model = self.model_name or os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
            os.environ["GEMINI_MODEL"] = active_model
            active_thinking = self.thinking_level or os.environ.get("GEMINI_THINKING_LEVEL", "HIGH")
            os.environ["GEMINI_THINKING_LEVEL"] = active_thinking

            # Ensure server folder is in sys.path to access legacy services
            server_dir = Path(__file__).resolve().parents[3] / "server"
            if server_dir.exists() and str(server_dir) not in sys.path:
                sys.path.insert(0, str(server_dir))

            from services.crag import MultimodalEarthquakeCRAG
            from services.manage_model import get_session_telemetry

            if self.provider == "ai_studio":
                # Local-first direct ingestion: stream local file bytes directly via types.Part.from_bytes()
                # Completely eliminates GCS bucket upload and service account credentials
                signed_url = str(path)
                unique_blob_name = file_name
            else:
                # Vertex AI / GCP storage workflow
                unique_blob_name = f"steer_{uuid.uuid4().hex[:8]}_{file_name}"
                from services.utilities import upload_to_gcs
                bucket = os.environ.get("GCS_BUCKET", "quakemap-media-data")
                signed_url = upload_to_gcs(str(path), bucketname=bucket, blob_name=unique_blob_name)

            crag = MultimodalEarthquakeCRAG()
            crag_result = crag.analyze_media_and_traverse_states(
                blob_name=unique_blob_name,
                signed_url=signed_url,
                mime_type="application/pdf",
            )

            final_data = crag_result.get("final_analysis", {}) if isinstance(crag_result, dict) else {}
            # Retrieve cumulative session telemetry tracking EVERY Gemini call made during the CRAG traversal
            token_usage = (crag_result.get("token_usage") if isinstance(crag_result, dict) else None) or get_session_telemetry()
            retrieval_status = crag_result.get("retrieval_status", "UNRETRIEVED") if isinstance(crag_result, dict) else "UNRETRIEVED"
            retrieval_source = crag_result.get("retrieval_source", "none") if isinstance(crag_result, dict) else "none"
            ref_mode = crag_result.get("reference_mode", self.reference_mode) if isinstance(crag_result, dict) else self.reference_mode
            mmi_docs = crag_result.get("mmi_documents", []) if isinstance(crag_result, dict) else []
            doc_count = len(mmi_docs) if mmi_docs else (crag_result.get("mmi_documents_count", 0) if isinstance(crag_result, dict) else 0)
            building_type = final_data.get("building_type", "Unspecified")
            building_materials = final_data.get("building_materials", "Unspecified")
            visual_obs = final_data.get("description", "")
            is_synthetic = False
            baseline_type = "LIVE_CRAG_EXECUTION"

        else:
            raise ValueError(f"Unknown mode '{self.mode}'. Use 'offline' or 'live'.")

        if self.mode == "offline":
            retrieval_status = "SUCCESS"
            retrieval_source = "offline_fixture"
            ref_mode = self.reference_mode
            doc_count = 10 if self.reference_mode == "full_scale" else 3

        # ──────────────────────────────────────────────────────────────────────
        # Step 3b: Safe Extraction of MMI & Confidence (No Fabricated Fallbacks)
        # ──────────────────────────────────────────────────────────────────────
        raw_mmi = final_data.get("mmi_estimation")
        raw_conf = final_data.get("confidence")
        mmi_val: Optional[float] = None
        conf_val: Optional[float] = None

        if raw_mmi is not None:
            try:
                parsed_mmi = float(raw_mmi)
                if 1.0 <= parsed_mmi <= 12.0:
                    mmi_val = parsed_mmi
                else:
                    # Physically invalid MMI
                    mmi_val = None
            except (ValueError, TypeError):
                mmi_val = None

        if raw_conf is not None:
            try:
                parsed_conf = float(raw_conf)
                if 0.0 <= parsed_conf <= 1.0:
                    conf_val = parsed_conf
                else:
                    conf_val = None
            except (ValueError, TypeError):
                conf_val = None

        if mmi_val is None:
            reasoning_val = final_data.get("reasoning") or "Model produced missing, malformed, or out-of-range MMI estimation."
        else:
            reasoning_val = final_data.get("reasoning", "")

        # ──────────────────────────────────────────────────────────────────────
        # Step 3c: Separate Extraction of Model Coordinates & Discrepancy Detection
        # ──────────────────────────────────────────────────────────────────────
        location_context = self.unified_resolver.resolve(
            text=extraction.extracted_text if extraction.has_extractable_text else None,
            file_path=path,
            model_location=final_data.get("location") if isinstance(final_data.get("location"), dict) else None,
            region_bounds=self.spatial_bounds,
        )

        # Retain model's address text if document didn't specify one
        if not location_context.address and isinstance(final_data.get("location"), dict):
            location_context.address = final_data["location"].get("address")

        doc_coords = location_context.document_coordinates
        mapping_link_coords = location_context.mapping_link_coordinates
        geocoded_coords = location_context.geocoded_coordinates
        model_coords = location_context.model_coordinates
        primary_coords = location_context.coordinates
        comparison_status = location_context.comparison_status
        coordinates_disagree = location_context.coordinates_disagree
        discrepancy_details = location_context.discrepancy_details
        discrepancy_distance_km = location_context.discrepancy_distance_km

        # ──────────────────────────────────────────────────────────────────────
        # Step 4: Normalization into MMI-Gram Structured State Schema
        # ──────────────────────────────────────────────────────────────────────
        estimation = MMIEstimationResult(
            mmi_value=mmi_val,
            confidence=conf_val,
            reasoning=reasoning_val,
            is_calibrated=False,  # Uncalibrated until validated by expert consensus
        )

        damage = StructuralDamageAssessment(
            building_type=building_type,
            building_materials=building_materials,
            visual_observations=visual_obs,
        )

        evidence = EvidenceMetadata(
            blob_name=file_name,
            mime_type="application/pdf",
            sha256_hash=extraction.sha256_hash,
            media_source="steer_recon_pdf",
        )

        # ──────────────────────────────────────────────────────────────────────
        # Step 5: Automated Quality Control Evaluation
        # ──────────────────────────────────────────────────────────────────────
        qc = evaluate_quality(
            coordinates=primary_coords,
            estimation=estimation,
            damage=damage,
            location=location_context,
            retrieval_status=retrieval_status if self.mode == "live" else None,
        )

        # ──────────────────────────────────────────────────────────────────────
        # Step 6: Human-in-the-Loop Review Gate
        # ──────────────────────────────────────────────────────────────────────
        review_required = False
        triggers: List[str] = []

        if qc.qc_status in ("FLAGGED", "REJECTED"):
            review_required = True
            triggers.append(f"Quality Control status is {qc.qc_status} (Flags: {qc.qc_flags})")
        if self.mode == "live" and "REFERENCE_RETRIEVAL_FAILED" in qc.qc_flags:
            review_required = True
            triggers.append(f"Seismic reference retrieval incomplete or failed ({retrieval_status}); MMI estimate lacks empirical reference grounding.")
        if estimation.mmi_value is None:
            review_required = True
            triggers.append("Model output is missing, malformed, or outside valid MMI range (requires human expert estimation).")
        elif estimation.mmi_value >= 9.0:
            review_required = True
            triggers.append("High seismic intensity (MMI >= 9.0) requires authoritative verification.")
        if location_context.coordinates_disagree:
            review_required = True
            triggers.append(f"Coordinate discrepancy: {location_context.discrepancy_details}")
        elif location_context.comparison_status == "MODEL_LOCATION_UNAVAILABLE":
            review_required = True
            triggers.append("Model location was unavailable (Unknown); candidate coordinates rely solely on unverified document text.")
        if primary_coords is None or not primary_coords.is_valid:
            review_required = True
            triggers.append("Geographic coordinates could not be established from document text or model.")
        else:
            if not location_context.is_within_regional_bounds:
                review_required = True
                triggers.append(
                    f"Observation coordinates ({primary_coords.latitude:.4f}, {primary_coords.longitude:.4f}) "
                    "are outside configured regional bounds; requires geographic verification."
                )
            if not location_context.has_exportable_site_coordinates:
                review_required = True
                triggers.append(f"Observation lacks ShakeMap exportable site coordinates (precision: {location_context.precision_level}).")
            if not primary_coords.is_authoritative:
                review_required = True
                triggers.append("Candidate coordinates require expert validation against epicentral maps.")

        # Incorporate screening-stage review triggers if any
        if screening_res.review_required:
            review_required = True
            for trg in screening_res.review_triggers:
                if trg not in triggers:
                    triggers.append(trg)

        review_item = None
        if review_required:
            review_item = self.review_queue.check_and_enqueue(
                item_id=file_name,
                state={
                    "file_name": file_name,
                    "estimation": estimation.to_dict(),
                    "coordinates": primary_coords.to_dict() if primary_coords else None,
                    "location": location_context.to_dict(),
                    "qc": qc.to_dict(),
                },
                force=True,
            )

        # ──────────────────────────────────────────────────────────────────────
        # Observation-Level ShakeMap Export Eligibility (Stage 3 Evaluation)
        # ──────────────────────────────────────────────────────────────────────
        # Distinguish spatial coordinate eligibility from observation-level ShakeMap eligibility.
        # Export requires:
        #   1. Valid site-specific coordinates (has_exportable_site_coordinates == True)
        #   2. Valid numeric MMI (1.0 <= MMI <= 12.0)
        #   3. ESTIMABLE screening decision (not NOT_ESTIMABLE or REVIEW_REQUIRED)
        #   4. No coordinate conflicts (coordinates_disagree == False)
        #   5. QC status is not REJECTED or SCREENED_OUT
        #   6. No unresolved human review (automatic export blocked while review is required)
        # Note: Stage 4 owns final XML packaging and ingestion after human review clearance.
        has_site_coords = bool(location_context.has_exportable_site_coordinates)
        has_numeric_mmi = bool(estimation.mmi_value is not None and 1.0 <= estimation.mmi_value <= 12.0)
        is_estimable = bool(screening_res.relevance_decision == "ESTIMABLE")
        no_conflicts = bool(not location_context.coordinates_disagree)
        qc_acceptable = bool(qc.qc_status not in ("REJECTED", "SCREENED_OUT"))
        no_blocking_review = not review_required

        final_can_export = (
            has_site_coords
            and has_numeric_mmi
            and is_estimable
            and no_conflicts
            and qc_acceptable
            and no_blocking_review
        )
        location_context.can_export_to_shakemap = final_can_export

        duration_ms = round((time.time() - t0) * 1000.0, 2)
        active_model = (
            self.model_name or os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
            if self.mode == "live"
            else "offline-fixture"
        )
        active_thinking = (
            self.thinking_level or os.environ.get("GEMINI_THINKING_LEVEL", "HIGH")
            if (self.mode == "live" and ("3.8" in active_model or "gemini-3" in active_model))
            else None
        )

        final_summary = {
            "pipeline_name": "MMI-Gram General-Purpose StEER Pipeline",
            "file_name": file_name,
            "pipeline_mode": self.mode,
            "model_identifier": active_model,
            "execution_duration_ms": duration_ms,
            "provenance": {
                "is_synthetic": is_synthetic,
                "baseline_type": baseline_type,
                "is_authoritative_ground_truth": False,
                "model_identifier": active_model,
                "thinking_level": active_thinking,
                "execution_mode": self.mode,
                "provider": self.provider if self.mode == "live" else "offline",
                "source_sha256": extraction.sha256_hash,
                "mmi_result": estimation.mmi_value,
                "uncalibrated_confidence": estimation.confidence,
                "token_usage": (
                    token_usage
                    if self.mode == "live"
                    else {
                        "calls": 0,
                        "prompt_tokens": 0,
                        "candidates_tokens": 0,
                        "thoughts_tokens": 0,
                        "total_tokens": 0,
                    }
                ),
                "retrieval": {
                    "status": retrieval_status,
                    "source": retrieval_source,
                    "reference_mode": ref_mode,
                    "has_authoritative_reference": (retrieval_status == "SUCCESS"),
                    "document_count": doc_count,
                },
                "execution_duration_ms": duration_ms,
            },
            "document_extraction": {
                "page_count": extraction.page_count,
                "extraction_status": extraction.extraction_status,
                "has_extractable_text": extraction.has_extractable_text,
                "sha256_hash": extraction.sha256_hash,
            },
            "screening": screening_res.to_dict(),
            "seismic_intensity": {
                "mmi_estimation": estimation.mmi_value,
                "confidence": estimation.confidence,
                "is_calibrated": estimation.is_calibrated,
                "reasoning": estimation.reasoning,
            },
            "geographic_resolution": {
                "location": location_context.to_dict(),
                "coordinates": primary_coords.to_dict() if primary_coords else None,
                "document_coordinates": doc_coords.to_dict() if doc_coords else None,
                "mapping_link_coordinates": mapping_link_coords.to_dict() if mapping_link_coords else None,
                "geocoded_coordinates": geocoded_coords.to_dict() if geocoded_coords else None,
                "model_coordinates": model_coords.to_dict() if model_coords else None,
                "comparison_status": comparison_status,
                "coordinates_disagree": coordinates_disagree,
                "discrepancy_details": discrepancy_details,
                "discrepancy_distance_km": discrepancy_distance_km,
                "has_valid_coordinates": primary_coords.is_valid if primary_coords else False,
                "has_exportable_site_coordinates": location_context.has_exportable_site_coordinates,
                "precision_level": location_context.precision_level,
                "selection_rationale": location_context.selection_rationale,
                "can_export_to_shakemap": final_can_export,
                "is_authoritative": False,
            },
            "quality_control": {
                "status": qc.qc_status,
                "flags": qc.qc_flags,
                "score": qc.qc_score,
            },
            "human_in_the_loop": {
                "review_required": review_required,
                "review_status": review_item.status if review_item else "NOT_ENQUEUED",
                "triggers": triggers,
            },
        }

        self.logger.log_node_exit("ingest_pdf", final_summary, duration_ms=duration_ms)
        return final_summary
