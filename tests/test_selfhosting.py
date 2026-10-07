import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from archive.assets import delete_attachment_asset
from archive.models import ToolInstance, ToolSession


@override_settings(BILLING_ENABLED=False)
class FreeSelfHostedTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email='selfhost@example.com', password='selfhost-test-passphrase',
        )

    def test_free_account_has_full_access_without_subscription(self):
        self.assertEqual(self.user.plan, 'free')
        self.assertEqual(self.user.subscription_status, 'none')
        self.client.force_login(self.user)
        for name in ('tools:catalog', 'archive:knowledge_bank', 'accounts:profile'):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, 'Choose a plan')

    def test_public_pages_have_no_pricing_links_or_prices(self):
        for name in ('home', 'about', 'accessibility', 'accounts:signup', 'accounts:login', 'self_hosting'):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, '/pricing/')
            self.assertNotContains(response, '£5')
        self.assertRedirects(self.client.get(reverse('pricing')), reverse('self_hosting'), status_code=301)

    @override_settings(KWACART_SOURCE_URL='https://example.org/my-kwacart-source')
    def test_instance_can_offer_its_own_corresponding_source(self):
        response = self.client.get(reverse('self_hosting'))
        self.assertContains(response, 'https://example.org/my-kwacart-source', count=2)
        self.assertContains(response, 'Source code (AGPL v3)')

    @patch('accounts.views.create_checkout_session')
    def test_checkout_cannot_create_a_charge(self, checkout):
        self.client.force_login(self.user)
        response = self.client.get(reverse('accounts:checkout'), {'plan': 'solo', 'interval': 'month'})
        self.assertEqual(response.status_code, 404)
        checkout.assert_not_called()

    def test_registration_ignores_legacy_plan_query(self):
        self.client.get(reverse('accounts:signup'), {'plan': 'solo', 'interval': 'month'})
        response = self.client.post(reverse('accounts:signup'), {
            'email': 'new-selfhost@example.com',
            'password1': 'A-long-selfhost-passphrase-867!',
            'password2': 'A-long-selfhost-passphrase-867!',
        })
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('checkout', response.url)
        self.assertTrue(get_user_model().objects.get(email='new-selfhost@example.com').has_paid_access)

    @override_settings(STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    })
    @patch('cloudinary.uploader.upload')
    def test_attachment_upload_and_cleanup_need_no_cloud_service(self, cloud_upload):
        session = ToolSession.objects.create(
            tool_slug='min-specs', host=self.user, status='open',
        )
        instance = ToolInstance.objects.create(session=session, user=self.user)
        self.client.force_login(self.user)
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            response = self.client.post(
                reverse('tools:session_attachment_upload', kwargs={'session_id': session.pk}),
                {'file': SimpleUploadedFile('recording.webm', b'local-recording', content_type='audio/webm')},
            )
            self.assertEqual(response.status_code, 200, response.content)
            entry = response.json()
            cloud_upload.assert_not_called()
            self.assertTrue((Path(directory) / entry['storage_name']).is_file())
            instance.refresh_from_db()
            self.assertEqual(instance.attachments[0]['storage_name'], entry['storage_name'])
            self.assertFalse(delete_attachment_asset(entry, 'another-session'))
            self.assertTrue(delete_attachment_asset(entry, session.pk))
            self.assertFalse((Path(directory) / entry['storage_name']).exists())
