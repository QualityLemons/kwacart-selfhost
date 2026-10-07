"""Access control for authenticated users without an active paid plan."""
import re
from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


class PaidWorkspaceMiddleware:
    """Keep billing/profile/recovery pages available while tools are locked."""

    PUBLIC_TOOL_RE = re.compile(
        r'^/tools/(?:[^/]+/try/|session/[^/]+/guest/[^/]+(?:/respond/)?$)'
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            settings.BILLING_ENABLED
            and request.user.is_authenticated
            and not request.user.has_paid_access
            and request.path.startswith(('/tools/', '/archive/'))
            and not self.PUBLIC_TOOL_RE.match(request.path)
        ):
            return redirect(f'{reverse("pricing")}?billing=required')
        return self.get_response(request)
