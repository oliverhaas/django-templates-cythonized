# django-templates-cythonized -- Battle Plan

## Context

Exploratory package: Cython-accelerated Django template engine. The goal is to take the stock Django template engine, compile it with Cython for speed, and incrementally optimize with type annotations and C-level code. This is explicitly exploratory -- motivated by wanting to work with Cython again, and curious how far we can push it vs. django-rusty-templates (Rust).

We copy tooling/structure from django-cachex, Django's own template code as our starting point, and benchmarks/tests from django-rusty-templates.

## Step 1: Create repo and project skeleton (from django-cachex)

Create a new repo `django-templates-cythonized` with django-cachex's tooling:

**Files to create (adapted from django-cachex):**

```
django_templates_cythonized/
├── __init__.py              # Package init, version
├── py.typed                 # PEP 561 marker
├── backend.py               # Django BACKEND entry point
├── engine.py                # Copy of django/template/engine.py
├── base.py                  # Copy of django/template/base.py (THE hot path)
├── context.py               # Copy of django/template/context.py
├── defaulttags.py           # Copy of django/template/defaulttags.py
├── defaultfilters.py        # Copy of django/template/defaultfilters.py
├── loader_tags.py           # Copy of django/template/loader_tags.py
├── library.py               # Copy of django/template/library.py
├── smartif.py               # Copy of django/template/smartif.py
├── exceptions.py            # Copy of django/template/exceptions.py
├── utils.py                 # Copy of django/template/utils.py
├── autoreload.py            # Copy of django/template/autoreload.py
├── response.py              # Copy of django/template/response.py (maybe just re-export)
├── loaders/                 # Copy of django/template/loaders/
│   ├── __init__.py
│   ├── filesystem.py
│   ├── app_directories.py
│   ├── cached.py
│   └── locmem.py
└── backends/                # Not needed -- our backend.py replaces this
tests/
├── conftest.py
├── settings.py
├── test_templates.py        # Django's own template tests (adapted)
├── templates/               # Test templates
└── benchmarks/
    ├── conftest.py
    ├── test_benchmarks.py   # From django-rusty-templates (adapted)
    └── templates/           # Benchmark templates
pyproject.toml               # setuptools + Cython build
setup.py                     # Minimal -- just cythonize() call
.python-version              # 3.14
uv.lock
mkdocs.yml
README.md
LICENSE                      # BSD-3 (matching Django's license)
.gitignore
.pre-commit-config.yaml
.github/
├── workflows/
│   ├── ci.yml               # Lint + test matrix
│   ├── tag.yml              # Auto-tag on version bump
│   ├── publish.yml          # PyPI publish (COMMENTED OUT)
│   └── docs.yml             # MkDocs deployment
└── dependabot.yml
docs/
├── index.md
├── getting-started/
│   └── installation.md
└── reference/
    └── changelog.md
```

**Key difference from django-cachex**: build backend is **setuptools** (not hatchling) because we need Cython compilation.

## Step 2: Build system (setuptools + Cython + uv)

**pyproject.toml:**
```toml
[build-system]
requires = ["setuptools>=74.1", "Cython>=3.0"]
build-backend = "setuptools.build_meta"

[project]
name = "django-templates-cythonized"
version = "0.1.0a1"
description = "Cython-accelerated Django template engine"
readme = "README.md"
license = "BSD-3-Clause"
requires-python = ">=3.12"
authors = [{ name = "Oliver Haas", email = "ohaas@e1plus.de" }]
dependencies = ["Django>=5.2,<7"]

[project.urls]
Homepage = "https://github.com/oliverhaas/django-templates-cythonized"

[dependency-groups]
dev = [
    "pytest>=8",
    "pytest-django>=4.10",
    "pytest-cov>=6",
    "pytest-codspeed>=3",
    "ruff>=0.11",
    "mypy>=1.15",
    "pre-commit>=4",
    "Cython>=3.0",
]
docs = ["mkdocs>=1.6", "mkdocs-material>=9", "mike>=2"]

[tool.setuptools.packages.find]
include = ["django_templates_cythonized*"]

[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "tests.settings"
pythonpath = ["tests"]
testpaths = ["tests"]
xfail_strict = true
addopts = "--cov=django_templates_cythonized --cov-report=term-missing --no-cov-on-fail"

[tool.ruff]
target-version = "py312"
line-length = 120
fix = true

[tool.ruff.lint]
select = ["ALL"]
# (will adapt django-cachex's ruff ignores)

[tool.mypy]
python_version = "3.12"
plugins = ["mypy_django_plugin.main"]
```

