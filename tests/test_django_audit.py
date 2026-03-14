"""Tests derived from Django's template test suite.

These tests cover bugs found by running Django 6.0.2's test_filter_syntax,
test_autoescape, test_resetcycle, and test_include tests against our engine.
They verify:
1. Segfault fixes (empty block tag, exception propagation in variable resolution)
2. SafeData preservation through filters (capfirst on SafeClass)
3. resetcycle correctness with named cycles
4. Template.render() accepting Django's stock Context
"""

import pytest
from django.template import engines
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
    assert cyth_result == stock_result, (
        f"Mismatch!\n  stock: {stock_result!r}\n  cyth:  {cyth_result!r}"
    )
    return stock_result


# ---------------------------------------------------------------------------
# Helper classes (from Django's template_tests/utils.py)
# ---------------------------------------------------------------------------

class SomeException(Exception):
    silent_variable_failure = True


class SomeOtherException(Exception):
    pass


class SomeClass:
    def method3(self):
        raise SomeException

    def method4(self):
        raise SomeOtherException

    def __getitem__(self, key):
        if key == "silent_fail_key":
            raise SomeException
        elif key == "noisy_fail_key":
            raise SomeOtherException
        raise KeyError

    @property
    def silent_fail_attribute(self):
        raise SomeException

    @property
    def noisy_fail_attribute(self):
        raise SomeOtherException

    @property
    def attribute_error_attribute(self):
        raise AttributeError


class UnsafeClass:
    def __str__(self):
        return "you & me"


class SafeClass:
    def __str__(self):
        return mark_safe("you &gt; me")


# ---------------------------------------------------------------------------
# Segfault fixes (filter-syntax tests)
# ---------------------------------------------------------------------------

class TestFilterSyntaxSegfaults:
    """Tests for bugs that previously caused segfaults due to Cython's
    __Pyx_GetItemInt_Fast bypassing bounds checks on free-threaded Python."""

    def test_empty_block_tag(self, cyth):
        """filter-syntax08: {% %} should raise TemplateSyntaxError, not segfault."""
        with pytest.raises(TemplateSyntaxError, match="Empty block tag"):
            cyth.from_string("{% %}")

    def test_method_raises_non_silent_exception(self, stock, cyth):
        """filter-syntax14: {{ var.method4 }} where method4 raises SomeOtherException."""
        with pytest.raises(SomeOtherException):
            cyth.from_string("{{ var.method4 }}").render({"var": SomeClass()})

    def test_getitem_raises_non_silent_exception(self, stock, cyth):
        """filter-syntax23: {{ var.noisy_fail_key }} where __getitem__ raises."""
        with pytest.raises(SomeOtherException):
            cyth.from_string("{{ var.noisy_fail_key }}").render({"var": SomeClass()})

    def test_property_raises_non_silent_exception(self, stock, cyth):
        """filter-syntax24: {{ var.noisy_fail_attribute }} where property raises."""
        with pytest.raises(SomeOtherException):
            cyth.from_string("{{ var.noisy_fail_attribute }}").render(
                {"var": SomeClass()}
            )

    def test_property_raises_attribute_error(self, stock, cyth):
        """filter-syntax25: {{ var.attribute_error_attribute }} — AttributeError propagates."""
        with pytest.raises(AttributeError):
            cyth.from_string("{{ var.attribute_error_attribute }}").render(
                {"var": SomeClass()}
            )

    def test_silent_variable_failure(self, stock, cyth):
        """Silent exceptions should produce empty string, not crash."""
        _m(stock, cyth, "{{ var.method3 }}", {"var": SomeClass()})

    def test_silent_getitem_failure(self, stock, cyth):
        """Silent __getitem__ exception should produce empty string."""
        _m(stock, cyth, "{{ var.silent_fail_key }}", {"var": SomeClass()})

    def test_silent_attribute_failure(self, stock, cyth):
        """Silent property exception should produce empty string."""
        _m(stock, cyth, "{{ var.silent_fail_attribute }}", {"var": SomeClass()})


# ---------------------------------------------------------------------------
# SafeData preservation through filters
# ---------------------------------------------------------------------------

