"""Tests for fast-path form widget HTML generation.

Compares output of CythonizedFormRenderer's direct HTML generators
against stock Django template-based rendering for exact match.
Also tests auto-compilation of custom widget templates.
"""

import pytest
from django import forms
from django.forms.renderers import DjangoTemplates
from django.utils.safestring import SafeString

from django_templates_cythonized import backend as _backend
from django_templates_cythonized.backend import CythonizedFormRenderer
from django_templates_cythonized.forms import (
    exec_compiled_template,
    try_compile_widget_template,
)


@pytest.fixture(scope="module")
def stock_renderer():
    return DjangoTemplates()


@pytest.fixture(scope="module")
def fast_renderer():
    return CythonizedFormRenderer()


def _render_both(stock_renderer, fast_renderer, widget, name, value, attrs):
    """Render a widget with both renderers and return (stock, fast) HTML."""
    ctx = widget.get_context(name, value, attrs)
    stock = stock_renderer.render(widget.template_name, ctx).strip()
    fast = fast_renderer.render(widget.template_name, ctx)
    return stock, fast


# --- Input widgets ---


class TestTextInput:
    def test_basic(self, stock_renderer, fast_renderer):
        w = forms.TextInput()
        stock, fast = _render_both(
            stock_renderer,
            fast_renderer,
            w,
            "myfield",
            "hello",
            {"id": "id_myfield"},
        )
        assert fast == stock

    def test_with_required(self, stock_renderer, fast_renderer):
        w = forms.TextInput()
        stock, fast = _render_both(
            stock_renderer,
            fast_renderer,
            w,
            "name",
            "test",
            {"id": "id_name", "required": True},
        )
        assert fast == stock

    def test_none_value(self, stock_renderer, fast_renderer):
        w = forms.TextInput()
        stock, fast = _render_both(
            stock_renderer,
            fast_renderer,
            w,
            "field",
            None,
            {"id": "id_field"},
        )
        assert fast == stock

    def test_empty_string_value(self, stock_renderer, fast_renderer):
        w = forms.TextInput()
        stock, fast = _render_both(
            stock_renderer,
            fast_renderer,
            w,
            "field",
            "",
            {"id": "id_field"},
        )
        assert fast == stock

    def test_html_escaping_in_value(self, stock_renderer, fast_renderer):
        w = forms.TextInput()
        stock, fast = _render_both(
            stock_renderer,
            fast_renderer,
            w,
            "field",
            '<script>alert("xss")</script>',
            {"id": "id_field"},
        )
        assert fast == stock
        assert "&lt;script&gt;" in fast

    def test_html_escaping_in_attr(self, stock_renderer, fast_renderer):
        w = forms.TextInput()
        stock, fast = _render_both(
            stock_renderer,
            fast_renderer,
            w,
            "field",
            "ok",
            {"id": "id_field", "placeholder": 'say "hi" & <bye>'},
        )
        assert fast == stock
        assert "&amp;" in fast
        assert "&lt;" in fast

    def test_no_attrs(self, stock_renderer, fast_renderer):
        w = forms.TextInput(attrs={})
        stock, fast = _render_both(
            stock_renderer,
            fast_renderer,
            w,
            "field",
            "val",
            {},
        )
        assert fast == stock

    def test_safestring_value(self, stock_renderer, fast_renderer):
        w = forms.TextInput()
        stock, fast = _render_both(
            stock_renderer,
            fast_renderer,
            w,
            "field",
            SafeString("<b>bold</b>"),
            {"id": "id_field"},
        )
        assert fast == stock


class TestNumberInput:
    def test_basic(self, stock_renderer, fast_renderer):
        w = forms.NumberInput()
        stock, fast = _render_both(
            stock_renderer,
            fast_renderer,
            w,
            "quantity",
            "5",
            {"id": "id_quantity", "required": True, "min": "1", "max": "99"},
        )
        assert fast == stock


class TestEmailInput:
    def test_basic(self, stock_renderer, fast_renderer):
        w = forms.EmailInput()
        stock, fast = _render_both(
            stock_renderer,
            fast_renderer,
            w,
            "email",
            "a@b.com",
            {"id": "id_email"},
        )
        assert fast == stock


