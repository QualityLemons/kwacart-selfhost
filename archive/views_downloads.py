"""Secure file-download views for the archive application.

Every endpoint checks that the requesting user owns the record being
downloaded.  Non-owners receive a 404 rather than a 403 to avoid
confirming that a record with a given ID exists.

``VALID_FILE_TYPES`` is a whitelist that prevents arbitrary attribute access
on model instances via crafted URL parameters.

File delivery strategy
----------------------
In production the model field stores a Cloudinary ``secure_url`` (starts with
``https://``).  The view redirects the authenticated user directly to that URL
so the file is served by Cloudinary's CDN without proxying through the dyno.

In local development the field stores a relative filesystem path.  The view
opens the file via ``default_storage`` and streams it with ``FileResponse``.
"""
import os

from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404

from accounts.utils import log_action
from accounts.organisation_data_ownership import session_access_q, solo_record_access_q
from config.rate_limit import is_layered_rate_limited

from .models import ToolInstance, ToolSession


# Whitelist of supported file extensions.  Checked before calling
# getattr(instance, f'{file_type}_file') to prevent arbitrary attribute
# access on the model via a crafted URL parameter.
VALID_FILE_TYPES = {'md', 'rtf', 'html'}


def _download_limited(request, resource_id):
    return is_layered_rate_limited(
        request, 'export-download', ip_limit=120, user_limit=60,
        session_limit=120, session_id=resource_id,
        window_seconds=300, lockout_seconds=300,
    )


def _download_throttled():
    response = HttpResponse(
        'Too many download requests. Please try again later.', status=429,
    )
    response['Retry-After'] = '300'
    return response


def _serve_file(file_field):
    """Deliver a stored file to the browser.

    If the stored value is a full URL (Cloudinary secure_url in production),
    redirect to it.  Otherwise open the path via default_storage and stream
    it as an attachment (local development).

    If the stored value is a bare path but the Cloudinary backend is active,
    the file cannot be served (it was saved before Cloudinary was configured).
    A 404 is raised rather than letting the storage backend throw an
    unhandled exception.
    """
    value = str(file_field.name) if hasattr(file_field, 'name') else str(file_field)
    if value.startswith('https://') or value.startswith('http://'):
        return HttpResponseRedirect(value)
    # Bare path — try local storage, but give a clean 404 if unavailable.
    try:
        fh = default_storage.open(value, 'rb')
    except Exception:
        raise Http404('Export file is not available. Please regenerate the export from the archive.')
    filename = os.path.basename(value)
    return FileResponse(fh, as_attachment=True, filename=filename)


@login_required
def secure_download(request, instance_id, file_type):
    """Serve a file associated with a ToolInstance.

    Enforces that the requesting user owns the instance before the file is
    served; non-owners receive a 404 rather than a 403 to avoid leaking
    whether the instance exists.
    """
    if file_type not in VALID_FILE_TYPES:
        raise Http404('Unknown file type.')

    instance = get_object_or_404(
        ToolInstance.objects.filter(session__isnull=True).filter(
            solo_record_access_q(request.user)
        ),
        id=instance_id,
    )
    file_field = getattr(instance, f'{file_type}_file', None)
    if not file_field:
        raise Http404('File is not available.')
    if _download_limited(request, f'instance:{instance_id}'):
        return _download_throttled()

    log_action(
        user=request.user,
        action='download',
        resource_id=instance_id,
        metadata={'file_type': file_type},
    )
    return _serve_file(file_field)


@login_required
def secure_session_download(request, session_id, file_type):
    """Combined session export download. Allowed for host or participants.

    The Q() filter ensures that only the session host or any user who has a
    ToolInstance in the session (i.e. any participant) can download the
    combined export file.  Non-participants receive a 404.
    """
    if file_type not in VALID_FILE_TYPES:
        raise Http404('Unknown file type.')

    session = get_object_or_404(
        ToolSession.objects.filter(
            # Host OR any participant (anyone with a ToolInstance in the session).
            session_access_q(request.user) | Q(instances__user=request.user)
        ).distinct(),
        id=session_id,
    )

    file_field = getattr(session, f'{file_type}_file', None)
    if not file_field:
        raise Http404('File is not available.')
    if _download_limited(request, f'session:{session_id}'):
        return _download_throttled()

    log_action(
        user=request.user,
        action='download',
        resource_id=str(session_id),
        metadata={'file_type': file_type, 'session': True},
    )
    return _serve_file(file_field)
