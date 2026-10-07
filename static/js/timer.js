/* ── Timer widget ── */
/* jshint esversion: 11, laxbreak: true, shadow: true, -W082, -W058 */
/* Drives the shared timer widget used on draft, session-open, and guest pages.
   IS_HOST and the pause-reminder threshold are read from data attributes on the
   .timer-widget element so no Django template variables are needed in this file:
     data-is-host            "true" | "false"
     data-pause-threshold    integer seconds or "null" */
(function () {

    /* Delay between clearing and repopulating an aria-live region.
       50 ms gives NVDA/JAWS/VoiceOver enough time to register the cleared state
       before the new text arrives, preventing swallowed announcements. */
    const ANNOUNCE_DELAY_MS = 50;

    const widget = document.querySelector('.timer-widget');
    if (!widget) return;

    /* ── Config from data attributes ── */
    const IS_HOST = widget.dataset.isHost === 'true';
    let pauseReminderThresholdSec = widget.dataset.pauseThreshold === 'null'
        ? null
        : (parseInt(widget.dataset.pauseThreshold, 10) || 300);

    /* ── Element references ── */
    const display        = widget.querySelector('.timer-display');
    const pausedBadge    = widget.querySelector('.timer-paused-badge');
    const staleBadge     = widget.querySelector('.timer-stale-badge');
    const reconnectToast = widget.querySelector('.timer-reconnect-toast');
    const startBtn       = widget.querySelector('.timer-start');
    const pauseBtn       = widget.querySelector('.timer-pause');
    const resetBtn       = widget.querySelector('.timer-reset');
    const calmBlock      = widget.querySelector('.calm-block');
    const calmBlockLabel = widget.querySelector('.calm-block__label');
    const calmToggleBtn  = widget.querySelector('.calm-timer-toggle');

    /* ── Internal state ── */
    let intervalId        = null;
    let pauseTickId       = null;
    let _pausedAtMs       = null;
    let _wasPaused        = null;
    let pollFailCount     = 0;
    let _wasStale         = false;
    let _reconnectToastId = null;
    const POLL_FAIL_THRESHOLD = 3;

    /* ── Reconnect toast ── */
    function showReconnectToast() {
        if (!reconnectToast) return;
        if (_reconnectToastId) clearTimeout(_reconnectToastId);
        reconnectToast.textContent = '\u2713 Reconnected \u2014 syncing timer';
        reconnectToast.removeAttribute('hidden');
        _reconnectToastId = setTimeout(function () {
            reconnectToast.setAttribute('hidden', '');
            _reconnectToastId = null;
        }, 4000);
    }

    /* ── Stale indicator ── */
    function setStaleIndicator(isStale) {
        if (!staleBadge) return;
        if (isStale) {
            staleBadge.removeAttribute('hidden');
            _wasStale = true;
        } else {
            staleBadge.setAttribute('hidden', '');
            if (_wasStale) {
                _wasStale = false;
                showReconnectToast();
            }
        }
    }

    /* ── Paused badge ── */
    function updatePausedText() {
        if (!pausedBadge) return;
        if (!_pausedAtMs) {
            pausedBadge.textContent = '\u25ae\u25ae Paused';
            pausedBadge.classList.remove('long-paused');
            return;
        }
        const elapsedSec = Math.floor((Date.now() - _pausedAtMs) / 1000);
        const isLongPause = IS_HOST && pauseReminderThresholdSec !== null && elapsedSec >= pauseReminderThresholdSec;
        pausedBadge.classList.toggle('long-paused', isLongPause);
        if (elapsedSec < 60) {
            pausedBadge.textContent = '\u25ae\u25ae Paused \u00b7 ' + elapsedSec + 's';
        } else {
            const mins = Math.floor(elapsedSec / 60);
            if (isLongPause) {
                pausedBadge.textContent = '\u25ae\u25ae Still paused \u2014 ' + mins + ' min';
            } else {
                pausedBadge.textContent = '\u25ae\u25ae Paused \u00b7 ' + mins + ' min';
            }
        }
    }

    /* ── Expose threshold setter for pause_reminder.js ── */
    window.setTimerPauseReminderThreshold = function (newSec) {
        pauseReminderThresholdSec = (newSec === '' || newSec == null) ? null : +newSec;
        if (pauseTickId) updatePausedText();
    };

    function setPausedIndicator(isPaused, pausedAtMs, skipAnnounce) {
        if (!pausedBadge) return;
        const _announcer = document.getElementById('phase-announcer');
        if (isPaused) {
            _pausedAtMs = pausedAtMs || null;
            pausedBadge.removeAttribute('hidden');
            if (!skipAnnounce && _wasPaused === false && _announcer) {
                _announcer.textContent = '';
                setTimeout(function () { _announcer.textContent = 'Timer paused'; }, ANNOUNCE_DELAY_MS);
            }
            if (pauseTickId) clearInterval(pauseTickId);
            updatePausedText();
            pauseTickId = setInterval(updatePausedText, 1000);
        } else {
            _pausedAtMs = null;
            pausedBadge.setAttribute('hidden', '');
            pausedBadge.textContent = '\u25ae\u25ae Paused';
            pausedBadge.classList.remove('long-paused');
            if (pauseTickId) { clearInterval(pauseTickId); pauseTickId = null; }
            if (!skipAnnounce && _wasPaused === true && _announcer) {
                _announcer.textContent = '';
                setTimeout(function () { _announcer.textContent = 'Timer resumed'; }, ANNOUNCE_DELAY_MS);
            }
        }
        _wasPaused = isPaused;
    }

    /* ── URL helpers ── */
    const statusUrl      = widget.dataset.statusUrl      || null;
    const timerStartUrl  = widget.dataset.timerStartUrl  || null;
    const timerResetUrl  = widget.dataset.timerResetUrl  || null;
    const sessionMode    = !!statusUrl;

    /* Status requests are shared with session_poll.js/guest_poll.js when those
       scripts are present. This coalesces their normally simultaneous reads
       and keeps the last body available for an ETag 304 response. */
    function statusFetch(url, force) {
        if (window.sessionStatusFetch) return window.sessionStatusFetch(url, force);
        const records = {};
        window.sessionStatusFetch = function (requestUrl, forceRequest) {
            const rec = records[requestUrl] || (records[requestUrl] = {});
            if (rec.inFlight) return rec.inFlight;
            if (!forceRequest && rec.result && Date.now() - rec.completedAt < 750) {
                return Promise.resolve(rec.result);
            }
            const headers = {};
            if (rec.etag) headers['If-None-Match'] = rec.etag;
            const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
            rec.controller = controller;
            rec.inFlight = fetch(requestUrl, {
                credentials: 'same-origin',
                headers: headers,
                signal: controller ? controller.signal : undefined,
            }).then(function (resp) {
                if (resp.status === 304) return { data: rec.data, notModified: true };
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                const etag = resp.headers.get('ETag');
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

    function startStatusPolling(onData, onReturn, shouldSkip) {
        const BASE_DELAY = 4000;
        const MAX_DELAY  = 60000;
        let timeoutId = null;
        let inFlight = false;
        let stopped = false;
        let rerunRequested = false;

        function nextDelay() {
            if (!pollFailCount) return BASE_DELAY;
            const bounded = Math.min(
                MAX_DELAY,
                BASE_DELAY * Math.pow(2, Math.min(pollFailCount, 4))
            );
            return Math.round(bounded * (0.75 + Math.random() * 0.25));
        }

        function schedule() {
            clearTimeout(timeoutId);
            timeoutId = null;
            if (stopped || document.hidden || navigator.onLine === false) return;
            timeoutId = setTimeout(poll, nextDelay());
        }

        async function poll(force) {
            if (stopped || document.hidden || navigator.onLine === false) return;
            if (inFlight) {
                if (force === true) rerunRequested = true;
                return;
            }
            if (shouldSkip && shouldSkip()) {
                schedule();
                return;
            }
            inFlight = true;
            try {
                const result = await statusFetch(statusUrl, force === true);
                if (result.data) {
                    pollFailCount = 0;
                    setStaleIndicator(false);
                    onData(result.data, result.notModified);
                    if (result.data.status === 'closed') stopped = true;
                }
            } catch (e) {
                if (!stopped && (!e || e.name !== 'AbortError')) {
                    pollFailCount += 1;
                    if (pollFailCount >= POLL_FAIL_THRESHOLD) setStaleIndicator(true);
                }
            } finally {
                inFlight = false;
                if (rerunRequested) {
                    rerunRequested = false;
                    poll(true);
                } else {
                    schedule();
                }
            }
        }

        function resume() {
            if (stopped || document.hidden || navigator.onLine === false) return;
            clearTimeout(timeoutId);
            timeoutId = null;
            if (onReturn) onReturn();
            poll(true);
        }

        window.addEventListener('offline', function () {
            clearTimeout(timeoutId);
            timeoutId = null;
            setStaleIndicator(true);
        });
        window.addEventListener('online', resume);
        document.addEventListener('visibilitychange', function () {
            if (document.hidden) {
                clearTimeout(timeoutId);
                timeoutId = null;
            } else {
                resume();
            }
        });
        window.addEventListener('pagehide', function () {
            stopped = true;
            clearTimeout(timeoutId);
            timeoutId = null;
        }, { once: true });

        if (!document.hidden) poll();
    }

    /* ── Format seconds as MM:SS ── */
    function fmt(s) {
        const m   = Math.floor(s / 60);
        const sec = s % 60;
        return String(m).padStart(2, '0') + ':' + String(sec).padStart(2, '0');
    }

    /* ── Optional audio beep ── */
    function beep(frequency, duration, count) {
        try {
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            const ctx  = new AudioCtx();
            for (let i = 0; i < (count || 1); i++) {
                const osc  = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.frequency.value = frequency || 880;
                const start = ctx.currentTime + i * (duration || 0.4) * 1.4;
                gain.gain.setValueAtTime(0.25, start);
                gain.gain.exponentialRampToValueAtTime(0.001, start + (duration || 0.4));
                osc.start(start);
                osc.stop(start + (duration || 0.4));
            }
        } catch (e) {}
    }

    /* ── CSRF token helper ── */
    /* The string-splitting technique used here to read a cookie by name
     * is taken from the Django CSRF documentation:
     * https://docs.djangoproject.com/en/stable/howto/csrf/ */
    function getCsrf() {
        const val   = '; ' + document.cookie;
        const parts = val.split('; csrftoken=');
        if (parts.length === 2) return parts.pop().split(';').shift();
        return '';
    }

    /* ── Authenticated fetch POST ── */
    async function postJson(url) {
        const resp = await fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'X-CSRFToken': getCsrf(), 'Content-Type': 'application/json' },
        });
        return resp.json();
    }

    /* ── Calm timer ─────────────────────────────────────────────────────────
       Participants can replace the digit countdown with a colour-only block
       that drifts from green → amber → red as time elapses.
       The preference is stored in localStorage and restored on every page
       load.  Hosts always see digits; the toggle is not wired up for them.  */

    const CALM_KEY = 'kwacart_calm_timer';
    let calmMode   = false;

    function calmColor(pct) {
        pct = Math.max(0, Math.min(1, pct));
        var r, g, b;
        if (pct <= 0.5) {
            var t = pct * 2;
            r = Math.round(22  + (217 - 22)  * t);
            g = Math.round(163 + (119 - 163) * t);
            b = Math.round(74  + (6   - 74)  * t);
        } else {
            var t = (pct - 0.5) * 2;
            r = Math.round(217 + (220 - 217) * t);
            g = Math.round(119 + (38  - 119) * t);
            b = Math.round(6   + (38  - 6)   * t);
        }
        return 'rgb(' + r + ',' + g + ',' + b + ')';
    }

    function updateCalmBlock(rem, tot) {
        if (!calmBlock) return;
        const pct = tot > 0 ? Math.max(0, Math.min(1, (tot - rem) / tot)) : 0;
        calmBlock.style.backgroundColor = calmColor(pct);
        if (!calmBlockLabel) return;
        if (rem === 0) {
            calmBlockLabel.textContent = 'Time\u2019s up';
        } else if (pct === 0) {
            calmBlockLabel.textContent = 'Not started';
        } else {
            calmBlockLabel.textContent = 'Session in progress';
        }
    }

    function setCalmMode(active) {
        calmMode = active;
        if (display)   display.hidden   = active;
        if (calmBlock) calmBlock.hidden = !active;
        if (calmToggleBtn) {
            calmToggleBtn.setAttribute('aria-pressed', String(active));
            calmToggleBtn.textContent = active ? 'Show countdown' : 'Calm timer';
        }
        try {
            if (active) { localStorage.setItem(CALM_KEY, '1'); }
            else        { localStorage.removeItem(CALM_KEY);   }
        } catch (_) {}
    }

    if (!IS_HOST) {
        let _savedCalm = false;
        try { _savedCalm = localStorage.getItem(CALM_KEY) === '1'; } catch (_) {}
        if (_savedCalm) setCalmMode(true);
    }

    if (calmToggleBtn && !IS_HOST) {
        calmToggleBtn.addEventListener('click', function () {
            setCalmMode(!calmMode);
        });
    }

    /* ── Inclusive Pacing / extended personal timer ──────────────────────────
       When the host enables inclusive pacing, non-host participants see a panel
       with an "Activate my extended time" button.  Their personal countdown is
       computed entirely client-side: group_total × multiplier seconds from
       timer_started_at.  It runs independently — the group timer can expire
       while the participant's personal countdown is still ticking.
       The setting is broadcast on every session_status poll, so participants
       react within ≤4 seconds of the host toggling it.                       */

    const extPanel       = document.querySelector('.ext-timer-panel');
    const extDisplay     = document.querySelector('.ext-timer-display');
    const extRunning     = document.querySelector('.ext-timer-running');
    const extActivateBtn = document.querySelector('.ext-timer-activate');
    const extMultLabel   = document.querySelector('.ext-multiplier-label');

    let extActive     = false;
    let extIntervalId = null;
    let extRemaining  = 0;
    let extTotalSec   = 0;
    let extMultiplier = parseInt(widget.dataset.inclusiveMultiplier, 10) || 3;

    function renderExtDisplay() {
        if (!extDisplay) return;
        const s = extRemaining;
        let text;
        if (s >= 3600) {
            const h   = Math.floor(s / 3600);
            const m   = Math.floor((s % 3600) / 60);
            const sec = s % 60;
            text = h + ':' + String(m).padStart(2, '0') + ':' + String(sec).padStart(2, '0');
        } else {
            text = fmt(s);
        }
        extDisplay.textContent = text;
        extDisplay.classList.toggle('ext-expired', s === 0);
        if (extActive) updateCalmBlock(s, extTotalSec);
    }

    function tickExt() {
        if (extRemaining > 0) {
            extRemaining -= 1;
            renderExtDisplay();
        }
        if (extRemaining === 0) {
            clearInterval(extIntervalId);
            extIntervalId = null;
        }
    }

    function syncExtTimer(timerStartedAt, timerPausedAt, groupTotal) {
        if (!timerStartedAt) return;
        extTotalSec = groupTotal * extMultiplier;
        const referenceTime = timerPausedAt
            ? new Date(timerPausedAt).getTime()
            : Date.now();
        const elapsedSec = Math.floor(
            (referenceTime - new Date(timerStartedAt).getTime()) / 1000
        );
        extRemaining = Math.max(0, extTotalSec - elapsedSec);
        renderExtDisplay();
        if (timerPausedAt) {
            clearInterval(extIntervalId);
            extIntervalId = null;
        } else if (extRemaining > 0 && !extIntervalId) {
            extIntervalId = setInterval(tickExt, 1000);
        } else if (extRemaining === 0) {
            clearInterval(extIntervalId);
            extIntervalId = null;
        }
    }

    function applyInclusivePacing(ipActive, ipMultiplier, timerStartedAt, timerPausedAt, groupTotal) {
        if (IS_HOST) return;
        extMultiplier = ipMultiplier || 3;
        if (extPanel)    extPanel.hidden = !ipActive;
        if (extMultLabel) extMultLabel.textContent = extMultiplier + '\u00d7';
        if (extActive) syncExtTimer(timerStartedAt, timerPausedAt, groupTotal);
    }

    if (extActivateBtn && !IS_HOST) {
        extActivateBtn.addEventListener('click', function () {
            extActive = !extActive;
            extActivateBtn.setAttribute('aria-pressed', String(extActive));
            extActivateBtn.textContent = extActive
                ? 'Back to group timer'
                : 'Activate my extended time';
            if (extRunning) extRunning.hidden = !extActive;
            if (display) {
                display.style.opacity       = extActive ? '0.35' : '';
                display.style.pointerEvents = extActive ? 'none'  : '';
            }
            if (!extActive) {
                clearInterval(extIntervalId);
                extIntervalId = null;
                extRemaining  = 0;
                if (extDisplay) extDisplay.textContent = '--:--';
                if (extDisplay) extDisplay.classList.remove('ext-expired');
            }
        });
    }

    /* ── Phase data (multi-phase tools) ── */
    const phaseDataEl = document.getElementById('phase-data');
    const phases      = phaseDataEl ? JSON.parse(phaseDataEl.textContent) : null;

    /* ══════════════════════════════════════════════════════════════
       MULTI-PHASE TIMER
    ══════════════════════════════════════════════════════════════ */
    if (phases && phases.length) {

        const phaseLabel    = widget.querySelector('.timer-phase-label');
        const phaseProgress = widget.querySelector('.timer-phase-progress');
        const progressBar   = widget.querySelector('.phase-progress-bar');
        let phaseIdx  = 0;
        let remaining = phases[0].seconds;

        function totalSeconds() {
            return phases.reduce((s, p) => s + p.seconds, 0);
        }

        const announcer = document.getElementById('phase-announcer');

        function announce(msg) {
            if (!announcer) return;
            announcer.textContent = '';
            setTimeout(function () { announcer.textContent = msg; }, ANNOUNCE_DELAY_MS);
        }

        const MILESTONES = [300, 120, 60, 30, 10];
        let announcedMilestones = new Set();
        let firstSync        = true;
        let announceOnReturn = false;
        let clockSkew        = 0;

        function milestoneLabel(s) {
            if (s >= 60) {
                const m = s / 60;
                return m === 1 ? '1 minute' : m + ' minutes';
            }
            return s + ' seconds';
        }

        function approxLabel(s) {
            if (s >= 60) {
                const m = Math.round(s / 60);
                return m === 1 ? 'about 1 minute' : 'about ' + m + ' minutes';
            }
            return 'about ' + s + ' seconds';
        }

        function checkMilestones() {
            MILESTONES.forEach(function (ms) {
                if (remaining === ms && !announcedMilestones.has(ms)) {
                    announcedMilestones.add(ms);
                    announce(milestoneLabel(ms) + ' remaining in ' + phases[phaseIdx].label);
                }
            });
        }

        /* ── Progress bar segments (built once, proportional to phase duration) ── */
        let segmentEls = [];
        if (progressBar && phases.length) {
            const total = totalSeconds();
            phases.forEach(function (phase, i) {
                const seg  = document.createElement('div');
                seg.className = 'phase-segment upcoming';
                seg.style.width = ((phase.seconds / total) * 100).toFixed(2) + '%';
                seg.title = phase.label;
                seg.setAttribute('role', 'img');
                seg.setAttribute('aria-label', phase.label + ' \u2014 upcoming');
                const fill = document.createElement('div');
                fill.className   = 'phase-segment-fill';
                fill.style.width = '0%';
                seg.appendChild(fill);
                progressBar.appendChild(seg);
                segmentEls.push(seg);
            });
        }

        let initialRender = true;

        function renderProgressBar() {
            const phaseDuration = phases[phaseIdx].seconds;
            const elapsed  = phaseDuration - remaining;
            const fillPct  = phaseDuration > 0 ? ((elapsed / phaseDuration) * 100).toFixed(1) : 0;
            segmentEls.forEach(function (seg, i) {
                seg.classList.remove('done', 'active', 'upcoming');
                const fill  = seg.querySelector('.phase-segment-fill');
                const label = phases[i].label;
                if (initialRender && fill) fill.style.transition = 'none';
                if (i < phaseIdx) {
                    seg.classList.add('done');
                    seg.setAttribute('aria-label', label + ' \u2014 completed');
                    if (fill) fill.style.width = '100%';
                } else if (i === phaseIdx) {
                    if (remaining === 0) {
                        seg.classList.add('done');
                        seg.setAttribute('aria-label', label + ' \u2014 completed');
                        if (fill) fill.style.width = '100%';
                    } else {
                        seg.classList.add('active');
                        seg.setAttribute('aria-label', label + ' \u2014 active');
                        if (fill) fill.style.width = fillPct + '%';
                    }
                } else {
                    seg.classList.add('upcoming');
                    seg.setAttribute('aria-label', label + ' \u2014 upcoming');
                    if (fill) fill.style.width = '0%';
                }
            });
            if (initialRender) {
                initialRender = false;
                requestAnimationFrame(function () {
                    requestAnimationFrame(function () {
                        segmentEls.forEach(function (seg) {
                            const fill = seg.querySelector('.phase-segment-fill');
                            if (fill) fill.style.transition = '';
                        });
                    });
                });
            }
        }

        function resetToInitial(announceReset) {
            clearInterval(intervalId); intervalId = null;
            phaseIdx  = 0;
            remaining = phases[0].seconds;
            announcedMilestones = new Set();
            if (startBtn) { startBtn.disabled = false; startBtn.textContent = 'Start'; }
            setPausedIndicator(false, undefined, true);
            if (announceReset) announce('Timer reset');
            renderPhase();
        }

        function updateProgressText() {
            if (phaseProgress) phaseProgress.textContent = 'Phase ' + (phaseIdx + 1) + ' of ' + phases.length;
        }

        function renderPhase() {
            const phase = phases[phaseIdx];
            if (phaseLabel) phaseLabel.textContent = phase.label;
            updateProgressText();
            display.textContent = fmt(remaining);
            const isLastPhase = phaseIdx === phases.length - 1;
            display.classList.toggle('warning', remaining > 0 && remaining <= 10);
            display.classList.toggle('expired',  remaining === 0 && isLastPhase);
            renderProgressBar();
            if (!extActive) {
                let _totalRem = remaining;
                for (let _pi = phaseIdx + 1; _pi < phases.length; _pi++) _totalRem += phases[_pi].seconds;
                updateCalmBlock(_totalRem, totalSeconds());
            }
        }

        function flashLabel() {
            if (!phaseLabel) return;
            phaseLabel.classList.add('phase-flash');
            setTimeout(() => phaseLabel.classList.remove('phase-flash'), 1200);
        }

        function tick() {
            if (remaining > 0) {
                remaining -= 1;
                renderPhase();
                checkMilestones();
            }
            if (remaining === 0) {
                if (phaseIdx < phases.length - 1) {
                    phaseIdx  += 1;
                    remaining  = phases[phaseIdx].seconds;
                    announcedMilestones = new Set();
                    beep(880, 0.35, 1);
                    flashLabel();
                    announce('Now entering Phase ' + (phaseIdx + 1) + ' \u2014 ' + phases[phaseIdx].label);
                    renderPhase();
                } else {
                    clearInterval(intervalId); intervalId = null;
                    if (startBtn) { startBtn.disabled = false; startBtn.textContent = 'Start'; }
                    beep(660, 0.4, 2);
                    announce('All phases complete');
                    renderPhase();
                }
            }
        }

        function applyServerTimestamp(timerStartedAt, timerPausedAt) {
            if (!timerStartedAt) { resetToInitial(); return; }
            const returningToTab = announceOnReturn;
            const referenceTime = timerPausedAt
                ? new Date(timerPausedAt).getTime()
                : Date.now() + clockSkew;
            const elapsedSec = Math.floor((referenceTime - new Date(timerStartedAt).getTime()) / 1000);
            let acc = 0, newPhaseIdx = phases.length - 1, newRemaining = 0;
            for (let i = 0; i < phases.length; i++) {
                if (elapsedSec < acc + phases[i].seconds) {
                    newPhaseIdx   = i;
                    newRemaining  = phases[i].seconds - (elapsedSec - acc);
                    break;
                }
                acc += phases[i].seconds;
            }
            const prevPhaseIdx = phaseIdx;
            phaseIdx  = newPhaseIdx;
            remaining = newRemaining;
            if (newPhaseIdx !== prevPhaseIdx) {
                announcedMilestones = new Set();
                flashLabel();
                if (!returningToTab) {
                    announce('Now entering Phase ' + (phaseIdx + 1) + ' \u2014 ' + phases[phaseIdx].label);
                }
            }
            MILESTONES.forEach(function (ms) { if (remaining < ms) announcedMilestones.add(ms); });
            const _wasFSPaused = firstSync && !!timerStartedAt && remaining > 0 && !!timerPausedAt;
            if (!returningToTab && firstSync && timerStartedAt && remaining > 0) {
                if (timerPausedAt) {
                    announce('Timer is paused \u2014 ' + approxLabel(remaining) + ' remaining in ' + phases[phaseIdx].label);
                } else {
                    announce(approxLabel(remaining) + ' remaining in ' + phases[phaseIdx].label);
                }
            }
            if (announceOnReturn) {
                announceOnReturn = false;
                if (!timerPausedAt && remaining > 0) {
                    announce(approxLabel(remaining) + ' remaining in ' + phases[phaseIdx].label);
                }
            }
            firstSync = false;
            renderPhase();
            if (timerPausedAt) {
                clearInterval(intervalId); intervalId = null;
                if (startBtn) { startBtn.disabled = false; startBtn.textContent = 'Resume'; }
                setPausedIndicator(true, new Date(timerPausedAt).getTime(), _wasFSPaused);
            } else {
                setPausedIndicator(false);
                if (remaining > 0 && !intervalId) {
                    intervalId = setInterval(tick, 1000);
                    if (startBtn) { startBtn.disabled = true; startBtn.textContent = 'Running\u2026'; }
                } else if (remaining === 0 && intervalId) {
                    clearInterval(intervalId); intervalId = null;
                    if (startBtn) { startBtn.disabled = false; startBtn.textContent = 'Start'; }
                    announce('All phases complete');
                }
            }
        }

        if (sessionMode) {
            const _initStartedEl = document.getElementById('timer-started-at');
            const _initPausedEl  = document.getElementById('timer-paused-at');
            if (_initStartedEl) {
                applyServerTimestamp(
                    JSON.parse(_initStartedEl.textContent),
                    _initPausedEl ? JSON.parse(_initPausedEl.textContent) : null
                );
            }
        }

        let pauseIntent     = false;
        let virtualStartedAt = null;

        if (sessionMode) {
            startStatusPolling(function (data, notModified) {
                    if (pauseIntent) { pauseIntent = false; return; }
                    if (!notModified && data.server_now) {
                        clockSkew = new Date(data.server_now).getTime() - Date.now();
                    }
                    applyServerTimestamp(data.timer_started_at, data.timer_paused_at);
                    applyInclusivePacing(
                        data.inclusive_pacing            || false,
                        data.inclusive_pacing_multiplier || 3,
                        data.timer_started_at,
                        data.timer_paused_at,
                        totalSeconds()
                    );
                }, function () {
                    initialRender    = true;
                    announceOnReturn = true;
                }, function () {
                    if (!pauseIntent) return false;
                    pauseIntent = false;
                    return true;
                });
        } else {
            document.addEventListener('visibilitychange', function () {
                if (!document.hidden && intervalId && virtualStartedAt) {
                    initialRender = true;
                    announceOnReturn = true;
                    applyServerTimestamp(new Date(virtualStartedAt).toISOString(), null);
                }
            });
        }

        if (startBtn) {
            startBtn.addEventListener('click', async () => {
                if (intervalId) return;
                if (phaseIdx >= phases.length - 1 && remaining === 0) {
                    phaseIdx  = 0;
                    remaining = phases[0].seconds;
                    renderPhase();
                }
                if (sessionMode) {
                    pauseIntent = true;
                    try {
                        const data = await postJson(timerStartUrl);
                        if (data.timer_started_at) {
                            pauseIntent = false;
                            applyServerTimestamp(data.timer_started_at);
                            return;
                        }
                    } catch (e) { pauseIntent = false; }
                }
                setPausedIndicator(false);
                intervalId = setInterval(tick, 1000);
                if (startBtn) { startBtn.disabled = true; startBtn.textContent = 'Running\u2026'; }
                if (pauseBtn)  pauseBtn.disabled  = false;
                if (!sessionMode) {
                    var _elapsed = 0;
                    for (var _i = 0; _i < phaseIdx; _i++) _elapsed += phases[_i].seconds;
                    _elapsed += phases[phaseIdx].seconds - remaining;
                    virtualStartedAt = Date.now() - _elapsed * 1000;
                }
            });
        }

        if (pauseBtn) {
            pauseBtn.addEventListener('click', () => {
                if (!intervalId) return;
                pauseIntent = true;
                clearInterval(intervalId); intervalId = null;
                if (startBtn) { startBtn.disabled = false; startBtn.textContent = 'Resume'; }
                pauseBtn.disabled = true;
                setPausedIndicator(true, Date.now());
                if (!sessionMode) virtualStartedAt = null;
            });
        }

        if (resetBtn) {
            resetBtn.addEventListener('click', async () => {
                if (sessionMode) pauseIntent = true;
                virtualStartedAt = null;
                resetToInitial(true);
                if (sessionMode) { try { await postJson(timerResetUrl); } catch (e) {} }
            });
        }

        renderPhase();

    /* ══════════════════════════════════════════════════════════════
       SINGLE-PHASE TIMER
    ══════════════════════════════════════════════════════════════ */
    } else {

        const total     = parseInt(widget.dataset.duration, 10) || 60;
        let remaining   = total;

        const _simpleAnnouncer = document.getElementById('phase-announcer');
        function announce(msg) {
            if (!_simpleAnnouncer) return;
            _simpleAnnouncer.textContent = '';
            setTimeout(function () { _simpleAnnouncer.textContent = msg; }, ANNOUNCE_DELAY_MS);
        }

        const MILESTONES = [300, 120, 60, 30, 10];
        let announcedMilestones = new Set();
        let firstSync        = true;
        let announceOnReturn = false;
        let clockSkew        = 0;

        function milestoneLabel(s) {
            if (s >= 60) {
                const m = s / 60;
                return m === 1 ? '1 minute' : m + ' minutes';
            }
            return s + ' seconds';
        }

        function approxLabel(s) {
            if (s >= 60) {
                const m = Math.round(s / 60);
                return m === 1 ? 'about 1 minute' : 'about ' + m + ' minutes';
            }
            return 'about ' + s + ' seconds';
        }

        function checkMilestones() {
            MILESTONES.forEach(function (ms) {
                if (remaining === ms && !announcedMilestones.has(ms)) {
                    announcedMilestones.add(ms);
                    announce(milestoneLabel(ms) + ' remaining');
                }
            });
        }

        function resetToInitial(announceReset) {
            clearInterval(intervalId); intervalId = null;
            remaining           = total;
            announcedMilestones = new Set();
            if (startBtn) { startBtn.disabled = false; startBtn.textContent = 'Start'; }
            if (pauseBtn)   pauseBtn.disabled  = true;
            setPausedIndicator(false, undefined, true);
            if (announceReset) announce('Timer reset');
            render();
        }

        function render() {
            display.textContent = fmt(remaining);
            display.classList.toggle('warning', remaining > 0 && remaining <= 10);
            display.classList.toggle('expired',  remaining === 0);
            if (!extActive) updateCalmBlock(remaining, total);
        }

        function tick() {
            if (remaining > 0) { remaining -= 1; render(); checkMilestones(); }
            if (remaining === 0) {
                clearInterval(intervalId); intervalId = null;
                if (startBtn) { startBtn.disabled = false; startBtn.textContent = 'Start'; }
                if (pauseBtn)   pauseBtn.disabled  = true;
                announce('Timer complete');
            }
        }

        function applyServerTimestamp(timerStartedAt, timerPausedAt) {
            if (!timerStartedAt) { resetToInitial(); return; }
            const returningToTab = announceOnReturn;
            const referenceTime = timerPausedAt
                ? new Date(timerPausedAt).getTime()
                : Date.now() + clockSkew;
            const elapsedSec = Math.floor((referenceTime - new Date(timerStartedAt).getTime()) / 1000);
            remaining = Math.max(0, total - elapsedSec);
            MILESTONES.forEach(function (ms) { if (remaining < ms) announcedMilestones.add(ms); });
            const _wasFSPaused = firstSync && !!timerStartedAt && remaining > 0 && !!timerPausedAt;
            if (!returningToTab && firstSync && timerStartedAt && remaining > 0) {
                if (timerPausedAt) {
                    announce('Timer is paused \u2014 ' + approxLabel(remaining) + ' remaining');
                } else {
                    announce(approxLabel(remaining) + ' remaining');
                }
            }
            if (announceOnReturn) {
                announceOnReturn = false;
                if (!timerPausedAt && remaining > 0) announce(approxLabel(remaining) + ' remaining');
            }
            firstSync = false;
            render();
            if (timerPausedAt) {
                clearInterval(intervalId); intervalId = null;
                if (startBtn) { startBtn.disabled = false; startBtn.textContent = 'Resume'; }
                setPausedIndicator(true, new Date(timerPausedAt).getTime(), _wasFSPaused);
            } else {
                setPausedIndicator(false);
                if (remaining > 0 && !intervalId) {
                    intervalId = setInterval(tick, 1000);
                    if (startBtn) { startBtn.disabled = true; startBtn.textContent = 'Running\u2026'; }
                } else if (remaining === 0 && intervalId) {
                    clearInterval(intervalId); intervalId = null;
                    if (startBtn) { startBtn.disabled = false; startBtn.textContent = 'Start'; }
                    if (pauseBtn) pauseBtn.disabled = true;
                    announce('Timer complete');
                }
            }
        }

        if (sessionMode) {
            const _initStartedEl = document.getElementById('timer-started-at');
            const _initPausedEl  = document.getElementById('timer-paused-at');
            if (_initStartedEl) {
                applyServerTimestamp(
                    JSON.parse(_initStartedEl.textContent),
                    _initPausedEl ? JSON.parse(_initPausedEl.textContent) : null
                );
            }
        }

        let pauseIntent      = false;
        let virtualStartedAt = null;

        if (sessionMode) {
            startStatusPolling(function (data, notModified) {
                    if (pauseIntent) { pauseIntent = false; return; }
                    if (!notModified && data.server_now) {
                        clockSkew = new Date(data.server_now).getTime() - Date.now();
                    }
                    applyServerTimestamp(data.timer_started_at, data.timer_paused_at);
                    applyInclusivePacing(
                        data.inclusive_pacing            || false,
                        data.inclusive_pacing_multiplier || 3,
                        data.timer_started_at,
                        data.timer_paused_at,
                        total
                    );
                }, function () {
                    announceOnReturn = true;
                }, function () {
                    if (!pauseIntent) return false;
                    pauseIntent = false;
                    return true;
                });
        } else {
            document.addEventListener('visibilitychange', function () {
                if (!document.hidden && intervalId && virtualStartedAt) {
                    announceOnReturn = true;
                    applyServerTimestamp(new Date(virtualStartedAt).toISOString(), null);
                }
            });
        }

        if (startBtn) {
            startBtn.addEventListener('click', async () => {
                if (intervalId) return;
                if (remaining === 0) remaining = total;
                if (sessionMode) {
                    pauseIntent = true;
                    try {
                        const data = await postJson(timerStartUrl);
                        if (data.timer_started_at) {
                            pauseIntent = false;
                            applyServerTimestamp(data.timer_started_at);
                            return;
                        }
                    } catch (e) { pauseIntent = false; }
                }
                setPausedIndicator(false);
                intervalId = setInterval(tick, 1000);
                if (startBtn) { startBtn.disabled = true; startBtn.textContent = 'Running\u2026'; }
                if (pauseBtn)  pauseBtn.disabled  = false;
                if (!sessionMode) virtualStartedAt = Date.now() - (total - remaining) * 1000;
            });
        }

        if (pauseBtn) {
            pauseBtn.addEventListener('click', () => {
                if (!intervalId) return;
                pauseIntent = true;
                clearInterval(intervalId); intervalId = null;
                if (startBtn) { startBtn.disabled = false; startBtn.textContent = 'Resume'; }
                if (pauseBtn)   pauseBtn.disabled  = true;
                setPausedIndicator(true, Date.now());
                if (!sessionMode) virtualStartedAt = null;
            });
        }

        if (resetBtn) {
            resetBtn.addEventListener('click', async () => {
                if (sessionMode) pauseIntent = true;
                virtualStartedAt = null;
                resetToInitial(true);
                if (sessionMode) { try { await postJson(timerResetUrl); } catch (e) {} }
            });
        }

        render();
    }

}());
