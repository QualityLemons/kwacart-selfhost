"""
Integration tests for the session_status JSON API (tools/views.py).

Covers:
- ``server_now`` field is present in the response JSON
- ``server_now`` value is a valid ISO-8601 datetime string
- Unauthenticated requests are redirected (login_required)
- Non-participant requests receive HTTP 403

These tests use Django's test client and an in-memory SQLite database;
no browser or Playwright environment is required.
"""

import json
from datetime import datetime, timezone

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from archive.models import ToolSession

User = get_user_model()

# wise-crowds has both a tool class and a session model definition — a safe
# default to use in API tests that need a real tool slug.
TOOL_SLUG = "wise-crowds"
STATUS_URL_NAME = "tools:session_status"


def _iso8601_datetime(value):
    """
    Return a parsed datetime if *value* is a valid ISO-8601 string,
    otherwise raise ValueError.

    Accepts both offset-aware ('2026-04-26T14:23:01.123456+00:00') and
    naive ('2026-04-26T14:23:01.123456') variants produced by
    Django's ``timezone.now().isoformat()``.
    """
    # Python 3.7+ fromisoformat handles offset-aware strings.
    # Replace the trailing 'Z' suffix (from JavaScript's toISOString()) with
    # an explicit UTC offset so Python's parser accepts it.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TestSessionStatusServerNow(TestCase):
    """
    Confirm that the ``server_now`` field in session_status is present
    and formatted as a valid ISO-8601 datetime string.
    """

    @classmethod
    def setUpTestData(cls):
        cls.host = User.objects.create_user(
            email="status-api-host@example.com",
            password="testpassword123",
        )
        cls.session = ToolSession.objects.create(
            host=cls.host,
            tool_slug=TOOL_SLUG,
            tool_version="1.0",
        )
        cls.url = reverse(STATUS_URL_NAME, kwargs={"session_id": cls.session.id})

    def _get_status(self, user=None):
        if user is None:
            user = self.host
        self.client.force_login(user)
        return self.client.get(self.url)

    def test_server_now_is_present(self):
        response = self._get_status()
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        # assertIn with a failure message is used so that the error output
        # includes the full response dict, making it easier to diagnose
        # which keys are present when server_now is missing.
        self.assertIn(
            "server_now",
            data,
            "session_status response must include the 'server_now' key",
        )

    def test_server_now_is_iso8601(self):
        response = self._get_status()
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        raw = data.get("server_now", "")
        try:
            parsed = _iso8601_datetime(raw)
        except (ValueError, TypeError) as exc:
            self.fail(
                f"'server_now' value {raw!r} is not a valid ISO-8601 string: {exc}"
            )
        self.assertIsInstance(parsed, datetime)

    def test_server_now_is_timezone_aware(self):
        """Django's timezone.now() is UTC-aware; isoformat() must include offset."""
        response = self._get_status()
        data = json.loads(response.content)
        raw = data.get("server_now", "")
        parsed = _iso8601_datetime(raw)
        self.assertIsNotNone(
            parsed.tzinfo,
            f"'server_now' ({raw!r}) must be timezone-aware (include UTC offset)",
        )

    def test_response_includes_expected_keys(self):
        """Smoke-test that the overall response shape is intact."""
        response = self._get_status()
        data = json.loads(response.content)
        required_keys = {"status", "server_now", "timer_started_at", "participants"}
        missing = required_keys - data.keys()
        self.assertFalse(
            missing,
            f"session_status response is missing keys: {missing}",
        )


class TestSessionStatusAuth(TestCase):
    """Confirm authentication and participation guards work correctly."""

    @classmethod
    def setUpTestData(cls):
        cls.host = User.objects.create_user(
            email="status-auth-host@example.com",
            password="testpassword123",
        )
        cls.outsider = User.objects.create_user(
            email="status-auth-outsider@example.com",
            password="testpassword123",
        )
        cls.session = ToolSession.objects.create(
            host=cls.host,
            tool_slug=TOOL_SLUG,
            tool_version="1.0",
        )
        cls.url = reverse(STATUS_URL_NAME, kwargs={"session_id": cls.session.id})

    def test_unauthenticated_is_redirected(self):
        # login_required redirects to the login page.  Both 302 (temporary)
        # and 301 (permanent) are accepted because Django may use either
        # depending on the redirect middleware configuration.
        response = self.client.get(self.url)
        self.assertIn(response.status_code, (302, 301))

    def test_non_participant_receives_403(self):
        self.client.force_login(self.outsider)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_host_receives_200(self):
        self.client.force_login(self.host)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
