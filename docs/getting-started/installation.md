# Installation

## Requirements

- Python >= 3.12
- Django >= 5.2, < 7
- A C compiler (for Cython compilation)

## Install

```bash
pip install django-templates-cythonized
```

Or with uv:

```bash
uv add django-templates-cythonized
```

## Configuration

Add to your Django settings:

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

## Development Setup

```bash
git clone https://github.com/oliverhaas/django-templates-cythonized.git
cd django-templates-cythonized
uv sync --group dev
uv pip install -e .  # Build Cython extensions
uv run pytest        # Run tests
```
