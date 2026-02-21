import pytest
from django.template import engines


@pytest.fixture
def cythonized():
    return engines["cythonized"].from_string


@pytest.fixture
def django_template():
    return engines["django"].from_string


@pytest.fixture
def assert_render(cythonized, django_template):
    """Render with both engines and assert identical output."""

    def _assert(template_string, context, expected):
        django_result = django_template(template_string).render(context)
        cythonized_result = cythonized(template_string).render(context)
        assert django_result == expected
        assert cythonized_result == expected

    return _assert