**setup.py** (minimal, just for Cython compilation):
```python
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
```

**Development workflow:**
```bash
uv sync --group dev                    # Install dependencies
uv pip install -e .                    # Build Cython extensions + editable install
uv run pytest                          # Run tests
uv run pytest tests/benchmarks/        # Run benchmarks
uv run cython -a django_templates_cythonized/base.py  # Generate HTML annotation report
```

Note: after modifying .py source files, must re-run `uv pip install -e .` to recompile Cython.

## Step 3: Copy Django template engine source

Copy the following files from Django's `django/template/` directory (Django 5.2 stable) into `django_templates_cythonized/`:

**Core hot path (these get cythonized):**
- `base.py` -- Template, Lexer, Parser, Variable, FilterExpression, NodeList, Node, TextNode, VariableNode
- `context.py` -- Context, RenderContext, RequestContext
- `defaulttags.py` -- ForNode, IfNode, WithNode, etc.
- `defaultfilters.py` -- 60+ built-in filters
- `loader_tags.py` -- BlockNode, ExtendsNode, IncludeNode
- `smartif.py` -- Smart conditional parsing

**Support modules (copied but lower priority for optimization):**
- `engine.py` -- Engine class
- `library.py` -- Library registration
- `exceptions.py` -- TemplateSyntaxError, TemplateDoesNotExist
- `utils.py` -- Utility functions
- `loaders/` -- filesystem, app_directories, cached loaders
- `autoreload.py`, `response.py`

**Modifications to copied code:**
- Fix all imports to reference `django_templates_cythonized` instead of `django.template` for the copied modules
- Keep importing from `django.template` for anything we DON'T copy (e.g., `django.template.backends.base.BaseEngine`)
- Add a `backend.py` that implements the BACKEND interface:

```python
from django.template.backends.base import BaseEngine
from django.template.backends.django import DjangoTemplates

class CythonizedTemplates(DjangoTemplates):
    """Drop-in replacement for DjangoTemplates that uses cythonized internals."""
    # Override the engine class to use our cythonized Engine
    # Strategy: subclass DjangoTemplates and swap the Engine
```

**Usage:**
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

## Step 4: Copy tests from Django + benchmarks from django-rusty-templates

**Django template tests:**
- Copy relevant tests from `django/tests/template_tests/`
- Adapt to run against our engine instead of Django's
- These serve as the compatibility baseline -- if our tests pass, we're compatible

**django-rusty-templates benchmarks:**
- Copy benchmark templates and test structure from `tests/benchmarks/`
- Uses pytest-codspeed for continuous benchmarking
- Benchmark: render various templates (simple variable substitution, loops, includes, inheritance) and compare times against stock Django

**Benchmark structure:**
```python
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

def test_render_loop(benchmark, cythonized_engine):
    template = cythonized_engine.from_string("{% for i in items %}{{ i }}{% endfor %}")
    benchmark(template.render, {"items": range(1000)})
```

## Step 5: Incremental Cythonization strategy

**Phase 1: Compile as-is (no annotations)**
- Just compiling pure Python with Cython gives ~20-50% speedup automatically
- This is the initial release -- validates everything works
- Run benchmarks to establish baseline

**Phase 2: Pure Python mode annotations on hot path**
- Start with `base.py` -- this is where most time is spent:
  - `Variable.resolve()` -- dot notation traversal, called thousands of times per render
  - `FilterExpression.resolve()` -- filter chain application
  - `NodeList.render()` -- core rendering loop
  - `TextNode.render()`, `VariableNode.render()` -- leaf node rendering
- Add `@cython.ccall`, `@cython.cfunc`, typed variables
- Use `cython -a base.py` to visualize optimization opportunities (yellow = Python API calls, white = pure C)

**Phase 3: Context and tags**
- `context.py` -- Context variable lookup (dict-like operations)
- `defaulttags.py` -- ForNode, IfNode (hot loops)
- `defaultfilters.py` -- individual filter functions

**Phase 4: Consider C-level replacements**
- If pure Python mode hits a ceiling, replace specific hot functions with raw C
- This is the "maybe later" phase -- depends on how far pure Python mode gets us

## Step 6: README and docs

README should be clear about:
- **Exploratory package** -- this is a learning/research project, not production-ready yet
- **How it works** -- copies Django's template engine source, compiles with Cython
- **Attribution** -- Django's template engine (BSD-3), benchmarks from django-rusty-templates
- **django-rusty-templates** -- the Rust approach exists and is probably better long-term; this is the Cython approach for comparison and exploration
- **Status** -- alpha, seeking benchmarks and feedback

