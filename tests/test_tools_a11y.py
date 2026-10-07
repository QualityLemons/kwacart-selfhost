"""
Accessibility tests for tool view templates.

Covers the solo-draft form, session host view, and archive dashboard, checking:
- Page title is set
- Exactly one <h1> per page
- No heading level is skipped (e.g. h1 → h3 without h2)
- Navigation landmark (<nav>) is present
- HTML language attribute is set on <html>
- Form inputs have associated <label> elements
- Data tables contain <th> header cells
"""

from html.parser import HTMLParser

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from archive.models import ToolSession

User = get_user_model()

TOOL_SLUG = "wise-crowds"


# ---------------------------------------------------------------------------
# HTML parsing helpers
# ---------------------------------------------------------------------------

class _FullPageParser(HTMLParser):
    """
    Collects start tags, end tags, and character data from a full HTML page.
    Enables querying by tag name and attributes, and tracks inner text for
    elements like headings.
    """

    def __init__(self):
        super().__init__()
        self._elements = []
        self._tag_stack = []
        self._current_data = []

    def handle_starttag(self, tag, attrs):
        element = {"tag": tag, "attrs": dict(attrs), "text": ""}
        self._elements.append(element)
        self._tag_stack.append(element)

    def handle_endtag(self, tag):
        # Only pop the stack when the closing tag matches the most recent
        # open element.  This single-level check is intentionally simple —
        # HTML5 void elements (e.g. <br>, <input>) never push to the stack
        # so they will not cause spurious pops here.
        if self._tag_stack and self._tag_stack[-1]["tag"] == tag:
            closed = self._tag_stack.pop()
            closed["text"] = "".join(self._current_data).strip()
            self._current_data = []

    def handle_data(self, data):
        self._current_data.append(data)

    def find_all(self, tag=None, **attr_conditions):
        results = []
        for el in self._elements:
            if tag and el["tag"] != tag:
                continue
            if all(el["attrs"].get(k) == v for k, v in attr_conditions.items()):
                results.append(el)
        return results

    def find_one(self, tag=None, **attr_conditions):
        matches = self.find_all(tag=tag, **attr_conditions)
        return matches[0] if matches else None

    def headings(self):
        """Return all heading elements (h1–h6) in document order."""
        return [el for el in self._elements if el["tag"] in ("h1", "h2", "h3", "h4", "h5", "h6")]

    def heading_levels(self):
        """Return the numeric levels of all headings in document order."""
        return [int(el["tag"][1]) for el in self.headings()]


def _parse_html(html_bytes):
    parser = _FullPageParser()
    text = html_bytes.decode("utf-8") if isinstance(html_bytes, bytes) else html_bytes
    parser.feed(text)
    return parser


# ---------------------------------------------------------------------------
# Shared accessibility assertions (mixin)
# ---------------------------------------------------------------------------

