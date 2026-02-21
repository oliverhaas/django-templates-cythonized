from django.template.backends.django import DjangoTemplates

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
