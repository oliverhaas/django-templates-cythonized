"""
Fast direct HTML generation for common Django form widget templates.

Bypasses template rendering entirely for known widget types by generating
HTML directly in Cython C code. Called from CythonizedFormRenderer.render()
when the template_name matches a known widget template.

Two acceleration tiers:
1. Hardcoded cfunc renderers for stock Django widget templates (input, textarea, select).
2. Auto-compiled bytecode for arbitrary simple widget templates — the template AST
   is analyzed once and compiled into a flat ops tuple, then a Cython cfunc interpreter
   executes the ops on every render, bypassing the full template engine.

Replicates the exact output of Django's stock widget templates
(input.html, textarea.html, select.html, select_option.html, attrs.html)
including whitespace, attribute ordering, and HTML escaping behaviour.
"""

import html as _stdlib_html

import cython
from django.utils.safestring import SafeData

# --- Template name sets for dispatch ---

_INPUT_TEMPLATES: set = {
    "django/forms/widgets/input.html",
    "django/forms/widgets/text.html",
    "django/forms/widgets/number.html",
    "django/forms/widgets/email.html",
    "django/forms/widgets/url.html",
    "django/forms/widgets/color.html",
    "django/forms/widgets/search.html",
    "django/forms/widgets/tel.html",
    "django/forms/widgets/password.html",
    "django/forms/widgets/hidden.html",
    "django/forms/widgets/file.html",
    "django/forms/widgets/date.html",
    "django/forms/widgets/datetime.html",
    "django/forms/widgets/time.html",
    "django/forms/widgets/checkbox.html",
}

_TEXTAREA_TEMPLATE: str = "django/forms/widgets/textarea.html"
_SELECT_TEMPLATE: str = "django/forms/widgets/select.html"


# --- Escape helpers ---


@cython.cfunc
def _escape(value) -> str:
    """HTML-escape a value, respecting SafeData. Returns str."""
    s: str = str(value)
    if isinstance(value, SafeData):
        return s
    c: cython.Py_UCS4
    for c in s:
        if c == 60 or c == 62 or c == 38 or c == 34 or c == 39:
            return _stdlib_html.escape(s)
    return s


# --- Attr string builder (replaces attrs.html template) ---


@cython.cfunc
def _build_attrs_html(attrs: dict) -> str:
    """
    Build HTML attribute string from widget attrs dict.
    Matches attrs.html: insertion-order iteration, skip False,
    bare name for True, name="escaped_value" otherwise.
    Each attr prefixed with a space.
    """
    if not attrs:
        return ""
    parts: list = []
    for name, value in attrs.items():
        if value is False:
            continue
        parts.append(" ")
        parts.append(_escape(name))
        if value is not True:
            parts.append('="')
            parts.append(_escape(value))
            parts.append('"')
    return "".join(parts)


# --- Widget HTML generators ---


@cython.cfunc
def _render_input(widget: dict) -> str:
    """
    Direct HTML for <input> widgets.
    Replaces input.html + attrs.html include.
    """
    parts: list = [
        '<input type="',
        _escape(widget["type"]),
        '" name="',
        _escape(widget["name"]),
        '"',
    ]
    value = widget.get("value")
    if value is not None:
        parts.append(' value="')
        parts.append(_escape(value))
        parts.append('"')
    parts.append(_build_attrs_html(widget["attrs"]))
    parts.append(">")
    return "".join(parts)


@cython.cfunc
def _render_textarea(widget: dict) -> str:
    """
    Direct HTML for <textarea> widgets.
    Replaces textarea.html + attrs.html include.
    """
    parts: list = ['<textarea name="', _escape(widget["name"]), '"']
    parts.append(_build_attrs_html(widget["attrs"]))
    parts.append(">\n")
    value = widget.get("value")
    if value:
        parts.append(_escape(value))
    parts.append("</textarea>")
    return "".join(parts)


@cython.cfunc
def _render_select_option(option: dict) -> str:
    """
    Direct HTML for a single <option>.
    Replaces select_option.html + attrs.html include.
    """
    parts: list = ['<option value="', _escape(option["value"]), '"']
    parts.append(_build_attrs_html(option["attrs"]))
    parts.append(">")
    parts.append(_escape(option["label"]))
    parts.append("</option>")
    return "".join(parts)