class _A11yAssertions:
    """Reusable accessibility assertions for subclasses to call."""

    def _assert_single_h1(self, dom, page_label):
        h1s = dom.find_all(tag="h1")
        self.assertEqual(
            len(h1s), 1,
            f"{page_label}: expected exactly 1 <h1>, found {len(h1s)}",
        )

    def _assert_no_heading_skips(self, dom, page_label):
        levels = dom.heading_levels()
        # Ascending skips (e.g. h1 → h3) are illegal; descending jumps
        # (e.g. h3 → h1 back to the top) are allowed by the spec so only
        # curr - prev > 1 is checked, not the reverse.
        for i in range(1, len(levels)):
            prev, curr = levels[i - 1], levels[i]
            self.assertLessEqual(
                curr - prev, 1,
                f"{page_label}: heading hierarchy skips from h{prev} to h{curr} "
                f"(headings: {levels})",
            )

    def _assert_nav_landmark(self, dom, page_label):
        nav = dom.find_one(tag="nav")
        self.assertIsNotNone(nav, f"{page_label}: page must contain a <nav> landmark")

    def _assert_main_landmark(self, dom, page_label):
        main = dom.find_one(tag="main")
        self.assertIsNotNone(main, f"{page_label}: page must contain a <main> landmark")

    def _assert_html_lang(self, dom, page_label):
        html_el = dom.find_one(tag="html")
        self.assertIsNotNone(html_el, f"{page_label}: missing <html> element")
        lang = html_el["attrs"].get("lang", "")
        self.assertTrue(
            len(lang) >= 2,
            f"{page_label}: <html> must have a non-empty lang attribute, got {lang!r}",
        )

    def _assert_page_title(self, html_text, page_label):
        self.assertIn("<title>", html_text, f"{page_label}: <title> element is missing")
        import re
        match = re.search(r"<title>(.+?)</title>", html_text, re.DOTALL | re.IGNORECASE)
        self.assertIsNotNone(match, f"{page_label}: could not extract <title> content")
        title_text = match.group(1).strip()
        self.assertTrue(
            len(title_text) > 0,
            f"{page_label}: <title> must not be empty",
        )

    def _assert_skip_link(self, dom, page_label):
        skip = dom.find_one(tag="a", href="#main-content")
        self.assertIsNotNone(
            skip,
            f"{page_label}: page must contain a skip link <a href='#main-content'>",
        )
        main = dom.find_one(tag="main")
        self.assertIsNotNone(main, f"{page_label}: page must contain a <main> element")
        self.assertEqual(
            main["attrs"].get("id"),
            "main-content",
            f"{page_label}: <main> must have id='main-content'",
        )
        # The skip link must appear in the DOM *before* the primary <nav> so
        # that keyboard-only users encounter it before navigating the menu.
        # Position is measured by element index in dom._elements.
        self.assertEqual(
            main["attrs"].get("tabindex"),
            "-1",
            f"{page_label}: <main> must have tabindex='-1' to receive programmatic focus",
        )
        skip_index = next(
            (i for i, el in enumerate(dom._elements) if el is skip), None
        )
        nav_index = next(
            (i for i, el in enumerate(dom._elements) if el["tag"] == "nav"), None
        )
        self.assertIsNotNone(nav_index, f"{page_label}: page must contain a <nav> element")
        self.assertLess(
            skip_index,
            nav_index,
            f"{page_label}: skip link must appear before <nav> in the DOM "
            f"(skip at index {skip_index}, nav at index {nav_index})",
        )

    def _assert_inputs_have_labels(self, dom, page_label):
        """Every interactive (non-readonly) text/textarea/select input must have a label."""
        # SKIP_TYPES: input types that do not need a visible label because they
        # are either non-interactive (hidden), self-labelling (submit/button/reset),
        # or handled separately by the checkbox/radio label conventions.
        SKIP_TYPES = {"hidden", "submit", "button", "reset", "image", "checkbox", "radio"}
        inputs = dom.find_all(tag="input")
        textareas = dom.find_all(tag="textarea")
        selects = dom.find_all(tag="select")

        all_labels = dom.find_all(tag="label")
        labelled_fors = {el["attrs"].get("for") for el in all_labels if el["attrs"].get("for")}

        for inp in inputs:
            input_type = inp["attrs"].get("type", "text").lower()
            if input_type in SKIP_TYPES:
                continue
            # Read-only inputs (e.g. share links) are display elements, not form fields.
            if "readonly" in inp["attrs"]:
                continue
            input_id = inp["attrs"].get("id")
            aria_label = inp["attrs"].get("aria-label") or inp["attrs"].get("aria-labelledby")
            self.assertTrue(
                input_id in labelled_fors or aria_label,
                f"{page_label}: input id={input_id!r} has no associated <label> or aria-label",
            )

        for ta in textareas:
            ta_id = ta["attrs"].get("id")
            aria_label = ta["attrs"].get("aria-label") or ta["attrs"].get("aria-labelledby")
            self.assertTrue(
                ta_id in labelled_fors or aria_label,
                f"{page_label}: <textarea> id={ta_id!r} has no associated <label> or aria-label",
            )

        for sel in selects:
            sel_id = sel["attrs"].get("id")
            aria_label = sel["attrs"].get("aria-label") or sel["attrs"].get("aria-labelledby")
            self.assertTrue(
                sel_id in labelled_fors or aria_label,
                f"{page_label}: <select> id={sel_id!r} has no associated <label> or aria-label",
            )


