"""
Minimal Offline LangGraph Pipeline for StEER Page 1 Reconnaissance Observation.

Demonstrates end-to-end agent orchestration, quality control, geolocation resolution,
and human-in-the-loop review routing using Phase 2 components.
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Any, Optional, List

from ..core.state import (
    Coordinates,
    MMIEstimationResult,
    StructuralDamageAssessment,
    LocationContext,
    QualityControlRecord,
    HumanReviewRecord,
)
from ..geolocation.parser import extract_coordinates_from_text
from ..geolocation.validator import validate_coordinates, MYANMAR_BOUNDS
from ..qc.checker import evaluate_quality
from ..qc.rules import (
    FLAG_NULL_ISLAND,
    FLAG_INVALID_COORDINATES,
    FLAG_HIGH_INTENSITY_ANOMALY,
    FLAG_UNVERIFIED_ESTIMATE,
)
from ..review.queue import HumanReviewQueue, ReviewItem
from ..telemetry.tracer import StructuredAgentLogger
from .graph import LightweightWorkflowGraph


DEFAULT_FIXTURE_PATH = (
    Path(__file__).parents[1] / "tests" / "fixtures" / "steer_page1_baseline.json"
)


def get_steer_pipeline_mermaid() -> str:
    """
    Returns a Mermaid diagram representation of the actual implemented pipeline,
    clearly distinguishing implemented nodes from planned extensions.
    """
    return """
flowchart TD
    %% Styling Classes
    classDef implemented fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#ecfdf5;
    classDef router fill:#312e81,stroke:#6366f1,stroke-width:2px,color:#e0e7ff;
    classDef storage fill:#14532d,stroke:#22c55e,stroke-width:2px,color:#f0fdf4;
    classDef planned fill:#451a03,stroke:#f59e0b,stroke-width:2px,stroke-dasharray: 5 5,color:#fffbeb;

    subgraph Legend ["Component Status Legend"]
        Leg1["Implemented Offline Agent Node"]:::implemented
        Leg2{"Implemented Conditional Router"}:::router
        Leg3[("Implemented Storage / Queue")]:::storage
        Leg4["Planned Future Capability"]:::planned
    end

    subgraph OfflinePipeline ["MMI-Gram StEER Offline LangGraph Pipeline"]
        START((START))

        NodeLoad["Agent 1: load_observation_baseline\n(MMI 9.0, Conf 0.90, Coords 0,0)"]:::implemented
        NodeInitialQC["Agent 2: initial_qc_check\n(Detects Null Island 0,0 Error)"]:::implemented
        RouteCoord{"Router:\ncoords_invalid?"}:::router

        NodeGeoResolve["Agent 3: resolve_geolocation\n(Parses Sagaing DMS text -> Candidate Coords)"]:::implemented
        NodeSecondaryQC["Agent 4: secondary_qc_check\n(Evaluates MMI 9.0 & Candidate Coords)"]:::implemented
        RouteReview{"Router:\nrequires_review?"}:::router

        NodeQueue["Agent 5: route_to_human_review\n(Enqueues in HumanReviewQueue)"]:::implemented
        ReviewStore[("Human Review Queue\n(Holds MMI >= 9.0 for Expert Audit)")]:::storage

        NodeSummary["Agent 6: format_stage_summary\n(Produces Structured Stage Results)"]:::implemented
        ENDNode(((END)))

        START --> NodeLoad
        NodeLoad --> NodeInitialQC
        NodeInitialQC --> RouteCoord

        RouteCoord -- "Coords == (0,0) / Invalid" --> NodeGeoResolve
        RouteCoord -- "Coords Valid" --> NodeSecondaryQC

        NodeGeoResolve --> NodeSecondaryQC
        NodeSecondaryQC --> RouteReview

        RouteReview -- "MMI >= 9.0 or FLAGGED" --> NodeQueue
        RouteReview -- "Clean & Calibrated" --> NodeSummary

        NodeQueue --> ReviewStore
        ReviewStore --> NodeSummary
        NodeSummary --> ENDNode
    end

    subgraph PlannedExtensions ["Planned Future Capabilities (Phase 3+)"]
        PlannedHarvester["Planned: Social Media Harvester\n(Real-time X/Telegram Stream)"]:::planned
        PlannedDedupe["Planned: Perceptual Hash Dedupe\n(Clustering Viral Reposts)"]:::planned
        PlannedLandmark["Planned: Visual Landmark OCR\n(Banners/Signs/Gazetteer Lookup)"]:::planned
        PlannedGIS["Planned: Python-native GIS Cartography\n(GeoPandas & ShakeMap Generation)"]:::planned

        PlannedHarvester -.-> PlannedDedupe
        PlannedDedupe -.-> NodeLoad
        NodeGeoResolve -.-> PlannedLandmark
        NodeSummary -.-> PlannedGIS
    end
