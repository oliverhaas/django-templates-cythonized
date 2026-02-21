# django-templates-cythonized

Cython-accelerated Django template engine.

> **Exploratory package** -- this is a learning/research project, not production-ready yet.

## What is this?

This package takes the stock Django template engine, copies its source code, and compiles it with Cython for speed. The goal is to incrementally optimize with type annotations and C-level code, and see how far we can push performance.

This is explicitly exploratory -- motivated by wanting to work with Cython again, and curious how far we can push it vs. [django-rusty-templates](https://github.com/romanroe/django-rusty-templates) (Rust).

## How it works

1. **Copy** Django's template engine source (`django/template/`) into our package
2. **Compile** all `.py` files with Cython (just compiling pure Python gives ~20-50% speedup)
3. **Incrementally optimize** with `@cython.ccall`, typed variables, and C-level code
4. **Drop-in replacement** -- configure as a Django template backend

## Installation

```bash
pip install django-templates-cythonized
```

## Usage

```python
TEMPLATES = [
    {
        "BACKEND": "django_templates_cythonized.backend.CythonizedTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]
```

## Development

```bash
git clone https://github.com/oliverhaas/django-templates-cythonized.git
cd django-templates-cythonized
uv sync --group dev
uv pip install -e .          # Build Cython extensions
uv run pytest                # Run tests
uv run pytest tests/benchmarks/  # Run benchmarks
```

After modifying `.py` source files, re-run `uv pip install -e .` to recompile.

## Attribution

- **Django's template engine** -- this package contains modified copies of Django's template source code, licensed under BSD-3-Clause
- **django-rusty-templates** -- benchmark structure inspired by the Rust approach
- **Django** -- BSD-3-Clause license

## License

BSD-3-Clause (matching Django's license)
