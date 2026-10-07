"""Focused coverage for the Floop-inspired project and visual tools."""
import json
import tempfile
from unittest.mock import patch
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from archive.models import ToolInstance, ToolSession
from exporters.md_gen import generate_markdown
from exporters.md_gen import _load_canvas_bytes as load_markdown_canvas
from exporters.pipeline import run_export_pipeline
from exporters.rtf_gen import generate_rtf
from exporters.rtf_gen import _load_canvas_bytes as load_rtf_canvas
from tools.forms import (
    MoodSketchCheckInForm,
    ProjectVisionMapForm,
    VisualReflectionCanvasForm,
)
from tools.registry import TOOL_CATALOG, get_tool_form_class, get_tool_instance


User = get_user_model()
CANVAS = (
    'data:image/png;base64,'
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk'
    '+A8AAQUBAScY42YAAAAASUVORK5CYII='
)


class Task127RegistryAndFormTests(TestCase):
    def test_registry_resolves_each_new_tool(self):
        expected = {
            'project-vision-map': 'Project Vision Map',
            'visual-reflection-canvas': 'Visual Reflection Canvas',
            'mood-sketch-check-in': 'Mood & Sketch Check-In',
        }
        for slug, title in expected.items():
            self.assertEqual(TOOL_CATALOG[slug]['title'], title)
            self.assertIsNotNone(get_tool_form_class(slug))
            self.assertIsNotNone(get_tool_instance(slug))

    def test_project_vision_map_preserves_optional_prompts(self):
        form = ProjectVisionMapForm({
            'project_goal': 'Create a welcoming and useful member onboarding journey.',
            'best_case': 'New members confidently contribute in their first week.',
        })
        self.assertTrue(form.is_valid(), form.errors)
        output = get_tool_instance('project-vision-map', form.cleaned_data).execute()
        self.assertEqual(output['best_case'], form.cleaned_data['best_case'])
        self.assertEqual(output['requirements'], '')
        with self.assertRaises(ValidationError):
            get_tool_instance('project-vision-map', {'project_goal': 'short'}).execute()

    def test_visual_reflection_requires_drawing_or_text(self):
        self.assertFalse(VisualReflectionCanvasForm({}).is_valid())
        form = VisualReflectionCanvasForm({'canvas_description': 'A path curving toward a sunrise.'})
        self.assertTrue(form.is_valid(), form.errors)
        output = get_tool_instance('visual-reflection-canvas', form.cleaned_data).execute()
        self.assertEqual(output['canvas_description'], 'A path curving toward a sunrise.')
        self.assertFalse(output['has_drawing'])

    def test_canvas_fields_reject_arbitrary_external_urls(self):
        malicious = 'http://127.0.0.1:8000/private'
        visual_form = VisualReflectionCanvasForm({
            'canvas_description': 'A written alternative.',
            'canvas_data': malicious,
        })
        mood_form = MoodSketchCheckInForm({
            'mood': 'concerned',
            'canvas_data': malicious,
        })
        self.assertFalse(visual_form.is_valid())
        self.assertFalse(mood_form.is_valid())

    def test_mood_sketch_requires_mood_and_accepts_it_without_drawing(self):
        self.assertFalse(MoodSketchCheckInForm({}).is_valid())
        form = MoodSketchCheckInForm({'mood': 'hopeful'})
        self.assertTrue(form.is_valid(), form.errors)
        output = get_tool_instance('mood-sketch-check-in', form.cleaned_data).execute()
        self.assertEqual(output['mood'], 'hopeful')
        self.assertEqual(output['canvas_data'], '')
        self.assertFalse(output['has_drawing'])