@cython.cfunc
def _render_select(widget: dict) -> str:
    """
    Direct HTML for <select> widgets.
    Replaces select.html + select_option.html + attrs.html includes.

    Replicates exact whitespace of Django's select.html template:
    - Each option preceded by '\\n  ' (from template line break + indent)
    - Each option followed by '\\n' (from select_option.html trailing newline)
    - Optgroup tags preceded by '\\n  '
    """
    parts: list = ['<select name="', _escape(widget["name"]), '"']
    parts.append(_build_attrs_html(widget["attrs"]))
    parts.append(">")
    optgroups = widget["optgroups"]
    for group in optgroups:
        group_name = group[0]
        group_choices = group[1]
        if group_name:
            parts.append('\n  <optgroup label="')
            parts.append(_escape(group_name))
            parts.append('">')
        for option in group_choices:
            parts.append("\n  ")
            parts.append(_render_select_option(option))
            parts.append("\n")
        if group_name:
            parts.append("\n  </optgroup>")
    parts.append("\n</select>")
    return "".join(parts)


# --- Dispatch ---


@cython.ccall
def is_fast_widget_template(template_name: str) -> cython.bint:
    """Check if template_name is in the fast-path set."""
    return template_name in _INPUT_TEMPLATES or template_name == _TEXTAREA_TEMPLATE or template_name == _SELECT_TEMPLATE


@cython.ccall
def render_widget_fast(template_name: str, context: dict):
    """
    Attempt fast-path HTML generation for known widget templates.
    Returns the HTML string if handled, or None to signal fallback.
    """
    widget = context.get("widget")
    if widget is None:
        return None
    if template_name in _INPUT_TEMPLATES:
        return _render_input(widget)
    if template_name == _TEXTAREA_TEMPLATE:
        return _render_textarea(widget)
    if template_name == _SELECT_TEMPLATE:
        return _render_select(widget)
    return None


# ---------------------------------------------------------------------------
# Auto-compilation: compile arbitrary widget template ASTs into flat ops
# ---------------------------------------------------------------------------

# Op codes for compiled templates.
_OP_TEXT: cython.int = 0  # (0, "text")
_OP_VAR: cython.int = 1  # (1, "key")  -> _escape(widget["key"])
_OP_VAR_STR: cython.int = 2  # (2, "key")  -> _escape(str(widget["key"]))
_OP_VAR2: cython.int = 3  # (3, "k1", "k2")  -> _escape(widget["k1"]["k2"])
_OP_ATTRS: cython.int = 4  # (4,)  -> _build_attrs_html(widget["attrs"])
_OP_IF_NE_NONE: cython.int = 5  # (5, "key", sub_ops)
_OP_IF_TRUTHY: cython.int = 6  # (6, "key", sub_ops)
_OP_IF_TRUTHY2: cython.int = 7  # (7, "k1", "k2", sub_ops)


@cython.cfunc
def _exec_ops(ops: tuple, widget: dict, parts: list):
    """Execute compiled ops against a widget dict, appending to parts."""
    i: cython.int
    n: cython.int = len(ops)
    op: tuple
    code: cython.int
    for i in range(n):
        op = ops[i]
        code = op[0]
        if code == 0:  # TEXT
            parts.append(op[1])
        elif code == 1:  # VAR
            parts.append(_escape(widget[op[1]]))
        elif code == 2:  # VAR_STR
            parts.append(_escape(str(widget[op[1]])))
        elif code == 3:  # VAR2
            parts.append(_escape(widget[op[1]][op[2]]))
        elif code == 4:  # ATTRS
            parts.append(_build_attrs_html(widget["attrs"]))
        elif code == 5:  # IF_NE_NONE
            if widget.get(op[1]) is not None:
                _exec_ops(op[2], widget, parts)
        elif code == 6:  # IF_TRUTHY
            if widget.get(op[1]):
                _exec_ops(op[2], widget, parts)
        elif code == 7:  # IF_TRUTHY2
            _v = widget.get(op[1])
            if _v is not None:
                _v2 = _v.get(op[2]) if isinstance(_v, dict) else getattr(_v, op[2], None)
                if _v2:
                    _exec_ops(op[3], widget, parts)


@cython.ccall
def exec_compiled_template(ops: tuple, context: dict):
    """Execute compiled ops for a widget template. Returns HTML or None.

    The result is stripped to match Django's template rendering output
    (form renderer fallback path does ``tpl.render(ctx).strip()``).
    """
    widget = context.get("widget")
    if widget is None:
        return None
    parts: list = []
    _exec_ops(ops, widget, parts)
    return "".join(parts).strip()


# --- Template AST compiler ---


