"""Comprehensive template rendering compatibility tests.

Modeled after Django's official template_tests and django-rusty-templates.
Every test renders with both stock Django and our cythonized engine,
asserting byte-for-byte identical output.
"""

import copy
import datetime
import os

import pytest
from django.template import engines
from django.test import RequestFactory, override_settings
from django.utils.functional import lazy
from django.utils.safestring import SafeString, mark_safe

from django_templates_cythonized.exceptions import TemplateSyntaxError

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
    assert cyth_result == stock_result, f"Mismatch!\n  stock: {stock_result!r}\n  cyth:  {cyth_result!r}"
    return stock_result


# ---------------------------------------------------------------------------
# Helper classes for variable resolution tests
# ---------------------------------------------------------------------------


class SimpleObj:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class CallableObj:
    def __init__(self, value):
        self.value = value

    def get_value(self):
        return self.value

    def get_upper(self):
        return self.value.upper()

    def __str__(self):
        return str(self.value)


class AltersDataObj:
    def __init__(self):
        self.name = "secret"

    def delete(self):
        return "deleted!"

    delete.alters_data = True

    def safe_method(self):
        return "safe"


class DoNotCallObj:
    def __init__(self):
        self.value = 42

    def compute(self):
        return "computed"

    compute.do_not_call_in_templates = True


class HtmlObj:
    """Object whose __str__ returns HTML."""

    def __init__(self, html):
        self._html = html

    def __str__(self):
        return self._html


class NestedObj:
    def __init__(self):
        self.child = SimpleObj(name="inner", grandchild=SimpleObj(value="deep"))


# ===========================================================================
# 1. VARIABLE RESOLUTION
# ===========================================================================


class TestVariableResolution:
    """Test variable lookups: dict keys, object attributes, list indices, callables."""

    def test_dict_key(self, stock, cyth):
        _m(stock, cyth, "{{ user.name }}", {"user": {"name": "Alice"}})

    def test_object_attribute(self, stock, cyth):
        _m(stock, cyth, "{{ obj.name }}", {"obj": SimpleObj(name="Alice")})

    def test_list_index(self, stock, cyth):
        _m(stock, cyth, "{{ items.0 }}", {"items": ["first", "second", "third"]})

    def test_list_index_last(self, stock, cyth):
        _m(stock, cyth, "{{ items.2 }}", {"items": ["a", "b", "c"]})

    def test_list_index_out_of_range(self, stock, cyth):
        _m(stock, cyth, "{{ items.5 }}", {"items": ["a", "b"]})

    def test_tuple_index(self, stock, cyth):
        _m(stock, cyth, "{{ items.1 }}", {"items": ("x", "y", "z")})

    def test_nested_dict(self, stock, cyth):
        _m(stock, cyth, "{{ a.b.c }}", {"a": {"b": {"c": "deep"}}})

    def test_nested_object(self, stock, cyth):
        _m(stock, cyth, "{{ obj.child.name }}", {"obj": NestedObj()})

    def test_deep_nesting_4_levels(self, stock, cyth):
        """4-segment lookup — tests fallback beyond 3-segment fast path."""
        _m(stock, cyth, "{{ obj.child.grandchild.value }}", {"obj": NestedObj()})

    def test_callable_method(self, stock, cyth):
        """Django auto-calls callables without arguments."""
        _m(stock, cyth, "{{ obj.get_value }}", {"obj": CallableObj("hello")})

    def test_callable_method_chain(self, stock, cyth):
        _m(stock, cyth, "{{ obj.get_upper }}", {"obj": CallableObj("hello")})

    def test_alters_data_blocked(self, stock, cyth):
        """Methods with alters_data=True must not be called."""
        result = _m(stock, cyth, "{{ obj.delete }}", {"obj": AltersDataObj()})
        assert result == ""

    def test_alters_data_safe_method(self, stock, cyth):
        _m(stock, cyth, "{{ obj.safe_method }}", {"obj": AltersDataObj()})

    def test_do_not_call(self, stock, cyth):
        """Methods with do_not_call_in_templates=True are not called."""
        _m(stock, cyth, "{{ obj.compute }}", {"obj": DoNotCallObj()})

    def test_missing_variable(self, stock, cyth):
        result = _m(stock, cyth, "[{{ missing }}]", {})
        assert result == "[]"

    def test_missing_attribute(self, stock, cyth):
        result = _m(stock, cyth, "[{{ obj.nonexistent }}]", {"obj": SimpleObj(name="x")})
        assert result == "[]"

    def test_missing_dict_key(self, stock, cyth):
        result = _m(stock, cyth, "[{{ d.missing }}]", {"d": {"key": "val"}})
        assert result == "[]"

    def test_integer_rendering(self, stock, cyth):
        _m(stock, cyth, "{{ val }}", {"val": 42})

    def test_float_rendering(self, stock, cyth):
        _m(stock, cyth, "{{ val }}", {"val": 3.14})

    def test_boolean_true_rendering(self, stock, cyth):
        _m(stock, cyth, "{{ val }}", {"val": True})

    def test_boolean_false_rendering(self, stock, cyth):
        _m(stock, cyth, "{{ val }}", {"val": False})

    def test_none_rendering(self, stock, cyth):
        _m(stock, cyth, "{{ val }}", {"val": None})

    def test_zero_rendering(self, stock, cyth):
        _m(stock, cyth, "{{ val }}", {"val": 0})

    def test_empty_string_rendering(self, stock, cyth):
        _m(stock, cyth, "[{{ val }}]", {"val": ""})

    def test_empty_list_rendering(self, stock, cyth):
        _m(stock, cyth, "{{ val }}", {"val": []})

    def test_safestring_in_context(self, stock, cyth):
        """SafeString values should not be double-escaped."""
        _m(stock, cyth, "{{ val }}", {"val": SafeString("<b>bold</b>")})

    def test_mark_safe_in_context(self, stock, cyth):
        _m(stock, cyth, "{{ val }}", {"val": mark_safe("<i>italic</i>")})

    def test_object_str(self, stock, cyth):
        """Objects rendered via __str__ should be autoescaped."""
        _m(stock, cyth, "{{ obj }}", {"obj": HtmlObj("<b>html</b>")})

    def test_literal_string(self, stock, cyth):
        """Literal strings in template tags."""
        _m(stock, cyth, "{% with val='hello' %}{{ val }}{% endwith %}", {})

    def test_literal_number(self, stock, cyth):
        _m(stock, cyth, "{% with val=42 %}{{ val }}{% endwith %}", {})

    def test_dict_key_vs_method(self, stock, cyth):
        """Dict keys take precedence over dict methods."""
        _m(stock, cyth, "{{ d.items }}", {"d": {"items": "my_items"}})

    def test_list_in_loop_with_index(self, stock, cyth):
        """List index access inside a for loop."""
        _m(
            stock,
            cyth,
            "{% for row in matrix %}{{ row.0 }},{{ row.1 }}|{% endfor %}",
            {"matrix": [[1, 2], [3, 4], [5, 6]]},
        )


# ===========================================================================
# 2. IF TAG — comprehensive operator coverage
# ===========================================================================


class TestIfTag:
    """Test {% if %} with all operators and edge cases."""

    # --- Basic ---
    def test_if_true(self, stock, cyth):
        _m(stock, cyth, "{% if x %}yes{% endif %}", {"x": True})

    def test_if_false(self, stock, cyth):
        _m(stock, cyth, "{% if x %}yes{% endif %}", {"x": False})

    def test_if_else(self, stock, cyth):
        _m(stock, cyth, "{% if x %}yes{% else %}no{% endif %}", {"x": False})

    def test_if_elif_else(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{% if a %}A{% elif b %}B{% elif c %}C{% else %}D{% endif %}",
            {"a": False, "b": False, "c": True},
        )

    def test_if_multiple_elif(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{% if a %}A{% elif b %}B{% elif c %}C{% elif d %}D{% else %}E{% endif %}",
            {"a": False, "b": False, "c": False, "d": True},
        )

    # --- Comparison operators ---
    def test_if_eq(self, stock, cyth):
        _m(stock, cyth, "{% if x == 5 %}yes{% endif %}", {"x": 5})

    def test_if_neq(self, stock, cyth):
        _m(stock, cyth, "{% if x != 5 %}yes{% endif %}", {"x": 3})

    def test_if_lt(self, stock, cyth):
        _m(stock, cyth, "{% if x < 5 %}yes{% endif %}", {"x": 3})

    def test_if_gt(self, stock, cyth):
        _m(stock, cyth, "{% if x > 5 %}yes{% endif %}", {"x": 10})

    def test_if_lte(self, stock, cyth):
        _m(stock, cyth, "{% if x <= 5 %}yes{% else %}no{% endif %}", {"x": 5})

    def test_if_gte(self, stock, cyth):
        _m(stock, cyth, "{% if x >= 5 %}yes{% else %}no{% endif %}", {"x": 5})

    def test_if_eq_string(self, stock, cyth):
        _m(stock, cyth, '{% if x == "hello" %}yes{% endif %}', {"x": "hello"})

    def test_if_neq_string(self, stock, cyth):
        _m(stock, cyth, '{% if x != "hello" %}yes{% endif %}', {"x": "world"})

    # --- Logical operators ---
    def test_if_and(self, stock, cyth):
        _m(stock, cyth, "{% if a and b %}yes{% else %}no{% endif %}", {"a": True, "b": True})

    def test_if_and_false(self, stock, cyth):
        _m(stock, cyth, "{% if a and b %}yes{% else %}no{% endif %}", {"a": True, "b": False})

    def test_if_or(self, stock, cyth):
        _m(stock, cyth, "{% if a or b %}yes{% else %}no{% endif %}", {"a": False, "b": True})

    def test_if_or_both_false(self, stock, cyth):
        _m(stock, cyth, "{% if a or b %}yes{% else %}no{% endif %}", {"a": False, "b": False})

    def test_if_not(self, stock, cyth):
        _m(stock, cyth, "{% if not x %}yes{% else %}no{% endif %}", {"x": False})

    def test_if_not_true(self, stock, cyth):
        _m(stock, cyth, "{% if not x %}yes{% else %}no{% endif %}", {"x": True})

    def test_if_and_or_precedence(self, stock, cyth):
        """and binds tighter than or: a or b and c == a or (b and c)"""
        _m(stock, cyth, "{% if a or b and c %}yes{% else %}no{% endif %}", {"a": False, "b": True, "c": False})

    def test_if_complex_logic(self, stock, cyth):
        _m(stock, cyth, "{% if a and b or c %}yes{% else %}no{% endif %}", {"a": True, "b": False, "c": True})

    # --- Membership operators ---
    def test_if_in(self, stock, cyth):
        _m(stock, cyth, '{% if "a" in items %}yes{% else %}no{% endif %}', {"items": ["a", "b", "c"]})

    def test_if_in_false(self, stock, cyth):
        _m(stock, cyth, '{% if "z" in items %}yes{% else %}no{% endif %}', {"items": ["a", "b", "c"]})

    def test_if_not_in(self, stock, cyth):
        _m(stock, cyth, '{% if "z" not in items %}yes{% else %}no{% endif %}', {"items": ["a", "b", "c"]})

    def test_if_in_string(self, stock, cyth):
        _m(stock, cyth, '{% if "ell" in word %}yes{% endif %}', {"word": "hello"})

    def test_if_in_dict(self, stock, cyth):
        _m(stock, cyth, '{% if "key" in d %}yes{% endif %}', {"d": {"key": "val"}})

    # --- Identity operators ---
    def test_if_is_none(self, stock, cyth):
        _m(stock, cyth, "{% if x is None %}yes{% else %}no{% endif %}", {"x": None})

    def test_if_is_not_none(self, stock, cyth):
        _m(stock, cyth, "{% if x is not None %}yes{% else %}no{% endif %}", {"x": 42})

    def test_if_is_true(self, stock, cyth):
        _m(stock, cyth, "{% if x is True %}yes{% else %}no{% endif %}", {"x": True})

    def test_if_is_false(self, stock, cyth):
        _m(stock, cyth, "{% if x is False %}yes{% else %}no{% endif %}", {"x": False})

    # --- Filters in conditions ---
    def test_if_length(self, stock, cyth):
        _m(stock, cyth, "{% if items|length > 2 %}many{% else %}few{% endif %}", {"items": [1, 2, 3]})

    def test_if_length_zero(self, stock, cyth):
        _m(stock, cyth, "{% if items|length %}has{% else %}empty{% endif %}", {"items": []})

    def test_if_default(self, stock, cyth):
        _m(stock, cyth, "{% if val|default:'fallback' %}{{ val|default:'fallback' }}{% endif %}", {})

    # --- Undefined variables ---
    def test_if_undefined(self, stock, cyth):
        result = _m(stock, cyth, "{% if missing %}yes{% else %}no{% endif %}", {})
        assert result == "no"

    def test_if_undefined_comparison(self, stock, cyth):
        _m(stock, cyth, "{% if missing == 5 %}yes{% else %}no{% endif %}", {})

    # --- Truthiness ---
    def test_if_zero_is_falsy(self, stock, cyth):
        _m(stock, cyth, "{% if x %}yes{% else %}no{% endif %}", {"x": 0})

    def test_if_empty_string_is_falsy(self, stock, cyth):
        _m(stock, cyth, "{% if x %}yes{% else %}no{% endif %}", {"x": ""})

    def test_if_empty_list_is_falsy(self, stock, cyth):
        _m(stock, cyth, "{% if x %}yes{% else %}no{% endif %}", {"x": []})

    def test_if_nonempty_list_is_truthy(self, stock, cyth):
        _m(stock, cyth, "{% if x %}yes{% else %}no{% endif %}", {"x": [1]})

    # --- If inside for loop (interacts with LOOPIF optimization) ---
    def test_if_in_loop_attr_eq(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{% for item in items %}{% if item.x == 1 %}Y{% else %}N{% endif %}{% endfor %}",
            {"items": [{"x": 1}, {"x": 2}, {"x": 1}]},
        )

    def test_if_in_loop_and_or(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{% for item in items %}"
            "{% if item.a and item.b %}AB{% elif item.a or item.b %}A|B{% else %}-{% endif %}"
            "{% endfor %}",
            {
                "items": [
                    {"a": True, "b": True},
                    {"a": True, "b": False},
                    {"a": False, "b": False},
                ],
            },
        )


# ===========================================================================
# 3. FOR TAG — comprehensive
# ===========================================================================


class TestForTag:
    """Test {% for %} with unpacking, parentloop, reversed, empty, etc."""

    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{% for x in items %}{{ x }}{% endfor %}", {"items": ["a", "b", "c"]})

    def test_reversed(self, stock, cyth):
        _m(stock, cyth, "{% for x in items reversed %}{{ x }}{% endfor %}", {"items": [1, 2, 3]})

    def test_empty(self, stock, cyth):
        _m(stock, cyth, "{% for x in items %}{{ x }}{% empty %}none{% endfor %}", {"items": []})

    def test_reversed_empty(self, stock, cyth):
        """reversed + empty together."""
        _m(stock, cyth, "{% for x in items reversed %}{{ x }}{% empty %}none{% endfor %}", {"items": []})

    def test_reversed_with_items(self, stock, cyth):
        _m(stock, cyth, "{% for x in items reversed %}{{ x }}{% empty %}none{% endfor %}", {"items": [1, 2, 3]})

    def test_tuple_unpacking(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{% for key, val in items %}{{ key }}={{ val }} {% endfor %}",
            {"items": [("a", 1), ("b", 2), ("c", 3)]},
        )

    def test_tuple_unpacking_3(self, stock, cyth):
        """3-variable unpacking."""
        _m(
            stock,
            cyth,
            "{% for a, b, c in items %}{{ a }}.{{ b }}.{{ c }}|{% endfor %}",
            {"items": [(1, 2, 3), (4, 5, 6)]},
        )

    def test_forloop_counter(self, stock, cyth):
        _m(stock, cyth, "{% for x in items %}{{ forloop.counter }}{% endfor %}", {"items": "abcde"})

    def test_forloop_counter0(self, stock, cyth):
        _m(stock, cyth, "{% for x in items %}{{ forloop.counter0 }}{% endfor %}", {"items": "abcde"})

    def test_forloop_revcounter(self, stock, cyth):
        _m(stock, cyth, "{% for x in items %}{{ forloop.revcounter }}{% endfor %}", {"items": "abcde"})

    def test_forloop_revcounter0(self, stock, cyth):
        _m(stock, cyth, "{% for x in items %}{{ forloop.revcounter0 }}{% endfor %}", {"items": "abcde"})

    def test_forloop_first(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{% for x in items %}{% if forloop.first %}F{% endif %}{{ x }}{% endfor %}",
            {"items": ["a", "b", "c"]},
        )

    def test_forloop_last(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{% for x in items %}{{ x }}{% if forloop.last %}L{% endif %}{% endfor %}",
            {"items": ["a", "b", "c"]},
        )

    def test_forloop_first_and_last_single(self, stock, cyth):
        """Single-element list: both first and last are True."""
        _m(
            stock,
            cyth,
            "{% for x in items %}"
            "{% if forloop.first %}F{% endif %}"
            "{% if forloop.last %}L{% endif %}"
            "{{ x }}"
            "{% endfor %}",
            {"items": ["only"]},
        )

    def test_forloop_parentloop(self, stock, cyth):
        """Nested loops with forloop.parentloop."""
        _m(
            stock,
            cyth,
            "{% for outer in outers %}"
            "{% for inner in inners %}"
            "{{ forloop.parentloop.counter }}.{{ forloop.counter }} "
            "{% endfor %}"
            "{% endfor %}",
            {"outers": ["a", "b"], "inners": [1, 2, 3]},
        )

    def test_nested_loops(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{% for group in groups %}[{% for item in group %}{{ item }}{% endfor %}]{% endfor %}",
            {"groups": [[1, 2], [3], [4, 5, 6]]},
        )

    def test_for_string(self, stock, cyth):
        """Iterating over a string."""
        _m(stock, cyth, "{% for c in word %}{{ c }}-{% endfor %}", {"word": "hello"})

    def test_for_dict(self, stock, cyth):
        """Iterating over a dict iterates keys."""
        result = _m(stock, cyth, "{% for k in d %}{{ k }}{% endfor %}", {"d": {"a": 1}})
        assert "a" in result

    def test_undefined_iterable(self, stock, cyth):
        _m(stock, cyth, "{% for x in missing %}{{ x }}{% empty %}empty{% endfor %}", {})

    def test_for_with_cycle(self, stock, cyth):
        _m(stock, cyth, "{% for x in items %}{% cycle 'odd' 'even' %}:{{ x }} {% endfor %}", {"items": [1, 2, 3, 4, 5]})

    def test_for_with_if_forloop(self, stock, cyth):
        """Combined forloop.first/last with if — tests LOOPIF_CONST interaction."""
        _m(
            stock,
            cyth,
            "{% for x in items %}"
            "{% if forloop.first %}<first>{% endif %}"
            "{{ x }}"
            "{% if forloop.last %}<last>{% endif %}"
            "{% endfor %}",
            {"items": ["a", "b", "c"]},
        )


