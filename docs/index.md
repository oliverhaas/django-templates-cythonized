# Django Templates Cythonized

Cython-accelerated Django template engine -- an exploratory package.

## What is this?

This package takes Django's template engine source code, compiles it with Cython for speed, and incrementally optimizes with type annotations and C-level code.

## Quick Start

```python
TEMPLATES = [
    {
        "BACKEND": "django_templates_cythonized.backend.CythonizedTemplates",
        "DIRS": [...],
        "APP_DIRS": True,
        "OPTIONS": {...},
    }
]
```

See [Installation](getting-started/installation.md) for full setup instructions.

## Status

This is an **alpha/exploratory** package. It is not production-ready.

## Attribution

- Django's template engine source code (BSD-3-Clause)
- Benchmark structure inspired by [django-rusty-templates](https://github.com/romanroe/django-rusty-templates)