class TestHiddenInput:
    def test_basic(self, stock_renderer, fast_renderer):
        w = forms.HiddenInput()
        stock, fast = _render_both(
            stock_renderer,
            fast_renderer,
            w,
            "csrf",
            "abc123",
            {},
        )
        assert fast == stock


class TestPasswordInput:
    def test_basic(self, stock_renderer, fast_renderer):
        w = forms.PasswordInput()
        stock, fast = _render_both(
            stock_renderer,
            fast_renderer,
            w,
            "pw",
            None,
            {"id": "id_pw"},
        )
        assert fast == stock


class TestCheckboxInput:
    def test_checked(self, stock_renderer, fast_renderer):
        w = forms.CheckboxInput()
        stock, fast = _render_both(
            stock_renderer,
            fast_renderer,
            w,
            "gift_wrap",
            True,
            {"id": "id_gift_wrap"},
        )
        assert fast == stock
        assert "checked" in fast

    def test_unchecked(self, stock_renderer, fast_renderer):
        w = forms.CheckboxInput()
        stock, fast = _render_both(
            stock_renderer,
            fast_renderer,
            w,
            "gift_wrap",
            False,
            {"id": "id_gift_wrap"},
        )
        assert fast == stock
        assert "checked" not in fast

    def test_boolean_false_attr_omitted(self, stock_renderer, fast_renderer):
        """Boolean False attrs should be completely omitted."""
        w = forms.CheckboxInput()
        stock, fast = _render_both(
            stock_renderer,
            fast_renderer,
            w,
            "cb",
            False,
            {"id": "id_cb", "disabled": False},
        )
        assert fast == stock
        assert "disabled" not in fast


# --- Textarea ---


class TestTextarea:
    def test_basic(self, stock_renderer, fast_renderer):
        w = forms.Textarea(attrs={"rows": 3, "placeholder": "Special instructions"})
        stock, fast = _render_both(
            stock_renderer,
            fast_renderer,
            w,
            "notes",
            "some text",
            {"id": "id_notes"},
        )
        assert fast == stock

    def test_empty_value(self, stock_renderer, fast_renderer):
        w = forms.Textarea()
        stock, fast = _render_both(
            stock_renderer,
            fast_renderer,
            w,
            "notes",
            None,
            {"id": "id_notes"},
        )
        assert fast == stock

    def test_html_escaping(self, stock_renderer, fast_renderer):
        w = forms.Textarea()
        stock, fast = _render_both(
            stock_renderer,
            fast_renderer,
            w,
            "notes",
            "<script>alert(1)</script>",
            {"id": "id_notes"},
        )
        assert fast == stock
        assert "&lt;script&gt;" in fast


# --- Select ---


class TestSelect:
    def test_basic(self, stock_renderer, fast_renderer):
        w = forms.Select(
            choices=[
                ("standard", "Standard"),
                ("express", "Express"),
                ("overnight", "Overnight"),
            ],
        )
        stock, fast = _render_both(
            stock_renderer,
            fast_renderer,
            w,
            "shipping",
            "express",
            {"id": "id_shipping"},
        )
        assert fast == stock

    def test_no_selection(self, stock_renderer, fast_renderer):
        w = forms.Select(choices=[("a", "A"), ("b", "B")])
        stock, fast = _render_both(
            stock_renderer,
            fast_renderer,
            w,
            "f",
            "",
            {"id": "id_f"},
        )
        assert fast == stock

    def test_with_optgroups(self, stock_renderer, fast_renderer):
        w = forms.Select(
            choices=[
                ("Domestic", [("standard", "Standard"), ("express", "Express")]),
                ("International", [("intl", "International")]),
            ],
        )
        stock, fast = _render_both(
            stock_renderer,
            fast_renderer,
            w,
            "shipping",
            "express",
            {"id": "id_shipping"},
        )
        assert fast == stock

    def test_html_escaping_in_label(self, stock_renderer, fast_renderer):
        w = forms.Select(choices=[("a", '<b>Bold</b> & "quoted"')])
        stock, fast = _render_both(
            stock_renderer,
            fast_renderer,
            w,
            "f",
            "a",
            {"id": "id_f"},
        )
        assert fast == stock
        assert "&lt;b&gt;" in fast

    def test_html_escaping_in_value(self, stock_renderer, fast_renderer):
        w = forms.Select(choices=[('<evil">', "Evil")])
        stock, fast = _render_both(
            stock_renderer,
            fast_renderer,
            w,
            "f",
            '<evil">',
            {"id": "id_f"},
        )
        assert fast == stock


