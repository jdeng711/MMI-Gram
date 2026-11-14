"""
Seismological modules and MMI reference scales for MMI-Gram.
"""

from .mmi_reference import LocalMMIReference, validate_scale_completeness

__all__ = ["LocalMMIReference", "validate_scale_completeness"]
