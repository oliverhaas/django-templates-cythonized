"""Template compatibility tests.

Verify our cythonized engine produces identical output to stock Django.
"""

import pytest
from django.template import engines


class TestBasicRendering:
    def test_plain_text(self, assert_render):
        assert_render("Hello world", {}, "Hello world")

    def test_variable(self, assert_render):
        assert_render("Hello {{ name }}!", {"name": "World"}, "Hello World!")

    def test_missing_variable(self, assert_render):
        assert_render("Hello {{ name }}!", {}, "Hello !")

    def test_integer_variable(self, assert_render):
        assert_render("Count: {{ count }}", {"count": 42}, "Count: 42")

    def test_float_variable(self, assert_render):
        assert_render("Value: {{ val }}", {"val": 3.14}, "Value: 3.14")

    def test_dot_notation(self, assert_render):
        assert_render(
            "{{ user.name }}",
            {"user": {"name": "Alice"}},
            "Alice",
        )


class TestFilters:
    def test_lower(self, assert_render):
        assert_render("{{ name|lower }}", {"name": "ALICE"}, "alice")

    def test_upper(self, assert_render):
        assert_render("{{ name|upper }}", {"name": "alice"}, "ALICE")

    def test_default(self, assert_render):
        assert_render("{{ val|default:'N/A' }}", {}, "N/A")

    def test_default_with_value(self, assert_render):
        assert_render("{{ val|default:'N/A' }}", {"val": "hello"}, "hello")

    def test_length(self, assert_render):
        assert_render("{{ items|length }}", {"items": [1, 2, 3]}, "3")

    def test_join(self, assert_render):
        assert_render(
            '{{ items|join:", " }}',
            {"items": ["a", "b", "c"]},
            "a, b, c",
        )

    def test_capfirst(self, assert_render):
        assert_render("{{ name|capfirst }}", {"name": "alice"}, "Alice")

    def test_cut(self, assert_render):
        assert_render(
            '{{ val|cut:" " }}',
            {"val": "hello world"},
            "helloworld",
        )

    def test_slugify(self, assert_render):
        assert_render(
            "{{ title|slugify }}",
            {"title": "Hello World!"},
            "hello-world",
        )

    def test_safe(self, assert_render):
        assert_render(
            "{{ html|safe }}",
            {"html": "<b>bold</b>"},
            "<b>bold</b>",
        )

    def test_escape(self, assert_render):
        assert_render(
            "{{ html }}",
            {"html": "<b>bold</b>"},
            "&lt;b&gt;bold&lt;/b&gt;",
        )

    def test_chained_filters(self, assert_render):
        assert_render(
            "{{ name|lower|capfirst }}",
            {"name": "ALICE BOB"},
            "Alice bob",
        )

    def test_add(self, assert_render):
        assert_render("{{ a|add:b }}", {"a": 1, "b": 2}, "3")

    def test_yesno(self, assert_render):
        assert_render(
            "{{ val|yesno:'yes,no' }}",
            {"val": True},
            "yes",
        )

    def test_floatformat(self, assert_render):
        assert_render(
            "{{ val|floatformat:2 }}",
            {"val": 3.14159},
            "3.14",
        )


