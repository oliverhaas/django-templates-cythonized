from Cython.Build import cythonize
from setuptools import setup

setup(
    ext_modules=cythonize(
        "django_templates_cythonized/*.py",
        exclude=["django_templates_cythonized/__init__.py"],
        compiler_directives={
            "language_level": "3",
            "boundscheck": False,
            "wraparound": True,
            "cdivision": True,
            "infer_types": True,
            "profile": False,
        },
    ),
)
