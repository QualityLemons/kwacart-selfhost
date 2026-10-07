/* ── Guest session poll ── */
/* Polls the session status endpoint every 4 seconds so guest participants
   see a smooth "waiting for host" holding state when the session closes,
   then navigate automatically to the combined results.
   The status URL is read from data-status-url on #session-announcer. */
(function () {

    var ANNOUNCE_DELAY_MS    = 50;
    var POLL_INTERVAL_MS     = 4000;
    var MAX_BACKOFF_MS       = 60000;
    var ERROR_THRESHOLD      = 3;
    /* Grace period before auto-navigating to results.  Long enough for the
       export pipeline to finish and for participants to read the message. */
    var RESULTS_DELAY_MS     = 8000;

    /* ── Element references ── */
    var _announcer = document.getElementById('session-announcer');
    var statusUrl  = _announcer ? _announcer.dataset.statusUrl : null;

    if (!statusUrl) return;

    /* ── State ── */
    var consecutiveErrors = 0;
    var wasReconnecting   = false;
    var sessionClosed     = false;
    var pollTimer         = null;
    var pollInFlight      = false;
    var pollAgain         = false;
    var pageClosed        = false;

    function statusFetch(url, force) {
        if (window.sessionStatusFetch) return window.sessionStatusFetch(url, force);
        var records = {};
        window.sessionStatusFetch = function (requestUrl, forceRequest) {
            var rec = records[requestUrl] || (records[requestUrl] = {});
            if (rec.inFlight) return rec.inFlight;
            if (!forceRequest && rec.result && Date.now() - rec.completedAt < 750) {
                return Promise.resolve(rec.result);
            }
            var headers = {};
            if (rec.etag) headers['If-None-Match'] = rec.etag;
            var controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
            rec.controller = controller;
            rec.inFlight = fetch(requestUrl, {
                credentials: 'same-origin',
                headers: headers,
                signal: controller ? controller.signal : undefined
            }).then(function (resp) {
                if (resp.status === 304) return { data: rec.data, notModified: true };
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                var etag = resp.headers.get('ETag');
                if (etag) rec.etag = etag;
                return resp.json().then(function (data) {
                    rec.data = data;
                    return { data: data, notModified: false };
                });
            }).then(function (result) {
                rec.result = result;
                rec.completedAt = Date.now();
                return result;
            }).finally(function () {
                rec.inFlight = null;
                rec.controller = null;
            });
            return rec.inFlight;
        };
        window.addEventListener('pagehide', function () {
            Object.keys(records).forEach(function (key) {
                if (records[key].controller) records[key].controller.abort();
            });
        }, { once: true });
        return window.sessionStatusFetch(url, force);
    }

    /* ── Hybrid pacing banner elements ── */
    var _earlyPreviewBanner = document.getElementById('ip-early-preview');
    var _vbAacBanner        = document.getElementById('vb-aac-banner');
    var _vbGroupBanner      = document.getElementById('vb-group-banner');

    /* Reacts to inclusive_pacing + timer_started_at + verbal_breakout from each
       poll response, showing the right contextual banner to the participant.
         ip-early-preview: IP active and timer not yet started — participant
                           can start composing before the countdown begins.
         vb-aac-banner:    verbal breakout active + participant is composing —
                           reassures them their digital window is still open.
         vb-group-banner:  verbal breakout active + participant not composing —
                           prompts them to join the spoken discussion. */
    function applyHybridPacing(data) {
        var ip           = !!data.inclusive_pacing;
        var timerStarted = !!data.timer_started_at;
        var vb           = !!data.verbal_breakout;
        var composingBtn = document.getElementById('aac-composing-btn');
        var isComposing  = composingBtn &&
                           composingBtn.getAttribute('aria-pressed') === 'true';
        if (_earlyPreviewBanner) {
            _earlyPreviewBanner.style.display = (ip && !timerStarted) ? '' : 'none';
        }
        if (_vbAacBanner) {
            _vbAacBanner.style.display = (vb && isComposing) ? '' : 'none';
        }
        if (_vbGroupBanner) {
            _vbGroupBanner.style.display = (vb && !isComposing) ? '' : 'none';
        }
    }

    /* ── Announce to screen readers ── */
    function announce(msg) {
        if (!_announcer) return;
        _announcer.textContent = '';
        setTimeout(function () { _announcer.textContent = msg; }, ANNOUNCE_DELAY_MS);
    }

    /* ── Waiting overlay ── */
    function showWaitingState() {
        var overlay = document.getElementById('session-waiting-overlay');
        if (overlay) {
            overlay.removeAttribute('hidden');
        }

        /* Freeze any form fields so the participant cannot submit after close */
        document.querySelectorAll(
            '#session-waiting-overlay ~ * input, ' +
            '#session-waiting-overlay ~ * textarea, ' +
            'form input, form textarea, form select, form button'
        ).forEach(function (el) { el.disabled = true; });

        /* Reveal "View results" button with current URL so it navigates to
           the closed-results render on click */
        var viewBtn = document.getElementById('swl-view-btn');
        if (viewBtn) {
            viewBtn.href = window.location.href;
            viewBtn.removeAttribute('hidden');
        }

        /* Auto-navigate after the grace period */
        setTimeout(function () { window.location.reload(); }, RESULTS_DELAY_MS);
    }

    /* ── Poll ── */
    function nextDelay() {
        if (!consecutiveErrors) return POLL_INTERVAL_MS;
        var bounded = Math.min(
            MAX_BACKOFF_MS,
            POLL_INTERVAL_MS * Math.pow(2, Math.min(consecutiveErrors, 4))
        );
        return Math.round(bounded * (0.75 + Math.random() * 0.25));
    }

    function schedulePoll() {
        clearTimeout(pollTimer);
        pollTimer = null;
        if (pageClosed || sessionClosed || document.hidden || navigator.onLine === false) return;
        pollTimer = setTimeout(poll, nextDelay());
    }

    async function poll(force) {
        if (pageClosed || sessionClosed || document.hidden || navigator.onLine === false) return;
        if (pollInFlight) {
            if (force === true) pollAgain = true;
            return;
        }
        pollInFlight = true;

        try {
            var result = await statusFetch(statusUrl, force === true);
            var data = result.data;
            if (!data) return;

            if (consecutiveErrors >= ERROR_THRESHOLD || wasReconnecting) {
                announce('Reconnected');
                wasReconnecting = false;
            }
            consecutiveErrors = 0;
            applyHybridPacing(data);

            if (data.status === 'closed') {
                sessionClosed = true;
                if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }

                announce('Session has been closed. Preparing your results.');

                /* Flush the in-progress buffer so the latest text is captured */
                if (typeof window.sessionBufferFlush === 'function') {
                    await window.sessionBufferFlush();
                }

                showWaitingState();
            }
        } catch (err) {
            if (pageClosed || (err && err.name === 'AbortError')) return;
            consecutiveErrors += 1;
            if (consecutiveErrors >= ERROR_THRESHOLD && !wasReconnecting) {
                announce('Connection lost. Attempting to reconnect.');
                wasReconnecting = true;
            }
        } finally {
            pollInFlight = false;
            if (pollAgain) {
                pollAgain = false;
                poll(true);
            } else {
                schedulePoll();
            }
        }
    }

    function resumePolling() {
        if (pageClosed || sessionClosed || document.hidden || navigator.onLine === false) return;
        clearTimeout(pollTimer);
        pollTimer = null;
        poll(true);
    }

    document.addEventListener('visibilitychange', function () {
        if (document.hidden) {
            clearTimeout(pollTimer);
            pollTimer = null;
        } else {
            resumePolling();
        }
    });
    window.addEventListener('offline', function () {
        clearTimeout(pollTimer);
        pollTimer = null;
    });
    window.addEventListener('online', resumePolling);
    window.addEventListener('pagehide', function () {
        pageClosed = true;
        clearTimeout(pollTimer);
        pollTimer = null;
    }, { once: true });

    if (!document.hidden) poll();

}());
