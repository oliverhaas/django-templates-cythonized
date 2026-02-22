"""
Cython-accelerated HTML escaping utilities for the template engine.

Provides fast escape() and conditional_escape() with C-level character
scanning that skips html.escape() entirely when no special chars are present.
"""

import cython
import html as _html

from django.utils.safestring import SafeData, SafeString

__all__ = ["conditional_escape", "escape", "format_html"]


@cython.ccall
def escape(text):
    """
    Return the given text with ampersands, quotes and angle brackets encoded
    for use in HTML. Always escape input, even if already marked safe.
    """
    return SafeString(_html.escape(str(text)))


@cython.cfunc
def _fast_escape_str(s: str):
    """
    C-level HTML escape: scan string chars for <, >, &, ", '.
    If none found, return the original string unchanged (zero allocation).
    Only calls html.escape when actually needed.
    """
    c: cython.Py_UCS4
    for c in s:
        if c == 60 or c == 62 or c == 38 or c == 34 or c == 39:
            return _html.escape(s)
    return s


@cython.ccall
def conditional_escape(text):
    """
    Similar to escape(), except that it doesn't operate on pre-escaped strings.

    Uses C-level character scanning to skip html.escape() entirely when
    the string contains no HTML-special characters (the common case for
    template variables like names, numbers, etc.).
    """
    if isinstance(text, SafeData):
        return text
    if hasattr(text, "__html__"):
        return text.__html__()
    return _fast_escape_str(str(text))


def format_html(format_string, *args, **kwargs):
    """
    Similar to str.format, but pass all arguments through conditional_escape(),
    and call mark_safe() on the result. This function should be used instead
    of str.format or % interpolation to build up small HTML fragments.
    """
    args_safe = [conditional_escape(arg) for arg in args]
    kwargs_safe = {k: conditional_escape(v) for k, v in kwargs.items()}
    return SafeString(format_string.format(*args_safe, **kwargs_safe))
