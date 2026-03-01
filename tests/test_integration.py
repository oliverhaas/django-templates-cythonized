"""Integration tests comparing cythonized vs stock Django on realistic templates.

These render complex, multi-feature templates with both engines and assert
that the output is byte-for-byte identical.
"""

import pytest
from django import forms
from django.template import engines


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GENRES = ["fiction", "non-fiction", "science", "history", "biography"]
AUTHORS = [
    "Alice Smith", "Bob Jones", "Carol White",
    "David Brown", "Eve Davis", "Frank Miller",
]


def _make_books(n, with_forms=False):
    books = []
    for i in range(n):
        book = {
            "id": i + 1,
            "title": f"The Great Book of Everything Vol. {i + 1}",
            "author": AUTHORS[i % len(AUTHORS)],
            "year": 2000 + (i % 25),
            "genre": GENRES[i % len(GENRES)],
            "price": 9.99 + (i % 30),
            "in_stock": i % 3 != 0,
            "rating": (i % 5) + 1,
            "description": f"A fascinating exploration of topics in volume {i + 1}.",
        }
        if with_forms:
            book["order_form"] = BookOrderForm(
                initial={"quantity": 1}, prefix=f"book_{i + 1}",
            )
        books.append(book)
    return books


class BookOrderForm(forms.Form):
    quantity = forms.IntegerField(min_value=1, max_value=99, initial=1)
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Special instructions"}),
    )
    gift_wrap = forms.BooleanField(required=False)
    shipping = forms.ChoiceField(choices=[
        ("standard", "Standard"),
        ("express", "Express"),
        ("overnight", "Overnight"),
    ])


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

BOOKS_TEMPLATE = (
    '<h1>{{ site_name }} — Book Catalog</h1>'
    '<table class="catalog">'
    "<thead><tr>"
    "<th>#</th><th>Title</th><th>Author</th><th>Year</th>"
    "<th>Genre</th><th>Price</th><th>Rating</th><th>Status</th>"
    "</tr></thead>"
    "<tbody>"
    "{% for book in books %}"
    '<tr class="{% cycle \'odd\' \'even\' %}">'
    "<td>{{ forloop.counter }}</td>"
    "<td>{{ book.title }}</td>"
    "<td>{{ book.author }}</td>"
    "<td>{{ book.year }}</td>"
    "<td>{{ book.genre|capfirst }}</td>"
    "<td>{{ currency }}{{ book.price }}</td>"
    "<td>{% if book.rating == 5 %}★★★★★"
    "{% elif book.rating == 4 %}★★★★"
    "{% elif book.rating == 3 %}★★★"
    "{% elif book.rating == 2 %}★★"
    "{% else %}★{% endif %}</td>"
    "<td>{% if book.in_stock %}"
    '<span class="yes">In Stock</span>'
    "{% else %}"
    '<span class="no">Out of Stock</span>'
    "{% endif %}</td>"
    "</tr>"
    "{% if show_description %}"
    '<tr class="desc"><td colspan="8">{{ book.description }}</td></tr>'
    "{% endif %}"
    "{% endfor %}"
    "</tbody></table>"
    "<p>Showing {{ books|length }} books</p>"
)

