"""
This module contains generic exceptions used by template backends. Although,
due to historical reasons, the Django template language also internally uses
these exceptions, other exceptions specific to the DTL should not be added
here.

We inherit from Django's stock exceptions so that code catching
``django.template.TemplateDoesNotExist`` also catches ours.
"""

from django.template.exceptions import (
    TemplateDoesNotExist as _DjangoTemplateDoesNotExist,
    TemplateSyntaxError as _DjangoTemplateSyntaxError,
)


class TemplateDoesNotExist(_DjangoTemplateDoesNotExist):
    """
    The exception used when a template does not exist. Optional arguments:

    backend
        The template backend class used when raising this exception.

    tried
        A list of sources that were tried when finding the template. This
        is formatted as a list of tuples containing (origin, status), where
        origin is an Origin object or duck type and status is a string with the
        reason the template wasn't found.

    chain
        A list of intermediate TemplateDoesNotExist exceptions. This is used to
        encapsulate multiple exceptions when loading templates from multiple
        engines.
    """


class TemplateSyntaxError(_DjangoTemplateSyntaxError):
    """
    The exception used for syntax errors during parsing or rendering.
    """
