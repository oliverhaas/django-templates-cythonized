"""
Cython-accelerated localization formatting for the template engine.

Full reimplementation of the Django pipeline:
    localize → number_format → numberformat.format

Key optimizations over Django's implementation:
- Single get_language() call per number_format (Django calls it up to 4x)
- Per-language cached format values (DECIMAL_SEPARATOR, NUMBER_GROUPING, THOUSAND_SEPARATOR)
- C-level number formatting (_format_number cfunc)
- Early exit for ints when USE_THOUSAND_SEPARATOR is False (the default)
"""

import cython
import datetime
import decimal

from django.conf import settings
from django.utils.formats import date_format, get_format, time_format
from django.utils.translation import get_language

__all__ = ["localize", "number_format"]

# Cached settings flag: None = not yet checked, True/False = cached value.
_use_thousand_sep: object = None

# Per-language cached format values: lang → (decimal_sep, number_grouping, thousand_sep)
_number_format_cache: dict = {}


@cython.cfunc
def _get_use_thousand_sep():
    """Cache settings.USE_THOUSAND_SEPARATOR (defaults to False in Django)."""
    global _use_thousand_sep
    if _use_thousand_sep is None:
        _use_thousand_sep = bool(settings.USE_THOUSAND_SEPARATOR)
    return _use_thousand_sep


@cython.cfunc
def _get_number_formats(lang):
    """Get cached (decimal_sep, grouping, thousand_sep) for the given language."""
    cached = _number_format_cache.get(lang)
    if cached is not None:
        return cached
    decimal_sep = get_format("DECIMAL_SEPARATOR", lang, use_l10n=True)
    grouping = get_format("NUMBER_GROUPING", lang, use_l10n=True)
    thousand_sep = get_format("THOUSAND_SEPARATOR", lang, use_l10n=True)
    result = (decimal_sep, grouping, thousand_sep)
    _number_format_cache[lang] = result
    return result


@cython.cfunc
def _format_number(number, decimal_sep, decimal_pos, grouping, thousand_sep,
                   use_grouping):
    """
    C-level reimplementation of django.utils.numberformat.format().

    Formats a number as a string using the given decimal separator,
    decimal positions, grouping, and thousand separator.
    """
    if number is None or number == "":
        return str(number) if number is not None else ""

    # Fast path for simple ints (matches Django's own fast path)
    if isinstance(number, int) and not use_grouping and not decimal_pos:
        return str(number)

    sign: str = ""

    # Treat potentially very large/small floats as Decimals.
    if isinstance(number, float) and "e" in str(number).lower():
        number = decimal.Decimal(str(number))

    if isinstance(number, decimal.Decimal):
        if decimal_pos is not None:
            cutoff = decimal.Decimal("0." + "1".rjust(decimal_pos, "0"))
            if abs(number) < cutoff:
                number = decimal.Decimal("0")

        # Format values with more than 200 digits using scientific notation
        # to avoid high memory usage in {:f}.format().
        _, digits, exponent = number.as_tuple()
        if abs(exponent) + len(digits) > 200:
            number_str = "{:e}".format(number)
            coefficient, exp_str = number_str.split("e")
            coefficient = _format_number(
                coefficient, decimal_sep, decimal_pos, grouping,
                thousand_sep, use_grouping,
            )
            return "{}e{}".format(coefficient, exp_str)
        else:
            str_number = "{:f}".format(number)
    else:
        str_number = str(number)

    if str_number[0:1] == "-":
        sign = "-"
        str_number = str_number[1:]

    # Split into integer and decimal parts
    if "." in str_number:
        int_part, dec_part = str_number.split(".")
        if decimal_pos is not None:
            dec_part = dec_part[:decimal_pos]
    else:
        int_part = str_number
        dec_part = ""

    if decimal_pos is not None:
        dec_part += "0" * (decimal_pos - len(dec_part))

    if dec_part:
        dec_part = decimal_sep + dec_part

    # Apply grouping
    if use_grouping:
        try:
            intervals = list(grouping)
        except TypeError:
            intervals = [grouping, 0]
        active_interval = intervals.pop(0)
        int_part_gd: str = ""
        cnt: cython.int = 0
        for digit in int_part[::-1]:
            if cnt and cnt == active_interval:
                if intervals:
                    active_interval = intervals.pop(0) or active_interval
                int_part_gd += thousand_sep[::-1]
                cnt = 0
            int_part_gd += digit
            cnt += 1
        int_part = int_part_gd[::-1]

    return sign + int_part + dec_part


@cython.ccall
def number_format(value, decimal_pos=None, use_l10n=None, force_grouping=False):
    """
    Format a numeric value using localization settings.

    Reimplements django.utils.formats.number_format with:
    - Early exit for ints when USE_THOUSAND_SEPARATOR is False (avoids get_language)
    - Single get_language() call (Django does up to 4 via get_format)
    - Per-language cached format lookups
    """
    if use_l10n is None:
        use_l10n = True

    # Early exit for ints: if no thousand separator and no decimal positioning,
    # we don't need get_language() or any format lookups at all.
    if isinstance(value, int) and not force_grouping and decimal_pos is None:
        if not use_l10n or not _get_use_thousand_sep():
            return str(value)

    # Single get_language call (Django's number_format calls get_format 3x,
    # each of which calls get_language internally)
    lang = get_language() if use_l10n else None
    formats = _get_number_formats(lang)

    use_grouping: cython.bint = bool(use_l10n) and _get_use_thousand_sep()
    use_grouping = use_grouping or bool(force_grouping)
    use_grouping = use_grouping and formats[1] != 0

    return _format_number(
        value, formats[0], decimal_pos, formats[1], formats[2],
        use_grouping,
    )


@cython.ccall
def localize(value, use_l10n=None):
    """
    Check if value is a localizable type and return it formatted as a string
    using current locale format.
    """
    if isinstance(value, str):
        return value
    # int check first (catches bool subclass too) — the most common numeric type.
    # Single isinstance(int) is faster than isinstance((Decimal, float, int)) tuple.
    elif isinstance(value, int):
        if isinstance(value, bool):
            return str(value)
        if use_l10n is False:
            return str(value)
        # Inline USE_THOUSAND_SEPARATOR check directly — avoids cfunc call overhead.
        # _use_thousand_sep is a module-level cached value (None on first call).
        global _use_thousand_sep
        uts = _use_thousand_sep
        if uts is None:
            uts = bool(settings.USE_THOUSAND_SEPARATOR)
            _use_thousand_sep = uts
        if not uts:
            return str(value)
        return number_format(value, use_l10n=use_l10n)
    elif isinstance(value, float):
        if use_l10n is False:
            return str(value)
        return number_format(value, use_l10n=use_l10n)
    elif isinstance(value, decimal.Decimal):
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
