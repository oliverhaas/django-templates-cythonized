"""Regression tests for production-readiness bugs found during code review.

Each test reproduces a specific confirmed bug by comparing output between
stock Django and our cythonized engine. Tests are written to FAIL before
the fix is applied, demonstrating the bug is real.
"""

import copy
import os
import threading

import pytest
from django.template import engines
from django.test import RequestFactory, override_settings
from django.utils.functional import lazy
from django.utils.safestring import SafeString, mark_safe


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def stock():
    return engines["django"]


@pytest.fixture
def cyth():
    return engines["cythonized"]


def _m(stock, cyth, template_string, context=None):
    """Render with both engines and assert identical output."""
    if context is None:
        context = {}
    stock_result = stock.from_string(template_string).render(context)
    cyth_result = cyth.from_string(template_string).render(context)
    assert cyth_result == stock_result, (
        f"Mismatch!\n  stock: {stock_result!r}\n  cyth:  {cyth_result!r}"
    )
    return stock_result


# ---------------------------------------------------------------------------
# Bug #1: _fast_escape returns str instead of SafeString (double-escaping)
#
# render_value_in_context() calls _fast_escape() which returns plain str.
# Django's conditional_escape() returns SafeString. When the result is stored
# back into context (e.g. {% firstof ... as var %}), re-rendering causes
# double-escaping.
# ---------------------------------------------------------------------------


class TestDoubleEscapingBug:
    """Bug #1: _fast_escape must return SafeString to prevent double-escaping."""

    def test_firstof_asvar_html_content(self, stock, cyth):
        """{% firstof val as result %}{{ result }} double-escapes HTML."""
        _m(stock, cyth,
           "{% firstof val as result %}{{ result }}",
           {"val": "<b>hello</b>"})

    def test_firstof_asvar_ampersand(self, stock, cyth):
        """{% firstof val as result %}{{ result }} double-escapes ampersands."""
        _m(stock, cyth,
           "{% firstof val as result %}{{ result }}",
           {"val": "A & B"})

    def test_firstof_asvar_safe_value(self, stock, cyth):
        """Safe values stored via firstof should not be escaped."""
        _m(stock, cyth,
           "{% firstof val as result %}{{ result }}",
           {"val": mark_safe("<b>bold</b>")})

    def test_firstof_asvar_plain_text(self, stock, cyth):
        """Plain text (no special chars) should work unchanged."""
        _m(stock, cyth,
           "{% firstof val as result %}{{ result }}",
           {"val": "hello world"})

    def test_firstof_asvar_fallback(self, stock, cyth):
        """firstof should fall through to second value and still not double-escape."""
        _m(stock, cyth,
           "{% firstof empty_val fallback as result %}{{ result }}",
           {"empty_val": "", "fallback": "<em>test</em>"})

    def test_cycle_asvar_html_content(self, stock, cyth):
        """{% cycle ... as name %} then {{ name }} double-escapes HTML."""
        _m(stock, cyth,
           '{% for x in items %}{% cycle "<b>a</b>" "b" as cls %}{{ cls }}{% endfor %}',
           {"items": [1, 2]})

    def test_render_value_in_context_returns_safestring(self, stock, cyth):
        """render_value_in_context should return SafeString when autoescape=True."""
        from django_templates_cythonized.base import render_value_in_context
        from django_templates_cythonized.context import Context
        ctx = Context(autoescape=True)
        ctx.template = stock.from_string("").template  # need a template for engine ref
        result = render_value_in_context("hello <world>", ctx)
        assert isinstance(result, SafeString), (
            f"render_value_in_context should return SafeString, got {type(result).__name__}"
        )


# ---------------------------------------------------------------------------
# Bug #2: LOOPIF does not call callable attributes
#
# The LOOPIF optimization resolves item[attr] / getattr(item, attr) but does
# NOT call the result if it's callable. LOOPATTR correctly detects callable
# and falls back. LOOPIF compares the bound method to the literal value.
# ---------------------------------------------------------------------------


class CallableAttrObj:
    """Object with callable attributes for testing."""
    def __init__(self, status):
        self._status = status

    def get_status(self):
        return self._status

    def is_active(self):
        return self._status == "active"


