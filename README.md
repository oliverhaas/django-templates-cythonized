# django-templates-cythonized

Cython-accelerated drop-in replacement for Django's template engine.
**3-14x faster** depending on template complexity.

This is a benchmarking tool to evaluate what a Cython-level template speedup
would bring to your project. Not meant for production use. Feel free to try
though — if you run into issues, open an issue and I'll see if I can help.

## Benchmarks

Measured on an AMD Ryzen 9 5950X, Python 3.14t (free-threaded).

| Benchmark | Cythonized | Stock Django | Speedup |
|-----------|-----------|--------------|---------|
| 1000-book table (for/if/cycle/filters) | 2.4 ms | 33.7 ms | **14x** |
| 50-book table + per-book forms (4 widgets/row) | 6.1 ms | 21.3 ms | **3.5x** |

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

For form-heavy templates, also set the form renderer:

```python
FORM_RENDERER = "django_templates_cythonized.backend.CythonizedFormRenderer"
```

## Development

```bash
git clone https://github.com/oliverhaas/django-templates-cythonized.git
cd django-templates-cythonized
uv sync --group dev
uv pip install -e .          # Build Cython extensions
uv run pytest                # Run tests
uv run pytest tests/benchmarks/ -v --no-cov -p no:codspeed  # Run benchmarks
```

Re-run `uv pip install -e .` after modifying `.py` files to recompile.

## Attribution & License

Contains modified copies of Django's template source code.
BSD-3-Clause (matching Django). Benchmark structure inspired by
[django-rusty-templates](https://github.com/romanroe/django-rusty-templates).
