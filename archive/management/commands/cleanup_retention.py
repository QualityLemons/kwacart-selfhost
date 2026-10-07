"""Apply configured database retention and reconcile owned Cloudinary assets."""
from contextlib import contextmanager
from datetime import timedelta

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models.signals import post_delete
from django.utils import timezone

from accounts.models import RequestRateLimit
from archive.assets import cloudinary_asset_lock
from archive.models import AuditLog, FeatureRequest, ToolInstance, ToolSession
from archive.retention import (
    CloudinaryInventory,
    asset_is_referenced,
    collect_references,
    drawing_asset_is_old_enough,
    is_owned_asset,
    same_provider_version,
)


@contextmanager
def _defer_cloudinary_model_cleanup(enabled):
    """Let reconciliation batch provider cleanup instead of signal-by-signal calls.

    Local-storage runs retain the normal model signals, which remove local
    exports and canvases.  Receivers are always restored, including on errors.
    """
    if not enabled:
        yield
        return
    from archive.signals import (
        cleanup_deleted_instance_assets,
        cleanup_deleted_session_exports,
    )

    receivers = (
        (cleanup_deleted_instance_assets, ToolInstance),
        (cleanup_deleted_session_exports, ToolSession),
    )
    for receiver, sender in receivers:
        post_delete.disconnect(receiver, sender=sender)
    try:
        yield
    finally:
        for receiver, sender in receivers:
            post_delete.connect(receiver, sender=sender)


