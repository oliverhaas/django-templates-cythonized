# CLAUDE.md

## Project Overview

Cython-accelerated Django template engine. Copies Django's template source, compiles with Cython, and incrementally optimizes with type annotations and C-level code.

## Development Workflow

```bash
uv sync --group dev          # Install dependencies
uv pip install -e .          # Build Cython extensions (must re-run after .py changes)
uv run pytest tests/ --ignore=tests/benchmarks/ -v  # Run tests
```

## Cython Pure Python Mode Guidelines

We use Cython's **pure Python mode** — all type declarations live in `.py` files using `import cython` and decorators/annotations. The `.py` files remain valid Python when Cython is not installed (decorators are no-ops).

### Extension types (`cdef class`)

Use `@cython.cclass` to make a class an extension type (C-struct attributes, fast method dispatch):

```python
@cython.cclass
class Variable:
    cython.declare(var=object, literal=object, lookups=object)
    cython.declare(translate=cython.bint, message_context=object)

    @cython.ccall
    def resolve(self, context):
        ...

    @cython.cfunc
    def _resolve_lookup(self, context) -> object:
        ...
```

- `@cython.ccall` → `cpdef` (callable from Python AND C, fast path from Cython code)
- `@cython.cfunc` → `cdef` (C-only, not visible from Python — use for private methods)
- `cython.declare(...)` → typed attributes stored in C struct

### Key constraints

1. **`@cython.ccall` only works on `@cython.cclass` methods and module-level functions** — NOT on regular Python class methods. Attempting it causes a compiler crash: `AttributeError: 'PyObjectType' object has no attribute 'entry'`.

2. **`@cython.cclass` cannot inherit from a regular Python class.** But a regular Python class CAN inherit from a `@cython.cclass`. This means:
   - `Node` CANNOT be `@cython.cclass` (third-party tags subclass it from Python)
   - `Variable`, `FilterExpression` CAN be `@cython.cclass` (never subclassed externally)

3. **`cpdef`/`@cython.ccall` methods cannot have `*args` or `**kwargs`.** So `BaseContext.push(*args, **kwargs)` must stay `def`.

4. **Remove `__slots__` when using `@cython.cclass`** — the C struct replaces `__slots__`. Having both may conflict.

5. **Typed locals** — use inline annotations: `i: cython.int = 0`. These compile to C variables in Cython but are ignored by Python.

6. **Cython doesn't support `match`/`case` (structural pattern matching).** Rewrite to `if`/`elif` chains.

7. **`wraparound=True`** is required — Django's code uses negative indexing (`self.dicts[-1]`).

### What to annotate

Priority order for Cython optimization:
1. Hot inner-loop classes → `@cython.cclass` with typed attributes
2. Hot methods → `@cython.ccall` (if on cclass) or `@cython.cfunc` (if private)
3. Module-level functions → `@cython.ccall`
4. Loop variables → `i: cython.int`, `flag: cython.bint`

## Project Structure

Follow django-cachex for tooling (CI, pre-commit, ruff, mkdocs, dependabot). The build system differs: setuptools + Cython instead of hatchling.

## Testing

- Tests run against both stock Django and cythonized engines (dual-engine config in `tests/settings.py`)
- `tests/conftest.py` handles `django.setup()` manually (no pytest-django)
- Dev dependencies are pinned with `==` — dependabot handles upgrades
