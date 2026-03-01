# C-level declarations for cross-module cclass inheritance.
# Other modules (defaulttags.py, loader_tags.py, library.py) need to know
# that Node, TextNode, VariableNode are extension types so their subclasses
# can also be extension types.

from django_templates_cythonized.context cimport Context

cdef class CFilterInfo:
    cdef public object func
    cdef public list args
    cdef public bint expects_localtime
    cdef public bint needs_autoescape
    cdef public bint is_safe

cdef class Node:
    cdef public object token
    cdef public object origin
    cpdef render(self, Context context)
    cpdef render_annotated(self, Context context)
    cpdef get_nodes_by_type(self, nodetype)

cdef class TextNode(Node):
    cdef public str s
    cpdef render(self, Context context)
    cpdef render_annotated(self, Context context)

cdef class NodeList:
    cdef public list _nodes
    cdef public bint contains_nontext
    cpdef render(self, Context context)
    cpdef get_nodes_by_type(self, nodetype)

cdef class Template:
    cdef public object name
    cdef public object origin
    cdef public object engine
    cdef public str source
    cdef public NodeList nodelist
    cdef public dict extra_data
    cpdef _render(self, Context context)
    cpdef render(self, Context context)
    cpdef compile_nodelist(self)

cdef class FilterExpression:
    cdef public object token
    cdef public list filters
    cdef public object var
    cdef public bint is_var
    cdef public int _fast_filter
    cpdef resolve(self, Context context, ignore_failures=*)

cdef class VariableNode(Node):
    cdef public FilterExpression filter_expression
    cpdef render(self, Context context)

cpdef render_value_in_context(object value, Context context)
cdef _resolve_fe_raw(FilterExpression fe, Context context)
cdef _render_var_fast(FilterExpression fe, Context context)
cdef bint _fe_is_direct_loopvar(FilterExpression fe, object loopvar)
cdef _render_var_with_value(FilterExpression fe, object value, Context context)