# ===========================================================================
# 4. CYCLE TAG
# ===========================================================================


class TestCycleTag:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{% for x in items %}{% cycle 'a' 'b' 'c' %}{% endfor %}", {"items": range(7)})

    def test_named(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{% for x in items %}{% cycle 'odd' 'even' as cls %}{{ cls }}:{{ x }} {% endfor %}",
            {"items": [1, 2, 3, 4]},
        )

    def test_variable_values(self, stock, cyth):
        _m(stock, cyth, "{% for x in items %}{% cycle a b %}{% endfor %}", {"items": range(4), "a": "X", "b": "Y"})

    def test_silent(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{% for x in items %}{% cycle 'a' 'b' as val silent %}[{{ val }}]{% endfor %}",
            {"items": range(4)},
        )


# ===========================================================================
# 5. WITH TAG
# ===========================================================================


class TestWithTag:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{% with x='hello' %}{{ x }}{% endwith %}", {})

    def test_multiple_assignments(self, stock, cyth):
        _m(stock, cyth, "{% with a=1 b=2 c=3 %}{{ a }}.{{ b }}.{{ c }}{% endwith %}", {})

    def test_variable_value(self, stock, cyth):
        _m(stock, cyth, "{% with full=user.name %}{{ full }}{% endwith %}", {"user": {"name": "Alice"}})

    def test_scoping(self, stock, cyth):
        """Variable should not leak outside with block."""
        _m(stock, cyth, "[{% with x='inside' %}{{ x }}{% endwith %}][{{ x }}]", {})

    def test_with_filter(self, stock, cyth):
        _m(stock, cyth, "{% with upper_name=name|upper %}{{ upper_name }}{% endwith %}", {"name": "alice"})


# ===========================================================================
# 6. COMMENT TAG
# ===========================================================================


class TestCommentTag:
    def test_block_comment(self, stock, cyth):
        _m(stock, cyth, "a{% comment %}hidden{% endcomment %}b", {})

    def test_inline_comment(self, stock, cyth):
        _m(stock, cyth, "a{# inline comment #}b", {})

    def test_comment_with_tags(self, stock, cyth):
        """Template tags inside comments should be ignored."""
        _m(stock, cyth, "{% comment %}{% if True %}not rendered{% endif %}{% endcomment %}ok", {})

    def test_comment_with_variables(self, stock, cyth):
        _m(stock, cyth, "{% comment %}{{ secret }}{% endcomment %}visible", {"secret": "hidden"})

    def test_multiline_comment(self, stock, cyth):
        _m(stock, cyth, "before{% comment %}\nline 1\nline 2\n{% endcomment %}after", {})


# ===========================================================================
# 7. SPACELESS TAG
# ===========================================================================


class TestSpacelessTag:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{% spaceless %}<p> <a>link</a> </p>{% endspaceless %}", {})

    def test_preserves_text_whitespace(self, stock, cyth):
        """Whitespace inside text nodes is preserved."""
        _m(stock, cyth, "{% spaceless %}<p>hello world</p>{% endspaceless %}", {})

    def test_nested_tags(self, stock, cyth):
        _m(stock, cyth, "{% spaceless %}<div> <p> <span>x</span> </p> </div>{% endspaceless %}", {})


# ===========================================================================
# 8. FIRSTOF TAG
# ===========================================================================


class TestFirstofTag:
    def test_first_truthy(self, stock, cyth):
        _m(stock, cyth, "{% firstof a b c %}", {"a": "first", "b": "second"})

    def test_second_truthy(self, stock, cyth):
        _m(stock, cyth, "{% firstof a b c %}", {"a": "", "b": "second"})

    def test_literal_fallback(self, stock, cyth):
        _m(stock, cyth, '{% firstof a b "fallback" %}', {"a": "", "b": ""})

    def test_all_falsy(self, stock, cyth):
        result = _m(stock, cyth, "{% firstof a b c %}", {"a": "", "b": "", "c": ""})
        assert result == ""

    def test_as_variable(self, stock, cyth):
        _m(stock, cyth, "{% firstof a b as val %}[{{ val }}]", {"a": "", "b": "found"})

    def test_autoescape(self, stock, cyth):
        _m(stock, cyth, "{% firstof val %}", {"val": "<b>bold</b>"})


# ===========================================================================
# 9. VERBATIM TAG
# ===========================================================================


class TestVerbatimTag:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{% verbatim %}{{ not_rendered }}{% endverbatim %}", {})

    def test_with_tags(self, stock, cyth):
        _m(stock, cyth, "{% verbatim %}{% if True %}raw{% endif %}{% endverbatim %}", {})

    def test_named(self, stock, cyth):
        _m(stock, cyth, "{% verbatim myblock %}{{ raw }}{% endverbatim myblock %}", {})


# ===========================================================================
# 10. TEMPLATETAG
# ===========================================================================


class TestTemplatetagTag:
    def test_openblock(self, stock, cyth):
        _m(stock, cyth, "{% templatetag openblock %}", {})

    def test_closeblock(self, stock, cyth):
        _m(stock, cyth, "{% templatetag closeblock %}", {})

    def test_openvariable(self, stock, cyth):
        _m(stock, cyth, "{% templatetag openvariable %}", {})

    def test_closevariable(self, stock, cyth):
        _m(stock, cyth, "{% templatetag closevariable %}", {})

    def test_openbrace(self, stock, cyth):
        _m(stock, cyth, "{% templatetag openbrace %}", {})

    def test_closebrace(self, stock, cyth):
        _m(stock, cyth, "{% templatetag closebrace %}", {})

    def test_opencomment(self, stock, cyth):
        _m(stock, cyth, "{% templatetag opencomment %}", {})

    def test_closecomment(self, stock, cyth):
        _m(stock, cyth, "{% templatetag closecomment %}", {})


# ===========================================================================
# 11. NOW TAG
# ===========================================================================


class TestNowTag:
    def test_year(self, stock, cyth):
        _m(stock, cyth, '{% now "Y" %}', {})

    def test_full_date(self, stock, cyth):
        _m(stock, cyth, '{% now "j F Y" %}', {})

    def test_as_variable(self, stock, cyth):
        _m(stock, cyth, '{% now "Y" as year %}The year is {{ year }}.', {})


# ===========================================================================
# 12. WIDTHRATIO TAG
# ===========================================================================


class TestWidthratioTag:
    def test_basic(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{% widthratio this_val max_val max_width %}",
            {"this_val": 175, "max_val": 200, "max_width": 100},
        )

    def test_zero(self, stock, cyth):
        _m(stock, cyth, "{% widthratio 0 100 100 %}", {})

    def test_as_variable(self, stock, cyth):
        _m(stock, cyth, "{% widthratio this_val max_val 100 as ratio %}[{{ ratio }}]", {"this_val": 50, "max_val": 100})


# ===========================================================================
# 13. FILTER TAG
# ===========================================================================


class TestFilterTag:
    def test_upper(self, stock, cyth):
        _m(stock, cyth, "{% filter upper %}hello world{% endfilter %}", {})

    def test_lower(self, stock, cyth):
        _m(stock, cyth, "{% filter lower %}HELLO{% endfilter %}", {})

    def test_cut(self, stock, cyth):
        _m(stock, cyth, '{% filter cut:" " %}hello world{% endfilter %}', {})

    def test_with_variable(self, stock, cyth):
        _m(stock, cyth, "{% filter upper %}{{ name }}{% endfilter %}", {"name": "alice"})


# ===========================================================================
# 14. IFCHANGED TAG
# ===========================================================================


class TestIfchangedTag:
    def test_basic(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{% for x in items %}{% ifchanged %}{{ x }}{% endifchanged %}{% endfor %}",
            {"items": [1, 1, 2, 2, 3]},
        )

    def test_with_else(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{% for x in items %}{% ifchanged %}{{ x }}{% else %}.{% endifchanged %}{% endfor %}",
            {"items": [1, 1, 2, 2, 3]},
        )

    def test_parameter(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{% for item in items %}{% ifchanged item.group %}[{{ item.group }}]{% endifchanged %}{{ item.name }}{% endfor %}",
            {
                "items": [
                    {"group": "A", "name": "a1"},
                    {"group": "A", "name": "a2"},
                    {"group": "B", "name": "b1"},
                ],
            },
        )


# ===========================================================================
# 15. REGROUP TAG
# ===========================================================================


class TestRegroupTag:
    def test_basic(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{% regroup items by category as grouped %}"
            "{% for group in grouped %}"
            "{{ group.grouper }}:{% for item in group.list %}{{ item.name }}{% endfor %}|"
            "{% endfor %}",
            {
                "items": [
                    {"name": "a", "category": "X"},
                    {"name": "b", "category": "Y"},
                    {"name": "c", "category": "X"},
                    {"name": "d", "category": "Y"},
                ],
            },
        )


# ===========================================================================
# 16. RESETCYCLE TAG
# ===========================================================================


class TestResetcycleTag:
    def test_basic(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{% for x in items %}"
            "{% cycle 'a' 'b' 'c' as cls %}"
            "{% if forloop.last %}{% resetcycle cls %}{% endif %}"
            "{{ cls }}"
            "{% endfor %}"
            "|"
            "{% for x in items2 %}"
            "{% cycle 'a' 'b' 'c' as cls %}"
            "{{ cls }}"
            "{% endfor %}",
            {"items": [1, 2], "items2": [1, 2, 3]},
        )


# ===========================================================================
# 17. AUTOESCAPE & FILTER CHAINING SAFETY
# ===========================================================================


class TestAutoescapeAndSafety:
    """Test filter chaining safety propagation — modeled after Django's test_chaining.py."""

    def test_autoescape_on(self, stock, cyth):
        _m(stock, cyth, "{{ val }}", {"val": "<b>bold</b>"})

    def test_autoescape_off(self, stock, cyth):
        _m(stock, cyth, "{% autoescape off %}{{ val }}{% endautoescape %}", {"val": "<b>bold</b>"})

    def test_autoescape_nested(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{% autoescape off %}{{ val }}{% autoescape on %}{{ val }}{% endautoescape %}{{ val }}{% endautoescape %}",
            {"val": "<b>x</b>"},
        )

    def test_safe_filter(self, stock, cyth):
        _m(stock, cyth, "{{ val|safe }}", {"val": "<b>bold</b>"})

    def test_escape_filter(self, stock, cyth):
        _m(stock, cyth, "{{ val|escape }}", {"val": "<b>bold</b>"})

    def test_force_escape(self, stock, cyth):
        _m(stock, cyth, "{{ val|force_escape }}", {"val": "<b>bold</b>"})

    def test_force_escape_double(self, stock, cyth):
        """force_escape always escapes, even already-safe strings."""
        _m(stock, cyth, "{{ val|force_escape }}", {"val": SafeString("<b>bold</b>")})

    def test_safe_then_force_escape(self, stock, cyth):
        """force_escape overrides safe filter."""
        _m(stock, cyth, "{{ val|safe|force_escape }}", {"val": "<b>x</b>"})

    def test_escape_no_double_escape(self, stock, cyth):
        """escape + capfirst should not double-escape."""
        _m(stock, cyth, "{{ val|escape|capfirst }}", {"val": "<b>test</b>"})

    def test_capfirst_preserves_safety(self, stock, cyth):
        """Safeness-preserving filters maintain safe status."""
        _m(stock, cyth, "{{ val|capfirst }}", {"val": mark_safe("<b>test</b>")})

    def test_cut_resets_safety(self, stock, cyth):
        """cut filter resets safety status."""
        _m(stock, cyth, '{{ val|cut:" " }}', {"val": mark_safe("<b>te st</b>")})

    def test_safestring_not_escaped(self, stock, cyth):
        _m(stock, cyth, "{{ val }}", {"val": SafeString("<b>bold</b>")})

    def test_html_entities(self, stock, cyth):
        """All 5 HTML special characters should be escaped."""
        _m(stock, cyth, "{{ val }}", {"val": "<>&\"'"})

    def test_filter_in_autoescape_off(self, stock, cyth):
        _m(stock, cyth, "{% autoescape off %}{{ val|upper }}{% endautoescape %}", {"val": "<b>test</b>"})


# ===========================================================================
# 18. TEMPLATE INHERITANCE
# ===========================================================================


class TestTemplateInheritance:
    """Test extends/block/block.super with file-based templates."""

    def test_single_level(self, stock, cyth):
        for engine in [stock, cyth]:
            result = engine.get_template("child.html").render({"name": "Alice"})
            assert "<title>Child</title>" in result
            assert "<p>Hello Alice</p>" in result

    def test_two_level_inheritance(self, stock, cyth):
        """child -> middle -> base, testing block.super at each level."""
        stock_result = stock.get_template("grandchild.html").render({"name": "Bob"})
        cyth_result = cyth.get_template("grandchild.html").render({"name": "Bob"})
        assert cyth_result == stock_result

    def test_block_super(self, stock, cyth):
        """block.super should include parent block content."""
        stock_result = stock.get_template("grandchild.html").render({"name": "X"})
        cyth_result = cyth.get_template("grandchild.html").render({"name": "X"})
        # middle.html: {% block title %}Middle - {{ block.super }}{% endblock %}
        # grandchild.html: {% block title %}Grandchild - {{ block.super }}{% endblock %}
        # Should produce: "Grandchild - Middle - Default"
        assert "Grandchild - Middle - Default" in stock_result
        assert cyth_result == stock_result


# ===========================================================================
# 19. INCLUDE TAG
# ===========================================================================


class TestIncludeTag:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, '{% include "include_target.html" %}', {"message": "hi"})

    def test_with_clause(self, stock, cyth):
        _m(stock, cyth, '{% include "include_target.html" with message="hello" %}', {})

    def test_only(self, stock, cyth):
        """only keyword restricts context to with vars."""
        _m(
            stock,
            cyth,
            '{% include "include_context.html" with greeting="Hi" name="Bob" only %}',
            {"greeting": "ignored", "name": "ignored", "extra": "ignored"},
        )

    def test_dynamic_name(self, stock, cyth):
        _m(stock, cyth, "{% include tpl %}", {"tpl": "include_target.html", "message": "dynamic"})

    def test_include_in_loop(self, stock, cyth):
        _m(
            stock,
            cyth,
            '{% for msg in messages %}{% include "include_target.html" with message=msg %}{% endfor %}',
            {"messages": ["one", "two", "three"]},
        )

    def test_nested_include(self, stock, cyth):
        """Include a template that itself uses variables from context."""
        _m(stock, cyth, '{% include "include_simple.html" %}', {"item_name": "Widget", "item_value": "42"})


# ===========================================================================
# 20. BUILT-IN FILTERS — comprehensive coverage
# ===========================================================================


class TestFilterAdd:
    def test_integers(self, stock, cyth):
        _m(stock, cyth, "{{ a|add:b }}", {"a": 1, "b": 2})

    def test_strings(self, stock, cyth):
        _m(stock, cyth, "{{ a|add:b }}", {"a": "hello", "b": " world"})

    def test_mixed(self, stock, cyth):
        """String + int — falls back to string concatenation or empty."""
        _m(stock, cyth, "{{ a|add:b }}", {"a": "hello", "b": 5})

    def test_lists(self, stock, cyth):
        _m(stock, cyth, "{{ a|add:b }}", {"a": [1, 2], "b": [3, 4]})

    def test_literal(self, stock, cyth):
        _m(stock, cyth, "{{ val|add:5 }}", {"val": 10})

    def test_negative(self, stock, cyth):
        _m(stock, cyth, '{{ val|add:"-3" }}', {"val": 10})