def _compile_nodelist(nodelist):
    """Compile a nodelist to a list of op tuples. Returns list or None."""
    result = []
    for node in nodelist:
        ops = _compile_node(node)
        if ops is None:
            return None
        result.extend(ops)
    return result


def _compile_node(node):
    """Compile a single AST node to a list of op tuples. Returns list or None."""
    cls_name = type(node).__name__

    if cls_name == "TextNode":
        return [(_OP_TEXT, node.s)]

    if cls_name == "VariableNode":
        return _compile_var_node(node)

    if cls_name == "IfNode":
        return _compile_if_node(node)

    if cls_name == "ForNode":
        return _compile_for_node(node)

    return None  # Unsupported node type


def _compile_var_node(node):
    """Compile a VariableNode accessing widget.xxx or widget.xxx.yyy."""
    fe = node.filter_expression
    var = fe.var
    lookups = getattr(var, "lookups", None)

    if lookups is None or len(lookups) < 2 or lookups[0] != "widget":
        return None

    # Check for stringformat:'s' filter
    has_str_filter = False
    if fe.filters:
        if len(fe.filters) != 1:
            return None
        f = fe.filters[0]
        func = getattr(f, "func", None)
        if func is None or getattr(func, "__name__", None) != "stringformat":
            return None
        args = getattr(f, "args", None)
        if not args or args[0] != (False, "s"):
            return None
        has_str_filter = True

    if len(lookups) == 2:
        key = lookups[1]
        if has_str_filter:
            return [(_OP_VAR_STR, key)]
        return [(_OP_VAR, key)]
    elif len(lookups) == 3:
        if has_str_filter:
            return None  # VAR2 + stringformat not supported
        return [(_OP_VAR2, lookups[1], lookups[2])]

    return None  # Too many segments


def _compile_for_node(node):
    """Compile a ForNode. Only the attrs iteration pattern is supported."""
    if node.loopvars != ["name", "value"]:
        return None
    seq_var = getattr(node.sequence, "var", None)
    seq_lookups = getattr(seq_var, "lookups", None) if seq_var else None
    if seq_lookups == ("widget", "attrs", "items"):
        return [(_OP_ATTRS,)]
    return None


def _compile_if_node(node):
    """Compile an IfNode with a single condition (no elif/else)."""
    if len(node.conditions_nodelists) != 1:
        return None

    cond, nodelist = node.conditions_nodelists[0]

    # Compile the body
    body_ops = _compile_nodelist(nodelist)
    if body_ops is None:
        return None
    body_tuple = tuple(body_ops)

    cond_type = type(cond).__name__

    # Truthiness check: {% if widget.xxx %} or {% if widget.xxx.yyy %}
    if cond_type == "TemplateLiteral":
        fe = getattr(cond, "value", None)
        if fe is None:
            return None
        var = getattr(fe, "var", None)
        lookups = getattr(var, "lookups", None) if var else None
        if lookups is None or lookups[0] != "widget":
            return None
        if len(lookups) == 2:
            return [(_OP_IF_TRUTHY, lookups[1], body_tuple)]
        elif len(lookups) == 3:
            return [(_OP_IF_TRUTHY2, lookups[1], lookups[2], body_tuple)]
        return None

    # Comparison: {% if widget.xxx != None %} or {% if widget.xxx is not None %}
    if cond_type == "Operator":
        cond_id = getattr(cond, "id", None)
        first = getattr(cond, "first", None)
        second = getattr(cond, "second", None)

        if cond_id in ("!=", "is not") and first and second:
            first_fe = getattr(first, "value", None)
            second_fe = getattr(second, "value", None)
            if first_fe and second_fe:
                first_var = getattr(first_fe, "var", None)
                first_lookups = getattr(first_var, "lookups", None) if first_var else None
                second_var = getattr(second_fe, "var", None)
                second_literal = getattr(second_var, "literal", "MISSING") if second_var else "MISSING"
                if (
                    first_lookups
                    and first_lookups[0] == "widget"
                    and len(first_lookups) == 2
                    and second_literal is None
                ):
                    return [(_OP_IF_NE_NONE, first_lookups[1], body_tuple)]

        return None

    return None


@cython.ccall
def try_compile_widget_template(template) -> object:
    """Try to compile a widget template AST into an ops tuple.

    Walks the template's nodelist and converts supported node types
    (TextNode, VariableNode, IfNode, ForNode-attrs) into a flat tuple
    of operation descriptors.

    Returns the ops tuple if successful, or None if the template is
    too complex to compile.
    """
    ops = _compile_nodelist(template.nodelist)
    if ops is None:
        return None
    return tuple(ops)