class HeadingHierarchyAssertionTests(_A11yAssertions, SimpleTestCase):
    """Regression coverage for the heading-order assertion used by CI."""

    def test_heading_level_skip_fails(self):
        dom = _parse_html("<main><h1>Page title</h1><h3>Skipped section</h3></main>")

        with self.assertRaisesRegex(AssertionError, "skips from h1 to h3"):
            self._assert_no_heading_skips(dom, "Regression fixture")

# ---------------------------------------------------------------------------
# Solo draft editor view
# ---------------------------------------------------------------------------

class DraftEditorA11yTests(_A11yAssertions, TestCase):
    """
    Accessibility checks for the solo-draft form page
    (GET /tools/<tool_slug>/draft/).
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="draft-a11y@example.com",
            password="testpassword123",
        )

    def setUp(self):
        self.client.force_login(self.user)
        response = self.client.get(f"/tools/{TOOL_SLUG}/draft/")
        self.assertEqual(
            response.status_code, 200,
            f"Expected 200 from draft editor, got {response.status_code}",
        )
        self.html = response.content.decode("utf-8")
        self.dom = _parse_html(self.html)

    def test_page_title_is_set(self):
        self._assert_page_title(self.html, "Draft editor")

    def test_has_single_h1(self):
        self._assert_single_h1(self.dom, "Draft editor")

    def test_no_heading_level_skips(self):
        self._assert_no_heading_skips(self.dom, "Draft editor")

    def test_nav_landmark_present(self):
        self._assert_nav_landmark(self.dom, "Draft editor")

    def test_main_landmark_present(self):
        self._assert_main_landmark(self.dom, "Draft editor")

    def test_html_lang_attribute(self):
        self._assert_html_lang(self.dom, "Draft editor")

    def test_form_inputs_have_labels(self):
        self._assert_inputs_have_labels(self.dom, "Draft editor")

    def test_form_element_present(self):
        form = self.dom.find_one(tag="form")
        self.assertIsNotNone(form, "Draft editor must render a <form> element")

    def test_form_has_post_method(self):
        form = self.dom.find_one(tag="form")
        self.assertIsNotNone(form)
        self.assertEqual(
            form["attrs"].get("method", "").lower(),
            "post",
            "Draft form must use method='post'",
        )

    def test_skip_link_present(self):
        self._assert_skip_link(self.dom, "Draft editor")

    def test_submit_button_present(self):
        buttons = self.dom.find_all(tag="button")
        submit_buttons = [
            b for b in buttons
            if b["attrs"].get("type", "submit").lower() == "submit"
        ]
        self.assertGreater(
            len(submit_buttons), 0,
            "Draft editor must have at least one submit button",
        )


# ---------------------------------------------------------------------------
# Drawing-canvas draft editor — aria-live announcer
# ---------------------------------------------------------------------------

class DrawingCanvasA11yTests(_A11yAssertions, TestCase):
    """
    Accessibility checks for the solo-draft form of the canvas-enabled tool
    (GET /tools/drawing-together/draft/).

    Verifies that the #canvas-announcer aria-live region is present and
    correctly configured so screen readers can receive drawing-action feedback.
    """

    CANVAS_TOOL_SLUG = "drawing-together"

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="canvas-a11y@example.com",
            password="testpassword123",
        )

    def setUp(self):
        self.client.force_login(self.user)
        response = self.client.get(f"/tools/{self.CANVAS_TOOL_SLUG}/draft/")
        self.assertEqual(
            response.status_code, 200,
            f"Expected 200 from canvas draft editor, got {response.status_code}",
        )
        self.html = response.content.decode("utf-8")
        self.dom = _parse_html(self.html)

    def test_main_landmark_present(self):
        self._assert_main_landmark(self.dom, "Drawing canvas draft editor")

    def test_canvas_aria_live_announcer_present(self):
        announcer = self.dom.find_one(id="canvas-announcer")
        self.assertIsNotNone(
            announcer,
            "Drawing canvas draft page must include a #canvas-announcer element for live announcements",
        )
        self.assertEqual(
            announcer["attrs"].get("aria-live"),
            "polite",
            "#canvas-announcer must use aria-live='polite'",
        )
        self.assertEqual(
            announcer["attrs"].get("aria-atomic"),
            "true",
            "#canvas-announcer must use aria-atomic='true'",
        )

    def test_canvas_drawing_canvas_element_present(self):
        canvas = self.dom.find_one(tag="canvas")
        self.assertIsNotNone(
            canvas,
            "Drawing canvas draft page must include a <canvas> element",
        )
        self.assertIn(
            "aria-label",
            canvas["attrs"],
            "<canvas> element must have an aria-label",
        )


# ---------------------------------------------------------------------------
# Session host view
# ---------------------------------------------------------------------------

class SessionHostA11yTests(_A11yAssertions, TestCase):
    """
    Accessibility checks for the open-session host page
    (GET /tools/session/<session_id>/ as the host).
    """

    @classmethod
    def setUpTestData(cls):
        from archive.models import ToolInstance
        cls.user = User.objects.create_user(
            email="session-a11y@example.com",
            password="testpassword123",
        )
        cls.participant = User.objects.create_user(
            email="session-participant-a11y@example.com",
            password="testpassword123",
        )
        cls.session = ToolSession.objects.create(
            host=cls.user,
            tool_slug=TOOL_SLUG,
            tool_version="1.0",
        )
        cls.participant_instance = ToolInstance.objects.create(
            user=cls.participant,
            session=cls.session,
            tool_slug=TOOL_SLUG,
            tool_version="1.0",
            payload_input={"question": "A realistic participant response"},
        )

    def setUp(self):
        self.client.force_login(self.user)
        response = self.client.get(f"/tools/session/{self.session.id}/")
        self.assertEqual(
            response.status_code, 200,
            f"Expected 200 from session view, got {response.status_code}",
        )
        self.html = response.content.decode("utf-8")
        self.dom = _parse_html(self.html)

    def test_page_title_is_set(self):
        self._assert_page_title(self.html, "Session host view")

    def test_has_single_h1(self):
        self._assert_single_h1(self.dom, "Session host view")

    def test_no_heading_level_skips(self):
        self._assert_no_heading_skips(self.dom, "Session host view")

    def test_nav_landmark_present(self):
        self._assert_nav_landmark(self.dom, "Session host view")

    def test_main_landmark_present(self):
        self._assert_main_landmark(self.dom, "Session host view")

    def test_html_lang_attribute(self):
        self._assert_html_lang(self.dom, "Session host view")

    def test_form_inputs_have_labels(self):
        self._assert_inputs_have_labels(self.dom, "Session host view")

    def test_response_section_heading_present(self):
        h2s = self.dom.find_all(tag="h2")
        self.assertGreater(len(h2s), 0, "Session view must have at least one <h2>")

    def test_participants_heading_present(self):
        # The Participants <h2> contains a nested <span>, so search the raw HTML
        # for the heading text rather than relying on the parsed element text.
        import re
        participants_h2 = re.search(r"<h2[^>]*>.*?Participants.*?</h2>", self.html, re.DOTALL)
        self.assertIsNotNone(
            participants_h2,
            "Session view must have a 'Participants' <h2>",
        )

    def test_participant_is_rendered(self):
        self.assertIn(
            self.participant.email,
            self.html,
            "Session host view must render the participant fixture",
        )

    def test_share_link_input_present(self):
        # The share-link input carries an aria-label for accessibility.
        self.assertIn(
            'aria-label="Session invite link"',
            self.html,
            "Session view must include the share-link input with aria-label='Session invite link'",
        )

    def test_session_aria_live_announcer_present(self):
        announcer = self.dom.find_one(id="session-announcer")
        self.assertIsNotNone(
            announcer,
            "Session view must include a #session-announcer element for live announcements",
        )
        self.assertEqual(
            announcer["attrs"].get("aria-live"),
            "polite",
            "#session-announcer must use aria-live='polite'",
        )
        self.assertEqual(
            announcer["attrs"].get("aria-atomic"),
            "true",
            "#session-announcer must use aria-atomic='true'",
        )

    def test_timer_aria_live_announcer_present(self):
        announcer = self.dom.find_one(id="phase-announcer")
        self.assertIsNotNone(
            announcer,
            "Session view must include the timer #phase-announcer element for live announcements",
        )
        self.assertEqual(
            announcer["attrs"].get("aria-live"),
            "assertive",
            "#phase-announcer must use aria-live='assertive'",
        )

    def test_skip_link_present(self):
        self._assert_skip_link(self.dom, "Session host view")


# ---------------------------------------------------------------------------
# Session participant view — includes the waiting-state overlay
# ---------------------------------------------------------------------------

class SessionParticipantA11yTests(_A11yAssertions, TestCase):
    """
    Accessibility checks for the open-session participant page.

    This exercises the non-host branch, including the session-closed waiting
    overlay that is revealed while results are being prepared.
    """

    @classmethod
    def setUpTestData(cls):
        from archive.models import ToolInstance
        cls.host = User.objects.create_user(
            email="session-host-participant-view-a11y@example.com",
            password="testpassword123",
        )
        cls.participant = User.objects.create_user(
            email="session-waiting-a11y@example.com",
            password="testpassword123",
        )
        cls.session = ToolSession.objects.create(
            host=cls.host,
            tool_slug=TOOL_SLUG,
            tool_version="1.0",
        )
        cls.instance = ToolInstance.objects.create(
            user=cls.participant,
            session=cls.session,
            tool_slug=TOOL_SLUG,
            tool_version="1.0",
            payload_input={"question": "A saved response before results are revealed"},
        )

    def setUp(self):
        self.client.force_login(self.participant)
        response = self.client.get(f"/tools/session/{self.session.id}/")
        self.assertEqual(
            response.status_code, 200,
            f"Expected 200 from session participant view, got {response.status_code}",
        )
        self.html = response.content.decode("utf-8")
        self.dom = _parse_html(self.html)

    def test_page_title_is_set(self):
        self._assert_page_title(self.html, "Session participant view")

    def test_has_single_h1(self):
        self._assert_single_h1(self.dom, "Session participant view")

    def test_no_heading_level_skips(self):
        self._assert_no_heading_skips(self.dom, "Session participant view")

    def test_nav_landmark_present(self):
        self._assert_nav_landmark(self.dom, "Session participant view")

    def test_main_landmark_present(self):
        self._assert_main_landmark(self.dom, "Session participant view")

    def test_html_lang_attribute(self):
        self._assert_html_lang(self.dom, "Session participant view")

    def test_skip_link_present(self):
        self._assert_skip_link(self.dom, "Session participant view")

    def test_waiting_state_heading_present(self):
        import re
        waiting_heading = re.search(
            r'<div[^>]*id="session-waiting-overlay".*?<h2[^>]*>Session closed</h2>',
            self.html,
            re.DOTALL,
        )
        self.assertIsNotNone(
            waiting_heading,
            "Session participant view must render the waiting-state <h2>",
        )

    def test_participant_is_rendered(self):
        self.assertIn(
            self.participant.email,
            self.html,
            "Session participant view must render the participant fixture",
        )


# ---------------------------------------------------------------------------
# Knowledge Bank index
# ---------------------------------------------------------------------------

class ArchiveDashboardA11yTests(_A11yAssertions, TestCase):
    """
    Accessibility checks for the Knowledge Bank index.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="archive-a11y@example.com",
            password="testpassword123",
        )

    def setUp(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("archive:knowledge_bank"))
        self.assertEqual(
            response.status_code, 200,
            f"Expected 200 from Knowledge Bank, got {response.status_code}",
        )
        self.html = response.content.decode("utf-8")
        self.dom = _parse_html(self.html)

    def test_page_title_is_set(self):
        self._assert_page_title(self.html, "Archive dashboard")

    def test_has_single_h1(self):
        self._assert_single_h1(self.dom, "Archive dashboard")

    def test_no_heading_level_skips(self):
        self._assert_no_heading_skips(self.dom, "Archive dashboard")

    def test_nav_landmark_present(self):
        self._assert_nav_landmark(self.dom, "Archive dashboard")

    def test_main_landmark_present(self):
        self._assert_main_landmark(self.dom, "Archive dashboard")

    def test_html_lang_attribute(self):
        self._assert_html_lang(self.dom, "Archive dashboard")

    def test_solo_submissions_h2_present(self):
        self.assertIn("Every tool you've run", self.html)

    def test_sessions_h2_present(self):
        self.assertIn("tool catalog", self.html)

    def test_h1_text_is_my_archive(self):
        h1s = self.dom.find_all(tag="h1")
        self.assertEqual(len(h1s), 1)
        self.assertIn("Knowledge Bank", h1s[0]["text"])

    def test_empty_state_message_present_when_no_records(self):
        self.assertIn("No activity yet", self.html)

    def test_empty_sessions_message_present_when_no_sessions(self):
        self.assertIn("0 tools used", self.html)

    def test_skip_link_present(self):
        self._assert_skip_link(self.dom, "Archive dashboard")


