"""Tests for fast-path form widget HTML generation.

Compares output of CythonizedFormRenderer's direct HTML generators
against stock Django template-based rendering for exact match.
"""

import pytest
from django import forms
from django.forms.renderers import DjangoTemplates
from django.utils.safestring import SafeString

from django_templates_cythonized import backend as _backend
from django_templates_cythonized.backend import CythonizedFormRenderer


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