class TestTags:
    def test_if_true(self, assert_render):
        assert_render(
            "{% if show %}visible{% endif %}",
            {"show": True},
            "visible",
        )

    def test_if_false(self, assert_render):
        assert_render(
            "{% if show %}visible{% endif %}",
            {"show": False},
            "",
        )

    def test_if_else(self, assert_render):
        assert_render(
            "{% if show %}yes{% else %}no{% endif %}",
            {"show": False},
            "no",
        )

    def test_if_elif(self, assert_render):
        assert_render(
            "{% if a %}A{% elif b %}B{% else %}C{% endif %}",
            {"a": False, "b": True},
            "B",
        )

    def test_if_comparison(self, assert_render):
        assert_render(
            "{% if x > 5 %}big{% else %}small{% endif %}",
            {"x": 10},
            "big",
        )

    def test_for_loop(self, assert_render):
        assert_render(
            "{% for item in items %}{{ item }} {% endfor %}",
            {"items": ["a", "b", "c"]},
            "a b c ",
        )

    def test_for_loop_counter(self, assert_render):
        assert_render(
            "{% for item in items %}{{ forloop.counter }}{% endfor %}",
            {"items": ["a", "b", "c"]},
            "123",
        )

    def test_for_loop_empty(self, assert_render):
        assert_render(
            "{% for item in items %}{{ item }}{% empty %}none{% endfor %}",
            {"items": []},
            "none",
        )

    def test_for_loop_reversed(self, assert_render):
        assert_render(
            "{% for item in items reversed %}{{ item }}{% endfor %}",
            {"items": [1, 2, 3]},
            "321",
        )

    def test_with(self, assert_render):
        assert_render(
            "{% with name='World' %}Hello {{ name }}{% endwith %}",
            {},
            "Hello World",
        )

    def test_comment(self, assert_render):
        assert_render(
            "before{% comment %}invisible{% endcomment %}after",
            {},
            "beforeafter",
        )

    def test_spaceless(self, assert_render):
        assert_render(
            "{% spaceless %}<p> <a>link</a> </p>{% endspaceless %}",
            {},
            "<p><a>link</a></p>",
        )

    def test_cycle(self, assert_render):
        assert_render(
            "{% for i in items %}{% cycle 'a' 'b' %}{% endfor %}",
            {"items": [1, 2, 3, 4]},
            "abab",
        )

    def test_verbatim(self, assert_render):
        assert_render(
            "{% verbatim %}{{ not_rendered }}{% endverbatim %}",
            {},
            "{{ not_rendered }}",
        )

    def test_templatetag(self, assert_render):
        assert_render(
            "{% templatetag openblock %}",
            {},
            "{%",
        )

    def test_firstof(self, assert_render):
        assert_render(
            "{% firstof a b c %}",
            {"a": "", "b": "found", "c": "nope"},
            "found",
        )

    def test_now(self, cythonized, django_template):
        # Just verify both render without error (time-dependent output)
        template_str = '{% now "Y" %}'
        django_result = django_template(template_str).render({})
        cythonized_result = cythonized(template_str).render({})
        assert django_result == cythonized_result

    def test_widthratio(self, assert_render):
        assert_render(
            "{% widthratio this_val max_val max_width %}",
            {"this_val": 175, "max_val": 200, "max_width": 100},
            "88",
        )


class TestAutoescaping:
    def test_autoescape_on_by_default(self, assert_render):
        assert_render(
            "{{ html }}",
            {"html": "<script>alert('xss')</script>"},
            "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;",
        )

    def test_autoescape_off(self, assert_render):
        assert_render(
            "{% autoescape off %}{{ html }}{% endautoescape %}",
            {"html": "<b>bold</b>"},
            "<b>bold</b>",
        )


class TestTemplateLoading:
    def test_from_string(self, cythonized):
        template = cythonized("Hello {{ name }}!")
        result = template.render({"name": "World"})
        assert result == "Hello World!"

    def test_get_template(self):
        engine = engines["cythonized"]
        template = engine.get_template("basic.txt")
        result = template.render({"user": "Alice"})
        assert result == "Hello Alice!\n"

    def test_extends(self):
        engine = engines["cythonized"]
        template = engine.get_template("child.html")
        result = template.render({"name": "Alice"})
        assert "<title>Child</title>" in result
        assert "<p>Hello Alice</p>" in result

    def test_include(self, assert_render):
        assert_render(
            '{% include "include_target.html" with message="hi" %}',
            {},
            "<span>hi</span>",
        )


class TestCustomTags:
    def test_load_and_use_custom_filter(self, cythonized, django_template):
        template_str = '{% load custom_filters %}{{ val|cut:" " }}'
        context = {"val": "hello world"}
        django_result = django_template(template_str).render(context)
        cythonized_result = cythonized(template_str).render(context)
        assert django_result == cythonized_result == "helloworld"

    def test_custom_double_filter(self, cythonized, django_template):
        template_str = "{% load custom_filters %}{{ val|double }}"
        context = {"val": 5}
        django_result = django_template(template_str).render(context)
        cythonized_result = cythonized(template_str).render(context)
        assert django_result == cythonized_result == "10"