class TestFilterAddslashes:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{{ val|addslashes }}", {"val": "I'm happy"})

    def test_backslash(self, stock, cyth):
        _m(stock, cyth, "{{ val|addslashes }}", {"val": "path\\to\\file"})


class TestFilterCapfirst:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{{ val|capfirst }}", {"val": "hello world"})

    def test_empty(self, stock, cyth):
        _m(stock, cyth, "{{ val|capfirst }}", {"val": ""})

    def test_already_upper(self, stock, cyth):
        _m(stock, cyth, "{{ val|capfirst }}", {"val": "Hello"})


class TestFilterCenter:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, '{{ val|center:"15" }}', {"val": "hi"})


class TestFilterCut:
    def test_space(self, stock, cyth):
        _m(stock, cyth, '{{ val|cut:" " }}', {"val": "hello world"})

    def test_char(self, stock, cyth):
        _m(stock, cyth, '{{ val|cut:"x" }}', {"val": "xaxbxcx"})


class TestFilterDate:
    def test_format(self, stock, cyth):
        dt = datetime.datetime(2024, 1, 15, 14, 30, 0)
        _m(stock, cyth, '{{ val|date:"Y-m-d" }}', {"val": dt})

    def test_format_time(self, stock, cyth):
        dt = datetime.datetime(2024, 1, 15, 14, 30, 0)
        _m(stock, cyth, '{{ val|date:"H:i" }}', {"val": dt})

    def test_date_object(self, stock, cyth):
        d = datetime.date(2024, 6, 15)
        _m(stock, cyth, '{{ val|date:"j F Y" }}', {"val": d})

    def test_time_object(self, stock, cyth):
        t = datetime.time(14, 30, 0)
        _m(stock, cyth, '{{ val|time:"H:i" }}', {"val": t})

    def test_no_format(self, stock, cyth):
        """Without format argument, uses default DATE_FORMAT."""
        dt = datetime.datetime(2024, 1, 15, 14, 30, 0)
        _m(stock, cyth, "{{ val|date }}", {"val": dt})

    def test_non_date(self, stock, cyth):
        """Non-date value should render as empty string."""
        _m(stock, cyth, '{{ val|date:"Y" }}', {"val": "not a date"})


class TestFilterDefault:
    def test_missing(self, stock, cyth):
        _m(stock, cyth, "{{ val|default:'N/A' }}", {})

    def test_present(self, stock, cyth):
        _m(stock, cyth, "{{ val|default:'N/A' }}", {"val": "hello"})

    def test_falsy_zero(self, stock, cyth):
        _m(stock, cyth, "{{ val|default:'N/A' }}", {"val": 0})

    def test_falsy_empty_string(self, stock, cyth):
        _m(stock, cyth, "{{ val|default:'N/A' }}", {"val": ""})

    def test_falsy_none(self, stock, cyth):
        _m(stock, cyth, "{{ val|default:'N/A' }}", {"val": None})


class TestFilterDefaultIfNone:
    def test_none(self, stock, cyth):
        _m(stock, cyth, "{{ val|default_if_none:'N/A' }}", {"val": None})

    def test_not_none(self, stock, cyth):
        _m(stock, cyth, "{{ val|default_if_none:'N/A' }}", {"val": ""})

    def test_zero(self, stock, cyth):
        _m(stock, cyth, "{{ val|default_if_none:'N/A' }}", {"val": 0})


class TestFilterDivisibleby:
    def test_true(self, stock, cyth):
        _m(stock, cyth, '{{ val|divisibleby:"3" }}', {"val": 9})

    def test_false(self, stock, cyth):
        _m(stock, cyth, '{{ val|divisibleby:"3" }}', {"val": 10})


class TestFilterEscape:
    def test_html(self, stock, cyth):
        _m(stock, cyth, "{{ val|escape }}", {"val": "<b>&\"'"})


class TestFilterEscapejs:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{{ val|escapejs }}", {"val": 'hello "world"\nline2'})

    def test_special_chars(self, stock, cyth):
        _m(stock, cyth, "{{ val|escapejs }}", {"val": "</script>"})


class TestFilterFilesizeformat:
    def test_bytes(self, stock, cyth):
        _m(stock, cyth, "{{ val|filesizeformat }}", {"val": 1023})

    def test_kb(self, stock, cyth):
        _m(stock, cyth, "{{ val|filesizeformat }}", {"val": 1024 * 5})

    def test_mb(self, stock, cyth):
        _m(stock, cyth, "{{ val|filesizeformat }}", {"val": 1024 * 1024 * 3})


class TestFilterFirst:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{{ items|first }}", {"items": ["a", "b", "c"]})

    def test_string(self, stock, cyth):
        _m(stock, cyth, "{{ val|first }}", {"val": "hello"})


class TestFilterFloatformat:
    def test_default(self, stock, cyth):
        _m(stock, cyth, "{{ val|floatformat }}", {"val": 3.14159})

    def test_precision(self, stock, cyth):
        _m(stock, cyth, "{{ val|floatformat:2 }}", {"val": 3.14159})

    def test_zero(self, stock, cyth):
        _m(stock, cyth, "{{ val|floatformat:2 }}", {"val": 0})

    def test_integer(self, stock, cyth):
        _m(stock, cyth, "{{ val|floatformat:2 }}", {"val": 42})

    def test_negative(self, stock, cyth):
        """Negative arg: only show decimal places if non-zero."""
        _m(stock, cyth, '{{ val|floatformat:"-2" }}', {"val": 3.0})

    def test_negative_nonzero(self, stock, cyth):
        _m(stock, cyth, '{{ val|floatformat:"-2" }}', {"val": 3.14})


class TestFilterForceEscape:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{{ val|force_escape }}", {"val": "<b>bold</b>"})

    def test_already_safe(self, stock, cyth):
        _m(stock, cyth, "{{ val|force_escape }}", {"val": SafeString("<b>bold</b>")})


class TestFilterJoin:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, '{{ items|join:", " }}', {"items": ["a", "b", "c"]})

    def test_html(self, stock, cyth):
        """HTML in items should be escaped."""
        _m(stock, cyth, '{{ items|join:", " }}', {"items": ["<b>a</b>", "b&c"]})

    def test_autoescape_off(self, stock, cyth):
        _m(stock, cyth, '{% autoescape off %}{{ items|join:", " }}{% endautoescape %}', {"items": ["<b>a</b>", "b"]})


class TestFilterJsonScript:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, '{{ val|json_script:"data" }}', {"val": {"key": "value", "num": 42}})

    def test_xss(self, stock, cyth):
        """JSON script should prevent XSS."""
        _m(stock, cyth, '{{ val|json_script:"data" }}', {"val": "</script><script>alert('xss')</script>"})


class TestFilterLast:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{{ items|last }}", {"items": ["a", "b", "c"]})


class TestFilterLength:
    def test_list(self, stock, cyth):
        _m(stock, cyth, "{{ items|length }}", {"items": [1, 2, 3]})

    def test_string(self, stock, cyth):
        _m(stock, cyth, "{{ val|length }}", {"val": "hello"})

    def test_empty(self, stock, cyth):
        _m(stock, cyth, "{{ val|length }}", {"val": []})


class TestFilterLinebreaks:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{{ val|linebreaks }}", {"val": "line1\nline2"})

    def test_double_newline(self, stock, cyth):
        _m(stock, cyth, "{{ val|linebreaks }}", {"val": "para1\n\npara2"})


class TestFilterLinebreaksbr:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{{ val|linebreaksbr }}", {"val": "line1\nline2"})


class TestFilterLower:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{{ val|lower }}", {"val": "HELLO World"})


class TestFilterMakeList:
    def test_string(self, stock, cyth):
        _m(stock, cyth, "{{ val|make_list }}", {"val": "abc"})

    def test_integer(self, stock, cyth):
        _m(stock, cyth, "{{ val|make_list }}", {"val": 123})


class TestFilterPluralize:
    def test_single(self, stock, cyth):
        _m(stock, cyth, "{{ count }} item{{ count|pluralize }}", {"count": 1})

    def test_plural(self, stock, cyth):
        _m(stock, cyth, "{{ count }} item{{ count|pluralize }}", {"count": 3})

    def test_custom_suffix(self, stock, cyth):
        _m(stock, cyth, '{{ count }} cherr{{ count|pluralize:"y,ies" }}', {"count": 2})

    def test_custom_suffix_single(self, stock, cyth):
        _m(stock, cyth, '{{ count }} cherr{{ count|pluralize:"y,ies" }}', {"count": 1})


class TestFilterSafe:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{{ val|safe }}", {"val": "<b>bold</b>"})


class TestFilterSlice:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, '{{ items|slice:":2" }}', {"items": [1, 2, 3, 4, 5]})

    def test_from(self, stock, cyth):
        _m(stock, cyth, '{{ items|slice:"2:" }}', {"items": [1, 2, 3, 4, 5]})

    def test_range(self, stock, cyth):
        _m(stock, cyth, '{{ items|slice:"1:3" }}', {"items": [1, 2, 3, 4, 5]})


class TestFilterSlugify:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{{ val|slugify }}", {"val": "Hello World!"})

    def test_unicode(self, stock, cyth):
        _m(stock, cyth, "{{ val|slugify }}", {"val": "Héllo Wörld"})


class TestFilterStringformat:
    def test_s(self, stock, cyth):
        """stringformat:'s' — tests our FFILTER_STRINGFORMAT_S fast path."""
        _m(stock, cyth, '{{ val|stringformat:"s" }}', {"val": "hello"})

    def test_d(self, stock, cyth):
        _m(stock, cyth, '{{ val|stringformat:"d" }}', {"val": 42})

    def test_f(self, stock, cyth):
        _m(stock, cyth, '{{ val|stringformat:".2f" }}', {"val": 3.14159})

    def test_05d(self, stock, cyth):
        _m(stock, cyth, '{{ val|stringformat:"05d" }}', {"val": 42})

    def test_with_int(self, stock, cyth):
        _m(stock, cyth, '{{ val|stringformat:"s" }}', {"val": 42})


class TestFilterStriptags:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{{ val|striptags }}", {"val": "<b>bold</b> and <i>italic</i>"})


class TestFilterTime:
    def test_basic(self, stock, cyth):
        t = datetime.time(14, 30, 0)
        _m(stock, cyth, '{{ val|time:"H:i" }}', {"val": t})

    def test_datetime(self, stock, cyth):
        dt = datetime.datetime(2024, 1, 15, 14, 30, 45)
        _m(stock, cyth, '{{ val|time:"H:i:s" }}', {"val": dt})


class TestFilterTitle:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{{ val|title }}", {"val": "hello world"})

    def test_mixed(self, stock, cyth):
        _m(stock, cyth, "{{ val|title }}", {"val": "hELLO wORLD"})


class TestFilterTruncatechars:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{{ val|truncatechars:10 }}", {"val": "Hello World, how are you?"})

    def test_short(self, stock, cyth):
        _m(stock, cyth, "{{ val|truncatechars:100 }}", {"val": "short"})


class TestFilterTruncatewords:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{{ val|truncatewords:3 }}", {"val": "one two three four five"})

    def test_exact(self, stock, cyth):
        _m(stock, cyth, "{{ val|truncatewords:3 }}", {"val": "one two three"})


class TestFilterUpper:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{{ val|upper }}", {"val": "hello World"})


class TestFilterUrlencode:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{{ val|urlencode }}", {"val": "hello world&more"})


class TestFilterWordcount:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{{ val|wordcount }}", {"val": "hello world foo"})


class TestFilterWordwrap:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{{ val|wordwrap:10 }}", {"val": "this is a long sentence that should be wrapped"})


class TestFilterYesno:
    def test_true(self, stock, cyth):
        _m(stock, cyth, '{{ val|yesno:"yes,no" }}', {"val": True})

    def test_false(self, stock, cyth):
        _m(stock, cyth, '{{ val|yesno:"yes,no" }}', {"val": False})

    def test_none(self, stock, cyth):
        _m(stock, cyth, '{{ val|yesno:"yes,no,maybe" }}', {"val": None})

    def test_none_two_args(self, stock, cyth):
        _m(stock, cyth, '{{ val|yesno:"yes,no" }}', {"val": None})


class TestFilterChaining:
    """Test multiple filters chained together."""

    def test_lower_capfirst(self, stock, cyth):
        _m(stock, cyth, "{{ val|lower|capfirst }}", {"val": "HELLO WORLD"})

    def test_upper_truncatewords(self, stock, cyth):
        _m(stock, cyth, "{{ val|upper|truncatewords:2 }}", {"val": "hello world foo"})

    def test_default_lower(self, stock, cyth):
        _m(stock, cyth, "{{ val|default:'N/A'|lower }}", {})

    def test_triple_chain(self, stock, cyth):
        _m(stock, cyth, '{{ val|cut:" "|lower|capfirst }}', {"val": "HELLO WORLD"})

    def test_filter_with_variable_arg(self, stock, cyth):
        _m(stock, cyth, "{{ val|add:other }}", {"val": 10, "other": 5})


# ===========================================================================
# 21. BUILTINS — True, False, None literals
# ===========================================================================


class TestBuiltins:
    def test_true(self, stock, cyth):
        _m(stock, cyth, "{{ True }}", {})

    def test_false(self, stock, cyth):
        _m(stock, cyth, "{{ False }}", {})

    def test_none(self, stock, cyth):
        _m(stock, cyth, "{{ None }}", {})


# ===========================================================================
# 22. MIXED / REALISTIC EDGE CASES
# ===========================================================================


class TestMixedEdgeCases:
    """Test combinations of features that interact with our optimizations."""

    def test_loop_with_objects(self, stock, cyth):
        """Object attributes in a for loop — tests LOOPATTR with real objects."""
        items = [SimpleObj(name="Alice", age=30), SimpleObj(name="Bob", age=25)]
        _m(stock, cyth, "{% for item in items %}{{ item.name }}({{ item.age }}){% endfor %}", {"items": items})

    def test_loop_with_callables(self, stock, cyth):
        """Callable methods in a for loop."""
        items = [CallableObj("hello"), CallableObj("world")]
        _m(stock, cyth, "{% for item in items %}{{ item.get_value }}|{% endfor %}", {"items": items})

    def test_loop_with_index(self, stock, cyth):
        """List index access in loop body."""
        _m(
            stock,
            cyth,
            "{% for row in rows %}{{ row.0 }}:{{ row.1 }}|{% endfor %}",
            {"rows": [["a", 1], ["b", 2], ["c", 3]]},
        )

    def test_loop_with_filter_and_if(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{% for item in items %}{% if item.active %}{{ item.name|upper }}{% endif %}{% endfor %}",
            {
                "items": [
                    {"name": "alice", "active": True},
                    {"name": "bob", "active": False},
                    {"name": "carol", "active": True},
                ],
            },
        )

    def test_nested_loops_with_parentloop(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{% for group in groups %}"
            "[{% for item in group.items %}"
            "{{ forloop.parentloop.counter }}.{{ forloop.counter }}={{ item }} "
            "{% endfor %}]"
            "{% endfor %}",
            {
                "groups": [
                    {"items": ["a", "b"]},
                    {"items": ["c"]},
                    {"items": ["d", "e", "f"]},
                ],
            },
        )

    def test_include_in_loop(self, stock, cyth):
        _m(
            stock,
            cyth,
            '{% for msg in messages %}{% include "include_target.html" with message=msg %}{% endfor %}',
            {"messages": ["one", "two"]},
        )

    def test_cycle_with_filter(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{% for x in items %}{% cycle 'ODD' 'EVEN' as cls %}{{ cls|lower }} {% endfor %}",
            {"items": range(4)},
        )

    def test_multiline_template(self, stock, cyth):
        template = """<html>
<body>
{% for item in items %}
<p>{{ item.name }}: {{ item.value }}</p>
{% endfor %}
</body>
</html>"""
        _m(stock, cyth, template, {"items": [{"name": "a", "value": 1}, {"name": "b", "value": 2}]})

    def test_empty_template(self, stock, cyth):
        _m(stock, cyth, "", {})

    def test_only_whitespace(self, stock, cyth):
        _m(stock, cyth, "   \n  \t  ", {})

    def test_unicode_content(self, stock, cyth):
        _m(stock, cyth, "{{ val }}", {"val": "Hello 世界 🌍"})

    def test_unicode_in_loop(self, stock, cyth):
        _m(stock, cyth, "{% for item in items %}{{ item }}|{% endfor %}", {"items": ["café", "naïve", "日本語"]})

    def test_many_variables(self, stock, cyth):
        """Template with many variable substitutions."""
        tmpl = " ".join(f"{{{{ v{i} }}}}" for i in range(20))
        ctx = {f"v{i}": f"val{i}" for i in range(20)}
        _m(stock, cyth, tmpl, ctx)

    def test_deeply_nested_dicts(self, stock, cyth):
        _m(stock, cyth, "{{ a.b.c.d.e }}", {"a": {"b": {"c": {"d": {"e": "deep"}}}}})

    def test_boolean_in_if_and_render(self, stock, cyth):
        """Boolean should work in both if conditions and variable rendering."""
        _m(stock, cyth, "{% if flag %}flag={{ flag }}{% endif %}", {"flag": True})

    def test_integer_comparison_in_loop(self, stock, cyth):
        """Numeric comparison inside a loop — tests LOOPIF."""
        _m(
            stock,
            cyth,
            "{% for item in items %}{% if item.score >= 80 %}pass{% else %}fail{% endif %} {% endfor %}",
            {"items": [{"score": 90}, {"score": 50}, {"score": 80}]},
        )


