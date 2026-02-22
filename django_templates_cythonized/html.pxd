# C-level declarations for cross-module access to escape/conditional_escape.

cdef _fast_escape_str(str s)
cpdef escape(text)
cpdef conditional_escape(text)
