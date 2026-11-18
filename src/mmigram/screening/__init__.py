"""
MMI-Gram Pre-MMI Screening & Evidence Filtering Subsystem.

Exports:
  - RelevanceGate, RelevanceDecision
  - TemporalGate, TemporalCheckResult
  - RecycledMediaGate, DuplicateCheckResult
  - AuthenticityGate, AuthenticityCheckResult
  - SpatialGate, SpatialCheckResult
  - CompositeScreener, ScreeningResult
"""

from .relevance_gate import RelevanceGate, RelevanceDecision
from .temporal_gate import TemporalGate, TemporalCheckResult
from .recycled_gate import RecycledMediaGate, DuplicateCheckResult
from .authenticity_gate import AuthenticityGate, AuthenticityCheckResult
from .spatial_gate import SpatialGate, SpatialCheckResult
from .composite_screener import CompositeScreener, ScreeningResult

__all__ = [
    "RelevanceGate",
    "RelevanceDecision",
    "TemporalGate",
    "TemporalCheckResult",
    "RecycledMediaGate",
    "DuplicateCheckResult",
    "AuthenticityGate",
    "AuthenticityCheckResult",
    "SpatialGate",
    "SpatialCheckResult",
    "CompositeScreener",
    "ScreeningResult",
]
