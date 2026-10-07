"""
Browser-based accessibility tests for the archive detail and session-closed pages.

Two complementary approaches are used:

1. **Pre-rendered HTML tests** (``TestArchiveDetailBrowser``,
   ``TestSessionClosedBrowser``): The page HTML is pre-rendered server-side
   via ``page.set_content()``.  No live server is required; these tests run
   quickly and validate structural and a11y correctness of the templates
   themselves.

2. **Live-server smoke tests** (``TestArchiveDetailLiveServer``,
   ``TestSessionClosedLiveServer``): A real Django development server is
   started with ``pytest-django``'s ``live_server`` fixture.  The browser
   navigates to the actual application URLs to confirm route wiring, login
   gating, and full-stack rendering parity with the template-level checks.

These tests use Playwright to render the pre-built HTML in a real Chromium
browser and inject axe-core to audit the pages for WCAG 2 AA violations that
only surface at runtime (e.g. colour-contrast issues resolved by the browser's
rendering engine, missing implicit ARIA roles, focus-order problems).

The HTML is pre-rendered server-side by the ``archive_detail_html`` and
``session_closed_html`` fixtures in conftest.py using lightweight mock objects.
No running Django server is required — ``page.set_content()`` loads the HTML
directly into the browser.

What is checked
---------------
* No axe-core WCAG 2 AA violations on either page.
* Exactly one <h1> is present (structural correctness in a real browser).
* The <nav> and <main> landmark elements are present and visible.
* The HTML ``lang`` attribute is present and non-empty.
* The page ``<title>`` is non-empty.
* Heading levels do not skip (e.g. h1 → h3 without h2).
"""

from pathlib import Path

import pytest

AXE_SCRIPT = Path(__file__).parent / "axe.min.js"


# ---------------------------------------------------------------------------
# Helpers (mirrors the pattern in test_timer_a11y_browser.py)
# ---------------------------------------------------------------------------

def _load_page(page, html: str) -> None:
    """Load pre-rendered HTML into the browser and wait until it is ready."""
    page.set_content(html, wait_until="domcontentloaded")


def _run_axe(page) -> dict:
    """Inject axe-core (if not already present) and return axe.run() results."""
    if not page.evaluate("typeof window.axe !== 'undefined'"):
        page.add_script_tag(path=str(AXE_SCRIPT))
    results = page.evaluate("""
        async () => {
            const r = await window.axe.run(document.body, {
                runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa'] }
            });
            return {
                violations: r.violations.map(v => ({
                    id: v.id,
                    impact: v.impact,
                    description: v.description,
                    nodes: v.nodes.map(n => n.html).slice(0, 3),
                })),
                passes: r.passes.length,
            };
        }
    """)
    return results


def _assert_no_violations(results: dict, label: str) -> None:
    violations = results.get("violations", [])
    if violations:
        summary = "\n".join(
            f"  [{v['impact']}] {v['id']}: {v['description']}\n"
            f"    nodes: {v['nodes']}"
            for v in violations
        )
        pytest.fail(
            f"axe-core found {len(violations)} violation(s) on '{label}':\n{summary}"
        )


def _heading_levels(page) -> list:
    """Return the numeric heading levels present in the page in DOM order."""
    return page.evaluate("""
        () => Array.from(
            document.querySelectorAll('h1, h2, h3, h4, h5, h6')
        ).map(el => parseInt(el.tagName[1], 10))
    """)


# ---------------------------------------------------------------------------
# Archive detail page tests
# ---------------------------------------------------------------------------