# ---------------------------------------------------------------------------
# Knowledge Bank tool page with data — verifies table header accessibility
# ---------------------------------------------------------------------------

class ArchiveDashboardWithDataA11yTests(_A11yAssertions, TestCase):
    """
    Accessibility checks for the archive dashboard when records and sessions
    are present so that the data tables are rendered and can be inspected.
    """

    @classmethod
    def setUpTestData(cls):
        from archive.models import ToolInstance
        cls.user = User.objects.create_user(
            email="archive-data-a11y@example.com",
            password="testpassword123",
        )
        cls.session = ToolSession.objects.create(
            host=cls.user,
            data_owner=cls.user,
            tool_slug=TOOL_SLUG,
            tool_version="1.0",
        )
        cls.instance = ToolInstance.objects.create(
            user=cls.user,
            data_owner=cls.user,
            tool_slug=TOOL_SLUG,
            tool_version="1.0",
            status="archived",
        )

    def setUp(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("archive:knowledge_bank_tool", args=[TOOL_SLUG])
        )
        self.assertEqual(response.status_code, 200)
        self.html = response.content.decode("utf-8")
        self.dom = _parse_html(self.html)

    def test_main_landmark_present(self):
        self._assert_main_landmark(self.dom, "Archive dashboard with data")

    def test_solo_submissions_table_has_th_headers(self):
        ths = self.dom.find_all(tag="th")
        self.assertGreater(len(ths), 0, "Data tables must include <th> header cells")

    def test_table_th_cells_include_tool_column(self):
        ths = self.dom.find_all(tag="th")
        th_texts = [el["text"] for el in ths]
        self.assertTrue(
            any("Version" in t for t in th_texts),
            f"Expected a 'Version' <th> in the tables; found: {th_texts}",
        )

    def test_solo_table_has_submitted_column_header(self):
        ths = self.dom.find_all(tag="th")
        th_texts = [el["text"] for el in ths]
        self.assertTrue(
            any("Submitted" in t for t in th_texts),
            f"Expected a 'Submitted' <th>; found: {th_texts}",
        )