# --- Full form integration ---


class BookOrderForm(forms.Form):
    quantity = forms.IntegerField(min_value=1, max_value=99, initial=1)
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Special instructions"}),
    )
    gift_wrap = forms.BooleanField(required=False)
    shipping = forms.ChoiceField(
        choices=[
            ("standard", "Standard"),
            ("express", "Express"),
            ("overnight", "Overnight"),
        ],
    )


class TestFullFormIntegration:
    """Render full form fields via BoundField.__str__ and compare."""

    def test_all_fields_match(self, stock_renderer, fast_renderer):
        stock_form = BookOrderForm(
            initial={"quantity": 1},
            prefix="book_1",
            renderer=stock_renderer,
        )
        fast_form = BookOrderForm(
            initial={"quantity": 1},
            prefix="book_1",
            renderer=fast_renderer,
        )
        for field_name in ("quantity", "notes", "gift_wrap", "shipping"):
            stock_html = str(stock_form[field_name])
            fast_html = str(fast_form[field_name])
            assert fast_html == stock_html, (
                f"Field '{field_name}' mismatch:\n  stock: {stock_html!r}\n  fast:  {fast_html!r}"
            )

    def test_form_with_data(self, stock_renderer, fast_renderer):
        """Test with bound form data."""
        data = {
            "book_1-quantity": "3",
            "book_1-notes": "Gift wrap please",
            "book_1-gift_wrap": "on",
            "book_1-shipping": "express",
        }
        stock_form = BookOrderForm(
            data=data,
            prefix="book_1",
            renderer=stock_renderer,
        )
        fast_form = BookOrderForm(
            data=data,
            prefix="book_1",
            renderer=fast_renderer,
        )
        for field_name in ("quantity", "notes", "gift_wrap", "shipping"):
            stock_html = str(stock_form[field_name])
            fast_html = str(fast_form[field_name])
            assert fast_html == stock_html, (
                f"Field '{field_name}' (bound) mismatch:\n  stock: {stock_html!r}\n  fast:  {fast_html!r}"
            )


# --- Template override guard ---


class TestTemplateOverrideGuard:
    """Verify fast path is skipped when a template origin is non-stock."""

    def test_overridden_template_falls_back(self, fast_renderer):
        """Simulate a non-stock origin by poisoning the cache, then verify
        the renderer falls back to template-based rendering."""
        tpl_name = "django/forms/widgets/text.html"

        # Clear any cached result for this template.
        _backend._fast_path_ok.pop(tpl_name, None)

        # Force the cache entry to False (simulates detected override).
        _backend._fast_path_ok[tpl_name] = False

        # Render: should fall back to template engine, still producing valid HTML.
        w = forms.TextInput()
        ctx = w.get_context("field", "hello", {"id": "id_field"})
        result = fast_renderer.render(tpl_name, ctx)
        assert 'name="field"' in result
        assert 'value="hello"' in result

        # Restore: clear the poisoned entry so other tests aren't affected.
        _backend._fast_path_ok.pop(tpl_name, None)


# --- Auto-compilation: unit tests for compiler + interpreter ---