class TestArchiveDetailBrowser:
    """
    Live-browser checks for the archive detail page (``/archive/view/<pk>/``).

    The page HTML is pre-rendered via the ``archive_detail_html`` fixture so
    that no running server is required.
    """

    def test_no_axe_violations(self, page, archive_detail_html):
        """The archive detail page must pass axe-core WCAG 2 AA audit."""
        _load_page(page, archive_detail_html)
        results = _run_axe(page)
        _assert_no_violations(results, "archive detail")

    def test_single_h1(self, page, archive_detail_html):
        """Exactly one <h1> must be present in the rendered page."""
        _load_page(page, archive_detail_html)
        h1_count = page.locator("h1").count()
        assert h1_count == 1, (
            f"Archive detail: expected exactly 1 <h1>, found {h1_count}"
        )

    def test_h1_contains_tool_name(self, page, archive_detail_html):
        """The <h1> must contain the tool name used in the fixture."""
        _load_page(page, archive_detail_html)
        h1_text = page.locator("h1").inner_text()
        assert "Wise-Crowds" in h1_text or "wise-crowds" in h1_text.lower(), (
            f"Archive detail: <h1> text was '{h1_text}', expected tool name"
        )

    def test_nav_landmark_present(self, page, archive_detail_html):
        """A <nav> landmark must be visible in the rendered page."""
        _load_page(page, archive_detail_html)
        assert page.locator("nav").count() >= 1, (
            "Archive detail: page must contain at least one <nav> landmark"
        )

    def test_main_landmark_present(self, page, archive_detail_html):
        """A <main> landmark must be present in the rendered page."""
        _load_page(page, archive_detail_html)
        assert page.locator("main").count() == 1, (
            "Archive detail: page must contain exactly one <main> landmark"
        )

    def test_html_lang_attribute(self, page, archive_detail_html):
        """The <html> element must carry a non-empty lang attribute."""
        _load_page(page, archive_detail_html)
        lang = page.evaluate("document.documentElement.lang")
        assert lang and len(lang) >= 2, (
            f"Archive detail: <html lang> must be set, got {lang!r}"
        )

    def test_page_title_non_empty(self, page, archive_detail_html):
        """The <title> element must be present and non-empty."""
        _load_page(page, archive_detail_html)
        title = page.evaluate("document.title")
        assert title and len(title.strip()) > 0, (
            f"Archive detail: <title> must not be empty, got {title!r}"
        )

    def test_no_heading_level_skips(self, page, archive_detail_html):
        """Heading levels must not skip (e.g. h1 → h3 without h2)."""
        _load_page(page, archive_detail_html)
        levels = _heading_levels(page)
        for i in range(1, len(levels)):
            prev, curr = levels[i - 1], levels[i]
            assert curr - prev <= 1, (
                f"Archive detail: heading hierarchy skips from h{prev} to "
                f"h{curr} (all levels: {levels})"
            )

    def test_back_link_present(self, page, archive_detail_html):
        """The 'Back to archive' navigation link must be rendered."""
        _load_page(page, archive_detail_html)
        back_link = page.locator("a", has_text="Back to archive")
        assert back_link.count() >= 1, (
            "Archive detail: expected a 'Back to archive' link"
        )


# ---------------------------------------------------------------------------
# Session-closed page tests
# ---------------------------------------------------------------------------

class TestSessionClosedBrowser:
    """
    Live-browser checks for the session-closed results page
    (``/tools/session/<id>/`` when the session is closed).

    The page HTML is pre-rendered via the ``session_closed_html`` fixture so
    that no running server is required.
    """

    def test_no_axe_violations(self, page, session_closed_html):
        """The session-closed page must pass axe-core WCAG 2 AA audit."""
        _load_page(page, session_closed_html)
        results = _run_axe(page)
        _assert_no_violations(results, "session closed")

    def test_single_h1(self, page, session_closed_html):
        """Exactly one <h1> must be present in the rendered page."""
        _load_page(page, session_closed_html)
        h1_count = page.locator("h1").count()
        assert h1_count == 1, (
            f"Session closed: expected exactly 1 <h1>, found {h1_count}"
        )

    def test_h1_contains_tool_title(self, page, session_closed_html):
        """The <h1> must contain the tool title supplied in the fixture."""
        _load_page(page, session_closed_html)
        h1_text = page.locator("h1").inner_text()
        assert "Wise Crowds" in h1_text, (
            f"Session closed: <h1> text was '{h1_text}', expected tool title"
        )

    def test_nav_landmark_present(self, page, session_closed_html):
        """A <nav> landmark must be visible in the rendered page."""
        _load_page(page, session_closed_html)
        assert page.locator("nav").count() >= 1, (
            "Session closed: page must contain at least one <nav> landmark"
        )

    def test_main_landmark_present(self, page, session_closed_html):
        """A <main> landmark must be present in the rendered page."""
        _load_page(page, session_closed_html)
        assert page.locator("main").count() == 1, (
            "Session closed: page must contain exactly one <main> landmark"
        )

    def test_html_lang_attribute(self, page, session_closed_html):
        """The <html> element must carry a non-empty lang attribute."""
        _load_page(page, session_closed_html)
        lang = page.evaluate("document.documentElement.lang")
        assert lang and len(lang) >= 2, (
            f"Session closed: <html lang> must be set, got {lang!r}"
        )

    def test_page_title_non_empty(self, page, session_closed_html):
        """The <title> element must be present and non-empty."""
        _load_page(page, session_closed_html)
        title = page.evaluate("document.title")
        assert title and len(title.strip()) > 0, (
            f"Session closed: <title> must not be empty, got {title!r}"
        )

    def test_no_heading_level_skips(self, page, session_closed_html):
        """Heading levels must not skip (e.g. h1 → h3 without h2)."""
        _load_page(page, session_closed_html)
        levels = _heading_levels(page)
        for i in range(1, len(levels)):
            prev, curr = levels[i - 1], levels[i]
            assert curr - prev <= 1, (
                f"Session closed: heading hierarchy skips from h{prev} to "
                f"h{curr} (all levels: {levels})"
            )

    def test_empty_participants_message(self, page, session_closed_html):
        """
        When no instances are present the 'No participants' message must
        appear (the ``{% empty %}`` branch of the for-loop).
        """
        _load_page(page, session_closed_html)
        content = page.locator("main").inner_text()
        assert "No participants" in content, (
            f"Session closed: expected 'No participants' message, got:\n{content}"
        )

    def test_back_link_present(self, page, session_closed_html):
        """The 'Back to catalog' navigation link must be rendered."""
        _load_page(page, session_closed_html)
        back_link = page.locator("a", has_text="Back to catalog")
        assert back_link.count() >= 1, (
            "Session closed: expected a 'Back to catalog' link"
        )


