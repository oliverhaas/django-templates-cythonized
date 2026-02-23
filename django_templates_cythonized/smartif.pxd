# C-level declarations for cross-module cclass inheritance.
# TemplateLiteral in defaulttags.py extends Literal from smartif.py.

cdef class TokenBase:
    cdef public object id
    cdef public int lbp
    cdef public TokenBase first
    cdef public TokenBase second
    cdef public object value
    cpdef eval(self, context)

cdef class Operator(TokenBase):
    cdef public int op_code
    cdef public bint is_prefix
    cpdef eval(self, context)

cdef class Literal(TokenBase):
    cpdef eval(self, context)

cdef class EndToken(TokenBase):
    pass
