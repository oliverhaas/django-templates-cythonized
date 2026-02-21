"""
Cython-accelerated safe string utilities for the template engine.

Re-exports Django's SafeData/SafeString types for isinstance compatibility,
provides a fast mark_safe() without @keep_lazy overhead.
"""

import cython

from django.utils.safestring import SafeData, SafeString

__all__ = ["SafeData", "SafeString", "mark_safe"]


@cython.ccall
def mark_safe(s):
    """Mark a string as safe for HTML output."""
    if hasattr(s, "__html__"):
        return s
    return SafeString(s)
