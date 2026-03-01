# django-templates-cythonized

Cython-accelerated drop-in replacement for Django's template engine.
**3-13x faster** depending on template complexity.

> **Exploratory / vibe-coded** -- iterative profiling and optimization on top of
> Django's template source. Ideally this evolves into a clean re-implementation,
> but we're not there yet.

Copies Django's template engine source and compiles it with Cython, then
incrementally optimizes with type annotations, `.pxd` declarations, and C-level
fast paths. Accelerates both the normal template renderer and the form renderer
(via `CythonizedFormRenderer` which handles widget template rendering).

Fully compatible with existing Django templates, custom tags (`@register.simple_tag`,
`@register.inclusion_tag`, custom `Node` subclasses), and custom filters.

Motivated by wanting to work with Cython again, and curious how far we can push
it vs. [django-rusty-templates](https://github.com/romanroe/django-rusty-templates) (Rust).

## Benchmarks

Measured on an AMD Ryzen 9 5950X, Python 3.14t (free-threaded). Typical cloud
instances (2-4 vCPU) are easily 3-10x slower, especially under load -- on those
machines stock Django template renders can lose several hundred ms on a single
page. We'd like that to not be something we have to think about.

| Benchmark | Cythonized | Stock Django | Speedup |
|-----------|-----------|--------------|---------|
| 1000-book table (for/if/cycle/filters) | 2.5 ms | 33.4 ms | **13x** |
| 50-book table + per-book forms (4 widgets/row) | 5.5 ms | 20.5 ms | **3.7x** |

**Without forms** the speedup is pure template engine: loop body pre-classification
(LOOPATTR, LOOPIF, LOOPCYCLE, FORLOOP_COUNTER), constant variable caching,
C-level context dict scanning, inlined int/float/str fast paths, C-level filter
dispatch, and typed vtable calls for `{% if %}` conditions.

**With forms** ~4 ms is Django's pure-Python form machinery
(`BoundField.as_widget()`, `Widget.render()`, etc.) that we don't control; the
3.7x comes from accelerating everything around it (context reuse, template
caching, `{% include %}` fast paths, `|stringformat:'s'` bypass).

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

For form-heavy templates, also set the form renderer to avoid falling back to
stock Django for widget rendering:

```python
from django_templates_cythonized.backend import CythonizedFormRenderer

FORM_RENDERER = "django_templates_cythonized.backend.CythonizedFormRenderer"
```

## Development

```bash
git clone https://github.com/oliverhaas/django-templates-cythonized.git
cd django-templates-cythonized
uv sync --group dev
uv pip install -e .          # Build Cython extensions
uv run pytest                # Run tests (88 tests)
uv run pytest tests/benchmarks/ -v --no-cov -p no:codspeed  # Run benchmarks
```

Re-run `uv pip install -e .` after modifying `.py` files to recompile.

## Attribution & License

Contains modified copies of Django's template source code.
BSD-3-Clause (matching Django). Benchmark structure inspired by
[django-rusty-templates](https://github.com/romanroe/django-rusty-templates).
