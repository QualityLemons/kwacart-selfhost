"""
Browser-based tests for the simple (no-phases) timer's visibility re-sync.

When a browser tab is hidden the OS may throttle or completely suspend
setInterval callbacks.  On returning to the tab, the simple timer's
visibilitychange handler re-calculates elapsed time from `virtualStartedAt`
so the display jumps forward to the correct value instead of showing the
stale, drift-frozen reading.

These tests simulate that scenario with Playwright's fake-clock API:

  1. Start the 60-second timer and let 5 s elapse normally.
  2. Mark the tab as hidden and clear the running interval (throttle
     simulation) — the display freezes at 00:55.
  3. Advance the fake clock by 10 more seconds while hidden.
  4. Restore tab visibility — the visibilitychange handler fires
     applyServerTimestamp(virtualStartedAt), recomputing remaining from the
     wall-clock delta.
  5. Assert the display now shows 00:45 (60 − 15 s elapsed), not the frozen
     00:55.

No live Django server is required: the template is pre-rendered by the
`simple_timer_html` fixture and loaded via page.set_content().

Simulation details
------------------
Playwright's fake clock controls Date.now() and setInterval uniformly, so
we cannot naturally reproduce throttling.  Instead, after clicking Start we
wrap setInterval to capture the interval ID, then clear it explicitly before
advancing the clock.  This faithfully mimics the tab-hidden throttle: time
passes (Date.now() advances) but the tick callback does not fire.
"""

import pytest


TOTAL_SECONDS = 60


def _load_simple_timer(page, html: str) -> None:
    """Install a fake clock and load the simple-timer page."""
    page.clock.install()
    page.set_content(html, wait_until="domcontentloaded")
    page.wait_for_selector(".timer-widget")


def _display(page) -> str:
    return page.locator(".timer-display").inner_text()


def _start_button_text(page) -> str:
    return page.locator(".timer-start").inner_text()