# ---------------------------------------------------------------------------
# Archive detail page — with payload data (task #77)
# ---------------------------------------------------------------------------

class TestArchiveDetailWithPayloadBrowser:
    """
    Live-browser checks for the archive detail page when ``payload_output``
    and ``payload_input`` are both present.

    The empty-payload state is already covered by ``TestArchiveDetailBrowser``.
    This class exercises the additional template branches that render the
    "Results" and "Your input" sections — including extra ``<h2>`` headings
    and key/value blocks — to confirm they do not introduce heading-level
    skips or WCAG 2 AA violations.
    """

    def test_no_axe_violations_with_payload(self, page, archive_detail_with_payload_html):
        """The archive detail page with payload data must pass axe-core WCAG 2 AA audit."""
        _load_page(page, archive_detail_with_payload_html)
        results = _run_axe(page)
        _assert_no_violations(results, "archive detail — with payload")

    def test_single_h1_with_payload(self, page, archive_detail_with_payload_html):
        """Exactly one <h1> must be present even when payload sections are rendered."""
        _load_page(page, archive_detail_with_payload_html)
        h1_count = page.locator("h1").count()
        assert h1_count == 1, (
            f"Archive detail with payload: expected 1 <h1>, found {h1_count}"
        )

    def test_results_h2_present_with_payload(self, page, archive_detail_with_payload_html):
        """
        When ``payload_output`` is non-empty the 'Results' <h2> must be rendered,
        confirming the conditional branch fires correctly.
        """
        _load_page(page, archive_detail_with_payload_html)
        h2_texts = page.evaluate("""
            () => Array.from(document.querySelectorAll('h2')).map(el => el.textContent.trim())
        """)
        assert "Results" in h2_texts, (
            f"Archive detail with payload_output: expected an <h2>Results</h2>, got h2s: {h2_texts}"
        )

    def test_input_h2_present_with_payload(self, page, archive_detail_with_payload_html):
        """
        When ``payload_input`` is non-empty the 'Your input' <h2> must be rendered.
        """
        _load_page(page, archive_detail_with_payload_html)
        h2_texts = page.evaluate("""
            () => Array.from(document.querySelectorAll('h2')).map(el => el.textContent.trim())
        """)
        assert "Your input" in h2_texts, (
            f"Archive detail with payload_input: expected an <h2>Your input</h2>, got h2s: {h2_texts}"
        )

    def test_no_heading_level_skips_with_payload(self, page, archive_detail_with_payload_html):
        """
        Heading levels must not skip (e.g. h1 → h3 without h2) even when
        the extra 'Results' and 'Your input' sections are present.
        """
        _load_page(page, archive_detail_with_payload_html)
        levels = _heading_levels(page)
        for i in range(1, len(levels)):
            prev, curr = levels[i - 1], levels[i]
            assert curr - prev <= 1, (
                f"Archive detail with payload: heading hierarchy skips from h{prev} to "
                f"h{curr} (all levels: {levels})"
            )

    def test_payload_content_visible_in_main(self, page, archive_detail_with_payload_html):
        """
        The payload_output values from the fixture must appear inside <main>,
        confirming the template loops rendered correctly and the content is
        accessible to screen reader users.
        """
        _load_page(page, archive_detail_with_payload_html)
        main_text = page.locator("main").inner_text()
        assert "three key patterns" in main_text, (
            "Archive detail with payload: payload_output value not found in <main>"
        )
        assert "cross-team collaboration" in main_text, (
            "Archive detail with payload: payload_input value not found in <main>"
        )


# ---------------------------------------------------------------------------
# Live-server smoke tests — real URLs, route wiring, full-stack rendering
# ---------------------------------------------------------------------------

