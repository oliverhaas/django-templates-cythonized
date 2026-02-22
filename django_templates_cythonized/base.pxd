# C-level declarations for cross-module cclass inheritance.
# Other modules (defaulttags.py, loader_tags.py, library.py) need to know
# that Node, TextNode, VariableNode are extension types so their subclasses
# can also be extension types.

cdef class Node:
    cdef public object token
    cdef public object origin
    cpdef render(self, context)
    cpdef render_annotated(self, context)
    cpdef get_nodes_by_type(self, nodetype)

cdef class TextNode(Node):
    cdef public object s
    cpdef render(self, context)
    cpdef render_annotated(self, context)

cdef class NodeList:
    cdef public list _nodes
    cdef public bint contains_nontext
    cpdef render(self, context)
    cpdef get_nodes_by_type(self, nodetype)

cdef class FilterExpression:
    cdef public object token
    cdef public list filters
    cdef public object var
    cdef public bint is_var
    cdef public int _fast_filter
    cpdef resolve(self, context, ignore_failures=*)

cdef class VariableNode(Node):
    cdef public object filter_expression
    cpdef render(self, context)

cdef _resolve_fe_raw(FilterExpression fe, object context)
cdef _render_var_fast(FilterExpression fe, object context)
cdef bint _fe_is_direct_loopvar(FilterExpression fe, object loopvar)
cdef _render_var_with_value(FilterExpression fe, object value, object context)
