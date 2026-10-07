"""Pricing, branding, and retired-waitlist regression coverage."""

from django.contrib import admin
from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, Resolver404, resolve, reverse

from archive.models import WaitingListEntry


@override_settings(BILLING_ENABLED=True)
class PricingAndBrandingTests(TestCase):
    def test_pricing_page_presents_confirmed_plans_and_savings(self):
        response = self.client.get(reverse('pricing'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Solo')
        self.assertContains(response, '£5')
        self.assertContains(response, '£50')
        self.assertContains(response, 'save £10')
        self.assertContains(response, 'Organisation')
        self.assertContains(response, '£12')
        self.assertContains(response, '£100')
        self.assertContains(response, 'save £44')
        self.assertContains(
            response,
            'Additional users from your email domain included free',
        )
        self.assertNotContains(response, '<form')

    def test_homepage_uses_prominent_serif_wordmark_and_selfhosting_link(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, 'hero-wordmark kwacart-wordmark')
        self.assertContains(response, reverse('self_hosting'))
        self.assertNotContains(response, 'waiting list')


class RetiredWaitlistTests(TestCase):
    def test_waitlist_routes_and_admin_ui_are_removed(self):
        with self.assertRaises(NoReverseMatch):
            reverse('waiting_list_signup')
        with self.assertRaises(NoReverseMatch):
            reverse('archive:waiting_list_management')
        with self.assertRaises(Resolver404):
            resolve('/waiting-list/')
        self.assertFalse(admin.site.is_registered(WaitingListEntry))

    def test_historical_waitlist_records_are_preserved(self):
        entry = WaitingListEntry.objects.create(
            email='historical@example.com',
            name='Historical record',
        )

        self.client.get(reverse('pricing'))

        self.assertTrue(WaitingListEntry.objects.filter(pk=entry.pk).exists())