# ---------------------------------------------------------------------------
# Production edge case tests — correctness in LOOPATTR/LOOPIF hot paths
# ---------------------------------------------------------------------------


class TestLoopEdgeCases:
    """Tests for edge cases in the optimized ForNode loop paths.

    These test correctness of LOOPATTR, LOOPIF, LOOPIF_CONST, LOOPCYCLE,
    FORLOOP_COUNTER, and constant variable caching optimizations.
    """

    def test_dict_missing_key_in_loop(self, stock, cyth):
        """Dict in loop missing an accessed key should silently resolve to empty."""
        _m(
            stock,
            cyth,
            "{% for item in items %}[{{ item.name }}:{{ item.price }}]{% endfor %}",
            {
                "items": [
                    {"name": "a", "price": 10},
                    {"name": "b"},  # missing 'price'
                    {"price": 30},  # missing 'name'
                ],
            },
        )

    def test_dict_missing_key_in_loop_with_filter(self, stock, cyth):
        """Dict missing key when filter applied — LOOPATTR_FILTER path."""
        _m(
            stock,
            cyth,
            "{% for item in items %}[{{ item.name|upper }}]{% endfor %}",
            {
                "items": [
                    {"name": "hello"},
                    {},  # missing 'name'
                    {"name": "world"},
                ],
            },
        )

    def test_loop_if_dict_missing_key(self, stock, cyth):
        """LOOPIF with dict missing the condition key."""
        _m(
            stock,
            cyth,
            "{% for item in items %}{% if item.active %}Y{% else %}N{% endif %}{% endfor %}",
            {
                "items": [
                    {"active": True},
                    {},  # missing 'active'
                    {"active": False},
                ],
            },
        )

    def test_loop_if_comparison_dict_missing_key(self, stock, cyth):
        """LOOPIF comparison with dict missing the condition key."""
        _m(
            stock,
            cyth,
            "{% for item in items %}"
            "{% if item.score == 100 %}perfect{% elif item.score >= 50 %}pass{% else %}fail{% endif %} "
            "{% endfor %}",
            {
                "items": [
                    {"score": 100},
                    {},  # missing 'score'
                    {"score": 50},
                ],
            },
        )

    def test_loop_if_incompatible_comparison(self, stock, cyth):
        """LOOPIF with incompatible comparison types should not crash."""
        _m(
            stock,
            cyth,
            "{% for item in items %}{% if item.val > 10 %}big{% else %}small{% endif %} {% endfor %}",
            {
                "items": [
                    {"val": 20},
                    {"val": "not a number"},  # str > int raises TypeError
                    {"val": 5},
                ],
            },
        )

    def test_loop_objects_missing_attribute(self, stock, cyth):
        """Object in loop missing an accessed attribute — LOOPATTR path."""

        class Book:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        _m(
            stock,
            cyth,
            "{% for book in books %}[{{ book.title }}:{{ book.price }}]{% endfor %}",
            {
                "items": [
                    Book(title="A", price=10),
                    Book(title="B"),  # missing 'price'
                ],
            },
        )

    def test_constant_var_not_cached_with_custom_tag(self, stock, cyth):
        """Constant vars should NOT be cached when custom tags exist in loop body.

        {% load %} + {% custom_tag %} in loop body could modify context,
        so constant var caching must be disabled.
        """
        # This test uses {% with %} which is a safe tag, but it changes context.
        # The key insight is that {{ greeting }} is NOT the loop var, and
        # its value changes per iteration via the inner {% with %}.
        _m(
            stock,
            cyth,
            "{% for item in items %}{% with greeting=item.msg %}{{ greeting }} {% endwith %}{% endfor %}",
            {
                "items": [
                    {"msg": "hello"},
                    {"msg": "world"},
                    {"msg": "foo"},
                ],
            },
        )

    def test_forloop_counter_in_optimized_loop(self, stock, cyth):
        """forloop.counter/counter0/revcounter/revcounter0 in loop."""
        _m(
            stock,
            cyth,
            "{% for item in items %}"
            "{{ forloop.counter }}.{{ forloop.counter0 }}"
            ".{{ forloop.revcounter }}.{{ forloop.revcounter0 }} "
            "{% endfor %}",
            {"items": ["a", "b", "c"]},
        )

    def test_loop_cycle_with_if(self, stock, cyth):
        """cycle + if in same loop body — tests LOOPCYCLE + LOOPIF interaction."""
        _m(
            stock,
            cyth,
            "{% for item in items %}"
            "{% cycle 'odd' 'even' as cls %}"
            "{% if item.active %}{{ cls }}:{{ item.name }}{% endif %} "
            "{% endfor %}",
            {
                "items": [
                    {"name": "a", "active": True},
                    {"name": "b", "active": False},
                    {"name": "c", "active": True},
                    {"name": "d", "active": True},
                ],
            },
        )

    def test_mixed_dict_and_object_loop(self, stock, cyth):
        """Loop over mix of dicts and objects — tests type dispatch per item."""

        class Obj:
            def __init__(self, name):
                self.name = name

        _m(
            stock,
            cyth,
            "{% for item in items %}{{ item.name }} {% endfor %}",
            {
                "items": [
                    {"name": "dict1"},
                    Obj("obj1"),
                    {"name": "dict2"},
                ],
            },
        )

    def test_empty_loop_with_empty_tag(self, stock, cyth):
        """{% empty %} rendered when sequence is empty."""
        _m(stock, cyth, "{% for item in items %}{{ item }}{% empty %}EMPTY{% endfor %}", {"items": []})

    def test_loop_none_sequence(self, stock, cyth):
        """Iterating over None should use {% empty %} or produce nothing."""
        _m(stock, cyth, "{% for item in items %}{{ item }}{% empty %}NONE{% endfor %}", {"items": None})

    def test_nested_loop_with_optimized_inner(self, stock, cyth):
        """Nested for loops — inner loop should be independently optimized."""
        _m(
            stock,
            cyth,
            "{% for row in rows %}[{% for cell in row.cells %}{{ cell.val }}{% endfor %}]{% endfor %}",
            {
                "rows": [
                    {"cells": [{"val": 1}, {"val": 2}]},
                    {"cells": [{"val": 3}]},
                ],
            },
        )

    def test_loop_tuple_unpacking(self, stock, cyth):
        """Tuple unpacking in for loop."""
        _m(
            stock,
            cyth,
            "{% for k, v in items %}{{ k }}={{ v }} {% endfor %}",
            {"items": [("a", 1), ("b", 2), ("c", 3)]},
        )

    def test_loop_reversed(self, stock, cyth):
        """Reversed loop iteration."""
        _m(
            stock,
            cyth,
            "{% for item in items reversed %}{{ item.name }} {% endfor %}",
            {"items": [{"name": "a"}, {"name": "b"}, {"name": "c"}]},
        )


class TestUseThousandSeparator:
    """Test that USE_THOUSAND_SEPARATOR is respected for integer rendering."""

    @override_settings(USE_THOUSAND_SEPARATOR=True, USE_L10N=True)
    def test_int_with_thousand_separator_simple(self, stock, cyth):
        """Integer values should be formatted with thousand separators."""
        # Need to reset the cached _use_thousand_sep in formats module.
        import django_templates_cythonized.formats as fmt

        old_val = fmt._use_thousand_sep
        fmt._use_thousand_sep = None
        try:
            _m(stock, cyth, "{{ val }}", {"val": 1000000})
        finally:
            fmt._use_thousand_sep = old_val

    @override_settings(USE_THOUSAND_SEPARATOR=True, USE_L10N=True)
    def test_int_with_thousand_separator_in_loop(self, stock, cyth):
        """Integer in LOOPATTR path should respect USE_THOUSAND_SEPARATOR."""
        import django_templates_cythonized.formats as fmt

        old_val = fmt._use_thousand_sep
        fmt._use_thousand_sep = None
        try:
            _m(
                stock,
                cyth,
                "{% for item in items %}{{ item.price }} {% endfor %}",
                {"items": [{"price": 1234567}, {"price": 42}, {"price": 100000}]},
            )
        finally:
            fmt._use_thousand_sep = old_val


# ---------------------------------------------------------------------------
# Production-readiness tests — critical features, regression tests for bug fixes
# ---------------------------------------------------------------------------


class TestLoopIfConstNestedOperators:
    """Regression tests for LOOPIF_CONST with compound and/or/not conditions.

    Bug: nested Operator trees were not recursively inspected for loop variable
    references. A condition like `{% if flag and book.active %}` could be
    incorrectly classified as constant when `book` is the loop variable.
    """

    def test_compound_and_with_loop_var(self, stock, cyth):
        """{% if const_flag and item.attr %} must NOT be treated as constant."""
        _m(
            stock,
            cyth,
            "{% for item in items %}{% if show and item.active %}Y{% else %}N{% endif %}{% endfor %}",
            {"items": [{"active": True}, {"active": False}, {"active": True}], "show": True},
        )

    def test_compound_or_with_loop_var(self, stock, cyth):
        """{% if const_flag or item.attr %} must NOT be treated as constant."""
        _m(
            stock,
            cyth,
            "{% for item in items %}{% if fallback or item.val %}Y{% else %}N{% endif %}{% endfor %}",
            {"items": [{"val": True}, {"val": False}, {"val": True}], "fallback": False},
        )

    def test_not_with_loop_var(self, stock, cyth):
        """{% if not item.attr %} must NOT be treated as constant."""
        _m(
            stock,
            cyth,
            "{% for item in items %}{% if not item.hidden %}visible{% else %}hidden{% endif %} {% endfor %}",
            {"items": [{"hidden": False}, {"hidden": True}, {"hidden": False}]},
        )

    def test_deeply_nested_compound(self, stock, cyth):
        """Compound condition with 3 terms where loop var is deeply nested."""
        _m(
            stock,
            cyth,
            "{% for item in items %}{% if flag1 and flag2 or item.x %}Y{% else %}N{% endif %}{% endfor %}",
            {"items": [{"x": True}, {"x": False}], "flag1": False, "flag2": False},
        )

    def test_truly_constant_compound_condition(self, stock, cyth):
        """{% if flag1 and flag2 %} (no loop var) IS correctly treated as constant."""
        _m(
            stock,
            cyth,
            "{% for item in items %}{% if show_all and verbose %}[{{ item.name }}]{% endif %}{% endfor %}",
            {"items": [{"name": "a"}, {"name": "b"}], "show_all": True, "verbose": True},
        )


class TestResetCycle:
    """Comprehensive resetcycle tests from Django's test suite."""

    def test_resetcycle_resets_cycle_counter(self, stock, cyth):
        """{% resetcycle %} should restart the cycle from the beginning."""
        _m(
            stock,
            cyth,
            "{% for item in items %}"
            "{% cycle 'a' 'b' 'c' as cls %}"
            "{% if item.reset %}{% resetcycle cls %}{% endif %}"
            "{{ cls }},"
            "{% endfor %}",
            {
                "items": [
                    {"reset": False},
                    {"reset": True},  # resets cycle
                    {"reset": False},  # should restart from 'a'
                    {"reset": False},
                ],
            },
        )

    def test_cycle_without_resetcycle_uses_inline(self, stock, cyth):
        """Cycle without resetcycle should still produce correct output."""
        _m(
            stock,
            cyth,
            "{% for item in items %}{% cycle 'odd' 'even' as row %}{{ row }}:{{ item }} {% endfor %}",
            {"items": ["a", "b", "c", "d"]},
        )

    def test_resetcycle_no_cycles(self, cyth):
        """resetcycle with no cycles should raise TemplateSyntaxError."""
        with pytest.raises(TemplateSyntaxError, match="No cycles in template"):
            cyth.from_string("{% resetcycle %}")

    def test_resetcycle_undefined(self, cyth):
        """resetcycle with undefined name should raise TemplateSyntaxError."""
        with pytest.raises(TemplateSyntaxError, match="does not exist"):
            cyth.from_string("{% resetcycle undefinedcycle %}")

    def test_resetcycle_undefined_with_cycle(self, cyth):
        """resetcycle with undefined name when unnamed cycle exists."""
        with pytest.raises(TemplateSyntaxError, match="does not exist"):
            cyth.from_string("{% cycle 'a' 'b' %}{% resetcycle undefinedcycle %}")

    def test_resetcycle_undefined_with_named_cycle(self, cyth):
        """resetcycle with undefined name when different named cycle exists."""
        with pytest.raises(TemplateSyntaxError, match="does not exist"):
            cyth.from_string("{% cycle 'a' 'b' as ab %}{% resetcycle undefinedcycle %}")

    def test_resetcycle_simple(self, stock, cyth):
        """Simple unnamed resetcycle resets the cycle each iteration."""
        _m(stock, cyth, "{% for i in test %}{% cycle 'a' 'b' %}{% resetcycle %}{% endfor %}", {"test": list(range(5))})

    def test_resetcycle_multiple_cycles(self, stock, cyth):
        """Named cycle from outside loop + unnamed cycle in loop.
        Unnamed resetcycle resets the LAST cycle (unnamed one)."""
        _m(
            stock,
            cyth,
            "{% cycle 'a' 'b' 'c' as abc %}"
            "{% for i in test %}"
            "{% cycle abc %}"
            "{% cycle '-' '+' %}"
            "{% resetcycle %}"
            "{% endfor %}",
            {"test": list(range(5))},
        )

    def test_resetcycle_named_reset(self, stock, cyth):
        """resetcycle with name resets only the named cycle."""
        _m(
            stock,
            cyth,
            "{% cycle 'a' 'b' 'c' as abc %}"
            "{% for i in test %}"
            "{% resetcycle abc %}"
            "{% cycle abc %}"
            "{% cycle '-' '+' %}"
            "{% endfor %}",
            {"test": list(range(5))},
        )

    def test_resetcycle_nested_loops(self, stock, cyth):
        """resetcycle in outer loop resets inner loop's cycle."""
        _m(
            stock,
            cyth,
            "{% for i in outer %}{% for j in inner %}{% cycle 'a' 'b' %}{% endfor %}{% resetcycle %}{% endfor %}",
            {"outer": list(range(2)), "inner": list(range(3))},
        )

    def test_resetcycle_nested_multiple_cycles(self, stock, cyth):
        """Nested loops with multiple cycles and resetcycle."""
        _m(
            stock,
            cyth,
            "{% for i in outer %}"
            "{% cycle 'a' 'b' %}"
            "{% for j in inner %}"
            "{% cycle 'X' 'Y' %}"
            "{% endfor %}"
            "{% resetcycle %}"
            "{% endfor %}",
            {"outer": list(range(2)), "inner": list(range(3))},
        )

    def test_resetcycle_conditional(self, stock, cyth):
        """Conditional resetcycle on specific named cycle."""
        _m(
            stock,
            cyth,
            "{% for i in test %}"
            "{% cycle 'X' 'Y' 'Z' as XYZ %}"
            "{% cycle 'a' 'b' 'c' as abc %}"
            "{% if i == 1 %}"
            "{% resetcycle abc %}"
            "{% endif %}"
            "{% endfor %}",
            {"test": list(range(5))},
        )

    def test_resetcycle_conditional_other(self, stock, cyth):
        """Conditional resetcycle on the other named cycle."""
        _m(
            stock,
            cyth,
            "{% for i in test %}"
            "{% cycle 'X' 'Y' 'Z' as XYZ %}"
            "{% cycle 'a' 'b' 'c' as abc %}"
            "{% if i == 1 %}"
            "{% resetcycle XYZ %}"
            "{% endif %}"
            "{% endfor %}",
            {"test": list(range(5))},
        )


class TestRequestContext:
    """Tests for RequestContext rendering (cclass/Python class boundary)."""

    def test_request_context_rendering(self, stock, cyth):
        """RequestContext should render templates identically via backend.render()."""
        factory = RequestFactory()
        request = factory.get("/")

        stock_tpl = stock.from_string("Hello {{ name }}!")
        cyth_tpl = cyth.from_string("Hello {{ name }}!")

        # Backend .render() creates RequestContext internally when request is provided
        stock_result = stock_tpl.render({"name": "World"}, request=request)
        cyth_result = cyth_tpl.render({"name": "World"}, request=request)

        assert cyth_result == stock_result

    def test_request_context_with_variables(self, stock, cyth):
        """RequestContext rendering with loops and filters."""
        factory = RequestFactory()
        request = factory.get("/")

        tpl_str = "{% for item in items %}{{ item|upper }} {% endfor %}"
        stock_result = stock.from_string(tpl_str).render({"items": ["hello", "world"]}, request=request)
        cyth_result = cyth.from_string(tpl_str).render({"items": ["hello", "world"]}, request=request)

        assert cyth_result == stock_result

    def test_request_context_direct_construction(self):
        """Our RequestContext (regular class inheriting from cclass) works."""
        from django_templates_cythonized.context import RequestContext as CythRequestContext

        factory = RequestFactory()
        request = factory.get("/")

        ctx = CythRequestContext(request, {"name": "World"})
        assert ctx["name"] == "World"
        assert ctx.autoescape is True
        assert ctx.request is request


