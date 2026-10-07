"""Markdown export generator.

Converts ``payload_output`` from a ``ToolInstance`` or ``ToolSession`` into
a ``.md`` file.

Storage strategy
----------------
In production (``CLOUDINARY_URL`` present) the file is uploaded directly via
the Cloudinary Python SDK with an explicit ``public_id`` so the asset path is
fully controlled regardless of the account's folder mode.  The ``secure_url``
returned by Cloudinary is stored on the model field — the download view then
redirects to that URL, avoiding any URL-reconstruction issues.

In local development the file is written to ``MEDIA_ROOT/archives/md/`` via
Django's ``default_storage`` (FileSystemStorage).

Canvas drawings
---------------
When a ``ToolInstance`` or session participant's ``payload_output`` contains a
``canvas_data`` key (set by tools such as Drawing Together), the drawing is
embedded directly in the Markdown file as a Base64 data URI::

    ![Drawing Together canvas](data:image/png;base64,<encoded-bytes>)

This keeps the ``.md`` file completely self-contained — no separate image file
is needed and the drawing renders correctly in any Markdown viewer regardless
of where the file is opened.  If the PNG bytes cannot be retrieved (e.g. a
Cloudinary URL that is temporarily unavailable), the Cloudinary URL is used as
a plain link fallback.

Filename convention: ``YYYYMMDD_<tool-slug>_<instance-or-session-id>.md``
"""
import base64
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


def _canvas_to_md(canvas_value):
    """Return a Markdown image tag for a canvas drawing.

    Preference order:
    1. Base64 data URI — completely self-contained, works everywhere.
    2. Direct Cloudinary URL — used as fallback if the PNG fetch fails.
    3. Empty string — if the value is missing or unreadable.
    """
    if not canvas_value:
        return ''

    png_bytes = _load_canvas_bytes(canvas_value)
    if png_bytes:
        encoded = base64.b64encode(png_bytes).decode('ascii')
        return f'\n![Drawing Together canvas](data:image/png;base64,{encoded})\n'

    # Fallback: Cloudinary URL as a plain image link
    if is_trusted_cloudinary_canvas_url(canvas_value):
        return f'\n![Drawing Together canvas]({canvas_value})\n'

    return ''


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

def generate_markdown(instance):
    """Generate a Markdown file for a solo ``ToolInstance`` submission."""
    filename = (
        f"{instance.submitted_at.strftime('%Y%m%d')}"
        f"_{slugify(instance.tool_slug)}_{instance.id}.md"
    )
    relative_path = f"archives/md/{filename}"

    content_lines = [
        f"# {instance.tool_slug.replace('-', ' ').title()}",
        f"**Date:** {instance.submitted_at.strftime('%Y-%m-%d %H:%M')}",
        f"**Tool Version:** {instance.tool_version}",
        "\n--- \n",
        "## Results",
    ]

    canvas_value = None
    for key, value in instance.payload_output.items():
        if key == 'canvas_data':
            # Collect the canvas value; render it as an embedded image below
            # its natural position in the output rather than as a raw path.
            canvas_value = value
            continue
        label = key.replace('_', ' ').title()
        content_lines.append(f"### {label}\n{value}\n")

    if canvas_value:
        content_lines.append("### Drawing\n")
        content_lines.append(_canvas_to_md(canvas_value))

    return _save_file(relative_path, "\n".join(content_lines).encode('utf-8'))


def generate_session_markdown(session):
    """Combine every participant's response into one Markdown file."""
    closed_stamp = (session.closed_at or session.created_at).strftime('%Y%m%d')
    filename = f"{closed_stamp}_{slugify(session.tool_slug)}_session_{session.id}.md"
    relative_path = f"archives/md/{filename}"

    title = session.tool_slug.replace('-', ' ').title()
    closed_at_str = session.closed_at.strftime('%Y-%m-%d %H:%M') if session.closed_at else '-'
    content_lines = [
        f"# {title} — Combined Session Results",
        f"**Hosted by:** {session.host.email if session.host else 'Unknown'}",
        f"**Closed at:** {closed_at_str}",
        f"**Tool version:** {session.tool_version}",
        "\n---\n",
    ]

    instances = session.instances.select_related('user').order_by('submitted_at', 'created_at')
    for inst in instances:
        marker = ' (host)' if inst.user_id == session.host_id else ''
        display = inst.user.email if inst.user_id else (inst.guest_name or 'Guest')
        content_lines.append(f"## {display}{marker}")

        if inst.payload_output:
            canvas_value = None
            for key, value in inst.payload_output.items():
                if key == 'canvas_data':
                    canvas_value = value
                    continue
                label = key.replace('_', ' ').title()
                content_lines.append(f"### {label}\n{value}\n")

            if canvas_value:
                content_lines.append("### Drawing\n")
                content_lines.append(_canvas_to_md(canvas_value))
        else:
            content_lines.append("*No response submitted.*\n")

        # Multimedia attachments — include transcriptions as first-class text;
        # fall back to a plain hyperlink when no transcription was provided.
        for att in (inst.attachments or []):
            att_type = att.get('type', 'attachment')
            att_name = att.get('name', att_type)
            att_url  = att.get('url', '')
            transcription = (att.get('transcription') or '').strip()

            if att_type == 'image':
                label = 'Symbol board / image'
            else:
                label = 'Audio clip'

            if transcription:
                content_lines.append(f"**{label} — transcription:**\n\n> {transcription}\n")
            elif att_url:
                content_lines.append(f"**{label}:** [{att_name}]({att_url})\n")

        content_lines.append("---\n")

    return _save_file(relative_path, "\n".join(content_lines).encode('utf-8'))
