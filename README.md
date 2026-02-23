# django-templates-cythonized

Cython-accelerated drop-in replacement for Django's template engine.

> **Exploratory / vibe-coded** -- iterative profiling and optimization on top of
> Django's template source. Ideally this evolves into a clean re-implementation,
> but we're not there yet.

Copies Django's template engine source and compiles it with Cython, then
incrementally optimizes with type annotations, `.pxd` declarations, and C-level
fast paths. Motivated by wanting to work with Cython again, and curious how far
we can push it vs. [django-rusty-templates](https://github.com/romanroe/django-rusty-templates) (Rust).

## Benchmarks

Measured on an AMD Ryzen 9 5950X, Python 3.14t (free-threaded). Typical cloud
instances (2-4 vCPU) are easily 3-10x slower, especially under load -- on those
machines stock Django template renders can lose several hundred ms on a single
page. We'd like that to not be something we have to think about.

| Benchmark | Cythonized | Stock Django | Speedup |
|-----------|-----------|--------------|---------|
| 1000-book table (for/if/cycle/filters) | 5.1 ms | 34.1 ms | **6.7x** |
| 50-book table + 4 form widgets/row | 6.0 ms | 20.6 ms | **3.4x** |

**Without forms** the speedup is pure template engine: C-level context dict
scanning, inlined int/float/str fast paths, C-level filter dispatch, typed
vtable calls for `{% if %}`. **With forms** ~5 ms is Django's pure-Python form
machinery (`BoundField.as_widget()`, `Widget.render()`, etc.) that we don't
control; the 3.4x comes from accelerating everything around it (context reuse,
template caching, `{% include %}` fast paths, `|stringformat:'s'` bypass).

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

Re-run `uv pip install -e .` after modifying `.py` files to recompile.

## Attribution & License

Contains modified copies of Django's template source code.
BSD-3-Clause (matching Django). Benchmark structure inspired by
[django-rusty-templates](https://github.com/romanroe/django-rusty-templates).