class TestAutoCompilationCompiler:
    """Test the template AST compiler (try_compile_widget_template)."""

    def test_compiles_input_pattern(self, fast_renderer):
        """Stock input.html is compilable."""
        tpl = fast_renderer.engine.get_template("django/forms/widgets/input.html").template
        ops = try_compile_widget_template(tpl)
        assert ops is not None
        assert len(ops) > 0

    def test_compiles_textarea_pattern(self, fast_renderer):
        """Stock textarea.html is compilable."""
        tpl = fast_renderer.engine.get_template("django/forms/widgets/textarea.html").template
        ops = try_compile_widget_template(tpl)
        assert ops is not None

    def test_compiles_select_option(self, fast_renderer):
        """Stock select_option.html is compilable."""
        tpl = fast_renderer.engine.get_template("django/forms/widgets/select_option.html").template
        ops = try_compile_widget_template(tpl)
        assert ops is not None

    def test_compiles_input_option(self, fast_renderer):
        """Stock input_option.html is compilable (has nested IfNode)."""
        tpl = fast_renderer.engine.get_template("django/forms/widgets/input_option.html").template
        ops = try_compile_widget_template(tpl)
        assert ops is not None

    def test_rejects_select(self, fast_renderer):
        """select.html has nested ForNode (optgroups) and is not compilable."""
        tpl = fast_renderer.engine.get_template("django/forms/widgets/select.html").template
        assert try_compile_widget_template(tpl) is None

    def test_rejects_multiple_input(self, fast_renderer):
        """multiple_input.html uses WithNode and is not compilable."""
        tpl = fast_renderer.engine.get_template("django/forms/widgets/multiple_input.html").template
        assert try_compile_widget_template(tpl) is None

    def test_rejects_multiwidget(self, fast_renderer):
        """multiwidget.html uses SpacelessNode and is not compilable."""
        tpl = fast_renderer.engine.get_template("django/forms/widgets/multiwidget.html").template
        assert try_compile_widget_template(tpl) is None


class TestAutoCompilationInterpreter:
    """Test the ops interpreter (exec_compiled_template) against stock Django."""

    def test_input_matches_stock(self, stock_renderer, fast_renderer):
        """Auto-compiled input.html matches stock Django output."""
        tpl = fast_renderer.engine.get_template("django/forms/widgets/input.html").template
        ops = try_compile_widget_template(tpl)

        w = forms.TextInput()
        ctx = w.get_context("field", "hello", {"id": "id_field"})
        assert exec_compiled_template(ops, ctx) == stock_renderer.render(w.template_name, ctx).strip()

    def test_input_none_value(self, stock_renderer, fast_renderer):
        """Auto-compiled input with None value omits value attr."""
        tpl = fast_renderer.engine.get_template("django/forms/widgets/input.html").template
        ops = try_compile_widget_template(tpl)

        w = forms.TextInput()
        ctx = w.get_context("field", None, {"id": "id_field"})
        assert exec_compiled_template(ops, ctx) == stock_renderer.render(w.template_name, ctx).strip()

    def test_input_html_escaping(self, stock_renderer, fast_renderer):
        """Auto-compiled input escapes HTML special chars."""
        tpl = fast_renderer.engine.get_template("django/forms/widgets/input.html").template
        ops = try_compile_widget_template(tpl)

        w = forms.TextInput()
        ctx = w.get_context("f", '<script>alert("xss")</script>', {"id": "id_f"})
        result = exec_compiled_template(ops, ctx)
        assert result == stock_renderer.render(w.template_name, ctx).strip()
        assert "&lt;script&gt;" in result

    def test_input_boolean_attrs(self, stock_renderer, fast_renderer):
        """Auto-compiled input handles boolean True/False attrs."""
        tpl = fast_renderer.engine.get_template("django/forms/widgets/input.html").template
        ops = try_compile_widget_template(tpl)

        w = forms.TextInput()
        ctx = w.get_context("f", "val", {"id": "id_f", "required": True, "disabled": False})
        result = exec_compiled_template(ops, ctx)
        assert result == stock_renderer.render(w.template_name, ctx).strip()
        assert "required" in result
        assert "disabled" not in result

    def test_input_safestring_value(self, stock_renderer, fast_renderer):
        """Auto-compiled input respects SafeString (no double-escaping)."""
        tpl = fast_renderer.engine.get_template("django/forms/widgets/input.html").template
        ops = try_compile_widget_template(tpl)

        w = forms.TextInput()
        ctx = w.get_context("f", SafeString("<b>bold</b>"), {"id": "id_f"})
        assert exec_compiled_template(ops, ctx) == stock_renderer.render(w.template_name, ctx).strip()

    def test_textarea_matches_stock(self, stock_renderer, fast_renderer):
        """Auto-compiled textarea.html matches stock output."""
        tpl = fast_renderer.engine.get_template("django/forms/widgets/textarea.html").template
        ops = try_compile_widget_template(tpl)

        w = forms.Textarea(attrs={"rows": 3})
        ctx = w.get_context("notes", "some text", {"id": "id_notes"})
        assert exec_compiled_template(ops, ctx) == stock_renderer.render(w.template_name, ctx).strip()

    def test_textarea_empty_value(self, stock_renderer, fast_renderer):
        """Auto-compiled textarea with None value."""
        tpl = fast_renderer.engine.get_template("django/forms/widgets/textarea.html").template
        ops = try_compile_widget_template(tpl)

        w = forms.Textarea()
        ctx = w.get_context("notes", None, {"id": "id_notes"})
        assert exec_compiled_template(ops, ctx) == stock_renderer.render(w.template_name, ctx).strip()

    def test_checkbox_checked(self, stock_renderer, fast_renderer):
        """Auto-compiled checkbox input with checked attr."""
        tpl = fast_renderer.engine.get_template("django/forms/widgets/input.html").template
        ops = try_compile_widget_template(tpl)

        w = forms.CheckboxInput()
        ctx = w.get_context("cb", True, {"id": "id_cb"})
        result = exec_compiled_template(ops, ctx)
        assert result == stock_renderer.render("django/forms/widgets/input.html", ctx).strip()

    def test_no_widget_in_context_returns_none(self, fast_renderer):
        """exec_compiled_template returns None if context has no widget key."""
        tpl = fast_renderer.engine.get_template("django/forms/widgets/input.html").template
        ops = try_compile_widget_template(tpl)
        assert exec_compiled_template(ops, {"foo": "bar"}) is None