class TestUseTZ:
    """Tests for USE_TZ=True with timezone-aware datetime values."""

    @override_settings(USE_TZ=True)
    def test_aware_datetime_rendering(self, stock, cyth):
        """Timezone-aware datetime should render identically with USE_TZ=True."""
        import zoneinfo

        tz = zoneinfo.ZoneInfo("UTC")
        dt = datetime.datetime(2024, 6, 15, 14, 30, 0, tzinfo=tz)
        _m(stock, cyth, "{{ dt }}", {"dt": dt})

    @override_settings(USE_TZ=True)
    def test_naive_datetime_rendering(self, stock, cyth):
        """Naive datetime with USE_TZ=True should render identically."""
        dt = datetime.datetime(2024, 6, 15, 14, 30, 0)
        _m(stock, cyth, "{{ dt }}", {"dt": dt})

    @override_settings(USE_TZ=True)
    def test_date_rendering_with_use_tz(self, stock, cyth):
        """Date (not datetime) should render identically with USE_TZ=True."""
        d = datetime.date(2024, 6, 15)
        _m(stock, cyth, "{{ d }}", {"d": d})


class TestCsrfToken:
    """Tests for {% csrf_token %} tag."""

    def test_csrf_token_renders_input(self, stock, cyth):
        """{% csrf_token %} should produce identical output."""
        _m(stock, cyth, "{% csrf_token %}", {"csrf_token": "abc123"})

    def test_csrf_token_missing(self, stock, cyth):
        """{% csrf_token %} with no csrf_token in context should match stock."""
        _m(stock, cyth, "{% csrf_token %}", {})


class TestUrlTag:
    """Tests for {% url %} tag (requires URL configuration)."""

    @override_settings(ROOT_URLCONF="tests.urls")
    def test_url_basic(self, stock, cyth):
        """{% url 'home' %} should resolve identically."""
        _m(stock, cyth, "{% url 'home' %}")

    @override_settings(ROOT_URLCONF="tests.urls")
    def test_url_with_args(self, stock, cyth):
        """{% url 'detail' pk %} should resolve identically."""
        _m(stock, cyth, "{% url 'detail' pk=42 %}")

    @override_settings(ROOT_URLCONF="tests.urls")
    def test_url_as_variable(self, stock, cyth):
        """{% url 'home' as link %} should resolve identically."""
        _m(stock, cyth, "{% url 'home' as link %}[{{ link }}]")


class TestWithTag:
    """Tests for {% with %} legacy and modern syntax."""

    def test_with_keyword_syntax(self, stock, cyth):
        """{% with x='hello' %} modern syntax."""
        _m(stock, cyth, "{% with greeting='hello' %}{{ greeting }}{% endwith %}")

    def test_with_legacy_syntax(self, stock, cyth):
        """{% with user.name as fullname %} legacy syntax."""
        _m(stock, cyth, "{% with user.name as fullname %}{{ fullname }}{% endwith %}", {"user": {"name": "Alice"}})


class TestFormatHtml:
    """Tests for format_html utility function."""

    def test_format_html_empty_args_raises(self):
        """format_html() without args or kwargs should raise TypeError."""
        from django_templates_cythonized.html import format_html

        with pytest.raises(TypeError, match="args or kwargs must be provided"):
            format_html("hello")

    def test_format_html_with_args(self):
        """format_html() with positional args should escape them."""
        from django_templates_cythonized.html import format_html

        result = format_html("<b>{}</b>", "<script>")
        assert "&lt;script&gt;" in result

    def test_format_html_with_kwargs(self):
        """format_html() with keyword args should escape them."""
        from django_templates_cythonized.html import format_html

        result = format_html("<b>{name}</b>", name="<script>")
        assert "&lt;script&gt;" in result


class TestForLoopEdgeCases:
    """Edge cases for ForNode optimization paths."""

    def test_loop_empty_list(self, stock, cyth):
        """Empty list renders empty nodelist."""
        _m(stock, cyth, "{% for x in items %}{{ x }}{% empty %}EMPTY{% endfor %}", {"items": []})

    def test_loop_reversed(self, stock, cyth):
        """{% for x in items reversed %} iterates in reverse."""
        _m(stock, cyth, "{% for x in items reversed %}{{ x }},{% endfor %}", {"items": [1, 2, 3]})

    def test_loop_nested_parentloop(self, stock, cyth):
        """Nested loops expose parentloop correctly."""
        _m(
            stock,
            cyth,
            "{% for row in rows %}{% for col in cols %}"
            "{{ forloop.parentloop.counter }}:{{ forloop.counter }},"
            "{% endfor %}{% endfor %}",
            {"rows": ["a", "b"], "cols": [1, 2]},
        )

    def test_loop_unpack_multiple_vars(self, stock, cyth):
        """{% for k, v in items %} unpacks correctly."""
        _m(stock, cyth, "{% for k, v in items %}{{ k }}={{ v }},{% endfor %}", {"items": [("a", 1), ("b", 2)]})

    def test_loopattr_object_not_dict(self, stock, cyth):
        """LOOPATTR resolves object attributes (not just dict keys)."""
        items = [SimpleObj(name="Alice"), SimpleObj(name="Bob")]
        _m(stock, cyth, "{% for item in items %}{{ item.name }},{% endfor %}", {"items": items})

    def test_loopattr_callable_fallback(self, stock, cyth):
        """LOOPATTR falls back correctly when attr is a callable method."""
        items = [CallableObj("hello"), CallableObj("world")]
        _m(stock, cyth, "{% for item in items %}{{ item.get_value }},{% endfor %}", {"items": items})

    def test_loopattr_missing_attr(self, stock, cyth):
        """LOOPATTR handles missing attributes gracefully."""
        items = [{"name": "Alice"}, {"age": 30}]
        _m(stock, cyth, "{% for item in items %}{{ item.name }},{% endfor %}", {"items": items})

    def test_loopattr_none_value(self, stock, cyth):
        """LOOPATTR handles None attribute values."""
        items = [{"name": None}, {"name": "Bob"}]
        _m(stock, cyth, "{% for item in items %}{{ item.name }},{% endfor %}", {"items": items})

    def test_loopattr_html_escape(self, stock, cyth):
        """LOOPATTR escapes HTML in string values."""
        items = [{"name": "<b>Alice</b>"}, {"name": "Bob"}]
        _m(stock, cyth, "{% for item in items %}{{ item.name }},{% endfor %}", {"items": items})

    def test_loopattr_safestring(self, stock, cyth):
        """LOOPATTR preserves SafeString values."""
        items = [{"name": mark_safe("<b>Alice</b>")}, {"name": "Bob"}]
        _m(stock, cyth, "{% for item in items %}{{ item.name }},{% endfor %}", {"items": items})

    def test_loopattr_float_value(self, stock, cyth):
        """LOOPATTR handles float values correctly."""
        items = [{"price": 19.99}, {"price": 0.5}]
        _m(stock, cyth, "{% for item in items %}{{ item.price }},{% endfor %}", {"items": items})

    def test_loopattr_bool_value(self, stock, cyth):
        """LOOPATTR handles bool values (bool is subclass of int)."""
        items = [{"active": True}, {"active": False}]
        _m(stock, cyth, "{% for item in items %}{{ item.active }},{% endfor %}", {"items": items})

    def test_loopattr_with_filter(self, stock, cyth):
        """LOOPATTR_FILTER path handles filter application."""
        items = [{"name": "alice"}, {"name": "bob"}]
        _m(stock, cyth, "{% for item in items %}{{ item.name|upper }},{% endfor %}", {"items": items})

    def test_loopattr_filter_callable_fallback(self, stock, cyth):
        """LOOPATTR_FILTER falls back when attr is callable."""
        items = [CallableObj("hello"), CallableObj("world")]
        _m(stock, cyth, "{% for item in items %}{{ item.get_value|upper }},{% endfor %}", {"items": items})


class TestLoopIfEdgeCases:
    """Edge cases for LOOPIF and LOOPIF_CONST optimization paths."""

    def test_loopif_not_operator(self, stock, cyth):
        """{% if not book.attr %} with not prefix operator."""
        books = [
            {"title": "A", "out_of_stock": True},
            {"title": "B", "out_of_stock": False},
            {"title": "C", "out_of_stock": None},
        ]
        _m(
            stock,
            cyth,
            "{% for book in books %}{% if not book.out_of_stock %}{{ book.title }},{% endif %}{% endfor %}",
            {"books": books},
        )

    def test_loopif_boolean_truthiness(self, stock, cyth):
        """LOOPIF simple boolean truthiness test."""
        books = [{"title": "A", "active": True}, {"title": "B", "active": False}, {"title": "C", "active": ""}]
        _m(
            stock,
            cyth,
            "{% for book in books %}{% if book.active %}{{ book.title }},{% endif %}{% endfor %}",
            {"books": books},
        )

    def test_loopif_none_comparison(self, stock, cyth):
        """LOOPIF comparing attribute against None."""
        items = [{"val": None}, {"val": 0}, {"val": ""}]
        _m(
            stock,
            cyth,
            "{% for item in items %}{% if item.val == None %}null,{% else %}val,{% endif %}{% endfor %}",
            {"items": items},
        )

    def test_loopif_missing_attr(self, stock, cyth):
        """LOOPIF handles missing attributes (should not crash)."""
        items = [{"status": "active"}, {"name": "Bob"}]
        _m(
            stock,
            cyth,
            "{% for item in items %}{% if item.status == 'active' %}yes,{% else %}no,{% endif %}{% endfor %}",
            {"items": items},
        )

    def test_loopif_incompatible_types(self, stock, cyth):
        """LOOPIF handles comparison between incompatible types."""
        items = [{"val": "abc"}, {"val": 42}]
        _m(
            stock,
            cyth,
            "{% for item in items %}{% if item.val > 10 %}big,{% else %}small,{% endif %}{% endfor %}",
            {"items": items},
        )

    def test_loopif_const_not_prefix(self, stock, cyth):
        """LOOPIF_CONST with not prefix operator on constant."""
        _m(
            stock,
            cyth,
            "{% for x in items %}{% if not show_all %}{{ x }},{% endif %}{% endfor %}",
            {"items": [1, 2, 3], "show_all": False},
        )

    def test_loopif_const_and_operator(self, stock, cyth):
        """LOOPIF_CONST falls back correctly for compound and/or."""
        _m(
            stock,
            cyth,
            "{% for x in items %}{% if flag_a and flag_b %}{{ x }},{% endif %}{% endfor %}",
            {"items": [1, 2, 3], "flag_a": True, "flag_b": True},
        )

    def test_loopif_const_loop_var_in_compound(self, stock, cyth):
        """Compound condition with loop var should NOT be classified as const."""
        items = [{"val": 1}, {"val": 2}, {"val": 3}]
        _m(
            stock,
            cyth,
            "{% for item in items %}{% if item.val > 1 and flag %}{{ item.val }},{% endif %}{% endfor %}",
            {"items": items, "flag": True},
        )

    def test_loopif_multiple_elif(self, stock, cyth):
        """LOOPIF with multiple elif branches."""
        items = [{"status": "active"}, {"status": "pending"}, {"status": "inactive"}, {"status": "unknown"}]
        _m(
            stock,
            cyth,
            "{% for item in items %}"
            "{% if item.status == 'active' %}A,"
            "{% elif item.status == 'pending' %}P,"
            "{% elif item.status == 'inactive' %}I,"
            "{% else %}?,"
            "{% endif %}"
            "{% endfor %}",
            {"items": items},
        )

    def test_loopif_different_attrs_per_branch(self, stock, cyth):
        """LOOPIF with different attributes in each condition branch."""
        items = [{"price": 100, "qty": 5}, {"price": 50, "qty": 0}, {"price": 200, "qty": 10}]
        _m(
            stock,
            cyth,
            "{% for item in items %}"
            "{% if item.price > 99 %}expensive,"
            "{% elif item.qty == 0 %}oos,"
            "{% else %}ok,"
            "{% endif %}"
            "{% endfor %}",
            {"items": items},
        )


class TestForloopCounterEdgeCases:
    """Edge cases for FORLOOP_COUNTER inline optimization."""

    def test_forloop_counter(self, stock, cyth):
        """{{ forloop.counter }} starts at 1."""
        _m(stock, cyth, "{% for x in items %}{{ forloop.counter }},{% endfor %}", {"items": "abc"})

    def test_forloop_counter0(self, stock, cyth):
        """{{ forloop.counter0 }} starts at 0."""
        _m(stock, cyth, "{% for x in items %}{{ forloop.counter0 }},{% endfor %}", {"items": "abc"})

    def test_forloop_revcounter(self, stock, cyth):
        """{{ forloop.revcounter }} counts down to 1."""
        _m(stock, cyth, "{% for x in items %}{{ forloop.revcounter }},{% endfor %}", {"items": "abc"})

    def test_forloop_revcounter0(self, stock, cyth):
        """{{ forloop.revcounter0 }} counts down to 0."""
        _m(stock, cyth, "{% for x in items %}{{ forloop.revcounter0 }},{% endfor %}", {"items": "abc"})

    def test_forloop_first_last(self, stock, cyth):
        """{{ forloop.first }} and {{ forloop.last }} work correctly."""
        _m(
            stock,
            cyth,
            "{% for x in items %}"
            "{% if forloop.first %}[{% endif %}"
            "{{ x }}"
            "{% if forloop.last %}]{% endif %}"
            "{% if not forloop.last %},{% endif %}"
            "{% endfor %}",
            {"items": [1, 2, 3]},
        )

    def test_forloop_single_item(self, stock, cyth):
        """Single-item loop: first and last both True."""
        _m(
            stock,
            cyth,
            "{% for x in items %}{{ forloop.counter }},{{ forloop.first }},{{ forloop.last }}{% endfor %}",
            {"items": [42]},
        )


class TestLoopCycleEdgeCases:
    """Edge cases for LOOPCYCLE inline optimization."""

    def test_cycle_basic(self, stock, cyth):
        """Basic cycle in a loop."""
        _m(stock, cyth, "{% for x in items %}{% cycle 'a' 'b' 'c' %},{% endfor %}", {"items": [1, 2, 3, 4, 5]})

    def test_cycle_as_variable(self, stock, cyth):
        """{% cycle ... as var %} sets variable in context."""
        _m(
            stock,
            cyth,
            "{% for x in items %}{% cycle 'odd' 'even' as rowclass %}{{ rowclass }}-{{ x }},{% endfor %}",
            {"items": [1, 2, 3, 4]},
        )

    def test_cycle_silent(self, stock, cyth):
        """{% cycle ... as var silent %} does not output."""
        _m(
            stock,
            cyth,
            "{% for x in items %}{% cycle 'a' 'b' as cls silent %}[{{ cls }}]{% endfor %}",
            {"items": [1, 2, 3]},
        )


class TestConstVarCacheEdgeCases:
    """Edge cases for constant variable caching optimization."""

    def test_const_var_cached(self, stock, cyth):
        """Constant variable (not referencing loop var) renders correctly."""
        _m(stock, cyth, "{% for x in items %}{{ prefix }}-{{ x }},{% endfor %}", {"items": [1, 2, 3], "prefix": "item"})

    def test_const_var_with_cycle_variable(self, stock, cyth):
        """Constant var is NOT cached when cycle writes to same name."""
        _m(
            stock,
            cyth,
            "{% for x in items %}{% cycle 'a' 'b' as rowclass %}{{ rowclass }}-{{ x }},{% endfor %}",
            {"items": [1, 2, 3, 4]},
        )

    def test_const_var_deep_lookup(self, stock, cyth):
        """Constant var with multi-segment lookup (e.g. settings.name)."""
        _m(
            stock,
            cyth,
            "{% for x in items %}{{ config.prefix }}-{{ x }},{% endfor %}",
            {"items": [1, 2, 3], "config": {"prefix": "v"}},
        )

    def test_const_var_with_custom_tag_present(self, stock, cyth):
        """Constant var caching disabled when non-standard nodes present."""
        _m(
            stock,
            cyth,
            "{% load custom_tags %}{% for x in items %}{% greeting 'World' %}{{ currency }}-{{ x }},{% endfor %}",
            {"items": [1, 2, 3], "currency": "USD"},
        )


# ---------------------------------------------------------------------------
# Include flattening tests
# ---------------------------------------------------------------------------


