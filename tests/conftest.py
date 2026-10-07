"""
Pytest configuration for the test suite.

Provides a `timer_html` fixture that pre-renders the timer widget template as a
plain string.  Browser tests use page.set_content() to load it directly, so no
live Django server is required — the timer widget is fully client-side once it
has been rendered.

Also provides `archive_detail_html` and `session_closed_html` fixtures that
pre-render those full-page templates using lightweight mock context objects so
that the browser-based axe-core tests can load them without a running server.
"""

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

# pytest-playwright uses an asyncio event loop for its session-scoped browser
# fixture.  Django 6.0 added a strict guard that raises SynchronousOnlyOperation
# whenever synchronous ORM operations (including connection.close() during test
# DB creation) are called from within an async context.  The env var below is
# the sanctioned override for test environments where this is harmless.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

# ---------------------------------------------------------------------------
# Chromium / Playwright library path setup for Replit
# ---------------------------------------------------------------------------
# On Replit the Nix environment exposes REPLIT_LD_LIBRARY_PATH with most of
# Chromium's runtime libraries.  Some Mesa packages put libgbm in a separate
# mesa-libgbm output, however, so detect that output when the supplied paths
# do not contain libgbm.so.1.
#
# If REPLIT_LD_LIBRARY_PATH is not set (e.g. local development outside
# Replit) we fall back to the old heuristic of checking
# /home/runner/.nix-profile/lib.
_replit_lib = os.environ.get("REPLIT_LD_LIBRARY_PATH", "")
_nix_lib = "/home/runner/.nix-profile/lib"
_existing_libs = os.environ.get("LD_LIBRARY_PATH", "")
_library_paths = [
    path
    for path in (*_replit_lib.split(os.pathsep), *_existing_libs.split(os.pathsep))
    if path
]