class TestAutoCompilationIntegration:
    """Test auto-compilation through CythonizedFormRenderer.render()."""

    def test_autocompile_path_used_for_overridden_stock(self, stock_renderer, fast_renderer):
        """When hardcoded path is disabled, auto-compilation kicks in."""
        tpl_name = "django/forms/widgets/text.html"

        # Disable the hardcoded fast path.
        _backend._fast_path_ok[tpl_name] = False
        # Clear any previous compilation.
        _backend._compiled_templates.pop(tpl_name, None)

        try:
            w = forms.TextInput()
            ctx = w.get_context("field", "hello", {"id": "id_field"})
            fast = fast_renderer.render(tpl_name, ctx)
            stock = stock_renderer.render(tpl_name, ctx).strip()
            assert fast == stock

            # The template should now be in the compiled cache.
            assert tpl_name in _backend._compiled_templates
            assert isinstance(_backend._compiled_templates[tpl_name], tuple)
        finally:
            _backend._fast_path_ok.pop(tpl_name, None)
            _backend._compiled_templates.pop(tpl_name, None)

    def test_compiled_cache_hit(self, stock_renderer, fast_renderer):
        """Second render uses cached compiled ops."""
        tpl_name = "django/forms/widgets/text.html"
        _backend._fast_path_ok[tpl_name] = False
        _backend._compiled_templates.pop(tpl_name, None)

        try:
            w = forms.TextInput()
            ctx = w.get_context("f", "v1", {"id": "id_f"})
            fast_renderer.render(tpl_name, ctx)  # First render: compiles.

            ctx2 = w.get_context("f", "v2", {"id": "id_f"})
            fast = fast_renderer.render(tpl_name, ctx2)  # Second render: cached.
            stock = stock_renderer.render(tpl_name, ctx2).strip()
            assert fast == stock
        finally:
            _backend._fast_path_ok.pop(tpl_name, None)
            _backend._compiled_templates.pop(tpl_name, None)

    def test_non_compilable_falls_through(self, fast_renderer):
        """Non-compilable templates fall through to template rendering."""
        tpl_name = "django/forms/widgets/select.html"
        _backend._fast_path_ok[tpl_name] = False
        _backend._compiled_templates.pop(tpl_name, None)

        try:
            w = forms.Select(choices=[("a", "A"), ("b", "B")])
            ctx = w.get_context("f", "a", {"id": "id_f"})
            result = fast_renderer.render(tpl_name, ctx)
            assert "<select" in result
            assert "<option" in result

            # Cached as not-compilable.
            assert _backend._compiled_templates[tpl_name] is False
        finally:
            _backend._fast_path_ok.pop(tpl_name, None)
            _backend._compiled_templates.pop(tpl_name, None)
