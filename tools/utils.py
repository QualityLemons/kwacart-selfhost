"""Utility helpers shared across the tools application.

Contains:
- ``save_canvas_to_file`` — persists a base64 data-URL PNG to ``media/drawings/``
  (development) or Cloudinary (production) and returns the URL/path, deduplicating
  by content hash.
- ``extract_canvas_from_payload`` — replaces the ``canvas_data`` key in a form
  payload dict with a saved file path/URL before the payload is stored in the DB.
- ``_normalize_meta`` / ``get_tool_metadata`` — ensure every tool metadata dict
  has a predictable set of keys so templates never encounter missing variables.
- ``get_all_tools_by_category`` — groups the catalog for the catalog page view.
"""
import base64
import hashlib
import os
import struct
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import unquote, urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError

from archive.assets import cloudinary_asset_lock
from .registry import TOOL_CATALOG


CANVAS_DATA_PREFIX = 'data:image/png;base64,'
MAX_CANVAS_BYTES = 5 * 1024 * 1024
MAX_CANVAS_DIMENSION = 4096


def _uses_cloudinary_storage():
    """Return True only when this Django environment selected Cloudinary."""
    backend = settings.STORAGES.get('default', {}).get('BACKEND', '')
    return backend.startswith('cloudinary_storage.')


def is_valid_canvas_png(png_bytes):
    """Return whether bytes are a reasonably sized, structurally valid PNG."""
    if not png_bytes or len(png_bytes) > MAX_CANVAS_BYTES:
        return False
    if png_bytes[:8] != b'\x89PNG\r\n\x1a\n' or png_bytes[12:16] != b'IHDR':
        return False
    try:
        width, height = struct.unpack('>II', png_bytes[16:24])
    except (struct.error, TypeError):
        return False
    return (
        0 < width <= MAX_CANVAS_DIMENSION
        and 0 < height <= MAX_CANVAS_DIMENSION
    )


