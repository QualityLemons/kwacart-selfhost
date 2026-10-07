"""RTF export generator.

Converts ``payload_output`` from a ``ToolInstance`` or ``ToolSession`` into
a minimal ``.rtf`` file.

Storage strategy
----------------
In production (``CLOUDINARY_URL`` present) the file is uploaded directly via
the Cloudinary Python SDK with an explicit ``public_id`` so the asset path is
fully controlled regardless of the account's folder mode.  The ``secure_url``
returned by Cloudinary is stored on the model field — the download view then
redirects to that URL, avoiding any URL-reconstruction issues.

In local development the file is written to ``MEDIA_ROOT/archives/rtf/`` via
Django's ``default_storage`` (FileSystemStorage).

Canvas drawings
---------------
When a ``ToolInstance`` or session participant's ``payload_output`` contains a
``canvas_data`` key, the PNG is embedded inline using the RTF ``\\pict\\pngblip``
control word sequence.  The PNG bytes are hex-encoded and written directly into
the ``.rtf`` file body — no separate image file is required.  The RTF document
is therefore a single, self-contained file.

Dimensions are read from the PNG IHDR header chunk and converted to twips
(1440 per inch at 96 DPI).  The width is capped at 9 000 twips (~6.25 inches)
so the image fits within standard letter/A4 margins; height scales
proportionally.

RTF encoding notes
------------------
- Backslashes, opening braces, and closing braces must be escaped.
- Newlines in user text are converted to ``\\line``.
- The file is written in UTF-8; the RTF header declares ``\\ansi\\ansicpg1252``.

Filename convention: ``YYYYMMDD_<tool-slug>_<instance-or-session-id>.rtf``
"""
import struct
import urllib.request

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils.text import slugify

from tools.utils import (
    MAX_CANVAS_BYTES,
    decode_canvas_png,
    is_trusted_cloudinary_canvas_url,
    is_valid_canvas_png,
    resolve_local_canvas_path,
)


def _uses_cloudinary_storage():
    """Return True only when this Django environment selected Cloudinary."""
    backend = settings.STORAGES.get('default', {}).get('BACKEND', '')
    return backend.startswith('cloudinary_storage.')


# ── Canvas helpers ─────────────────────────────────────────────────────────

