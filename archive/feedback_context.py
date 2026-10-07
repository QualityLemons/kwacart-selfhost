"""Signed, allowlisted context for feedback submitted from tool screens."""
from django.core import signing

from tools.registry import TOOL_CATALOG

from .models import FeatureRequest


CONTEXT_SALT = 'archive.feedback-context.v1'
CONTEXT_MAX_AGE_SECONDS = 24 * 60 * 60
ALLOWED_INTERACTION_MODES = {
    value for value, _label in FeatureRequest.INTERACTION_MODES
}
CONTEXT_SOURCES = {'tool_completion', 'session_end', 'knowledge_bank'}
TOOL_REQUIRED_SOURCES = {'tool_completion', 'session_end'}
CONTEXT_KEYS = {'source', 'tool_slug', 'interaction_mode'}
PROMPT_SUPPRESSION_COOKIE = 'kwacart_feedback_prompts_suppressed'
PROMPT_SUPPRESSION_SECONDS = 30 * 24 * 60 * 60


def _validate_context(source, tool_slug, interaction_mode):
    if source not in CONTEXT_SOURCES:
        raise ValueError('Unknown contextual feedback source.')
    if source in TOOL_REQUIRED_SOURCES and not tool_slug:
        raise ValueError('This feedback source requires a tool.')
    if tool_slug is not None and tool_slug not in TOOL_CATALOG:
        raise ValueError('Unknown tool.')
    if (
        interaction_mode is not None
        and interaction_mode not in ALLOWED_INTERACTION_MODES
    ):
        raise ValueError('Unknown interaction mode.')


def create_feedback_context(source, tool_slug=None, interaction_mode=None):
    """Create a short-lived token; only trusted server code should call this."""
    _validate_context(source, tool_slug, interaction_mode)
    return signing.dumps(
        {
            'source': source,
            'tool_slug': tool_slug,
            'interaction_mode': interaction_mode,
        },
        salt=CONTEXT_SALT,
        compress=True,
    )


def read_feedback_context(token):
    """Verify and return an allowlisted context, raising BadSignature if unsafe."""
    context = signing.loads(
        token, salt=CONTEXT_SALT, max_age=CONTEXT_MAX_AGE_SECONDS,
    )
    if not isinstance(context, dict) or set(context) != CONTEXT_KEYS:
        raise signing.BadSignature('Invalid feedback context.')
    try:
        _validate_context(
            context['source'],
            context['tool_slug'],
            context['interaction_mode'],
        )
    except ValueError as exc:
        raise signing.BadSignature('Invalid feedback context.') from exc
    return context


# Descriptive aliases for integrations which prefer explicit token terminology.
make_feedback_context_token = create_feedback_context
parse_feedback_context_token = read_feedback_context