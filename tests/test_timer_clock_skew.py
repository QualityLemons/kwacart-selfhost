"""
Browser tests for clock-skew correction in the timer widget.

Both the multi-phase and simple timer variants track a ``clockSkew`` value
(milliseconds) computed from ``server_now`` on the first successful poll::

    clockSkew = new Date(data.server_now).getTime() - Date.now();

``applyServerTimestamp`` then uses ``Date.now() + clockSkew`` as the
reference time so elapsed-time calculations reflect the *server* clock even
when the client clock differs.

Test strategy
-------------
1. ``page.clock.install()`` freezes ``Date.now()`` (and pauses
   ``setInterval`` / ``setTimeout``) at the current real system time.
2. ``page.evaluate("Date.now()")`` reads the exact frozen value (``T``).
3. ``page.route()`` intercepts the status-poll fetch and returns a
   synthetic response built from ``T``:
   - *with-skew* tests:   ``server_now = T + SKEW``, ``timer_started_at``
     set so that server-elapsed == the target duration.
   - *no-server_now* tests: same ``timer_started_at`` but the ``server_now``
     field is omitted, so ``clockSkew`` stays 0 and ``referenceTime ==
     Date.now() == T``.
4. Because timers are paused, ``setInterval(tick, 1000)`` never fires and
   the display remains stable after the poll — no race conditions.

The pre-rendered HTML fixtures include a ``<base href="http://testhost/">``
tag so the relative poll URL resolves to an absolute URL that
``page.route()`` can intercept.  No live Django server is needed.
"""

import datetime
import json

import pytest


_ROUTE_PATTERN = "http://testhost/**"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso(ms_from_epoch: int) -> str:
    """Convert an integer ms-from-epoch value to an ISO-8601 UTC string.

    The output is formatted as ``YYYY-MM-DDTHH:MM:SS.mmmZ`` — the same
    shape that Django's ``timezone.now().isoformat()`` produces, plus a
    trailing 'Z' suffix so it is accepted by the JS ``new Date(...)``
    constructor.
    """
    dt = (
        datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
        + datetime.timedelta(milliseconds=ms_from_epoch)
    )
    ms_part = ms_from_epoch % 1000
    return dt.strftime(f"%Y-%m-%dT%H:%M:%S.{ms_part:03d}Z")


def _setup(page, html, *, elapsed_ms: int, skew_ms: int = 0):
    """
    Full test setup:

    1. Install the fake clock (pauses timers, freezes Date.now()).
    2. Read the frozen Date.now() value ``T`` from the browser.
    3. Compute ``timer_started_at`` and (if ``skew_ms != 0``) ``server_now``
       relative to ``T`` so elapsed and clock-skew are exact.
    4. Install a route that answers every poll with the fake response.
    5. Load the timer HTML.
    """
    page.clock.install()
    T = page.evaluate("Date.now()")

    server_now_ms = T + skew_ms
    timer_started_at_ms = server_now_ms - elapsed_ms

    data: dict = {
        "status": "open",
        "timer_started_at": _iso(timer_started_at_ms),
        "timer_paused_at": None,
    }
    if skew_ms:
        data["server_now"] = _iso(server_now_ms)

    body = json.dumps(data)
    page.route(_ROUTE_PATTERN, lambda route: route.fulfill(
        content_type="application/json", body=body
    ))

    page.set_content(html, wait_until="domcontentloaded")
    # wait_for_selector ensures the JS has initialised the widget before
    # the test begins querying .timer-display text or advancing the clock.
    page.wait_for_selector(".timer-widget")


# ---------------------------------------------------------------------------
# Phase-timer tests  (3 × 3 s = 9 s total, phases: Alpha / Beta / Gamma)
# ---------------------------------------------------------------------------