# Each book carries its own order_form (per-row, not shared).
BOOKS_WITH_FORMS_TEMPLATE = (
    '<h1>{{ site_name }} — Book Catalog</h1>'
    '<table class="catalog">'
    "<thead><tr>"
    "<th>#</th><th>Title</th><th>Author</th><th>Year</th>"
    "<th>Genre</th><th>Price</th><th>Rating</th><th>Status</th>"
    "</tr></thead>"
    "<tbody>"
    "{% for book in books %}"
    '<tr class="{% cycle \'odd\' \'even\' %}">'
    "<td>{{ forloop.counter }}</td>"
    "<td>{{ book.title }}</td>"
    "<td>{{ book.author }}</td>"
    "<td>{{ book.year }}</td>"
    "<td>{{ book.genre|capfirst }}</td>"
    "<td>{{ currency }}{{ book.price }}</td>"
    "<td>{% if book.rating == 5 %}★★★★★"
    "{% elif book.rating == 4 %}★★★★"
    "{% elif book.rating == 3 %}★★★"
    "{% elif book.rating == 2 %}★★"
    "{% else %}★{% endif %}</td>"
    "<td>{% if book.in_stock %}"
    '<span class="yes">In Stock</span>'
    "{% else %}"
    '<span class="no">Out of Stock</span>'
    "{% endif %}</td>"
    "</tr>"
    "{% if show_description %}"
    '<tr class="desc"><td colspan="8">{{ book.description }}</td></tr>'
    "{% endif %}"
    '<tr class="modal-row" style="display:none">'
    '<td colspan="8">'
    '<div class="modal" id="order-modal-{{ book.id }}">'
    "<h3>Order: {{ book.title }}</h3>"
    '<form method="post" action="/order/{{ book.id }}/">'
    '<div class="field">'
    "<label>{{ book.order_form.quantity.label }}</label>"
    "{{ book.order_form.quantity }}"
    "</div>"
    '<div class="field">'
    "<label>{{ book.order_form.notes.label }}</label>"
    "{{ book.order_form.notes }}"
    "</div>"
    '<div class="field">'
    "<label>{{ book.order_form.gift_wrap.label }}</label>"
    "{{ book.order_form.gift_wrap }}"
    "</div>"
    '<div class="field">'
    "<label>{{ book.order_form.shipping.label }}</label>"
    "{{ book.order_form.shipping }}"
    "</div>"
    '<button type="submit">Place Order — {{ currency }}{{ book.price }}</button>'
    "</form>"
    "</div>"
    "</td></tr>"
    "{% endfor %}"
    "</tbody></table>"
    "<p>Showing {{ books|length }} books</p>"
)

# Named cycle variant — {% cycle 'odd' 'even' as rowclass %} then {{ rowclass }}
CYCLE_AS_TEMPLATE = (
    "{% for book in books %}"
    "{% cycle 'odd' 'even' as rowclass %}"
    '<tr class="{{ rowclass }}">'
    "<td>{{ book.title }}</td>"
    "<td>{{ rowclass }}</td>"
    "</tr>"
    "{% endfor %}"
)

# Nested loops
NESTED_LOOP_TEMPLATE = (
    "{% for book in books %}"
    "<div>{{ book.title }}:"
    "{% for tag in book.tags %}"
    " {{ tag }}"
    "{% endfor %}"
    "</div>"
    "{% endfor %}"
)

# forloop intrinsics
FORLOOP_TEMPLATE = (
    "{% for book in books %}"
    "{{ forloop.counter }}/{{ forloop.counter0 }}"
    "/{{ forloop.revcounter }}/{{ forloop.revcounter0 }}"
    "{% if forloop.first %} FIRST{% endif %}"
    "{% if forloop.last %} LAST{% endif %}"
    "|"
    "{% endfor %}"
)

# Empty loop with {% empty %}
EMPTY_LOOP_TEMPLATE = (
    "{% for book in books %}"
    "{{ book.title }}"
    "{% empty %}"
    "No books found."
    "{% endfor %}"
)

# Mixed filters
FILTERS_TEMPLATE = (
    "{% for book in books %}"
    "{{ book.title|upper }} by {{ book.author|lower }} "
    "({{ book.genre|capfirst }}) "
    "{{ book.price|floatformat:2 }} "
    "{{ book.in_stock|yesno:'yes,no' }}\n"
    "{% endfor %}"
)

