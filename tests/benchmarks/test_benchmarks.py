"""Benchmarks comparing cythonized vs stock Django template rendering.

Run with: uv run pytest tests/benchmarks/ -v --no-cov -p no:codspeed
"""

import pytest
from django import forms

from django_templates_cythonized.backend import CythonizedFormRenderer


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


GENRES = ["fiction", "non-fiction", "science", "history", "biography"]
AUTHORS = [
    "Alice Smith", "Bob Jones", "Carol White",
    "David Brown", "Eve Davis", "Frank Miller",
]


def _make_books(n):
    return [
        {
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
        for i in range(n)
    ]


# Template WITHOUT form widgets — pure template engine workload.
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

# Template WITH form widgets per row — tests form rendering overhead.
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
    "<label>{{ order_form.quantity.label }}</label>"
    "{{ order_form.quantity }}"
    "</div>"
    '<div class="field">'
    "<label>{{ order_form.notes.label }}</label>"
    "{{ order_form.notes }}"
    "</div>"
    '<div class="field">'
    "<label>{{ order_form.gift_wrap.label }}</label>"
    "{{ order_form.gift_wrap }}"
    "</div>"
    '<div class="field">'
    "<label>{{ order_form.shipping.label }}</label>"
    "{{ order_form.shipping }}"
    "</div>"
    '<button type="submit">Place Order — {{ currency }}{{ book.price }}</button>'
    "</form>"
    "</div>"
    "</td></tr>"
    "{% endfor %}"
    "</tbody></table>"
    "<p>Showing {{ books|length }} books</p>"
)


# --- Realistic: 1000 books, no forms (pure template engine) ---


@pytest.mark.benchmark(group="realistic")
def test_cythonized_realistic(benchmark, cythonized_engine):
    context = {
        "books": _make_books(1000),
        "show_description": True,
        "currency": "$",
        "site_name": "BookShop",
    }
    template = cythonized_engine.from_string(BOOKS_TEMPLATE)
    benchmark(template.render, context)


@pytest.mark.benchmark(group="realistic")
def test_stock_realistic(benchmark, stock_engine):
    context = {
        "books": _make_books(1000),
        "show_description": True,
        "currency": "$",
        "site_name": "BookShop",
    }
    template = stock_engine.from_string(BOOKS_TEMPLATE)
    benchmark(template.render, context)


# --- Realistic + forms: 50 books with form widgets per row ---


@pytest.mark.benchmark(group="realistic_forms")
def test_cythonized_realistic_forms(benchmark, cythonized_engine):
    context = {
        "books": _make_books(50),
        "show_description": True,
        "currency": "$",
        "site_name": "BookShop",
        "order_form": BookOrderForm(renderer=CythonizedFormRenderer()),
    }
    template = cythonized_engine.from_string(BOOKS_WITH_FORMS_TEMPLATE)
    benchmark(template.render, context)


@pytest.mark.benchmark(group="realistic_forms")
def test_stock_realistic_forms(benchmark, stock_engine):
    context = {
        "books": _make_books(50),
        "show_description": True,
        "currency": "$",
        "site_name": "BookShop",
        "order_form": BookOrderForm(),
    }
    template = stock_engine.from_string(BOOKS_WITH_FORMS_TEMPLATE)
    benchmark(template.render, context)
