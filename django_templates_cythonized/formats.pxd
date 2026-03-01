# C-level declarations for cross-module access to localize/number_format.

cdef bint _float_is_str_fast(lang)
cpdef localize(value, use_l10n=*, lang=*)
cpdef number_format(value, decimal_pos=*, use_l10n=*, force_grouping=*, lang=*)