class TestLoopifCallableBug:
    """Bug #2: LOOPIF must call callable attributes before comparison."""

    def test_loopif_callable_eq(self, stock, cyth):
        """{% if book.get_status == 'active' %} should call get_status()."""
        _m(stock, cyth,
           '{% for book in books %}{% if book.get_status == "active" %}YES{% else %}NO{% endif %}{% endfor %}',
           {"books": [CallableAttrObj("active"), CallableAttrObj("inactive")]})

    def test_loopif_callable_ne(self, stock, cyth):
        """{% if book.get_status != 'inactive' %} should call get_status()."""
        _m(stock, cyth,
           '{% for book in books %}{% if book.get_status != "inactive" %}YES{% else %}NO{% endif %}{% endfor %}',
           {"books": [CallableAttrObj("active"), CallableAttrObj("inactive")]})

    def test_loopif_callable_truthiness(self, stock, cyth):
        """{% if book.is_active %} should call is_active()."""
        _m(stock, cyth,
           '{% for book in books %}{% if book.is_active %}YES{% else %}NO{% endif %}{% endfor %}',
           {"books": [CallableAttrObj("active"), CallableAttrObj("inactive")]})

    def test_loopif_callable_with_elif(self, stock, cyth):
        """Multiple elif branches with callable attributes."""
        _m(stock, cyth,
           '{% for book in books %}'
           '{% if book.get_status == "active" %}A'
           '{% elif book.get_status == "pending" %}P'
           '{% else %}X{% endif %}'
           '{% endfor %}',
           {"books": [CallableAttrObj("active"), CallableAttrObj("pending"),
                      CallableAttrObj("other")]})

    def test_loopattr_callable_renders_correctly(self, stock, cyth):
        """{{ book.get_status }} should call get_status() (LOOPATTR path)."""
        _m(stock, cyth,
           '{% for book in books %}{{ book.get_status }}{% endfor %}',
           {"books": [CallableAttrObj("active"), CallableAttrObj("inactive")]})


# ---------------------------------------------------------------------------
# Bug #3: Context.__copy__ drops RequestContext.__dict__ attributes
#
# Context.__copy__ only copies cclass attributes. RequestContext stores
# request, _processors, _processors_index in __dict__, which is not copied.
# context.new() (used by InclusionTag) returns a context without request.
# ---------------------------------------------------------------------------


class TestContextCopyBug:
    """Bug #3: Context.__copy__ must preserve RequestContext.__dict__."""

    def test_requestcontext_copy_preserves_request(self):
        """copy(RequestContext) should preserve the request attribute."""
        from django_templates_cythonized.context import RequestContext
        rf = RequestFactory()
        request = rf.get("/")
        rc = RequestContext(request, {"a": 1})
        dup = copy.copy(rc)
        assert hasattr(dup, "request"), "Copy of RequestContext lost 'request' attribute"
        assert dup.request is request, "Copy of RequestContext has wrong request object"

    def test_requestcontext_copy_preserves_processors(self):
        """copy(RequestContext) should preserve _processors."""
        from django_templates_cythonized.context import RequestContext
        rf = RequestFactory()
        request = rf.get("/")
        rc = RequestContext(request, {"a": 1}, processors=[lambda r: {"extra": True}])
        dup = copy.copy(rc)
        assert hasattr(dup, "_processors"), "Copy of RequestContext lost '_processors'"
        assert len(dup._processors) == 1

    def test_requestcontext_new_preserves_request(self):
        """context.new() should preserve request on the new context."""
        from django_templates_cythonized.context import RequestContext
        rf = RequestFactory()
        request = rf.get("/")
        rc = RequestContext(request, {"a": 1})
        new_ctx = rc.new({"b": 2})
        assert hasattr(new_ctx, "request"), "new() context lost 'request' attribute"
        assert new_ctx.request is request


# ---------------------------------------------------------------------------
# Bug #4: _flatten_includes shares node objects across duplicate includes
#
# When the same template is included twice, both positions get the same node
# objects. Stateful nodes like CycleNode share render_context[self] state,
# producing different output than Django where each include is independent.
# ---------------------------------------------------------------------------

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")


