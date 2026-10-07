"""
Integration tests for collaboration access control (Task #122).

Covers:
- session_detail is restricted to the host and existing participants; a
  bare session URL no longer silently enrolls arbitrary authenticated users.
- A valid invite link (session UUID + guest_token as ?t=) enrolls a new
  authenticated participant into an open session, but not a closed one.
- Pairing-code brute force is throttled: after the attempt budget is
  exceeded, further guesses are rejected with 429 without hitting the DB
  lookup (i.e. even a correct code fails once locked out).
"""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from archive.models import ToolInstance, ToolSession
from tools.views import PAIRING_MAX_ATTEMPTS

User = get_user_model()

TOOL_SLUG = "wise-crowds"


class TestSessionDetailAccessControl(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.host = User.objects.create_user(
            email="sac-host@example.com", password="testpassword123",
        )
        cls.outsider = User.objects.create_user(
            email="sac-outsider@example.com", password="testpassword123",
        )
        cls.participant = User.objects.create_user(
            email="sac-participant@example.com", password="testpassword123",
        )

    def setUp(self):
        self.session = ToolSession.objects.create(
            host=self.host, tool_slug=TOOL_SLUG, tool_version="1.0",
        )
        self.url = reverse(
            "tools:session_detail", kwargs={"session_id": self.session.id}
        )

    def test_host_can_view(self):
        self.client.force_login(self.host)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_outsider_without_token_gets_404(self):
        self.client.force_login(self.outsider)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)
        # And must not have been silently enrolled as a participant.
        self.assertFalse(
            ToolInstance.objects.filter(
                session=self.session, user=self.outsider
            ).exists()
        )

    def test_outsider_with_valid_token_is_enrolled_on_open_session(self):
        self.client.force_login(self.outsider)
        response = self.client.get(self.url, {"t": str(self.session.guest_token)})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            ToolInstance.objects.filter(
                session=self.session, user=self.outsider
            ).exists()
        )

    def test_outsider_with_invalid_token_gets_404(self):
        self.client.force_login(self.outsider)
        response = self.client.get(self.url, {"t": "not-a-real-token"})
        self.assertEqual(response.status_code, 404)

    def test_existing_participant_can_revisit_without_token(self):
        ToolInstance.objects.create(
            session=self.session, user=self.participant,
            tool_slug=TOOL_SLUG, tool_version="1.0", status="draft",
        )
        self.client.force_login(self.participant)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_token_does_not_grant_access_to_closed_session(self):
        self.session.status = "closed"
        self.session.save(update_fields=["status"])
        self.client.force_login(self.outsider)
        response = self.client.get(self.url, {"t": str(self.session.guest_token)})
        self.assertEqual(response.status_code, 404)

    def test_participant_can_view_closed_session(self):
        ToolInstance.objects.create(
            session=self.session, user=self.participant,
            tool_slug=TOOL_SLUG, tool_version="1.0", status="archived",
        )
        self.session.status = "closed"
        self.session.save(update_fields=["status"])
        self.client.force_login(self.participant)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)


class TestPairingRateLimit(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.host = User.objects.create_user(
            email="pairing-host@example.com", password="testpassword123",
        )

    def setUp(self):
        cache.clear()
        self.session = ToolSession.objects.create(
            host=self.host, tool_slug=TOOL_SLUG, tool_version="1.0",
            pairing_code="123",
        )

    def tearDown(self):
        cache.clear()

    def _join(self, code):
        return self.client.get(
            reverse("pairing_join", kwargs={"code": code}),
            REMOTE_ADDR="203.0.113.5",
        )

    def test_valid_code_redirects(self):
        response = self._join("123")
        self.assertEqual(response.status_code, 302)

    def test_unknown_code_returns_404(self):
        response = self._join("999")
        self.assertEqual(response.status_code, 404)

    def test_exceeding_attempt_budget_locks_out_client(self):
        for _ in range(PAIRING_MAX_ATTEMPTS):
            response = self._join("999")
            self.assertEqual(response.status_code, 404)

        # Budget exceeded: even the *correct* code is now rejected with 429.
        response = self._join("123")
        self.assertEqual(response.status_code, 429)

    def test_lockout_is_scoped_per_client_ip(self):
        for _ in range(PAIRING_MAX_ATTEMPTS + 1):
            self.client.get(
                reverse("pairing_join", kwargs={"code": "999"}),
                REMOTE_ADDR="203.0.113.5",
            )
        # A different client IP is unaffected.
        response = self.client.get(
            reverse("pairing_join", kwargs={"code": "123"}),
            REMOTE_ADDR="203.0.113.9",
        )
        self.assertEqual(response.status_code, 302)
