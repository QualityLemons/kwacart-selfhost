"""
Browser tests for the reconnection toast (Task #46).

When session-mode polling fails three consecutive times the ``.timer-stale-badge``
appears.  When polling recovers (next successful response) the stale badge hides
and ``.timer-reconnect-toast`` is shown briefly, then auto-hidden after 4 seconds.

Behaviour under test
--------------------
* ``setStaleIndicator(true)``  — called when ``pollFailCount >= POLL_FAIL_THRESHOLD (3)``
* ``setStaleIndicator(false)`` — called on next successful poll; if ``_wasStale`` is
  set it triggers ``showReconnectToast()``
* ``showReconnectToast()``     — reveals ``.timer-reconnect-toast``, schedules a 4000 ms
  setTimeout to hide it again

The element carries ``role="status"`` and ``aria-live="polite"`` so screen readers
announce the text "✓ Reconnected — syncing timer" automatically when it appears.

Test strategy
-------------
1. ``page.clock.install()`` — freeze ``Date.now()`` and pause ``setTimeout``/
   ``setInterval`` so poll intervals do not fire spontaneously.
2. A mutable ``mode`` list is shared with a ``page.route()`` handler so the test
   can switch from error responses to success responses mid-test.
3. The initial ``pollTimerState()`` call (fired on page load) counts as failure #1.
   Two ``page.clock.run_for(4100)`` calls advance through failures #2 and #3.
4. Switching ``mode`` to ``'succeed'`` and advancing one more interval triggers the
   recovery poll that shows the toast.
5. A final ``page.clock.run_for(4100)`` fires the 4000 ms hide-timeout.

All session tests use ``session_phase_timer_html`` or ``session_simple_timer_html``
(from conftest.py) which have a ``<base href="http://testhost/">`` tag so relative
poll URLs resolve to something ``page.route("http://testhost/**")`` can intercept.

Fixtures
--------
* ``session_phase_timer_html`` — 3 × 3 s phases, session mode
* ``session_simple_timer_html`` — 60 s simple timer, session mode
"""

import json

import pytest


