"""
Browser tests for offline/online event-driven stale badge behaviour (Task #47).

The timer widget in session mode listens for the browser's ``window offline``
and ``window online`` events:

  window.addEventListener('offline', () => setStaleIndicator(true));
  window.addEventListener('online',  () => pollTimerState());

These listeners are separate from the polling-failure path: the stale badge
must appear *immediately* on ``offline`` — not only after three failed polls
(``POLL_FAIL_THRESHOLD = 3``).

Behaviour under test
--------------------
* ``offline`` event → ``.timer-stale-badge`` visible straight away (no clock
  advance, no poll failures).
* ``online`` event (after ``offline``) → recovery ``pollTimerState()`` call
  fires; on success the stale badge hides and ``.timer-reconnect-toast``
  appears (because ``_wasStale`` was set by the earlier ``offline`` event).
* The stale badge must NOT appear merely from a plain ``offline`` event in
  standalone mode (no listeners are attached outside session mode).

Test strategy
-------------
* ``page.clock.install()`` freezes ``Date.now()`` and pauses
  ``setTimeout``/``setInterval`` so no background poll intervals fire
  spontaneously during the test.
* Offline/online events are dispatched via ``page.evaluate()`` — they reach
  the same JS event listeners that a real browser network change would trigger.
* For the "immediate" assertion the test checks the DOM *before* any
  ``page.clock.run_for()`` call, proving the badge is not gated on a timer.
* For the recovery tests the route handler is switched to return success JSON
  before the ``online`` event is dispatched; ``page.wait_for_timeout(50)``
  lets the async fetch complete.

Fixtures
--------
* ``session_phase_timer_html``  — 3 × 3 s phases, session mode (conftest.py)
* ``session_simple_timer_html`` — 60 s simple timer, session mode (conftest.py)
* ``timer_html``                — 3 × 3 s phases, standalone mode (conftest.py)
"""

import json

import pytest


