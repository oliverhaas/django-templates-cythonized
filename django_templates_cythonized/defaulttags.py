"""Default tags used by the template system, available to all templates."""

import cython
import re
import sys
import warnings
from collections import namedtuple
from collections.abc import Iterable, Mapping
from datetime import datetime
from itertools import cycle as itertools_cycle
from itertools import groupby

from django.conf import settings
from django.http import QueryDict
from django.utils import timezone
from django.utils.datastructures import DeferredSubDict
from django.utils.html import format_html
from django.utils.lorem_ipsum import paragraphs, words

from .html import conditional_escape, escape
from .safestring import SafeData, SafeString, mark_safe

from cython.cimports.django_templates_cythonized.base import Node, TextNode, NodeList, VariableNode, FilterExpression, _fast_escape, _render_var_fast, _fe_is_direct_loopvar, _render_var_with_value, _resolve_fe_raw
from cython.cimports.django_templates_cythonized.context import Context
from cython.cimports.django_templates_cythonized.formats import localize, _float_is_str_fast
from cython.cimports.django_templates_cythonized.smartif import Literal, Operator, TokenBase

from .base import (
    BLOCK_TAG_END,
    BLOCK_TAG_START,
    COMMENT_TAG_END,
    COMMENT_TAG_START,
    FILTER_SEPARATOR,
    SINGLE_BRACE_END,
    SINGLE_BRACE_START,
    VARIABLE_ATTRIBUTE_SEPARATOR,
    VARIABLE_TAG_END,
    VARIABLE_TAG_START,
    NodeList,
    PartialTemplate,
    TemplateSyntaxError,
    VariableDoesNotExist,
    _RESOLVE_FALLBACK,
    kwarg_re,
    render_value_in_context,
    token_kwargs,
)
from .context import Context
from .defaultfilters import date
from .library import Library
from .smartif import IfParser, Literal, OP_EQ, OP_NE, OP_GT, OP_GE, OP_LT, OP_LE

register = Library()


@cython.cclass
class AutoEscapeControlNode(Node):
    """Implement the actions of the autoescape tag."""

    setting = cython.declare(cython.bint, visibility='public')
    nodelist = cython.declare(object, visibility='public')

    def __init__(self, setting, nodelist):
        self.setting = setting
        self.nodelist = nodelist

    @cython.ccall
    def render(self, context: Context):
        old_setting = context.autoescape
        context.autoescape = self.setting
        output = self.nodelist.render(context)
        context.autoescape = old_setting
        if self.setting:
            return mark_safe(output)
        else:
            return output


@cython.cclass
class CommentNode(Node):
    child_nodelists = ()

    @cython.ccall
    def render(self, context: Context):
        return ""


@cython.cclass
class CsrfTokenNode(Node):
    child_nodelists = ()

    @cython.ccall
    def render(self, context: Context):
        csrf_token = context.get("csrf_token")
        if csrf_token:
            if csrf_token == "NOTPROVIDED":
                return format_html("")
            else:
                return format_html(
                    '<input type="hidden" name="csrfmiddlewaretoken" value="{}">',
                    csrf_token,
                )
        else:
            # It's very probable that the token is missing because of
            # misconfiguration, so we raise a warning
            if settings.DEBUG:
                warnings.warn(
                    "A {% csrf_token %} was used in a template, but the context "
                    "did not provide the value. This is usually caused by not "
                    "using RequestContext."
                )
            return ""


@cython.cclass
class CycleNode(Node):
    cyclevars = cython.declare(list, visibility='public')
    variable_name = cython.declare(object, visibility='public')
    silent = cython.declare(cython.bint, visibility='public')
    _preresolved = cython.declare(tuple, visibility='public')
    _n = cython.declare(cython.Py_ssize_t, visibility='public')
    _needs_escape = cython.declare(cython.bint, visibility='public')

    def __init__(self, cyclevars, variable_name=None, silent=False):
        self.cyclevars = cyclevars
        self.variable_name = variable_name
        self.silent = silent
        # Pre-resolve literal cycle values for fast path
        self._preresolved = None
        self._n = len(cyclevars)
        if not variable_name and not silent:
            pre = []
            for fe_obj in cyclevars:
                fe: FilterExpression = fe_obj
                if not fe.is_var and len(fe.filters) == 0 and isinstance(fe.var, str):
                    pre.append(fe.var)
                else:
                    break
            if len(pre) == self._n:
                self._preresolved = tuple(pre)
                # Check if any value needs HTML escaping
                self._needs_escape = False
                c: cython.Py_UCS4
                for s in pre:
                    for c in s:
                        if c == 60 or c == 62 or c == 38 or c == 34 or c == 39:
                            self._needs_escape = True
                            break
                    if self._needs_escape:
                        break

    @cython.ccall
    def render(self, context: Context):
        # Fast path: pre-resolved literal strings, no variable_name
        if self._preresolved is not None:
            idx: cython.Py_ssize_t = context.render_context.get(self, 0)
            context.render_context[self] = (idx + 1) % self._n
            value = self._preresolved[idx]
            if context.autoescape and self._needs_escape:
                return escape(value)
            return value
        # General path
        if self not in context.render_context:
            # First time the node is rendered in template
            context.render_context[self] = itertools_cycle(self.cyclevars)
        cycle_iter = context.render_context[self]
        value = next(cycle_iter).resolve(context)
        if self.variable_name:
            context.set_upward(self.variable_name, value)
        if self.silent:
            return ""
        return render_value_in_context(value, context)

    @cython.ccall
    def reset(self, context: Context):
        """
        Reset the cycle iteration back to the beginning.
        """
        if self._preresolved is not None:
            context.render_context[self] = 0
        else:
            context.render_context[self] = itertools_cycle(self.cyclevars)


@cython.cclass
class DebugNode(Node):
    @cython.ccall
    def render(self, context: Context):
        if not settings.DEBUG:
            return ""

        from pprint import pformat

        output = [escape(pformat(val)) for val in context]
        output.append("\n\n")
        output.append(escape(pformat(sys.modules)))
        return "".join(output)


@cython.cclass
class FilterNode(Node):
    filter_expr = cython.declare(object, visibility='public')
    nodelist = cython.declare(object, visibility='public')

    def __init__(self, filter_expr, nodelist):
        self.filter_expr = filter_expr
        self.nodelist = nodelist

    @cython.ccall
    def render(self, context: Context):
        output = self.nodelist.render(context)
        # Apply filters.
        with context.push(var=output):
            return self.filter_expr.resolve(context)


@cython.cclass
class FirstOfNode(Node):
    vars = cython.declare(list, visibility='public')
    asvar = cython.declare(object, visibility='public')

    def __init__(self, variables, asvar=None):
        self.vars = variables
        self.asvar = asvar

    @cython.ccall
    def render(self, context: Context):
        first = ""
        for var in self.vars:
            value = var.resolve(context, ignore_failures=True)
            if value:
                first = render_value_in_context(value, context)
                break
        if self.asvar:
            context[self.asvar] = first
            return ""
        return first