class Task127CanvasPersistenceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='task127@example.com', password='password123',
        )

    @patch('tools.views.extract_canvas_from_payload')
    def test_signed_in_session_response_persists_canvas(self, extract_canvas):
        extract_canvas.side_effect = lambda data, slug, identifier, **kwargs: {
            **data, 'canvas_data': f'/media/drawings/{identifier}.png',
        }
        session = ToolSession.objects.create(
            host=self.user, tool_slug='visual-reflection-canvas', tool_version='1.0',
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('tools:session_detail', args=[session.id]),
            {'canvas_data': CANVAS, 'canvas_description': ''},
        )
        self.assertEqual(response.status_code, 302)
        instance = ToolInstance.objects.get(session=session, user=self.user)
        self.assertEqual(instance.payload_input['canvas_data'], f'/media/drawings/{self.user.id}.png')
        extract_canvas.assert_called_once()

    @patch('tools.views.extract_canvas_from_payload')
    def test_guest_session_response_persists_canvas_with_non_pii_identifier(self, extract_canvas):
        extract_canvas.side_effect = lambda data, slug, identifier, **kwargs: {
            **data, 'canvas_data': f'/media/drawings/{identifier}.png',
        }
        session = ToolSession.objects.create(
            host=self.user, tool_slug='mood-sketch-check-in', tool_version='1.0',
        )
        join_url = reverse('tools:guest_join', args=[session.id, session.guest_token])
        self.client.post(join_url, {'guest_name': 'A guest name'})
        instance = ToolInstance.objects.get(session=session, user__isnull=True)
        response = self.client.post(
            reverse('tools:guest_respond', args=[session.id, session.guest_token]),
            {'mood': 'hopeful', 'reflection': '', 'canvas_data': CANVAS},
        )
        self.assertEqual(response.status_code, 302)
        instance.refresh_from_db()
        self.assertEqual(
            instance.payload_input['canvas_data'],
            f'/media/drawings/guest-{instance.pk}.png',
        )
        self.assertEqual(extract_canvas.call_args.args[2], f'guest-{instance.pk}')
        self.assertNotIn('A guest name', extract_canvas.call_args.args[2])

    def test_session_buffer_rejects_untrusted_canvas_url(self):
        session = ToolSession.objects.create(
            host=self.user,
            tool_slug='visual-reflection-canvas',
            tool_version='1.0',
        )
        ToolInstance.objects.create(
            session=session,
            user=self.user,
            tool_slug=session.tool_slug,
            tool_version=session.tool_version,
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('tools:session_buffer_save', args=[session.id]),
            data=json.dumps({
                'form_data': {
                    'canvas_data': 'http://169.254.169.254/latest/meta-data/',
                },
            }),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_signed_in_buffered_canvas_survives_host_close(self):
        local_storage = {
            'default': {
                'BACKEND': 'django.core.files.storage.FileSystemStorage',
            },
            'staticfiles': {
                'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
            },
        }
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root, STORAGES=local_storage):
                session = ToolSession.objects.create(
                    host=self.user,
                    tool_slug='visual-reflection-canvas',
                    tool_version='1.0',
                )
                instance = ToolInstance.objects.create(
                    session=session,
                    user=self.user,
                    tool_slug=session.tool_slug,
                    tool_version=session.tool_version,
                )
                self.client.force_login(self.user)
                buffered = self.client.post(
                    reverse('tools:session_buffer_save', args=[session.id]),
                    data=json.dumps({
                        'form_data': {
                            'canvas_data': CANVAS,
                            'canvas_description': '',
                        },
                    }),
                    content_type='application/json',
                )
                self.assertEqual(buffered.status_code, 200)
                instance.refresh_from_db()
                saved_canvas = instance.payload_input['canvas_data']
                self.assertTrue(saved_canvas.startswith('/media/drawings/'))
                self.assertTrue(
                    (Path(media_root) / saved_canvas.removeprefix('/media/')).exists()
                )

                closed = self.client.post(
                    reverse('tools:session_close', args=[session.id]),
                )
                self.assertEqual(closed.status_code, 302)
                instance.refresh_from_db()
                self.assertEqual(instance.payload_output['canvas_data'], saved_canvas)
                self.assertTrue(instance.payload_output['has_drawing'])

    def test_guest_buffered_canvas_survives_host_close(self):
        local_storage = {
            'default': {
                'BACKEND': 'django.core.files.storage.FileSystemStorage',
            },
            'staticfiles': {
                'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
            },
        }
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root, STORAGES=local_storage):
                session = ToolSession.objects.create(
                    host=self.user,
                    tool_slug='visual-reflection-canvas',
                    tool_version='1.0',
                )
                self.client.post(
                    reverse('tools:guest_join', args=[session.id, session.guest_token]),
                    {'guest_name': 'Buffered guest'},
                )
                guest = ToolInstance.objects.get(session=session, user__isnull=True)
                buffered = self.client.post(
                    reverse('tools:session_buffer_save', args=[session.id]),
                    data=json.dumps({
                        'form_data': {
                            'canvas_data': CANVAS,
                            'canvas_description': 'A buffered guest drawing.',
                        },
                    }),
                    content_type='application/json',
                )
                self.assertEqual(buffered.status_code, 200)
                guest.refresh_from_db()
                saved_canvas = guest.payload_input['canvas_data']
                self.assertTrue(saved_canvas.startswith('/media/drawings/'))

                self.client.force_login(self.user)
                closed = self.client.post(
                    reverse('tools:session_close', args=[session.id]),
                )
                self.assertEqual(closed.status_code, 302)
                guest.refresh_from_db()
                self.assertEqual(guest.payload_output['canvas_data'], saved_canvas)
                self.assertEqual(
                    guest.payload_output['canvas_description'],
                    'A buffered guest drawing.',
                )
                self.assertTrue(guest.payload_output['has_drawing'])

    @patch('exporters.rtf_gen.urllib.request.urlopen')
    @patch('exporters.md_gen.urllib.request.urlopen')
    def test_exporters_never_fetch_untrusted_canvas_urls(self, md_urlopen, rtf_urlopen):
        malicious = 'http://127.0.0.1:8000/private'
        self.assertIsNone(load_markdown_canvas(malicious))
        self.assertIsNone(load_rtf_canvas(malicious))
        md_urlopen.assert_not_called()
        rtf_urlopen.assert_not_called()


