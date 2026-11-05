"""
Human-in-the-Loop Review Queue for Seismic Observations.
Allows expert structural seismologists to audit, approve, reject, or override AI estimates.
"""

from __future__ import annotations
import json
import datetime
from typing import Dict, List, Optional, Any
from ..core.state import Coordinates, HumanReviewRecord, MMIGramState
from ..qc.rules import FLAG_HIGH_INTENSITY_ANOMALY, FLAG_LOW_CONFIDENCE, FLAG_OUT_OF_REGION


class ReviewItem:
    """A single observation queued for human expert review."""

    def __init__(
        self,
        item_id: str,
        data: Dict[str, Any],
        triggers: List[str],
        status: str = "UNREVIEWED",
        reviewer_id: Optional[str] = None,
        reviewer_notes: Optional[str] = None,
        reviewed_at_utc: Optional[str] = None,
        overridden_mmi: Optional[float] = None,
        overridden_coordinates: Optional[Dict[str, Any]] = None,
    ):
        self.item_id = item_id
        self.data = data
        self.triggers = triggers
        self.status = status
        self.reviewer_id = reviewer_id
        self.reviewer_notes = reviewer_notes
        self.reviewed_at_utc = reviewed_at_utc
        self.overridden_mmi = overridden_mmi
        self.overridden_coordinates = overridden_coordinates

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "data": self.data,
            "triggers": self.triggers,
            "status": self.status,
            "reviewer_id": self.reviewer_id,
            "reviewer_notes": self.reviewer_notes,
            "reviewed_at_utc": self.reviewed_at_utc,
            "overridden_mmi": self.overridden_mmi,
            "overridden_coordinates": self.overridden_coordinates,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ReviewItem:
        return cls(
            item_id=d["item_id"],
            data=d.get("data", {}),
            triggers=d.get("triggers", []),
            status=d.get("status", "UNREVIEWED"),
            reviewer_id=d.get("reviewer_id"),
            reviewer_notes=d.get("reviewer_notes"),
            reviewed_at_utc=d.get("reviewed_at_utc"),
            overridden_mmi=d.get("overridden_mmi"),
            overridden_coordinates=d.get("overridden_coordinates"),
        )


class HumanReviewQueue:
    """
    Queue managing observations requiring expert seismological review.
    """

    def __init__(self, persistence_file: Optional[str] = None):
        self.items: Dict[str, ReviewItem] = {}
        self.persistence_file = persistence_file
        if self.persistence_file:
            self.load()

    def check_and_enqueue(
        self,
        item_id: str,
        state: Dict[str, Any],
        force: bool = False,
    ) -> Optional[ReviewItem]:
        """
        Evaluate observation against review trigger criteria and enqueue if necessary.
        """
        triggers: List[str] = []

        # 1. Check QC flags
        qc_data = state.get("qc", {})
        qc_flags = qc_data.get("qc_flags", [])

        if FLAG_HIGH_INTENSITY_ANOMALY in qc_flags:
            triggers.append(
                "High seismic intensity (MMI >= 9.0) requires authoritative verification."
            )
        if FLAG_LOW_CONFIDENCE in qc_flags:
            triggers.append("Model confidence is below acceptable threshold (< 0.75).")
        if FLAG_OUT_OF_REGION in qc_flags:
            triggers.append("Coordinates are outside target regional bounding box.")

        # 2. Check direct values if QC not run
        est = state.get("estimation", {})
        mmi = est.get("mmi_value")
        conf = est.get("confidence", 0.0)
        if mmi is not None and mmi >= 9.0 and "High seismic intensity" not in str(triggers):
            triggers.append(f"Reported MMI {mmi} >= 9.0 requires expert scrutiny.")
        if conf is not None and conf < 0.75 and "below acceptable threshold" not in str(triggers):
            triggers.append(f"Low confidence ({conf:.2f} < 0.75).")

        if triggers or force:
            item = ReviewItem(item_id=item_id, data=state, triggers=triggers)
            self.items[item_id] = item
            self._save()
            return item

        return None

    def get_pending(self) -> List[ReviewItem]:
        """Return all items awaiting review."""
        return [item for item in self.items.values() if item.status == "UNREVIEWED"]

    def get_item(self, item_id: str) -> Optional[ReviewItem]:
        return self.items.get(item_id)

    def approve(self, item_id: str, reviewer_id: str, notes: str = "") -> ReviewItem:
        """Approve an observation as scientifically acceptable."""
        item = self._require_item(item_id)
        item.status = "APPROVED"
        item.reviewer_id = reviewer_id
        item.reviewer_notes = notes
        item.reviewed_at_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._save()
        return item

    def reject(self, item_id: str, reviewer_id: str, reason: str) -> ReviewItem:
        """Reject an observation as invalid or erroneous."""
        item = self._require_item(item_id)
        item.status = "REJECTED"
        item.reviewer_id = reviewer_id
        item.reviewer_notes = reason
        item.reviewed_at_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._save()
        return item

    def override_mmi(
        self,
        item_id: str,
        reviewer_id: str,
        new_mmi: float,
        notes: str,
    ) -> ReviewItem:
        """Override estimated MMI value with expert calibrated score."""
        item = self._require_item(item_id)
        item.status = "OVERRIDDEN"
        item.reviewer_id = reviewer_id
        item.overridden_mmi = float(new_mmi)
        item.reviewer_notes = notes
        item.reviewed_at_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._save()
        return item

    def override_coordinates(
        self,
        item_id: str,
        reviewer_id: str,
        latitude: float,
        longitude: float,
        notes: str,
    ) -> ReviewItem:
        """Override coordinates with expert verified coordinates."""
        item = self._require_item(item_id)
        item.status = "OVERRIDDEN"
        item.reviewer_id = reviewer_id
        item.overridden_coordinates = {
            "latitude": float(latitude),
            "longitude": float(longitude),
            "source": "manual_override",
            "is_valid": True,
            "confidence": 1.0,
        }
        item.reviewer_notes = notes
        item.reviewed_at_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._save()
        return item

    def _require_item(self, item_id: str) -> ReviewItem:
        if item_id not in self.items:
            raise KeyError(f"Item '{item_id}' not found in review queue.")
        return self.items[item_id]

    def _save(self) -> None:
        if not self.persistence_file:
            return
        try:
            with open(self.persistence_file, "w", encoding="utf-8") as f:
                json.dump([item.to_dict() for item in self.items.values()], f, indent=2)
        except Exception:
            pass

    def load(self) -> None:
        if not self.persistence_file:
            return
        try:
            with open(self.persistence_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.items = {d["item_id"]: ReviewItem.from_dict(d) for d in data}
        except FileNotFoundError:
            self.items = {}
        except Exception:
            self.items = {}