def decode_canvas_png(canvas_data):
    """Decode an approved PNG data URL, returning None when it is invalid."""
    if not isinstance(canvas_data, str) or not canvas_data.startswith(CANVAS_DATA_PREFIX):
        return None
    encoded = canvas_data[len(CANVAS_DATA_PREFIX):]
    if len(encoded) > ((MAX_CANVAS_BYTES * 4 // 3) + 8):
        return None
    try:
        png_bytes = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        return None
    return png_bytes if is_valid_canvas_png(png_bytes) else None


def is_trusted_cloudinary_canvas_url(canvas_value):
    """Allow only Cloudinary's HTTPS image-delivery URLs for saved canvases."""
    try:
        parsed = urlsplit(canvas_value)
        port = parsed.port
    except (TypeError, ValueError):
        return False
    return (
        parsed.scheme == 'https'
        and parsed.hostname == 'res.cloudinary.com'
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
        and '/image/upload/' in parsed.path
        and parsed.path.lower().endswith('.png')
        and not parsed.fragment
    )


def resolve_local_canvas_path(canvas_value):
    """Resolve an approved /media/drawings/*.png value inside MEDIA_ROOT."""
    if not isinstance(canvas_value, str):
        return None
    parsed = urlsplit(canvas_value)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        return None
    path = unquote(parsed.path)
    prefix = f"{settings.MEDIA_URL.rstrip('/')}/drawings/"
    if not path.startswith(prefix) or not path.lower().endswith('.png'):
        return None
    drawings_root = (Path(settings.MEDIA_ROOT) / 'drawings').resolve()
    candidate = (Path(settings.MEDIA_ROOT) / path[len(settings.MEDIA_URL):].lstrip('/')).resolve()
    if candidate != drawings_root and drawings_root not in candidate.parents:
        return None
    return candidate


def is_trusted_saved_canvas_reference(canvas_value):
    return bool(
        resolve_local_canvas_path(canvas_value)
        or is_trusted_cloudinary_canvas_url(canvas_value)
    )


def validate_canvas_data(canvas_value):
    """Django field validator for canvas PNGs and saved canvas references."""
    if not canvas_value:
        return
    if decode_canvas_png(canvas_value) is not None:
        return
    if is_trusted_saved_canvas_reference(canvas_value):
        return
    raise ValidationError('The drawing data is not a valid KwaCart canvas PNG.')


def save_canvas_to_file(canvas_data, tool_slug, user_id):
    """
    Accept a data-URL PNG from the drawing canvas and persist it.

    In production (CLOUDINARY_URL present) the PNG is uploaded to Cloudinary
    as an image resource and the secure_url is returned — this survives Heroku
    dyno restarts and is immediately usable in exports.

    In development the PNG is written to media/drawings/ on the local
    filesystem and a media-relative URL is returned
    (e.g. '/media/drawings/drawing-together_7_abc123.png').

    If canvas_data is already a path/URL (not a data-URL), return it unchanged.
    If canvas_data is empty, return an empty string.
    """
    if not canvas_data:
        return ''
    if not canvas_data.startswith(CANVAS_DATA_PREFIX):
        return canvas_data if is_trusted_saved_canvas_reference(canvas_data) else ''

    png_bytes = decode_canvas_png(canvas_data)
    if png_bytes is None:
        return ''

    # SHA-256 of the raw PNG bytes produces a short, collision-resistant
    # filename — duplicate images for the same canvas content are naturally
    # deduplicated because they hash to the same filename.
    content_hash = hashlib.sha256(png_bytes).hexdigest()[:12]
    filename = f'{tool_slug}_{user_id}_{content_hash}.png'

    if _uses_cloudinary_storage():
        # Production: upload directly to Cloudinary as a persistent image asset.
        # resource_type='image' (not 'raw') so Cloudinary serves it with the
        # correct Content-Type and the URL works in <img> tags and exports.
        import cloudinary.uploader
        result = cloudinary.uploader.upload(
            png_bytes,
            resource_type='image',
            # Image delivery adds the PNG suffix. Keeping it out of the
            # public ID avoids ambiguous legacy ``.png.png`` URLs.
            public_id=f'drawings/{Path(filename).stem}',
            format='png',
            overwrite=True,
            use_filename=False,
            unique_filename=False,
        )
        return result['secure_url']

    # Development: write to local filesystem.
    drawings_dir = os.path.join(settings.MEDIA_ROOT, 'drawings')
    os.makedirs(drawings_dir, exist_ok=True)
    filepath = os.path.join(drawings_dir, filename)
    with open(filepath, 'wb') as fh:
        fh.write(png_bytes)
    return settings.MEDIA_URL + 'drawings/' + filename


@contextmanager
def canvas_write_lock(payload, tool_slug, user_id):
    """Hold the drawing identity lock from provider upload through DB commit."""
    canvas_data = payload.get('canvas_data', '') if isinstance(payload, dict) else ''
    png_bytes = (
        decode_canvas_png(canvas_data)
        if isinstance(canvas_data, str) and canvas_data.startswith(CANVAS_DATA_PREFIX)
        else None
    )
    if png_bytes is None or not _uses_cloudinary_storage():
        yield
        return
    content_hash = hashlib.sha256(png_bytes).hexdigest()[:12]
    public_id = f'drawings/{tool_slug}_{user_id}_{content_hash}'
    with cloudinary_asset_lock('image', public_id):
        yield


def extract_canvas_from_payload(payload, tool_slug, user_id, existing_canvas=''):
    """
    If payload contains a 'canvas_data' data-URL, save it to a file
    and return a copy of payload with 'canvas_data' replaced by the
    media path/URL. Returns payload unchanged if no conversion is needed.
    """
    if not payload or 'canvas_data' not in payload:
        return payload
    canvas_data = payload.get('canvas_data', '')
    if not canvas_data:
        return payload
    if not canvas_data.startswith(CANVAS_DATA_PREFIX):
        if canvas_data == existing_canvas and is_trusted_saved_canvas_reference(canvas_data):
            return payload
        raise ValidationError('The drawing reference is not valid for this response.')
    # A shallow copy is made so the original cleaned_data dict passed in by
    # the view is not mutated.
    result = dict(payload)
    result['canvas_data'] = save_canvas_to_file(canvas_data, tool_slug, user_id)
    if not result['canvas_data']:
        raise ValidationError('The drawing could not be validated as a PNG.')
    return result


def _normalize_meta(slug, meta):
    """Return a copy of meta with guaranteed keys so templates never see missing vars."""
    if meta is None:
        return None
    m = dict(meta)
    m['slug'] = slug
    # Some older templates reference 'how_to' and newer ones reference 'how'.
    # Both keys are populated from whichever is present so either works.
    m.setdefault('how', m.get('how_to', ''))
    m.setdefault('how_to', m.get('how', ''))
    m.setdefault('what', '')
    m.setdefault('why', '')
    m.setdefault('tagline', '')
    m.setdefault('show_canvas', False)
    m.setdefault('canvas_label', '')
    m.setdefault('canvas_instruction', '')
    m.setdefault('canvas_hint', '')
    m.setdefault('phases', None)
    return m


def get_tool_metadata(slug):
    """Fetches full metadata for a tool, including how-to and examples."""
    return _normalize_meta(slug, TOOL_CATALOG.get(slug))


def get_all_tools_by_category():
    """Groups tools for the Catalog view."""
    grouped = {}
    for slug, meta in TOOL_CATALOG.items():
        cat = meta.get('category', 'General')
        if cat not in grouped:
            grouped[cat] = []
        # Mutates the registry entry in place to add the slug key.  This is
        # intentional and idempotent — the catalog view calls this function
        # once per request and slug is always the same value for a given entry.
        meta['slug'] = slug
        grouped[cat].append(meta)
    return grouped