class TestIncludeFlattening:
    """Tests for compile-time include flattening."""

    def test_simple_include_flattened(self, stock, cyth):
        """Basic include produces same output after flattening."""
        _m(stock, cyth, '{% include "flat_outer.html" %}', {"inner_val": "hello"})

    def test_chained_includes_flattened(self, stock, cyth):
        """A -> B -> C include chain produces correct output."""
        _m(stock, cyth, '{% include "flat_chain_a.html" %}', {"c_val": "deep"})

    def test_include_in_for_loop(self, stock, cyth):
        """Include inside for loop produces same output."""
        _m(
            stock,
            cyth,
            '{% for item in items %}{% include "flat_inner.html" %}{% endfor %}',
            {"items": [{"inner_val": "a"}, {"inner_val": "b"}], "inner_val": "fallback"},
        )

    def test_include_with_extra_context_not_flattened(self, stock, cyth):
        """Include with extra context is NOT flattened but still works."""
        _m(stock, cyth, '{% include "include_target.html" with message="hi" %}', {})

    def test_include_with_isolated_context_not_flattened(self, stock, cyth):
        """Include with only keyword is NOT flattened but still works."""
        _m(stock, cyth, '{% include "include_target.html" with message="hi" only %}', {"message": "should_not_appear"})

    def test_include_variable_template_not_flattened(self, stock, cyth):
        """Include with variable template name is NOT flattened."""
        _m(stock, cyth, "{% include tpl_name %}", {"tpl_name": "include_target.html", "message": "dynamic"})

    def test_include_in_if_branch(self, stock, cyth):
        """Include inside an if branch is correctly flattened."""
        _m(
            stock,
            cyth,
            '{% if show %}{% include "flat_inner.html" %}{% endif %}',
            {"show": True, "inner_val": "visible"},
        )

    def test_include_in_if_branch_false(self, stock, cyth):
        """Include in if branch that's not taken still renders correctly."""
        _m(
            stock,
            cyth,
            '{% if show %}{% include "flat_inner.html" %}{% else %}none{% endif %}',
            {"show": False, "inner_val": "invisible"},
        )


# ---------------------------------------------------------------------------
# LOOPIF is/is not operator tests
# ---------------------------------------------------------------------------


class TestLoopIfIsOperators:
    """Tests for is/is not operators in LOOPIF-classified for loops."""

    def test_is_true(self, stock, cyth):
        """{% if item.flag is True %} inside a for loop."""
        _m(
            stock,
            cyth,
            "{% for item in items %}{% if item.flag is True %}T{% else %}F{% endif %}{% endfor %}",
            {"items": [{"flag": True}, {"flag": False}, {"flag": None}, {"flag": 1}]},
        )

    def test_is_false(self, stock, cyth):
        """{% if item.flag is False %} inside a for loop."""
        _m(
            stock,
            cyth,
            "{% for item in items %}{% if item.flag is False %}F{% else %}T{% endif %}{% endfor %}",
            {"items": [{"flag": True}, {"flag": False}, {"flag": None}, {"flag": 0}]},
        )

    def test_is_none(self, stock, cyth):
        """{% if item.val is None %} inside a for loop."""
        _m(
            stock,
            cyth,
            "{% for item in items %}{% if item.val is None %}N{% else %}V{% endif %}{% endfor %}",
            {"items": [{"val": None}, {"val": ""}, {"val": 0}, {"val": "x"}]},
        )

    def test_is_not_false(self, stock, cyth):
        """{% if item.val is not False %} — the attrs.html pattern."""
        _m(
            stock,
            cyth,
            "{% for item in items %}{% if item.val is not False %}[{{ item.val }}]{% endif %}{% endfor %}",
            {"items": [{"val": "a"}, {"val": False}, {"val": True}, {"val": ""}]},
        )

    def test_is_not_true(self, stock, cyth):
        """{% if item.val is not True %} — the attrs.html value display."""
        _m(
            stock,
            cyth,
            "{% for item in items %}{% if item.val is not True %}={{ item.val }}{% else %}!{% endif %}{% endfor %}",
            {"items": [{"val": "a"}, {"val": True}, {"val": False}, {"val": 42}]},
        )

    def test_is_not_none(self, stock, cyth):
        """{% if item.val is not None %} inside a for loop."""
        _m(
            stock,
            cyth,
            "{% for item in items %}{% if item.val is not None %}[{{ item.val }}]{% endif %}{% endfor %}",
            {"items": [{"val": "a"}, {"val": None}, {"val": 0}, {"val": ""}]},
        )

    def test_attrs_pattern(self, stock, cyth):
        """Full attrs.html pattern: is not False + is not True combo."""
        _m(
            stock,
            cyth,
            "{% for name, value in attrs.items %}"
            "{% if value is not False %} {{ name }}"
            '{% if value is not True %}="{{ value }}"{% endif %}'
            "{% endif %}"
            "{% endfor %}",
            {"attrs": {"class": "form-control", "required": True, "disabled": False, "id": "my-input"}},
        )

    def test_is_identity_not_equality(self, stock, cyth):
        """is checks identity, not equality. 0 is not False, '' is not False."""
        _m(
            stock,
            cyth,
            "{% for item in items %}{% if item.v is False %}F{% else %}NF{% endif %}{% endfor %}",
            {"items": [{"v": False}, {"v": 0}, {"v": ""}, {"v": None}]},
        )


# ---------------------------------------------------------------------------
# Context operations (from Django's test_context.py)
# ---------------------------------------------------------------------------


class TestContextOperations:
    """Tests for Context push/pop/set_upward/flatten/new/update."""

    def test_push_pop(self, stock, cyth):
        _m(stock, cyth, "{% with x=1 %}{{ x }}{% endwith %}{{ x }}", {"x": "outer"})

    def test_nested_push(self, stock, cyth):
        _m(stock, cyth, "{% with x=1 %}{% with x=2 %}{{ x }}{% endwith %}{{ x }}{% endwith %}", {})

    def test_set_upward_via_cycle(self, stock, cyth):
        """cycle 'as' uses set_upward — verify it works across scopes."""
        _m(
            stock,
            cyth,
            "{% for i in items %}{% cycle 'a' 'b' as rowclass %}{{ rowclass }}{% endfor %}",
            {"items": [1, 2, 3, 4]},
        )

    def test_flatten_via_include_only(self, stock, cyth):
        """{% include ... only %} uses context.new() which calls flatten internally."""
        _m(stock, cyth, "{% include 'flat_inner.html' only %}", {"greeting": "hello"})

    def test_context_update(self, stock, cyth):
        """{% with %} is effectively context.update/push."""
        _m(stock, cyth, "{% with a=1 b=2 %}{{ a }}-{{ b }}{% endwith %}", {})

    def test_context_has_builtins(self, stock, cyth):
        """True, False, None should be available in any context."""
        _m(stock, cyth, "{{ True }}-{{ False }}-{{ None }}", {})

    def test_context_overrides_builtins(self, stock, cyth):
        """Context values should override builtins like True/False/None."""
        _m(stock, cyth, "{{ True }}", {"True": "overridden"})


# ---------------------------------------------------------------------------
# TEMPLATE_STRING_IF_INVALID (from Django's test_invalid_string.py)
# ---------------------------------------------------------------------------


class TestStringIfInvalid:
    """Tests that string_if_invalid is respected for missing variables."""

    @pytest.fixture
    def stock_inv(self):
        from django.template import Engine

        return Engine(string_if_invalid="INVALID")

    @pytest.fixture
    def cyth_inv(self):
        from django_templates_cythonized.engine import Engine

        return Engine(string_if_invalid="INVALID")

    def test_missing_var(self, stock_inv, cyth_inv):
        from django.template import Context

        from django_templates_cythonized.context import Context as CContext

        s = stock_inv.from_string("{{ missing }}").render(Context())
        c = cyth_inv.from_string("{{ missing }}").render(CContext())
        assert c == s == "INVALID"

    def test_missing_var_with_filter(self, stock_inv, cyth_inv):
        from django.template import Context

        from django_templates_cythonized.context import Context as CContext

        s = stock_inv.from_string("{{ missing|default:'fallback' }}").render(Context())
        c = cyth_inv.from_string("{{ missing|default:'fallback' }}").render(CContext())
        assert c == s

    def test_present_var(self, stock_inv, cyth_inv):
        from django.template import Context

        from django_templates_cythonized.context import Context as CContext

        s = stock_inv.from_string("{{ x }}").render(Context({"x": "hello"}))
        c = cyth_inv.from_string("{{ x }}").render(CContext({"x": "hello"}))
        assert c == s == "hello"

    def test_empty_string_if_invalid(self, stock, cyth):
        """Default string_if_invalid='' — missing vars produce empty string."""
        _m(stock, cyth, "{{ missing }}", {})


# ---------------------------------------------------------------------------
# Callable edge cases (from Django's test_callables.py)
# ---------------------------------------------------------------------------


class AltersDataObj:
    def dangerous(self):
        return "DANGER"

    dangerous.alters_data = True

    def safe_method(self):
        return "SAFE"


class DoNotCallWholeObj:
    def __init__(self, val):
        self.val = val

    def __call__(self):
        return "SHOULD NOT SEE THIS"

    do_not_call_in_templates = True

    def __str__(self):
        return self.val


class TestCallables:
    """Tests for callable handling: alters_data, do_not_call_in_templates."""

    def test_callable_method(self, stock, cyth):
        _m(stock, cyth, "{{ obj.get_value }}", {"obj": CallableObj("hello")})

    def test_alters_data(self, stock, cyth):
        """Methods with alters_data=True should produce empty string."""
        _m(stock, cyth, "{{ obj.dangerous }}", {"obj": AltersDataObj()})

    def test_do_not_call_whole_object(self, stock, cyth):
        """Objects with do_not_call_in_templates use __str__ instead."""
        _m(stock, cyth, "{{ obj }}", {"obj": DoNotCallWholeObj("my-value")})

    def test_alters_data_propagation(self, stock, cyth):
        """Non-alters_data methods should render normally."""
        _m(stock, cyth, "{{ obj.safe_method }}", {"obj": AltersDataObj()})


# ---------------------------------------------------------------------------
# Missing filter tests
# ---------------------------------------------------------------------------


class TestFilterDictsort:
    def test_basic(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{% for item in items|dictsort:'name' %}{{ item.name }},{% endfor %}",
            {"items": [{"name": "c"}, {"name": "a"}, {"name": "b"}]},
        )

    def test_reversed(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{% for item in items|dictsortreversed:'name' %}{{ item.name }},{% endfor %}",
            {"items": [{"name": "c"}, {"name": "a"}, {"name": "b"}]},
        )

    def test_nested_key(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{% for item in items|dictsort:'info.age' %}{{ item.name }},{% endfor %}",
            {
                "items": [
                    {"name": "b", "info": {"age": 30}},
                    {"name": "a", "info": {"age": 20}},
                    {"name": "c", "info": {"age": 25}},
                ],
            },
        )


class TestFilterTimesince:
    def test_basic(self, stock, cyth):
        import datetime as dt

        now = dt.datetime(2025, 6, 15, 12, 0, 0)
        past = now - dt.timedelta(days=3, hours=5)
        _m(stock, cyth, "{{ past|timesince:now }}", {"past": past, "now": now})

    def test_timeuntil(self, stock, cyth):
        import datetime as dt

        now = dt.datetime(2025, 6, 15, 12, 0, 0)
        future = now + dt.timedelta(days=2, hours=3)
        _m(stock, cyth, "{{ future|timeuntil:now }}", {"future": future, "now": now})


class TestFilterUrlize:
    def test_url(self, stock, cyth):
        _m(stock, cyth, "{{ text|urlize }}", {"text": "Visit https://example.com today"})

    def test_urlizetrunc(self, stock, cyth):
        _m(stock, cyth, "{{ text|urlizetrunc:15 }}", {"text": "Visit https://example.com/very/long/path today"})

    def test_email(self, stock, cyth):
        _m(stock, cyth, "{{ text|urlize }}", {"text": "Email me at user@example.com"})


class TestFilterTruncateHtml:
    def test_truncatechars_html(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{{ text|truncatechars_html:25 }}",
            {"text": "<p>Hello <b>beautiful</b> world, this is long</p>"},
        )

    def test_truncatewords_html(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{{ text|truncatewords_html:3 }}",
            {"text": "<p>Hello <b>beautiful</b> world, this is long</p>"},
        )


class TestFilterSafeseq:
    def test_safeseq_join(self, stock, cyth):
        _m(stock, cyth, '{{ items|safeseq|join:", " }}', {"items": ["<b>a</b>", "<i>b</i>"]})


class TestFilterUnorderedList:
    def test_basic(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{{ items|unordered_list }}",
            {"items": ["States", ["Kansas", ["Lawrence", "Topeka"], "Illinois"]]},
        )


class TestFilterLinenumbers:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{{ text|linenumbers }}", {"text": "line one\nline two\nline three"})


class TestFilterPhone2numeric:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{{ phone|phone2numeric }}", {"phone": "1-800-COLLECT"})


class TestFilterGetDigit:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{{ num|get_digit:'2' }}", {"num": 123})

    def test_invalid(self, stock, cyth):
        _m(stock, cyth, "{{ num|get_digit:'0' }}", {"num": 123})


class TestFilterIriencode:
    def test_basic(self, stock, cyth):
        _m(stock, cyth, "{{ url|iriencode }}", {"url": "/path/to/page?q=hello world"})


class TestFilterLjustRjust:
    def test_ljust(self, stock, cyth):
        _m(stock, cyth, "{{ val|ljust:'10' }}", {"val": "hi"})

    def test_rjust(self, stock, cyth):
        _m(stock, cyth, "{{ val|rjust:'10' }}", {"val": "hi"})


class TestFilterEscapeseq:
    """Django 5.0 escapeseq filter."""

    def test_basic(self, stock, cyth):
        _m(stock, cyth, '{{ items|escapeseq|join:", " }}', {"items": ["<b>a</b>", "b & c"]})


# ---------------------------------------------------------------------------
# Extends edge cases (from Django's test_extends.py)
# ---------------------------------------------------------------------------


class TestExtendsEdgeCases:
    """Extended template inheritance tests."""

    def test_direct_extends(self, stock, cyth):
        """Direct extends with block override."""
        _m(stock, cyth, "{% extends 'base.html' %}{% block content %}CHILD{% endblock %}")

    def test_block_super(self, stock, cyth):
        """{{ block.super }} in a child template."""
        _m(stock, cyth, "{% extends 'base.html' %}{% block content %}{{ block.super }}+CHILD{% endblock %}")

    def test_three_level_inheritance(self, stock, cyth):
        """Three-level extends: grandchild -> middle -> base."""
        result = _m(stock, cyth, "{% extends 'middle.html' %}{% block content %}GRANDCHILD{% endblock %}")
        assert "GRANDCHILD" in result

    def test_title_override(self, stock, cyth):
        """Override the title block."""
        _m(stock, cyth, "{% extends 'base.html' %}{% block title %}My Title{% endblock %}")


# ---------------------------------------------------------------------------
# Cache tag (from Django's test_cache.py)
# ---------------------------------------------------------------------------


class TestCacheTag:
    def test_basic_cache(self, stock, cyth):
        _m(stock, cyth, "{% load cache %}{% cache 300 test_key %}CACHED{% endcache %}")

    def test_cache_with_variable(self, stock, cyth):
        _m(stock, cyth, "{% load cache %}{% cache 300 test_key x %}{{ x }}{% endcache %}", {"x": "hello"})


# ---------------------------------------------------------------------------
# Querystring tag (Django 5.1+)
# ---------------------------------------------------------------------------


class TestQuerystringTag:
    """Tests for {% querystring %} tag including QueryDict.lists() support."""

    @staticmethod
    def _qs(stock, cyth, template_string, request, extra_context=None):
        """Render querystring template with request context."""
        ctx = extra_context or {}
        s = stock.from_string(template_string).render(ctx, request=request)
        c = cyth.from_string(template_string).render(ctx, request=request)
        assert c == s, f"Mismatch!\n  stock: {s!r}\n  cyth:  {c!r}"
        return s

    def test_basic_kwargs(self, stock, cyth):
        self._qs(stock, cyth, "{% querystring foo='bar' %}", RequestFactory().get("/"))

    def test_override_existing(self, stock, cyth):
        self._qs(stock, cyth, "{% querystring foo='new' %}", RequestFactory().get("/?foo=old"))

    def test_remove_key(self, stock, cyth):
        self._qs(stock, cyth, "{% querystring foo=None %}", RequestFactory().get("/?foo=bar&baz=qux"))

    def test_custom_dict(self, stock, cyth):
        self._qs(
            stock,
            cyth,
            "{% querystring my_dict page=2 %}",
            RequestFactory().get("/"),
            {"my_dict": {"sort": "name"}},
        )

    def test_querydict_multivalue(self, stock, cyth):
        """QueryDict with multiple values for same key should preserve all."""
        from django.http import QueryDict

        qd = QueryDict("color=red&color=blue", mutable=False)
        self._qs(stock, cyth, "{% querystring qd %}", RequestFactory().get("/"), {"qd": qd})

    def test_iterable_none_filtering(self, stock, cyth):
        """None values in iterables should be stripped."""
        self._qs(
            stock,
            cyth,
            "{% querystring tags=tag_list %}",
            RequestFactory().get("/"),
            {"tag_list": ["a", None, "b"]},
        )


# ---------------------------------------------------------------------------
# Template exceptions (from Django's test_exceptions.py)
# ---------------------------------------------------------------------------