## Step 7: CI (adapted from django-cachex)

**ci.yml:**
- Lint job: ruff + mypy
- Test job: matrix of Python 3.12/3.13/3.14 x Django 5.2/6.0
- Must install with `uv pip install -e .` (not just `uv sync`) to trigger Cython compilation
- Benchmark job: run benchmarks and report (pytest-codspeed or just pytest-benchmark)

**tag.yml + publish.yml:**
- tag.yml: same as django-cachex (auto-tag on version bump)
- publish.yml: **COMMENTED OUT** -- not publishing to PyPI yet

## Verification

1. `uv pip install -e .` succeeds (Cython compilation works)
2. `uv run pytest tests/` passes (all Django template tests pass)
3. `uv run pytest tests/benchmarks/` runs and shows timing comparison
4. `cython -a django_templates_cythonized/base.py` generates annotation HTML
5. Django test project with `BACKEND = "django_templates_cythonized.backend.CythonizedTemplates"` renders pages correctly

---

## Public API Surface Analysis

Everything below documents what **must stay Python-compatible** (because user/third-party code touches it) versus what is **purely internal** (can be full C structs, cdef functions, etc.).

### Boundary 1: Template Rendering (user calls)

Users call `template.render(context)` where context is a `dict`, `Context`, or `RequestContext`. The `Engine.from_string()` and `Engine.get_template()` methods return `Template` objects. This is the outer shell — it must accept Python objects.

**Must stay Python:**
- `Template.render(context)` — accepts dict or Context
- `Engine.from_string(string)` → Template
- `Engine.get_template(name)` → Template
- `Context(dict)`, `RequestContext(request, dict)` constructors

### Boundary 2: Context Protocol (custom tags read/write context)

Custom tags receive `context` in `render(self, context)` and call:

```python
context["key"]              # __getitem__ — lookup variable
context["key"] = value      # __setitem__ — set variable
context.get("key")          # get with default
key in context              # __contains__
context.push()              # push new scope (returns context manager)
context.pop()               # pop scope
context.update(other_dict)  # push dict onto stack
context.flatten()           # merge all dicts
context.autoescape          # bool flag
context.use_l10n            # localization flag
context.use_tz              # timezone flag
context.template            # current Template being rendered
context.render_context       # RenderContext for tag-local state storage
context.dicts               # the internal list[dict] stack (some tags touch this)
```

**Implication:** BaseContext can't be a cclass (push uses `*args/**kwargs`, user-subclassed via RequestContext). The `dicts` attribute is a Python `list[dict]` and must remain so — user code and third-party tags may iterate it.

### Boundary 3: Custom Template Tags (user writes)

Users subclass `Node` and implement `render(self, context)`:

```python
class MyNode(Node):
    child_nodelists = ("nodelist",)  # declares which attrs are NodeLists

    def __init__(self, nodelist, expression):
        self.nodelist = nodelist
        self.expression = expression  # FilterExpression

    def render(self, context):
        value = self.expression.resolve(context)
        output = self.nodelist.render(context)
        return f"<div>{value}{output}</div>"
```

Compile function receives parser + token:

```python
@register.tag("my_tag")
def do_my_tag(parser, token):
    bits = token.split_contents()          # list[str]
    expr = parser.compile_filter(bits[1])  # FilterExpression
    nodelist = parser.parse(("endmy_tag",))
    parser.delete_first_token()
    return MyNode(nodelist, expr)
```

**Must stay Python:**
- `Node` base class (subclassed by user code)
- `Node.render(context)` signature
- `Node.child_nodelists` tuple (framework iterates it for `get_nodes_by_type`)
- `Node.token`, `Node.origin` (set by framework, read for error reporting)
- `FilterExpression.resolve(context)` — returns resolved value
- `parser.compile_filter(string)` → FilterExpression
- `token.split_contents()` → list[str]
- `token_kwargs(bits, parser)` → dict
- `NodeList.render(context)` — renders child nodes to string
- `Library` class: `.tag()`, `.filter()`, `.simple_tag()`, `.inclusion_tag()`

### Boundary 4: Custom Template Filters (user writes)

```python
@register.filter(is_safe=True)
def my_filter(value, arg=None):
    return str(value) + str(arg)

@register.filter(needs_autoescape=True)
def my_filter2(value, autoescape=True):
    if autoescape:
        value = conditional_escape(value)
    return mark_safe(f"<b>{value}</b>")
```

