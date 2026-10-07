"""Focused coverage for retention cleanup and provider safety boundaries."""
from datetime import timedelta
from io import StringIO
import threading
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import RequestRateLimit
from archive.assets import cloudinary_asset_lock
from archive.models import AuditLog, FeatureRequest, ToolInstance, ToolSession
from archive.retention import Asset, CloudinaryInventory, is_owned_asset
from tools.utils import canvas_write_lock


RETENTION = {
    'RETENTION_TOOL_DATA_DAYS': 30,
    'RETENTION_AUDIT_LOG_DAYS': 30,
    'RETENTION_FEEDBACK_DAYS': 30,
    'RETENTION_RATE_LIMIT_DAYS': 2,
    'RETENTION_DRAWING_ORPHAN_GRACE_HOURS': 24,
}
CANVAS = (
    'data:image/png;base64,'
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk'
    '+A8AAQUBAScY42YAAAAASUVORK5CYII='
)
CLOUD_STORAGE = {
    'default': {'BACKEND': 'cloudinary_storage.storage.MediaCloudinaryStorage'},
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}


class FakeInventory:
    deleted = []

    def __init__(self, batch_size):
        self.batch_size = batch_size

    def configured(self):
        return True

    def resources(self):
        created_at = timezone.now() - timedelta(days=60)
        return iter([
            Asset(
                'raw',
                'archives/md/old.md',
                'https://res.cloudinary.com/c/raw/upload/v1/archives/md/old.md',
                created_at=created_at,
                version=1,
            ),
            Asset(
                'raw',
                'archives/md/live.md',
                'https://res.cloudinary.com/c/raw/upload/v1/archives/md/live.md',
                created_at=created_at,
                version=1,
            ),
            Asset('image', 'unowned/never-delete'),
        ])

    def delete(self, assets):
        self.__class__.deleted = list(assets)
        return len(self.deleted), []

    def resource(self, asset):
        return asset


@override_settings(**RETENTION)
class RetentionCommandTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            'retention@example.com', 'A-strong-password-136!',
        )
        self.old = timezone.now() - timedelta(days=60)
        self.recent = timezone.now() - timedelta(days=1)

    def _records(self):
        old_session = ToolSession.objects.create(
            host=self.user, tool_slug='one', tool_version='1', status='closed',
            closed_at=self.old, md_file='https://res.cloudinary.com/c/raw/upload/v1/archives/md/old.md',
        )
        live_instance = ToolInstance.objects.create(
            user=self.user, tool_slug='two', tool_version='1',
            md_file='https://res.cloudinary.com/c/raw/upload/v1/archives/md/live.md',
        )
        old_instance = ToolInstance.objects.create(
            user=self.user, tool_slug='three', tool_version='1',
        )
        ToolInstance.objects.filter(pk=old_instance.pk).update(updated_at=self.old)
        audit = AuditLog.objects.create(user=self.user, action='login')
        AuditLog.objects.filter(pk=audit.pk).update(timestamp=self.old)
        feedback = FeatureRequest.objects.create(title='old')
        FeatureRequest.objects.filter(pk=feedback.pk).update(submitted_at=self.old)
        rate = RequestRateLimit.objects.create(key='a')
        RequestRateLimit.objects.filter(pk=rate.pk).update(updated_at=self.old)
        Session.objects.create(
            session_key='expired-session', session_data='', expire_date=self.old,
        )
        return old_session, live_instance, old_instance

    @patch(
        'archive.management.commands.cleanup_retention.CloudinaryInventory',
        FakeInventory,
    )
    def test_default_is_dry_run_and_reports_without_deleting(self):
        old_session, _, old_instance = self._records()
        output = StringIO()
        call_command('cleanup_retention', stdout=output)
        self.assertTrue(ToolSession.objects.filter(pk=old_session.pk).exists())
        self.assertTrue(ToolInstance.objects.filter(pk=old_instance.pk).exists())
        self.assertIn('DRY RUN', output.getvalue())
        self.assertIn('orphaned/expiring owned Cloudinary assets: 1', output.getvalue())
        self.assertEqual(FakeInventory.deleted, [])

    @patch(
        'archive.management.commands.cleanup_retention.CloudinaryInventory',
        FakeInventory,
    )
    def test_delete_removes_eligible_rows_and_only_unreferenced_owned_asset(self):
        FakeInventory.deleted = []
        old_session, live_instance, old_instance = self._records()
        call_command('cleanup_retention', '--delete', stdout=StringIO())
        self.assertFalse(ToolSession.objects.filter(pk=old_session.pk).exists())
        self.assertFalse(ToolInstance.objects.filter(pk=old_instance.pk).exists())
        self.assertTrue(ToolInstance.objects.filter(pk=live_instance.pk).exists())
        self.assertFalse(AuditLog.objects.exists())
        self.assertFalse(FeatureRequest.objects.exists())
        self.assertFalse(RequestRateLimit.objects.exists())
        self.assertFalse(Session.objects.exists())
        self.assertEqual(
            [asset.public_id for asset in FakeInventory.deleted],
            ['archives/md/old.md'],
        )
        # A second execution has no rows/assets newly eligible.
        call_command('cleanup_retention', '--delete', stdout=StringIO())