_ROUTE_PATTERN = "http://testhost/**"
_SUCCESS_BODY = json.dumps(
    {"status": "open", "timer_started_at": None, "timer_paused_at": None, "server_now": None}
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_session(page, html: str) -> None:
    page.set_content(html, wait_until="domcontentloaded")
    page.wait_for_selector(".timer-widget")


def _install_fail_then_succeed_route(page, mode: list) -> None:
    """
    Install a route handler whose behaviour is governed by ``mode[0]``.

    When ``mode[0] == 'fail'``   → return HTTP 500 with a non-JSON body so
                                    ``fetch().then(r => r.json())`` throws and the
                                    ``catch`` block increments ``pollFailCount``.
    When ``mode[0] == 'succeed'`` → return a valid JSON status response so
                                    ``pollFailCount`` resets to 0 and
                                    ``setStaleIndicator(false)`` fires.
    """
    def handler(route):
        if mode[0] == "fail":
            # Return a non-JSON 500 response so that ``response.json()``
            # throws inside the widget's fetch handler and the ``catch``
            # block increments ``pollFailCount``.
            route.fulfill(status=500, content_type="text/plain", body="error")
        else:
            route.fulfill(content_type="application/json", body=_SUCCESS_BODY)

    page.route(_ROUTE_PATTERN, handler)


def _drive_to_stale(page, mode: list) -> None:
    """
    Advance the clock through the three poll failures needed to set
    ``_wasStale = true`` via ``setStaleIndicator(true)``.

    Timeline
    --------
    * Page load:  immediate ``pollTimerState()`` → error → pollFailCount = 1
    * +8100 ms:   second poll (backoff <= 8 s)  → error → pollFailCount = 2
    * +16100 ms:  third poll (backoff <= 16 s) → error → pollFailCount = 3
                  → ``setStaleIndicator(true)`` → stale badge visible
    """
    # Allow the immediately-invoked first poll to complete.
    # 50 ms is enough for the fetch() promise chain to resolve/reject even
    # with a fake clock because page.wait_for_timeout uses real-world time.
    page.wait_for_timeout(50)
    # Second poll.
    page.clock.run_for(8100)
    page.wait_for_timeout(50)
    # Third poll — crosses POLL_FAIL_THRESHOLD, triggering setStaleIndicator(true).
    page.clock.run_for(16100)
    page.wait_for_timeout(50)
    # Guard: ensure the stale badge is actually visible before proceeding.
    page.wait_for_function(
        "!document.querySelector('.timer-stale-badge').hasAttribute('hidden')"
    )


def _drive_recovery(page, mode: list) -> None:
    """
    Switch to success responses then advance the current backoff interval so
    ``setStaleIndicator(false)`` fires and the toast appears.
    """
    mode[0] = "succeed"
    page.clock.run_for(32100)
    page.wait_for_timeout(50)
    page.wait_for_function(
        "!document.querySelector('.timer-reconnect-toast').hasAttribute('hidden')"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestReconnectToast:
    """Reconnection toast — visibility, content, ARIA, and auto-hide behaviour."""

    # ------------------------------------------------------------------
    # Phase timer (session mode)
    # ------------------------------------------------------------------

    def test_stale_badge_appears_after_three_poll_failures(
        self, page, session_phase_timer_html
    ):
        """
        The ``.timer-stale-badge`` element must become visible after three
        consecutive poll failures (``pollFailCount >= POLL_FAIL_THRESHOLD``).
        """
        page.clock.install()
        mode = ["fail"]
        _install_fail_then_succeed_route(page, mode)
        _load_session(page, session_phase_timer_html)

        _drive_to_stale(page, mode)

        assert page.locator(".timer-stale-badge").is_visible(), (
            "Expected .timer-stale-badge to be visible after 3 poll failures"
        )

    def test_stale_badge_clears_on_recovery(
        self, page, session_phase_timer_html
    ):
        """
        After a successful poll that follows a stale period the
        ``.timer-stale-badge`` must be hidden again.
        """
        page.clock.install()
        mode = ["fail"]
        _install_fail_then_succeed_route(page, mode)
        _load_session(page, session_phase_timer_html)

        _drive_to_stale(page, mode)
        _drive_recovery(page, mode)

        assert not page.locator(".timer-stale-badge").is_visible(), (
            "Expected .timer-stale-badge to be hidden after successful poll recovery"
        )

    def test_reconnect_toast_appears_after_recovery(
        self, page, session_phase_timer_html
    ):
        """
        ``.timer-reconnect-toast`` must become visible immediately after the
        first successful poll following a stale period.
        """
        page.clock.install()
        mode = ["fail"]
        _install_fail_then_succeed_route(page, mode)
        _load_session(page, session_phase_timer_html)

        _drive_to_stale(page, mode)
        _drive_recovery(page, mode)

        assert page.locator(".timer-reconnect-toast").is_visible(), (
            "Expected .timer-reconnect-toast to be visible after poll recovery"
        )

    def test_reconnect_toast_text(
        self, page, session_phase_timer_html
    ):
        """
        The toast must display the exact text "✓ Reconnected — syncing timer".
        """
        page.clock.install()
        mode = ["fail"]
        _install_fail_then_succeed_route(page, mode)
        _load_session(page, session_phase_timer_html)

        _drive_to_stale(page, mode)
        _drive_recovery(page, mode)

        text = page.locator(".timer-reconnect-toast").inner_text()
        expected = "\u2713 Reconnected \u2014 syncing timer"
        assert text == expected, (
            f"Expected toast text '{expected}', got '{text}'"
        )

    def test_reconnect_toast_aria_role(
        self, page, session_phase_timer_html
    ):
        """
        ``.timer-reconnect-toast`` must carry ``role="status"`` so that
        screen readers announce its content when it appears.
        """
        page.clock.install()
        mode = ["fail"]
        _install_fail_then_succeed_route(page, mode)
        _load_session(page, session_phase_timer_html)

        _drive_to_stale(page, mode)
        _drive_recovery(page, mode)

        role = page.locator(".timer-reconnect-toast").get_attribute("role")
        assert role == "status", (
            f"Expected role='status' on .timer-reconnect-toast, got '{role}'"
        )

    def test_reconnect_toast_aria_live(
        self, page, session_phase_timer_html
    ):
        """
        ``.timer-reconnect-toast`` must carry ``aria-live="polite"`` so the
        text is announced by screen readers without interrupting the user.
        """
        page.clock.install()
        mode = ["fail"]
        _install_fail_then_succeed_route(page, mode)
        _load_session(page, session_phase_timer_html)

        _drive_to_stale(page, mode)
        _drive_recovery(page, mode)

        aria_live = page.locator(".timer-reconnect-toast").get_attribute("aria-live")
        assert aria_live == "polite", (
            f"Expected aria-live='polite' on .timer-reconnect-toast, got '{aria_live}'"
        )

    def test_reconnect_toast_autohides_after_four_seconds(
        self, page, session_phase_timer_html
    ):
        """
        The toast must hide itself after ~4 000 ms (the setTimeout in
        ``showReconnectToast``).  Advancing the fake clock 4 100 ms past
        the moment the toast appeared must leave it hidden.
        """
        page.clock.install()
        mode = ["fail"]
        _install_fail_then_succeed_route(page, mode)
        _load_session(page, session_phase_timer_html)

        _drive_to_stale(page, mode)
        _drive_recovery(page, mode)

        # Toast is visible here; advance past its 4000 ms hide-timeout.
        page.clock.run_for(4100)
        page.wait_for_timeout(50)

        assert not page.locator(".timer-reconnect-toast").is_visible(), (
            "Expected .timer-reconnect-toast to be hidden 4 s after appearing"
        )

    def test_no_toast_without_prior_stale(
        self, page, session_phase_timer_html
    ):
        """
        If polling has never failed (``_wasStale`` is ``false``), a normal
        successful poll must NOT show the reconnect toast.
        """
        page.clock.install()
        mode = ["succeed"]
        _install_fail_then_succeed_route(page, mode)
        _load_session(page, session_phase_timer_html)

        # Wait for the initial successful poll.
        page.wait_for_timeout(50)
        # Advance one more interval for a second clean poll.
        page.clock.run_for(4100)
        page.wait_for_timeout(50)

        assert not page.locator(".timer-reconnect-toast").is_visible(), (
            "Reconnect toast must not appear when polling has never failed"
        )

    # ------------------------------------------------------------------
    # Simple timer (session mode) — verify the same mechanism works in
    # the no-phases code path
    # ------------------------------------------------------------------

    def test_reconnect_toast_appears_simple_timer(
        self, page, session_simple_timer_html
    ):
        """
        ``.timer-reconnect-toast`` must appear after recovery in the simple
        (no-phases) session-mode timer.
        """
        page.clock.install()
        mode = ["fail"]
        _install_fail_then_succeed_route(page, mode)
        _load_session(page, session_simple_timer_html)

        _drive_to_stale(page, mode)
        _drive_recovery(page, mode)

        assert page.locator(".timer-reconnect-toast").is_visible(), (
            "Expected .timer-reconnect-toast to be visible in simple-timer "
            "session mode after poll recovery"
        )

    def test_reconnect_toast_autohides_simple_timer(
        self, page, session_simple_timer_html
    ):
        """
        Simple-timer variant: toast must self-hide after 4 000 ms.
        """
        page.clock.install()
        mode = ["fail"]
        _install_fail_then_succeed_route(page, mode)
        _load_session(page, session_simple_timer_html)

        _drive_to_stale(page, mode)
        _drive_recovery(page, mode)

        page.clock.run_for(4100)
        page.wait_for_timeout(50)

        assert not page.locator(".timer-reconnect-toast").is_visible(), (
            "Expected .timer-reconnect-toast to be hidden 4 s after appearing "
            "(simple-timer session mode)"
        )
