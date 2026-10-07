"""Retention planning and safe Cloudinary reconciliation.

Only assets below prefixes owned exclusively by KwaCart are inventoried or
deleted.  Database values never widen this allow-list.
"""
from dataclasses import dataclass
from datetime import datetime
from django.conf import settings
from django.utils.dateparse import parse_datetime

from archive.assets import cloudinary_key_from_url
from archive.models import ToolInstance, ToolSession


# (resource type, public-id prefix).  Keep this list in step with upload code.
OWNED_CLOUDINARY_PREFIXES = (
    ('raw', 'archives/md/'),
    ('raw', 'archives/rtf/'),
    ('raw', 'archives/html/'),
    ('image', 'drawings/'),
    ('image', 'kwacart/attachments/'),
    ('video', 'kwacart/attachments/'),
)


@dataclass(frozen=True)
class Asset:
    resource_type: str
    public_id: str
    secure_url: str = ''
    created_at: datetime | None = None
    updated_at: datetime | None = None
    version: int | None = None

    @property
    def key(self):
        return self.resource_type, self.public_id

    @property
    def provider_timestamp(self):
        return self.updated_at or self.created_at


def is_owned_asset(resource_type, public_id):
    """Return True only for a known resource type and exact owned prefix."""
    return any(
        resource_type == allowed_type and public_id.startswith(prefix)
        for allowed_type, prefix in OWNED_CLOUDINARY_PREFIXES
    )


def _cloudinary_key_from_url(value):
    """Best-effort identity extraction shared with lifecycle deletion."""
    key = cloudinary_key_from_url(value)
    return key if key and is_owned_asset(*key) else None


def _add_reference(keys, urls, value, resource_type=None, public_id=None):
    if isinstance(value, str) and value:
        urls.add(value.split('?', 1)[0])
        parsed = _cloudinary_key_from_url(value)
        if parsed:
            keys.add(parsed)
    if resource_type and isinstance(public_id, str):
        if is_owned_asset(resource_type, public_id):
            keys.add((resource_type, public_id))


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


def collect_references(*, excluded_sessions=(), excluded_instances=()):
    """Return provider identities and URLs referenced by retained DB rows."""
    keys, urls = set(), set()
    sessions = ToolSession.objects.exclude(pk__in=excluded_sessions)
    for session in sessions.iterator():
        _add_reference(keys, urls, session.md_file.name if session.md_file else '')
        _add_reference(keys, urls, session.rtf_file.name if session.rtf_file else '')

    instances = ToolInstance.objects.exclude(pk__in=excluded_instances)
    if excluded_sessions:
        instances = instances.exclude(session_id__in=excluded_sessions)
    for instance in instances.iterator():
        for field_name in ('html_file', 'md_file', 'rtf_file'):
            field = getattr(instance, field_name)
            _add_reference(keys, urls, field.name if field else '')
        for payload in (instance.payload_input, instance.payload_output):
            for value in _walk_canvas_values(payload):
                _add_reference(keys, urls, value)
        for attachment in instance.attachments or []:
            if not isinstance(attachment, dict):
                continue
            resource_type = 'image' if attachment.get('type') == 'image' else 'video'
            _add_reference(
                keys,
                urls,
                attachment.get('url'),
                resource_type,
                attachment.get('public_id'),
            )
    return keys, urls


def asset_is_referenced(asset, keys, urls):
    clean_url = asset.secure_url.split('?', 1)[0] if asset.secure_url else ''
    return asset.key in keys or bool(clean_url and clean_url in urls)


def drawing_asset_is_old_enough(asset, cutoff):
    """Require drawings to have a provider timestamp older than the grace cutoff."""
    if asset.resource_type != 'image' or not asset.public_id.startswith('drawings/'):
        return True
    return bool(asset.provider_timestamp and asset.provider_timestamp <= cutoff)


def _provider_datetime(value):
    if isinstance(value, datetime):
        return value
    return parse_datetime(value) if isinstance(value, str) else None


def same_provider_version(inventoried, current):
    """Return True only when current provider metadata matches inventory."""
    if inventoried.key != current.key:
        return False
    if (
        inventoried.version is not None
        and current.version is not None
        and inventoried.version != current.version
    ):
        return False
    return (
        inventoried.provider_timestamp is not None
        and inventoried.provider_timestamp == current.provider_timestamp
    )


class CloudinaryInventory:
    """Small adapter around Cloudinary's Admin API, convenient to mock."""

    def __init__(self, batch_size=None):
        self.batch_size = min(int(batch_size or settings.RETENTION_CLEANUP_BATCH_SIZE), 100)

    def configured(self):
        try:
            import cloudinary
            config = cloudinary.config()
            return bool(config.cloud_name and config.api_key and config.api_secret)
        except Exception:
            return False

    def resources(self):
        import cloudinary.api

        for resource_type, prefix in OWNED_CLOUDINARY_PREFIXES:
            cursor = None
            while True:
                kwargs = {
                    'resource_type': resource_type,
                    'type': 'upload',
                    'prefix': prefix,
                    'max_results': 500,
                }
                if cursor:
                    kwargs['next_cursor'] = cursor
                response = cloudinary.api.resources(**kwargs)
                for item in response.get('resources', []):
                    asset = Asset(
                        resource_type,
                        item.get('public_id', ''),
                        item.get('secure_url', ''),
                        _provider_datetime(item.get('created_at')),
                        _provider_datetime(item.get('updated_at')),
                        item.get('version'),
                    )
                    # Defend again in case the provider returns an unexpected row.
                    if asset.public_id and is_owned_asset(*asset.key):
                        yield asset
                cursor = response.get('next_cursor')
                if not cursor:
                    break

    def resource(self, asset):
        """Fetch current metadata for one candidate immediately before deletion."""
        import cloudinary.api

        item = cloudinary.api.resource(
            asset.public_id,
            resource_type=asset.resource_type,
            type='upload',
        )
        return Asset(
            asset.resource_type,
            item.get('public_id', ''),
            item.get('secure_url', ''),
            _provider_datetime(item.get('created_at')),
            _provider_datetime(item.get('updated_at')),
            item.get('version'),
        )

    def delete(self, assets):
        """Delete in provider-sized batches and return (deleted, errors)."""
        import cloudinary.api

        deleted = 0
        errors = []
        grouped = {}
        for asset in assets:
            if is_owned_asset(*asset.key):
                grouped.setdefault(asset.resource_type, []).append(asset.public_id)
        for resource_type, public_ids in grouped.items():
            for start in range(0, len(public_ids), self.batch_size):
                batch = public_ids[start:start + self.batch_size]
                try:
                    response = cloudinary.api.delete_resources(
                        batch, resource_type=resource_type, type='upload',
                    )
                    statuses = response.get('deleted', {})
                    for public_id in batch:
                        status = statuses.get(public_id)
                        if status in ('deleted', 'not_found'):
                            deleted += 1
                        else:
                            errors.append(f'{resource_type}:{public_id}: {status or "no status"}')
                except Exception as exc:
                    errors.append(
                        f'{resource_type} batch beginning {batch[0]}: {exc}'
                    )
        return deleted, errors
