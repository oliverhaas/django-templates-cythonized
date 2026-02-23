# C-level declarations for context cclass hierarchy.

cdef class BaseContext:
    cdef public list dicts

cdef class Context(BaseContext):
    cdef public bint autoescape
    cdef public object use_l10n
    cdef public object use_tz
    cdef public object template_name
    cdef public object render_context
    cdef public object template
    cdef public object _lang

cdef class RenderContext(BaseContext):
    cdef public object template
