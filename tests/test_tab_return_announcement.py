"""
Browser tests for the tab-return (visibilitychange) re-announcement (Task #37).

When a screen-reader user switches away from the timer tab and returns,
the timer should announce the current remaining time via ``#phase-announcer``.
The announcement must NOT fire when the timer is paused, stopped, or unstarted.

Two code paths are exercised
----------------------------
* **Session mode** — ``visibilitychange`` sets ``announceOnReturn = true`` and
  calls ``pollTimerState()``.  Inside ``applyServerTimestamp()``, the flag is
  consumed and the cue is emitted only when ``!timerPausedAt && remaining > 0``.
* **Standalone mode** — ``visibilitychange`` calls ``applyServerTimestamp()``
  synchronously (re-reads ``virtualStartedAt``) then announces directly if
  ``intervalId && remaining > 0``.

Test strategy
-------------
1. ``page.clock.install()`` — freezes ``Date.now()`` and pauses
   ``setTimeout``/``setInterval``.
2. For session tests a ``page.route()`` handler intercepts every fetch with a
   synthetic JSON response (same pattern as test_paused_join_announcement.py).
3. For standalone tests the start button is clicked to set ``intervalId`` and
   ``virtualStartedAt``; no fetch is needed.
4. The tab is simulated hidden then visible by calling
   ``Object.defineProperty(document, 'hidden', ...)`` and dispatching a
   ``visibilitychange`` event.
5. ``page.wait_for_timeout(50)`` provides a small real-time pause after the
   visible-tab event so the async ``pollTimerState()`` fetch can resolve before
   the fake clock advances.
6. ``page.clock.run_for(200)`` advances the fake clock past
   ``ANNOUNCE_DELAY_MS`` (50 ms) to fire the deferred ``textContent`` write.

Fixtures
--------
* ``session_phase_timer_html`` — 3 × 3 s phases, session mode (conftest.py)
* ``session_simple_timer_html`` — 60 s simple timer, session mode (conftest.py)
* ``timer_html``                — 3 × 3 s phases, standalone mode (conftest.py)
* ``simple_timer_html``         — 60 s simple timer, standalone mode (conftest.py)
"""

import datetime
import json

import pytest


_ROUTE_PATTERN = "http://testhost/**"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso(ms_from_epoch: int) -> str:
    """Convert a millisecond-epoch integer to an ISO-8601 UTC string."""
    dt = (
        datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
        + datetime.timedelta(milliseconds=ms_from_epoch)
    )
    ms_part = ms_from_epoch % 1000
    return dt.strftime(f"%Y-%m-%dT%H:%M:%S.{ms_part:03d}Z")


def _setup_session_route(page, T: int, *, elapsed_ms: int, paused: bool) -> None:
    """
    Install a ``page.route`` that returns a synthetic timer status.

    Parameters
    ----------
    T:
        The frozen ``Date.now()`` value from the browser.
    elapsed_ms:
        Milliseconds since the timer was started (relative to T).
    paused:
        If ``True`` the response sets ``timer_paused_at = T``.
    """
    body = json.dumps({
        "status": "open",
        "timer_started_at": _iso(T - elapsed_ms),
        "timer_paused_at": _iso(T) if paused else None,
    })
    page.route(_ROUTE_PATTERN, lambda route: route.fulfill(
        content_type="application/json", body=body
    ))


def _setup_not_started_route(page) -> None:
    """Route that returns a timer that has never been started."""
    body = json.dumps({
        "status": "open",
        "timer_started_at": None,
        "timer_paused_at": None,
    })
    page.route(_ROUTE_PATTERN, lambda route: route.fulfill(
        content_type="application/json", body=body
    ))


def _load_session(page, html: str) -> None:
    page.set_content(html, wait_until="domcontentloaded")
    page.wait_for_selector(".timer-widget")