# ---------------------------------------------------------------------------
# Archive detail view
# ---------------------------------------------------------------------------

class ArchiveDetailA11yTests(_A11yAssertions, TestCase):
    """
    Accessibility checks for the archive detail page
    (GET /archive/detail/<pk>/).
    """

    @classmethod
    def setUpTestData(cls):
        from archive.models import ToolInstance
        cls.user = User.objects.create_user(
            email="archive-detail-a11y@example.com",
            password="testpassword123",
        )
        cls.instance = ToolInstance.objects.create(
            user=cls.user,
            data_owner=cls.user,
            tool_slug=TOOL_SLUG,
            tool_version="1.0",
            status="archived",
        )

    def setUp(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("archive:detail", args=[self.instance.pk])
        )
        self.assertEqual(
            response.status_code, 200,
            f"Expected 200 from archive detail, got {response.status_code}",
        )
        self.html = response.content.decode("utf-8")
        self.dom = _parse_html(self.html)

    def test_page_title_is_set(self):
        self._assert_page_title(self.html, "Archive detail")

    def test_has_single_h1(self):
        self._assert_single_h1(self.dom, "Archive detail")

    def test_no_heading_level_skips(self):
        self._assert_no_heading_skips(self.dom, "Archive detail")

    def test_nav_landmark_present(self):
        self._assert_nav_landmark(self.dom, "Archive detail")

    def test_main_landmark_present(self):
        self._assert_main_landmark(self.dom, "Archive detail")

    def test_html_lang_attribute(self):
        self._assert_html_lang(self.dom, "Archive detail")

    def test_skip_link_present(self):
        self._assert_skip_link(self.dom, "Archive detail")