class CloudinarySafetyTests(TestCase):
    def test_prefix_allow_list_cannot_be_widened_by_database_values(self):
        self.assertTrue(is_owned_asset('raw', 'archives/rtf/a.rtf'))
        self.assertTrue(is_owned_asset('video', 'kwacart/attachments/s/audio'))
        self.assertFalse(is_owned_asset('image', 'customer-assets/photo'))
        self.assertFalse(is_owned_asset('raw', 'archives-other/file'))

    @patch('cloudinary.api.resources')
    def test_inventory_includes_provider_timestamps(self, resources):
        created_at = timezone.now() - timedelta(days=2)
        updated_at = timezone.now() - timedelta(days=1)
        resources.return_value = {
            'resources': [{
                'public_id': 'drawings/timestamped',
                'secure_url': 'https://res.cloudinary.com/c/image/upload/drawings/timestamped',
                'created_at': created_at.isoformat(),
                'updated_at': updated_at.isoformat(),
            }],
        }
        assets = list(CloudinaryInventory().resources())
        self.assertEqual(assets[0].created_at, created_at)
        self.assertEqual(assets[0].updated_at, updated_at)

    @override_settings(**RETENTION)
    @patch('archive.management.commands.cleanup_retention.CloudinaryInventory')
    def test_recent_drawing_waits_for_grace_period(self, inventory_class):
        inventory = inventory_class.return_value
        inventory.configured.return_value = True
        inventory.resources.return_value = iter([
            Asset(
                'image',
                'drawings/recent',
                created_at=timezone.now() - timedelta(hours=1),
            ),
        ])
        call_command('cleanup_retention', '--delete', stdout=StringIO())
        inventory.delete.assert_not_called()

    @override_settings(**RETENTION)
    @patch('archive.management.commands.cleanup_retention.CloudinaryInventory')
    def test_canvas_referenced_between_inventory_and_delete_is_kept(
        self, inventory_class,
    ):
        canvas_url = (
            'https://res.cloudinary.com/c/image/upload/v1/drawings/re-uploaded'
        )
        asset = Asset(
            'image',
            'drawings/re-uploaded',
            canvas_url,
            created_at=timezone.now() - timedelta(days=2),
        )
        inventory = inventory_class.return_value
        inventory.configured.return_value = True
        inventory.resources.return_value = iter([asset])
        inventory.resource.return_value = asset

        from archive.management.commands import cleanup_retention
        original_collect = cleanup_retention.collect_references
        calls = 0

        def collect_then_reference(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                ToolInstance.objects.create(
                    user=get_user_model().objects.create_user(
                        'race@example.com', 'A-strong-password-136!'
                    ),
                    tool_slug='drawing',
                    tool_version='1',
                    payload_output={'canvas_data': canvas_url},
                )
            return original_collect(**kwargs)

        with patch.object(
            cleanup_retention,
            'collect_references',
            side_effect=collect_then_reference,
        ):
            call_command('cleanup_retention', '--delete', stdout=StringIO())

        inventory.delete.assert_not_called()

    @override_settings(**RETENTION)
    @patch('archive.management.commands.cleanup_retention.CloudinaryInventory')
    def test_overwrite_after_inventory_is_not_deleted_before_reference_commit(
        self, inventory_class,
    ):
        old = timezone.now() - timedelta(days=2)
        candidate = Asset(
            'image', 'drawings/re-uploaded', created_at=old, version=1,
        )
        overwritten = Asset(
            'image',
            'drawings/re-uploaded',
            created_at=old,
            updated_at=timezone.now(),
            version=2,
        )
        inventory = inventory_class.return_value
        inventory.configured.return_value = True
        inventory.resources.return_value = iter([candidate])
        # The provider overwrite has happened, but its ToolInstance save has not.
        inventory.resource.return_value = overwritten

        call_command('cleanup_retention', '--delete', stdout=StringIO())

        inventory.resource.assert_called_once_with(candidate)
        inventory.delete.assert_not_called()

    @override_settings(STORAGES=CLOUD_STORAGE)
    def test_replacement_upload_waits_for_final_check_and_old_asset_delete(self):
        public_id = 'drawings/drawing-together_9_431ced6916a2'
        upload_started = threading.Event()
        upload_acquired = threading.Event()
        order = []

        def replacement_upload_and_save():
            upload_started.set()
            with canvas_write_lock(
                {'canvas_data': CANVAS}, 'drawing-together', 9,
            ):
                upload_acquired.set()
                order.extend(['replacement uploaded', 'reference committed'])

        with cloudinary_asset_lock('image', public_id):
            order.append('final reference check')
            thread = threading.Thread(target=replacement_upload_and_save)
            thread.start()
            self.assertTrue(upload_started.wait(1))
            self.assertFalse(upload_acquired.wait(0.05))
            order.append('old asset deleted')

        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(order, [
            'final reference check',
            'old asset deleted',
            'replacement uploaded',
            'reference committed',
        ])

    @patch('cloudinary.api.delete_resources')
    def test_provider_deletes_use_resource_type_and_batches(self, delete_resources):
        delete_resources.side_effect = [
            {'deleted': {f'drawings/{i}': 'deleted' for i in range(2)}},
            {'deleted': {'drawings/2': 'not_found'}},
            {'deleted': {'archives/md/a.md': 'deleted'}},
        ]
        inventory = CloudinaryInventory(batch_size=2)
        assets = [
            Asset('image', f'drawings/{i}') for i in range(3)
        ] + [Asset('raw', 'archives/md/a.md'), Asset('raw', 'not-owned/a')]
        deleted, errors = inventory.delete(assets)
        self.assertEqual(deleted, 4)
        self.assertEqual(errors, [])
        self.assertEqual(delete_resources.call_count, 3)
        self.assertEqual(
            delete_resources.call_args_list[0].kwargs['resource_type'], 'image',
        )
        self.assertEqual(
            delete_resources.call_args_list[2].kwargs['resource_type'], 'raw',
        )