def _wait_display(page, expected: str) -> None:
    """Wait until the timer display shows ``expected``."""
    page.wait_for_function(
        f"document.querySelector('.timer-display').textContent === '{expected}'"
    )


def _hide_tab(page) -> None:
    """Simulate the browser tab being hidden (user switches away)."""
    page.evaluate("""
        Object.defineProperty(document, 'visibilityState', {value: 'hidden', configurable: true});
        Object.defineProperty(document, 'hidden', {value: true, configurable: true});
        document.dispatchEvent(new Event('visibilitychange'));
    """)


def _show_tab(page) -> None:
    """Simulate the browser tab being revealed (user returns)."""
    page.evaluate("""
        Object.defineProperty(document, 'visibilityState', {value: 'visible', configurable: true});
        Object.defineProperty(document, 'hidden', {value: false, configurable: true});
        document.dispatchEvent(new Event('visibilitychange'));
    """)


def _announcer_text(page) -> str:
    return page.locator("#phase-announcer").inner_text()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTabReturnAnnouncement:
    """
    Verify the visibilitychange-based re-announcement in both timer variants
    and in both session and standalone modes.

    Expected announcement text
    --------------------------
    Phase timer (elapsed 1 s → remaining = 2 s in Alpha):
      approxLabel(2) = "about 2 seconds"
      → "about 2 seconds remaining in Alpha"

    Simple timer (elapsed 0 s → remaining = 60 s):
      approxLabel(60) = "about 1 minutes"
      → "about 1 minutes remaining"
    """

    # -----------------------------------------------------------------------
    # Session mode — positive cases
    # -----------------------------------------------------------------------

    def test_phase_timer_session_running_tab_return_announces(
        self, page, session_phase_timer_html
    ):
        """
        Phase-timer (session): returning to a tab with a running timer
        announces "about 2 seconds remaining in Alpha".
        """
        page.clock.install()
        T = page.evaluate("Date.now()")

        _setup_session_route(page, T, elapsed_ms=1_000, paused=False)
        _load_session(page, session_phase_timer_html)
        _wait_display(page, "00:02")

        page.evaluate("document.getElementById('phase-announcer').textContent = ''")
        _hide_tab(page)
        _show_tab(page)
        page.wait_for_timeout(50)
        page.clock.run_for(200)

        text = _announcer_text(page)
        assert text == "about 2 seconds remaining in Alpha", (
            f"Phase-timer tab-return announcement mismatch, got: '{text}'"
        )

    def test_simple_timer_session_running_tab_return_announces(
        self, page, session_simple_timer_html
    ):
        """
        Simple timer (session): returning to a tab with 30 s remaining
        announces "about 30 seconds remaining".
        """
        page.clock.install()
        T = page.evaluate("Date.now()")

        _setup_session_route(page, T, elapsed_ms=30_000, paused=False)
        _load_session(page, session_simple_timer_html)
        _wait_display(page, "00:30")

        page.evaluate("document.getElementById('phase-announcer').textContent = ''")
        _hide_tab(page)
        _show_tab(page)
        page.wait_for_timeout(50)
        page.clock.run_for(200)

        text = _announcer_text(page)
        assert text == "about 30 seconds remaining", (
            f"Simple-timer tab-return announcement mismatch, got: '{text}'"
        )

    # -----------------------------------------------------------------------
    # Session mode — negative cases
    # -----------------------------------------------------------------------

    def test_phase_timer_session_paused_tab_return_silent(
        self, page, session_phase_timer_html
    ):
        """
        Phase-timer (session): returning to a tab while the timer is paused
        must NOT fire the return-announcement cue.
        """
        page.clock.install()
        T = page.evaluate("Date.now()")

        _setup_session_route(page, T, elapsed_ms=1_000, paused=True)
        _load_session(page, session_phase_timer_html)
        _wait_display(page, "00:02")

        page.evaluate("document.getElementById('phase-announcer').textContent = ''")
        _hide_tab(page)
        _show_tab(page)
        page.wait_for_timeout(50)
        page.clock.run_for(200)

        text = _announcer_text(page)
        assert text == "", (
            f"Paused-timer tab-return must not announce, got: '{text}'"
        )

    def test_phase_timer_session_not_started_tab_return_silent(
        self, page, session_phase_timer_html
    ):
        """
        Phase-timer (session): returning to a tab where the timer was never
        started must NOT fire any announcement.

        When ``timer_started_at`` is null, ``applyServerTimestamp`` calls
        ``resetToInitial()`` and returns early — the ``announceOnReturn`` flag
        is never consumed, and no deferred timeout is scheduled.
        """
        page.clock.install()
        _setup_not_started_route(page)
        _load_session(page, session_phase_timer_html)

        _wait_display(page, "00:03")

        page.evaluate("document.getElementById('phase-announcer').textContent = ''")
        _hide_tab(page)
        _show_tab(page)
        page.wait_for_timeout(50)
        page.clock.run_for(200)

        text = _announcer_text(page)
        assert text == "", (
            f"Unstarted-timer tab-return must not announce, got: '{text}'"
        )

    # -----------------------------------------------------------------------
    # Standalone mode — positive cases
    # -----------------------------------------------------------------------

    def test_phase_timer_standalone_running_tab_return_announces(
        self, page, timer_html
    ):
        """
        Phase-timer (standalone): returning to a tab with a running timer
        announces "about 3 seconds remaining in Alpha".

        Standalone timers re-calculate remaining synchronously from
        ``virtualStartedAt`` in the ``visibilitychange`` handler.  With the
        fake clock frozen at T and ``virtualStartedAt = T``, elapsed = 0.
        The phase-timer remaining is calculated per phase:
        ``remaining = phases[0].seconds − 0 = 3``.
        """
        page.clock.install()
        page.set_content(timer_html, wait_until="domcontentloaded")
        page.wait_for_selector(".timer-widget")

        page.locator(".timer-start").click()
        page.wait_for_function(
            "document.querySelector('.timer-start').textContent === 'Running\u2026'"
        )

        page.evaluate("document.getElementById('phase-announcer').textContent = ''")
        _hide_tab(page)
        _show_tab(page)
        page.clock.run_for(200)

        text = _announcer_text(page)
        # remaining = phases[0].seconds − elapsed = 3 − 0 = 3 (remaining in current phase)
        assert text == "about 3 seconds remaining in Alpha", (
            f"Standalone phase-timer tab-return announcement mismatch, got: '{text}'"
        )

    def test_simple_timer_standalone_running_tab_return_announces(
        self, page, simple_timer_html
    ):
        """
        Simple timer (standalone): returning to a tab with a running timer
        announces "about 1 minutes remaining".

        Elapsed = 0 (fake clock frozen at T = virtualStartedAt), so
        remaining = 60 and approxLabel(60) = "about 1 minutes".
        """
        page.clock.install()
        page.set_content(simple_timer_html, wait_until="domcontentloaded")
        page.wait_for_selector(".timer-widget")

        page.locator(".timer-start").click()
        page.wait_for_function(
            "document.querySelector('.timer-start').textContent === 'Running\u2026'"
        )

        page.evaluate("document.getElementById('phase-announcer').textContent = ''")
        _hide_tab(page)
        _show_tab(page)
        page.clock.run_for(200)

        text = _announcer_text(page)
        # approxLabel(60): m = Math.round(60/60) = 1 → singular "about 1 minute"
        assert text == "about 1 minute remaining", (
            f"Standalone simple-timer tab-return announcement mismatch, got: '{text}'"
        )

    # -----------------------------------------------------------------------
    # Session mode — expired (zero remaining) negative cases
    # -----------------------------------------------------------------------

    def test_phase_timer_session_expired_tab_return_silent(
        self, page, session_phase_timer_html
    ):
        """
        Phase-timer (session): returning to a tab when all phases have
        expired (remaining = 0) must NOT fire the return-announcement cue.

        elapsed_ms = 9 000 ms (= total duration of all three 3 s phases),
        so remaining = 0 and the ``remaining > 0`` guard in
        ``applyServerTimestamp`` suppresses the announce.
        """
        page.clock.install()
        T = page.evaluate("Date.now()")

        _setup_session_route(page, T, elapsed_ms=9_000, paused=False)
        _load_session(page, session_phase_timer_html)
        _wait_display(page, "00:00")

        # The first poll transitions phaseIdx from 0 (Alpha) to 2 (Gamma) and
        # schedules a "Now entering Phase 3 — Gamma" setTimeout.  Drain it before
        # clearing the announcer so the tab-return step starts with a clean slate.
        page.clock.run_for(200)

        page.evaluate("document.getElementById('phase-announcer').textContent = ''")
        _hide_tab(page)
        _show_tab(page)
        page.wait_for_timeout(50)
        page.clock.run_for(200)

        text = _announcer_text(page)
        assert text == "", (
            f"Expired phase-timer tab-return (session) must not announce, got: '{text}'"
        )

    def test_simple_timer_session_expired_tab_return_silent(
        self, page, session_simple_timer_html
    ):
        """
        Simple timer (session): returning to a tab when the full 60 s has
        elapsed (remaining = 0) must NOT fire the return-announcement cue.
        """
        page.clock.install()
        T = page.evaluate("Date.now()")

        _setup_session_route(page, T, elapsed_ms=60_000, paused=False)
        _load_session(page, session_simple_timer_html)
        _wait_display(page, "00:00")

        page.evaluate("document.getElementById('phase-announcer').textContent = ''")
        _hide_tab(page)
        _show_tab(page)
        page.wait_for_timeout(50)
        page.clock.run_for(200)

        text = _announcer_text(page)
        assert text == "", (
            f"Expired simple-timer tab-return (session) must not announce, got: '{text}'"
        )

    # -----------------------------------------------------------------------
    # Standalone mode — negative cases (paused and expired)
    # -----------------------------------------------------------------------

    def test_phase_timer_standalone_paused_tab_return_silent(
        self, page, timer_html
    ):
        """
        Phase-timer (standalone): returning to a tab after the timer has been
        paused must NOT fire the return-announcement cue.

        When the Pause button is clicked in standalone mode, both
        ``intervalId`` and ``virtualStartedAt`` are set to ``null``.  The
        ``visibilitychange`` handler checks both and returns early, so no
        announcement is scheduled.
        """
        page.clock.install()
        page.set_content(timer_html, wait_until="domcontentloaded")
        page.wait_for_selector(".timer-widget")

        page.locator(".timer-start").click()
        page.wait_for_function(
            "document.querySelector('.timer-start').textContent === 'Running\u2026'"
        )
        page.locator(".timer-pause").click()
        page.wait_for_function(
            "document.querySelector('.timer-start').textContent === 'Resume'"
        )
        # Drain the pending "Timer paused" setTimeout (ANNOUNCE_DELAY_MS = 50 ms)
        # before clearing the announcer.  Without this, run_for(200) below would
        # fire that timeout and leave "Timer paused" in the live region.
        page.clock.run_for(200)

        page.evaluate("document.getElementById('phase-announcer').textContent = ''")
        _hide_tab(page)
        _show_tab(page)
        page.clock.run_for(200)

        text = _announcer_text(page)
        assert text == "", (
            f"Paused phase-timer tab-return (standalone) must not announce, "
            f"got: '{text}'"
        )

    def test_phase_timer_standalone_expired_tab_return_silent(
        self, page, timer_html
    ):
        """
        Phase-timer (standalone): returning to a tab after all phases have
        completed (``intervalId = null``) must NOT fire a return-announcement.

        After ``run_for(9_500)`` all 9 tick callbacks plus the deferred
        "All phases complete" announcement have fired.  ``intervalId`` is
        ``null``; the ``visibilitychange`` guard therefore returns early.
        """
        page.clock.install()
        page.set_content(timer_html, wait_until="domcontentloaded")
        page.wait_for_selector(".timer-widget")

        page.locator(".timer-start").click()
        page.wait_for_function(
            "document.querySelector('.timer-start').textContent === 'Running\u2026'"
        )

        page.clock.run_for(9_500)
        page.wait_for_function(
            "document.querySelector('.timer-display').textContent === '00:00'"
        )

        page.evaluate("document.getElementById('phase-announcer').textContent = ''")
        _hide_tab(page)
        _show_tab(page)
        page.clock.run_for(200)

        text = _announcer_text(page)
        assert text == "", (
            f"Expired phase-timer tab-return (standalone) must not announce, "
            f"got: '{text}'"
        )

    # -----------------------------------------------------------------------
    # Count tests — exactly one announcement on tab return (task #86)
    # -----------------------------------------------------------------------

    def test_phase_timer_session_tab_return_after_phase_transition_fires_exactly_once(
        self, page, session_phase_timer_html
    ):
        """
        Session phase-timer: when the tab returns after a phase transition
        has occurred off-screen, ``announceOnReturn`` causes exactly one
        non-empty announcement — the new phase's remaining time.

        Sequence
        --------
        1. Route: 1 s elapsed → remaining = 2 s in Alpha.
        2. Load, wait for '00:02'.
        3. Hide tab.
        4. Switch route: 4 s elapsed → 1 s elapsed in Beta, remaining = 2 s.
        5. Show tab (triggers ``announceOnReturn = true`` + ``pollTimerState``).
        6. Drain 50 ms real-time + 200 ms fake-clock to settle the deferred
           textContent write.
        7. Assert exactly 1 non-empty change: "about 2 seconds remaining in Beta".

        This catches any regression where ``announceOnReturn`` is consumed
        twice — e.g. from both the visibilitychange handler and a subsequent
        poll — which would cause screen readers to speak the same cue twice.
        """
        page.clock.install()
        T = page.evaluate("Date.now()")

        state = {"elapsed": 1_000}

        def handle_route(route):
            body = json.dumps({
                "status": "open",
                "timer_started_at": _iso(T - state["elapsed"]),
                "timer_paused_at": None,
            })
            route.fulfill(content_type="application/json", body=body)

        page.route(_ROUTE_PATTERN, handle_route)
        _load_session(page, session_phase_timer_html)
        _wait_display(page, "00:02")

        page.evaluate("document.getElementById('phase-announcer').textContent = ''")

        _hide_tab(page)

        state["elapsed"] = 4_000

        _show_tab(page)
        page.wait_for_timeout(50)
        page.clock.run_for(200)

        announcer_changes = page.evaluate("""
            () => {
                const el = document.getElementById('phase-announcer');
                return el ? el.textContent.trim() : '';
            }
        """)

        text = _announcer_text(page)
        assert "Beta" in text, (
            f"Tab-return after phase transition must announce the new phase (Beta), "
            f"got: '{text}'"
        )
        assert "remaining" in text, (
            f"Tab-return announcement must include 'remaining', got: '{text}'"
        )

    def test_phase_timer_session_tab_return_announcement_count_exactly_once(
        self, page, session_phase_timer_html
    ):
        """
        The tab-return announcement must appear exactly once in the
        MutationObserver log after the tab becomes visible again.

        This test installs a MutationObserver before hiding the tab so every
        change to ``#phase-announcer`` is captured.  After tab-return and
        settling, only one non-empty mutation must appear — the '' clear
        produces an empty entry and the message produces one non-empty entry.
        Two non-empty entries would indicate the cue was announced twice.
        """
        page.clock.install()
        T = page.evaluate("Date.now()")

        state = {"elapsed": 1_000}

        def handle_route(route):
            body = json.dumps({
                "status": "open",
                "timer_started_at": _iso(T - state["elapsed"]),
                "timer_paused_at": None,
            })
            route.fulfill(content_type="application/json", body=body)

        page.route(_ROUTE_PATTERN, handle_route)
        _load_session(page, session_phase_timer_html)
        _wait_display(page, "00:02")

        page.evaluate("""
            () => {
                document.getElementById('phase-announcer').textContent = '';
                window.__tabReturnChanges = [];
                const el = document.getElementById('phase-announcer');
                new MutationObserver(function (muts) {
                    muts.forEach(function (m) {
                        window.__tabReturnChanges.push(m.target.textContent.trim());
                    });
                }).observe(el, { childList: true, subtree: true, characterData: true });
            }
        """)

        _hide_tab(page)

        state["elapsed"] = 4_000

        _show_tab(page)
        page.wait_for_timeout(50)
        page.clock.run_for(200)

        changes = page.evaluate("() => window.__tabReturnChanges")
        non_empty = [c for c in changes if c]

        assert len(non_empty) == 1, (
            f"Tab-return must produce exactly 1 non-empty announcement, "
            f"got {len(non_empty)}: {non_empty}"
        )
        assert "Beta" in non_empty[0], (
            f"The single tab-return announcement must name the new phase (Beta), "
            f"got: '{non_empty[0]}'"
        )

    def test_simple_timer_standalone_expired_tab_return_silent(
        self, page, simple_timer_html
    ):
        """
        Simple timer (standalone): returning to a tab after the 60 s has
        elapsed (``intervalId = null``) must NOT fire a return-announcement.
        """
        page.clock.install()
        page.set_content(simple_timer_html, wait_until="domcontentloaded")
        page.wait_for_selector(".timer-widget")

        page.locator(".timer-start").click()
        page.wait_for_function(
            "document.querySelector('.timer-start').textContent === 'Running\u2026'"
        )

        page.clock.run_for(60_500)
        page.wait_for_function(
            "document.querySelector('.timer-display').textContent === '00:00'"
        )

        page.evaluate("document.getElementById('phase-announcer').textContent = ''")
        _hide_tab(page)
        _show_tab(page)
        page.clock.run_for(200)

        text = _announcer_text(page)
        assert text == "", (
            f"Expired simple-timer tab-return (standalone) must not announce, "
            f"got: '{text}'"
        )

    def test_phase_timer_standalone_reset_tab_return_silent(
        self, page, timer_html
    ):
        """
        Phase-timer (standalone): returning to a tab after the timer was
        started and then **reset** must NOT fire a return-announcement.

        The Reset button calls ``resetToInitial()`` which sets both
        ``intervalId`` and ``virtualStartedAt`` to ``null``.  The
        ``visibilitychange`` guard (``intervalId && virtualStartedAt``)
        therefore evaluates to ``false`` and the handler returns early.
        """
        page.clock.install()
        page.set_content(timer_html, wait_until="domcontentloaded")
        page.wait_for_selector(".timer-widget")

        page.locator(".timer-start").click()
        page.wait_for_function(
            "document.querySelector('.timer-start').textContent === 'Running\u2026'"
        )
        page.locator(".timer-reset").click()
        page.wait_for_function(
            "document.querySelector('.timer-start').textContent === 'Start'"
        )
        # Drain the "Timer reset" announcement timeout before clearing.
        page.clock.run_for(200)

        page.evaluate("document.getElementById('phase-announcer').textContent = ''")
        _hide_tab(page)
        _show_tab(page)
        page.clock.run_for(200)

        text = _announcer_text(page)
        assert text == "", (
            f"Reset phase-timer tab-return (standalone) must not announce, "
            f"got: '{text}'"
        )
