"""Safe template integration for contextual feedback tokens."""
from django import template

from archive.feedback_context import (
    PROMPT_SUPPRESSION_COOKIE,
    create_feedback_context,
)


register = template.Library()


@register.simple_tag
def feedback_context_token(source, tool_slug=None, interaction_mode=None):
    """Sign server-rendered context, returning no token for invalid constants."""
    tool_slug = tool_slug or None
    interaction_mode = interaction_mode or None
    try:
        return create_feedback_context(source, tool_slug, interaction_mode)
    except (TypeError, ValueError):
        return ''


@register.simple_tag(takes_context=True)
def feedback_prompts_suppressed(context):
    """Whether this browser has recently dismissed or answered a prompt."""
    request = context.get('request')
    return bool(
        request
        and request.COOKIES.get(PROMPT_SUPPRESSION_COOKIE) == '1'
    )