_ROUTE_PATTERN = "http://testhost/**"
# server_now is included but null — the widget treats null the same as a
# missing key and leaves clockSkew at 0, which is correct for these tests
# because we are not testing clock-skew compensation here.
_SUCCESS_BODY = json.dumps(
    {"status": "open", "timer_started_at": None, "timer_paused_at": None, "server_now": None}
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_session(page, html: str) -> None:
    page.set_content(html, wait_until="domcontentloaded")
    page.wait_for_selector(".timer-widget")


def _route_success(page) -> None:
    """Install a route that always returns a valid timer-status JSON response."""
    page.route(
        _ROUTE_PATTERN,
        lambda route: route.fulfill(content_type="application/json", body=_SUCCESS_BODY),
    )


def _go_offline(page) -> None:
    """Dispatch a ``window offline`` event inside the browser page.

    This triggers the widget's ``window.addEventListener('offline', ...)``
    listener, which calls ``setStaleIndicator(true)`` immediately — before
    any poll failure has occurred.
    """
    page.evaluate("window.dispatchEvent(new Event('offline'))")


def _go_online(page) -> None:
    """Dispatch a ``window online`` event inside the browser page.

    This triggers the widget's ``window.addEventListener('online', ...)``
    listener, which calls ``pollTimerState()`` immediately to attempt
    recovery after an offline period.
    """
    page.evaluate("window.dispatchEvent(new Event('online'))")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOfflineDetection:
    """Offline/online event listeners — stale badge and recovery behaviour."""

    # ------------------------------------------------------------------
    # Instant appearance on offline — phase timer
    # ------------------------------------------------------------------

    def test_offline_event_shows_stale_badge_immediately_phase_timer(
        self, page, session_phase_timer_html
    ):
        """
        Dispatching ``window offline`` must make ``.timer-stale-badge``
        visible immediately — before any clock advance and without waiting
        for three poll failures.
        """
        page.clock.install()
        _route_success(page)
        _load_session(page, session_phase_timer_html)

        # Wait for the initial success poll so the widget is fully initialised.
        page.wait_for_timeout(50)

        # No clock.run_for() — the badge must appear synchronously.
        _go_offline(page)

        assert page.locator(".timer-stale-badge").is_visible(), (
            "Expected .timer-stale-badge to be visible immediately after "
            "'offline' event, before any clock advance"
        )

    def test_offline_badge_appears_without_poll_failures_phase_timer(
        self, page, session_phase_timer_html
    ):
        """
        The stale badge must appear after a single ``offline`` event even
        though ``pollFailCount`` is still 0 (no poll has failed yet).
        This confirms the badge is driven by the event listener, not the
        failure counter.
        """
        page.clock.install()
        _route_success(page)
        _load_session(page, session_phase_timer_html)
        page.wait_for_timeout(50)

        # pollFailCount is a closure-local JS variable; confirm the badge is
        # not yet visible before the event fires (route returns success, so
        # no poll failures have accumulated).
        assert not page.locator(".timer-stale-badge").is_visible(), (
            "Stale badge must be hidden before 'offline' event fires "
            "(routing is returning success, so no failures yet)"
        )

        _go_offline(page)

        assert page.locator(".timer-stale-badge").is_visible(), (
            "Stale badge must be visible after 'offline' event, not only "
            "after three poll failures"
        )

    # ------------------------------------------------------------------
    # Instant appearance on offline — simple timer
    # ------------------------------------------------------------------

    def test_offline_event_shows_stale_badge_immediately_simple_timer(
        self, page, session_simple_timer_html
    ):
        """
        The ``offline`` event must immediately show the stale badge in the
        simple (no-phases) session-mode timer too.
        """
        page.clock.install()
        _route_success(page)
        _load_session(page, session_simple_timer_html)
        page.wait_for_timeout(50)

        _go_offline(page)

        assert page.locator(".timer-stale-badge").is_visible(), (
            "Expected .timer-stale-badge immediately after 'offline' event "
            "(simple-timer session mode)"
        )

    # ------------------------------------------------------------------
    # Standalone mode — no listeners attached, badge must stay hidden
    # ------------------------------------------------------------------

    def test_offline_event_ignored_in_standalone_mode(
        self, page, timer_html
    ):
        """
        In standalone mode (no session ID, no status-poll URL) the
        ``offline``/``online`` listeners are never attached, so the
        ``offline`` event must NOT show the stale badge.
        """
        page.clock.install()
        # Standalone mode — no route needed.
        page.set_content(timer_html, wait_until="domcontentloaded")
        page.wait_for_selector(".timer-widget")

        _go_offline(page)

        assert not page.locator(".timer-stale-badge").is_visible(), (
            "Stale badge must stay hidden in standalone mode after 'offline' event "
            "(no session listeners are attached)"
        )

    def test_offline_event_ignored_in_simple_timer_standalone_mode(
        self, page, simple_timer_html
    ):
        """
        In simple-timer standalone mode (no session ID, no status-poll URL)
        the ``offline``/``online`` listeners are never attached, so the
        ``offline`` event must NOT show the stale badge.
        """
        page.clock.install()
        # Standalone mode — no route needed.
        page.set_content(simple_timer_html, wait_until="domcontentloaded")
        page.wait_for_selector(".timer-widget")

        _go_offline(page)

        assert not page.locator(".timer-stale-badge").is_visible(), (
            "Stale badge must stay hidden in simple-timer standalone mode after "
            "'offline' event (no session listeners are attached)"
        )

    # ------------------------------------------------------------------
    # Online recovery — phase timer
    # ------------------------------------------------------------------

    def test_online_event_clears_stale_badge_phase_timer(
        self, page, session_phase_timer_html
    ):
        """
        After going offline (stale badge shown), dispatching ``window online``
        must trigger a recovery poll that clears the stale badge.
        """
        page.clock.install()
        _route_success(page)
        _load_session(page, session_phase_timer_html)
        page.wait_for_timeout(50)

        _go_offline(page)
        assert page.locator(".timer-stale-badge").is_visible(), (
            "Pre-condition: stale badge should be visible after 'offline'"
        )

        _go_online(page)
        # Give the async fetch from pollTimerState() time to complete.
        page.wait_for_timeout(100)

        assert not page.locator(".timer-stale-badge").is_visible(), (
            "Expected .timer-stale-badge to be hidden after 'online' event "
            "triggered a successful recovery poll"
        )

    def test_online_event_triggers_reconnect_toast_phase_timer(
        self, page, session_phase_timer_html
    ):
        """
        The ``online``-driven recovery poll clears ``_wasStale`` and calls
        ``showReconnectToast()``, so ``.timer-reconnect-toast`` must be
        visible after the ``online`` event fires.
        """
        page.clock.install()
        _route_success(page)
        _load_session(page, session_phase_timer_html)
        page.wait_for_timeout(50)

        _go_offline(page)
        _go_online(page)
        page.wait_for_timeout(100)

        assert page.locator(".timer-reconnect-toast").is_visible(), (
            "Expected .timer-reconnect-toast to appear after 'online' recovery poll "
            "(phase-timer session mode)"
        )

    # ------------------------------------------------------------------
    # Online recovery — simple timer
    # ------------------------------------------------------------------

    def test_online_event_clears_stale_badge_simple_timer(
        self, page, session_simple_timer_html
    ):
        """
        ``online`` recovery must also clear the stale badge in the
        simple (no-phases) session-mode timer.
        """
        page.clock.install()
        _route_success(page)
        _load_session(page, session_simple_timer_html)
        page.wait_for_timeout(50)

        _go_offline(page)
        _go_online(page)
        page.wait_for_timeout(100)

        assert not page.locator(".timer-stale-badge").is_visible(), (
            "Expected .timer-stale-badge to be hidden after online recovery "
            "(simple-timer session mode)"
        )

    def test_online_event_triggers_reconnect_toast_simple_timer(
        self, page, session_simple_timer_html
    ):
        """
        ``online`` recovery must show the reconnect toast in the simple-timer
        session-mode variant.
        """
        page.clock.install()
        _route_success(page)
        _load_session(page, session_simple_timer_html)
        page.wait_for_timeout(50)

        _go_offline(page)
        _go_online(page)
        page.wait_for_timeout(100)

        assert page.locator(".timer-reconnect-toast").is_visible(), (
            "Expected .timer-reconnect-toast after online recovery "
            "(simple-timer session mode)"
        )

    # ------------------------------------------------------------------
    # Failed recovery poll — badge must remain visible
    # ------------------------------------------------------------------

    def test_stale_badge_persists_when_recovery_poll_fails_phase_timer(
        self, page, session_phase_timer_html
    ):
        """
        If the device comes back online but the server is still unreachable,
        the recovery ``pollTimerState()`` call will throw in its catch block.
        The stale badge must remain visible because ``setStaleIndicator(false)``
        is never called on an error path.
        """
        page.clock.install()
        _route_success(page)
        _load_session(page, session_phase_timer_html)
        page.wait_for_timeout(50)

        _go_offline(page)
        assert page.locator(".timer-stale-badge").is_visible(), (
            "Pre-condition: stale badge must be visible after 'offline' event"
        )

        # Switch the route to simulate a server-side error so the recovery
        # fetch throws (non-JSON 500 body causes r.json() to reject).
        page.route(
            _ROUTE_PATTERN,
            lambda route: route.fulfill(status=500, body="Internal Server Error"),
        )

        _go_online(page)
        # Allow the async fetch to complete and fail.
        page.wait_for_timeout(100)

        assert page.locator(".timer-stale-badge").is_visible(), (
            "Expected .timer-stale-badge to remain visible after 'online' event "
            "when the recovery poll returns HTTP 500 (phase-timer session mode)"
        )

    def test_stale_badge_persists_when_recovery_poll_fails_simple_timer(
        self, page, session_simple_timer_html
    ):
        """
        Same as the phase-timer variant: a failed recovery poll on the
        simple-timer must not hide the stale badge.
        """
        page.clock.install()
        _route_success(page)
        _load_session(page, session_simple_timer_html)
        page.wait_for_timeout(50)

        _go_offline(page)
        assert page.locator(".timer-stale-badge").is_visible(), (
            "Pre-condition: stale badge must be visible after 'offline' event"
        )

        page.route(
            _ROUTE_PATTERN,
            lambda route: route.fulfill(status=500, body="Internal Server Error"),
        )

        _go_online(page)
        page.wait_for_timeout(100)

        assert page.locator(".timer-stale-badge").is_visible(), (
            "Expected .timer-stale-badge to remain visible after 'online' event "
            "when the recovery poll returns HTTP 500 (simple-timer session mode)"
        )

    def test_stale_badge_clears_after_failed_then_successful_recovery_phase_timer(
        self, page, session_phase_timer_html
    ):
        """
        Full stale → failed-recovery → successful-recovery sequence:
        1. Go offline  → badge appears.
        2. Go online while server is unreachable → badge persists.
        3. Server recovers; go online again → badge clears.
        This confirms the badge lifecycle is correct end-to-end.
        """
        page.clock.install()
        _route_success(page)
        _load_session(page, session_phase_timer_html)
        page.wait_for_timeout(50)

        # Step 1: go offline.
        _go_offline(page)
        assert page.locator(".timer-stale-badge").is_visible(), (
            "Pre-condition: stale badge must appear after 'offline'"
        )

        # Step 2: go online but server still errors — badge must stay.
        page.route(
            _ROUTE_PATTERN,
            lambda route: route.fulfill(status=500, body="Internal Server Error"),
        )
        _go_online(page)
        page.wait_for_timeout(100)
        assert page.locator(".timer-stale-badge").is_visible(), (
            "Badge must remain visible after failed recovery poll"
        )

        # Step 3: server recovers — reinstall the success route, then go online.
        _route_success(page)
        _go_online(page)
        page.wait_for_timeout(100)

        assert not page.locator(".timer-stale-badge").is_visible(), (
            "Expected .timer-stale-badge to clear after a successful recovery poll "
            "following earlier failures (phase-timer session mode)"
        )
