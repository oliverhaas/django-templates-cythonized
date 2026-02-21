"""Benchmarks comparing cythonized vs stock Django template rendering.

Run with: uv run pytest tests/benchmarks/ -v
"""

import pytest


@pytest.fixture
def loop_context():
    return {"items": list(range(1000))}


@pytest.fixture
def variable_context():
    return {k: f"value_{k}" for k in "abcdefghij"}


@pytest.fixture
def filter_context():
    return {"name": "Hello World", "count": 42}


@pytest.fixture
def if_context():
    return {"a": False, "b": False, "c": True}


# --- Cythonized engine benchmarks ---


@pytest.mark.benchmark(group="loop")
def test_cythonized_loop(benchmark, cythonized_engine, loop_context):
    template = cythonized_engine.from_string(
        "{% for item in items %}{{ item }}{% endfor %}"
    )
    benchmark(template.render, loop_context)


@pytest.mark.benchmark(group="variables")
def test_cythonized_variables(benchmark, cythonized_engine, variable_context):
    template = cythonized_engine.from_string(
        "{{ a }} {{ b }} {{ c }} {{ d }} {{ e }} {{ f }} {{ g }} {{ h }} {{ i }} {{ j }}"
    )
    benchmark(template.render, variable_context)


@pytest.mark.benchmark(group="filters")
def test_cythonized_filters(benchmark, cythonized_engine, filter_context):
    template = cythonized_engine.from_string(
        "{{ name|lower }} {{ name|upper }} {{ name|capfirst }} {{ count|add:1 }} {{ name|slugify }}"
    )
    benchmark(template.render, filter_context)


@pytest.mark.benchmark(group="if")
def test_cythonized_if(benchmark, cythonized_engine, if_context):
    template = cythonized_engine.from_string(
        "{% if a %}A{% elif b %}B{% elif c %}C{% else %}D{% endif %}"
    )
    benchmark(template.render, if_context)


@pytest.mark.benchmark(group="plain_text")
def test_cythonized_plain_text(benchmark, cythonized_engine):
    template = cythonized_engine.from_string("Hello World! " * 100)
    benchmark(template.render, {})


# --- Stock Django engine benchmarks ---


@pytest.mark.benchmark(group="loop")
def test_stock_loop(benchmark, stock_engine, loop_context):
    template = stock_engine.from_string(
        "{% for item in items %}{{ item }}{% endfor %}"
    )
    benchmark(template.render, loop_context)


@pytest.mark.benchmark(group="variables")
def test_stock_variables(benchmark, stock_engine, variable_context):
    template = stock_engine.from_string(
        "{{ a }} {{ b }} {{ c }} {{ d }} {{ e }} {{ f }} {{ g }} {{ h }} {{ i }} {{ j }}"
    )
    benchmark(template.render, variable_context)


@pytest.mark.benchmark(group="filters")
def test_stock_filters(benchmark, stock_engine, filter_context):
    template = stock_engine.from_string(
        "{{ name|lower }} {{ name|upper }} {{ name|capfirst }} {{ count|add:1 }} {{ name|slugify }}"
    )
    benchmark(template.render, filter_context)


@pytest.mark.benchmark(group="if")
def test_stock_if(benchmark, stock_engine, if_context):
    template = stock_engine.from_string(
        "{% if a %}A{% elif b %}B{% elif c %}C{% else %}D{% endif %}"
    )
    benchmark(template.render, if_context)


@pytest.mark.benchmark(group="plain_text")
def test_stock_plain_text(benchmark, stock_engine):
    template = stock_engine.from_string("Hello World! " * 100)
    benchmark(template.render, {})
