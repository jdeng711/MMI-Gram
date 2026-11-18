"""
USGS ShakeMap 4.5 Observation Exporter (*_dat.json).

Exports verified, georeferenced, estimable MMI observations to the official
USGS ShakeMap v4 input data specification (GeoJSON FeatureCollection).

Reference:
- USGS ShakeMap Manual (Input Data Formats):
  https://ghsc.code-pages.usgs.gov/esi/shakemap/manual4_0/tg_input_formats.html#json-format

Scientific & Operational Safeguards:
1. Coordinate Order: Strict GeoJSON [longitude, latitude] ordering.
2. Scientific Qualification Gate:
   - Excludes NOT_ESTIMABLE inputs, approximate viewport centers, approximate city centroids,
     unresolved coordinate conflicts, and unapproved human-review items.
   - Properly recorded expert approvals (review_status == 'APPROVED') clear review restrictions.
3. Audit Transparency:
   - All excluded observations and specific exclusion reasons are written to a companion
     excluded_observations.json audit log.
4. Observation Uncertainty in USGS ShakeMap 4.5:
   - In official USGS ShakeMap 4.5, macroseismic observations (such as Did You Feel It? CDI aggregates)
     have an observation variance sigma^2 scaling with the number of responses (Worden et al., 2012).
   - For single macroseismic reports without ensemble aggregation, ShakeMap expects an observation stddev
     (often defaulting around 0.3-0.5 in model.conf depending on network settings).
   - For AI-derived MMI observations, NO calibrated observation uncertainty distribution is currently
     established in the scientific literature. A fixed prior like sigma = 0.50 is an experimental assumption,
     NOT an empirical ground truth or established consensus.
   - Clara's formula sigma = 0.35 + (1.0 - conf) * 0.70 is preserved strictly for experimental comparison.
   - All exported observations explicitly record the chosen uncertainty policy and the raw model confidence.
5. Spatial Duplication & Proximal Clusters:
   - Distinguishes exact duplicate media, repeated reports of the same physical structure, and
     nearby but scientifically independent observations.
   - Independent observations within 100 meters are PRESERVED and grouped into spatial clusters,
     preventing the wrongful suppression of valid nearby eyewitness reports or distinct buildings.
"""

from __future__ import annotations
import math
import json
import enum
import hashlib
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union


def haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute great-circle distance between two geodetic points in meters."""
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2.0)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2.0)**2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return 6371008.8 * c


class UncertaintyStrategy(str, enum.Enum):
    """Observation standard deviation strategy for ShakeMap export."""
    EXPERIMENTAL_FIXED_PRIOR = "experimental_fixed_prior"  # Configurable fixed experimental prior (e.g. sigma = 0.50)
    CLARA_EXPERIMENTAL = "clara_experimental"              # Clara's heuristic: sigma = 0.35 + (1 - conf) * 0.70 (experimental comparison only)
    EXPERT_SPECIFIED = "expert_specified"                  # User-configured static or per-observation sigma

    # Backwards compatibility alias
    STANDARD_CONSENSUS = "experimental_fixed_prior"


class ShakeMapExporter:
    """
    Exports MMI observation records into USGS ShakeMap 4.5 GeoJSON input format.
    """

    def __init__(
        self,
        event_id: str = "unknown",
        uncertainty_strategy: Union[UncertaintyStrategy, str] = UncertaintyStrategy.EXPERIMENTAL_FIXED_PRIOR,
        default_stddev: float = 0.50,
        agency_name: str = "MMI-Gram",
        output_dir: Optional[Union[str, Path]] = None,
        expert_uncertainty: Optional[float] = None,
    ):
        self.event_id = event_id
        if isinstance(uncertainty_strategy, str):
            strat_lower = uncertainty_strategy.lower()
            if strat_lower in ("standard_consensus", "experimental_fixed_prior"):
                self.uncertainty_strategy = UncertaintyStrategy.EXPERIMENTAL_FIXED_PRIOR
            elif strat_lower == "clara_experimental":
                self.uncertainty_strategy = UncertaintyStrategy.CLARA_EXPERIMENTAL
            elif strat_lower == "expert_specified":
                self.uncertainty_strategy = UncertaintyStrategy.EXPERT_SPECIFIED
            else:
                self.uncertainty_strategy = UncertaintyStrategy.EXPERIMENTAL_FIXED_PRIOR
        else:
            self.uncertainty_strategy = uncertainty_strategy

        if expert_uncertainty is not None:
            self.default_stddev = float(expert_uncertainty)
        else:
            self.default_stddev = float(default_stddev)

        self.agency_name = agency_name
        self.default_output_dir = Path(output_dir) if output_dir else None

    def compute_stddev(self, confidence: Optional[float], custom_stddev: Optional[float] = None) -> float:
        """
        Compute intensity standard deviation based on configured strategy.
        """
        if self.uncertainty_strategy == UncertaintyStrategy.EXPERT_SPECIFIED:
            if custom_stddev is not None and custom_stddev > 0.0:
                return round(float(custom_stddev), 3)
            return self.default_stddev

        elif self.uncertainty_strategy == UncertaintyStrategy.CLARA_EXPERIMENTAL:
            # Clara's linear heuristic: sigma in [0.35, 1.05]
            conf = confidence if confidence is not None else 0.50
            conf_clamped = max(0.0, min(1.0, float(conf)))
            return round(0.35 + (1.0 - conf_clamped) * 0.70, 3)

        else:
            # EXPERIMENTAL_FIXED_PRIOR: Configurable working prior for experimental ShakeMap integration
            return round(self.default_stddev, 3)

    def get_uncertainty_policy_description(self) -> str:
        """Return human-readable documentation of the selected observation uncertainty policy."""
        if self.uncertainty_strategy == UncertaintyStrategy.EXPERIMENTAL_FIXED_PRIOR:
            return (
                f"Configurable experimental fixed prior (sigma = {self.default_stddev:.2f}). "
                "Note: No calibrated AI observation uncertainty distribution is currently established; "
                "this is a working experimental prior, not an empirical consensus."
            )
        elif self.uncertainty_strategy == UncertaintyStrategy.CLARA_EXPERIMENTAL:
            return (
                "Clara Yoon heuristic formula: sigma = 0.35 + (1.0 - conf) * 0.70. "
                "Preserved strictly for experimental comparison; LLM confidence scores are uncalibrated."
            )
        elif self.uncertainty_strategy == UncertaintyStrategy.EXPERT_SPECIFIED:
            return "User-configured static or per-observation expert uncertainty."
        return "Unspecified uncertainty policy."

    @classmethod
    def generate_observation_code(cls, item_id: str, lat: float, lon: float) -> str:
        """Generate a deterministic 8-character observation code."""
        key = f"{item_id}_{lat:.4f}_{lon:.4f}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]

    def export_observations(
        self,
        observations: List[Dict[str, Any]],
        output_dir: Optional[Union[str, Path]] = None,
        filename: str = "agent_mmi_dat.json",
        allow_unreviewed_approved: bool = True,
        require_expert_approval: bool = False,
    ) -> Dict[str, Any]:
        """
        Process observation records, export qualified records to *_dat.json,
        and write excluded records to excluded_observations.json.

        Distinguishes:
        - Exact duplicate media (identical SHA-256)
        - Repeated evidence from the same observation site
        - Nearby but scientifically independent observations (preserved and clustered!)
        - Technical compatibility export vs. scientifically validated expert-approved export

        Args:
            observations: List of observation dictionaries from MMI-Gram or QuakeAgent.
            output_dir: Directory where GeoJSON and audit logs will be written.
            filename: Target ShakeMap observation file name (*_dat.json).
            allow_unreviewed_approved: If True, observations with review_status == 'APPROVED' clear review gate.
            require_expert_approval: If True, STRICTLY requires review_status == 'APPROVED' for every exported
                observation; any unreviewed or pending observation is rejected and logged.

        Returns:
            summary_stats dict containing exported_count, excluded_count, file paths.
        """
        target_dir = Path(output_dir) if output_dir is not None else (self.default_output_dir or Path("."))
        target_dir.mkdir(parents=True, exist_ok=True)
        export_path = target_dir / filename
        audit_path = target_dir / "excluded_observations.json"

        qualified_features: List[Dict[str, Any]] = []
        excluded_records: List[Dict[str, Any]] = []
        accepted_records: List[Dict[str, Any]] = []
        clusters: Dict[str, List[str]] = {}
        cluster_counter = 0

        for obs in observations:
            file_name = obs.get("file_name", "unknown")
            seis = obs.get("seismic_intensity", {})
            geo = obs.get("geographic_resolution", {})
            qc = obs.get("quality_control", {})
            hitl = obs.get("human_in_the_loop", {})
            screening = obs.get("screening", {})

            rejection_reasons: List[str] = []

            # 1. Check Screening Status
            relevance = screening.get("relevance_decision", "UNKNOWN")
            if relevance in ("NOT_ESTIMABLE", "SCREENED_OUT"):
                rejection_reasons.append(f"Pre-MMI screening classified document as {relevance}")

            # 2. Check MMI validity
            mmi = seis.get("mmi_estimation")
            if mmi is None or not (1.0 <= mmi <= 12.0):
                rejection_reasons.append("Missing or out-of-range MMI estimate (requires 1.0 <= MMI <= 12.0)")

            # 3. Check Coordinates
            coords = geo.get("coordinates")
            lat: Optional[float] = None
            lon: Optional[float] = None
            if not coords or coords.get("latitude") is None or coords.get("longitude") is None:
                rejection_reasons.append("Missing geographic coordinates (coordinates: null)")
            else:
                lat = float(coords["latitude"])
                lon = float(coords["longitude"])

            # 4. Check Coordinate Conflict
            if geo.get("coordinates_disagree", False):
                rejection_reasons.append(f"Active coordinate conflict: {geo.get('discrepancy_details')}")

            # 5. Check Exportable Site Coordinates & Precision
            prec = geo.get("precision_level", "unknown")
            has_site_coords = geo.get("has_exportable_site_coordinates", False)
            if not has_site_coords:
                rejection_reasons.append(f"Ineligible coordinate precision level '{prec}' (requires verified site-specific coordinates)")

            # 6. Check QC Status
            qc_status = qc.get("status", "UNKNOWN")
            if qc_status in ("REJECTED", "SCREENED_OUT"):
                rejection_reasons.append(f"Quality control status is {qc_status} (Flags: {qc.get('flags')})")

            # 7. Check Human Review Status
            review_required = hitl.get("review_required", False)
            review_status = hitl.get("review_status", "NOT_ENQUEUED")

            if require_expert_approval:
                if review_status != "APPROVED":
                    rejection_reasons.append(
                        f"Observation requires scientific expert approval before ShakeMap export (Status: '{review_status}')"
                    )
            else:
                is_cleared = (not review_required) or (allow_unreviewed_approved and review_status == "APPROVED")
                if not is_cleared:
                    rejection_reasons.append(
                        f"Observation requires expert human review (Status: {review_status}, Triggers: {hitl.get('triggers')})"
                    )

            # 8. Discrimination between:
            #    (a) Exact duplicate media (identical SHA-256)
            #    (b) Repeated evidence of the exact same observation/site
            #    (c) Nearby but scientifically independent observations (preserve & cluster!)
            is_duplicate = False
            duplicate_reason = None
            duplicate_of_code = None
            matched_cluster_id: Optional[str] = None

            if lat is not None and lon is not None:
                obs_sha256 = (
                    obs.get("document_extraction", {}).get("sha256_hash")
                    or obs.get("screening", {}).get("sha256_hash")
                    or obs.get("sha256_hash")
                    or obs.get("content_sha256")
                )
                obs_place = (geo.get("place_name") or geo.get("location", {}).get("site_name") or "").strip().lower()

                for prior in accepted_records:
                    dist_m = haversine_distance_meters(lat, lon, prior["lat"], prior["lon"])
                    if dist_m < 100.0:
                        # (a) Exact duplicate media (identical hash)
                        if obs_sha256 and prior["sha256"] and obs_sha256 == prior["sha256"]:
                            is_duplicate = True
                            duplicate_reason = (
                                f"DUPLICATE_MEDIA: Media SHA-256 identical to prior accepted observation "
                                f"{prior['code']} ({prior['file_name']})"
                            )
                            duplicate_of_code = prior["code"]
                            break

                        # (b) Same source report re-submitted
                        if file_name == prior["file_name"]:
                            is_duplicate = True
                            duplicate_reason = (
                                f"DUPLICATE_REPORT: Source file '{file_name}' already exported as {prior['code']}"
                            )
                            duplicate_of_code = prior["code"]
                            break

                        # (c) Repeated observation of the exact same site (< 15 m and matching site name or same unnamed site)
                        if dist_m < 15.0 and (
                            (obs_place and prior["place_name"] and obs_place == prior["place_name"])
                            or (not obs_place and not prior["place_name"])
                        ):
                            site_label = geo.get("place_name") or geo.get("location", {}).get("site_name") or "unnamed site"
                            is_duplicate = True
                            duplicate_reason = (
                                f"DUPLICATE_SITE: Repeated observation of site '{site_label}' "
                                f"at distance {dist_m:.1f} m from {prior['code']}"
                            )
                            duplicate_of_code = prior["code"]
                            break

                        # (d) Nearby but scientifically independent observations (< 100 m)
                        # DO NOT DISCARD! Group into spatial cluster.
                        if prior["cluster_id"] is None:
                            cluster_counter += 1
                            new_cid = f"cluster_{cluster_counter:03d}"
                            prior["cluster_id"] = new_cid
                            if "feature_properties" in prior:
                                prior["feature_properties"]["cluster_flag"] = "PROXIMAL_INDEPENDENT_CLUSTER"
                                prior["feature_properties"]["cluster_id"] = new_cid
                            clusters[new_cid] = [prior["code"]]
                        matched_cluster_id = prior["cluster_id"]

            if is_duplicate and duplicate_reason:
                rejection_reasons.append(duplicate_reason)

            if rejection_reasons:
                ex_rec = {
                    "file_name": file_name,
                    "reason": "; ".join(rejection_reasons),
                    "exclusion_reasons": rejection_reasons,
                    "observation_data": obs,
                }
                if duplicate_of_code is not None:
                    ex_rec["duplicate_of"] = duplicate_of_code
                excluded_records.append(ex_rec)
                continue

            # Observation is qualified!
            code = self.generate_observation_code(file_name, lat, lon)

            cluster_flag = "SINGLE"
            if matched_cluster_id is not None:
                cluster_flag = "PROXIMAL_INDEPENDENT_CLUSTER"
                clusters[matched_cluster_id].append(code)

            conf = seis.get("confidence")
            stddev = self.compute_stddev(conf)
            rrup = geo.get("rrup_km")

            props = {
                "code": code,
                "name": geo.get("place_name") or f"MMI-Gram Eyewitness: {file_name}",
                "network": "MMI",
                "netid": "MMI",
                "station_type": "macroseismic",
                "channels": [],
                "nresp": 1,
                "source": f"{self.agency_name} Agentic Reconnaissance",
                "intensity": round(float(mmi), 1),
                "intensity_stddev": stddev,
                "intensity_flag": "0",
                "agency": self.agency_name,
                "file_name": file_name,
                "model_name": obs.get("model_identifier", "gemini"),
                "raw_model_confidence": round(float(conf), 3) if conf is not None else None,
                "uncertainty_policy": self.uncertainty_strategy.value,
                "rrup_km": round(float(rrup), 2) if rrup is not None else None,
                "precision_level": prec,
                "cluster_flag": cluster_flag,
                "cluster_id": matched_cluster_id,
                "expert_approved": (review_status == "APPROVED"),
                "review_status": review_status,
                "scientific_use_allowed": (review_status == "APPROVED"),
            }

            accepted_records.append({
                "code": code,
                "file_name": file_name,
                "lat": lat,
                "lon": lon,
                "sha256": obs_sha256 if lat is not None else None,
                "place_name": obs_place if lat is not None else None,
                "cluster_id": matched_cluster_id,
                "feature_properties": props,
            })

            feature = {
                "type": "Feature",
                "id": f"MMI.{code}",
                "properties": props,
                "geometry": {
                    "type": "Point",
                    "coordinates": [round(lon, 6), round(lat, 6)],
                },
            }
            qualified_features.append(feature)

        # Determine dataset validation type
        is_fully_approved_dataset = (
            len(qualified_features) > 0
            and all(f.get("properties", {}).get("expert_approved", False) for f in qualified_features)
        )
        dataset_type = (
            "scientifically_validated_observation_dataset"
            if is_fully_approved_dataset
            else "technical_compatibility_artifact"
        )
        human_review_status = (
            "FULLY_EXPERT_APPROVED"
            if is_fully_approved_dataset
            else "INCOMPLETE_EXPERIMENTAL_TECHNICAL_ARTIFACT"
        )
        warning_msg = (
            None
            if is_fully_approved_dataset
            else (
                "EXPERIMENTAL TECHNICAL ARTIFACT ONLY: Contains unreviewed AI-derived observations. "
                "This file has NOT been validated by human seismologists and must NOT be used as official "
                "ground truth or for final scientific reporting."
            )
        )

        # Assemble ShakeMap GeoJSON document
        geojson_doc = {
            "type": "FeatureCollection",
            "metadata": {
                "event_id": self.event_id,
                "source": f"{self.agency_name} ShakeMap Observation Exporter",
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "count": len(qualified_features),
                "dataset_type": dataset_type,
                "expert_reviewed": is_fully_approved_dataset,
                "human_review_status": human_review_status,
                "warning": warning_msg,
                "uncertainty_policy": self.uncertainty_strategy.value,
                "uncertainty_policy_description": self.get_uncertainty_policy_description(),
                "default_stddev": self.default_stddev,
                "spatial_clusters": clusters,
            },
            "features": qualified_features,
        }

        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(geojson_doc, f, indent=2)

        # Write audit trail of excluded observations and clusters
        audit_doc = {
            "event_id": self.event_id,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "excluded_count": len(excluded_records),
            "excluded_observations": excluded_records,
            "spatial_clusters": clusters,
        }
        with open(audit_path, "w", encoding="utf-8") as f:
            json.dump(audit_doc, f, indent=2)

        stats = {
            "total_submitted": len(observations),
            "exported_count": len(qualified_features),
            "qualified_exported": len(qualified_features),
            "excluded_count": len(excluded_records),
            "export_file": str(export_path),
            "audit_file": str(audit_path),
        }
        return stats

    @classmethod
    def validate_shakemap_geojson(cls, geojson_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Validate a generated ShakeMap GeoJSON document against official USGS ShakeMap 4.5 input specs.
        """
        errors: List[str] = []

        if geojson_data.get("type") != "FeatureCollection":
            errors.append("Top-level type must be 'FeatureCollection'")

        features = geojson_data.get("features")
        if not isinstance(features, list):
            errors.append("'features' must be a list")
            return (False, errors)

        for idx, feat in enumerate(features):
            if feat.get("type") != "Feature":
                errors.append(f"Feature {idx}: type must be 'Feature'")

            geom = feat.get("geometry", {})
            if geom.get("type") != "Point":
                errors.append(f"Feature {idx}: geometry type must be 'Point'")

            coords = geom.get("coordinates", [])
            if not isinstance(coords, (list, tuple)) or len(coords) < 2:
                errors.append(f"Feature {idx}: coordinates must be [lon, lat]")
            else:
                lon, lat = coords[0], coords[1]
                if not (-180.0 <= lon <= 180.0):
                    errors.append(f"Feature {idx}: longitude {lon} out of range [-180, 180]")
                if not (-90.0 <= lat <= 90.0):
                    errors.append(f"Feature {idx}: latitude {lat} out of range [-90, 90]")

            props = feat.get("properties", {})
            for req_field in ["code", "network", "intensity", "intensity_flag", "station_type"]:
                if req_field not in props:
                    errors.append(f"Feature {idx}: missing required ShakeMap property '{req_field}'")

            intensity = props.get("intensity")
            if intensity is None or not (1.0 <= float(intensity) <= 12.0):
                errors.append(f"Feature {idx}: intensity must be between 1.0 and 12.0 (got {intensity})")

            stddev = props.get("intensity_stddev")
            if stddev is not None and float(stddev) <= 0.0:
                errors.append(f"Feature {idx}: intensity_stddev must be > 0.0 (got {stddev})")

        return (len(errors) == 0, errors)