if not any((Path(path) / "libgbm.so.1").exists() for path in _library_paths):
    _mesa_stores = [
        path for path in _library_paths if "-mesa-" in Path(path).parent.name
    ]
    for _mesa_store in _mesa_stores:
        try:
            _requisites = subprocess.run(
                ["nix-store", "--query", "--requisites", str(Path(_mesa_store).parent)],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.splitlines()
        except (FileNotFoundError, subprocess.SubprocessError):
            continue

        _libgbm_stores = [
            Path(path) / "lib"
            for path in _requisites
            if "-mesa-libgbm-" in Path(path).name
        ]
        if _libgbm_stores:
            _library_paths.insert(0, str(_libgbm_stores[0]))
            break

if not _replit_lib and os.path.isdir(_nix_lib):
    _library_paths.insert(0, _nix_lib)

if _library_paths:
    os.environ["LD_LIBRARY_PATH"] = os.pathsep.join(dict.fromkeys(_library_paths))

import django
import pytest

django.setup()


TEST_PHASES = [
    {"label": "Alpha", "seconds": 3},
    {"label": "Beta", "seconds": 3},
    {"label": "Gamma", "seconds": 3},
]


def _render_timer_test_page(context: dict) -> str:
    """Render the timer test page with the production timer script embedded."""
    from django.contrib.staticfiles import finders
    from django.template.loader import render_to_string

    html = render_to_string("tools/timer_test_page.html", context)
    timer_script_path = finders.find("js/timer.js")
    if not timer_script_path:
        raise RuntimeError("Could not find static/js/timer.js for browser tests")
    timer_script = Path(timer_script_path).read_text(encoding="utf-8")
    return html.replace("</body>", f"<script>{timer_script}</script>\n</body>", 1)


@pytest.fixture(scope="session")
def timer_html() -> str:
    """
    Pre-render the timer widget template with three 3-second phases.
    Tests load this HTML via page.set_content() — no server required.
    """
    tool_meta = SimpleNamespace(
        phases=TEST_PHASES,
        timer_seconds=9,
        title="Test Timer",
    )
    return _render_timer_test_page(
        {"tool_meta": tool_meta, "timer_session_id": None}
    )


@pytest.fixture(scope="session")
def simple_timer_html() -> str:
    """Pre-render the timer widget in simple (no-phases) mode with a 60 s countdown.

    ``phases=None`` selects the plain countdown path inside the timer template.
    Unlike ``timer_html`` — which is also standalone — this fixture uses a
    60-second duration (``timer_html`` uses a longer value) so it is suitable
    for tests that check visibility re-sync behaviour within a short window.
    No session ID is passed, so the status-poll fetch is never triggered.
    """
    tool_meta = SimpleNamespace(
        phases=None,
        timer_seconds=60,
        title="Simple Timer",
    )
    return _render_timer_test_page(
        {"tool_meta": tool_meta, "timer_session_id": None}
    )


# ---------------------------------------------------------------------------
# Session-mode fixtures (clock-skew tests)
# ---------------------------------------------------------------------------

# A fake session UUID used only for rendering URLs in the template.
# The value never hits the database; fetch() calls are intercepted by
# page.route() before they reach any network.  It must be a valid UUID4
# string because Django's URL resolver validates the format before passing
# it to the view.
_TEST_SESSION_ID = "00000000-0000-0000-0000-000000000001"

# Base URL injected via a <base> tag so that the relative status-poll URL
# produced by {% url 'tools:session_status' session_id=... %} resolves to an
# absolute URL that page.route("http://testhost/**") can intercept.
_TEST_BASE = "http://testhost"


def _inject_base(html: str) -> str:
    """Insert a ``<base href="http://testhost/">`` tag into the document head.

    Without this, relative fetch URLs such as ``/tools/session/<id>/status/``
    resolve against the about:blank origin and are never matched by
    ``page.route(_ROUTE_PATTERN)``.
    """
    return html.replace("<head>", f'<head><base href="{_TEST_BASE}/">', 1)


@pytest.fixture(scope="session")
def host_timer_html() -> str:
    """
    Pre-render the phase timer widget with ``is_host=True``.

    Used by the long-pause host reminder tests to verify that the
    ``.timer-paused-badge.long-paused`` class and "Still paused — X min"
    text appear for host views after ``PAUSE_REMINDER_THRESHOLD_SEC`` (300 s)
    have elapsed since the pause.
    """
    tool_meta = SimpleNamespace(
        phases=TEST_PHASES,
        timer_seconds=9,
        title="Host Timer",
    )
    return _render_timer_test_page(
        {"tool_meta": tool_meta, "timer_session_id": None, "is_host": True}
    )


@pytest.fixture(scope="session")
def host_timer_html_threshold_120() -> str:
    """
    Pre-render the phase timer widget with ``is_host=True`` and a custom
    ``pause_reminder_threshold_js`` of 120 seconds.

    Used to verify that the ``long-paused`` class appears at 120 s rather
    than the default 300 s.
    """
    tool_meta = SimpleNamespace(
        phases=TEST_PHASES,
        timer_seconds=9,
        title="Host Timer Threshold 120",
    )
    return _render_timer_test_page(
        {
            "tool_meta": tool_meta,
            "timer_session_id": None,
            "is_host": True,
            "pause_reminder_threshold_js": "120",
        },
    )


@pytest.fixture(scope="session")
def host_timer_html_threshold_null() -> str:
    """
    Pre-render the phase timer widget with ``is_host=True`` and
    ``pause_reminder_threshold_js`` set to ``null`` (disabled).

    Used to verify that the ``long-paused`` class never appears when the
    reminder threshold is disabled, regardless of elapsed pause time.
    """
    tool_meta = SimpleNamespace(
        phases=TEST_PHASES,
        timer_seconds=9,
        title="Host Timer Threshold Null",
    )
    return _render_timer_test_page(
        {
            "tool_meta": tool_meta,
            "timer_session_id": None,
            "is_host": True,
            "pause_reminder_threshold_js": "null",
        },
    )


@pytest.fixture(scope="session")
def host_session_timer_html() -> str:
    """
    Pre-render the phase timer widget with ``is_host=True`` **and** a real
    fake session ID.

    Summary of rendered branches
    ----------------------------
    * ``timer_session_id=None`` → ``{% if not timer_session_id %}`` branch →
      all three buttons (Start / Pause / Reset) rendered — used by
      ``timer_html`` / ``host_timer_html`` fixtures.
    * ``timer_session_id=<uuid>`` AND ``is_host=True`` → ``{% elif is_host %}``
      branch → only Start and Reset buttons rendered (no Pause) — this fixture.
    * ``timer_session_id=<uuid>`` AND ``is_host=False`` → participant view,
      no timer controls — ``session_phase_timer_html`` fixture.

    A ``<base href="http://testhost/">`` tag is injected so that the
    relative start/reset URLs resolve to absolute URLs that can be
    intercepted by ``page.route()`` in the tests.
    """
    tool_meta = SimpleNamespace(
        phases=TEST_PHASES,
        timer_seconds=9,
        title="Host Session Timer",
    )
    html = _render_timer_test_page(
        {
            "tool_meta": tool_meta,
            "timer_session_id": _TEST_SESSION_ID,
            "timer_started_at": None,
            "timer_paused_at": None,
            "is_host": True,
        },
    )
    return _inject_base(html)


@pytest.fixture(scope="session")
def session_phase_timer_html() -> str:
    """
    Phase timer (3 × 3 s) rendered in session mode with a fake session ID.
    The status-poll URL is intercepted by page.route() in the tests; no live
    server is required.
    """
    tool_meta = SimpleNamespace(
        phases=TEST_PHASES,
        timer_seconds=9,
        title="Session Phase Timer",
    )
    html = _render_timer_test_page(
        {
            "tool_meta": tool_meta,
            "timer_session_id": _TEST_SESSION_ID,
            "timer_started_at": None,
            "timer_paused_at": None,
        },
    )
    return _inject_base(html)


@pytest.fixture(scope="session")
def session_long_phase_timer_html() -> str:
    """
    Phase timer (3 × 120 s = 6 minutes per phase) rendered in session mode.

    Used by pause-resume cycle tests (task #91) where the fake-clock advances
    across multiple 4 s poll intervals.  The long phases ensure the timer
    never expires mid-test, avoiding spurious "Now in Beta" / "All phases
    complete" announcements that would break the observer count assertions.
    """
    long_phases = [
        {"label": "Alpha", "seconds": 120},
        {"label": "Beta", "seconds": 120},
        {"label": "Gamma", "seconds": 120},
    ]
    tool_meta = SimpleNamespace(
        phases=long_phases,
        timer_seconds=360,
        title="Session Long Phase Timer",
    )
    html = _render_timer_test_page(
        {
            "tool_meta": tool_meta,
            "timer_session_id": _TEST_SESSION_ID,
            "timer_started_at": None,
            "timer_paused_at": None,
        },
    )
    return _inject_base(html)


@pytest.fixture(scope="session")
def session_simple_timer_html() -> str:
    """
    Simple (no-phases) timer (60 s) rendered in session mode with a fake
    session ID.  The status-poll URL is intercepted by page.route().

    ``simple_timer_html`` and ``timer_html`` are the standalone equivalents
    of this fixture — they render the same template without a session ID so
    no polling is set up and the clock-skew / stale-badge code paths are
    not activated.
    """
    tool_meta = SimpleNamespace(
        phases=None,
        timer_seconds=60,
        title="Session Simple Timer",
    )
    html = _render_timer_test_page(
        {
            "tool_meta": tool_meta,
            "timer_session_id": _TEST_SESSION_ID,
            "timer_started_at": None,
            "timer_paused_at": None,
        },
    )
    return _inject_base(html)


# ---------------------------------------------------------------------------
# Archive detail and session-closed page fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def archive_detail_html() -> str:
    """
    Pre-render the archive detail template using a lightweight mock record.

    No database access is required — all context values are supplied via
    SimpleNamespace objects.  The payload sections and download buttons are
    omitted (payload_output/input and md_file/rtf_file are falsy) so that
    no URL reversals for dynamic PKs are needed.
    """
    from datetime import datetime
    from django.template.loader import render_to_string

    record = SimpleNamespace(
        tool_slug="wise-crowds",
        tool_version="1.0",
        submitted_at=datetime(2025, 1, 15, 10, 30),
        user=SimpleNamespace(email="tester@example.com"),
        payload_output=None,
        payload_input=None,
        md_file=None,
        rtf_file=None,
    )
    return render_to_string("archive/detail.html", {"record": record})


@pytest.fixture(scope="session")
def canvas_html() -> str:
    """
    Pre-render the drawing-canvas partial template wrapped in a minimal HTML
    page so Playwright can load it via page.set_content().

    No database access is required — the canvas widget is entirely client-side
    once the HTML has been rendered.
    """
    from django.template.loader import render_to_string

    fragment = render_to_string("tools/_drawing_canvas.html", {})
    return (
        "<!DOCTYPE html>"
        "<html lang='en'>"
        "<head><meta charset='utf-8'><title>Canvas Test</title></head>"
        f"<body>{fragment}</body>"
        "</html>"
    )


@pytest.fixture(scope="session")
def phase_timer_milestone_html() -> str:
    """
    Pre-render the phase timer with a single 15-second phase.

    This fixture is used by milestone-count tests.  With a 15-second phase the
    only milestone that fires is the 10-second one (MILESTONES = [300, 120, 60,
    30, 10]).  After 5 simulated seconds the remaining time reaches 10 s and
    ``checkMilestones()`` emits "10 seconds remaining in Alpha" exactly once.
    """
    tool_meta = SimpleNamespace(
        phases=[{"label": "Alpha", "seconds": 15}],
        timer_seconds=15,
        title="Milestone Timer",
    )
    return _render_timer_test_page(
        {"tool_meta": tool_meta, "timer_session_id": None}
    )


@pytest.fixture(scope="session")
def phase_timer_long_milestone_html() -> str:
    """
    Pre-render the phase timer with a single 360-second phase.

    This fixture is used by milestone-count tests that must exercise the
    5-minute (300 s) milestone — the highest-priority entry in MILESTONES =
    [300, 120, 60, 30, 10].  With a 360-second phase the 300 s milestone fires
    after 60 simulated seconds of countdown (remaining goes from 361 → 300).
    ``checkMilestones()`` must emit "5 minutes remaining in Alpha" exactly once.
    """
    tool_meta = SimpleNamespace(
        phases=[{"label": "Alpha", "seconds": 360}],
        timer_seconds=360,
        title="Long Milestone Timer",
    )
    return _render_timer_test_page(
        {"tool_meta": tool_meta, "timer_session_id": None}
    )


@pytest.fixture(scope="session")
def archive_detail_with_payload_html() -> str:
    """
    Pre-render the archive detail template with both payload_output and
    payload_input present.

    The template renders extra <h2> sections ("Results" and "Your input") and
    key/value pairs when these fields are non-empty.  This fixture exercises
    those branches so that axe-core and heading-level tests can confirm the
    additional markup is accessible.
    """
    from datetime import datetime
    from django.template.loader import render_to_string

    record = SimpleNamespace(
        tool_slug="wise-crowds",
        tool_version="1.0",
        submitted_at=datetime(2025, 1, 15, 10, 30),
        user=SimpleNamespace(email="tester@example.com"),
        payload_output={
            "summary": "The group identified three key patterns.",
            "themes": "Trust, communication, shared goals.",
        },
        payload_input={
            "challenge": "How do we improve cross-team collaboration?",
            "context": "We are a team of 12 distributed across three time zones.",
        },
        md_file=None,
        rtf_file=None,
    )
    return render_to_string("archive/detail.html", {"record": record})


@pytest.fixture(scope="session")
def session_closed_html() -> str:
    """
    Pre-render the session-closed template using lightweight mock objects.

    The instances list is empty so the {% empty %} branch is taken and no
    per-participant URL reversals are needed.  Download links are suppressed
    by setting md_file and rtf_file to falsy values.
    """
    from datetime import datetime
    from django.template.loader import render_to_string

    tool_meta = SimpleNamespace(title="Wise Crowds")
    session = SimpleNamespace(
        closed_at=datetime(2025, 1, 15, 11, 0),
        host=SimpleNamespace(email="host@example.com"),
        md_file=None,
        rtf_file=None,
    )
    return render_to_string(
        "tools/session_closed.html",
        {"tool_meta": tool_meta, "session": session, "instances": []},
    )