"""


class SteerOfflinePipeline:
    """
    Offline LangGraph pipeline execution engine for StEER report cards.
    Demonstrates Turn-by-Turn Agent Orchestration with Structured Logging.
    """

    def __init__(
        self,
        fixture_path: Optional[Path] = None,
        logger: Optional[StructuredAgentLogger] = None,
        review_queue: Optional[HumanReviewQueue] = None,
    ):
        self.fixture_path = fixture_path or DEFAULT_FIXTURE_PATH
        self.logger = logger or StructuredAgentLogger(name="mmigram.steer_pipeline", console_output=True)
        self.review_queue = review_queue or HumanReviewQueue()
        self.stage_history: List[Dict[str, Any]] = []

        with open(self.fixture_path, "r", encoding="utf-8") as f:
            self.fixture = json.load(f)

        self.graph = LightweightWorkflowGraph(logger=self.logger)
        self._build_pipeline_graph()

    def _build_pipeline_graph(self) -> None:
        """Assemble the 5 core offline workflow nodes and routing edges."""
        # 1. Add nodes
        self.graph.add_node("load_baseline", self.node_load_baseline)
        self.graph.add_node("initial_qc", self.node_initial_qc)
        self.graph.add_node("resolve_geolocation", self.node_resolve_geolocation)
        self.graph.add_node("secondary_qc", self.node_secondary_qc)
        self.graph.add_node("route_to_human_review", self.node_route_to_human_review)
        self.graph.add_node("format_stage_summary", self.node_format_stage_summary)

        # 2. Add edges & conditional routing
        self.graph.set_entry_point("load_baseline")
        self.graph.add_edge("load_baseline", "initial_qc")

        # Router 1: Coordinate validity check
        self.graph.add_conditional_edges(
            "initial_qc",
            self.router_check_coordinates,
            {
                "resolve_coordinates": "resolve_geolocation",
                "proceed_to_secondary_qc": "secondary_qc",
            },
        )

        self.graph.add_edge("resolve_geolocation", "secondary_qc")

        # Router 2: Review necessity check
        self.graph.add_conditional_edges(
            "secondary_qc",
            self.router_check_review_need,
            {
                "enqueue_review": "route_to_human_review",
                "skip_review": "format_stage_summary",
            },
        )

        self.graph.add_edge("route_to_human_review", "format_stage_summary")
        self.graph.add_edge("format_stage_summary", "END")

    # ──────────────────────────────────────────────────────────────────────────
    # Node Implementations
    # ──────────────────────────────────────────────────────────────────────────

    def node_load_baseline(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Stage 1: Load recorded StEER page 1 baseline.
        Specifically initializes coordinates to (0.0, 0.0) to simulate raw unparsed observation.
        """
        baseline = self.fixture["observed_legacy_baseline"]
        inp = self.fixture["input"]

        # Null Island (0, 0) simulates raw initial state prior to coordinate extraction
        initial_coords = Coordinates(
            latitude=0.0,
            longitude=0.0,
            source="uninitialized_raw_input",
            is_valid=False,
            confidence=0.0,
            is_authoritative=False,
        )

        estimation = MMIEstimationResult(
            mmi_value=float(baseline["mmi_estimation"]),
            confidence=float(baseline["confidence"]),
            reasoning=baseline["reasoning"],
            is_calibrated=False,
        )

        damage = StructuralDamageAssessment(
            building_type=baseline.get("building_type"),
            building_materials=baseline.get("building_materials"),
            visual_observations=baseline["visual_observation"],
        )

        stage_record = {
            "stage_number": 1,
            "stage_name": "load_baseline",
            "status": "LOADED",
            "mmi": estimation.mmi_value,
            "confidence": estimation.confidence,
            "initial_coordinates": [0.0, 0.0],
            "raw_location_string": inp["raw_location_string"],
            "notes": "Loaded baseline with uninitialized Null Island (0,0) coordinates.",
        }
        self.stage_history.append(stage_record)

        return {
            "blob_name": inp["file_name"],
            "mime_type": inp["mime_type"],
            "raw_location_string": inp["raw_location_string"],
            "estimation": estimation.to_dict(),
            "damage": damage.to_dict(),
            "location": {
                "address": baseline["location"]["address"],
                "coordinates": initial_coords.to_dict(),
            },
            "stage_records": list(self.stage_history),
        }

    def node_initial_qc(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Stage 2: Evaluate raw observation through Quality Control.
        Must identify (0.0, 0.0) coordinates as invalid Null Island error.
        """
        coords_dict = state["location"]["coordinates"]
        coords = Coordinates.from_dict(coords_dict)
        est = MMIEstimationResult.from_dict(state["estimation"])
        damage = StructuralDamageAssessment.from_dict(state["damage"])

        qc_record = evaluate_quality(coordinates=coords, estimation=est, damage=damage)

        stage_record = {
            "stage_number": 2,
            "stage_name": "initial_qc",
            "qc_status": qc_record.qc_status,
            "qc_flags": qc_record.qc_flags,
            "qc_score": qc_record.qc_score,
            "notes": "QC strictly flagged (0,0) as fatal Null Island coordinate error.",
        }
        self.stage_history.append(stage_record)

        return {
            "initial_qc": qc_record.to_dict(),
            "stage_records": list(self.stage_history),
        }

    def router_check_coordinates(self, state: Dict[str, Any]) -> str:
        """
        Router 1: If coordinates are invalid or Null Island, route to Geolocation Resolver.
        """
        coords = state.get("location", {}).get("coordinates", {})
        is_valid = coords.get("is_valid", False)
        lat = coords.get("latitude")
        lon = coords.get("longitude")

        is_null_island = lat is not None and lon is not None and abs(lat) < 1e-5 and abs(lon) < 1e-5

        if not is_valid or is_null_island or state.get("raw_location_string"):
            return "resolve_coordinates"
        return "proceed_to_secondary_qc"

    def node_resolve_geolocation(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Stage 3: Run geolocation parsing against StEER source text.
        Extracts candidate coordinates: Sagaing city (21.880353 N, 95.984881 E).
        CRITICAL: Coordinates are candidate extractions and NOT automatically approved ground truth.
        """
        raw_text = state.get("raw_location_string", "")
        coords = extract_coordinates_from_text(raw_text)

        # Validate against Myanmar regional bounds
        validated = validate_coordinates(coords, region_bounds=MYANMAR_BOUNDS)

        # Ensure marked as unverified candidate
        validated.is_authoritative = False

        stage_record = {
            "stage_number": 3,
            "stage_name": "resolve_geolocation",
            "status": "PARSED_CANDIDATE",
            "resolved_latitude": validated.latitude,
            "resolved_longitude": validated.longitude,
            "is_valid": validated.is_valid,
            "is_authoritative": validated.is_authoritative,
            "coordinate_source": validated.source,
            "notes": "Recovered candidate Sagaing coordinates from DMS text; left unverified per protocol.",
        }
        self.stage_history.append(stage_record)

        return {
            "location": {
                "address": "Sagaing city, Myanmar",
                "coordinates": validated.to_dict(),
            },
            "stage_records": list(self.stage_history),
        }

    def node_secondary_qc(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Stage 4: Re-evaluate Quality Control with resolved candidate coordinates.
        Coordinate error is resolved, but MMI 9.0 triggers HIGH_INTENSITY_ANOMALY.
        Status: FLAGGED (treated as requiring review, NOT automatically incorrect).
        """
        coords = Coordinates.from_dict(state["location"]["coordinates"])
        est = MMIEstimationResult.from_dict(state["estimation"])
        damage = StructuralDamageAssessment.from_dict(state["damage"])

        qc_record = evaluate_quality(coordinates=coords, estimation=est, damage=damage)

        stage_record = {
            "stage_number": 4,
            "stage_name": "secondary_qc",
            "qc_status": qc_record.qc_status,
            "qc_flags": qc_record.qc_flags,
            "qc_score": qc_record.qc_score,
            "notes": "Coordinates valid candidate. MMI 9.0 flagged for expert review (not rejected).",
        }
        self.stage_history.append(stage_record)

        return {
            "qc": qc_record.to_dict(),
            "stage_records": list(self.stage_history),
        }

    def router_check_review_need(self, state: Dict[str, Any]) -> str:
        """
        Router 2: Route high intensity (MMI >= 9.0) or FLAGGED observations to Human Review.
        """
        qc = state.get("qc", {})
        est = state.get("estimation", {})
        mmi = est.get("mmi_value", 0.0)

        if qc.get("qc_status") in ("FLAGGED", "REJECTED") or mmi >= 9.0:
            return "enqueue_review"
        return "skip_review"

    def node_route_to_human_review(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Stage 5: Intercept observation into HumanReviewQueue.
        Preserves human oversight: prevents automatic approval.
        """
        blob_name = state.get("blob_name", "test_page1.pdf")
        review_item = self.review_queue.check_and_enqueue(
            item_id=blob_name,
            state=state,
            force=True,
        )

        stage_record = {
            "stage_number": 5,
            "stage_name": "route_to_human_review",
            "status": "QUEUED_FOR_EXPERT_REVIEW",
            "triggers": review_item.triggers if review_item else [],
            "queue_pending_count": len(self.review_queue.get_pending()),
            "notes": "Observation placed in review queue; awaiting structural seismologist audit.",
        }
        self.stage_history.append(stage_record)

        review_info = {
            "review_required": True,
            "review_status": "UNREVIEWED",
            "triggers": review_item.triggers if review_item else [],
            "enqueued_item_id": blob_name,
        }

        return {
            "review": review_info,
            "stage_records": list(self.stage_history),
        }

    def node_format_stage_summary(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Stage 6: Assemble final structured report showing stage-by-stage outputs.
        """
        coords = state.get("location", {}).get("coordinates", {})
        est = state.get("estimation", {})
        qc = state.get("qc", {})
        rev = state.get("review", {})

        summary = {
            "pipeline_name": "MMI-Gram StEER Offline LangGraph Pipeline",
            "observation_id": state.get("blob_name", "test_page1.pdf"),
            "final_pipeline_decision": "HELD_IN_HUMAN_REVIEW_QUEUE",
            "seismic_intensity": {
                "mmi_estimation": est.get("mmi_value"),
                "confidence": est.get("confidence"),
                "is_calibrated": est.get("is_calibrated", False),
                "seismological_notes": est.get("reasoning"),
            },
            "geographic_resolution": {
                "latitude": coords.get("latitude"),
                "longitude": coords.get("longitude"),
                "is_valid": coords.get("is_valid"),
                "is_authoritative": coords.get("is_authoritative", False),
                "coordinate_source": coords.get("source"),
                "regional_envelope": "Myanmar (9.0-29.0 N, 91.0-102.0 E)",
            },
            "quality_control_audit": {
                "initial_status": state.get("initial_qc", {}).get("qc_status"),
                "final_status": qc.get("qc_status"),
                "active_flags": qc.get("qc_flags", []),
                "qc_score": qc.get("qc_score"),
            },
            "human_in_the_loop": {
                "review_required": rev.get("review_required", True),
                "review_status": rev.get("review_status", "UNREVIEWED"),
                "review_triggers": rev.get("triggers", []),
                "overridden": False,
            },
            "stages_executed": list(self.stage_history),
        }

        return {"structured_summary": summary}

    def execute(self) -> Dict[str, Any]:
        """Run the complete pipeline end-to-end starting with an empty initial state."""
        self.stage_history.clear()
        initial_state = {}
        return self.graph.execute(initial_state)