# Module-level convenience function
validate_shakemap_geojson = ShakeMapExporter.validate_shakemap_geojson


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MMI-Gram USGS ShakeMap 4.5 Observation Exporter (*_dat.json)"
    )
    parser.add_argument(
        "--input",
        "-i",
        required=True,
        type=Path,
        help="Path to input observations JSON file",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        required=True,
        type=Path,
        help="Directory to write agent_mmi_dat.json and audit log",
    )
    parser.add_argument(
        "--event-id",
        type=str,
        default="us7000pn9s",
        help="USGS earthquake event ID (default: us7000pn9s)",
    )
    parser.add_argument(
        "--uncertainty-strategy",
        type=str,
        default="experimental_fixed_prior",
        choices=["experimental_fixed_prior", "clara_experimental", "expert_specified"],
        help="Observation uncertainty policy (default: experimental_fixed_prior)",
    )
    parser.add_argument(
        "--default-stddev",
        type=float,
        default=0.50,
        help="Default observation standard deviation (default: 0.50)",
    )
    parser.add_argument(
        "--filename",
        type=str,
        default="agent_mmi_dat.json",
        help="Output GeoJSON file name (default: agent_mmi_dat.json)",
    )
    parser.add_argument(
        "--require-expert-approval",
        action="store_true",
        default=False,
        help="Enforce that only human expert-approved observations (review_status == 'APPROVED') are exported",
    )
    parser.add_argument(
        "--agency-name",
        type=str,
        default="MMI-Gram",
        help="Reporting agency name (default: MMI-Gram)",
    )

    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: input file '{args.input}' does not exist.", file=sys.stderr)
        sys.exit(1)

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Allow either a list of observations or an object with an 'observations' list
    obs_list = data if isinstance(data, list) else data.get("observations", [])

    exporter = ShakeMapExporter(
        event_id=args.event_id,
        uncertainty_strategy=args.uncertainty_strategy,
        default_stddev=args.default_stddev,
        agency_name=args.agency_name,
        output_dir=args.output_dir,
    )

    result = exporter.export_observations(
        observations=obs_list,
        output_dir=args.output_dir,
        filename=args.filename,
        require_expert_approval=args.require_expert_approval,
    )

    print(
        f"Export completed: {result['exported_count']} exported, "
        f"{result['excluded_count']} excluded. "
        f"Output: {result['export_file']}"
    )