class TestPhaseTimerClockSkew:
    """
    Skew scenario for the phase timer
    ----------------------------------
    * Server is 3 s ahead of client  (skew_ms = +3 000)
    * Timer started 5 server-seconds ago  (elapsed_ms = 5 000)
    * ``referenceTime = Date.now() + clockSkew = T + 3 000``
    * ``elapsedSec = floor((T + 3 000 − (T + 3 000 − 5 000)) / 1 000) = 5 s``
    * Phase 0 = Alpha (0–3 s), Phase 1 = Beta (3–6 s): at 5 s → Beta
    Without skew correction (no server_now):
    * ``referenceTime = T``
    * ``elapsedSec = floor((T − (T − 2 000)) / 1 000) = 2 s`` → Alpha
    """

    def test_skew_corrects_phase_position(self, page, session_phase_timer_html):
        """Clock-skew correction advances the displayed phase from Alpha to Beta."""
        _setup(page, session_phase_timer_html, elapsed_ms=5_000, skew_ms=3_000)

        page.wait_for_function(
            "document.querySelector('.timer-phase-label').textContent === 'Beta'"
        )

        label = page.locator(".timer-phase-label").inner_text()
        assert label == "Beta", (
            f"Expected 'Beta' with +3 s clock skew (server elapsed = 5 s), got '{label}'"
        )

    def test_no_server_now_uses_client_clock(self, page, session_phase_timer_html):
        """Without server_now, clockSkew = 0; client elapsed = 2 s → phase Alpha."""
        _setup(page, session_phase_timer_html, elapsed_ms=2_000, skew_ms=0)

        page.wait_for_function(
            "document.querySelector('.timer-display').textContent === '00:01'"
        )

        label = page.locator(".timer-phase-label").inner_text()
        assert label == "Alpha", (
            f"Expected 'Alpha' (no clock skew, client elapsed = 2 s), got '{label}'"
        )


# ---------------------------------------------------------------------------
# Simple-timer tests  (60 s, no phases)
# ---------------------------------------------------------------------------

class TestSimpleTimerClockSkew:
    """
    Skew scenario for the simple timer
    ------------------------------------
    * Server is 10 s ahead of client  (skew_ms = +10 000)
    * Timer started 20 server-seconds ago  (elapsed_ms = 20 000)
    * ``referenceTime = T + 10 000``
    * ``elapsedSec = floor((T + 10 000 − (T + 10 000 − 20 000)) / 1 000) = 20 s``
    * ``remaining = max(0, 60 − 20) = 40 s`` → display '00:40'
    Without skew correction (no server_now):
    * ``referenceTime = T``
    * ``elapsedSec = floor((T − (T − 10 000)) / 1 000) = 10 s``
    * ``remaining = max(0, 60 − 10) = 50 s`` → display '00:50'
    """

    def test_skew_corrects_remaining_time(self, page, session_simple_timer_html):
        """Clock-skew correction shows 40 s remaining instead of 50 s."""
        _setup(page, session_simple_timer_html, elapsed_ms=20_000, skew_ms=10_000)

        page.wait_for_function(
            "document.querySelector('.timer-display').textContent === '00:40'"
        )

        display = page.locator(".timer-display").inner_text()
        assert display == "00:40", (
            f"Expected '00:40' with +10 s clock skew (server elapsed = 20 s), got '{display}'"
        )

    def test_no_server_now_uses_client_clock(self, page, session_simple_timer_html):
        """Without server_now, clockSkew = 0; client elapsed = 10 s → '00:50'."""
        _setup(page, session_simple_timer_html, elapsed_ms=10_000, skew_ms=0)

        page.wait_for_function(
            "document.querySelector('.timer-display').textContent === '00:50'"
        )

        display = page.locator(".timer-display").inner_text()
        assert display == "00:50", (
            f"Expected '00:50' (no clock skew, client elapsed = 10 s), got '{display}'"
        )


# ---------------------------------------------------------------------------
# Re-measurement tests  — verify skew is updated on *every* poll
# ---------------------------------------------------------------------------

