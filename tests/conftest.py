import pytest
from django.core.management import call_command
from django.template import engines


@pytest.fixture(scope="session")
def django_db_setup(django_test_environment, django_db_blocker):
    """Create database tables for admin integration tests (in-memory SQLite)."""
    with django_db_blocker.unblock():
        call_command("migrate", "--run-syncdb", verbosity=0)


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
