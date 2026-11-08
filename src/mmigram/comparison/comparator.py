"""
Standardized Benchmark & Comparison Framework for Earthquake Observations.
Enables side-by-side comparison between MMI-Gram and Clara's quake_agent workflow.
"""

from __future__ import annotations
import csv
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Any, List, Optional


@dataclass
class StandardObservationRecord:
    """
    Standardized observation record for cross-pipeline benchmarking.
    """
    source_filename: str
    document_sha256: str
    event_id: str
    workflow_system: str           # "MMI-Gram" or "quake_agent"
    workflow_version: str          # e.g. "0.2.0"
    model_identifier: str          # e.g. "gemini-2.5-flash", "gemini-3.8-flash"
    execution_mode: str            # "offline" or "live"
    predicted_mmi: Optional[float]
    model_confidence: Optional[float]
    document_coordinates: Optional[Dict[str, Any]]
    model_coordinates: Optional[Dict[str, Any]]
    coordinates_disagree: bool
    qc_status: str                 # "PASSED", "FLAGGED", "REJECTED"
    qc_flags: List[str]
    human_review_required: bool
    human_review_status: str       # "UNREVIEWED", "APPROVED", "OVERRIDDEN", "REJECTED"
    execution_duration_ms: float
    error_message: Optional[str] = None
    provenance_notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BenchmarkComparator:
    """
    Manages collection and export of benchmark observation records.
    """

    def __init__(self, event_id: str = "us7000pn9s"):
        self.event_id = event_id
        self.records: List[StandardObservationRecord] = []

    def add_mmigram_result(
        self,
        result: Dict[str, Any],
        duration_ms: float = 0.0,
        model_name: str = "offline-replay",
    ) -> StandardObservationRecord:
        """
        Normalize an MMI-Gram pipeline execution result into a StandardObservationRecord.
        """
        doc_ext = result.get("document_extraction", {})
        seis = result.get("seismic_intensity", {})
        geo = result.get("geographic_resolution", {})
        qc = result.get("quality_control", {})
        hitl = result.get("human_in_the_loop", {})
        prov = result.get("provenance", {})

        record = StandardObservationRecord(
            source_filename=result.get("file_name", "unknown"),
            document_sha256=doc_ext.get("sha256_hash", "unknown"),
            event_id=self.event_id,
            workflow_system="MMI-Gram",
            workflow_version="0.2.0",
            model_identifier=model_name,
            execution_mode=result.get("pipeline_mode", "offline"),
            predicted_mmi=seis.get("mmi_estimation"),
            model_confidence=seis.get("confidence"),
            document_coordinates=geo.get("document_coordinates"),
            model_coordinates=geo.get("model_coordinates"),
            coordinates_disagree=geo.get("coordinates_disagree", False),
            qc_status=qc.get("status", "UNKNOWN"),
            qc_flags=qc.get("flags", []),
            human_review_required=hitl.get("review_required", False),
            human_review_status=hitl.get("review_status", "NOT_ENQUEUED"),
            execution_duration_ms=round(duration_ms, 2),
            error_message=result.get("error_message") or result.get("message"),
            provenance_notes=f"Synthetic: {prov.get('is_synthetic', False)}, Baseline: {prov.get('baseline_type')}",
        )
        self.records.append(record)
        return record

    def export_json(self, output_path: Path | str) -> None:
        """Export all benchmark records to JSON."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump([r.to_dict() for r in self.records], f, indent=2)

    def export_csv(self, output_path: Path | str) -> None:
        """Export all benchmark records to tabular CSV for comparative analysis."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not self.records:
            return

        fieldnames = [
            "source_filename",
            "event_id",
            "workflow_system",
            "model_identifier",
            "execution_mode",
            "predicted_mmi",
            "model_confidence",
            "doc_lat",
            "doc_lon",
            "model_lat",
            "model_lon",
            "coordinates_disagree",
            "qc_status",
            "qc_flags",
            "human_review_status",
            "execution_duration_ms",
            "error_message",
        ]

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in self.records:
                doc_c = r.document_coordinates or {}
                model_c = r.model_coordinates or {}
                row = {
                    "source_filename": r.source_filename,
                    "event_id": r.event_id,
                    "workflow_system": r.workflow_system,
                    "model_identifier": r.model_identifier,
                    "execution_mode": r.execution_mode,
                    "predicted_mmi": r.predicted_mmi if r.predicted_mmi is not None else "",
                    "model_confidence": r.model_confidence if r.model_confidence is not None else "",
                    "doc_lat": doc_c.get("latitude", ""),
                    "doc_lon": doc_c.get("longitude", ""),
                    "model_lat": model_c.get("latitude", ""),
                    "model_lon": model_c.get("longitude", ""),
                    "coordinates_disagree": r.coordinates_disagree,
                    "qc_status": r.qc_status,
                    "qc_flags": ";".join(r.qc_flags),
                    "human_review_status": r.human_review_status,
                    "execution_duration_ms": r.execution_duration_ms,
                    "error_message": r.error_message or "",
                }
                writer.writerow(row)