class TestSimpleTimerVisibilityResync:
    """
    The simple timer must re-sync from virtualStartedAt when the tab
    becomes visible again after having been hidden.
    """

    def test_display_resyncs_after_tab_hidden(self, page, simple_timer_html):
        """
        Core regression check: display jumps forward on visibility restore.

        Without the visibilitychange re-sync the display would remain frozen
        at the value it held when the interval was throttled.  With re-sync
        it must reflect the true elapsed wall-clock time.
        """
        _load_simple_timer(page, simple_timer_html)

        page.evaluate("""
            () => {
                const _orig = window.setInterval;
                window.setInterval = function (fn, delay, ...rest) {
                    const id = _orig(fn, delay, ...rest);
                    window._capturedIntervalId = id;
                    return id;
                };
            }
        """)

        page.locator(".timer-start").click()

        page.clock.run_for(5_000)
        assert _display(page) == "00:55", (
            f"After 5 s the display should read 00:55, got '{_display(page)}'"
        )

        page.evaluate("""
            () => {
                Object.defineProperty(document, 'hidden', {
                    get: () => true,
                    configurable: true,
                });
                document.dispatchEvent(new Event('visibilitychange'));
            }
        """)

        page.evaluate("""
            () => {
                if (window._capturedIntervalId !== undefined) {
                    clearInterval(window._capturedIntervalId);
                }
            }
        """)

        page.clock.run_for(10_000)

        assert _display(page) == "00:55", (
            "While the tab is hidden and the interval cleared, "
            f"the display must stay frozen at 00:55, got '{_display(page)}'"
        )

        page.evaluate("""
            () => {
                Object.defineProperty(document, 'hidden', {
                    get: () => false,
                    configurable: true,
                });
                document.dispatchEvent(new Event('visibilitychange'));
            }
        """)

        assert _display(page) == "00:45", (
            "After visibility restore, the display must jump to 00:45 "
            f"(60 − 15 s elapsed), got '{_display(page)}'"
        )

    def test_start_button_stays_disabled_after_resync(self, page, simple_timer_html):
        """
        The Start button must remain in its 'Running…' / disabled state
        after the re-sync so the user cannot start a second concurrent timer.
        """
        _load_simple_timer(page, simple_timer_html)

        page.evaluate("""
            () => {
                const _orig = window.setInterval;
                window.setInterval = function (fn, delay, ...rest) {
                    const id = _orig(fn, delay, ...rest);
                    window._capturedIntervalId = id;
                    return id;
                };
            }
        """)

        page.locator(".timer-start").click()
        page.clock.run_for(5_000)

        page.evaluate("""
            () => {
                Object.defineProperty(document, 'hidden', {
                    get: () => true, configurable: true
                });
                document.dispatchEvent(new Event('visibilitychange'));
                if (window._capturedIntervalId !== undefined) {
                    clearInterval(window._capturedIntervalId);
                }
            }
        """)
        page.clock.run_for(10_000)

        page.evaluate("""
            () => {
                Object.defineProperty(document, 'hidden', {
                    get: () => false, configurable: true
                });
                document.dispatchEvent(new Event('visibilitychange'));
            }
        """)

        start_btn = page.locator(".timer-start")
        assert start_btn.is_disabled(), (
            "Start button must still be disabled after visibility re-sync"
        )

    def test_expires_cleanly_on_tab_return_after_full_countdown(self, page, simple_timer_html):
        """
        Edge case: the tab returns *after* the full 60 s countdown has elapsed
        while hidden.

        The visibilitychange handler must call applyServerTimestamp, which
        should set the display to 00:00, re-enable the Start button (clearing
        the stale interval reference), and fire the 'Timer complete'
        announcement exactly once.
        """
        _load_simple_timer(page, simple_timer_html)

        page.evaluate("""
            () => {
                const _orig = window.setInterval;
                window.setInterval = function (fn, delay, ...rest) {
                    const id = _orig(fn, delay, ...rest);
                    window._capturedIntervalId = id;
                    return id;
                };
                window._announceCount = 0;
                const announcer = document.getElementById('phase-announcer');
                if (announcer) {
                    new MutationObserver(function (mutations) {
                        mutations.forEach(function (m) {
                            if (announcer.textContent === 'Timer complete') {
                                window._announceCount += 1;
                            }
                        });
                    }).observe(announcer, { childList: true, subtree: true, characterData: true });
                }
            }
        """)

        page.locator(".timer-start").click()

        page.evaluate("""
            () => {
                Object.defineProperty(document, 'hidden', {
                    get: () => true,
                    configurable: true,
                });
                document.dispatchEvent(new Event('visibilitychange'));
                if (window._capturedIntervalId !== undefined) {
                    clearInterval(window._capturedIntervalId);
                }
            }
        """)

        page.clock.run_for(65_000)

        assert _display(page) == "01:00", (
            "While hidden the display must stay frozen at the start value, "
            f"got '{_display(page)}'"
        )

        page.evaluate("""
            () => {
                Object.defineProperty(document, 'hidden', {
                    get: () => false,
                    configurable: true,
                });
                document.dispatchEvent(new Event('visibilitychange'));
            }
        """)

        page.clock.run_for(100)

        assert _display(page) == "00:00", (
            "After tab return with 65 s elapsed, display must show 00:00, "
            f"got '{_display(page)}'"
        )

        start_btn = page.locator(".timer-start")
        assert not start_btn.is_disabled(), (
            "Start button must be re-enabled once the timer has expired on tab return"
        )

        announce_count = page.evaluate("() => window._announceCount")
        assert announce_count == 1, (
            f"'Timer complete' must be announced exactly once, got {announce_count}"
        )

        announcer_text = page.locator("#phase-announcer").inner_text()
        assert announcer_text == "Timer complete", (
            f"#phase-announcer must read 'Timer complete', got '{announcer_text}'"
        )

    def test_phase_timer_expires_cleanly_on_tab_return(self, page, timer_html):
        """
        Phase-timer variant: the tab returns *after* all 9 s of phases have
        elapsed while hidden.

        The visibilitychange handler calls applyServerTimestamp, which must:
        - set display to '00:00' (last phase exhausted)
        - re-enable the Start button
        - announce 'All phases complete' exactly once via #phase-announcer

        The '&& intervalId' guard inside applyServerTimestamp ensures that
        if this path is somehow reached when the interval is already cleared
        (impossible in practice but defensive), no double-announcement fires.
        """
        page.clock.install()
        page.set_content(timer_html, wait_until="domcontentloaded")
        page.wait_for_selector(".timer-widget")

        page.evaluate("""
            () => {
                const _orig = window.setInterval;
                window.setInterval = function (fn, delay, ...rest) {
                    const id = _orig(fn, delay, ...rest);
                    window._capturedIntervalId = id;
                    return id;
                };
                window._allPhasesCount = 0;
                const announcer = document.getElementById('phase-announcer');
                if (announcer) {
                    new MutationObserver(function (mutations) {
                        mutations.forEach(function (m) {
                            if (announcer.textContent === 'All phases complete') {
                                window._allPhasesCount += 1;
                            }
                        });
                    }).observe(announcer, { childList: true, subtree: true, characterData: true });
                }
            }
        """)

        page.locator(".timer-start").click()

        page.evaluate("""
            () => {
                Object.defineProperty(document, 'hidden', {
                    get: () => true,
                    configurable: true,
                });
                document.dispatchEvent(new Event('visibilitychange'));
                if (window._capturedIntervalId !== undefined) {
                    clearInterval(window._capturedIntervalId);
                }
            }
        """)

        page.clock.run_for(15_000)

        page.evaluate("""
            () => {
                Object.defineProperty(document, 'hidden', {
                    get: () => false,
                    configurable: true,
                });
                document.dispatchEvent(new Event('visibilitychange'));
            }
        """)

        page.clock.run_for(100)

        assert _display(page) == "00:00", (
            "After tab return with 15 s elapsed (> 9 s total), display must show 00:00, "
            f"got '{_display(page)}'"
        )

        start_btn = page.locator(".timer-start")
        assert not start_btn.is_disabled(), (
            "Start button must be re-enabled once all phases have expired on tab return"
        )

        count = page.evaluate("() => window._allPhasesCount")
        assert count == 1, (
            f"'All phases complete' must be announced exactly once on tab return, got {count}"
        )

        announcer_text = page.locator("#phase-announcer").inner_text()
        assert announcer_text == "All phases complete", (
            f"#phase-announcer must read 'All phases complete', got '{announcer_text}'"
        )

    def test_no_resync_when_paused(self, page, simple_timer_html):
        """
        When the timer is paused, virtualStartedAt is null.  The
        visibilitychange handler must NOT call applyServerTimestamp, so the
        display must stay at the paused value rather than jumping forward.
        """
        _load_simple_timer(page, simple_timer_html)

        page.locator(".timer-start").click()
        page.clock.run_for(5_000)

        page.locator(".timer-pause").click()
        paused_display = _display(page)

        page.clock.run_for(10_000)

        page.evaluate("""
            () => {
                Object.defineProperty(document, 'hidden', {
                    get: () => false, configurable: true
                });
                document.dispatchEvent(new Event('visibilitychange'));
            }
        """)

        assert _display(page) == paused_display, (
            f"Paused timer must not re-sync on tab restore; "
            f"expected '{paused_display}', got '{_display(page)}'"
        )
