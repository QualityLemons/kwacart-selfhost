"""Browser checks for the session-status polling lifecycle."""

import json


_ROUTE = "http://testhost/**"


def _open_response(started_at):
    return {
        "status": "open",
        "server_now": started_at,
        "timer_started_at": started_at,
        "timer_paused_at": None,
        "inclusive_pacing": False,
    }


def test_timer_poll_pauses_hidden_and_resumes_immediately(
    page, session_simple_timer_html
):
    calls = []

    def handler(route):
        calls.append(route.request.url)
        route.fulfill(
            content_type="application/json",
            body=json.dumps(_open_response("2025-01-01T00:00:00Z")),
        )

    page.clock.install()
    page.route(_ROUTE, handler)
    page.set_content(session_simple_timer_html, wait_until="domcontentloaded")
    page.wait_for_function("() => window.sessionStatusFetch !== undefined")
    page.wait_for_timeout(50)
    assert len(calls) == 1

    page.evaluate("""
        Object.defineProperty(document, 'hidden', {
            get: () => true, configurable: true
        });
        document.dispatchEvent(new Event('visibilitychange'));
    """)
    page.clock.run_for(30_000)
    page.wait_for_timeout(50)
    assert len(calls) == 1

    page.evaluate("""
        Object.defineProperty(document, 'hidden', {
            get: () => false, configurable: true
        });
        document.dispatchEvent(new Event('visibilitychange'));
    """)
    page.wait_for_timeout(50)
    assert len(calls) == 2


def test_timer_poll_sends_etag_and_accepts_304(page, session_simple_timer_html):
    requests = []
    page.clock.install()
    now = page.evaluate("new Date().toISOString()")

    def handler(route):
        requests.append(route.request.headers)
        if len(requests) == 1:
            route.fulfill(
                status=200,
                headers={"ETag": '"status-v1"'},
                content_type="application/json",
                body=json.dumps(_open_response(now)),
            )
        else:
            route.fulfill(status=304, headers={"ETag": '"status-v1"'}, body="")

    page.route(_ROUTE, handler)
    page.set_content(session_simple_timer_html, wait_until="domcontentloaded")
    page.wait_for_function("() => window.sessionStatusFetch !== undefined")
    page.wait_for_timeout(50)
    page.clock.run_for(4_000)
    page.wait_for_timeout(50)

    assert len(requests) >= 2
    assert requests[1].get("if-none-match") == '"status-v1"'
    assert page.locator(".timer-display").inner_text() == "00:56"


def test_timer_poll_does_not_overlap_requests(page, session_simple_timer_html):
    calls = [0]
    pending = []

    def handler(route):
        calls[0] += 1
        pending.append(route)

    page.clock.install()
    page.route(_ROUTE, handler)
    page.set_content(session_simple_timer_html, wait_until="domcontentloaded")
    page.wait_for_function("() => window.sessionStatusFetch !== undefined")
    page.wait_for_timeout(50)
    assert calls[0] == 1

    page.clock.run_for(20_000)
    page.wait_for_timeout(50)
    assert calls[0] == 1

    pending.pop().fulfill(
        content_type="application/json",
        body=json.dumps(_open_response("2025-01-01T00:00:00Z")),
    )


def test_timer_poll_uses_error_backoff(page, session_simple_timer_html):
    calls = [0]

    def handler(route):
        calls[0] += 1
        route.fulfill(status=503, body="")

    page.clock.install()
    page.evaluate("Math.random = () => 0")
    page.route(_ROUTE, handler)
    page.set_content(session_simple_timer_html, wait_until="domcontentloaded")
    page.wait_for_function("() => window.sessionStatusFetch !== undefined")
    page.wait_for_timeout(50)
    assert calls[0] == 1

    # First error: 4s * 2, with minimum jitter (0.75), gives a 6s retry.
    page.clock.run_for(5_999)
    page.wait_for_timeout(25)
    assert calls[0] == 1
    page.clock.run_for(1)
    page.wait_for_timeout(50)
    assert calls[0] == 2