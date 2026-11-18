"""
Temporal Consistency Gate for MMI-Gram.

Verifies that observation timestamps do not contradict the earthquake event timing.
Distinguishes between missing timestamps (accepted with lower provenance) and
demonstrated chronological contradictions (predating origin time T0).

Attribution:
  Adapted and expanded from Clara Yoon's TemporalGate in QuakeLLMmap (quake_agent/gates/temporal_gate.py).
"""

from __future__ import annotations
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, Union


@dataclass
class TemporalCheckResult:
    """Result of temporal consistency evaluation."""
    status: str = "VALID"  # 'VALID', 'TIMESTAMP_MISSING', 'PREDATES_EVENT', 'PDF_METADATA_ONLY'
    is_valid: bool = True
    observed_timestamp_utc: Optional[str] = None
    timestamp_source: str = "none"  # 'reported_observation', 'exif_capture', 'pdf_creation', 'none'
    timestamp_reliability: str = "none"  # 'high', 'medium', 'low', 'none'
    is_observation_time: bool = False
    reason: str = "Timestamp is temporally consistent with event."
    clock_drift_minutes: float = 5.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TemporalGate:
    """
    Checks whether content timestamps post-date the earthquake origin time T0.
    Distinguishes high-reliability observation times (EXIF capture, reported observation)
    from low-reliability document compilation times (PDF creation/modification).
    """

    def __init__(
        self,
        origin_time_utc: str = "2025-03-28T06:20:00Z",
        clock_drift_minutes: float = 5.0,
    ):
        clean_origin = origin_time_utc.replace("Z", "+00:00")
        try:
            self.t0 = datetime.fromisoformat(clean_origin)
            if self.t0.tzinfo is None:
                self.t0 = self.t0.replace(tzinfo=timezone.utc)
        except Exception:
            self.t0 = datetime(2025, 3, 28, 6, 20, 0, tzinfo=timezone.utc)
        self.clock_drift_minutes = clock_drift_minutes

    def check(
        self,
        file_path: Optional[Union[str, Path]] = None,
        extracted_text: Optional[str] = None,
        explicit_timestamp: Optional[Union[str, datetime]] = None,
    ) -> TemporalCheckResult:
        """
        Evaluates temporal consistency against event origin time T0.
        """
        observed_dt: Optional[datetime] = None
        source: str = "none"
        reliability: str = "none"
        is_obs_time: bool = False

        # 1. Explicit reported timestamp if provided
        if explicit_timestamp:
            if isinstance(explicit_timestamp, datetime):
                observed_dt = explicit_timestamp
            else:
                observed_dt = self._parse_iso_string(str(explicit_timestamp))
            if observed_dt:
                source = "reported_observation"
                reliability = "high"
                is_obs_time = True

        # 2. Extract from document text observation dates if absent
        if not observed_dt and extracted_text:
            text_dt = self._extract_text_datetime(extracted_text)
            if text_dt:
                observed_dt = text_dt
                source = "reported_observation"
                reliability = "high"
                is_obs_time = True

        # 3. Extract from image EXIF capture time (DateTimeOriginal)
        if not observed_dt and file_path:
            p = Path(file_path).resolve()
            if p.exists():
                ext = p.suffix.lower()
                if ext in (".jpg", ".jpeg", ".tiff", ".png"):
                    exif_dt = self._extract_image_exif_datetime(p)
                    if exif_dt:
                        observed_dt = exif_dt
                        source = "exif_capture"
                        reliability = "high"
                        is_obs_time = True
                elif ext == ".pdf":
                    # PDF creation date (compilation time, NOT observation time)
                    pdf_dt = self._extract_pdf_creation_datetime(p)
                    if pdf_dt:
                        observed_dt = pdf_dt
                        source = "pdf_creation"
                        reliability = "low"
                        is_obs_time = False

        # 4. If no timestamp found at all: ACCEPT without penalty
        if not observed_dt:
            return TemporalCheckResult(
                status="TIMESTAMP_MISSING",
                is_valid=True,
                observed_timestamp_utc=None,
                timestamp_source="none",
                timestamp_reliability="none",
                is_observation_time=False,
                reason="No timestamp metadata found in document; accepted as valid without temporal contradiction.",
                clock_drift_minutes=self.clock_drift_minutes,
            )

        # Ensure timezone-aware
        if observed_dt.tzinfo is None:
            observed_dt = observed_dt.replace(tzinfo=timezone.utc)

        allowed_earliest = self.t0 - timedelta(minutes=self.clock_drift_minutes)

        # 5. Handle timestamps predating T0
        if observed_dt < allowed_earliest:
            # Only flag as contradiction if source is a reliable observation or EXIF capture time
            if is_obs_time and reliability in ("high", "medium"):
                return TemporalCheckResult(
                    status="PREDATES_EVENT",
                    is_valid=False,
                    observed_timestamp_utc=observed_dt.isoformat(),
                    timestamp_source=source,
                    timestamp_reliability=reliability,
                    is_observation_time=True,
                    reason=(
                        f"Reliable observation timestamp ({observed_dt.isoformat()}, source: {source}) "
                        f"predates earthquake origin ({self.t0.isoformat()}) by more than {self.clock_drift_minutes} minutes."
                    ),
                    clock_drift_minutes=self.clock_drift_minutes,
                )
            else:
                # PDF template creation or file modification date predates event
                return TemporalCheckResult(
                    status="PDF_METADATA_ONLY",
                    is_valid=True,
                    observed_timestamp_utc=observed_dt.isoformat(),
                    timestamp_source=source,
                    timestamp_reliability=reliability,
                    is_observation_time=False,
                    reason=(
                        f"PDF metadata timestamp ({observed_dt.isoformat()}, source: {source}) predates event origin, "
                        "likely reflecting legacy presentation template creation rather than an observation contradiction. "
                        "Accepted as valid."
                    ),
                    clock_drift_minutes=self.clock_drift_minutes,
                )

        return TemporalCheckResult(
            status="VALID",
            is_valid=True,
            observed_timestamp_utc=observed_dt.isoformat(),
            timestamp_source=source,
            timestamp_reliability=reliability,
            is_observation_time=is_obs_time,
            reason=f"Observation timestamp ({observed_dt.isoformat()}, source: {source}) post-dates earthquake origin.",
            clock_drift_minutes=self.clock_drift_minutes,
        )

    def _parse_iso_string(self, ts_str: str) -> Optional[datetime]:
        try:
            clean = ts_str.strip().replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        except Exception:
            return None

    def _extract_image_exif_datetime(self, path: Path) -> Optional[datetime]:
        try:
            from PIL import Image, ExifTags
            with Image.open(path) as img:
                exif = img.getexif()
                if not exif:
                    return None
                for tag_id, value in exif.items():
                    tag_name = ExifTags.TAGS.get(tag_id, tag_id)
                    if tag_name in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
                        # Format: "YYYY:MM:DD HH:MM:SS"
                        clean_str = str(value).strip()
                        return datetime.strptime(clean_str, "%Y:%m:%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except Exception:
            pass
        return None

    def _extract_pdf_creation_datetime(self, path: Path) -> Optional[datetime]:
        try:
            import pypdf
            reader = pypdf.PdfReader(str(path))
            meta = reader.metadata
            if not meta:
                return None
            # Strictly use /CreationDate, NEVER /ModDate (which is just file save time)
            raw_date = meta.get("/CreationDate")
            if raw_date:
                # PDF format: D:YYYYMMDDHHmmSS...
                match = re.search(r"D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})", str(raw_date))
                if match:
                    y, m, d, hh, mm, ss = [int(v) for v in match.groups()]
                    return datetime(y, m, d, hh, mm, ss, tzinfo=timezone.utc)
        except Exception:
            pass
        return None

    def _extract_text_datetime(self, text: str) -> Optional[datetime]:
        # Regex for common ISO dates: YYYY-MM-DD HH:MM:SS
        match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})[T\s](\d{2}):(\d{2})(?::(\d{2}))?", text)
        if match:
            try:
                y = int(match.group(1))
                m = int(match.group(2))
                d = int(match.group(3))
                hh = int(match.group(4))
                mm = int(match.group(5))
                ss = int(match.group(6) or 0)
                return datetime(y, m, d, hh, mm, ss, tzinfo=timezone.utc)
            except Exception:
                pass
        return None