class TestAutoescapeStringfilter:
    """Tests for SafeData preservation when filters like capfirst are applied
    to objects whose __str__ returns SafeString."""

    def test_unsafe_capfirst(self, stock, cyth):
        """stringfilter01: UnsafeClass + capfirst should escape."""
        _m(stock, cyth, "{{ unsafe|capfirst }}", {"unsafe": UnsafeClass()})

    def test_unsafe_capfirst_autoescape_off(self, stock, cyth):
        """stringfilter02: UnsafeClass + capfirst with autoescape off."""
        _m(stock, cyth,
           "{% autoescape off %}{{ unsafe|capfirst }}{% endautoescape %}",
           {"unsafe": UnsafeClass()})

    def test_safe_capfirst(self, stock, cyth):
        """stringfilter03: SafeClass + capfirst should preserve SafeString."""
        _m(stock, cyth, "{{ safe|capfirst }}", {"safe": SafeClass()})

    def test_safe_capfirst_autoescape_off(self, stock, cyth):
        """stringfilter04: SafeClass + capfirst with autoescape off."""
        _m(stock, cyth,
           "{% autoescape off %}{{ safe|capfirst }}{% endautoescape %}",
           {"safe": SafeClass()})

    def test_safe_lower(self, stock, cyth):
        """SafeClass + lower should preserve SafeString."""
        _m(stock, cyth, "{{ safe|lower }}", {"safe": SafeClass()})

    def test_safe_upper(self, stock, cyth):
        """SafeClass + upper should preserve SafeString."""
        _m(stock, cyth, "{{ safe|upper }}", {"safe": SafeClass()})


# ---------------------------------------------------------------------------
# resetcycle tests (from Django's test_resetcycle.py)
# ---------------------------------------------------------------------------

class TestResetCycle:
    """All resetcycle tests from Django's test suite."""

    def test_resetcycle01_no_cycles(self, cyth):
        """resetcycle with no cycles should raise TemplateSyntaxError."""
        with pytest.raises(TemplateSyntaxError, match="No cycles in template"):
            cyth.from_string("{% resetcycle %}")

    def test_resetcycle02_undefined(self, cyth):
        """resetcycle with undefined name should raise TemplateSyntaxError."""
        with pytest.raises(TemplateSyntaxError, match="does not exist"):
            cyth.from_string("{% resetcycle undefinedcycle %}")

    def test_resetcycle03_undefined_with_cycle(self, cyth):
        """resetcycle with undefined name when unnamed cycle exists."""
        with pytest.raises(TemplateSyntaxError, match="does not exist"):
            cyth.from_string("{% cycle 'a' 'b' %}{% resetcycle undefinedcycle %}")

    def test_resetcycle04_undefined_with_named_cycle(self, cyth):
        """resetcycle with undefined name when different named cycle exists."""
        with pytest.raises(TemplateSyntaxError, match="does not exist"):
            cyth.from_string(
                "{% cycle 'a' 'b' as ab %}{% resetcycle undefinedcycle %}"
            )

    def test_resetcycle05_simple(self, stock, cyth):
        """Simple unnamed resetcycle resets the cycle each iteration."""
        _m(stock, cyth,
           "{% for i in test %}{% cycle 'a' 'b' %}{% resetcycle %}{% endfor %}",
           {"test": list(range(5))})

    def test_resetcycle06_multiple_cycles(self, stock, cyth):
        """Named cycle from outside loop + unnamed cycle in loop.
        Unnamed resetcycle resets the LAST cycle (unnamed one)."""
        _m(stock, cyth,
           "{% cycle 'a' 'b' 'c' as abc %}"
           "{% for i in test %}"
           "{% cycle abc %}"
           "{% cycle '-' '+' %}"
           "{% resetcycle %}"
           "{% endfor %}",
           {"test": list(range(5))})

    def test_resetcycle07_named_reset(self, stock, cyth):
        """resetcycle with name resets only the named cycle."""
        _m(stock, cyth,
           "{% cycle 'a' 'b' 'c' as abc %}"
           "{% for i in test %}"
           "{% resetcycle abc %}"
           "{% cycle abc %}"
           "{% cycle '-' '+' %}"
           "{% endfor %}",
           {"test": list(range(5))})

    def test_resetcycle08_nested_loops(self, stock, cyth):
        """resetcycle in outer loop resets inner loop's cycle."""
        _m(stock, cyth,
           "{% for i in outer %}"
           "{% for j in inner %}"
           "{% cycle 'a' 'b' %}"
           "{% endfor %}"
           "{% resetcycle %}"
           "{% endfor %}",
           {"outer": list(range(2)), "inner": list(range(3))})

    def test_resetcycle09_nested_multiple_cycles(self, stock, cyth):
        """Nested loops with multiple cycles and resetcycle."""
        _m(stock, cyth,
           "{% for i in outer %}"
           "{% cycle 'a' 'b' %}"
           "{% for j in inner %}"
           "{% cycle 'X' 'Y' %}"
           "{% endfor %}"
           "{% resetcycle %}"
           "{% endfor %}",
           {"outer": list(range(2)), "inner": list(range(3))})

    def test_resetcycle10_conditional(self, stock, cyth):
        """Conditional resetcycle on specific named cycle."""
        _m(stock, cyth,
           "{% for i in test %}"
           "{% cycle 'X' 'Y' 'Z' as XYZ %}"
           "{% cycle 'a' 'b' 'c' as abc %}"
           "{% if i == 1 %}"
           "{% resetcycle abc %}"
           "{% endif %}"
           "{% endfor %}",
           {"test": list(range(5))})

    def test_resetcycle11_conditional_other(self, stock, cyth):
        """Conditional resetcycle on the other named cycle."""
        _m(stock, cyth,
           "{% for i in test %}"
           "{% cycle 'X' 'Y' 'Z' as XYZ %}"
           "{% cycle 'a' 'b' 'c' as abc %}"
           "{% if i == 1 %}"
           "{% resetcycle XYZ %}"
           "{% endif %}"
           "{% endfor %}",
           {"test": list(range(5))})


