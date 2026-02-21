"""
Cython-accelerated HTML escaping utilities for the template engine.

Provides fast escape() and conditional_escape() without @keep_lazy
or Promise handling overhead.
"""

import cython
import html as _html

from django.utils.safestring import SafeString

__all__ = ["conditional_escape", "escape"]


@cython.ccall
def escape(text):
    """
    Return the given text with ampersands, quotes and angle brackets encoded
    for use in HTML. Always escape input, even if already marked safe.
    """
    return SafeString(_html.escape(str(text)))


@cython.ccall
def conditional_escape(text):
    """
    Similar to escape(), except that it doesn't operate on pre-escaped strings.

    Relies on the __html__ convention used by Django's SafeData class
    and third-party libraries like markupsafe.
    """
    if hasattr(text, "__html__"):
        return text.__html__()
    return SafeString(_html.escape(str(text)))