**Must stay Python:**
- `@register.filter()` decorator with flags: `is_safe`, `needs_autoescape`, `expects_localtime`
- Filter function signature: `(value)` or `(value, arg)` or with `autoescape=` kwarg
- `@stringfilter` decorator (wraps filter to auto-convert to str, preserve SafeData)

### Boundary 5: Variable Resolution Protocol (user objects in context)

When a template does `{{ object.attr.method }}`, Variable._resolve_lookup tries, in order:

1. `object[attr]` — `__getitem__`
2. `getattr(object, attr)` — attribute access
3. `object[int(attr)]` — integer index

If the result is callable:
- `do_not_call_in_templates = True` → don't call, return as-is
- `alters_data = True` → return `string_if_invalid`
- Otherwise → call with no args

**Must stay Python:** This entire protocol operates on arbitrary user Python objects. Can't be replaced with C structs.

### Boundary 6: forloop Object (CForloopContext)

Template code accesses `{{ forloop.counter }}`, which goes through `Variable._resolve_lookup` calling `context["forloop"]["counter"]`. Custom tags inside loops may also access `context["forloop"]`.

`CForloopContext` is already a cclass (C struct for `_i`, `_length`) with Python `__getitem__` for the dict-like interface. IfChangedNode stores state on it via `forloop[self] = compare_to` and `forloop.setdefault(self)`.

**Must stay Python-compatible:**
- `__getitem__(key)` for standard keys (counter, counter0, revcounter, revcounter0, first, last, length, parentloop)
- `__setitem__(key, value)` for arbitrary state storage (IfChangedNode)
- `__contains__(key)` for `in` checks
- `setdefault(key, default)` for IfChangedNode state init

**Can be C:** The internal `_i`, `_length`, `_parentloop` fields. The `_extra` dict is only created lazily when `__setitem__` is called with a non-standard key.

### Summary: What's Internal (Can Be Full C)

| Component | Status | Why |
|-----------|--------|-----|
| `_render_var_fast()` | **Internal** | Only called by NodeList.render / ForNode.render |
| `_render_var_with_value()` | **Internal** | Only called by ForNode ultra-fast loop |
| `_fe_is_direct_loopvar()` | **Internal** | Only called by ForNode pre-scan |
| `_resolve_fe_raw()` | **Internal** | Only called by TemplateLiteral.eval |
| `_fast_escape()` | **Internal** | Only called by _render_var_fast |
| `_context_lookup()` | **Internal** | Only called by BaseContext methods |
| `Variable._resolve_lookup()` | **Internal** | Only called by Variable.resolve |
| `Variable.lookups`, `.translate`, `.literal` | **Internal** | Never accessed by user code |
| `FilterExpression.filters` tuple | **Internal** | Users only call `.resolve()` |
| `FilterExpression._fast_filter` | **Internal** | C-level filter dispatch code |
| `CForloopContext._i`, `._length` | **Internal** | C ints, only accessed by ForNode |
| `NodeList._nodes` list | **Semi-internal** | Advanced third-party code may access |
| `TextNode.s` | **Internal** | Framework-only access |
| `VariableNode.filter_expression` | **Semi-internal** | Advanced third-party code may access |
| ForNode inner render loop | **Internal** | Entirely framework code |

### What This Means for Further Optimization

The hot loop in ForNode is 100% internal code. On each iteration:

1. `loop_ctx._i = i` — already C int assignment
2. `top[loopvar0] = item` — **Python dict write** (skipped in ultra-fast path)
3. For each VariableNode: scan `context.dicts` — **Python dict lookups** (skipped in ultra-fast path)
4. String escaping — `_fast_escape` already does C-level char scanning
5. `"".join(nodelist)` — unavoidable Python string join

After Phase 11 (direct loopvar bypass), the remaining per-iteration overhead in the ultra-fast loop path is:

- `enumerate(values)` — Python iterator protocol on user-provided iterable
- `isinstance(inner_node, TextNode)` — C-level type check (fast)
- `_render_var_with_value(fe, item, context)` — cdef function, fast
  - Inside: `isinstance(value, str)`, `context.autoescape` access, `_fast_escape(value)`
- List assignment `nodelist[idx] = result` — C-level list setitem (fast)

The remaining Python overhead is:
- **`enumerate(values)`** — iterating user-provided list. Can't avoid Python iterator protocol since `values` comes from user context.
- **`context.autoescape` access** — Python attribute access on BaseContext (not a cclass). Could be cached once before the loop.
- **`render_value_in_context(item, context)` for non-string items** — calls `localize()` and `template_localtime()`. Only hit for non-string values (ints, datetimes, etc.).
- **`"".join(nodelist)`** — final string concatenation. Unavoidable.
