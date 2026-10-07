"""
Integration tests for public abuse controls (Task #124).

Covers:
- Login POSTs are throttled per client IP: after the attempt budget is
  exceeded, further POSTs are rejected with 429 without evaluating
  credentials (i.e. even a correct password fails once locked out).
- The feature-request public form is throttled per client IP so a bot cannot
  flood the endpoint indefinitely.
- The feature-request description field has a server-side length cap.
"""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from accounts.views import LOGIN_MAX_ATTEMPTS
from archive.models import FeatureRequest
from archive.views import PUBLIC_FORM_MAX_ATTEMPTS

User = get_user_model()


class TestLoginRateLimiting(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="rl-user@example.com", password="correct-horse-battery",
        )

    def setUp(self):
        cache.clear()
        self.url = reverse("accounts:login")

    def test_wrong_password_does_not_lock_out_within_budget(self):
        for _ in range(LOGIN_MAX_ATTEMPTS):
            response = self.client.post(
                self.url,
                {"username": "rl-user@example.com", "password": "wrong"},
            )
            self.assertEqual(response.status_code, 200)

    def test_exceeding_budget_locks_out_even_correct_credentials(self):
        for _ in range(LOGIN_MAX_ATTEMPTS + 1):
            self.client.post(
                self.url,
                {"username": "rl-user@example.com", "password": "wrong"},
            )

        response = self.client.post(
            self.url,
            {"username": "rl-user@example.com", "password": "correct-horse-battery"},
        )
        self.assertEqual(response.status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_lockout_is_scoped_per_client_ip(self):
        for _ in range(LOGIN_MAX_ATTEMPTS + 1):
            self.client.post(
                self.url,
                {"username": "rl-user@example.com", "password": "wrong"},
                REMOTE_ADDR="10.0.0.1",
            )
        locked_out = self.client.post(
            self.url,
            {"username": "rl-user@example.com", "password": "wrong"},
            REMOTE_ADDR="10.0.0.1",
        )
        self.assertEqual(locked_out.status_code, 429)

        still_allowed = self.client.post(
            self.url,
            {"username": "rl-user@example.com", "password": "correct-horse-battery"},
            REMOTE_ADDR="10.0.0.2",
        )
        self.assertEqual(still_allowed.status_code, 302)


class TestFeatureRequestRateLimiting(TestCase):
    def setUp(self):
        cache.clear()
        self.url = reverse("feature_request")

    def _payload(self, suffix):
        return {
            "title": f"Idea {suffix}",
            "description": "Some helpful description of the idea.",
        }

    def test_submissions_within_budget_succeed(self):
        for i in range(PUBLIC_FORM_MAX_ATTEMPTS):
            response = self.client.post(self.url, self._payload(i))
            self.assertEqual(response.status_code, 302)
        self.assertEqual(FeatureRequest.objects.count(), PUBLIC_FORM_MAX_ATTEMPTS)

    def test_exceeding_budget_is_rejected_and_not_persisted(self):
        for i in range(PUBLIC_FORM_MAX_ATTEMPTS):
            self.client.post(self.url, self._payload(f"a{i}"))

        response = self.client.post(self.url, self._payload("overflow"))
        self.assertEqual(response.status_code, 429)
        self.assertFalse(
            FeatureRequest.objects.filter(title="Idea overflow").exists()
        )

    def test_description_has_a_server_side_length_cap(self):
        from archive.forms import FeatureRequestForm

        huge_description = "x" * 5000
        form = FeatureRequestForm(data={
            "title": "Too long",
            "description": huge_description,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("description", form.errors)