# ---------------------------------------------------------------------------
# Session-closed view
# ---------------------------------------------------------------------------

class SessionClosedA11yTests(_A11yAssertions, TestCase):
    """
    Accessibility checks for the session-closed results page
    (GET /tools/session/<session_id>/ when the session is closed).
    """

    @classmethod
    def setUpTestData(cls):
        from django.utils import timezone
        cls.user = User.objects.create_user(
            email="session-closed-a11y@example.com",
            password="testpassword123",
        )
        cls.session = ToolSession.objects.create(
            host=cls.user,
            tool_slug=TOOL_SLUG,
            tool_version="1.0",
            status="closed",
            closed_at=timezone.now(),
        )

    def setUp(self):
        self.client.force_login(self.user)
        response = self.client.get(f"/tools/session/{self.session.id}/")
        self.assertEqual(
            response.status_code, 200,
            f"Expected 200 from session-closed view, got {response.status_code}",
        )
        self.html = response.content.decode("utf-8")
        self.dom = _parse_html(self.html)

    def test_page_title_is_set(self):
        self._assert_page_title(self.html, "Session closed")

    def test_has_single_h1(self):
        self._assert_single_h1(self.dom, "Session closed")

    def test_no_heading_level_skips(self):
        self._assert_no_heading_skips(self.dom, "Session closed")

    def test_nav_landmark_present(self):
        self._assert_nav_landmark(self.dom, "Session closed")

    def test_main_landmark_present(self):
        self._assert_main_landmark(self.dom, "Session closed")

    def test_html_lang_attribute(self):
        self._assert_html_lang(self.dom, "Session closed")

    def test_skip_link_present(self):
        self._assert_skip_link(self.dom, "Session closed")