class TestClockSkewUpdatedEachPoll:
    """
    Verify that ``clockSkew`` is re-measured on every successful poll, not
    just the first.  This matters for tabs that are left open across a laptop
    sleep or mobile background: the first poll sets an initial skew, but
    subsequent polls must keep it fresh.

    Scenario (simple timer, 60 s)
    --------------------------------
    * First poll  (at fake time T):
        server_now = T + 10 000  →  clockSkew = +10 000
        timer_started_at = T − 10 000  →  elapsed = 20 s  →  remaining = 40 s
    * Clock advances 4 s (four ticks fire): remaining 40 → 36
    * Second poll fires at T + 4 000:
        server_now = T + 4 000  →  clockSkew is now re-measured to 0
        timer_started_at = T + 4 000 − 10 000 = T − 6 000  →  elapsed = 10 s
        →  remaining = 50 s  →  display '00:50'
    The jump from 36 s to 50 s proves clockSkew was updated on the second poll.
    """

    def test_skew_remeasured_on_second_poll(self, page, session_simple_timer_html):
        """Second poll updates clockSkew; remaining jumps from 36 s to 50 s."""
        page.clock.install()
        T = page.evaluate("Date.now()")

        # A mutable list is used instead of a plain variable so the inner
        # lambda/def can read and update the value without a nonlocal
        # declaration (nonlocal is not available to lambdas in Python).
        call_count = [0]

        def _handler(route):
            call_count[0] += 1
            if call_count[0] == 1:
                body = json.dumps({
                    "status": "open",
                    "timer_started_at": _iso(T - 10_000),
                    "timer_paused_at": None,
                    "server_now": _iso(T + 10_000),
                })
            else:
                body = json.dumps({
                    "status": "open",
                    "timer_started_at": _iso(T - 6_000),
                    "timer_paused_at": None,
                    "server_now": _iso(T + 4_000),
                })
            route.fulfill(content_type="application/json", body=body)

        page.route(_ROUTE_PATTERN, _handler)
        page.set_content(session_simple_timer_html, wait_until="domcontentloaded")
        page.wait_for_selector(".timer-widget")

        page.wait_for_function(
            "document.querySelector('.timer-display').textContent === '00:40'"
        )

        page.clock.run_for(4_000)

        page.wait_for_function(
            "document.querySelector('.timer-display').textContent === '00:50'"
        )

        display = page.locator(".timer-display").inner_text()
        assert display == "00:50", (
            f"Expected '00:50' after second poll re-measured clockSkew to 0, "
            f"got '{display}'"
        )


# ---------------------------------------------------------------------------
# Long-sleep wake-up tests  — visibilitychange triggers re-sync
# ---------------------------------------------------------------------------

