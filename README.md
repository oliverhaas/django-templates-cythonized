# django-templates-cythonized

Cython-accelerated Django template engine.

> **Exploratory / vibe-coded** -- this is a research project to see what kind of
> optimizations are possible and how much they help. The current code is the
> result of iterative profiling and optimization on top of Django's template
> source. Ideally this evolves into a clean, maintainable re-implementation of
> the template rendering pipeline, but we're not there yet.

## What is this?

This package takes the stock Django template engine, copies its source code, and compiles it with Cython for speed. The goal is to incrementally optimize with type annotations and C-level code, and see how far we can push performance.

This is explicitly exploratory -- motivated by wanting to work with Cython again, and curious how far we can push it vs. [django-rusty-templates](https://github.com/romanroe/django-rusty-templates) (Rust).

## Preliminary benchmarks

Measured on an AMD Ryzen 9 5950X (32 GB RAM) running Python 3.14t (free-threaded)
with `pytest-benchmark`. Note that typical cloud/web instances (e.g. 2-4 vCPU VMs)
are easily 3-10x slower than this desktop CPU, especially under load -- so the
absolute times below would be proportionally larger in production.

The "realistic" benchmark renders a book catalog table with `{% for %}`,
`{% if %}`/`{% elif %}`, `{% cycle %}`, `|capfirst` filters, and mixed
int/float/string variables. The "realistic + forms" variant adds Django form
widgets (4 fields per row).

| Benchmark | Cythonized | Stock Django | Speedup |
|-----------|-----------|--------------|---------|
| Realistic (1000 books, no forms) | 5.1 ms | 34.1 ms | **6.7x** |
| Realistic + forms (50 books, 4 widgets/row) | 6.0 ms | 20.6 ms | **3.4x** |

### Where the time goes

**Realistic (no forms):** Nearly all time is in our Cython template engine --
the loop body, variable resolution, filter application, and conditional
evaluation. This is where the 6.7x speedup comes from: C-level context dict
scanning, inlined `isinstance` fast paths for int/float/str, C-level filter
dispatch, and typed vtable calls for the `{% if %}` evaluator.

**Realistic + forms:** About ~1 ms is template engine work (same optimizations
as above), and the remaining ~5 ms is Django's Python form machinery --
`BoundField.as_widget()`, `Widget.render()`, `build_widget_attrs()`, etc. This
code lives in Django's `forms/` package and is pure Python we don't control.
The 3.4x speedup comes from accelerating the template rendering around the
form widgets (context reuse, template caching, `{% include %}` fast paths,
`|stringformat:'s'` bypass).

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
uv run pytest tests/benchmarks/ -v --no-cov -p no:codspeed  # Run benchmarks
```

After modifying `.py` source files, re-run `uv pip install -e .` to recompile.

## Attribution

- **Django's template engine** -- this package contains modified copies of Django's template source code, licensed under BSD-3-Clause
- **django-rusty-templates** -- benchmark structure inspired by the Rust approach
- **Django** -- BSD-3-Clause license

## License

BSD-3-Clause (matching Django's license)
