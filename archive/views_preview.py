"""Inline Markdown preview endpoint for the Archive Dashboard.

Returns the raw Markdown text of a stored export file as a JSON response.
The browser renders it with marked.js inside a modal — no file download or
page navigation required.

Authorization mirrors ``views_downloads.py``:
  - Instance preview: requesting user must own the ``ToolInstance``.
  - Session preview:  requesting user must be the host or a participant.

File-reading strategy:
  - Production (Cloudinary): the stored value is a ``https://`` URL.
    The view fetches the raw content via ``urllib.request`` on the dyno.
  - Development: the stored value is a relative filesystem path opened via
    ``default_storage``.
"""
import urllib.request as _urllib_req
from urllib.error import URLError

from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from accounts.organisation_data_ownership import session_access_q, solo_record_access_q

from .models import ToolInstance, ToolSession

_FETCH_TIMEOUT = 10   # seconds; prevents hanging the dyno on slow CDN responses
_MAX_MD_BYTES  = 2 * 1024 * 1024   # 2 MB safety cap


def _read_md_content(file_field):
    """Return the UTF-8 text of a stored Markdown file.

    Raises ``Http404`` if the field is empty, the file is missing, or the
    remote request times out.
    """
    if not file_field:
        raise Http404('No Markdown export for this record.')

    value = str(file_field.name) if hasattr(file_field, 'name') else str(file_field)
    if not value:
        raise Http404('No Markdown export for this record.')

    if value.startswith('https://') or value.startswith('http://'):
        try:
            with _urllib_req.urlopen(value, timeout=_FETCH_TIMEOUT) as resp:
                raw = resp.read(_MAX_MD_BYTES)
        except URLError:
            raise Http404('Could not fetch the export file. Please try again.')
        return raw.decode('utf-8', errors='replace')

    # Local development path via default_storage
    try:
        with default_storage.open(value, 'rb') as fh:
            return fh.read(_MAX_MD_BYTES).decode('utf-8', errors='replace')
    except Exception:
        raise Http404('Export file is not available on local storage.')


@require_GET
@login_required
def md_preview(request, instance_id):
    """Return the Markdown content of a solo ToolInstance export as JSON.

    Response shape: ``{ "markdown": "<raw markdown text>" }``
    """
    instance = get_object_or_404(
        ToolInstance.objects.filter(session__isnull=True).filter(
            solo_record_access_q(request.user)
        ),
        id=instance_id,
    )
    content = _read_md_content(getattr(instance, 'md_file', None))
    return JsonResponse({'markdown': content})


@require_GET
@login_required
def session_md_preview(request, session_id):
    """Return the combined Markdown export for a session as JSON.

    Accessible to the session host and any participant (same rule as the
    download endpoint).

    Response shape: ``{ "markdown": "<raw markdown text>" }``
    """
    session = get_object_or_404(
        ToolSession.objects.filter(
            session_access_q(request.user) | Q(instances__user=request.user)
        ).distinct(),
        id=session_id,
    )
    content = _read_md_content(getattr(session, 'md_file', None))
    return JsonResponse({'markdown': content})
