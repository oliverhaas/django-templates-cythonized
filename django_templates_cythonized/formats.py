"""
Cython-accelerated localization formatting for the template engine.

Provides a fast localize() with C-level isinstance dispatch.
Delegates to Django's number_format/date_format/time_format for
the slow paths (numbers, dates).
"""

import cython
import datetime
import decimal

from django.utils.formats import date_format, number_format, time_format

__all__ = ["localize"]


@cython.ccall
def localize(value, use_l10n=None):
    """
    Check if value is a localizable type and return it formatted as a string
    using current locale format.
    """
    if isinstance(value, str):
        return value
    elif isinstance(value, bool):
        return str(value)
    elif isinstance(value, (decimal.Decimal, float, int)):
        if use_l10n is False:
            return str(value)
        return number_format(value, use_l10n=use_l10n)
    elif isinstance(value, datetime.datetime):
        return date_format(value, "DATETIME_FORMAT", use_l10n=use_l10n)
    elif isinstance(value, datetime.date):
        return date_format(value, use_l10n=use_l10n)
    elif isinstance(value, datetime.time):
        return time_format(value, use_l10n=use_l10n)
    return value
