"""
Model and legacy service adapters for MMI-Gram.
"""

from .crag_adapter import CRAGAdapter, check_live_prerequisites

__all__ = ["CRAGAdapter", "check_live_prerequisites"]
