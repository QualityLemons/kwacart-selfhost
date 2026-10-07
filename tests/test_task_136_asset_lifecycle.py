"""Focused coverage for owned upload and export lifecycle cleanup."""
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.db import transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from archive.assets import (
    canvas_asset_identity,
    delete_canvas_asset,
    delete_cloudinary_asset,
    delete_export_asset,
)
from archive.models import ToolInstance, ToolSession
from archive.retention import collect_references
from exporters.pipeline import run_export_pipeline
from tools.utils import save_canvas_to_file


User = get_user_model()
LOCAL_STORAGE = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}
CANVAS = (
    'data:image/png;base64,'
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk'
    '+A8AAQUBAScY42YAAAAASUVORK5CYII='
)


class AssetDeletionSafetyTests(TestCase):
    @patch('cloudinary.uploader.upload', return_value={'secure_url': 'https://example/canvas'})
    def test_new_cloudinary_canvas_upload_uses_extension_free_public_id(self, upload):
        cloud_storage = {
            **LOCAL_STORAGE,
            'default': {'BACKEND': 'cloudinary_storage.storage.MediaCloudinaryStorage'},
        }
        with override_settings(STORAGES=cloud_storage):
            self.assertEqual(save_canvas_to_file(CANVAS, 'drawing-together', 9), 'https://example/canvas')
        kwargs = upload.call_args.kwargs
        self.assertEqual(kwargs['public_id'], 'drawings/drawing-together_9_431ced6916a2')
        self.assertEqual(kwargs['format'], 'png')

    def test_canvas_cloudinary_identity_handles_new_and_legacy_urls(self):
        new_url = (
            'https://res.cloudinary.com/demo/image/upload/v1/'
            'drawings/new-canvas.png'
        )
        legacy_url = (
            'https://res.cloudinary.com/demo/image/upload/v1/'
            'drawings/legacy-canvas.png.png'
        )
        self.assertEqual(
            canvas_asset_identity(new_url),
            ('cloudinary', 'image', 'drawings/new-canvas'),
        )
        self.assertEqual(
            canvas_asset_identity(legacy_url),
            ('cloudinary', 'image', 'drawings/legacy-canvas.png'),
        )

    @patch('cloudinary.uploader.destroy')
    def test_transformed_canvas_urls_use_public_id_after_version(self, destroy):
        current = (
            'https://res.cloudinary.com/demo/image/upload/c_fill,w_300/v42/'
            'drawings/current.png'
        )
        legacy = (
            'https://res.cloudinary.com/demo/image/upload/c_fill,w_300/v42/'
            'drawings/legacy.png.png'
        )
        self.assertTrue(delete_canvas_asset(current))
        self.assertTrue(delete_canvas_asset(legacy))
        self.assertEqual(
            [call.args[0] for call in destroy.call_args_list],
            ['drawings/current', 'drawings/legacy.png'],
        )

    def test_versionless_transformed_canvas_url_fails_closed(self):
        self.assertIsNone(canvas_asset_identity(
            'https://res.cloudinary.com/demo/image/upload/c_fill,w_300/'
            'drawings/current.png',
        ))

    @patch('cloudinary.uploader.destroy')
    def test_cloudinary_deletion_rejects_unowned_public_ids(self, destroy):
        self.assertFalse(delete_cloudinary_asset(
            'someone-else/private', 'image', 'canvas',
        ))
        self.assertFalse(delete_cloudinary_asset(
            'drawings/../private', 'image', 'canvas',
        ))
        destroy.assert_not_called()

    @patch('cloudinary.uploader.destroy')
    def test_cloudinary_export_is_deleted_as_raw_resource(self, destroy):
        value = (
            'https://res.cloudinary.com/demo/raw/upload/v123/'
            'archives/md/20260101_tool_1.md'
        )
        self.assertTrue(delete_export_asset(value))
        destroy.assert_called_once_with(
            'archives/md/20260101_tool_1.md',
            resource_type='raw',
            invalidate=True,
        )

    def test_local_export_deletion_is_idempotent_and_constrained(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root, STORAGES=LOCAL_STORAGE):
                export = Path(media_root) / 'archives/md/result.md'
                export.parent.mkdir(parents=True)
                export.write_text('result')
                self.assertTrue(delete_export_asset('archives/md/result.md'))
                self.assertFalse(export.exists())
                self.assertTrue(delete_export_asset('archives/md/result.md'))
                self.assertFalse(delete_export_asset('../outside.md'))


class ModelAssetLifecycleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='task136@example.com', password='password123',
        )

    def test_canvas_replacement_deletes_old_local_file_after_save(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root, STORAGES=LOCAL_STORAGE):
                old = Path(media_root) / 'drawings/old.png'
                old.parent.mkdir(parents=True)
                old.write_bytes(b'old')
                instance = ToolInstance.objects.create(
                    user=self.user,
                    tool_slug='drawing-together',
                    tool_version='1.0',
                    payload_input={'canvas_data': '/media/drawings/old.png'},
                )
                with self.captureOnCommitCallbacks(execute=True):
                    instance.payload_input = {
                        'canvas_data': '/media/drawings/new.png',
                    }
                    instance.save()
                self.assertFalse(old.exists())

    @patch('cloudinary.uploader.destroy')
    def test_cloudinary_canvas_replacement_deletes_legacy_explicit_id(self, destroy):
        old_url = (
            'https://res.cloudinary.com/demo/image/upload/v1/'
            'drawings/old.png.png'
        )
        instance = ToolInstance.objects.create(
            user=self.user, tool_slug='drawing-together', tool_version='1.0',
            payload_input={'canvas_data': old_url},
        )
        with self.captureOnCommitCallbacks(execute=True):
            instance.payload_input = {'canvas_data': ''}
            instance.save()
        destroy.assert_called_once_with(
            'drawings/old.png', resource_type='image', invalidate=True,
        )

    @patch('cloudinary.uploader.destroy')
    def test_nested_canvas_reference_prevents_cloudinary_delete(self, destroy):
        canvas = (
            'https://res.cloudinary.com/demo/image/upload/v1/'
            'drawings/nested.png'
        )
        first = ToolInstance.objects.create(
            user=self.user, tool_slug='drawing-together', tool_version='1.0',
            payload_input={'canvas_data': canvas},
        )
        ToolInstance.objects.create(
            user=self.user, tool_slug='drawing-together', tool_version='1.0',
            payload_output={'steps': [{'canvas_data': canvas}]},
        )
        with self.captureOnCommitCallbacks(execute=True):
            first.delete()
        destroy.assert_not_called()

    def test_retention_matches_transformed_current_and_legacy_canvas_urls(self):
        current = (
            'https://res.cloudinary.com/demo/image/upload/c_fill,w_300/v42/'
            'drawings/current.png'
        )
        legacy = (
            'https://res.cloudinary.com/demo/image/upload/c_fill,w_300/v42/'
            'drawings/legacy.png.png'
        )
        ToolInstance.objects.create(
            user=self.user, tool_slug='drawing-together', tool_version='1.0',
            payload_output={'canvases': [
                {'canvas_data': current},
                {'nested': {'canvas_data': legacy}},
            ]},
        )
        keys, urls = collect_references()
        self.assertIn(('image', 'drawings/current'), keys)
        self.assertIn(('image', 'drawings/legacy.png'), keys)
        self.assertIn(current, urls)
        self.assertIn(legacy, urls)

    @patch('cloudinary.uploader.destroy')
    def test_rolled_back_canvas_replacement_never_deletes(self, destroy):
        canvas = (
            'https://res.cloudinary.com/demo/image/upload/v1/'
            'drawings/rollback.png'
        )
        instance = ToolInstance.objects.create(
            user=self.user, tool_slug='drawing-together', tool_version='1.0',
            payload_input={'canvas_data': canvas},
        )
        with transaction.atomic():
            instance.payload_input = {'canvas_data': ''}
            instance.save()
            transaction.set_rollback(True)
        destroy.assert_not_called()

    def test_shared_canvas_survives_until_last_instance_is_deleted(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root, STORAGES=LOCAL_STORAGE):
                canvas = Path(media_root) / 'drawings/shared.png'
                canvas.parent.mkdir(parents=True)
                canvas.write_bytes(b'shared')
                value = '/media/drawings/shared.png'
                first = ToolInstance.objects.create(
                    user=self.user, tool_slug='drawing-together',
                    tool_version='1.0', payload_input={'canvas_data': value},
                )
                second = ToolInstance.objects.create(
                    user=self.user, tool_slug='drawing-together',
                    tool_version='1.0', payload_output={'canvas_data': value},
                )
                with self.captureOnCommitCallbacks(execute=True):
                    first.delete()
                self.assertTrue(canvas.exists())
                with self.captureOnCommitCallbacks(execute=True):
                    second.delete()
                self.assertFalse(canvas.exists())

    @patch('exporters.pipeline.cleanup_export_if_unreferenced')
    @patch('exporters.pipeline.generate_rtf', side_effect=RuntimeError('failed'))
    @patch(
        'exporters.pipeline.generate_markdown',
        return_value='archives/md/generated.md',
    )
    def test_partial_export_failure_cleans_generated_file(
        self, generate_markdown, generate_rtf, cleanup,
    ):
        instance = ToolInstance.objects.create(
            user=self.user, tool_slug='min-specs', tool_version='1.0',
        )
        run_export_pipeline(instance)
        cleanup.assert_called_once_with('archives/md/generated.md')

    @patch('cloudinary.uploader.destroy')
    def test_attachment_removal_deletes_matched_video_after_commit(self, destroy):
        session = ToolSession.objects.create(
            host=self.user, tool_slug='min-specs', tool_version='1.0',
        )
        public_id = f'kwacart/attachments/{session.id}/clip'
        ToolInstance.objects.create(
            session=session,
            user=self.user,
            tool_slug=session.tool_slug,
            tool_version=session.tool_version,
            attachments=[{
                'type': 'audio', 'public_id': public_id, 'url': 'https://example/clip',
            }],
        )
        self.client.force_login(self.user)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse('tools:session_attachment_remove', args=[session.id]),
                {'public_id': public_id},
            )
        self.assertEqual(response.status_code, 200)
        destroy.assert_called_once_with(
            public_id, resource_type='video', invalidate=True,
        )

    @patch('cloudinary.uploader.destroy')
    def test_session_cascade_cleans_child_canvas_attachment_and_exports(self, destroy):
        session = ToolSession.objects.create(
            host=self.user, tool_slug='min-specs', tool_version='1.0',
            md_file=(
                'https://res.cloudinary.com/demo/raw/upload/v1/'
                'archives/md/session.md'
            ),
        )
        canvas = (
            'https://res.cloudinary.com/demo/image/upload/v1/'
            'drawings/session-child.png'
        )
        attachment_id = f'kwacart/attachments/{session.id}/child'
        ToolInstance.objects.create(
            session=session, user=self.user, tool_slug=session.tool_slug,
            tool_version=session.tool_version,
            payload_input={'deep': {'canvas_data': canvas}},
            attachments=[{'type': 'image', 'public_id': attachment_id}],
            md_file=(
                'https://res.cloudinary.com/demo/raw/upload/v1/'
                'archives/md/child.md'
            ),
        )
        with self.captureOnCommitCallbacks(execute=True):
            session.delete()
        deleted = {
            (call.args[0], call.kwargs['resource_type'])
            for call in destroy.call_args_list
        }
        self.assertSetEqual(deleted, {
            ('drawings/session-child', 'image'),
            (attachment_id, 'image'),
            ('archives/md/session.md', 'raw'),
            ('archives/md/child.md', 'raw'),
        })

    @patch('tools.views.delete_attachment_asset')
    @override_settings(STORAGES={
        'default': {'BACKEND': 'cloudinary_storage.storage.MediaCloudinaryStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    })
    @patch('cloudinary.uploader.upload')
    def test_failed_database_write_cleans_successful_upload(self, upload, delete):
        session = ToolSession.objects.create(
            host=self.user, tool_slug='min-specs', tool_version='1.0',
        )
        instance = ToolInstance.objects.create(
            session=session, user=self.user,
            tool_slug=session.tool_slug, tool_version=session.tool_version,
        )
        public_id_prefix = f'kwacart/attachments/{session.id}/{instance.id}_image_'
        upload.side_effect = lambda *args, **kwargs: {
            'secure_url': 'https://res.cloudinary.com/demo/image/upload/file.png',
            'public_id': kwargs['public_id'],
        }
        self.client.force_login(self.user)
        with patch.object(ToolInstance, 'save', side_effect=IntegrityError('failed')):
            with self.assertRaises(IntegrityError):
                self.client.post(
                    reverse('tools:session_attachment_upload', args=[session.id]),
                    {'file': self._image()},
                )
        cleaned = delete.call_args.args[0]
        self.assertTrue(cleaned['public_id'].startswith(public_id_prefix))
        self.assertEqual(delete.call_args.args[1], session.id)

    @staticmethod
    def _image():
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile('symbol.png', b'png', content_type='image/png')