class Command(BaseCommand):
    help = (
        'Report retention-eligible data and orphaned owned Cloudinary assets. '
        'Nothing is removed unless --delete is supplied.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--delete', action='store_true',
            help='Delete eligible rows and orphaned owned provider assets.',
        )
        parser.add_argument(
            '--skip-cloudinary', action='store_true',
            help='Only process database retention.',
        )
        parser.add_argument(
            '--batch-size', type=int,
            default=settings.RETENTION_CLEANUP_BATCH_SIZE,
            help='Database/provider deletion batch size (maximum provider batch is 100).',
        )

    @staticmethod
    def _cutoff(setting_name, now):
        days = getattr(settings, setting_name)
        if days is None:
            return None
        if isinstance(days, bool) or not isinstance(days, int) or days <= 0:
            raise CommandError(f'{setting_name} must be a positive integer or None.')
        return now - timedelta(days=days)

    @staticmethod
    def _delete_queryset(queryset, batch_size):
        total = 0
        while True:
            pks = list(queryset.values_list('pk', flat=True)[:batch_size])
            if not pks:
                break
            with transaction.atomic():
                total += queryset.model.objects.filter(pk__in=pks).delete()[0]
        return total

    def handle(self, *args, **options):
        delete = options['delete']
        batch_size = options['batch_size']
        if batch_size <= 0:
            raise CommandError('--batch-size must be positive.')
        now = timezone.now()
        drawing_grace_hours = settings.RETENTION_DRAWING_ORPHAN_GRACE_HOURS
        if (
            isinstance(drawing_grace_hours, bool)
            or not isinstance(drawing_grace_hours, int)
            or drawing_grace_hours <= 0
        ):
            raise CommandError(
                'RETENTION_DRAWING_ORPHAN_GRACE_HOURS must be a positive integer.'
            )
        drawing_cutoff = now - timedelta(hours=drawing_grace_hours)
        tool_cutoff = self._cutoff('RETENTION_TOOL_DATA_DAYS', now)
        audit_cutoff = self._cutoff('RETENTION_AUDIT_LOG_DAYS', now)
        feedback_cutoff = self._cutoff('RETENTION_FEEDBACK_DAYS', now)
        rate_cutoff = self._cutoff('RETENTION_RATE_LIMIT_DAYS', now)

        sessions = ToolSession.objects.none()
        solo_instances = ToolInstance.objects.none()
        if tool_cutoff:
            sessions = ToolSession.objects.filter(
                status='closed', closed_at__lt=tool_cutoff,
            )
            solo_instances = ToolInstance.objects.filter(
                session__isnull=True, updated_at__lt=tool_cutoff,
            )
        audit_logs = (
            AuditLog.objects.filter(timestamp__lt=audit_cutoff)
            if audit_cutoff else AuditLog.objects.none()
        )
        feedback = (
            FeatureRequest.objects.filter(submitted_at__lt=feedback_cutoff)
            if feedback_cutoff else FeatureRequest.objects.none()
        )
        rate_limits = (
            RequestRateLimit.objects.filter(updated_at__lt=rate_cutoff)
            .filter(locked_until__isnull=True)
            | RequestRateLimit.objects.filter(
                updated_at__lt=rate_cutoff, locked_until__lte=now,
            )
            if rate_cutoff else RequestRateLimit.objects.none()
        )
        expired_sessions = Session.objects.filter(expire_date__lt=now)

        planned = {
            'closed tool sessions': sessions.count(),
            'solo tool instances': solo_instances.count(),
            'audit logs': audit_logs.count(),
            'feedback rows': feedback.count(),
            'request-rate-limit rows': rate_limits.count(),
            'expired Django sessions': expired_sessions.count(),
        }
        mode = 'DELETE' if delete else 'DRY RUN'
        self.stdout.write(f'Retention cleanup ({mode})')
        for label, count in planned.items():
            self.stdout.write(f'  {label}: {count}')

        excluded_sessions = list(sessions.values_list('pk', flat=True))
        excluded_instances = list(solo_instances.values_list('pk', flat=True))
        cloudinary = CloudinaryInventory(batch_size)
        provider_candidates = []
        provider_errors = []
        if not options['skip_cloudinary']:
            if cloudinary.configured():
                try:
                    keys, urls = collect_references(
                        excluded_sessions=excluded_sessions,
                        excluded_instances=excluded_instances,
                    )
                    provider_candidates = [
                        asset for asset in cloudinary.resources()
                        if is_owned_asset(*asset.key)
                        and drawing_asset_is_old_enough(asset, drawing_cutoff)
                        and not asset_is_referenced(asset, keys, urls)
                    ]
                    self.stdout.write(
                        f'  orphaned/expiring owned Cloudinary assets: '
                        f'{len(provider_candidates)}'
                    )
                except Exception as exc:
                    provider_errors.append(f'Cloudinary inventory failed: {exc}')
            else:
                self.stdout.write('  Cloudinary: skipped (not configured)')

        if delete:
            # Database-first means a provider failure leaves a recoverable orphan,
            # never a live row pointing at a file this command just removed.
            provider_cleanup_is_batched = (
                not options['skip_cloudinary'] and cloudinary.configured()
            )
            with _defer_cloudinary_model_cleanup(provider_cleanup_is_batched):
                for queryset in (
                    solo_instances, sessions, audit_logs, feedback,
                    rate_limits, expired_sessions,
                ):
                    self._delete_queryset(queryset, batch_size)
            if provider_candidates and not provider_errors:
                deleted = 0
                errors = []
                for asset in provider_candidates:
                    with cloudinary_asset_lock(*asset.key):
                        # Refresh provider state and DB references while uploads
                        # of the same drawing identity are excluded.
                        current = cloudinary.resource(asset)
                        keys, urls = collect_references()
                        if (
                            is_owned_asset(*current.key)
                            and same_provider_version(asset, current)
                            and drawing_asset_is_old_enough(current, drawing_cutoff)
                            and not asset_is_referenced(current, keys, urls)
                        ):
                            asset_deleted, asset_errors = cloudinary.delete([current])
                            deleted += asset_deleted
                            errors.extend(asset_errors)
                self.stdout.write(f'  Cloudinary assets removed: {deleted}')
                provider_errors.extend(errors)

        if provider_errors:
            for error in provider_errors:
                self.stderr.write(error)
            raise CommandError(
                f'Retention cleanup completed with {len(provider_errors)} provider error(s).'
            )
        if not delete:
            self.stdout.write('Dry run only; rerun with --delete to remove these items.')