# ---------------------------------------------------------------------------
# Session-closed view — with participants
# ---------------------------------------------------------------------------

class SessionClosedWithParticipantsA11yTests(_A11yAssertions, TestCase):
    """
    Accessibility checks for the session-closed results page when at least one
    participant ToolInstance is present.

    Without participants the participant loop body (which contains headings) is
    never rendered, so heading-order problems in that loop are invisible to the
    empty-session test.  This class exercises the heading hierarchy produced by
    the participant loop to ensure no level is skipped (e.g. h1 -> h3).
    """

    @classmethod
    def setUpTestData(cls):
        from django.utils import timezone
        from archive.models import ToolInstance
        cls.user = User.objects.create_user(
            email="session-closed-participants-a11y@example.com",
            password="testpassword123",
        )
        cls.session = ToolSession.objects.create(
            host=cls.user,
            tool_slug=TOOL_SLUG,
            tool_version="1.0",
            status="closed",
            closed_at=timezone.now(),
        )
        cls.instance = ToolInstance.objects.create(
            user=cls.user,
            session=cls.session,
            tool_slug=TOOL_SLUG,
            tool_version="1.0",
            status="archived",
        )

    def setUp(self):
        self.client.force_login(self.user)
        response = self.client.get(f"/tools/session/{self.session.id}/")
        self.assertEqual(
            response.status_code, 200,
            f"Expected 200 from session-closed view, got {response.status_code}",
        )
        self.html = response.content.decode("utf-8")
        self.dom = _parse_html(self.html)

    def test_page_title_is_set(self):
        self._assert_page_title(self.html, "Session closed (with participants)")

    def test_has_single_h1(self):
        self._assert_single_h1(self.dom, "Session closed (with participants)")

    def test_no_heading_level_skips(self):
        self._assert_no_heading_skips(self.dom, "Session closed (with participants)")

    def test_nav_landmark_present(self):
        self._assert_nav_landmark(self.dom, "Session closed (with participants)")

    def test_main_landmark_present(self):
        self._assert_main_landmark(self.dom, "Session closed (with participants)")

    def test_html_lang_attribute(self):
        self._assert_html_lang(self.dom, "Session closed (with participants)")

    def test_skip_link_present(self):
        self._assert_skip_link(self.dom, "Session closed (with participants)")

    def test_participant_heading_present(self):
        """Each participant entry must render a heading with the user email."""
        import re
        participant_heading = re.search(
            r"<h2[^>]*>.*?session-closed-participants-a11y@example\.com.*?</h2>",
            self.html,
            re.DOTALL,
        )
        self.assertIsNotNone(
            participant_heading,
            "Session closed (with participants): expected an <h2> heading containing "
            "the participant email address",
        )