class TestTemplateExceptions:
    """Template syntax error tests."""

    def test_unknown_tag(self, cyth):
        with pytest.raises(TemplateSyntaxError):
            cyth.from_string("{% unknown_tag %}")

    def test_unclosed_block(self, cyth):
        with pytest.raises(TemplateSyntaxError):
            cyth.from_string("{% if True %}unclosed")

    def test_unexpected_endblock(self, cyth):
        with pytest.raises(TemplateSyntaxError):
            cyth.from_string("{% endif %}")

    def test_invalid_filter(self, cyth):
        with pytest.raises(TemplateSyntaxError):
            cyth.from_string("{{ var|nonexistent_filter }}")


# ---------------------------------------------------------------------------
# Load tag edge cases
# ---------------------------------------------------------------------------


class TestLoadTag:
    """Tests for {% load %} tag."""

    def test_load_nonexistent(self, cyth):
        with pytest.raises(TemplateSyntaxError):
            cyth.from_string("{% load nonexistent_lib %}")

    def test_load_builtin(self, stock, cyth):
        """Loading a lib that's already builtin should work."""
        _m(stock, cyth, "{% load cache %}{% cache 300 k %}ok{% endcache %}")


# ---------------------------------------------------------------------------
# Named endblock
# ---------------------------------------------------------------------------


class TestNamedEndblock:
    def test_named_endblock(self, stock, cyth):
        """{% endblock name %} syntax should be accepted."""
        _m(stock, cyth, "{% extends 'base.html' %}{% block content %}X{% endblock content %}")


# ===========================================================================
# EXCEPTION PROPAGATION & SEGFAULT SAFETY
# ===========================================================================


class _SilentException(Exception):
    silent_variable_failure = True


class _NoisyException(Exception):
    pass


class _ExceptionTestObj:
    def method_silent(self):
        raise _SilentException

    def method_noisy(self):
        raise _NoisyException

    def __getitem__(self, key):
        if key == "silent_fail_key":
            raise _SilentException
        if key == "noisy_fail_key":
            raise _NoisyException
        raise KeyError

    @property
    def silent_fail_attribute(self):
        raise _SilentException

    @property
    def noisy_fail_attribute(self):
        raise _NoisyException

    @property
    def attribute_error_attribute(self):
        raise AttributeError


class TestExceptionPropagation:
    """Variable resolution must propagate non-silent exceptions and suppress silent ones."""

    def test_empty_block_tag(self, cyth):
        """{% %} should raise TemplateSyntaxError, not segfault."""
        with pytest.raises(TemplateSyntaxError, match="Empty block tag"):
            cyth.from_string("{% %}")

    def test_method_raises_non_silent(self, stock, cyth):
        """{{ var.method }} where method raises non-silent exception must propagate."""
        with pytest.raises(_NoisyException):
            cyth.from_string("{{ var.method_noisy }}").render({"var": _ExceptionTestObj()})

    def test_getitem_raises_non_silent(self, stock, cyth):
        """{{ var.noisy_fail_key }} where __getitem__ raises must propagate."""
        with pytest.raises(_NoisyException):
            cyth.from_string("{{ var.noisy_fail_key }}").render({"var": _ExceptionTestObj()})

    def test_property_raises_non_silent(self, stock, cyth):
        """{{ var.noisy_fail_attribute }} where property raises must propagate."""
        with pytest.raises(_NoisyException):
            cyth.from_string("{{ var.noisy_fail_attribute }}").render({"var": _ExceptionTestObj()})

    def test_property_raises_attribute_error(self, stock, cyth):
        """{{ var.attribute_error_attribute }} — AttributeError propagates."""
        with pytest.raises(AttributeError):
            cyth.from_string("{{ var.attribute_error_attribute }}").render({"var": _ExceptionTestObj()})

    def test_silent_method_produces_empty(self, stock, cyth):
        """Silent exceptions should produce empty string, not crash."""
        _m(stock, cyth, "{{ var.method_silent }}", {"var": _ExceptionTestObj()})

    def test_silent_getitem_produces_empty(self, stock, cyth):
        """Silent __getitem__ exception should produce empty string."""
        _m(stock, cyth, "{{ var.silent_fail_key }}", {"var": _ExceptionTestObj()})

    def test_silent_attribute_produces_empty(self, stock, cyth):
        """Silent property exception should produce empty string."""
        _m(stock, cyth, "{{ var.silent_fail_attribute }}", {"var": _ExceptionTestObj()})


# ===========================================================================
# SafeData PRESERVATION THROUGH STRINGFILTERS
# ===========================================================================


class _UnsafeObj:
    def __str__(self):
        return "you & me"


class _SafeObj:
    def __str__(self):
        return mark_safe("you &gt; me")


class TestSafeDataPreservation:
    """Filters applied to objects whose __str__ returns SafeString must preserve safety."""

    def test_unsafe_capfirst(self, stock, cyth):
        _m(stock, cyth, "{{ obj|capfirst }}", {"obj": _UnsafeObj()})

    def test_unsafe_capfirst_autoescape_off(self, stock, cyth):
        _m(stock, cyth, "{% autoescape off %}{{ obj|capfirst }}{% endautoescape %}", {"obj": _UnsafeObj()})

    def test_safe_capfirst(self, stock, cyth):
        _m(stock, cyth, "{{ obj|capfirst }}", {"obj": _SafeObj()})

    def test_safe_capfirst_autoescape_off(self, stock, cyth):
        _m(stock, cyth, "{% autoescape off %}{{ obj|capfirst }}{% endautoescape %}", {"obj": _SafeObj()})

    def test_safe_lower(self, stock, cyth):
        _m(stock, cyth, "{{ obj|lower }}", {"obj": _SafeObj()})

    def test_safe_upper(self, stock, cyth):
        _m(stock, cyth, "{{ obj|upper }}", {"obj": _SafeObj()})


# ===========================================================================
# CONTEXT COMPATIBILITY
# ===========================================================================


class TestContextTypes:
    """Template.render() must accept various context types."""

    def test_render_with_our_context(self, cyth):
        from django_templates_cythonized.context import Context

        tpl = cyth.from_string("{{ greeting }}").template
        ctx = Context({"greeting": "hello"})
        assert tpl.render(ctx) == "hello"

    def test_render_with_django_context(self, cyth):
        from django.template import Context as DjangoContext

        tpl = cyth.from_string("{{ greeting }}").template
        ctx = DjangoContext({"greeting": "world"})
        assert tpl.render(ctx) == "world"

    def test_render_with_dict(self, cyth):
        tpl = cyth.from_string("{{ greeting }}").template
        assert tpl.render({"greeting": "dict"}) == "dict"


# ===========================================================================
# FILTER BOUNDS SAFETY
# ===========================================================================


class TestFilterBoundsSafety:
    """Filters with list indexing must not segfault on empty inputs."""

    def test_first_empty_list(self, stock, cyth):
        _m(stock, cyth, "{{ items|first }}", {"items": []})

    def test_last_empty_list(self, stock, cyth):
        _m(stock, cyth, "{{ items|last }}", {"items": []})

    def test_first_nonempty(self, stock, cyth):
        _m(stock, cyth, "{{ items|first }}", {"items": ["a", "b", "c"]})

    def test_last_nonempty(self, stock, cyth):
        _m(stock, cyth, "{{ items|last }}", {"items": ["a", "b", "c"]})

    def test_first_string(self, stock, cyth):
        _m(stock, cyth, "{{ val|first }}", {"val": "hello"})

    def test_last_string(self, stock, cyth):
        _m(stock, cyth, "{{ val|last }}", {"val": "hello"})

    def test_first_empty_string(self, stock, cyth):
        _m(stock, cyth, "{{ val|first }}", {"val": ""})

    def test_last_empty_string(self, stock, cyth):
        _m(stock, cyth, "{{ val|last }}", {"val": ""})


# ===========================================================================
# SAFESTRING ESCAPING (firstof/cycle asvar, render_value_in_context)
# ===========================================================================


class TestSafeStringEscaping:
    """Values stored back into context must be SafeString to prevent double-escaping."""

    def test_firstof_asvar_html_content(self, stock, cyth):
        _m(stock, cyth, "{% firstof val as result %}{{ result }}", {"val": "<b>hello</b>"})

    def test_firstof_asvar_ampersand(self, stock, cyth):
        _m(stock, cyth, "{% firstof val as result %}{{ result }}", {"val": "A & B"})

    def test_firstof_asvar_safe_value(self, stock, cyth):
        _m(stock, cyth, "{% firstof val as result %}{{ result }}", {"val": mark_safe("<b>bold</b>")})

    def test_firstof_asvar_plain_text(self, stock, cyth):
        _m(stock, cyth, "{% firstof val as result %}{{ result }}", {"val": "hello world"})

    def test_firstof_asvar_fallback(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{% firstof empty_val fallback as result %}{{ result }}",
            {"empty_val": "", "fallback": "<em>test</em>"},
        )

    def test_cycle_asvar_html_content(self, stock, cyth):
        _m(stock, cyth, '{% for x in items %}{% cycle "<b>a</b>" "b" as cls %}{{ cls }}{% endfor %}', {"items": [1, 2]})

    def test_render_value_in_context_returns_safestring(self, stock, cyth):
        from django_templates_cythonized.base import render_value_in_context
        from django_templates_cythonized.context import Context

        ctx = Context(autoescape=True)
        ctx.template = stock.from_string("").template
        result = render_value_in_context("hello <world>", ctx)
        assert isinstance(result, SafeString), (
            f"render_value_in_context should return SafeString, got {type(result).__name__}"
        )


# ===========================================================================
# CALLABLE ATTRIBUTE RESOLUTION IN LOOPS
# ===========================================================================


class _CallableAttrObj:
    def __init__(self, status):
        self._status = status

    def get_status(self):
        return self._status

    def is_active(self):
        return self._status == "active"


class TestCallableAttributeResolution:
    """Loop optimizations must call callable attributes before comparison."""

    def test_loopif_callable_eq(self, stock, cyth):
        _m(
            stock,
            cyth,
            '{% for book in books %}{% if book.get_status == "active" %}YES{% else %}NO{% endif %}{% endfor %}',
            {"books": [_CallableAttrObj("active"), _CallableAttrObj("inactive")]},
        )

    def test_loopif_callable_ne(self, stock, cyth):
        _m(
            stock,
            cyth,
            '{% for book in books %}{% if book.get_status != "inactive" %}YES{% else %}NO{% endif %}{% endfor %}',
            {"books": [_CallableAttrObj("active"), _CallableAttrObj("inactive")]},
        )

    def test_loopif_callable_truthiness(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{% for book in books %}{% if book.is_active %}YES{% else %}NO{% endif %}{% endfor %}",
            {"books": [_CallableAttrObj("active"), _CallableAttrObj("inactive")]},
        )

    def test_loopif_callable_with_elif(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{% for book in books %}"
            '{% if book.get_status == "active" %}A'
            '{% elif book.get_status == "pending" %}P'
            "{% else %}X{% endif %}"
            "{% endfor %}",
            {"books": [_CallableAttrObj("active"), _CallableAttrObj("pending"), _CallableAttrObj("other")]},
        )

    def test_loopattr_callable(self, stock, cyth):
        _m(
            stock,
            cyth,
            "{% for book in books %}{{ book.get_status }}{% endfor %}",
            {"books": [_CallableAttrObj("active"), _CallableAttrObj("inactive")]},
        )


# ===========================================================================
# CONTEXT __copy__ SEMANTICS
# ===========================================================================


class TestContextCopy:
    """Context.__copy__ must preserve Python subclass __dict__ attributes."""

    def test_requestcontext_copy_preserves_request(self):
        from django_templates_cythonized.context import RequestContext

        rf = RequestFactory()
        request = rf.get("/")
        rc = RequestContext(request, {"a": 1})
        dup = copy.copy(rc)
        assert hasattr(dup, "request"), "Copy of RequestContext lost 'request' attribute"
        assert dup.request is request

    def test_requestcontext_copy_preserves_processors(self):
        from django_templates_cythonized.context import RequestContext

        rf = RequestFactory()
        request = rf.get("/")
        rc = RequestContext(request, {"a": 1}, processors=[lambda r: {"extra": True}])
        dup = copy.copy(rc)
        assert hasattr(dup, "_processors"), "Copy of RequestContext lost '_processors'"
        assert len(dup._processors) == 1

    def test_requestcontext_new_preserves_request(self):
        from django_templates_cythonized.context import RequestContext

        rf = RequestFactory()
        request = rf.get("/")
        rc = RequestContext(request, {"a": 1})
        new_ctx = rc.new({"b": 2})
        assert hasattr(new_ctx, "request"), "new() context lost 'request' attribute"
        assert new_ctx.request is request


# ===========================================================================
# INCLUDE FLATTENING (duplicate includes, stateful node isolation)
# ===========================================================================

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")


class TestIncludeFlattening:
    """Include flattening must not share stateful nodes across duplicate includes."""

    def test_duplicate_include_with_cycle(self, stock, cyth):
        """Including the same template twice: each should start its cycle fresh."""
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
            tpl = '{% include "_cycle_leak.html" %}|{% cycle "1" "2" as d %}{{ d }}'
            _m(stock, cyth, tpl)
        finally:
            if os.path.exists(child_path):
                os.unlink(child_path)


# ===========================================================================
# LAZY STRING (Promise) HANDLING
# ===========================================================================


class TestLazyStringHandling:
    """conditional_escape must resolve Promise before SafeData check."""

    def test_lazy_mark_safe_not_escaped(self):
        from django_templates_cythonized.html import conditional_escape

        lazy_safe = lazy(mark_safe, str)
        val = lazy_safe("<b>bold</b>")
        result = conditional_escape(val)
        assert result == "<b>bold</b>"

    def test_lazy_plain_string_escaped(self):
        from django_templates_cythonized.html import conditional_escape

        lazy_str = lazy(str, str)
        val = lazy_str("<b>bold</b>")
        result = conditional_escape(val)
        assert "&lt;" in result

    def test_format_html_with_lazy_safe(self):
        from django_templates_cythonized.html import format_html

        lazy_safe = lazy(mark_safe, str)
        val = lazy_safe("<b>bold</b>")
        result = format_html("{}", val)
        assert result == "<b>bold</b>"


# ===========================================================================
# FORM RENDERER LANGUAGE CACHE
# ===========================================================================


class TestFormRendererLangCache:
    """CythonizedFormRenderer must reset _lang between renders."""

    def test_lang_reset_between_renders(self):
        from django_templates_cythonized.backend import CythonizedFormRenderer, _form_ctx_local

        renderer = CythonizedFormRenderer()

        ctx = getattr(_form_ctx_local, "ctx", None)
        if ctx is not None:
            ctx._lang = "stale-xx"
            renderer.render(
                "django/forms/widgets/text.html",
                {
                    "widget": {
                        "name": "test",
                        "is_hidden": False,
                        "required": False,
                        "value": "",
                        "attrs": {"id": "id_test"},
                        "template_name": "django/forms/widgets/text.html",
                    },
                },
            )
            assert ctx._lang != "stale-xx", "_lang was not reset between renders — stale language cache"


# ---------------------------------------------------------------------------
# Variable writing / scoping inside for loops
# ---------------------------------------------------------------------------