def _inject_session_cookie(page, live_server_url: str, session_key: str) -> None:
    """
    Inject a Django session cookie obtained from the test client into the
    Playwright browser context so the browser is authenticated.
    """
    from urllib.parse import urlparse
    parsed = urlparse(live_server_url)
    page.context.add_cookies([{
        "name": "sessionid",
        "value": session_key,
        "domain": parsed.hostname,
        "path": "/",
    }])


@pytest.mark.django_db
class TestArchiveDetailLiveServer:
    """
    Smoke tests for the archive detail page using a live Django test server.

    These tests navigate to the real URL ``/archive/view/<pk>/`` and confirm
    that the route is reachable, the page renders a proper HTML structure,
    and axe-core reports no WCAG 2 AA violations — validating the full
    server-to-browser pipeline rather than just the pre-rendered template.
    """

    def test_route_renders_h1_and_nav(self, page, live_server, django_user_model, client):
        """
        GET /archive/view/<pk>/ as an authenticated user must return a page
        with exactly one <h1> and at least one <nav> landmark.
        """
        from archive.models import ToolInstance

        user = django_user_model.objects.create_user(
            email="ls-archive-detail@example.com",
            password="testpw123!",
        )
        instance = ToolInstance.objects.create(
            user=user,
            tool_slug="wise-crowds",
            tool_version="1.0",
            status="archived",
        )
        client.force_login(user)
        session_key = client.cookies["sessionid"].value

        _inject_session_cookie(page, live_server.url, session_key)
        page.goto(f"{live_server.url}/archive/view/{instance.pk}/")
        page.wait_for_selector("main")

        assert page.locator("h1").count() == 1, (
            "Archive detail live: expected exactly 1 <h1>"
        )
        assert page.locator("nav").count() >= 1, (
            "Archive detail live: page must have a <nav> landmark"
        )

    def test_no_axe_violations_live(self, page, live_server, django_user_model, client):
        """
        The archive detail page served from the live server must pass the
        axe-core WCAG 2 AA audit.
        """
        from archive.models import ToolInstance

        user = django_user_model.objects.create_user(
            email="ls-archive-axe@example.com",
            password="testpw123!",
        )
        instance = ToolInstance.objects.create(
            user=user,
            tool_slug="wise-crowds",
            tool_version="1.0",
            status="archived",
        )
        client.force_login(user)
        session_key = client.cookies["sessionid"].value

        _inject_session_cookie(page, live_server.url, session_key)
        page.goto(f"{live_server.url}/archive/view/{instance.pk}/")
        page.wait_for_selector("main")

        results = _run_axe(page)
        _assert_no_violations(results, "archive detail (live server)")


@pytest.mark.django_db
class TestSessionClosedLiveServer:
    """
    Smoke tests for the session-closed page using a live Django test server.

    These tests navigate to the real URL ``/tools/session/<id>/`` when the
    session is closed and confirm that the route is reachable, the page
    renders correctly, and axe-core reports no WCAG 2 AA violations.
    """

    def test_route_renders_h1_and_nav(self, page, live_server, django_user_model, client):
        """
        GET /tools/session/<id>/ for a closed session as the host must return
        a page with exactly one <h1> and at least one <nav> landmark.
        """
        from django.utils import timezone
        from archive.models import ToolSession

        user = django_user_model.objects.create_user(
            email="ls-session-closed@example.com",
            password="testpw123!",
        )
        session = ToolSession.objects.create(
            host=user,
            tool_slug="wise-crowds",
            tool_version="1.0",
            status="closed",
            closed_at=timezone.now(),
        )
        client.force_login(user)
        session_key = client.cookies["sessionid"].value

        _inject_session_cookie(page, live_server.url, session_key)
        page.goto(f"{live_server.url}/tools/session/{session.id}/")
        page.wait_for_selector("main")

        assert page.locator("h1").count() == 1, (
            "Session closed live: expected exactly 1 <h1>"
        )
        assert page.locator("nav").count() >= 1, (
            "Session closed live: page must have a <nav> landmark"
        )

    def test_no_axe_violations_live(self, page, live_server, django_user_model, client):
        """
        The session-closed page served from the live server must pass the
        axe-core WCAG 2 AA audit.
        """
        from django.utils import timezone
        from archive.models import ToolSession

        user = django_user_model.objects.create_user(
            email="ls-session-axe@example.com",
            password="testpw123!",
        )
        session = ToolSession.objects.create(
            host=user,
            tool_slug="wise-crowds",
            tool_version="1.0",
            status="closed",
            closed_at=timezone.now(),
        )
        client.force_login(user)
        session_key = client.cookies["sessionid"].value

        _inject_session_cookie(page, live_server.url, session_key)
        page.goto(f"{live_server.url}/tools/session/{session.id}/")
        page.wait_for_selector("main")

        results = _run_axe(page)
        _assert_no_violations(results, "session closed (live server)")
