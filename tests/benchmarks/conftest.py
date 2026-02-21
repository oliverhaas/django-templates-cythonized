import pytest
from django.template import engines


@pytest.fixture
def cythonized_engine():
    """Our cythonized engine."""
    return engines["cythonized"]


@pytest.fixture
def stock_engine():
    """Stock Django engine for comparison."""
    return engines["django"]