def _load_canvas_bytes(canvas_value):
    """Return the raw PNG bytes for a canvas_data value.

    Accepts either a Cloudinary https:// URL (production) or a local
    /media/drawings/… path (development).  Returns None on any failure.
    """
    if not canvas_value:
        return None

    inline_png = decode_canvas_png(canvas_value)
    if inline_png is not None:
        return inline_png

    if is_trusted_cloudinary_canvas_url(canvas_value):
        try:
            req = urllib.request.Request(
                canvas_value,
                headers={'User-Agent': 'KwaCart-export/1.0'},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                png_bytes = resp.read(MAX_CANVAS_BYTES + 1)
                return png_bytes if is_valid_canvas_png(png_bytes) else None
        except Exception:
            return None

    local_path = resolve_local_canvas_path(canvas_value)
    if local_path is None:
        return None
    try:
        png_bytes = local_path.read_bytes()
        return png_bytes if is_valid_canvas_png(png_bytes) else None
    except OSError:
        return None


def _png_dimensions(png_bytes):
    """Read width and height from a PNG IHDR chunk.

    PNG layout: 8-byte signature + 4-byte chunk length + 4-byte 'IHDR' +
    4-byte width + 4-byte height.  Returns (600, 400) on any parse error.
    """
    try:
        w, h = struct.unpack('>II', png_bytes[16:24])
        return w, h
    except Exception:
        return 600, 400


def _canvas_to_rtf(canvas_value):
    r"""Return an RTF ``\pict\pngblip`` block with the canvas PNG embedded inline.

    The PNG bytes are hex-encoded (128 hex chars per line for readability) and
    written directly into the RTF stream.  No external file reference is used,
    so the resulting ``.rtf`` is fully self-contained.

    Returns an empty string if the PNG bytes cannot be retrieved.
    """
    png_bytes = _load_canvas_bytes(canvas_value)
    if not png_bytes:
        return ''

    w_px, h_px = _png_dimensions(png_bytes)

    # Convert pixels → twips: 1 twip = 1/1440 inch; assume 96 DPI screen.
    # Cap width at 9 000 twips (~6.25 in) to fit letter/A4 margins.
    MAX_W_TW = 9000
    DPI = 96
    TWIPS_PER_INCH = 1440
    w_tw = w_px * TWIPS_PER_INCH // DPI
    h_tw = h_px * TWIPS_PER_INCH // DPI
    if w_tw > MAX_W_TW:
        scale = MAX_W_TW / w_tw
        w_tw = MAX_W_TW
        h_tw = int(h_tw * scale)

    # Hex-encode PNG bytes, 128 hex chars per line for readability.
    raw_hex = png_bytes.hex()
    hex_lines = [raw_hex[i:i + 128] for i in range(0, len(raw_hex), 128)]
    hex_block = '\n'.join(hex_lines)

    return (
        r'{\pict\pngblip'
        + f'\\picwgoal{w_tw}\\pichgoal{h_tw}'
        + r'\picscalex100\picscaley100 '
        + '\n' + hex_block + '\n}'
    )


# ── Text escaping helper ───────────────────────────────────────────────────

def _rtf_escape(value):
    """Escape a string for safe inclusion in an RTF document."""
    return (
        str(value)
        .replace('\\', r'\\')
        .replace('{', r'\{')
        .replace('}', r'\}')
        .replace('\n', r' \line ')
    )


# ── File storage helper ────────────────────────────────────────────────────

def _save_file(relative_path, content_bytes):
    """Upload content to Cloudinary (production) or local storage (development).

    Returns the value to store on the model field:
    - production: the Cloudinary ``secure_url`` (starts with ``https://``)
    - development: the relative filesystem path
    """
    if _uses_cloudinary_storage():
        import cloudinary.uploader
        result = cloudinary.uploader.upload(
            content_bytes,
            resource_type='raw',
            public_id=relative_path,
            overwrite=True,
            use_filename=False,
            unique_filename=False,
        )
        return result['secure_url']
    if default_storage.exists(relative_path):
        default_storage.delete(relative_path)
    return default_storage.save(relative_path, ContentFile(content_bytes))


# ── Export functions ───────────────────────────────────────────────────────

def generate_rtf(instance):
    """Generate an RTF file for a solo ``ToolInstance`` submission."""
    filename = (
        f"{instance.submitted_at.strftime('%Y%m%d')}"
        f"_{slugify(instance.tool_slug)}_{instance.id}.rtf"
    )
    relative_path = f"archives/rtf/{filename}"

    rtf_header = r"{\rtf1\ansi\deff0 {\fonttbl {\f0 Arial;}}\f0\fs24 "
    parts = [rtf_header]
    parts.append(r"\b " + instance.tool_slug.upper() + r"\b0 \line ")
    parts.append(f"Date: {instance.submitted_at.strftime('%Y-%m-%d')} \\line ")
    parts.append(r"\line -------------------------- \line ")

    canvas_value = None
    for key, value in instance.payload_output.items():
        if key == 'canvas_data':
            canvas_value = value
            continue
        label = key.replace('_', ' ').title()
        parts.append(r"\b " + label + r": \b0 \line ")
        parts.append(f"{_rtf_escape(value)} \\line \\line ")

    if canvas_value:
        parts.append(r"\b Drawing: \b0 \line ")
        pict = _canvas_to_rtf(canvas_value)
        if pict:
            parts.append(pict + r' \line \line ')
        elif is_trusted_cloudinary_canvas_url(canvas_value):
            # Fallback: URL as plain text if the image could not be fetched
            parts.append(f"{_rtf_escape(canvas_value)} \\line \\line ")

    parts.append("}")
    return _save_file(relative_path, "".join(parts).encode('utf-8'))


def generate_session_rtf(session):
    """Combine every participant's response into one RTF file."""
    closed_stamp = (session.closed_at or session.created_at).strftime('%Y%m%d')
    filename = f"{closed_stamp}_{slugify(session.tool_slug)}_session_{session.id}.rtf"
    relative_path = f"archives/rtf/{filename}"

    rtf_header = r"{\rtf1\ansi\deff0 {\fonttbl {\f0 Arial;}}\f0\fs24 "
    parts = [rtf_header]

    title = session.tool_slug.upper() + ' - COMBINED SESSION RESULTS'
    parts.append(r"\b " + title + r"\b0 \line ")
    parts.append(f"Hosted by: {_rtf_escape(session.host.email if session.host else 'Unknown')} \\line ")
    if session.closed_at:
        parts.append(f"Closed at: {session.closed_at.strftime('%Y-%m-%d %H:%M')} \\line ")
    parts.append(r"\line ========================== \line ")

    instances = session.instances.select_related('user').order_by('submitted_at', 'created_at')
    for inst in instances:
        marker = ' (host)' if inst.user_id == session.host_id else ''
        display = inst.user.email if inst.user_id else (inst.guest_name or 'Guest')
        parts.append(r"\b " + _rtf_escape(display + marker) + r"\b0 \line ")

        if inst.payload_output:
            canvas_value = None
            for key, value in inst.payload_output.items():
                if key == 'canvas_data':
                    canvas_value = value
                    continue
                label = key.replace('_', ' ').title()
                parts.append(r"\b " + label + r": \b0 \line ")
                parts.append(f"{_rtf_escape(value)} \\line ")

            if canvas_value:
                parts.append(r"\b Drawing: \b0 \line ")
                pict = _canvas_to_rtf(canvas_value)
                if pict:
                    parts.append(pict + r' \line ')
                elif is_trusted_cloudinary_canvas_url(canvas_value):
                    parts.append(f"{_rtf_escape(canvas_value)} \\line ")
        else:
            parts.append(r"\i No response submitted. \i0 \line ")

        parts.append(r"\line -------------------------- \line ")

    parts.append("}")
    return _save_file(relative_path, "".join(parts).encode('utf-8'))
