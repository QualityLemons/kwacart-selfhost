from django.test import TestCase
from django.urls import reverse


class PrivacyPageTests(TestCase):
    def test_privacy_page_is_public_and_careful_about_compliance_claims(self):
        response = self.client.get(reverse('privacy'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'selfhost_privacy.html')
        self.assertContains(response, 'person or organisation operating this instance')
        self.assertContains(response, 'not a formal privacy notice')
        self.assertNotContains(response, 'ISO/IEC 27001 certification')

    def test_privacy_page_describes_controls_and_questions_route(self):
        response = self.client.get(reverse('privacy'))

        self.assertContains(response, 'Organisation-retained work')
        self.assertContains(response, 'securely hashed password')
        self.assertContains(response, reverse('self_hosting'))
        self.assertContains(response, 'Ask the operator')

    def test_public_navigation_links_to_privacy_page(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, reverse('privacy'), count=2)
        self.assertContains(response, '>Privacy</a>', count=2)