class TestForLoopVariableScoping:
    """Tests for {% with %}, {% firstof ... as %}, {% cycle ... as %},
    {% now ... as %}, {% widthratio ... as %}, and other context-writing
    tags inside for loops — especially interactions with LOOPIF_CONST
    and constant variable caching optimizations."""

    # --- Basic {% with %} inside {% for %} ---

    def test_with_inside_for(self, stock, cyth):
        """{% with book.title as t %} inside for loop."""
        _m(
            stock,
            cyth,
            "{% for book in books %}{% with book.title as t %}[{{ t }}]{% endwith %}{% endfor %}",
            {"books": [{"title": "A"}, {"title": "B"}, {"title": "C"}]},
        )

    def test_with_expression_inside_for(self, stock, cyth):
        """{% with t=book.title %} (keyword form) inside for loop."""
        _m(
            stock,
            cyth,
            "{% for book in books %}{% with t=book.title %}[{{ t }}]{% endwith %}{% endfor %}",
            {"books": [{"title": "X"}, {"title": "Y"}, {"title": "Z"}]},
        )

    def test_with_shadowing_outer_variable(self, stock, cyth):
        """{% with %} shadows a variable that exists in outer context."""
        _m(
            stock,
            cyth,
            "{% for book in books %}"
            "{% with 'SHADOW' as currency %}[{{ currency }}]{% endwith %}"
            "({{ currency }})"
            "{% endfor %}",
            {"books": [{"title": "A"}, {"title": "B"}], "currency": "$"},
        )

    def test_with_shadowing_loop_variable(self, stock, cyth):
        """{% with %} shadows the loop variable itself."""
        _m(
            stock,
            cyth,
            "{% for x in items %}({{ x }}){% with 'REPLACED' as x %}[{{ x }}]{% endwith %}({{ x }}){% endfor %}",
            {"items": ["a", "b", "c"]},
        )

    def test_with_nested_inside_for(self, stock, cyth):
        """Nested {% with %} blocks inside for loop."""
        _m(
            stock,
            cyth,
            "{% for book in books %}"
            "{% with book.title as t %}"
            "{% with 'X' as x %}{{ t }}{{ x }}{% endwith %}"
            "{% endwith %}"
            "{% endfor %}",
            {"books": [{"title": "A"}, {"title": "B"}]},
        )

    # --- {% firstof ... as %} inside {% for %} ---

    def test_firstof_as_inside_for(self, stock, cyth):
        """{% firstof ... as var %} writes to context each iteration."""
        _m(
            stock,
            cyth,
            "{% for book in books %}{% firstof book.title 'N/A' as t %}[{{ t }}]{% endfor %}",
            {
                "books": [
                    {"title": "A"},
                    {"title": ""},
                    {"title": "C"},
                    {},
                ],
            },
        )

    def test_firstof_as_changes_per_iteration(self, stock, cyth):
        """Value set by firstof must change each iteration, not be cached."""
        _m(
            stock,
            cyth,
            "{% for item in items %}{% firstof item.a item.b 'default' as val %}{{ val }},{% endfor %}",
            {
                "items": [
                    {"a": "A1", "b": "B1"},
                    {"a": "", "b": "B2"},
                    {"a": "", "b": ""},
                    {"a": "A4", "b": "B4"},
                ],
            },
        )

    # --- {% cycle ... as %} inside {% for %} ---

    def test_cycle_as_inside_for(self, stock, cyth):
        """{% cycle ... as cls %} writes to context, used later."""
        _m(
            stock,
            cyth,
            "{% for x in items %}{% cycle 'odd' 'even' as cls %}[{{ cls }}:{{ x }}]{% endfor %}",
            {"items": ["a", "b", "c", "d"]},
        )

    def test_cycle_as_used_multiple_times(self, stock, cyth):
        """Cycle variable used multiple times in same iteration."""
        _m(
            stock,
            cyth,
            "{% for x in items %}{% cycle 'A' 'B' 'C' as cls %}<{{ cls }}>{{ x }}</{{ cls }}>{% endfor %}",
            {"items": [1, 2, 3, 4, 5, 6]},
        )

    # --- {% now ... as %} inside {% for %} ---

    def test_now_as_inside_for(self, stock, cyth):
        """{% now 'Y' as yr %} inside for loop — same value each iter."""
        _m(
            stock,
            cyth,
            "{% for x in items %}{% now 'Y' as yr %}[{{ yr }}:{{ x }}]{% endfor %}",
            {"items": ["a", "b"]},
        )

    # --- {% widthratio ... as %} inside {% for %} ---

    def test_widthratio_as_inside_for(self, stock, cyth):
        """{% widthratio ... as pct %} changes per iteration."""
        _m(
            stock,
            cyth,
            "{% for book in books %}{% widthratio book.rating 5 100 as pct %}[{{ pct }}]{% endfor %}",
            {
                "books": [
                    {"rating": 1},
                    {"rating": 3},
                    {"rating": 5},
                ],
            },
        )

    # --- Context-writing tags inside {% if %} inside {% for %} ---
    # These test LOOPIF_CONST interactions with variable caching.

    def test_with_inside_const_if_inside_for(self, stock, cyth):
        """{% with %} inside LOOPIF_CONST=true branch."""
        _m(
            stock,
            cyth,
            "{% for book in books %}"
            "{% if show %}"
            "{% with book.title as t %}[{{ t }}]{% endwith %}"
            "{% endif %}"
            "{% endfor %}",
            {"books": [{"title": "A"}, {"title": "B"}], "show": True},
        )

    def test_with_inside_const_if_false(self, stock, cyth):
        """{% with %} inside LOOPIF_CONST=false — branch not taken."""
        _m(
            stock,
            cyth,
            "{% for book in books %}"
            "{% if show %}"
            "{% with book.title as t %}[{{ t }}]{% endwith %}"
            "{% endif %}"
            "{% endfor %}",
            {"books": [{"title": "A"}, {"title": "B"}], "show": False},
        )

    def test_firstof_as_inside_const_if_var_used_outside(self, stock, cyth):
        """{% firstof ... as t %} inside const-if, {{ t }} used OUTSIDE the if.
        This is the dangerous pattern: t is set per-iteration inside the if,
        but {{ t }} outside must NOT be cached as a constant."""
        _m(
            stock,
            cyth,
            "{% for book in books %}{% if show %}{% firstof book.title 'N/A' as t %}{% endif %}[{{ t }}]{% endfor %}",
            {
                "books": [{"title": "A"}, {"title": "B"}, {"title": "C"}],
                "show": True,
            },
        )

    def test_firstof_as_inside_const_if_false_var_used_outside(self, stock, cyth):
        """Same as above but show=False — firstof never runs, t is unset."""
        _m(
            stock,
            cyth,
            "{% for book in books %}{% if show %}{% firstof book.title 'N/A' as t %}{% endif %}[{{ t }}]{% endfor %}",
            {
                "books": [{"title": "A"}, {"title": "B"}, {"title": "C"}],
                "show": False,
            },
        )

    def test_widthratio_as_inside_const_if_var_used_outside(self, stock, cyth):
        """{% widthratio ... as pct %} inside const-if, {{ pct }} outside."""
        _m(
            stock,
            cyth,
            "{% for book in books %}"
            "{% if show %}{% widthratio book.rating 5 100 as pct %}{% endif %}"
            "[{{ pct }}]"
            "{% endfor %}",
            {
                "books": [{"rating": 1}, {"rating": 3}, {"rating": 5}],
                "show": True,
            },
        )

    def test_now_as_inside_const_if_var_used_outside(self, stock, cyth):
        """{% now 'Y' as yr %} inside const-if, {{ yr }} used outside."""
        _m(
            stock,
            cyth,
            "{% for book in books %}{% if show %}{% now 'Y' as yr %}{% endif %}[{{ yr }}]{% endfor %}",
            {"books": [{"title": "A"}, {"title": "B"}], "show": True},
        )

    # --- Variable redefinition patterns ---

    def test_var_redefined_by_with(self, stock, cyth):
        """Outer var, then {% with %} redefines it, then outer again."""
        _m(
            stock,
            cyth,
            "{% for book in books %}"
            "({{ label }})"
            "{% with book.title as label %}[{{ label }}]{% endwith %}"
            "({{ label }})"
            "{% endfor %}",
            {
                "books": [{"title": "A"}, {"title": "B"}],
                "label": "OUTER",
            },
        )

    def test_const_var_after_with_block(self, stock, cyth):
        """{{ currency }} (outer constant) after {% with %} that doesn't touch it."""
        _m(
            stock,
            cyth,
            "{% for book in books %}{% with book.title as t %}{{ t }}{% endwith %}{{ currency }}{% endfor %}",
            {
                "books": [{"title": "A"}, {"title": "B"}],
                "currency": "$",
            },
        )

    def test_loop_var_single_segment_not_cached(self, stock, cyth):
        """{{ x }} (the loop variable itself) must NOT be cached as constant."""
        _m(
            stock,
            cyth,
            "{% for x in items %}{% if flag %}{{ x }},{% endif %}{% endfor %}",
            {"items": [1, 2, 3], "flag": True},
        )

    def test_loop_var_single_segment_in_const_if(self, stock, cyth):
        """{{ x }} inside LOOPIF_CONST=true branch, x is the loop var."""
        _m(
            stock,
            cyth,
            "{% for x in items %}{% if show %}[{{ x }}]{% endif %}{% endfor %}",
            {"items": ["a", "b", "c"], "show": True},
        )

    def test_loop_var_single_segment_in_const_if_false(self, stock, cyth):
        """{{ x }} inside LOOPIF_CONST=false — branch not taken."""
        _m(
            stock,
            cyth,
            "{% for x in items %}{% if show %}[{{ x }}]{% endif %}{% endfor %}",
            {"items": ["a", "b", "c"], "show": False},
        )

    # --- Compound patterns: const-if + with + variables ---

    def test_const_if_with_multiple_vars_and_text(self, stock, cyth):
        """LOOPIF_CONST branch with {% with %}, text, and loop vars."""
        _m(
            stock,
            cyth,
            "{% for book in books %}"
            "<row>"
            "{% if show_extra %}"
            "{% with book.title as t %}"
            "<extra>{{ t }} by {{ book.author }}</extra>"
            "{% endwith %}"
            "{% endif %}"
            "</row>"
            "{% endfor %}",
            {
                "books": [
                    {"title": "A", "author": "X"},
                    {"title": "B", "author": "Y"},
                ],
                "show_extra": True,
            },
        )

    def test_const_if_with_cycle_and_const_var(self, stock, cyth):
        """LOOPIF_CONST branch + cycle + constant variable."""
        _m(
            stock,
            cyth,
            "{% for book in books %}"
            "<tr class=\"{% cycle 'odd' 'even' %}\">"
            "{{ book.title }}"
            "{% if show_price %}{{ currency }}{{ book.price }}{% endif %}"
            "</tr>"
            "{% endfor %}",
            {
                "books": [
                    {"title": "A", "price": 10},
                    {"title": "B", "price": 20},
                    {"title": "C", "price": 30},
                ],
                "show_price": True,
                "currency": "$",
            },
        )

    def test_const_if_false_with_cycle_and_const_var(self, stock, cyth):
        """Same as above but show_price=False."""
        _m(
            stock,
            cyth,
            "{% for book in books %}"
            "<tr class=\"{% cycle 'odd' 'even' %}\">"
            "{{ book.title }}"
            "{% if show_price %}{{ currency }}{{ book.price }}{% endif %}"
            "</tr>"
            "{% endfor %}",
            {
                "books": [
                    {"title": "A", "price": 10},
                    {"title": "B", "price": 20},
                ],
                "show_price": False,
                "currency": "$",
            },
        )

    # --- Multi-segment loop var inside const-if (LOOPATTR after flatten) ---

    def test_loopattr_inside_const_if_true(self, stock, cyth):
        """{{ book.description }} inside LOOPIF_CONST=true — flattened to LOOPATTR."""
        _m(
            stock,
            cyth,
            "{% for book in books %}"
            "{{ book.title }}"
            "{% if show_desc %}<desc>{{ book.description }}</desc>{% endif %}"
            "{% endfor %}",
            {
                "books": [
                    {"title": "A", "description": "Desc A"},
                    {"title": "B", "description": "Desc B"},
                ],
                "show_desc": True,
            },
        )

    def test_loopattr_with_filter_inside_const_if(self, stock, cyth):
        """{{ book.genre|capfirst }} inside LOOPIF_CONST=true — LOOPATTR_FILTER."""
        _m(
            stock,
            cyth,
            "{% for book in books %}{% if show_genre %}[{{ book.genre|capfirst }}]{% endif %}{% endfor %}",
            {
                "books": [
                    {"genre": "fiction"},
                    {"genre": "science"},
                ],
                "show_genre": True,
            },
        )

    def test_forloop_counter_inside_const_if(self, stock, cyth):
        """{{ forloop.counter }} inside LOOPIF_CONST=true — FORLOOP_COUNTER."""
        _m(
            stock,
            cyth,
            "{% for x in items %}{% if show_num %}#{{ forloop.counter }}{% endif %}={{ x }},{% endfor %}",
            {"items": ["a", "b", "c"], "show_num": True},
        )

    def test_forloop_counter_inside_const_if_false(self, stock, cyth):
        """{{ forloop.counter }} inside LOOPIF_CONST=false."""
        _m(
            stock,
            cyth,
            "{% for x in items %}{% if show_num %}#{{ forloop.counter }}{% endif %}={{ x }},{% endfor %}",
            {"items": ["a", "b", "c"], "show_num": False},
        )

    # --- Edge: multiple const-if blocks with different conditions ---

    def test_multiple_const_ifs(self, stock, cyth):
        """Multiple LOOPIF_CONST blocks with different conditions."""
        _m(
            stock,
            cyth,
            "{% for book in books %}"
            "<row>"
            "{% if show_title %}{{ book.title }}{% endif %}"
            "{% if show_price %}{{ currency }}{{ book.price }}{% endif %}"
            "{% if show_desc %}{{ book.description }}{% endif %}"
            "</row>"
            "{% endfor %}",
            {
                "books": [
                    {"title": "A", "price": 10, "description": "D1"},
                    {"title": "B", "price": 20, "description": "D2"},
                ],
                "show_title": True,
                "show_price": False,
                "show_desc": True,
                "currency": "$",
            },
        )

    # --- Edge: empty loop bodies with const-if ---

    def test_const_if_only_content_in_loop(self, stock, cyth):
        """Entire loop body is a single const-if."""
        _m(
            stock,
            cyth,
            "{% for x in items %}{% if show %}{{ x }}{% endif %}{% endfor %}",
            {"items": [1, 2, 3], "show": True},
        )

    def test_const_if_only_content_false(self, stock, cyth):
        """Entire loop body is a single const-if=false → empty output."""
        _m(
            stock,
            cyth,
            "{% for x in items %}{% if show %}{{ x }}{% endif %}{% endfor %}",
            {"items": [1, 2, 3], "show": False},
        )


# ---------------------------------------------------------------------------
# Bug regression tests
# ---------------------------------------------------------------------------


class TestBugCycleCounterAfterLoop:
    """B2: Named cycle counter must be correct after the for loop ends.

    When a named cycle like ``{% cycle 'a' 'b' 'c' as cls %}`` is used
    inside a for loop, and later referenced after the loop with
    ``{% cycle cls %}``, the post-loop cycle should continue from where
    the loop left off — not restart from the beginning.
    """

    def test_cycle_continues_after_loop(self, stock, cyth):
        """Post-loop cycle picks up where the loop left off."""
        _m(
            stock,
            cyth,
            "{% for x in items %}{% cycle 'a' 'b' 'c' as cls %}{% endfor %}{% cycle cls %}",
            {"items": [1, 2, 3, 4, 5]},
        )

    def test_cycle_after_loop_single_iteration(self, stock, cyth):
        """A single-iteration loop advances the counter by 1."""
        _m(
            stock,
            cyth,
            "{% for x in items %}{% cycle 'x' 'y' as cls %}{% endfor %}{% cycle cls %}",
            {"items": ["only"]},
        )

    def test_cycle_after_loop_exact_multiple(self, stock, cyth):
        """Loop length is an exact multiple of the cycle length."""
        _m(
            stock,
            cyth,
            "{% for x in items %}{% cycle 'a' 'b' as cls %}{% endfor %}{% cycle cls %}",
            {"items": [1, 2, 3, 4]},
        )


class TestBugFirstLastFilterFalsyContainer:
    """B3: first/last filters must match stock Django for edge-case inputs.

    A falsy-but-subscriptable object (``__bool__`` returns False but
    ``__getitem__`` works) should still have its first/last item
    extracted, not be treated as empty.
    """

    def test_first_on_falsy_container(self, stock, cyth):
        class FalsyContainer:
            def __bool__(self):
                return False

            def __getitem__(self, i):
                if i == 0:
                    return "found"
                raise IndexError

        _m(stock, cyth, "{{ val|first }}", {"val": FalsyContainer()})

    def test_last_on_falsy_container(self, stock, cyth):
        class FalsyContainer:
            def __bool__(self):
                return False

            def __getitem__(self, i):
                if i == -1:
                    return "found"
                raise IndexError

        _m(stock, cyth, "{{ val|last }}", {"val": FalsyContainer()})

    def test_first_empty_list(self, stock, cyth):
        """Empty list should still return empty string (not break)."""
        _m(stock, cyth, "{{ val|first }}", {"val": []})

    def test_last_empty_list(self, stock, cyth):
        _m(stock, cyth, "{{ val|last }}", {"val": []})

    def test_first_normal_list(self, stock, cyth):
        """Normal lists still work after the fix."""
        _m(stock, cyth, "{{ val|first }}", {"val": ["a", "b", "c"]})

    def test_last_normal_list(self, stock, cyth):
        _m(stock, cyth, "{{ val|last }}", {"val": ["a", "b", "c"]})


class TestBugConstCacheCustomTagInIf:
    """B5: Constant variable caching must account for custom tags inside IfNodes.

    When a custom tag that writes to context (without using Django's
    standard ``as varname`` pattern) is nested inside an ``{% if %}``
    block within a for loop, the constant-variable cache must not treat
    the written variable as constant — its value changes per iteration.
    """

    def test_setvar_inside_if_not_cached(self, stock, cyth):
        """A variable set by a custom tag inside {% if %} must update each iteration."""
        _m(
            stock,
            cyth,
            "{% load custom_tags %}"
            "{% for item in items %}"
            "{% if True %}{% setvar label item.name %}{% endif %}"
            "{{ label }},"
            "{% endfor %}",
            {
                "items": [
                    SimpleObj(name="Alice"),
                    SimpleObj(name="Bob"),
                    SimpleObj(name="Charlie"),
                ],
            },
        )

    def test_setvar_inside_if_with_condition(self, stock, cyth):
        """Custom tag inside conditional if — the variable should reflect each item."""
        _m(
            stock,
            cyth,
            "{% load custom_tags %}"
            "{% for item in items %}"
            "{% if item.active %}{% setvar status 'ON' %}{% endif %}"
            "{{ status }},"
            "{% endfor %}",
            {
                "items": [
                    SimpleObj(active=True),
                    SimpleObj(active=False),
                    SimpleObj(active=True),
                ],
            },
        )
