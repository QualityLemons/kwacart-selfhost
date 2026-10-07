"""
Browser-based accessibility tests for the drawing-canvas widget announcements.

These tests use Playwright to load the canvas widget in a real Chromium browser
and verify that the JavaScript announce() function fires correctly when a user
activates the Eraser, clicks Eraser again to return to drawing mode, and clicks
Undo with an empty history.

A MutationObserver (the same technique used by the pause/resume timer tests)
is installed on #canvas-announcer before each interaction so that every
textContent mutation is captured and can be asserted after the fact.

The canvas template HTML is pre-rendered in the ``canvas_html`` fixture defined
in conftest.py and loaded into the browser via page.set_content(), so no
running Django server is needed.

Clock note
----------
The canvas announce() function defers the textContent update via setTimeout
with ANNOUNCE_DELAY_MS = 50 ms.  We install a fake clock before set_content
and call page.clock.run_for(200) after each button click so the setTimeout
callback fires before the assertion reads the live region.
"""

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_canvas(page, canvas_html: str) -> None:
    """
    Install a fake clock, load the pre-rendered canvas HTML into the browser
    page, and wait for the drawing toolbar to be visible.

    The clock is installed before set_content so that every setTimeout call
    made by the canvas widget's init code is under test control from the very
    first script execution.
    """
    page.clock.install()
    page.set_content(canvas_html, wait_until="domcontentloaded")
    page.wait_for_selector(".drawing-toolbar")


def _advance(page, milliseconds: int) -> None:
    """
    Advance the fake clock to flush pending setTimeout callbacks.

    run_for fires both timer callbacks and requestAnimationFrame callbacks,
    ensuring the announce() helper's deferred textContent update is complete
    before the assertion reads the live region.
    """
    page.clock.run_for(milliseconds)


def _install_canvas_observer(page) -> None:
    """
    Inject a MutationObserver that records every textContent change on
    ``#canvas-announcer`` into ``window.__canvasAnnouncerChanges``.

    Call this after the canvas toolbar is visible but before the action under
    test so that every mutation is captured.  The list accumulates both the ''
    clear and the actual message text, allowing tests to count non-empty
    announcements separately.
    """
    page.evaluate("""
        () => {
            window.__canvasAnnouncerChanges = [];
            const el = document.getElementById('canvas-announcer');
            const obs = new MutationObserver(muts => {
                muts.forEach(m => {
                    window.__canvasAnnouncerChanges.push(m.target.textContent.trim());
                });
            });
            obs.observe(el, { childList: true, subtree: true, characterData: true });
        }
    """)


def _get_canvas_announcer_changes(page) -> list:
    """Return the list of textContent snapshots captured by the observer."""
    return page.evaluate("() => window.__canvasAnnouncerChanges")


def _announcer_text(page) -> str:
    """Return the current textContent of #canvas-announcer."""
    return page.locator("#canvas-announcer").inner_text()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDrawingCanvasAnnouncementsBrowser:
    """
    Browser-level tests verifying that canvas drawing-action announcements
    fire correctly via the #canvas-announcer aria-live region.
    """

    def test_eraser_active_announcement_fires(self, page, canvas_html):
        """
        Clicking the Eraser button once must fire the announcement
        'Eraser active' in the #canvas-announcer live region.
        """
        _load_canvas(page, canvas_html)
        _install_canvas_observer(page)

        page.locator(".eraser-btn").click()
        _advance(page, 200)

        changes = _get_canvas_announcer_changes(page)
        non_empty = [c for c in changes if c]
        assert non_empty, (
            "Expected at least one non-empty announcement after clicking Eraser; "
            f"got changes: {changes}"
        )
        assert any("Eraser active" in c for c in non_empty), (
            f"Expected 'Eraser active' in announcer changes; got: {non_empty}"
        )

    def test_drawing_mode_active_announcement_fires(self, page, canvas_html):
        """
        Clicking the Eraser button a second time (to toggle it off) must fire
        the announcement 'Drawing mode active' in the #canvas-announcer live
        region.
        """
        _load_canvas(page, canvas_html)

        page.locator(".eraser-btn").click()
        _advance(page, 200)

        _install_canvas_observer(page)

        page.locator(".eraser-btn").click()
        _advance(page, 200)

        changes = _get_canvas_announcer_changes(page)
        non_empty = [c for c in changes if c]
        assert non_empty, (
            "Expected at least one non-empty announcement after toggling Eraser off; "
            f"got changes: {changes}"
        )
        assert any("Drawing mode active" in c for c in non_empty), (
            f"Expected 'Drawing mode active' in announcer changes; got: {non_empty}"
        )

    def test_undo_with_no_history_announces_nothing_to_undo(self, page, canvas_html):
        """
        Clicking the Undo button when the history stack is empty must fire the
        announcement 'Nothing to undo' in the #canvas-announcer live region.
        """
        _load_canvas(page, canvas_html)
        _install_canvas_observer(page)

        page.locator(".undo-btn").click()
        _advance(page, 200)

        changes = _get_canvas_announcer_changes(page)
        non_empty = [c for c in changes if c]
        assert non_empty, (
            "Expected at least one non-empty announcement after clicking Undo with no history; "
            f"got changes: {changes}"
        )
        assert any("Nothing to undo" in c for c in non_empty), (
            f"Expected 'Nothing to undo' in announcer changes; got: {non_empty}"
        )

    def test_eraser_announcement_is_exactly_once(self, page, canvas_html):
        """
        A single Eraser click must produce exactly one non-empty announcement
        ('Eraser active'). It must not fire multiple times.
        """
        _load_canvas(page, canvas_html)
        _install_canvas_observer(page)

        page.locator(".eraser-btn").click()
        _advance(page, 500)

        changes = _get_canvas_announcer_changes(page)
        non_empty = [c for c in changes if c]
        assert len(non_empty) == 1, (
            f"Expected exactly 1 non-empty announcement for a single Eraser click; "
            f"got: {non_empty}"
        )
        assert non_empty[0] == "Eraser active", (
            f"Expected 'Eraser active', got: {non_empty[0]!r}"
        )

    def test_announcer_aria_live_attributes_unchanged_after_interactions(
        self, page, canvas_html
    ):
        """
        After eraser, drawing-mode toggle, and undo clicks the #canvas-announcer
        element must still carry aria-live='polite' and aria-atomic='true' —
        the JS must not have mutated these attributes.
        """
        _load_canvas(page, canvas_html)

        page.locator(".eraser-btn").click()
        _advance(page, 200)
        page.locator(".eraser-btn").click()
        _advance(page, 200)
        page.locator(".undo-btn").click()
        _advance(page, 200)

        announcer = page.locator("#canvas-announcer")
        assert announcer.get_attribute("aria-live") == "polite", (
            "aria-live must remain 'polite' after canvas interactions"
        )
        assert announcer.get_attribute("aria-atomic") == "true", (
            "aria-atomic must remain 'true' after canvas interactions"
        )
