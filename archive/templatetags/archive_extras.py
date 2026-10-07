"""Custom template filters for the archive app.

Registered with Django's template library so they can be loaded in templates
with ``{% load archive_extras %}``.
"""

from django import template

register = template.Library()


@register.filter
def human_key(value):
    """Replace underscores with spaces and title-case the result."""
    return str(value).replace('_', ' ').title()
