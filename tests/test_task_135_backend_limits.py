from unittest.mock import patch
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase
from django.urls import reverse

from archive.models import ToolInstance, ToolSession
from config.rate_limit import client_ip, is_layered_rate_limited


User = get_user_model()


class LayeredThrottleTests(TestCase):
    def test_ip_user_and_logical_session_buckets_are_enforced(self):
        user = User.objects.create_user(email='layers@example.com', password='testpass123')
        request = RequestFactory().get('/', REMOTE_ADDR='192.0.2.10')
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.save()
        request.user = user
        kwargs = {
            'ip_limit': 1, 'user_limit': 1, 'session_limit': 1,
            'session_id': 'workshop-1', 'window_seconds': 60,
            'lockout_seconds': 60,
        }
        self.assertFalse(is_layered_rate_limited(request, 'test-layers', **kwargs))
        self.assertTrue(is_layered_rate_limited(request, 'test-layers', **kwargs))

    def test_public_origin_cannot_spoof_forwarded_address(self):
        request = RequestFactory().get(
            '/', REMOTE_ADDR='203.0.113.8',
            HTTP_X_FORWARDED_FOR='198.51.100.20',
        )
        self.assertEqual(client_ip(request), '203.0.113.8')

    def test_trusted_proxy_uses_appended_address_not_spoofed_prefix(self):
        request = RequestFactory().get(
            '/', REMOTE_ADDR='127.0.0.1',
            HTTP_X_FORWARDED_FOR='spoofed, 198.51.100.20',
        )
        self.assertEqual(client_ip(request), '198.51.100.20')

    @patch(
        'config.rate_limit.settings.RATE_LIMIT_TRUSTED_PROXY_NETWORKS',
        ('127.0.0.0/8', '10.0.0.0/8'),
    )
    def test_trusted_multi_hop_chain_returns_first_untrusted_address(self):
        request = RequestFactory().get(
            '/', REMOTE_ADDR='127.0.0.1',
            HTTP_X_FORWARDED_FOR='invalid, 198.51.100.20, 10.1.2.3',
        )
        self.assertEqual(client_ip(request), '198.51.100.20')


class HostingCapTests(TestCase):
    def setUp(self):
        self.host = User.objects.create_user(
            email='caps-host@example.com', password='testpass123',
        )
        self.session = ToolSession.objects.create(
            host=self.host, tool_slug='wise-crowds', tool_version='1.0',
        )

    @patch('tools.views.MAX_SESSION_PARTICIPANTS', 1)
    def test_guest_join_cap_is_checked_before_insert(self):
        ToolInstance.objects.create(
            session=self.session, user=self.host, tool_slug='wise-crowds',
            tool_version='1.0',
        )
        response = self.client.post(
            reverse('tools:guest_join', args=[self.session.id, self.session.guest_token]),
            {'guest_name': 'Extra guest'},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(ToolInstance.objects.filter(session=self.session).count(), 1)

    @patch('tools.views.MAX_ACTIVE_SESSIONS_PER_USER', 1)
    def test_active_session_cap_prevents_creation(self):
        self.client.force_login(self.host)
        response = self.client.post(
            reverse('tools:session_create', args=['wise-crowds']),
        )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(ToolSession.objects.filter(host=self.host).count(), 1)

    @patch('tools.views.MAX_REQUEST_PAYLOAD_BYTES', 10)
    def test_buffer_rejects_oversized_payload_before_parsing(self):
        ToolInstance.objects.create(
            session=self.session, user=self.host, tool_slug='wise-crowds',
            tool_version='1.0',
        )
        self.client.force_login(self.host)
        response = self.client.post(
            reverse('tools:session_buffer_save', args=[self.session.id]),
            data='{"form_data":{"answer":"too long"}}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 413)

    def test_status_supports_conditional_requests(self):
        self.client.force_login(self.host)
        url = reverse('tools:session_status', args=[self.session.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        conditional = self.client.get(url, HTTP_IF_NONE_MATCH=response['ETag'])
        self.assertEqual(conditional.status_code, 304)

    def test_closed_session_cannot_enroll_authenticated_invitee(self):
        invitee = User.objects.create_user(
            email='late-invitee@example.com', password='testpass123',
        )
        self.session.status = 'closed'
        self.session.save(update_fields=['status'])
        self.client.force_login(invitee)
        response = self.client.get(
            reverse('tools:session_detail', args=[self.session.id]),
            {'t': self.session.guest_token},
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            ToolInstance.objects.filter(session=self.session, user=invitee).exists()
        )

    def test_close_committing_during_authenticated_join_prevents_enrollment(self):
        invitee = User.objects.create_user(
            email='racing-invitee@example.com', password='testpass123',
        )
        locked_session = ToolSession.objects.get(pk=self.session.pk)
        locked_session.status = 'closed'
        self.client.force_login(invitee)
        with patch(
            'tools.views.ToolSession.objects.select_for_update'
        ) as select_for_update:
            select_for_update.return_value.get.return_value = locked_session
            response = self.client.get(
                reverse('tools:session_detail', args=[self.session.id]),
                {'t': self.session.guest_token},
            )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            ToolInstance.objects.filter(session=self.session, user=invitee).exists()
        )

    def test_closed_session_guest_post_is_handled_without_creating_participant(self):
        self.session.status = 'closed'
        self.session.save(update_fields=['status'])
        response = self.client.post(
            reverse('tools:guest_join', args=[self.session.id, self.session.guest_token]),
            {'guest_name': 'Late guest'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            ToolInstance.objects.filter(
                session=self.session, guest_name='Late guest',
            ).exists()
        )

    def test_attachment_upload_requires_valid_content_length(self):
        request = RequestFactory().post(
            reverse('tools:session_attachment_upload', args=[self.session.id]),
            data=b'chunked multipart body',
            content_type='multipart/form-data; boundary=test',
        )
        request.META.pop('CONTENT_LENGTH', None)
        request.user = self.host
        from tools.views import session_attachment_upload
        response = session_attachment_upload(request, self.session.id)
        self.assertEqual(response.status_code, 411)

    @patch('tools.views.run_export_pipeline')
    @patch('tools.views.get_tool_instance')
    def test_solo_export_budget_blocks_work_before_pipeline(
        self, get_tool_instance, run_export_pipeline,
    ):
        get_tool_instance.return_value = SimpleNamespace(execute=lambda: {'ok': True})
        self.client.force_login(self.host)
        statuses = []
        for index in range(7):
            instance = ToolInstance.objects.create(
                user=self.host,
                tool_slug='wise-crowds',
                tool_version='1.0',
                status='draft',
            )
            response = self.client.post(
                reverse('tools:submit', args=[instance.id]),
            )
            statuses.append(response.status_code)

        self.assertEqual(statuses[:6], [302] * 6)
        self.assertEqual(statuses[6], 429)
        self.assertEqual(run_export_pipeline.call_count, 6)

    @patch('tools.views.MAX_ATTACHMENTS_PER_PARTICIPANT', 1)
    def test_attachment_count_cap_is_checked_before_storage_upload(self):
        ToolInstance.objects.create(
            session=self.session, user=self.host, tool_slug='wise-crowds',
            tool_version='1.0',
            attachments=[{
                'type': 'image', 'name': 'existing.png', 'url': 'https://example.invalid',
                'public_id': 'existing', 'size': 4,
            }],
        )
        self.client.force_login(self.host)
        response = self.client.post(
            reverse('tools:session_attachment_upload', args=[self.session.id]),
            {'file': SimpleUploadedFile('new.png', b'png', content_type='image/png')},
        )
        self.assertEqual(response.status_code, 409)