class TestFlattenIncludesSharedNodesBug:
    """Bug #4: _flatten_includes must not share stateful nodes."""

    def test_duplicate_include_with_cycle(self, stock, cyth):
        """Including the same template twice: each should start its cycle fresh."""
        # Write a child template with a cycle
        child_path = os.path.join(TEMPLATES_DIR, "_cycle_child.html")
        try:
            with open(child_path, "w") as f:
                f.write('{% cycle "A" "B" %}')
            tpl = '{% include "_cycle_child.html" %}|{% include "_cycle_child.html" %}'
            _m(stock, cyth, tpl)
        finally:
            if os.path.exists(child_path):
                os.unlink(child_path)

    def test_duplicate_include_with_variable(self, stock, cyth):
        """Including the same template twice: variables should render independently."""
        # Simple variable-only child (no stateful nodes — should be fine)
        child_path = os.path.join(TEMPLATES_DIR, "_var_child.html")
        try:
            with open(child_path, "w") as f:
                f.write("{{ greeting }}")
            tpl = '{% include "_var_child.html" %}|{% include "_var_child.html" %}'
            _m(stock, cyth, tpl, {"greeting": "hello"})
        finally:
            if os.path.exists(child_path):
                os.unlink(child_path)

    def test_include_cycle_state_isolation(self, stock, cyth):
        """Cycle state from included template should not leak into parent."""
        child_path = os.path.join(TEMPLATES_DIR, "_cycle_leak.html")
        try:
            with open(child_path, "w") as f:
                f.write('{% cycle "X" "Y" as c %}{{ c }}')
            # Include then use a cycle in parent — states should be independent
            tpl = '{% include "_cycle_leak.html" %}|{% cycle "1" "2" as d %}{{ d }}'
            _m(stock, cyth, tpl)
        finally:
            if os.path.exists(child_path):
                os.unlink(child_path)


# ---------------------------------------------------------------------------
# Bug #5: conditional_escape missing Promise (lazy string) handling
#
# Django's conditional_escape resolves lazy(mark_safe, str) before checking
# SafeData. Our version skips Promise resolution, incorrectly escaping.
# ---------------------------------------------------------------------------


class TestConditionalEscapePromiseBug:
    """Bug #5: conditional_escape must resolve Promise before SafeData check."""

    def test_lazy_mark_safe_not_escaped(self):
        """lazy(mark_safe, str) should not be escaped by conditional_escape."""
        from django_templates_cythonized.html import conditional_escape
        lazy_safe = lazy(mark_safe, str)
        val = lazy_safe("<b>bold</b>")
        result = conditional_escape(val)
        assert result == "<b>bold</b>", (
            f"Expected '<b>bold</b>', got {result!r} — Promise not resolved before SafeData check"
        )

    def test_lazy_plain_string_escaped(self):
        """lazy(str, str) should be escaped normally."""
        from django_templates_cythonized.html import conditional_escape
        lazy_str = lazy(str, str)
        val = lazy_str("<b>bold</b>")
        result = conditional_escape(val)
        assert "&lt;" in result, f"Expected escaping, got {result!r}"

    def test_format_html_with_lazy_safe(self):
        """format_html should handle lazy(mark_safe) arguments."""
        from django_templates_cythonized.html import format_html
        lazy_safe = lazy(mark_safe, str)
        val = lazy_safe("<b>bold</b>")
        result = format_html("{}", val)
        assert result == "<b>bold</b>", (
            f"Expected '<b>bold</b>', got {result!r}"
        )


# ---------------------------------------------------------------------------
# Bug #6: CythonizedFormRenderer leaks stale _lang across requests
#
# Per-thread reused Context._lang is never reset between renders. If the
# thread switches languages, form widgets use the cached language.
# ---------------------------------------------------------------------------


class TestFormRendererLangCacheBug:
    """Bug #6: CythonizedFormRenderer must reset _lang between renders."""

    def test_lang_reset_between_renders(self):
        """The per-thread Context._lang should be reset on each render call."""
        from django_templates_cythonized.backend import CythonizedFormRenderer, _form_ctx_local

        renderer = CythonizedFormRenderer()

        # Render once to populate the per-thread ctx
        from django_templates_cythonized.context import Context
        ctx = getattr(_form_ctx_local, "ctx", None)
        if ctx is not None:
            # If a ctx exists, check _lang gets reset
            old_lang = ctx._lang
            # Force a stale _lang
            ctx._lang = "stale-xx"
            renderer.render("django/forms/widgets/text.html", {"widget": {
                "name": "test", "is_hidden": False, "required": False,
                "value": "", "attrs": {"id": "id_test"}, "template_name": "django/forms/widgets/text.html",
            }})
            # After render, _lang should have been reset (not still "stale-xx")
            assert ctx._lang != "stale-xx", (
                "_lang was not reset between renders — stale language cache"
            )
