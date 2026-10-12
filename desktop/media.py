"""Serve registered attachments, never arbitrary files from MEDIA_ROOT."""
from uuid import UUID

from django.core.files.storage import default_storage
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from accounts.organisation_data_ownership import session_access_q
from archive.models import ToolInstance, ToolSession


def unavailable_media(request):
    raise Http404


@never_cache
@require_safe
def session_attachment(request, storage_path, session_id):
    try:
        session_id = UUID(session_id)
    except ValueError:
        raise Http404
    if request.user.is_authenticated:
        # Same workshop read authority as archive's combined download endpoint.
        session = get_object_or_404(
            ToolSession.objects.filter(
                session_access_q(request.user) | Q(instances__user=request.user)
            ).distinct(),
            pk=session_id,
        )
        instances = session.instances.all()
    else:
        # A guest may read only attachments bound to their own signed session.
        guest_id = request.session.get(f'guest_instance_{session_id}')
        if not guest_id:
            raise Http404
        instances = ToolInstance.objects.filter(
            pk=guest_id, session_id=session_id, user__isnull=True,
        )
    registered = any(
        isinstance(entry, dict)
        and entry.get('storage_name') == storage_path
        and entry.get('public_id') == storage_path
        for instance in instances
        for entry in (instance.attachments or [])
    )
    if not registered:
        raise Http404
    try:
        handle = default_storage.open(storage_path, 'rb')
    except (OSError, ValueError):
        raise Http404
    response = FileResponse(handle)
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "sandbox; default-src 'none'"
    return response