class Task127ExportTests(TestCase):
    @patch('exporters.md_gen._save_file', return_value='archives/md/task127.md')
    def test_visual_reflection_export_includes_accessible_description(self, save_file):
        user = User.objects.create_user(
            email='task127-export@example.com', password='password123',
        )
        instance = ToolInstance.objects.create(
            user=user,
            tool_slug='visual-reflection-canvas',
            tool_version='1.0',
            status='archived',
            submitted_at=timezone.now(),
            payload_output={
                'canvas_description': 'A bridge linking two groups.',
                'canvas_data': '',
                'has_drawing': False,
            },
        )
        generate_markdown(instance)
        content = save_file.call_args.args[1].decode('utf-8')
        self.assertIn('Canvas Description', content)
        self.assertIn('A bridge linking two groups.', content)

    @patch('exporters.rtf_gen._save_file', return_value='archives/rtf/task127.rtf')
    def test_mood_check_in_rtf_export_includes_mood_and_reflection(self, save_file):
        user = User.objects.create_user(
            email='task127-rtf@example.com', password='password123',
        )
        instance = ToolInstance.objects.create(
            user=user,
            tool_slug='mood-sketch-check-in',
            tool_version='1.0',
            status='archived',
            submitted_at=timezone.now(),
            payload_output={
                'mood': 'calm',
                'reflection': 'Present and ready to begin.',
                'canvas_data': '',
                'has_drawing': False,
            },
        )
        generate_rtf(instance)
        content = save_file.call_args.args[1].decode('utf-8')
        self.assertIn('Mood', content)
        self.assertIn('calm', content)
        self.assertIn('Present and ready to begin.', content)

    def test_local_export_pipeline_ignores_unselected_cloudinary_environment(self):
        user = User.objects.create_user(
            email='task127-local-export@example.com', password='password123',
        )
        instance = ToolInstance.objects.create(
            user=user,
            tool_slug='mood-sketch-check-in',
            tool_version='1.0',
            status='archived',
            submitted_at=timezone.now(),
            payload_output={
                'mood': 'hopeful',
                'reflection': '',
                'canvas_data': '',
                'has_drawing': False,
            },
        )
        local_storage = {
            'default': {
                'BACKEND': 'django.core.files.storage.FileSystemStorage',
            },
            'staticfiles': {
                'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
            },
        }
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root, STORAGES=local_storage):
                run_export_pipeline(instance)
                instance.refresh_from_db()
                self.assertTrue(instance.md_file.name.endswith('.md'))
                self.assertTrue(instance.rtf_file.name.endswith('.rtf'))


class Task127ClosedSessionDisplayTests(TestCase):
    def test_host_and_guest_results_render_canvas_as_an_image(self):
        user = User.objects.create_user(
            email='task127-results@example.com', password='password123',
        )
        session = ToolSession.objects.create(
            host=user,
            tool_slug='visual-reflection-canvas',
            tool_version='1.0',
            status='closed',
            closed_at=timezone.now(),
        )
        instance = ToolInstance.objects.create(
            session=session,
            guest_name='Guest participant',
            tool_slug=session.tool_slug,
            tool_version=session.tool_version,
            status='archived',
            payload_output={
                'canvas_description': 'A bridge between two circles.',
                'canvas_data': '/media/drawings/reflection.png',
                'has_drawing': True,
            },
        )
        context = {
            'session': session,
            'tool_meta': TOOL_CATALOG[session.tool_slug],
            'instances': [instance],
            'guest_instance': instance,
        }
        for template in (
            'tools/session_closed.html',
            'tools/guest_session_closed.html',
        ):
            html = render_to_string(template, context)
            self.assertIn('<img', html)
            self.assertIn('/media/drawings/reflection.png', html)
            self.assertIn('A bridge between two circles.', html)