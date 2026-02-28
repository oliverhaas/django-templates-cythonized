"""
Parser and utilities for the smart 'if' tag
"""

import cython
from cython.cimports.django_templates_cythonized.context import Context

# Using a simple top down parser, as described here:
# https://11l-lang.org/archive/simple-top-down-parsing/
# 'led' = left denotation
# 'nud' = null denotation
# 'bp' = binding power (left = lbp, right = rbp)

# Op codes for the unified Operator cclass.
OP_OR: cython.int = 0
OP_AND: cython.int = 1
OP_NOT: cython.int = 2
OP_IN: cython.int = 3
OP_NOT_IN: cython.int = 4
OP_IS: cython.int = 5
OP_IS_NOT: cython.int = 6
OP_EQ: cython.int = 7
OP_NE: cython.int = 8
OP_GT: cython.int = 9
OP_GE: cython.int = 10
OP_LT: cython.int = 11
OP_LE: cython.int = 12


# TokenBase, Operator, Literal, EndToken are declared as cdef classes
# in smartif.pxd. Do NOT use @cython.cclass or cython.declare() here.

class TokenBase:
    """
    Base class for operators and literals, mainly for debugging and for
    throwing syntax errors.
    """

    if not cython.compiled:
        id = None
        lbp = 0
        first = None
        second = None
        value = None

    @cython.ccall
    def eval(self, context: Context):
        return None

    def nud(self, parser):
        # Null denotation - called in prefix context
        raise parser.error_class(
            "Not expecting '%s' in this position in if tag." % self.id
        )

    def led(self, left, parser):
        # Left denotation - called in infix context
        raise parser.error_class(
            "Not expecting '%s' as infix operator in if tag." % self.id
        )

    def display(self):
        """
        Return what to display in error messages for this node
        """
        return self.id

    def __repr__(self):
        out = [str(x) for x in [self.id, self.first, self.second] if x is not None]
        return "(" + " ".join(out) + ")"


class Operator(TokenBase):
    """Unified operator node replacing all infix/prefix factory classes."""

    if not cython.compiled:
        op_code = 0
        is_prefix = False

    def __init__(self, op_code, lbp, op_id, is_prefix=False):
        self.op_code = op_code
        self.lbp = lbp
        self.id = op_id
        self.is_prefix = is_prefix
        self.first = None
        self.second = None
        self.value = None

    def nud(self, parser):
        if self.is_prefix:
            self.first = parser.expression(self.lbp)
            self.second = None
            return self
        raise parser.error_class(
            "Not expecting '%s' in this position in if tag." % self.id
        )

    def led(self, left, parser):
        if not self.is_prefix:
            self.first = left
            self.second = parser.expression(self.lbp)
            return self
        raise parser.error_class(
            "Not expecting '%s' as infix operator in if tag." % self.id
        )

    @cython.ccall
    def eval(self, context: Context):
        op: cython.int = self.op_code
        try:
            if op == OP_OR:
                left = self.first.eval(context)
                return left if left else self.second.eval(context)
            elif op == OP_AND:
                left = self.first.eval(context)
                return self.second.eval(context) if left else left
            elif op == OP_NOT:
                return not self.first.eval(context)
            elif op == OP_IN:
                return self.first.eval(context) in self.second.eval(context)
            elif op == OP_NOT_IN:
                return self.first.eval(context) not in self.second.eval(context)
            elif op == OP_IS:
                return self.first.eval(context) is self.second.eval(context)
            elif op == OP_IS_NOT:
                return self.first.eval(context) is not self.second.eval(context)
            elif op == OP_EQ:
                return self.first.eval(context) == self.second.eval(context)
            elif op == OP_NE:
                return self.first.eval(context) != self.second.eval(context)
            elif op == OP_GT:
                return self.first.eval(context) > self.second.eval(context)
            elif op == OP_GE:
                return self.first.eval(context) >= self.second.eval(context)
            elif op == OP_LT:
                return self.first.eval(context) < self.second.eval(context)
            elif op == OP_LE:
                return self.first.eval(context) <= self.second.eval(context)
        except Exception:
            return False
        return False


class Literal(TokenBase):
    """
    A basic self-resolvable object similar to a Django template variable.
    """

    # IfParser uses Literal in create_var, but TemplateIfParser overrides
    # create_var so that a proper implementation that actually resolves
    # variables, filters etc. is used.

    def __init__(self, value):
        self.id = "literal"
        self.lbp = 0
        self.value = value
        self.first = None
        self.second = None

    def display(self):
        return repr(self.value)

    def nud(self, parser):
        return self

    @cython.ccall
    def eval(self, context: Context):
        return self.value

    def __repr__(self):
        return "(%s %r)" % (self.id, self.value)


class EndToken(TokenBase):
    def __init__(self):
        self.lbp = 0
        self.id = None
        self.first = None
        self.second = None
        self.value = None

    def nud(self, parser):
        raise parser.error_class("Unexpected end of expression in if tag.")


_end_token = EndToken()


# Operator precedence follows Python.
OPERATORS = {
    "or": lambda: Operator(OP_OR, 6, "or"),
    "and": lambda: Operator(OP_AND, 7, "and"),
    "not": lambda: Operator(OP_NOT, 8, "not", is_prefix=True),
    "in": lambda: Operator(OP_IN, 9, "in"),
    "not in": lambda: Operator(OP_NOT_IN, 9, "not in"),
    "is": lambda: Operator(OP_IS, 10, "is"),
    "is not": lambda: Operator(OP_IS_NOT, 10, "is not"),
    "==": lambda: Operator(OP_EQ, 10, "=="),
    "!=": lambda: Operator(OP_NE, 10, "!="),
    ">": lambda: Operator(OP_GT, 10, ">"),
    ">=": lambda: Operator(OP_GE, 10, ">="),
    "<": lambda: Operator(OP_LT, 10, "<"),
    "<=": lambda: Operator(OP_LE, 10, "<="),
}


class IfParser:
    error_class = ValueError

    def __init__(self, tokens):
        # Turn 'is','not' and 'not','in' into single tokens.
        num_tokens = len(tokens)
        mapped_tokens = []
        i = 0
        while i < num_tokens:
            token = tokens[i]
            if token == "is" and i + 1 < num_tokens and tokens[i + 1] == "not":
                token = "is not"
                i += 1  # skip 'not'
            elif token == "not" and i + 1 < num_tokens and tokens[i + 1] == "in":
                token = "not in"
                i += 1  # skip 'in'
            mapped_tokens.append(self.translate_token(token))
            i += 1

        self.tokens = mapped_tokens
        self.pos = 0
        self.current_token = self.next_token()

    def translate_token(self, token):
        try:
            op = OPERATORS[token]
        except (KeyError, TypeError):
            return self.create_var(token)
        else:
            return op()

    def next_token(self):
        if self.pos >= len(self.tokens):
            return _end_token
        else:
            retval = self.tokens[self.pos]
            self.pos += 1
            return retval

    def parse(self):
        retval = self.expression()
        # Check that we have exhausted all the tokens
        if self.current_token is not _end_token:
            raise self.error_class(
                "Unused '%s' at end of if expression." % self.current_token.display()
            )
        return retval

    def expression(self, rbp=0):
        t = self.current_token
        self.current_token = self.next_token()
        left = t.nud(self)
        while rbp < self.current_token.lbp:
            t = self.current_token
            self.current_token = self.next_token()
            left = t.led(left, self)
        return left

    def create_var(self, value):
        return Literal(value)
