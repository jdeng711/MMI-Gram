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
from ..geolocation.validator import validate_coordinates, haversine_distance_km, MYANMAR_BOUNDS
from ..qc.checker import evaluate_quality
from ..review.queue import HumanReviewQueue
from ..telemetry.tracer import StructuredAgentLogger


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
    ):
        self.mode = mode.lower()
        self.fixtures_dir = fixtures_dir or DEFAULT_FIXTURES_DIR
        self.logger = logger or StructuredAgentLogger(name="mmigram.general_steer", console_output=True)
        self.review_queue = review_queue or HumanReviewQueue()
        self.allow_live_api = allow_live_api
        self.pdf_extractor = PDFExtractor(min_text_threshold=min_text_threshold)

        # Mapping of known filenames to their offline recorded fixture JSON
        self.fixture_registry: Dict[str, str] = {
            "test_page1.pdf": "steer_page1_baseline.json",
            "synthetic_steer_page2_mandalay.pdf": "synthetic_steer_page2_mandalay.json",
            "synthetic_steer_page3_no_coords.pdf": "synthetic_steer_page3_no_coords.json",
        }

    def process_pdf(self, file_path: Union[str, Path]) -> Dict[str, Any]:
        """
        Execute the general-purpose StEER ingestion and analysis workflow on a target PDF.
        """
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
        # Step 2: Dynamic Geolocation Parsing (from PDF text)
        # ──────────────────────────────────────────────────────────────────────
        coords = None
        if extraction.has_extractable_text:
            parsed = extract_coordinates_from_text(extraction.extracted_text)
            if parsed.is_valid:
                coords = validate_coordinates(parsed, region_bounds=MYANMAR_BOUNDS)
                coords.is_authoritative = False  # Text-extracted candidate, not verified ground truth
            else:
                coords = Coordinates(
                    latitude=None,
                    longitude=None,
                    source="not_found_in_text",
                    is_valid=False,
                    validation_error="No geographic coordinates detected in document text",
                    is_authoritative=False,
                )
        else:
            coords = Coordinates(
                latitude=None,
                longitude=None,
                source="image_based_pdf",
                is_valid=False,
                validation_error="Document is image-based without an embedded text layer",
                is_authoritative=False,
            )

        # ──────────────────────────────────────────────────────────────────────
        # Step 3: Analysis Execution (Strict Offline vs. Live CRAG)
        # ──────────────────────────────────────────────────────────────────────
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

            # Unique cloud object name to prevent collisions
            unique_blob_name = f"steer_{uuid.uuid4().hex[:8]}_{file_name}"

            # Ensure server folder is in sys.path to access Clara's legacy services
            server_dir = Path(__file__).resolve().parents[3] / "server"
            if server_dir.exists() and str(server_dir) not in sys.path:
                sys.path.insert(0, str(server_dir))

            # Import Clara's legacy utilities without modification
            from services.utilities import upload_to_gcs
            from services.crag import MultimodalEarthquakeCRAG

            bucket = os.environ.get("GCS_BUCKET", "quakemap-media-data")
            signed_url = upload_to_gcs(str(path), bucketname=bucket, blob_name=unique_blob_name)

            crag = MultimodalEarthquakeCRAG()
            crag_result = crag.analyze_media_and_traverse_states(
                blob_name=unique_blob_name,
                signed_url=signed_url,
                mime_type="application/pdf",
            )

            final_data = crag_result.get("final_analysis", {}) if isinstance(crag_result, dict) else {}
            building_type = final_data.get("building_type", "Unspecified")
            building_materials = final_data.get("building_materials", "Unspecified")
            visual_obs = final_data.get("description", "")
            is_synthetic = False
            baseline_type = "LIVE_CRAG_EXECUTION"

        else:
            raise ValueError(f"Unknown mode '{self.mode}'. Use 'offline' or 'live'.")

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
        doc_coords = coords  # Coordinates extracted from document text in Step 2

        model_coords_raw = None
        if isinstance(final_data.get("location"), dict):
            model_coords_raw = final_data["location"].get("coordinates")

        model_coords: Optional[Coordinates] = None
        if isinstance(model_coords_raw, (list, tuple)) and len(model_coords_raw) == 2:
            try:
                m_lat = float(model_coords_raw[0])
                m_lon = float(model_coords_raw[1])
                model_coords = Coordinates(
                    latitude=m_lat,
                    longitude=m_lon,
                    source="model_predicted",
                    is_authoritative=False,
                )
                model_coords = validate_coordinates(model_coords)
            except (ValueError, TypeError):
                model_coords = None

        # Discrepancy analysis
        coordinates_disagree = False
        discrepancy_details: Optional[str] = None
        discrepancy_distance_km: Optional[float] = None

        if doc_coords and doc_coords.is_valid and model_coords and model_coords.is_valid:
            dist = haversine_distance_km(doc_coords.latitude, doc_coords.longitude, model_coords.latitude, model_coords.longitude)
            discrepancy_distance_km = round(dist, 2)
            if dist > 10.0:  # Threshold > 10 km
                coordinates_disagree = True
                discrepancy_details = (
                    f"Document coordinates ({doc_coords.latitude:.4f}, {doc_coords.longitude:.4f}) and "
                    f"model coordinates ({model_coords.latitude:.4f}, {model_coords.longitude:.4f}) "
                    f"disagree by {dist:.1f} km (threshold: 10.0 km)."
                )
        elif doc_coords and doc_coords.is_valid and model_coords and not model_coords.is_valid:
            coordinates_disagree = True
            discrepancy_details = (
                f"Document text contains valid coordinates ({doc_coords.latitude:.4f}, {doc_coords.longitude:.4f}), "
                f"but model returned invalid coordinates ({model_coords.validation_error or 'invalid'})."
            )
        elif model_coords and model_coords.is_valid and (not doc_coords or not doc_coords.is_valid):
            coordinates_disagree = True
            discrepancy_details = "Model predicted coordinates but no coordinates were detected in document text."

        # Candidate coordinate resolution: keep unknown as null, never invent!
        primary_coords: Optional[Coordinates] = None
        if doc_coords and doc_coords.is_valid:
            primary_coords = doc_coords
        elif model_coords and model_coords.is_valid:
            primary_coords = model_coords
        else:
            primary_coords = None

        location_context = LocationContext(
            address=final_data.get("location", {}).get("address") if isinstance(final_data.get("location"), dict) else None,
            coordinates=primary_coords,
            document_coordinates=doc_coords,
            model_coordinates=model_coords,
            coordinates_disagree=coordinates_disagree,
            discrepancy_details=discrepancy_details,
            discrepancy_distance_km=discrepancy_distance_km,
        )

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
        )

        # ──────────────────────────────────────────────────────────────────────
        # Step 6: Human-in-the-Loop Review Gate
        # ──────────────────────────────────────────────────────────────────────
        review_required = False
        triggers: List[str] = []

        if qc.qc_status in ("FLAGGED", "REJECTED"):
            review_required = True
            triggers.append(f"Quality Control status is {qc.qc_status} (Flags: {qc.qc_flags})")
        if estimation.mmi_value is None:
            review_required = True
            triggers.append("Model output is missing, malformed, or outside valid MMI range (requires human expert estimation).")
        elif estimation.mmi_value >= 9.0:
            review_required = True
            triggers.append("High seismic intensity (MMI >= 9.0) requires authoritative verification.")
        if location_context.coordinates_disagree:
            review_required = True
            triggers.append(f"Coordinate discrepancy: {location_context.discrepancy_details}")
        if primary_coords is None or not primary_coords.is_valid:
            review_required = True
            triggers.append("Geographic coordinates could not be established from document text or model.")
        elif not primary_coords.is_authoritative:
            review_required = True
            triggers.append("Candidate coordinates require expert validation against epicentral maps.")

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

        final_summary = {
            "pipeline_name": "MMI-Gram General-Purpose StEER Pipeline",
            "file_name": file_name,
            "pipeline_mode": self.mode,
            "provenance": {
                "is_synthetic": is_synthetic,
                "baseline_type": baseline_type,
                "is_authoritative_ground_truth": False,
            },
            "document_extraction": {
                "page_count": extraction.page_count,
                "extraction_status": extraction.extraction_status,
                "has_extractable_text": extraction.has_extractable_text,
                "sha256_hash": extraction.sha256_hash,
            },
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
                "model_coordinates": model_coords.to_dict() if model_coords else None,
                "coordinates_disagree": coordinates_disagree,
                "discrepancy_details": discrepancy_details,
                "discrepancy_distance_km": discrepancy_distance_km,
                "has_valid_coordinates": primary_coords.is_valid if primary_coords else False,
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

        self.logger.log_node_exit("ingest_pdf", final_summary, duration_ms=1.2)
        return final_summary