@cython.cclass
class CForloopContext:
    """C-level forloop struct. Stores only (i, length) as C ints and computes
    counter/revcounter/first/last on demand via __getitem__. Replaces the
    plain dict that Django writes 6 keys to on every loop iteration."""

    _i = cython.declare(cython.Py_ssize_t, visibility='public')
    _length = cython.declare(cython.Py_ssize_t, visibility='public')
    _parentloop = cython.declare(object, visibility='public')
    _extra = cython.declare(dict, visibility='public')

    def __init__(self, length, parentloop):
        self._i = 0
        self._length = length
        self._parentloop = parentloop
        self._extra = None

    def __getitem__(self, key):
        if key == "counter0":
            return self._i
        if key == "counter":
            return self._i + 1
        if key == "revcounter":
            return self._length - self._i
        if key == "revcounter0":
            return self._length - self._i - 1
        if key == "first":
            return self._i == 0
        if key == "last":
            return self._i == self._length - 1
        if key == "length":
            return self._length
        if key == "parentloop":
            return self._parentloop
        if self._extra is not None:
            return self._extra[key]
        raise KeyError(key)

    def __setitem__(self, key, value):
        if self._extra is None:
            self._extra = {}
        self._extra[key] = value

    def __contains__(self, key):
        if isinstance(key, str) and key in (
            "counter0", "counter", "revcounter", "revcounter0",
            "first", "last", "length", "parentloop",
        ):
            return True
        return self._extra is not None and key in self._extra

    def setdefault(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            self[key] = default
            return default


@cython.cclass
class ForNode(Node):
    loopvars = cython.declare(list, visibility='public')
    sequence = cython.declare(object, visibility='public')
    is_reversed = cython.declare(cython.bint, visibility='public')
    nodelist_loop = cython.declare(object, visibility='public')
    nodelist_empty = cython.declare(object, visibility='public')
    child_nodelists = ("nodelist_loop", "nodelist_empty")

    def __init__(
        self, loopvars, sequence, is_reversed, nodelist_loop, nodelist_empty=None
    ):
        self.loopvars = loopvars
        self.sequence = sequence
        self.is_reversed = is_reversed
        self.nodelist_loop = nodelist_loop
        if nodelist_empty is None:
            self.nodelist_empty = NodeList()
        else:
            self.nodelist_empty = nodelist_empty

    def __repr__(self):
        reversed_text = " reversed" if self.is_reversed else ""
        return "<%s: for %s in %s, tail_len: %d%s>" % (
            self.__class__.__name__,
            ", ".join(self.loopvars),
            self.sequence,
            len(self.nodelist_loop),
            reversed_text,
        )

    @cython.wraparound(False)
    @cython.ccall
    def render(self, context: Context):
        i: cython.int
        j: cython.Py_ssize_t
        idx: cython.Py_ssize_t
        len_values: cython.int
        num_loopvars: cython.int
        num_nodes: cython.Py_ssize_t
        unpack: cython.bint
        pop_context: cython.bint
        debug: cython.bint
        needs_ctx_write: cython.bint

        if "forloop" in context:
            parentloop = context["forloop"]
        else:
            parentloop = {}
        # Inline context.push() — plain dict append avoids ContextDict overhead.
        context.dicts.append({})
        try:
            values = self.sequence.resolve(context, ignore_failures=True)
            if values is None:
                values = []
            if not hasattr(values, "__len__"):
                values = list(values)
            len_values = len(values)
            if len_values < 1:
                return self.nodelist_empty.render(context)
            if self.is_reversed:
                values = reversed(values)
            num_loopvars = len(self.loopvars)
            unpack = num_loopvars > 1
            # Pre-extract loop nodes for C-level iteration
            loop_nodes: list = self.nodelist_loop._nodes
            num_nodes = len(loop_nodes)
            # Pre-allocate output list
            nodelist: list = [None] * (len_values * num_nodes)
            idx = 0
            # Check debug once
            tmpl = context.template
            debug = tmpl is not None and tmpl.engine.debug
            # Cache top context dict for fast single-variable assignment
            _dicts = context.dicts
            top: dict = _dicts[len(_dicts) - 1]
            loopvar0 = self.loopvars[0] if not unpack else None

            # Pre-scan loop body: check if we can bypass context writes entirely.
            # Possible when all non-TextNode nodes are simple VariableNodes that
            # directly reference the loop variable (single-segment, no translate,
            # eligible filters). Saves the dict write + dict scan round-trip.
            needs_ctx_write = True
            if not unpack and not debug:
                needs_ctx_write = False
                for j in range(num_nodes):
                    nd: Node = loop_nodes[j]
                    if isinstance(nd, TextNode):
                        continue
                    if isinstance(nd, VariableNode):
                        nd_vnode: VariableNode = nd
                        if _fe_is_direct_loopvar(nd_vnode.filter_expression, loopvar0):
                            continue
                    needs_ctx_write = True
                    break

            # Pre-classify loop body nodes for LOOPATTR optimization.
            # For {{ loopvar.attr }} patterns, resolve item[attr] directly
            # instead of writing to context and scanning back through dicts.
            # Tag codes: 0=TEXT, 1=VAR, 2=LOOPATTR_NOFILTER, 3=LOOPATTR_FILTER,
            #            4=OTHER, 5=LOOPIF
            _ntags: list = None
            _nattrs: list = None
            _ntext: list = None
            if needs_ctx_write and not unpack and not debug:
                _ntags = [4] * num_nodes
                _nattrs = [None] * num_nodes
                _ntext = [None] * num_nodes
                for j in range(num_nodes):
                    _nd: Node = loop_nodes[j]
                    if isinstance(_nd, TextNode):
                        _tnd: TextNode = _nd
                        _ntags[j] = 0
                        _ntext[j] = _tnd.s
                    elif isinstance(_nd, VariableNode):
                        _ntags[j] = 1  # default: regular VAR
                        _vnd: VariableNode = _nd
                        _fec: FilterExpression = _vnd.filter_expression
                        if _fec.is_var:
                            _varc = _fec.var
                            if not _varc.translate:
                                _lkc = _varc.lookups
                                if _lkc is not None and len(_lkc) == 2:
                                    _lkt: tuple = _lkc
                                    if _lkt[0] == loopvar0:
                                        _nf: cython.Py_ssize_t = len(_fec.filters)
                                        if _nf == 0:
                                            _ntags[j] = 2  # LOOPATTR_NOFILTER
                                            _nattrs[j] = _lkt[1]
                                        elif _nf == 1:
                                            _ntags[j] = 3  # LOOPATTR_FILTER
                                            _nattrs[j] = _lkt[1]
                    elif isinstance(_nd, IfNode):
                        # Try to classify IfNode for LOOPIF optimization.
                        # Conditions must be simple loopvar.attr boolean or
                        # loopvar.attr <op> literal comparisons.
                        # Tuple format: (attr, op, rhs, nodelist_or_None, text_or_None)
                        # When text is not None, branch result is pre-computed (single TextNode).
                        _if_nd: IfNode = _nd
                        _conds_nls = _if_nd.conditions_nodelists
                        _if_info: list = []
                        _if_ok: cython.bint = True
                        for _cn in _conds_nls:
                            _cond = _cn[0]
                            _nl = _cn[1]
                            # Pre-extract text for single-TextNode branches
                            _br_text = None
                            _br_nl = _nl
                            _br_nodes: list = _nl._nodes
                            if len(_br_nodes) == 1 and isinstance(_br_nodes[0], TextNode):
                                _br_tnode: TextNode = _br_nodes[0]
                                _br_text = _br_tnode.s
                                _br_nl = None  # don't need NodeList
                            if _cond is None:
                                # else clause — always matches
                                _if_info.append((None, -1, None, _br_nl, _br_text))
                            elif isinstance(_cond, TemplateLiteral):
                                # Simple boolean: {% if book.attr %}
                                _tl: TemplateLiteral = _cond
                                _tl_fe: FilterExpression = _tl.value
                                if _tl_fe.is_var and len(_tl_fe.filters) == 0:
                                    _tl_var = _tl_fe.var
                                    if not _tl_var.translate:
                                        _tl_lk = _tl_var.lookups
                                        if _tl_lk is not None and len(_tl_lk) == 2:
                                            _tl_lkt: tuple = _tl_lk
                                            if _tl_lkt[0] == loopvar0:
                                                _if_info.append((_tl_lkt[1], -1, None, _br_nl, _br_text))
                                                continue
                                _if_ok = False
                                break
                            elif isinstance(_cond, Operator):
                                # Comparison: {% if book.attr == literal %}
                                _op: Operator = _cond
                                _op_code: cython.int = _op.op_code
                                if _op_code < OP_EQ or _op_code > OP_LE:
                                    _if_ok = False
                                    break
                                _op_first: TokenBase = _op.first
                                _op_second: TokenBase = _op.second
                                # First must be TemplateLiteral for loopvar.attr
                                if not isinstance(_op_first, TemplateLiteral):
                                    _if_ok = False
                                    break
                                _lhs_tl: TemplateLiteral = _op_first
                                _lhs_fe: FilterExpression = _lhs_tl.value
                                if not _lhs_fe.is_var or len(_lhs_fe.filters) != 0:
                                    _if_ok = False
                                    break
                                _lhs_var = _lhs_fe.var
                                if _lhs_var.translate:
                                    _if_ok = False
                                    break
                                _lhs_lk = _lhs_var.lookups
                                if _lhs_lk is None or len(_lhs_lk) != 2:
                                    _if_ok = False
                                    break
                                _lhs_lkt: tuple = _lhs_lk
                                if _lhs_lkt[0] != loopvar0:
                                    _if_ok = False
                                    break
                                # Second must be TemplateLiteral with a literal value (no Variable lookup)
                                if not isinstance(_op_second, TemplateLiteral):
                                    _if_ok = False
                                    break
                                _rhs_tl: TemplateLiteral = _op_second
                                _rhs_fe: FilterExpression = _rhs_tl.value
                                if _rhs_fe.is_var:
                                    _rhs_var = _rhs_fe.var
                                    if _rhs_var.lookups is not None:
                                        _if_ok = False
                                        break
                                    _rhs_val = _rhs_var.literal
                                else:
                                    _rhs_val = _rhs_fe.var
                                if len(_rhs_fe.filters) != 0:
                                    _if_ok = False
                                    break
                                _if_info.append((_lhs_lkt[1], _op_code, _rhs_val, _br_nl, _br_text))
                            else:
                                _if_ok = False
                                break
                        if _if_ok and len(_if_info) > 0:
                            # Check if all conditions reference the same attr
                            # (common for {% if x.a == 1 %}{% elif x.a == 2 %}...)
                            # If so, resolve attr once and reuse for all comparisons.
                            _same_attr = None
                            _all_same: cython.bint = True
                            for _ie in _if_info:
                                _ie_attr = _ie[0]
                                if _ie_attr is None:
                                    continue  # else clause
                                if _same_attr is None:
                                    _same_attr = _ie_attr
                                elif _ie_attr != _same_attr:
                                    _all_same = False
                                    break
                            _ntags[j] = 5  # LOOPIF
                            # Store (same_attr_or_None, conditions_list)
                            if _all_same and _same_attr is not None:
                                _nattrs[j] = (_same_attr, _if_info)
                            else:
                                _nattrs[j] = (None, _if_info)

            # Create forloop context. CForloopContext computes
            # counter/revcounter/first/last on demand — no dict writes per iteration.
            loop_ctx: CForloopContext = CForloopContext(len_values, parentloop)
            context["forloop"] = loop_ctx

            if not needs_ctx_write:
                # ULTRA-FAST LOOP: no context writes needed.
                # All non-TextNode nodes are direct loopvar VariableNodes.
                # Pass item value directly via _render_var_with_value, bypassing
                # the dict write + dict scan round-trip entirely.
                for i, item in enumerate(values):
                    loop_ctx._i = i
                    for j in range(num_nodes):
                        inner_node: Node = loop_nodes[j]
                        if isinstance(inner_node, TextNode):
                            inner_tnode: TextNode = inner_node
                            nodelist[idx] = inner_tnode.s
                        else:
                            inner_vnode: VariableNode = inner_node
                            nodelist[idx] = _render_var_with_value(
                                inner_vnode.filter_expression, item, context
                            )
                        idx += 1
            elif _ntags is not None:
                # OPTIMIZED LOOP: pre-classified LOOPATTR dispatch.
                # For {{ book.attr }} patterns, resolve item[attr] directly
                # instead of scanning context dicts via _render_var_fast.
                _ae: cython.bint = context.autoescape
                for i, item in enumerate(values):
                    loop_ctx._i = i
                    top[loopvar0] = item
                    _item_is_dict: cython.bint = type(item) is dict
                    for j in range(num_nodes):
                        _tag: cython.int = _ntags[j]
                        if _tag == 0:  # TextNode
                            nodelist[idx] = _ntext[j]
                        elif _tag == 2:  # LOOPATTR_NOFILTER
                            if _item_is_dict:
                                # Dict items: direct subscript, no try/except
                                _av = item[_nattrs[j]]
                            else:
                                try:
                                    _av = item[_nattrs[j]]
                                except (TypeError, KeyError, IndexError):
                                    try:
                                        _av = getattr(item, _nattrs[j])
                                    except (TypeError, AttributeError):
                                        nodelist[idx] = loop_nodes[j].render(context)
                                        idx += 1
                                        continue
                            if isinstance(_av, str):
                                if _ae:
                                    if isinstance(_av, SafeData):
                                        nodelist[idx] = _av
                                    else:
                                        nodelist[idx] = _fast_escape(_av)
                                else:
                                    nodelist[idx] = _av
                            elif isinstance(_av, int) and not isinstance(_av, bool):
                                nodelist[idx] = str(_av)
                            elif isinstance(_av, float):
                                _lang = context._lang
                                if _lang is None:
                                    from django.utils.translation import get_language
                                    _lang = get_language()
                                    context._lang = _lang
                                if _float_is_str_fast(_lang):
                                    nodelist[idx] = str(_av)
                                else:
                                    nodelist[idx] = localize(
                                        _av, use_l10n=context.use_l10n, lang=_lang
                                    )
                            elif callable(_av):
                                nodelist[idx] = loop_nodes[j].render(context)
                            else:
                                nodelist[idx] = render_value_in_context(_av, context)
                        elif _tag == 3:  # LOOPATTR_FILTER
                            if _item_is_dict:
                                _av = item[_nattrs[j]]
                            else:
                                try:
                                    _av = item[_nattrs[j]]
                                except (TypeError, KeyError, IndexError):
                                    try:
                                        _av = getattr(item, _nattrs[j])
                                    except (TypeError, AttributeError):
                                        nodelist[idx] = loop_nodes[j].render(context)
                                        idx += 1
                                        continue
                            if callable(_av):
                                nodelist[idx] = loop_nodes[j].render(context)
                            else:
                                _rvn: VariableNode = loop_nodes[j]
                                result = _render_var_with_value(
                                    _rvn.filter_expression, _av, context
                                )
                                if result is not None:
                                    nodelist[idx] = result
                                else:
                                    nodelist[idx] = loop_nodes[j].render(context)
                        elif _tag == 5:  # LOOPIF
                            # Inline IfNode condition evaluation for loopvar.attr patterns.
                            # Resolves item[attr] directly instead of going through
                            # condition.eval → TemplateLiteral.eval → _resolve_fe_raw.
                            _if_data = _nattrs[j]
                            _if_same_attr = _if_data[0]
                            _if_info = _if_data[1]
                            _if_matched: cython.bint = False
                            # If all conditions reference same attr, resolve once
                            if _if_same_attr is not None:
                                if _item_is_dict:
                                    _if_val = item[_if_same_attr]
                                else:
                                    try:
                                        _if_val = item[_if_same_attr]
                                    except (TypeError, KeyError, IndexError):
                                        try:
                                            _if_val = getattr(item, _if_same_attr)
                                        except (TypeError, AttributeError):
                                            _if_val = None
                                for _if_entry in _if_info:
                                    _if_op: cython.int = _if_entry[1]
                                    _if_rhs = _if_entry[2]
                                    _if_br_nl = _if_entry[3]
                                    _if_br_text = _if_entry[4]
                                    if _if_entry[0] is None:
                                        # else clause
                                        if _if_br_text is not None:
                                            nodelist[idx] = _if_br_text
                                        else:
                                            nodelist[idx] = _if_br_nl.render(context)
                                        _if_matched = True
                                        break
                                    if _if_op == -1:
                                        if _if_val:
                                            if _if_br_text is not None:
                                                nodelist[idx] = _if_br_text
                                            else:
                                                nodelist[idx] = _if_br_nl.render(context)
                                            _if_matched = True
                                            break
                                    else:
                                        _cmp_ok: cython.bint = False
                                        if _if_op == OP_EQ:
                                            _cmp_ok = _if_val == _if_rhs
                                        elif _if_op == OP_NE:
                                            _cmp_ok = _if_val != _if_rhs
                                        elif _if_op == OP_GT:
                                            _cmp_ok = _if_val > _if_rhs
                                        elif _if_op == OP_GE:
                                            _cmp_ok = _if_val >= _if_rhs
                                        elif _if_op == OP_LT:
                                            _cmp_ok = _if_val < _if_rhs
                                        elif _if_op == OP_LE:
                                            _cmp_ok = _if_val <= _if_rhs
                                        if _cmp_ok:
                                            if _if_br_text is not None:
                                                nodelist[idx] = _if_br_text
                                            else:
                                                nodelist[idx] = _if_br_nl.render(context)
                                            _if_matched = True
                                            break
                            else:
                                # Different attrs per condition — resolve each
                                for _if_entry in _if_info:
                                    _if_attr = _if_entry[0]
                                    _if_op = _if_entry[1]
                                    _if_rhs = _if_entry[2]
                                    _if_br_nl = _if_entry[3]
                                    _if_br_text = _if_entry[4]
                                    if _if_attr is None:
                                        if _if_br_text is not None:
                                            nodelist[idx] = _if_br_text
                                        else:
                                            nodelist[idx] = _if_br_nl.render(context)
                                        _if_matched = True
                                        break
                                    if _item_is_dict:
                                        _if_val = item[_if_attr]
                                    else:
                                        try:
                                            _if_val = item[_if_attr]
                                        except (TypeError, KeyError, IndexError):
                                            try:
                                                _if_val = getattr(item, _if_attr)
                                            except (TypeError, AttributeError):
                                                _if_val = None
                                    if _if_op == -1:
                                        if _if_val:
                                            if _if_br_text is not None:
                                                nodelist[idx] = _if_br_text
                                            else:
                                                nodelist[idx] = _if_br_nl.render(context)
                                            _if_matched = True
                                            break
                                    else:
                                        _cmp_ok = False
                                        if _if_op == OP_EQ:
                                            _cmp_ok = _if_val == _if_rhs
                                        elif _if_op == OP_NE:
                                            _cmp_ok = _if_val != _if_rhs
                                        elif _if_op == OP_GT:
                                            _cmp_ok = _if_val > _if_rhs
                                        elif _if_op == OP_GE:
                                            _cmp_ok = _if_val >= _if_rhs
                                        elif _if_op == OP_LT:
                                            _cmp_ok = _if_val < _if_rhs
                                        elif _if_op == OP_LE:
                                            _cmp_ok = _if_val <= _if_rhs
                                        if _cmp_ok:
                                            if _if_br_text is not None:
                                                nodelist[idx] = _if_br_text
                                            else:
                                                nodelist[idx] = _if_br_nl.render(context)
                                            _if_matched = True
                                            break
                            if not _if_matched:
                                nodelist[idx] = ""
                        elif _tag == 1:  # VariableNode
                            _rvn2: VariableNode = loop_nodes[j]
                            result = _render_var_fast(
                                _rvn2.filter_expression, context
                            )
                            if result is not None:
                                nodelist[idx] = result
                            else:
                                nodelist[idx] = loop_nodes[j].render(context)
                        else:  # Other node (CycleNode, etc.)
                            nodelist[idx] = loop_nodes[j].render(context)
                        idx += 1
            else:
                for i, item in enumerate(values):
                    loop_ctx._i = i

                    pop_context = False
                    if unpack:
                        # If there are multiple loop variables, unpack the item
                        # into them.
                        try:
                            len_item = len(item)
                        except TypeError:  # not an iterable
                            len_item = 1
                        # Check loop variable count before unpacking
                        if num_loopvars != len_item:
                            raise ValueError(
                                "Need {} values to unpack in for loop; got {}. ".format(
                                    num_loopvars, len_item
                                ),
                            )
                        unpacked_vars = dict(zip(self.loopvars, item))
                        pop_context = True
                        # Inline push: plain dict avoids ContextDict overhead.
                        _dicts.append(unpacked_vars)
                    else:
                        top[loopvar0] = item

                    # Inlined render loop with TextNode + VariableNode fast-paths
                    if not debug:
                        for j in range(num_nodes):
                            inner_node = loop_nodes[j]
                            if isinstance(inner_node, TextNode):
                                inner_tnode = inner_node
                                nodelist[idx] = inner_tnode.s
                            elif isinstance(inner_node, VariableNode):
                                inner_vnode = inner_node
                                result = _render_var_fast(inner_vnode.filter_expression, context)
                                if result is not None:
                                    nodelist[idx] = result
                                else:
                                    nodelist[idx] = inner_node.render(context)
                            else:
                                nodelist[idx] = inner_node.render(context)
                            idx += 1
                    else:
                        for j in range(num_nodes):
                            nodelist[idx] = loop_nodes[j].render_annotated(context)
                            idx += 1

                    if pop_context:
                        _dicts.pop()
        finally:
            context.dicts.pop()
        return SafeString("".join(nodelist))


@cython.cclass
class IfChangedNode(Node):
    nodelist_true = cython.declare(object, visibility='public')
    nodelist_false = cython.declare(object, visibility='public')
    _varlist = cython.declare(tuple, visibility='public')
    child_nodelists = ("nodelist_true", "nodelist_false")

    def __init__(self, nodelist_true, nodelist_false, *varlist):
        self.nodelist_true = nodelist_true
        self.nodelist_false = nodelist_false
        self._varlist = varlist

    @cython.ccall
    def render(self, context: Context):
        # Init state storage
        state_frame = self._get_context_stack_frame(context)
        state_frame.setdefault(self)

        nodelist_true_output = None
        if self._varlist:
            # Consider multiple parameters. This behaves like an OR evaluation
            # of the multiple variables.
            compare_to = [
                var.resolve(context, ignore_failures=True) for var in self._varlist
            ]
        else:
            # The "{% ifchanged %}" syntax (without any variables) compares
            # the rendered output.
            compare_to = nodelist_true_output = self.nodelist_true.render(context)

        if compare_to != state_frame[self]:
            state_frame[self] = compare_to
            # render true block if not already rendered
            return nodelist_true_output or self.nodelist_true.render(context)
        elif self.nodelist_false:
            return self.nodelist_false.render(context)
        return ""

    @cython.ccall
    def _get_context_stack_frame(self, context):
        # The Context object behaves like a stack where each template tag can
        # create a new scope. Find the place where to store the state to detect
        # changes.
        if "forloop" in context:
            # Ifchanged is bound to the local for loop.
            # When there is a loop-in-loop, the state is bound to the inner
            # loop, so it resets when the outer loop continues.
            return context["forloop"]
        else:
            # Using ifchanged outside loops. Effectively this is a no-op
            # because the state is associated with 'self'.
            return context.render_context


@cython.cclass
class IfNode(Node):
    conditions_nodelists = cython.declare(list, visibility='public')

    def __init__(self, conditions_nodelists):
        self.conditions_nodelists = conditions_nodelists

    def __repr__(self):
        return "<%s>" % self.__class__.__name__

    def __iter__(self):
        for _, nodelist in self.conditions_nodelists:
            yield from nodelist

    @property
    def nodelist(self):
        return NodeList(self)

    @cython.ccall
    def render(self, context: Context):
        match: object
        conditions_nodelists = self.conditions_nodelists
        # Fast path: single {% if %} with no elif/else (the common case).
        if len(conditions_nodelists) == 1:
            condition, nodelist = conditions_nodelists[0]
            try:
                match = condition.eval(context)
            except VariableDoesNotExist:
                match = None
            if match:
                return nodelist.render(context)
            return ""

        for condition, nodelist in conditions_nodelists:
            if condition is not None:  # if / elif clause
                try:
                    match = condition.eval(context)
                except VariableDoesNotExist:
                    match = None
            else:  # else clause
                match = True

            if match:
                return nodelist.render(context)

        return ""


@cython.cclass
class LoremNode(Node):
    count = cython.declare(object, visibility='public')
    method = cython.declare(object, visibility='public')
    common = cython.declare(cython.bint, visibility='public')

    def __init__(self, count, method, common):
        self.count = count
        self.method = method
        self.common = common

    @cython.ccall
    def render(self, context: Context):
        try:
            count = int(self.count.resolve(context))
        except (ValueError, TypeError):
            count = 1
        if self.method == "w":
            return words(count, common=self.common)
        else:
            paras = paragraphs(count, common=self.common)
        if self.method == "p":
            paras = ["<p>%s</p>" % p for p in paras]
        return "\n\n".join(paras)


GroupedResult = namedtuple("GroupedResult", ["grouper", "list"])


@cython.cclass
class RegroupNode(Node):
    target = cython.declare(object, visibility='public')
    expression = cython.declare(object, visibility='public')
    var_name = cython.declare(object, visibility='public')

    def __init__(self, target, expression, var_name):
        self.target = target
        self.expression = expression
        self.var_name = var_name

    @cython.ccall
    def resolve_expression(self, obj, context):
        # This method is called for each object in self.target. See regroup()
        # for the reason why we temporarily put the object in the context.
        context[self.var_name] = obj
        return self.expression.resolve(context, ignore_failures=True)

    def _group_objects(self, obj_list, context):
        # Separate method because lambdas (closures) aren't allowed in cpdef.
        return [
            GroupedResult(grouper=key, list=list(val))
            for key, val in groupby(
                obj_list, lambda obj: self.resolve_expression(obj, context)
            )
        ]

    @cython.ccall
    def render(self, context: Context):
        obj_list = self.target.resolve(context, ignore_failures=True)
        if obj_list is None:
            # target variable wasn't found in context; fail silently.
            context[self.var_name] = []
            return ""
        # List of dictionaries in the format:
        # {'grouper': 'key', 'list': [list of contents]}.
        context[self.var_name] = self._group_objects(obj_list, context)
        return ""


@cython.cclass
class LoadNode(Node):
    child_nodelists = ()

    @cython.ccall
    def render(self, context: Context):
        return ""


@cython.cclass
class NowNode(Node):
    format_string = cython.declare(object, visibility='public')
    asvar = cython.declare(object, visibility='public')

    def __init__(self, format_string, asvar=None):
        self.format_string = format_string
        self.asvar = asvar

    @cython.ccall
    def render(self, context: Context):
        tzinfo = timezone.get_current_timezone() if settings.USE_TZ else None
        formatted = date(datetime.now(tz=tzinfo), self.format_string)

        if self.asvar:
            context[self.asvar] = formatted
            return ""
        else:
            return formatted


@cython.cclass
class PartialDefNode(Node):
    partial_name = cython.declare(object, visibility='public')
    inline = cython.declare(cython.bint, visibility='public')
    nodelist = cython.declare(object, visibility='public')

    def __init__(self, partial_name, inline, nodelist):
        self.partial_name = partial_name
        self.inline = inline
        self.nodelist = nodelist

    @cython.ccall
    def render(self, context: Context):
        return self.nodelist.render(context) if self.inline else ""


@cython.cclass
class PartialNode(Node):
    partial_name = cython.declare(object, visibility='public')
    partial_mapping = cython.declare(object, visibility='public')

    def __init__(self, partial_name, partial_mapping):
        # Defer lookup in `partial_mapping` and nodelist to runtime.
        self.partial_name = partial_name
        self.partial_mapping = partial_mapping

    @cython.ccall
    def render(self, context: Context):
        try:
            return self.partial_mapping[self.partial_name].render(context)
        except KeyError:
            raise TemplateSyntaxError(
                f"Partial '{self.partial_name}' is not defined in the current template."
            )


@cython.cclass
class ResetCycleNode(Node):
    node = cython.declare(object, visibility='public')

    def __init__(self, node):
        self.node = node

    @cython.ccall
    def render(self, context: Context):
        self.node.reset(context)
        return ""


@cython.cclass
class SpacelessNode(Node):
    nodelist = cython.declare(object, visibility='public')

    def __init__(self, nodelist):
        self.nodelist = nodelist

    @cython.ccall
    def render(self, context: Context):
        from django.utils.html import strip_spaces_between_tags

        return strip_spaces_between_tags(self.nodelist.render(context).strip())


@cython.cclass
class TemplateTagNode(Node):
    tagtype = cython.declare(object, visibility='public')
    mapping = {
        "openblock": BLOCK_TAG_START,
        "closeblock": BLOCK_TAG_END,
        "openvariable": VARIABLE_TAG_START,
        "closevariable": VARIABLE_TAG_END,
        "openbrace": SINGLE_BRACE_START,
        "closebrace": SINGLE_BRACE_END,
        "opencomment": COMMENT_TAG_START,
        "closecomment": COMMENT_TAG_END,
    }

    def __init__(self, tagtype):
        self.tagtype = tagtype

    @cython.ccall
    def render(self, context: Context):
        return self.mapping.get(self.tagtype, "")


@cython.cclass
class URLNode(Node):
    view_name = cython.declare(object, visibility='public')
    args = cython.declare(list, visibility='public')
    kwargs = cython.declare(dict, visibility='public')
    asvar = cython.declare(object, visibility='public')
    child_nodelists = ()

    def __init__(self, view_name, args, kwargs, asvar):
        self.view_name = view_name
        self.args = args
        self.kwargs = kwargs
        self.asvar = asvar

    def __repr__(self):
        return "<%s view_name='%s' args=%s kwargs=%s as=%s>" % (
            self.__class__.__qualname__,
            self.view_name,
            repr(self.args),
            repr(self.kwargs),
            repr(self.asvar),
        )

    @cython.ccall
    def render(self, context: Context):
        from django.urls import NoReverseMatch, reverse

        args = [arg.resolve(context) for arg in self.args]
        kwargs = {k: v.resolve(context) for k, v in self.kwargs.items()}
        view_name = self.view_name.resolve(context)
        try:
            current_app = context.request.current_app
        except AttributeError:
            try:
                current_app = context.request.resolver_match.namespace
            except AttributeError:
                current_app = None
        # Try to look up the URL. If it fails, raise NoReverseMatch unless the
        # {% url ... as var %} construct is used, in which case return nothing.
        url = ""
        try:
            url = reverse(view_name, args=args, kwargs=kwargs, current_app=current_app)
        except NoReverseMatch:
            if self.asvar is None:
                raise

        if self.asvar:
            context[self.asvar] = url
            return ""
        else:
            if context.autoescape:
                url = conditional_escape(url)
            return url


@cython.cclass
class VerbatimNode(Node):
    content = cython.declare(object, visibility='public')

    def __init__(self, content):
        self.content = content

    @cython.ccall
    def render(self, context: Context):
        return self.content


@cython.cclass
class WidthRatioNode(Node):
    val_expr = cython.declare(object, visibility='public')
    max_expr = cython.declare(object, visibility='public')
    max_width = cython.declare(object, visibility='public')
    asvar = cython.declare(object, visibility='public')

    def __init__(self, val_expr, max_expr, max_width, asvar=None):
        self.val_expr = val_expr
        self.max_expr = max_expr
        self.max_width = max_width
        self.asvar = asvar

    @cython.ccall
    def render(self, context: Context):
        try:
            value = self.val_expr.resolve(context)
            max_value = self.max_expr.resolve(context)
            max_width = int(self.max_width.resolve(context))
        except VariableDoesNotExist:
            return ""
        except (ValueError, TypeError):
            raise TemplateSyntaxError("widthratio final argument must be a number")
        try:
            value = float(value)
            max_value = float(max_value)
            ratio = (value / max_value) * max_width
            result = str(round(ratio))
        except ZeroDivisionError:
            result = "0"
        except (ValueError, TypeError, OverflowError):
            result = ""

        if self.asvar:
            context[self.asvar] = result
            return ""
        else:
            return result


@cython.cclass
class WithNode(Node):
    nodelist = cython.declare(object, visibility='public')
    extra_context = cython.declare(dict, visibility='public')

    def __init__(self, var, name, nodelist, extra_context=None):
        self.nodelist = nodelist
        # var and name are legacy attributes, being left in case they are used
        # by third-party subclasses of this Node.
        self.extra_context = extra_context or {}
        if name:
            self.extra_context[name] = var

    def __repr__(self):
        return "<%s>" % self.__class__.__name__

    @cython.ccall
    def render(self, context: Context):
        values = {key: val.resolve(context) for key, val in self.extra_context.items()}
        with context.push(**values):
            return self.nodelist.render(context)


@register.tag
def autoescape(parser, token):
    """
    Force autoescape behavior for this block.
    """
    # token.split_contents() isn't useful here because this tag doesn't accept
    # variable as arguments.
    args = token.contents.split()
    if len(args) != 2:
        raise TemplateSyntaxError("'autoescape' tag requires exactly one argument.")
    arg = args[1]
    if arg not in ("on", "off"):
        raise TemplateSyntaxError("'autoescape' argument should be 'on' or 'off'")
    nodelist = parser.parse(("endautoescape",))
    parser.delete_first_token()
    return AutoEscapeControlNode((arg == "on"), nodelist)


@register.tag
def comment(parser, token):
    """
    Ignore everything between ``{% comment %}`` and ``{% endcomment %}``.
    """
    parser.skip_past("endcomment")
    return CommentNode()


@register.tag
def cycle(parser, token):
    """
    Cycle among the given strings each time this tag is encountered.

    Within a loop, cycles among the given strings each time through
    the loop::

        {% for o in some_list %}
            <tr class="{% cycle 'row1' 'row2' %}">
                ...
            </tr>
        {% endfor %}

    Outside of a loop, give the values a unique name the first time you call
    it, then use that name each successive time through::

            <tr class="{% cycle 'row1' 'row2' 'row3' as rowcolors %}">...</tr>
            <tr class="{% cycle rowcolors %}">...</tr>
            <tr class="{% cycle rowcolors %}">...</tr>

    You can use any number of values, separated by spaces. Commas can also
    be used to separate values; if a comma is used, the cycle values are
    interpreted as literal strings.

    The optional flag "silent" can be used to prevent the cycle declaration
    from returning any value::

        {% for o in some_list %}
            {% cycle 'row1' 'row2' as rowcolors silent %}
            <tr class="{{ rowcolors }}">{% include "subtemplate.html " %}</tr>
        {% endfor %}
    """
    # Note: This returns the exact same node on each {% cycle name %} call;
    # that is, the node object returned from {% cycle a b c as name %} and the
    # one returned from {% cycle name %} are the exact same object. This
    # shouldn't cause problems (heh), but if it does, now you know.
    #
    # Ugly hack warning: This stuffs the named template dict into parser so
    # that names are only unique within each template (as opposed to using
    # a global variable, which would make cycle names have to be unique across
    # *all* templates.
    #
    # It keeps the last node in the parser to be able to reset it with
    # {% resetcycle %}.

    args = token.split_contents()

    if len(args) < 2:
        raise TemplateSyntaxError("'cycle' tag requires at least two arguments")

    if len(args) == 2:
        # {% cycle foo %} case.
        name = args[1]
        if not hasattr(parser, "_named_cycle_nodes"):
            raise TemplateSyntaxError(
                "No named cycles in template. '%s' is not defined" % name
            )
        if name not in parser._named_cycle_nodes:
            raise TemplateSyntaxError("Named cycle '%s' does not exist" % name)
        return parser._named_cycle_nodes[name]

    as_form = False

    if len(args) > 4:
        # {% cycle ... as foo [silent] %} case.
        if args[-3] == "as":
            if args[-1] != "silent":
                raise TemplateSyntaxError(
                    "Only 'silent' flag is allowed after cycle's name, not '%s'."
                    % args[-1]
                )
            as_form = True
            silent = True
            args = args[:-1]
        elif args[-2] == "as":
            as_form = True
            silent = False

    if as_form:
        name = args[-1]
        values = [parser.compile_filter(arg) for arg in args[1:-2]]
        node = CycleNode(values, name, silent=silent)
        if not hasattr(parser, "_named_cycle_nodes"):
            parser._named_cycle_nodes = {}
        parser._named_cycle_nodes[name] = node
    else:
        values = [parser.compile_filter(arg) for arg in args[1:]]
        node = CycleNode(values)
    parser._last_cycle_node = node
    return node


@register.tag
def csrf_token(parser, token):
    return CsrfTokenNode()


@register.tag
def debug(parser, token):
    """
    Output a whole load of debugging information, including the current
    context and imported modules.

    Sample usage::

        <pre>
            {% debug %}
        </pre>
    """
    return DebugNode()


@register.tag("filter")
def do_filter(parser, token):
    """
    Filter the contents of the block through variable filters.

    Filters can also be piped through each other, and they can have
    arguments -- just like in variable syntax.

    Sample usage::

        {% filter force_escape|lower %}
            This text will be HTML-escaped, and will appear in lowercase.
        {% endfilter %}

    Note that the ``escape`` and ``safe`` filters are not acceptable arguments.
    Instead, use the ``autoescape`` tag to manage autoescaping for blocks of
    template code.
    """
    # token.split_contents() isn't useful here because this tag doesn't accept
    # variable as arguments.
    _, rest = token.contents.split(None, 1)
    filter_expr = parser.compile_filter("var|%s" % (rest))
    for func, unused in filter_expr.filters:
        filter_name = getattr(func, "_filter_name", None)
        if filter_name in ("escape", "safe"):
            raise TemplateSyntaxError(
                '"filter %s" is not permitted. Use the "autoescape" tag instead.'
                % filter_name
            )
    nodelist = parser.parse(("endfilter",))
    parser.delete_first_token()
    return FilterNode(filter_expr, nodelist)


@register.tag
def firstof(parser, token):
    """
    Output the first variable passed that is not False.

    Output nothing if all the passed variables are False.

    Sample usage::

        {% firstof var1 var2 var3 as myvar %}

    This is equivalent to::

        {% if var1 %}
            {{ var1 }}
        {% elif var2 %}
            {{ var2 }}
        {% elif var3 %}
            {{ var3 }}
        {% endif %}

    but much cleaner!

    You can also use a literal string as a fallback value in case all
    passed variables are False::

        {% firstof var1 var2 var3 "fallback value" %}

    If you want to disable auto-escaping of variables you can use::

        {% autoescape off %}
            {% firstof var1 var2 var3 "<strong>fallback value</strong>" %}
        {% autoescape %}

    Or if only some variables should be escaped, you can use::

        {% firstof var1 var2|safe var3 "<strong>fallback</strong>"|safe %}
    """
    bits = token.split_contents()[1:]
    asvar = None
    if not bits:
        raise TemplateSyntaxError("'firstof' statement requires at least one argument")

    if len(bits) >= 2 and bits[-2] == "as":
        asvar = bits[-1]
        bits = bits[:-2]
    return FirstOfNode([parser.compile_filter(bit) for bit in bits], asvar)


@register.tag("for")
def do_for(parser, token):
    """
    Loop over each item in an array.

    For example, to display a list of athletes given ``athlete_list``::

        <ul>
        {% for athlete in athlete_list %}
            <li>{{ athlete.name }}</li>
        {% endfor %}
        </ul>

    You can loop over a list in reverse by using
    ``{% for obj in list reversed %}``.

    You can also unpack multiple values from a two-dimensional array::

        {% for key,value in dict.items %}
            {{ key }}: {{ value }}
        {% endfor %}

    The ``for`` tag can take an optional ``{% empty %}`` clause that will
    be displayed if the given array is empty or could not be found::

        <ul>
          {% for athlete in athlete_list %}
            <li>{{ athlete.name }}</li>
          {% empty %}
            <li>Sorry, no athletes in this list.</li>
          {% endfor %}
        <ul>

    The above is equivalent to -- but shorter, cleaner, and possibly faster
    than -- the following::

        <ul>
          {% if athlete_list %}
            {% for athlete in athlete_list %}
              <li>{{ athlete.name }}</li>
            {% endfor %}
          {% else %}
            <li>Sorry, no athletes in this list.</li>
          {% endif %}
        </ul>

    The for loop sets a number of variables available within the loop:

        =======================  ==============================================
        Variable                 Description
        =======================  ==============================================
        ``forloop.counter``      The current iteration of the loop (1-indexed)
        ``forloop.counter0``     The current iteration of the loop (0-indexed)
        ``forloop.revcounter``   The number of iterations from the end of the
                                 loop (1-indexed)
        ``forloop.revcounter0``  The number of iterations from the end of the
                                 loop (0-indexed)
        ``forloop.first``        True if this is the first time through the
                                 loop
        ``forloop.last``         True if this is the last time through the loop
        ``forloop.parentloop``   For nested loops, this is the loop "above" the
                                 current one
        =======================  ==============================================
    """
    bits = token.split_contents()
    if len(bits) < 4:
        raise TemplateSyntaxError(
            "'for' statements should have at least four words: %s" % token.contents
        )

    is_reversed = bits[-1] == "reversed"
    in_index = -3 if is_reversed else -2
    if bits[in_index] != "in":
        raise TemplateSyntaxError(
            "'for' statements should use the format"
            " 'for x in y': %s" % token.contents
        )

    invalid_chars = frozenset((" ", '"', "'", FILTER_SEPARATOR))
    loopvars = re.split(r" *, *", " ".join(bits[1:in_index]))
    for var in loopvars:
        if not var or not invalid_chars.isdisjoint(var):
            raise TemplateSyntaxError(
                "'for' tag received an invalid argument: %s" % token.contents
            )

    sequence = parser.compile_filter(bits[in_index + 1])
    nodelist_loop = parser.parse(
        (
            "empty",
            "endfor",
        )
    )
    token = parser.next_token()
    if token.contents == "empty":
        nodelist_empty = parser.parse(("endfor",))
        parser.delete_first_token()
    else:
        nodelist_empty = None
    return ForNode(loopvars, sequence, is_reversed, nodelist_loop, nodelist_empty)


@cython.cclass
class TemplateLiteral(Literal):
    text = cython.declare(object, visibility='public')

    def __init__(self, value, text):
        self.value = value
        self.text = text  # for better error messages
        self.id = "literal"
        self.lbp = 0
        self.first = None
        self.second = None

    def display(self):
        return self.text

    @cython.ccall
    def eval(self, context: Context):
        result = _resolve_fe_raw(self.value, context)
        if result is not _RESOLVE_FALLBACK:
            return result
        return self.value.resolve(context, ignore_failures=True)


class TemplateIfParser(IfParser):
    error_class = TemplateSyntaxError

    def __init__(self, parser, *args, **kwargs):
        self.template_parser = parser
        super().__init__(*args, **kwargs)

    def create_var(self, value):
        return TemplateLiteral(self.template_parser.compile_filter(value), value)


@register.tag("if")
def do_if(parser, token):
    """
    Evaluate a variable, and if that variable is "true" (i.e., exists, is not
    empty, and is not a false boolean value), output the contents of the block:

    ::

        {% if athlete_list %}
            Number of athletes: {{ athlete_list|count }}
        {% elif athlete_in_locker_room_list %}
            Athletes should be out of the locker room soon!
        {% else %}
            No athletes.
        {% endif %}

    In the above, if ``athlete_list`` is not empty, the number of athletes will
    be displayed by the ``{{ athlete_list|count }}`` variable.

    The ``if`` tag may take one or several `` {% elif %}`` clauses, as well as
    an ``{% else %}`` clause that will be displayed if all previous conditions
    fail. These clauses are optional.

    ``if`` tags may use ``or``, ``and`` or ``not`` to test a number of
    variables or to negate a given variable::

        {% if not athlete_list %}
            There are no athletes.
        {% endif %}

        {% if athlete_list or coach_list %}
            There are some athletes or some coaches.
        {% endif %}

        {% if athlete_list and coach_list %}
            Both athletes and coaches are available.
        {% endif %}

        {% if not athlete_list or coach_list %}
            There are no athletes, or there are some coaches.
        {% endif %}

        {% if athlete_list and not coach_list %}
            There are some athletes and absolutely no coaches.
        {% endif %}

    Comparison operators are also available, and the use of filters is also
    allowed, for example::

        {% if articles|length >= 5 %}...{% endif %}

    Arguments and operators _must_ have a space between them, so
    ``{% if 1>2 %}`` is not a valid if tag.

    All supported operators are: ``or``, ``and``, ``in``, ``not in``
    ``==``, ``!=``, ``>``, ``>=``, ``<`` and ``<=``.

    Operator precedence follows Python.
    """
    # {% if ... %}
    bits = token.split_contents()[1:]
    condition = TemplateIfParser(parser, bits).parse()
    nodelist = parser.parse(("elif", "else", "endif"))
    conditions_nodelists = [(condition, nodelist)]
    token = parser.next_token()

    # {% elif ... %} (repeatable)
    while token.contents.startswith("elif"):
        bits = token.split_contents()[1:]
        condition = TemplateIfParser(parser, bits).parse()
        nodelist = parser.parse(("elif", "else", "endif"))
        conditions_nodelists.append((condition, nodelist))
        token = parser.next_token()

    # {% else %} (optional)
    if token.contents == "else":
        nodelist = parser.parse(("endif",))
        conditions_nodelists.append((None, nodelist))
        token = parser.next_token()

    # {% endif %}
    if token.contents != "endif":
        raise TemplateSyntaxError(
            'Malformed template tag at line {}: "{}"'.format(
                token.lineno, token.contents
            )
        )

    return IfNode(conditions_nodelists)


@register.tag
def ifchanged(parser, token):
    """
    Check if a value has changed from the last iteration of a loop.

    The ``{% ifchanged %}`` block tag is used within a loop. It has two
    possible uses.

    1. Check its own rendered contents against its previous state and only
       displays the content if it has changed. For example, this displays a
       list of days, only displaying the month if it changes::

            <h1>Archive for {{ year }}</h1>

            {% for date in days %}
                {% ifchanged %}<h3>{{ date|date:"F" }}</h3>{% endifchanged %}
                <a href="{{ date|date:"M/d"|lower }}/">{{ date|date:"j" }}</a>
            {% endfor %}

    2. If given one or more variables, check whether any variable has changed.
       For example, the following shows the date every time it changes, while
       showing the hour if either the hour or the date has changed::

            {% for date in days %}
                {% ifchanged date.date %} {{ date.date }} {% endifchanged %}
                {% ifchanged date.hour date.date %}
                    {{ date.hour }}
                {% endifchanged %}
            {% endfor %}
    """
    bits = token.split_contents()
    nodelist_true = parser.parse(("else", "endifchanged"))
    token = parser.next_token()
    if token.contents == "else":
        nodelist_false = parser.parse(("endifchanged",))
        parser.delete_first_token()
    else:
        nodelist_false = NodeList()
    values = [parser.compile_filter(bit) for bit in bits[1:]]
    return IfChangedNode(nodelist_true, nodelist_false, *values)


def find_library(parser, name):
    try:
        return parser.libraries[name]
    except KeyError:
        raise TemplateSyntaxError(
            "'%s' is not a registered tag library. Must be one of:\n%s"
            % (
                name,
                "\n".join(sorted(parser.libraries)),
            ),
        )


def load_from_library(library, label, names):
    """
    Return a subset of tags and filters from a library.
    """
    subset = Library()
    for name in names:
        found = False
        if name in library.tags:
            found = True
            subset.tags[name] = library.tags[name]
        if name in library.filters:
            found = True
            subset.filters[name] = library.filters[name]
        if found is False:
            raise TemplateSyntaxError(
                "'%s' is not a valid tag or filter in tag library '%s'"
                % (
                    name,
                    label,
                ),
            )
    return subset


@register.tag
def load(parser, token):
    """
    Load a custom template tag library into the parser.

    For example, to load the template tags in
    ``django/templatetags/news/photos.py``::

        {% load news.photos %}

    Can also be used to load an individual tag/filter from
    a library::

        {% load byline from news %}
    """
    # token.split_contents() isn't useful here because this tag doesn't accept
    # variable as arguments.
    bits = token.contents.split()
    if len(bits) >= 4 and bits[-2] == "from":
        # from syntax is used; load individual tags from the library
        name = bits[-1]
        lib = find_library(parser, name)
        subset = load_from_library(lib, name, bits[1:-2])
        parser.add_library(subset)
    else:
        # one or more libraries are specified; load and add them to the parser
        for name in bits[1:]:
            lib = find_library(parser, name)
            parser.add_library(lib)
    return LoadNode()


@register.tag
def lorem(parser, token):
    """
    Create random Latin text useful for providing test data in templates.

    Usage format::

        {% lorem [count] [method] [random] %}

    ``count`` is a number (or variable) containing the number of paragraphs or
    words to generate (default is 1).

    ``method`` is either ``w`` for words, ``p`` for HTML paragraphs, ``b`` for
    plain-text paragraph blocks (default is ``b``).

    ``random`` is the word ``random``, which if given, does not use the common
    paragraph (starting "Lorem ipsum dolor sit amet, consectetuer...").

    Examples:

    * ``{% lorem %}`` outputs the common "lorem ipsum" paragraph
    * ``{% lorem 3 p %}`` outputs the common "lorem ipsum" paragraph
      and two random paragraphs each wrapped in HTML ``<p>`` tags
    * ``{% lorem 2 w random %}`` outputs two random latin words
    """
    bits = list(token.split_contents())
    tagname = bits[0]
    # Random bit
    common = bits[-1] != "random"
    if not common:
        bits.pop()
    # Method bit
    if bits[-1] in ("w", "p", "b"):
        method = bits.pop()
    else:
        method = "b"
    # Count bit
    if len(bits) > 1:
        count = bits.pop()
    else:
        count = "1"
    count = parser.compile_filter(count)
    if len(bits) != 1:
        raise TemplateSyntaxError("Incorrect format for %r tag" % tagname)
    return LoremNode(count, method, common)


@register.tag
def now(parser, token):
    """
    Display the date, formatted according to the given string.

    Use the same format as PHP's ``date()`` function; see https://php.net/date
    for all the possible values.

    Sample usage::

        It is {% now "jS F Y H:i" %}
    """
    bits = token.split_contents()
    asvar = None
    if len(bits) == 4 and bits[-2] == "as":
        asvar = bits[-1]
        bits = bits[:-2]
    if len(bits) != 2:
        raise TemplateSyntaxError("'now' statement takes one argument")
    format_string = bits[1][1:-1]
    return NowNode(format_string, asvar)


@register.tag(name="partialdef")
def partialdef_func(parser, token):
    """
    Declare a partial that can be used in the template.

    Usage::

        {% partialdef partial_name %}
        Content goes here.
        {% endpartialdef %}

    Store the nodelist in the context under the key "partials". It can be
    retrieved using the ``{% partial %}`` tag.

    The optional ``inline`` argument renders the partial's contents
    immediately, at the point where it is defined.
    """
    bits = token.split_contents()
    if len(bits) == 3 and bits[2] == "inline":
        partial_name = bits[1]
        inline = True
    elif len(bits) == 3:
        raise TemplateSyntaxError(
            "The 'inline' argument does not have any parameters; either use "
            "'inline' or remove it completely."
        )
    elif len(bits) == 2:
        partial_name = bits[1]
        inline = False
    elif len(bits) == 1:
        raise TemplateSyntaxError("'partialdef' tag requires a name")
    else:
        raise TemplateSyntaxError("'partialdef' tag takes at most 2 arguments")

    # Parse the content until the end tag.
    valid_endpartials = ("endpartialdef", f"endpartialdef {partial_name}")

    pos_open = getattr(token, "position", None)
    source_start = pos_open[0] if isinstance(pos_open, tuple) else None

    nodelist = parser.parse(valid_endpartials)
    endpartial = parser.next_token()
    if endpartial.contents not in valid_endpartials:
        parser.invalid_block_tag(endpartial, "endpartialdef", valid_endpartials)

    pos_close = getattr(endpartial, "position", None)
    source_end = pos_close[1] if isinstance(pos_close, tuple) else None

    # Store the partial nodelist in the parser.extra_data attribute.
    partials = parser.extra_data.setdefault("partials", {})
    if partial_name in partials:
        raise TemplateSyntaxError(
            f"Partial '{partial_name}' is already defined in the "
            f"'{parser.origin.name}' template."
        )
    partials[partial_name] = PartialTemplate(
        nodelist,
        parser.origin,
        partial_name,
        source_start=source_start,
        source_end=source_end,
    )

    return PartialDefNode(partial_name, inline, nodelist)


@register.tag(name="partial")
def partial_func(parser, token):
    """
    Render a partial previously declared with the ``{% partialdef %}`` tag.

    Usage::

        {% partial partial_name %}
    """
    bits = token.split_contents()
    if len(bits) == 2:
        partial_name = bits[1]
        extra_data = parser.extra_data
        partial_mapping = DeferredSubDict(extra_data, "partials")
        return PartialNode(partial_name, partial_mapping=partial_mapping)
    else:
        raise TemplateSyntaxError("'partial' tag requires a single argument")


@register.simple_tag(name="querystring", takes_context=True)
def querystring(context, *args, **kwargs):
    """
    Build a query string using `args` and `kwargs` arguments.

    This tag constructs a new query string by adding, removing, or modifying
    parameters from the given positional and keyword arguments. Positional
    arguments must be mappings (such as `QueryDict` or `dict`), and
    `request.GET` is used as the starting point if `args` is empty.

    Keyword arguments are treated as an extra, final mapping. These mappings
    are processed sequentially, with later arguments taking precedence.

    A query string prefixed with `?` is returned.

    Raise TemplateSyntaxError if a positional argument is not a mapping or if
    keys are not strings.

    For example::

        {# Set a parameter on top of `request.GET` #}
        {% querystring foo=3 %}

        {# Remove a key from `request.GET` #}
        {% querystring foo=None %}

        {# Use with pagination #}
        {% querystring page=page_obj.next_page_number %}

        {# Use a custom ``QueryDict`` #}
        {% querystring my_query_dict foo=3 %}

        {# Use multiple positional and keyword arguments #}
        {% querystring my_query_dict my_dict foo=3 bar=None %}
    """
    if not args:
        args = [context.request.GET]
    params = QueryDict(mutable=True)
    for d in [*args, kwargs]:
        if not isinstance(d, Mapping):
            raise TemplateSyntaxError(
                "querystring requires mappings for positional arguments (got "
                "%r instead)." % d
            )
        for key, value in d.items():
            if not isinstance(key, str):
                raise TemplateSyntaxError(
                    "querystring requires strings for mapping keys (got %r "
                    "instead)." % key
                )
            if value is None:
                params.pop(key, None)
            elif isinstance(value, Iterable) and not isinstance(value, str):
                params.setlist(key, value)
            else:
                params[key] = value
    query_string = params.urlencode() if params else ""
    return f"?{query_string}"


@register.tag
def regroup(parser, token):
    """
    Regroup a list of alike objects by a common attribute.

    This complex tag is best illustrated by use of an example: say that
    ``musicians`` is a list of ``Musician`` objects that have ``name`` and
    ``instrument`` attributes, and you'd like to display a list that
    looks like:

        * Guitar:
            * Django Reinhardt
            * Emily Remler
        * Piano:
            * Lovie Austin
            * Bud Powell
        * Trumpet:
            * Duke Ellington

    The following snippet of template code would accomplish this dubious task::

        {% regroup musicians by instrument as grouped %}
        <ul>
        {% for group in grouped %}
            <li>{{ group.grouper }}
            <ul>
                {% for musician in group.list %}
                <li>{{ musician.name }}</li>
                {% endfor %}
            </ul>
        {% endfor %}
        </ul>

    As you can see, ``{% regroup %}`` populates a variable with a list of
    objects with ``grouper`` and ``list`` attributes. ``grouper`` contains the
    item that was grouped by; ``list`` contains the list of objects that share
    that ``grouper``. In this case, ``grouper`` would be ``Guitar``, ``Piano``
    and ``Trumpet``, and ``list`` is the list of musicians who play this
    instrument.

    Note that ``{% regroup %}`` does not work when the list to be grouped is
    not sorted by the key you are grouping by! This means that if your list of
    musicians was not sorted by instrument, you'd need to make sure it is
    sorted before using it, i.e.::

        {% regroup musicians|dictsort:"instrument" by instrument as grouped %}
    """
    bits = token.split_contents()
    if len(bits) != 6:
        raise TemplateSyntaxError("'regroup' tag takes five arguments")
    target = parser.compile_filter(bits[1])
    if bits[2] != "by":
        raise TemplateSyntaxError("second argument to 'regroup' tag must be 'by'")
    if bits[4] != "as":
        raise TemplateSyntaxError("next-to-last argument to 'regroup' tag must be 'as'")
    var_name = bits[5]
    # RegroupNode will take each item in 'target', put it in the context under
    # 'var_name', evaluate 'var_name'.'expression' in the current context, and
    # group by the resulting value. After all items are processed, it will
    # save the final result in the context under 'var_name', thus clearing the
    # temporary values. This hack is necessary because the template engine
    # doesn't provide a context-aware equivalent of Python's getattr.
    expression = parser.compile_filter(
        var_name + VARIABLE_ATTRIBUTE_SEPARATOR + bits[3]
    )
    return RegroupNode(target, expression, var_name)


@register.tag
def resetcycle(parser, token):
    """
    Reset a cycle tag.

    If an argument is given, reset the last rendered cycle tag whose name
    matches the argument, else reset the last rendered cycle tag (named or
    unnamed).
    """
    args = token.split_contents()

    if len(args) > 2:
        raise TemplateSyntaxError("%r tag accepts at most one argument." % args[0])

    if len(args) == 2:
        name = args[1]
        try:
            return ResetCycleNode(parser._named_cycle_nodes[name])
        except (AttributeError, KeyError):
            raise TemplateSyntaxError("Named cycle '%s' does not exist." % name)
    try:
        return ResetCycleNode(parser._last_cycle_node)
    except AttributeError:
        raise TemplateSyntaxError("No cycles in template.")


@register.tag
def spaceless(parser, token):
    """
    Remove whitespace between HTML tags, including tab and newline characters.

    Example usage::

        {% spaceless %}
            <p>
                <a href="foo/">Foo</a>
            </p>
        {% endspaceless %}

    This example returns this HTML::

        <p><a href="foo/">Foo</a></p>

    Only space between *tags* is normalized -- not space between tags and text.
    In this example, the space around ``Hello`` isn't stripped::

        {% spaceless %}
            <strong>
                Hello
            </strong>
        {% endspaceless %}
    """
    nodelist = parser.parse(("endspaceless",))
    parser.delete_first_token()
    return SpacelessNode(nodelist)


@register.tag
def templatetag(parser, token):
    """
    Output one of the bits used to compose template tags.

    Since the template system has no concept of "escaping", to display one of
    the bits used in template tags, you must use the ``{% templatetag %}`` tag.

    The argument tells which template bit to output:

        ==================  =======
        Argument            Outputs
        ==================  =======
        ``openblock``       ``{%``
        ``closeblock``      ``%}``
        ``openvariable``    ``{{``
        ``closevariable``   ``}}``
        ``openbrace``       ``{``
        ``closebrace``      ``}``
        ``opencomment``     ``{#``
        ``closecomment``    ``#}``
        ==================  =======
    """
    # token.split_contents() isn't useful here because this tag doesn't accept
    # variable as arguments.
    bits = token.contents.split()
    if len(bits) != 2:
        raise TemplateSyntaxError("'templatetag' statement takes one argument")
    tag = bits[1]
    if tag not in TemplateTagNode.mapping:
        raise TemplateSyntaxError(
            "Invalid templatetag argument: '%s'."
            " Must be one of: %s" % (tag, list(TemplateTagNode.mapping))
        )
    return TemplateTagNode(tag)


@register.tag
def url(parser, token):
    r"""
    Return an absolute URL matching the given view with its parameters.

    This is a way to define links that aren't tied to a particular URL
    configuration::

        {% url "url_name" arg1 arg2 %}

        or

        {% url "url_name" name1=value1 name2=value2 %}

    The first argument is a URL pattern name. Other arguments are
    space-separated values that will be filled in place of positional and
    keyword arguments in the URL. Don't mix positional and keyword arguments.
    All arguments for the URL must be present.

    For example, if you have a view ``app_name.views.client_details`` taking
    the client's id and the corresponding line in a URLconf looks like this::

        path(
            'client/<int:id>/',
            views.client_details,
            name='client-detail-view',
        )

    and this app's URLconf is included into the project's URLconf under some
    path::

        path('clients/', include('app_name.urls'))

    then in a template you can create a link for a certain client like this::

        {% url "client-detail-view" client.id %}

    The URL will look like ``/clients/client/123/``.

    The first argument may also be the name of a template variable that will be
    evaluated to obtain the view name or the URL name, e.g.::

        {% with url_name="client-detail-view" %}
        {% url url_name client.id %}
        {% endwith %}
    """
    bits = token.split_contents()
    if len(bits) < 2:
        raise TemplateSyntaxError(
            "'%s' takes at least one argument, a URL pattern name." % bits[0]
        )
    viewname = parser.compile_filter(bits[1])
    args = []
    kwargs = {}
    asvar = None
    bits = bits[2:]
    if len(bits) >= 2 and bits[-2] == "as":
        asvar = bits[-1]
        bits = bits[:-2]

    for bit in bits:
        match = kwarg_re.match(bit)
        if not match:
            raise TemplateSyntaxError("Malformed arguments to url tag")
        name, value = match.groups()
        if name:
            kwargs[name] = parser.compile_filter(value)
        else:
            args.append(parser.compile_filter(value))

    return URLNode(viewname, args, kwargs, asvar)


@register.tag
def verbatim(parser, token):
    """
    Stop the template engine from rendering the contents of this block tag.

    Usage::

        {% verbatim %}
            {% don't process this %}
        {% endverbatim %}

    You can also designate a specific closing tag block (allowing the
    unrendered use of ``{% endverbatim %}``)::

        {% verbatim myblock %}
            ...
        {% endverbatim myblock %}
    """
    nodelist = parser.parse(("endverbatim",))
    parser.delete_first_token()
    return VerbatimNode(nodelist.render(Context()))


@register.tag
def widthratio(parser, token):
    """
    For creating bar charts and such. Calculate the ratio of a given value to a
    maximum value, and then apply that ratio to a constant.

    For example::

        <img src="bar.png" alt="Bar"
             height="10"
             width="{% widthratio this_value max_value max_width %}">

    If ``this_value`` is 175, ``max_value`` is 200, and ``max_width`` is 100,
    the image in the above example will be 88 pixels wide
    (because 175/200 = .875; .875 * 100 = 87.5 which is rounded up to 88).

    In some cases you might want to capture the result of widthratio in a
    variable. It can be useful for instance in a blocktranslate like this::

        {% widthratio this_value max_value max_width as width %}
        {% blocktranslate %}The width is: {{ width }}{% endblocktranslate %}
    """
    bits = token.split_contents()
    if len(bits) == 4:
        tag, this_value_expr, max_value_expr, max_width = bits
        asvar = None
    elif len(bits) == 6:
        tag, this_value_expr, max_value_expr, max_width, as_, asvar = bits
        if as_ != "as":
            raise TemplateSyntaxError(
                "Invalid syntax in widthratio tag. Expecting 'as' keyword"
            )
    else:
        raise TemplateSyntaxError("widthratio takes at least three arguments")

    return WidthRatioNode(
        parser.compile_filter(this_value_expr),
        parser.compile_filter(max_value_expr),
        parser.compile_filter(max_width),
        asvar=asvar,
    )


@register.tag("with")
def do_with(parser, token):
    """
    Add one or more values to the context (inside of this block) for caching
    and easy access.

    For example::

        {% with total=person.some_sql_method %}
            {{ total }} object{{ total|pluralize }}
        {% endwith %}

    Multiple values can be added to the context::

        {% with foo=1 bar=2 %}
            ...
        {% endwith %}

    The legacy format of ``{% with person.some_sql_method as total %}`` is
    still accepted.
    """
    bits = token.split_contents()
    remaining_bits = bits[1:]
    extra_context = token_kwargs(remaining_bits, parser, support_legacy=True)
    if not extra_context:
        raise TemplateSyntaxError(
            "%r expected at least one variable assignment" % bits[0]
        )
    if remaining_bits:
        raise TemplateSyntaxError(
            "%r received an invalid token: %r" % (bits[0], remaining_bits[0])
        )
    nodelist = parser.parse(("endwith",))
    parser.delete_first_token()
    return WithNode(None, None, nodelist, extra_context=extra_context)
