import threading
from pathlib import Path

import django.forms
from django.conf import settings
from django.forms.renderers import BaseRenderer, EngineMixin
from django.template import TemplateDoesNotExist
from django.template.backends.base import BaseEngine
from django.template.backends.django import DjangoTemplates, reraise

from .context import Context, make_context
from .engine import Engine
from .forms import is_fast_widget_template, render_widget_fast

_form_ctx_local = threading.local()

# Absolute path to Django's stock forms template directory.
# Used to verify that a widget template hasn't been overridden by a project.
_STOCK_FORMS_TPL_DIR = str(Path(django.forms.__file__).parent / "templates")

# Cache: template_name -> True (fast path ok) / False (not in set or overridden).
# Populated lazily on first encounter of each template_name.
_fast_path_ok: dict = {}


class CythonizedTemplates(DjangoTemplates):
    """Drop-in replacement for DjangoTemplates that uses cythonized internals."""

    def __init__(self, params):
        params = params.copy()
        options = params.pop("OPTIONS").copy()
        options.setdefault("autoescape", True)
        options.setdefault("debug", settings.DEBUG)
        options.setdefault("file_charset", "utf-8")
        libraries = options.get("libraries", {})
        options["libraries"] = self.get_templatetag_libraries(libraries)
        # Call BaseEngine.__init__ (skip DjangoTemplates.__init__)
        BaseEngine.__init__(self, params)
        # Use OUR Engine instead of django.template.engine.Engine
        self.engine = Engine(self.dirs, self.app_dirs, **options)
        self._template_cache = {}

    def from_string(self, template_code):
        return _Template(self.engine.from_string(template_code), self)

    def get_template(self, template_name):
        cached = self._template_cache.get(template_name)
        if cached is not None:
            return cached
        try:
            result = _Template(self.engine.get_template(template_name), self)
        except TemplateDoesNotExist as exc:
            reraise(exc, self)
        self._template_cache[template_name] = result
        return result


class _Template:
    """Backend template wrapper using our cythonized make_context."""

    __slots__ = ("backend", "template")

    def __init__(self, template, backend):
        self.template = template
        self.backend = backend

    @property
    def origin(self):
        return self.template.origin

    def render(self, context=None, request=None):
        context = make_context(context, request, autoescape=self.backend.engine.autoescape)
        try:
            return self.template.render(context)
        except TemplateDoesNotExist as exc:
            reraise(exc, self.backend)


class CythonizedFormRenderer(EngineMixin, BaseRenderer):
    """Form renderer that uses our cythonized template engine for widgets.

    Bypasses per-widget make_context + Context creation overhead by reusing
    one Context per thread and pushing/popping the widget dict. Template
    caching is handled by Engine.get_template() and
    CythonizedTemplates.get_template().
    """

    backend = CythonizedTemplates

    def _verify_fast_path(self, template_name):
        """Check if template_name is in the fast set AND resolves to stock Django."""
        if not is_fast_widget_template(template_name):
            return False
        try:
            tpl = self.get_template(template_name)
            return str(tpl.template.origin.name).startswith(_STOCK_FORMS_TPL_DIR)
        except Exception:
            return False

    def render(self, template_name, context, request=None):
        # Fast path: direct HTML generation for known stock widget templates.
        # Skipped if a project has overridden the template (different origin).
        ok = _fast_path_ok.get(template_name)
        if ok is None:
            ok = self._verify_fast_path(template_name)
            _fast_path_ok[template_name] = ok
        if ok:
            result = render_widget_fast(template_name, context)
            if result is not None:
                return result

        # Fallback: template-based rendering for unknown/overridden templates.
        tpl = self.get_template(template_name).template

        ctx = getattr(_form_ctx_local, "ctx", None)
        if ctx is None:
            ctx = Context(autoescape=True)
            _form_ctx_local.ctx = ctx

        # Reset cached language so locale changes between requests are respected.
        ctx._lang = None
        ctx.dicts.append(context)
        try:
            return tpl.render(ctx).strip()
        finally:
            ctx.dicts.pop()
