"""Safe, best-effort deletion of storage assets owned by KwaCart."""
from contextlib import contextmanager
import hashlib
import logging
from pathlib import PurePosixPath
import threading
from urllib.parse import unquote, urlsplit

from django.apps import apps
from django.core.files.storage import default_storage
from django.db import connection

logger = logging.getLogger(__name__)
_local_asset_locks = {}
_local_asset_locks_guard = threading.Lock()

OWNED_CLOUDINARY_PREFIXES = {
    'canvas': ('drawings/',),
    'attachment': ('kwacart/attachments/',),
    'export': ('archives/html/', 'archives/md/', 'archives/rtf/'),
}


@contextmanager
def cloudinary_asset_lock(resource_type, public_id):
    """Serialize replacement and deletion of one provider asset identity."""
    identity = f'{resource_type}:{public_id}'
    if connection.vendor == 'postgresql':
        lock_id = int.from_bytes(
            hashlib.sha256(identity.encode()).digest()[:8],
            byteorder='big',
            signed=True,
        )
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_lock(%s)', [lock_id])
        try:
            yield
        finally:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_unlock(%s)', [lock_id])
        return

    with _local_asset_locks_guard:
        lock = _local_asset_locks.setdefault(identity, threading.RLock())
    with lock:
        yield


def _safe_public_id(public_id, kind, expected_prefix=None):
    if not isinstance(public_id, str):
        return None
    public_id = unquote(public_id).strip().strip('/')
    if (
        not public_id
        or '\\' in public_id
        or any(part in ('', '.', '..') for part in public_id.split('/'))
    ):
        return None
    prefixes = OWNED_CLOUDINARY_PREFIXES.get(kind, ())
    if not any(public_id.startswith(prefix) for prefix in prefixes):
        return None
    if expected_prefix and not public_id.startswith(expected_prefix):
        return None
    return public_id


def cloudinary_key_from_url(value):
    """Return the canonical ``(resource_type, public_id)`` for a delivery URL.

    Canvas uploads made now use an extension-free public ID plus ``format=png``.
    Cloudinary therefore delivers ``drawing.png`` for the ID ``drawing``.  Old
    uploads supplied ``drawing.png`` as their public ID; Cloudinary can deliver
    those as ``drawing.png.png``.  Removing exactly one delivery extension
    handles both forms and deliberately preserves the legacy explicit ``.png``.
    """
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError):
        return None
    marker = '/upload/'
    if (
        parsed.scheme != 'https'
        or parsed.hostname != 'res.cloudinary.com'
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or marker not in parsed.path
    ):
        return None
    before, tail = parsed.path.split(marker, 1)
    resource_type = before.rstrip('/').rsplit('/', 1)[-1]
    if resource_type not in ('image', 'video', 'raw'):
        return None
    tail = unquote(tail).lstrip('/')
    parts = tail.split('/')
    version_index = next(
        (
            index for index, part in enumerate(parts)
            if part.startswith('v') and part[1:].isdigit()
        ),
        None,
    )
    if version_index is not None:
        # Transformations may precede the version.  The first version marker
        # is Cloudinary's unambiguous boundary before the public ID.
        parts = parts[version_index + 1:]
    elif not parts or parts[0] not in ('drawings', 'archives', 'kwacart'):
        # A versionless URL is only safe when the path begins directly with an
        # owned top-level folder. Otherwise it might contain transformations,
        # whose boundary cannot be identified safely.
        return None
    public_id = '/'.join(parts)
    if resource_type == 'image' and public_id.lower().endswith('.png'):
        public_id = public_id[:-4]
    return resource_type, public_id


def _cloudinary_public_id(value, resource_type):
    key = cloudinary_key_from_url(value)
    return key[1] if key and key[0] == resource_type else None


def delete_cloudinary_asset(public_id, resource_type, kind, expected_prefix=None):
    """Idempotently delete one explicitly owned Cloudinary asset."""
    public_id = _safe_public_id(public_id, kind, expected_prefix)
    if not public_id or resource_type not in ('image', 'video', 'raw'):
        return False
    try:
        import cloudinary.uploader
        cloudinary.uploader.destroy(
            public_id,
            resource_type=resource_type,
            invalidate=True,
        )
        return True
    except Exception:
        logger.exception('Could not delete owned %s asset %s', kind, public_id)
        return False


