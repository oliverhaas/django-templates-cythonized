"""
Cython-accelerated timezone utilities for the template engine.

Provides a fast template_localtime() with inlined is_naive check.
"""

import cython
from datetime import datetime

from django.conf import settings
from django.utils.timezone import localtime

__all__ = ["template_localtime"]


@cython.ccall
def template_localtime(value, use_tz=None):
    """
    Check if value is a datetime and convert it to local time if necessary.

    If use_tz is provided and is not None, that will force the value to
    be converted (or not), overriding the value of settings.USE_TZ.
    """
    should_convert: cython.bint = (
        isinstance(value, datetime)
        and (settings.USE_TZ if use_tz is None else use_tz)
        and value.utcoffset() is not None
        and getattr(value, "convert_to_local_time", True)
    )
    if should_convert:
        return localtime(value)
    return value