class TestLongSleepWakeup:
    """
    Verify the full tab wake-up path after a long idle.

    When a browser tab has been sleeping (e.g. laptop closed for 30 minutes),
    the ``visibilitychange`` handler fires ``pollTimerState()`` the moment the
    tab becomes visible again.  That poll re-measures ``clockSkew`` from the
    updated ``server_now`` field and calls ``applyServerTimestamp``, so the
    display jumps to the server-correct position rather than the stale
    client-side value.

    Simulation technique
    --------------------
    The client clock is frozen with ``page.clock.install()`` (``Date.now()``
    stays at ``T`` throughout the test).  To simulate 30 minutes of server
    time having passed without advancing the client clock, the wake-up poll's
    ``server_now`` field is set to ``T + SLEEP_MS + skew``.  Because
    ``clockSkew = server_now − Date.now()`` and ``Date.now() = T``, the
    timer widget re-measures ``clockSkew = SLEEP_MS + skew``.
    ``applyServerTimestamp`` then computes::

        referenceTime = Date.now() + clockSkew
                      = T + (SLEEP_MS + skew)
                      = server_now

    which equals the *server*'s current time — exactly as in a real wake-up.

    Test coverage
    -------------
    * Phase timer: initial poll → Alpha phase; wake-up poll → Gamma phase.
    * Simple timer: initial poll → 50 s remaining; wake-up poll → 10 s remaining.
    * Both confirm that a stale (initial) clockSkew would give the *wrong*
      answer, so the assertion only passes because the skew was re-measured.
    """

    _SLEEP_MS = 30 * 60 * 1_000  # 30 minutes in ms

    def test_phase_timer_wakeup_resyncs_to_server_position(
        self, page, session_phase_timer_html
    ):
        """
        Phase timer: initial poll places timer in Alpha (1 s elapsed, server
        2 s ahead of client).  After the ``visibilitychange`` wake event the
        wake-up poll shows 7 s elapsed server-side → timer must re-sync to
        Gamma phase.

        Without re-measuring clockSkew the widget would use the stale
        skew (+2 000 ms) and compute elapsed ≈ 0 s → Alpha — proving that
        only a fresh skew measurement gives the correct answer.
        """
        page.clock.install()
        T = page.evaluate("Date.now()")

        call_count = [0]

        def _handler(route):
            call_count[0] += 1
            if call_count[0] == 1:
                # Initial: server 2 s ahead, 1 s elapsed → Alpha
                data = {
                    "status": "open",
                    "timer_started_at": _iso(T + 2_000 - 1_000),
                    "timer_paused_at": None,
                    "server_now": _iso(T + 2_000),
                }
            else:
                # Wake-up: server 30 min + 2 s ahead, 7 s elapsed → Gamma
                data = {
                    "status": "open",
                    "timer_started_at": _iso(T + self._SLEEP_MS + 2_000 - 7_000),
                    "timer_paused_at": None,
                    "server_now": _iso(T + self._SLEEP_MS + 2_000),
                }
            route.fulfill(content_type="application/json", body=json.dumps(data))

        page.route(_ROUTE_PATTERN, _handler)
        page.set_content(session_phase_timer_html, wait_until="domcontentloaded")
        page.wait_for_selector(".timer-widget")

        # Initial poll must show Phase Alpha.
        page.wait_for_function(
            "document.querySelector('.timer-phase-label').textContent === 'Alpha'"
        )

        # Simulate tab becoming visible (wake event).
        page.evaluate("""
            Object.defineProperty(document, 'hidden', {
                get: () => false, configurable: true
            });
            document.dispatchEvent(new Event('visibilitychange'));
        """)

        # Wake-up poll re-measures clockSkew; 7 s elapsed → Gamma.
        page.wait_for_function(
            "document.querySelector('.timer-phase-label').textContent === 'Gamma'"
        )

        label = page.locator(".timer-phase-label").inner_text()
        assert label == "Gamma", (
            f"Expected phase 'Gamma' after wake-up re-sync "
            f"(7 s server-elapsed), got '{label}'"
        )

    def test_simple_timer_wakeup_resyncs_to_server_position(
        self, page, session_simple_timer_html
    ):
        """
        Simple timer (60 s): initial poll shows 50 s remaining (server 5 s
        ahead, 10 s elapsed).  After the ``visibilitychange`` wake event the
        wake-up poll shows 50 s elapsed → display must jump to '00:10'.

        With the stale clockSkew (+5 000 ms) ``referenceTime`` would be
        ``T + 5 000``; elapsed would still be 10 s → '00:50', not '00:10'.
        Only the re-measured skew produces the correct answer.
        """
        page.clock.install()
        T = page.evaluate("Date.now()")

        call_count = [0]

        def _handler(route):
            call_count[0] += 1
            if call_count[0] == 1:
                # Initial: server 5 s ahead, 10 s elapsed → 50 s remaining
                data = {
                    "status": "open",
                    "timer_started_at": _iso(T + 5_000 - 10_000),
                    "timer_paused_at": None,
                    "server_now": _iso(T + 5_000),
                }
            else:
                # Wake-up: server 30 min + 5 s ahead, 50 s elapsed → 10 s remaining
                data = {
                    "status": "open",
                    "timer_started_at": _iso(T + self._SLEEP_MS + 5_000 - 50_000),
                    "timer_paused_at": None,
                    "server_now": _iso(T + self._SLEEP_MS + 5_000),
                }
            route.fulfill(content_type="application/json", body=json.dumps(data))

        page.route(_ROUTE_PATTERN, _handler)
        page.set_content(session_simple_timer_html, wait_until="domcontentloaded")
        page.wait_for_selector(".timer-widget")

        # Initial poll shows 50 s remaining.
        page.wait_for_function(
            "document.querySelector('.timer-display').textContent === '00:50'"
        )

        # Simulate tab becoming visible (wake event).
        page.evaluate("""
            Object.defineProperty(document, 'hidden', {
                get: () => false, configurable: true
            });
            document.dispatchEvent(new Event('visibilitychange'));
        """)

        # Wake-up poll re-measures clockSkew; 50 s elapsed → 10 s remaining.
        page.wait_for_function(
            "document.querySelector('.timer-display').textContent === '00:10'"
        )

        display = page.locator(".timer-display").inner_text()
        assert display == "00:10", (
            f"Expected '00:10' after wake-up re-sync (50 s server-elapsed), "
            f"got '{display}'"
        )

    def test_wakeup_after_clock_advance_resyncs_correctly(
        self, page, session_simple_timer_html
    ):
        """
        Verify the wake-up path when ``page.clock.run_for()`` explicitly
        advances ``Date.now()`` before the ``visibilitychange`` fires.

        A paused timer is used so that no tick callbacks fire during the
        clock advance — only the polling ``setInterval`` callbacks fire,
        all returning the same paused response so the display stays frozen.
        After 30 s of fake time the wake event fires with a *resumed* server
        response; the display must jump to the server-correct position.

        Scenario (simple timer, 60 s)
        --------------------------------
        * T = frozen Date.now().
        * Poll 1 (on load): paused, 10 s elapsed → '00:50'.
          ``server_now = T``, ``timer_paused_at = T``.
        * ``page.clock.run_for(30 000)`` → Date.now() = T + 30 000.
          Interval fires ~7 times; all polls return the paused response;
          display stays frozen at '00:50'.
        * Wake event → resumed poll:
          ``server_now = T + 35 000`` (server 5 s ahead of new Date.now()),
          40 s elapsed server-side → remaining = 20 s → display '00:20'.
        """
        page.clock.install()
        T = page.evaluate("Date.now()")

        _ADVANCE_MS = 30_000  # 30 seconds — triggers ~7 poll intervals
        mode = ["paused"]

        def _handler(route):
            if mode[0] == "paused":
                # Timer paused 10 s after start → 50 s remaining.
                data = {
                    "status": "open",
                    "timer_started_at": _iso(T - 10_000),
                    "timer_paused_at": _iso(T),
                    "server_now": _iso(T),
                }
            else:
                # Wake-up: timer resumed; Date.now() is now T + _ADVANCE_MS.
                # server_now = T + _ADVANCE_MS + 5 000 → clockSkew = 5 000.
                # timer_started_at = server_now - 40 000 → elapsed = 40 s.
                data = {
                    "status": "open",
                    "timer_started_at": _iso(T + _ADVANCE_MS + 5_000 - 40_000),
                    "timer_paused_at": None,
                    "server_now": _iso(T + _ADVANCE_MS + 5_000),
                }
            route.fulfill(content_type="application/json", body=json.dumps(data))

        page.route(_ROUTE_PATTERN, _handler)
        page.set_content(session_simple_timer_html, wait_until="domcontentloaded")
        page.wait_for_selector(".timer-widget")

        # Initial poll: paused at 10 s → '00:50'.
        page.wait_for_function(
            "document.querySelector('.timer-display').textContent === '00:50'"
        )

        # Advance fake clock 30 s — Date.now() moves to T + 30 000.
        # Polling interval fires ~7 times; all get the paused response.
        page.clock.run_for(_ADVANCE_MS)
        page.wait_for_timeout(100)

        # Display must still be '00:50': paused timer does not drift.
        assert page.locator(".timer-display").inner_text() == "00:50", (
            "Paused timer display must not change while the clock advances"
        )

        # Switch to resumed response, then fire wake event.
        mode[0] = "resumed"
        page.evaluate("""
            Object.defineProperty(document, 'hidden', {
                get: () => false, configurable: true
            });
            document.dispatchEvent(new Event('visibilitychange'));
        """)

        # Wake-up poll: server 5 s ahead of new Date.now(), 40 s elapsed
        # → 20 s remaining → display '00:20'.
        page.wait_for_function(
            "document.querySelector('.timer-display').textContent === '00:20'"
        )

        display = page.locator(".timer-display").inner_text()
        assert display == "00:20", (
            f"Expected '00:20' after wake-up re-sync with clock advance "
            f"(40 s server-elapsed, Date.now() advanced 30 s), got '{display}'"
        )

    def test_phase_timer_wakeup_shows_expired_state(
        self, page, session_phase_timer_html
    ):
        """
        Phase timer (3 × 3 s = 9 s total): after waking up the tab the
        wake-up poll reports elapsed >= total (all 9 s consumed server-side).

        Expected outcome:
        - Display shows '00:00'.
        - Last phase (Gamma) is active and carries the ``expired`` CSS class.
        - The interval has been cleared — the display remains frozen at '00:00'
          after a short wait, confirming the tick loop is not still running.
        """
        page.clock.install()
        T = page.evaluate("Date.now()")

        call_count = [0]

        def _handler(route):
            call_count[0] += 1
            if call_count[0] == 1:
                # Initial: server 2 s ahead, 1 s elapsed → Alpha, 2 s remaining
                data = {
                    "status": "open",
                    "timer_started_at": _iso(T + 2_000 - 1_000),
                    "timer_paused_at": None,
                    "server_now": _iso(T + 2_000),
                }
            else:
                # Wake-up: all 9 s have elapsed server-side (elapsed >= total)
                data = {
                    "status": "open",
                    "timer_started_at": _iso(T + self._SLEEP_MS + 2_000 - 9_000),
                    "timer_paused_at": None,
                    "server_now": _iso(T + self._SLEEP_MS + 2_000),
                }
            route.fulfill(content_type="application/json", body=json.dumps(data))

        page.route(_ROUTE_PATTERN, _handler)
        page.set_content(session_phase_timer_html, wait_until="domcontentloaded")
        page.wait_for_selector(".timer-widget")

        # Initial poll must show Phase Alpha.
        page.wait_for_function(
            "document.querySelector('.timer-phase-label').textContent === 'Alpha'"
        )

        # Simulate tab becoming visible (wake event).
        page.evaluate("""
            Object.defineProperty(document, 'hidden', {
                get: () => false, configurable: true
            });
            document.dispatchEvent(new Event('visibilitychange'));
        """)

        # Wake-up poll: all phases consumed → Gamma expired, display '00:00'.
        page.wait_for_function(
            "document.querySelector('.timer-display').textContent === '00:00'"
        )

        display = page.locator(".timer-display")
        assert display.inner_text() == "00:00", (
            "Expected '00:00' after wake-up with all 9 s elapsed"
        )

        label = page.locator(".timer-phase-label").inner_text()
        assert label == "Gamma", (
            f"Expected last phase 'Gamma' to be active after expiry, got '{label}'"
        )

        assert display.evaluate("el => el.classList.contains('expired')"), (
            "Expected '.timer-display' to carry the 'expired' CSS class after "
            "elapsed >= total on wake-up"
        )

        # Let a couple of seconds pass (fake time) and confirm the display
        # does not change — the tick interval must have been cleared.
        page.clock.run_for(3_000)
        page.wait_for_timeout(100)
        assert display.inner_text() == "00:00", (
            "Timer display changed after expiry — tick interval was not cleared"
        )

    def test_simple_timer_wakeup_shows_expired_state(
        self, page, session_simple_timer_html
    ):
        """
        Simple timer (60 s): after waking up the tab the wake-up poll reports
        elapsed > total (65 s consumed server-side, well past the 60 s limit).

        Expected outcome:
        - Display shows '00:00'.
        - ``.timer-display`` carries the ``expired`` CSS class.
        - The interval has been cleared — the display remains frozen at '00:00'
          after a short wait, confirming the tick loop is not still running.
        """
        page.clock.install()
        T = page.evaluate("Date.now()")

        call_count = [0]

        def _handler(route):
            call_count[0] += 1
            if call_count[0] == 1:
                # Initial: server 5 s ahead, 10 s elapsed → 50 s remaining
                data = {
                    "status": "open",
                    "timer_started_at": _iso(T + 5_000 - 10_000),
                    "timer_paused_at": None,
                    "server_now": _iso(T + 5_000),
                }
            else:
                # Wake-up: 65 s elapsed (> 60 s total) → remaining = 0
                data = {
                    "status": "open",
                    "timer_started_at": _iso(T + self._SLEEP_MS + 5_000 - 65_000),
                    "timer_paused_at": None,
                    "server_now": _iso(T + self._SLEEP_MS + 5_000),
                }
            route.fulfill(content_type="application/json", body=json.dumps(data))

        page.route(_ROUTE_PATTERN, _handler)
        page.set_content(session_simple_timer_html, wait_until="domcontentloaded")
        page.wait_for_selector(".timer-widget")

        # Initial poll shows 50 s remaining.
        page.wait_for_function(
            "document.querySelector('.timer-display').textContent === '00:50'"
        )

        # Simulate tab becoming visible (wake event).
        page.evaluate("""
            Object.defineProperty(document, 'hidden', {
                get: () => false, configurable: true
            });
            document.dispatchEvent(new Event('visibilitychange'));
        """)

        # Wake-up poll: 65 s elapsed → remaining = 0 → display '00:00'.
        page.wait_for_function(
            "document.querySelector('.timer-display').textContent === '00:00'"
        )

        display = page.locator(".timer-display")
        assert display.inner_text() == "00:00", (
            "Expected '00:00' after wake-up with 65 s elapsed on a 60 s timer"
        )

        assert display.evaluate("el => el.classList.contains('expired')"), (
            "Expected '.timer-display' to carry the 'expired' CSS class after "
            "elapsed > total on wake-up"
        )

        # Let a couple of seconds pass (fake time) and confirm the display
        # does not change — the tick interval must have been cleared.
        page.clock.run_for(3_000)
        page.wait_for_timeout(100)
        assert display.inner_text() == "00:00", (
            "Timer display changed after expiry — tick interval was not cleared"
        )

    def test_phase_timer_wakeup_announces_expiry_to_screen_reader(
        self, page, session_phase_timer_html
    ):
        """
        Phase timer (3 × 3 s = 9 s total): after a long-sleep wake-up poll
        returns elapsed >= total, the aria-live region (#phase-announcer) must
        receive the text 'All phases complete' so screen-reader users know the
        timer has ended.

        The announce() helper uses a 50 ms setTimeout (ANNOUNCE_DELAY_MS) that
        is under the fake clock's control; the test advances the fake clock by
        100 ms to allow that callback to fire.
        """
        page.clock.install()
        T = page.evaluate("Date.now()")

        call_count = [0]

        def _handler(route):
            call_count[0] += 1
            if call_count[0] == 1:
                # Initial: server 2 s ahead, 1 s elapsed → Alpha, 2 s remaining
                data = {
                    "status": "open",
                    "timer_started_at": _iso(T + 2_000 - 1_000),
                    "timer_paused_at": None,
                    "server_now": _iso(T + 2_000),
                }
            else:
                # Wake-up: all 9 s have elapsed server-side (elapsed >= total)
                data = {
                    "status": "open",
                    "timer_started_at": _iso(T + self._SLEEP_MS + 2_000 - 9_000),
                    "timer_paused_at": None,
                    "server_now": _iso(T + self._SLEEP_MS + 2_000),
                }
            route.fulfill(content_type="application/json", body=json.dumps(data))

        page.route(_ROUTE_PATTERN, _handler)
        page.set_content(session_phase_timer_html, wait_until="domcontentloaded")
        page.wait_for_selector(".timer-widget")

        # Initial poll must show Phase Alpha.
        page.wait_for_function(
            "document.querySelector('.timer-phase-label').textContent === 'Alpha'"
        )

        # Simulate tab becoming visible (wake event).
        page.evaluate("""
            Object.defineProperty(document, 'hidden', {
                get: () => false, configurable: true
            });
            document.dispatchEvent(new Event('visibilitychange'));
        """)

        # Wait for the display to reach '00:00' before checking the announcer.
        page.wait_for_function(
            "document.querySelector('.timer-display').textContent === '00:00'"
        )

        # Advance the fake clock past ANNOUNCE_DELAY_MS (50 ms) so that the
        # setTimeout inside announce() fires and populates #phase-announcer.
        page.clock.run_for(100)
        page.wait_for_timeout(50)

        announcer_text = page.locator("#phase-announcer").inner_text()
        assert announcer_text == "All phases complete", (
            f"Expected aria-live region to contain 'All phases complete' after "
            f"wake-up expiry, got '{announcer_text}'"
        )

    def test_simple_timer_wakeup_announces_expiry_to_screen_reader(
        self, page, session_simple_timer_html
    ):
        """
        Simple timer (60 s): after a long-sleep wake-up poll returns elapsed
        > total, the aria-live region (#phase-announcer) must receive the text
        'Timer complete' so screen-reader users know the timer has ended.

        The announce() helper uses a 50 ms setTimeout (ANNOUNCE_DELAY_MS) that
        is under the fake clock's control; the test advances the fake clock by
        100 ms to allow that callback to fire.
        """
        page.clock.install()
        T = page.evaluate("Date.now()")

        call_count = [0]

        def _handler(route):
            call_count[0] += 1
            if call_count[0] == 1:
                # Initial: server 5 s ahead, 10 s elapsed → 50 s remaining
                data = {
                    "status": "open",
                    "timer_started_at": _iso(T + 5_000 - 10_000),
                    "timer_paused_at": None,
                    "server_now": _iso(T + 5_000),
                }
            else:
                # Wake-up: 65 s elapsed (> 60 s total) → remaining = 0
                data = {
                    "status": "open",
                    "timer_started_at": _iso(T + self._SLEEP_MS + 5_000 - 65_000),
                    "timer_paused_at": None,
                    "server_now": _iso(T + self._SLEEP_MS + 5_000),
                }
            route.fulfill(content_type="application/json", body=json.dumps(data))

        page.route(_ROUTE_PATTERN, _handler)
        page.set_content(session_simple_timer_html, wait_until="domcontentloaded")
        page.wait_for_selector(".timer-widget")

        # Initial poll shows 50 s remaining.
        page.wait_for_function(
            "document.querySelector('.timer-display').textContent === '00:50'"
        )

        # Simulate tab becoming visible (wake event).
        page.evaluate("""
            Object.defineProperty(document, 'hidden', {
                get: () => false, configurable: true
            });
            document.dispatchEvent(new Event('visibilitychange'));
        """)

        # Wait for the display to reach '00:00' before checking the announcer.
        page.wait_for_function(
            "document.querySelector('.timer-display').textContent === '00:00'"
        )

        # Advance the fake clock past ANNOUNCE_DELAY_MS (50 ms) so that the
        # setTimeout inside announce() fires and populates #phase-announcer.
        page.clock.run_for(100)
        page.wait_for_timeout(50)

        announcer_text = page.locator("#phase-announcer").inner_text()
        assert announcer_text == "Timer complete", (
            f"Expected aria-live region to contain 'Timer complete' after "
            f"wake-up expiry, got '{announcer_text}'"
        )