def delete_attachment_asset(attachment, session_id):
    if not isinstance(attachment, dict) or session_id is None:
        return False
    public_id = attachment.get('public_id')
    expected = f'kwacart/attachments/{session_id}/'
    storage_name = attachment.get('storage_name')
    if storage_name:
        path = PurePosixPath(storage_name)
        if (
            not storage_name.startswith(expected)
            or path.is_absolute()
            or '..' in path.parts
            or storage_name != public_id
        ):
            return False
        try:
            default_storage.delete(storage_name)
            return True
        except Exception:
            logger.exception('Could not delete owned local attachment')
            return False
    attachment_type = attachment.get('type')
    if attachment_type == 'image':
        resource_type = 'image'
    elif attachment_type in ('audio', 'video'):
        resource_type = 'video'
    else:
        return False
    return delete_cloudinary_asset(
        public_id, resource_type, 'attachment', expected_prefix=expected,
    )


def _local_export_name(value):
    if not isinstance(value, str) or not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        return None
    name = unquote(parsed.path).lstrip('/')
    path = PurePosixPath(name)
    if '..' in path.parts:
        return None
    if not any(name.startswith(prefix) for prefix in OWNED_CLOUDINARY_PREFIXES['export']):
        return None
    return name


def delete_export_asset(value):
    """Delete a raw Cloudinary export or a local FileField export."""
    if not value:
        return False
    public_id = _cloudinary_public_id(value, 'raw')
    if public_id:
        return delete_cloudinary_asset(public_id, 'raw', 'export')
    name = _local_export_name(value)
    if not name:
        return False
    try:
        default_storage.delete(name)
        return True
    except Exception:
        logger.exception('Could not delete owned local export %s', name)
        return False


def export_asset_identity(value):
    public_id = _cloudinary_public_id(value, 'raw')
    public_id = _safe_public_id(public_id, 'export')
    if public_id:
        return ('cloudinary', 'raw', public_id)
    name = _local_export_name(value)
    return ('local', name) if name else None


def delete_canvas_asset(value):
    """Delete an owned canvas, rejecting arbitrary URLs and local paths."""
    from tools.utils import resolve_local_canvas_path

    public_id = _cloudinary_public_id(value, 'image')
    if public_id:
        return delete_cloudinary_asset(public_id, 'image', 'canvas')
    path = resolve_local_canvas_path(value)
    if path is None:
        return False
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError:
        logger.exception('Could not delete owned local canvas %s', path)
        return False


def canvas_asset_identity(value):
    from tools.utils import resolve_local_canvas_path

    public_id = _cloudinary_public_id(value, 'image')
    public_id = _safe_public_id(public_id, 'canvas')
    if public_id:
        return ('cloudinary', 'image', public_id)
    path = resolve_local_canvas_path(value)
    return ('local', str(path)) if path is not None else None


def canvas_references(instance):
    """Return every canvas reference, including canvases nested in JSON data."""
    refs = set()
    for payload in (instance.payload_input, instance.payload_output):
        refs.update(
            value for value in _walk_canvas_values(payload)
            if isinstance(value, str) and value
        )
    return refs


def _walk_canvas_values(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == 'canvas_data':
                yield child
            else:
                yield from _walk_canvas_values(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk_canvas_values(child)


def attachment_references(instance):
    refs = set()
    for item in instance.attachments or []:
        if isinstance(item, dict) and item.get('public_id'):
            refs.add((item.get('type'), item['public_id']))
    return refs


def cleanup_canvas_if_unreferenced(value):
    identity = canvas_asset_identity(value)
    if identity is None:
        return False
    ToolInstance = apps.get_model('archive', 'ToolInstance')
    for instance in ToolInstance.objects.only('payload_input', 'payload_output').iterator():
        if any(canvas_asset_identity(item) == identity for item in canvas_references(instance)):
            return False
    return delete_canvas_asset(value)


def cleanup_attachment_if_unreferenced(attachment, session_id):
    key = (attachment.get('type'), attachment.get('public_id'))
    ToolInstance = apps.get_model('archive', 'ToolInstance')
    for instance in ToolInstance.objects.only('attachments').iterator():
        if key in attachment_references(instance):
            return False
    return delete_attachment_asset(attachment, session_id)


def cleanup_export_if_unreferenced(value):
    identity = export_asset_identity(value)
    if identity is None:
        return False
    ToolInstance = apps.get_model('archive', 'ToolInstance')
    ToolSession = apps.get_model('archive', 'ToolSession')
    fields = ('html_file', 'md_file', 'rtf_file')
    for model, model_fields in (
        (ToolInstance, fields),
        (ToolSession, ('md_file', 'rtf_file')),
    ):
        for values in model.objects.values_list(*model_fields).iterator():
            if any(export_asset_identity(str(item or '')) == identity for item in values):
                return False
    return delete_export_asset(value)