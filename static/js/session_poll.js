/* ── Host session poll ── */
/* jshint laxbreak: true */
/* Polls the session status endpoint every 4 seconds, updating the participant
   list and announcing joins, departures, and response submissions.
   Configuration from data attributes and a JSON script element:
     #session-announcer[data-status-url]    — polling endpoint URL
     #initial-responders-data               — JSON array of display names who
                                              had already responded at page load */
(function () {

    var ANNOUNCE_DELAY_MS = 50;
    var POLL_INTERVAL_MS  = 4000;
    var MAX_BACKOFF_MS    = 60000;
    var ERROR_THRESHOLD   = 3;

    /* ── Element references ── */
    var _sessionAnnouncer = document.getElementById('session-announcer');
    var listEl            = document.getElementById('participant-list');
    var countEl           = document.getElementById('participant-count');
    var pollStatusEl      = document.getElementById('poll-status');

    if (!_sessionAnnouncer) return;

    var statusUrl = _sessionAnnouncer.dataset.statusUrl;
    if (!statusUrl) return;

    /* ── Announce to screen readers ── */
    function announce(msg) {
        _sessionAnnouncer.textContent = '';
        setTimeout(function () { _sessionAnnouncer.textContent = msg; }, ANNOUNCE_DELAY_MS);
    }

    /* ── Seed known responders from page-load data ── */
    var _initialDataEl = document.getElementById('initial-responders-data');
    var initialNames   = _initialDataEl ? JSON.parse(_initialDataEl.textContent) : [];
    var knownResponders = new Set(initialNames);

    /* ── State ── */
    var consecutiveErrors    = 0;
    var wasReconnecting      = false;
    var sessionClosed        = false;
    var lastParticipantCount = countEl ? parseInt(countEl.textContent, 10) || 0 : 0;
    var pollTimer            = null;
    var pollInFlight         = false;
    var pollAgain            = false;
    var pageClosed           = false;

    /* Share simultaneous status reads with timer.js and retain the response
       body needed when the server answers a conditional request with 304. */
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
                if (resp.status === 304) {
                    return { data: rec.data, notModified: true };
                }
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

    /* Whether the current page is being viewed by the host.
       Participants need the holding state; the host is redirected by Django. */
    var IS_HOST = _sessionAnnouncer.dataset.isHost === 'true';

    /* ── Hybrid pacing banner elements ── */
    /* These elements are only present in the non-host view; element lookups
       safely return null for the host, so applyHybridPacing no-ops for them. */
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

    /* ── Waiting overlay (non-host participants only) ── */
    var RESULTS_DELAY_MS = 8000;

    function showWaitingState() {
        var overlay = document.getElementById('session-waiting-overlay');
        if (overlay) {
            overlay.removeAttribute('hidden');
            var viewBtn = document.getElementById('swl-view-btn');
            if (viewBtn) {
                viewBtn.href = window.location.href;
                viewBtn.removeAttribute('hidden');
            }
            setTimeout(function () { window.location.reload(); }, RESULTS_DELAY_MS);
        } else {
            setTimeout(function () { window.location.reload(); }, 600);
        }
        /* Freeze form fields */
        document.querySelectorAll('form input, form textarea, form button').forEach(
            function (el) { el.disabled = true; }
        );
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
            if (pollStatusEl) { pollStatusEl.textContent = 'live'; pollStatusEl.style.color = ''; }
            applyHybridPacing(data);

            if (data.status === 'closed') {
                sessionClosed = true;
                if (IS_HOST) {
                    /* Host triggered the close and was already redirected by Django.
                       If they somehow still see this (e.g. second tab), just reload. */
                    if (pollStatusEl) pollStatusEl.textContent = 'session closed \u2014 reloading\u2026';
                    announce('Session has been closed. Reloading the page.');
                    if (typeof window.sessionBufferFlush === 'function') {
                        await window.sessionBufferFlush();
                    }
                    setTimeout(function () { window.location.reload(); }, 600);
                } else {
                    /* Non-host participant: show the calm holding state. */
                    if (pollStatusEl) pollStatusEl.textContent = 'session closed';
                    announce('Session has been closed. Preparing your results.');
                    if (typeof window.sessionBufferFlush === 'function') {
                        await window.sessionBufferFlush();
                    }
                    showWaitingState();
                }
                return;
            }

            var newCount    = data.participants.length;
            var pollMessages = [];

            /* ── Join / leave announcements ── */
            if (newCount !== lastParticipantCount) {
                var diff = newCount - lastParticipantCount;
                if (diff > 0) {
                    pollMessages.push(
                        diff === 1 ?
                            'One participant joined. ' + newCount + ' participants total.' :
                            diff + ' participants joined. ' + newCount + ' participants total.'
                    );
                } else {
                    var removed = -diff;
                    pollMessages.push(
                        removed === 1 ?
                            'One participant left. ' + newCount + ' participants total.' :
                            removed + ' participants left. ' + newCount + ' participants total.'
                    );
                }
                lastParticipantCount = newCount;
            }

            /* ── Response announcements ── */
            var currentNames    = new Set(data.participants.map(function (p) { return p.display_name; }));
            var newKnownResponders = new Set();
            knownResponders.forEach(function (n) { if (currentNames.has(n)) newKnownResponders.add(n); });
            data.participants.forEach(function (p) {
                if (p.has_response) newKnownResponders.add(p.display_name);
            });

            var totalParticipants = data.participants.length;
            var totalResponded    = data.participants.filter(function (p) { return p.has_response; }).length;
            var newResponders     = data.participants.filter(function (p) {
                return p.has_response && !knownResponders.has(p.display_name);
            });

            if (newResponders.length === 1) {
                pollMessages.push(
                    newResponders[0].display_name + ' saved their response. ' +
                    totalResponded + ' of ' + totalParticipants + ' participants have responded.'
                );
            } else if (newResponders.length > 1) {
                pollMessages.push(
                    newResponders.length + ' participants saved their responses. ' +
                    totalResponded + ' of ' + totalParticipants + ' participants have responded.'
                );
            }
            knownResponders = newKnownResponders;

            if (pollMessages.length > 0) announce(pollMessages.join(' '));

            /* ── Update participant list DOM ── */
            if (countEl) countEl.textContent = newCount;
            if (listEl) {
                listEl.innerHTML = data.participants.map(function (p) {
                    var hostTag = p.is_host ? ' <span style="color:#64748b;">(host)</span>' : '';
                    var composingTag = p.is_composing
                        ? ' \u2014 <span style="color:#b45309; font-weight:600;"'
                          + ' title="Using AAC or external composition software">'
                          + '\uD83D\uDDE3\uFE0F Composing\u2026</span>'
                        : '';
                    var respTag = p.has_response ?
                        ' \u2014 <span style="color:#15803d;">response saved</span>' : '';
                    var safeName = p.display_name
                        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                    return '<li>' + safeName + hostTag + composingTag + respTag + '</li>';
                }).join('');
            }
        } catch (err) {
            if (pageClosed || (err && err.name === 'AbortError')) return;
            consecutiveErrors += 1;
            if (consecutiveErrors >= ERROR_THRESHOLD) {
                if (!wasReconnecting) {
                    announce('Connection lost. Attempting to reconnect.');
                    wasReconnecting = true;
                }
                if (pollStatusEl) { pollStatusEl.textContent = 'reconnecting\u2026'; pollStatusEl.style.color = '#b45309'; }
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