# ---------------------------------------------------------------------------
# Template.render() Context compatibility
# ---------------------------------------------------------------------------

class TestContextCompatibility:
    """Tests that Template.render() accepts various context types."""

    def test_render_with_our_context(self, cyth):
        """Template.render() accepts our Context."""
        from django_templates_cythonized.context import Context
        tpl = cyth.from_string("{{ greeting }}").template
        ctx = Context({"greeting": "hello"})
        assert tpl.render(ctx) == "hello"

    def test_render_with_django_context(self, cyth):
        """Template.render() accepts Django's stock Context."""
        from django.template import Context as DjangoContext
        tpl = cyth.from_string("{{ greeting }}").template
        ctx = DjangoContext({"greeting": "world"})
        assert tpl.render(ctx) == "world"

    def test_render_with_dict(self, cyth):
        """Template.render() accepts a plain dict."""
        tpl = cyth.from_string("{{ greeting }}").template
        assert tpl.render({"greeting": "dict"}) == "dict"


# ---------------------------------------------------------------------------
# first/last filter edge cases (Cython bounds safety)
# ---------------------------------------------------------------------------

class TestFilterBoundsSafety:
    """Tests that filters with list indexing don't segfault on empty inputs."""

    def test_first_empty_list(self, stock, cyth):
        """{{ items|first }} on empty list should return empty string."""
        _m(stock, cyth, "{{ items|first }}", {"items": []})

    def test_last_empty_list(self, stock, cyth):
        """{{ items|last }} on empty list should return empty string."""
        _m(stock, cyth, "{{ items|last }}", {"items": []})

    def test_first_nonempty(self, stock, cyth):
        """{{ items|first }} on non-empty list should return first element."""
        _m(stock, cyth, "{{ items|first }}", {"items": ["a", "b", "c"]})

    def test_last_nonempty(self, stock, cyth):
        """{{ items|last }} on non-empty list should return last element."""
        _m(stock, cyth, "{{ items|last }}", {"items": ["a", "b", "c"]})

    def test_first_string(self, stock, cyth):
        """{{ val|first }} on a string should return first char."""
        _m(stock, cyth, "{{ val|first }}", {"val": "hello"})

    def test_last_string(self, stock, cyth):
        """{{ val|last }} on a string should return last char."""
        _m(stock, cyth, "{{ val|last }}", {"val": "hello"})

    def test_first_empty_string(self, stock, cyth):
        """{{ val|first }} on empty string should return empty string."""
        _m(stock, cyth, "{{ val|first }}", {"val": ""})

    def test_last_empty_string(self, stock, cyth):
        """{{ val|last }} on empty string should return empty string."""
        _m(stock, cyth, "{{ val|last }}", {"val": ""})