# Constant if (condition doesn't depend on loop var)
CONST_IF_TEMPLATE = (
    "{% for book in books %}"
    "{% if show_description %}"
    "{{ book.description }}"
    "{% endif %}"
    "{% endfor %}"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def stock():
    return engines["django"]


@pytest.fixture
def cyth():
    return engines["cythonized"]


def _assert_engines_match(stock, cyth, template_string, context):
    """Render with both engines and assert identical output."""
    stock_result = stock.from_string(template_string).render(context)
    cyth_result = cyth.from_string(template_string).render(context)
    assert cyth_result == stock_result


# ---------------------------------------------------------------------------
# Integration tests — realistic templates
# ---------------------------------------------------------------------------

class TestRealisticTemplate:
    """Test the full realistic benchmark template (cycle + if/elif + counter + filters)."""

    def test_single_book(self, stock, cyth):
        ctx = {"books": _make_books(1), "show_description": True, "currency": "$", "site_name": "BookShop"}
        _assert_engines_match(stock, cyth, BOOKS_TEMPLATE, ctx)

    def test_three_books(self, stock, cyth):
        ctx = {"books": _make_books(3), "show_description": True, "currency": "$", "site_name": "BookShop"}
        _assert_engines_match(stock, cyth, BOOKS_TEMPLATE, ctx)

    def test_ten_books(self, stock, cyth):
        ctx = {"books": _make_books(10), "show_description": True, "currency": "$", "site_name": "BookShop"}
        _assert_engines_match(stock, cyth, BOOKS_TEMPLATE, ctx)

    def test_fifty_books(self, stock, cyth):
        ctx = {"books": _make_books(50), "show_description": True, "currency": "$", "site_name": "BookShop"}
        _assert_engines_match(stock, cyth, BOOKS_TEMPLATE, ctx)

    def test_no_description(self, stock, cyth):
        ctx = {"books": _make_books(10), "show_description": False, "currency": "€", "site_name": "Shop"}
        _assert_engines_match(stock, cyth, BOOKS_TEMPLATE, ctx)

    def test_empty_books(self, stock, cyth):
        ctx = {"books": [], "show_description": True, "currency": "$", "site_name": "BookShop"}
        _assert_engines_match(stock, cyth, BOOKS_TEMPLATE, ctx)


class TestRealisticWithFormsTemplate:
    """Test the realistic+forms benchmark template (per-book forms)."""

    def test_single_book_with_forms(self, stock, cyth):
        ctx = {
            "books": _make_books(1, with_forms=True), "show_description": True,
            "currency": "$", "site_name": "BookShop",
        }
        _assert_engines_match(stock, cyth, BOOKS_WITH_FORMS_TEMPLATE, ctx)

    def test_three_books_with_forms(self, stock, cyth):
        ctx = {
            "books": _make_books(3, with_forms=True), "show_description": True,
            "currency": "$", "site_name": "BookShop",
        }
        _assert_engines_match(stock, cyth, BOOKS_WITH_FORMS_TEMPLATE, ctx)

    def test_ten_books_with_forms(self, stock, cyth):
        ctx = {
            "books": _make_books(10, with_forms=True), "show_description": True,
            "currency": "$", "site_name": "BookShop",
        }
        _assert_engines_match(stock, cyth, BOOKS_WITH_FORMS_TEMPLATE, ctx)

    def test_fifty_books_with_forms(self, stock, cyth):
        ctx = {
            "books": _make_books(50, with_forms=True), "show_description": True,
            "currency": "$", "site_name": "BookShop",
        }
        _assert_engines_match(stock, cyth, BOOKS_WITH_FORMS_TEMPLATE, ctx)


class TestCycleNamed:
    """Test {% cycle ... as varname %} + {{ varname }} in loops."""

    def test_cycle_as_variable(self, stock, cyth):
        ctx = {"books": _make_books(6)}
        _assert_engines_match(stock, cyth, CYCLE_AS_TEMPLATE, ctx)

    def test_cycle_as_single_item(self, stock, cyth):
        ctx = {"books": _make_books(1)}
        _assert_engines_match(stock, cyth, CYCLE_AS_TEMPLATE, ctx)


class TestNestedLoops:
    """Test nested for loops."""

    def test_nested(self, stock, cyth):
        books = [
            {"title": "Book A", "tags": ["fiction", "classic"]},
            {"title": "Book B", "tags": ["science"]},
            {"title": "Book C", "tags": []},
        ]
        _assert_engines_match(stock, cyth, NESTED_LOOP_TEMPLATE, {"books": books})


class TestForloopIntrinsics:
    """Test forloop.counter, counter0, revcounter, revcounter0, first, last."""

    def test_forloop_vars(self, stock, cyth):
        ctx = {"books": _make_books(5)}
        _assert_engines_match(stock, cyth, FORLOOP_TEMPLATE, ctx)

    def test_forloop_single(self, stock, cyth):
        ctx = {"books": _make_books(1)}
        _assert_engines_match(stock, cyth, FORLOOP_TEMPLATE, ctx)


class TestEmptyLoop:
    """Test {% empty %} clause."""

    def test_with_items(self, stock, cyth):
        _assert_engines_match(stock, cyth, EMPTY_LOOP_TEMPLATE, {"books": _make_books(3)})

    def test_without_items(self, stock, cyth):
        _assert_engines_match(stock, cyth, EMPTY_LOOP_TEMPLATE, {"books": []})


class TestFiltersInLoop:
    """Test multiple filters applied inside a loop."""

    def test_various_filters(self, stock, cyth):
        ctx = {"books": _make_books(10)}
        _assert_engines_match(stock, cyth, FILTERS_TEMPLATE, ctx)


class TestConstantIfInLoop:
    """Test if-conditions that don't depend on the loop variable."""

    def test_const_true(self, stock, cyth):
        ctx = {"books": _make_books(5), "show_description": True}
        _assert_engines_match(stock, cyth, CONST_IF_TEMPLATE, ctx)

    def test_const_false(self, stock, cyth):
        ctx = {"books": _make_books(5), "show_description": False}
        _assert_engines_match(stock, cyth, CONST_IF_TEMPLATE, ctx)


# ---------------------------------------------------------------------------
# Custom template tags — simulates what a real package user would write
# ---------------------------------------------------------------------------


class TestCustomSimpleTag:
    """Test @register.simple_tag — basic, with args, takes_context, kwargs."""

    def test_simple_tag_basic(self, stock, cyth):
        _assert_engines_match(
            stock, cyth,
            '{% load custom_tags %}{% greeting "World" %}',
            {},
        )

    def test_simple_tag_with_variable(self, stock, cyth):
        _assert_engines_match(
            stock, cyth,
            '{% load custom_tags %}{% greeting name %}',
            {"name": "Alice"},
        )

    def test_simple_tag_multiple_args(self, stock, cyth):
        _assert_engines_match(
            stock, cyth,
            '{% load custom_tags %}{% add_numbers 3 7 %}',
            {},
        )

    def test_simple_tag_takes_context(self, stock, cyth):
        _assert_engines_match(
            stock, cyth,
            '{% load custom_tags %}{% current_user_greeting %}',
            {"user_name": "Bob"},
        )

    def test_simple_tag_takes_context_default(self, stock, cyth):
        _assert_engines_match(
            stock, cyth,
            '{% load custom_tags %}{% current_user_greeting %}',
            {},
        )

    def test_simple_tag_kwarg(self, stock, cyth):
        _assert_engines_match(
            stock, cyth,
            '{% load custom_tags %}{% format_price 19.99 currency="€" %}',
            {},
        )

    def test_simple_tag_kwarg_default(self, stock, cyth):
        _assert_engines_match(
            stock, cyth,
            '{% load custom_tags %}{% format_price 9.5 %}',
            {},
        )

    def test_simple_tag_as_variable(self, stock, cyth):
        _assert_engines_match(
            stock, cyth,
            '{% load custom_tags %}{% greeting "World" as g %}({{ g }})',
            {},
        )

    def test_simple_tag_in_loop(self, stock, cyth):
        _assert_engines_match(
            stock, cyth,
            '{% load custom_tags %}{% for name in names %}{% greeting name %} {% endfor %}',
            {"names": ["Alice", "Bob", "Carol"]},
        )


class TestCustomInclusionTag:
    """Test @register.inclusion_tag — renders a sub-template."""

    def test_inclusion_tag_basic(self, stock, cyth):
        _assert_engines_match(
            stock, cyth,
            '{% load custom_tags %}{% badge "New" %}',
            {},
        )

    def test_inclusion_tag_with_kwarg(self, stock, cyth):
        _assert_engines_match(
            stock, cyth,
            '{% load custom_tags %}{% badge "Error" kind="danger" %}',
            {},
        )

    def test_inclusion_tag_takes_context(self, stock, cyth):
        _assert_engines_match(
            stock, cyth,
            '{% load custom_tags %}{% user_card %}',
            {"user_name": "Alice", "role": "admin"},
        )

    def test_inclusion_tag_takes_context_defaults(self, stock, cyth):
        _assert_engines_match(
            stock, cyth,
            '{% load custom_tags %}{% user_card %}',
            {},
        )

    def test_inclusion_tag_in_loop(self, stock, cyth):
        _assert_engines_match(
            stock, cyth,
            '{% load custom_tags %}{% for item in items %}{% badge item.label item.kind %}{% endfor %}',
            {"items": [
                {"label": "Info", "kind": "info"},
                {"label": "Warn", "kind": "warning"},
                {"label": "OK", "kind": "success"},
            ]},
        )


class TestCustomNodeSubclass:
    """Test custom Node subclasses with manual tag parsing."""

    def test_repeat_literal(self, stock, cyth):
        _assert_engines_match(
            stock, cyth,
            '{% load custom_tags %}{% repeat 3 %}ha{% endrepeat %}',
            {},
        )

    def test_repeat_variable(self, stock, cyth):
        _assert_engines_match(
            stock, cyth,
            '{% load custom_tags %}{% repeat count %}{{ word }}{% endrepeat %}',
            {"count": 4, "word": "yo"},
        )

    def test_repeat_with_loop_inside(self, stock, cyth):
        _assert_engines_match(
            stock, cyth,
            '{% load custom_tags %}{% repeat 2 %}{% for x in items %}{{ x }}{% endfor %}-{% endrepeat %}',
            {"items": ["a", "b"]},
        )

    def test_upper_tag(self, stock, cyth):
        _assert_engines_match(
            stock, cyth,
            '{% load custom_tags %}{% upper %}hello {{ name }}{% endupper %}',
            {"name": "world"},
        )

    def test_upper_with_html(self, stock, cyth):
        _assert_engines_match(
            stock, cyth,
            '{% load custom_tags %}{% upper %}{{ text }}{% endupper %}',
            {"text": "<b>bold</b>"},
        )

    def test_nested_custom_tags(self, stock, cyth):
        _assert_engines_match(
            stock, cyth,
            '{% load custom_tags %}{% repeat 2 %}{% upper %}{{ word }}{% endupper %}-{% endrepeat %}',
            {"word": "hi"},
        )

    def test_custom_tag_in_for_loop(self, stock, cyth):
        """Custom tags inside a for loop — tests interaction with LOOPATTR etc."""
        _assert_engines_match(
            stock, cyth,
            '{% load custom_tags %}'
            '{% for item in items %}'
            '{% repeat item.count %}{{ item.word }}{% endrepeat %}|'
            '{% endfor %}',
            {"items": [
                {"count": 2, "word": "a"},
                {"count": 3, "word": "b"},
                {"count": 1, "word": "c"},
            ]},
        )
