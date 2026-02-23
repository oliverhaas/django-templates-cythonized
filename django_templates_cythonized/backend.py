from django.forms.renderers import BaseRenderer, EngineMixin
from django.template import TemplateDoesNotExist
from django.template.backends.django import DjangoTemplates

from .context import Context, make_context
from .engine import Engine


class CythonizedTemplates(DjangoTemplates):
    """Drop-in replacement for DjangoTemplates that uses cythonized internals."""

    def __init__(self, params):
        params = params.copy()
        options = params.pop("OPTIONS").copy()
        options.setdefault("autoescape", True)

        from django.conf import settings

        options.setdefault("debug", settings.DEBUG)
        options.setdefault("file_charset", "utf-8")
        libraries = options.get("libraries", {})
        options["libraries"] = self.get_templatetag_libraries(libraries)
        # Call BaseEngine.__init__ (skip DjangoTemplates.__init__)
        from django.template.backends.base import BaseEngine

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
            from django.template.backends.django import reraise
            reraise(exc, self)
        self._template_cache[template_name] = result
        return result


class _Template:
    """Backend template wrapper using our cythonized make_context."""

    __slots__ = ("template", "backend")

    def __init__(self, template, backend):
        self.template = template
        self.backend = backend

    @property
    def origin(self):
        return self.template.origin

    def render(self, context=None, request=None):
        context = make_context(
            context, request, autoescape=self.backend.engine.autoescape
        )
        try:
            return self.template.render(context)
        except TemplateDoesNotExist as exc:
            from django.template.backends.django import reraise
            reraise(exc, self.backend)


class CythonizedFormRenderer(EngineMixin, BaseRenderer):
    """Form renderer that uses our cythonized template engine for widgets.

    Bypasses per-widget make_context + Context creation overhead by reusing
    one Context and pushing/popping the widget dict. Template caching is
    handled by Engine.get_template() and CythonizedTemplates.get_template().
    """

    backend = CythonizedTemplates
    _ctx = None

    def render(self, template_name, context, request=None):
        tpl = self.get_template(template_name).template

        ctx = self._ctx
        if ctx is None:
            ctx = Context(autoescape=True)
            self._ctx = ctx

        ctx.dicts.append(context)
        try:
            return tpl.render(ctx).strip()
        finally:
            ctx.dicts.pop()
