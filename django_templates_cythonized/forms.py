"""
Fast direct HTML generation for common Django form widget templates.

Bypasses template rendering entirely for known widget types by generating
HTML directly in Cython C code. Called from CythonizedFormRenderer.render()
when the template_name matches a known widget template.

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
        parts.append(str(name))
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
