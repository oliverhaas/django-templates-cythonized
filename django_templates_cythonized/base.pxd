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

cdef class VariableNode(Node):
    cdef public object filter_expression
    cpdef render(self, context)
