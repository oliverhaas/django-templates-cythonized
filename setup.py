from setuptools import setup
from Cython.Build import cythonize

setup(
    ext_modules=cythonize(
        "django_templates_cythonized/*.py",
        exclude=["django_templates_cythonized/__init__.py"],
        compiler_directives={
            "language_level": "3",
            "boundscheck": False,
            "wraparound": False,
        },
    ),
)
