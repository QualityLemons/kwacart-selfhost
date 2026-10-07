/* ── AAC Composition Presence Flag ── */
/* Allows AAC users composing in external software (e.g. Grid 3, Snap Core
   First) to signal to the host that they are actively working on a response,
   even though no keystrokes reach the form.

   When the toggle is active a heartbeat POST is sent to the server every
   HEARTBEAT_MS milliseconds.  The server marks the participant's instance
   with the current timestamp; session_poll.js then surfaces a
   "Composing..." indicator next to their name in the host's participant list.

   The server-side timeout is 15 seconds.  Sending every 8 seconds ensures
   the flag stays active even if one request is delayed.

   Requires getCookie() to be defined before this script (provided by
   draft_init.js). */

(function () {

    var HEARTBEAT_MS = 8000;

    var anchorEl = document.getElementById('aac-presence');
    if (!anchorEl) return;

    var composingUrl = anchorEl.dataset.composingUrl;
    if (!composingUrl) return;

    var btn      = document.getElementById('aac-composing-btn');
    var statusEl = document.getElementById('aac-composing-status');

    if (!btn) return;

    var _active     = false;
    var _intervalId = null;

    /* ── Send a single heartbeat to the server ── */
    async function sendHeartbeat() {
        try {
            await fetch(composingUrl, {
                method: 'POST',
                headers: { 'X-CSRFToken': getCookie('csrftoken') },
                credentials: 'same-origin',
            });
        } catch (_) {
            /* Silently swallow network errors — the server-side flag will
               expire after 15 seconds if heartbeats stop reaching it. */
        }
    }

    /* ── Start signalling ── */
    function activate() {
        _active = true;
        btn.textContent = 'Stop signalling';
        btn.style.background = '#dc2626';
        btn.setAttribute('aria-pressed', 'true');
        if (statusEl) {
            statusEl.textContent =
                'Signal active \u2014 the host can see you are composing.';
            statusEl.style.color = '#92400e';
        }
        /* Send immediately so the host sees the indicator without waiting. */
        sendHeartbeat();
        _intervalId = setInterval(sendHeartbeat, HEARTBEAT_MS);
    }

    /* ── Stop signalling ── */
    function deactivate() {
        _active = false;
        clearInterval(_intervalId);
        _intervalId = null;
        btn.textContent = '\uD83D\uDDE3\uFE0F I\u2019m Composing';
        btn.style.background = '#d97706';
        btn.setAttribute('aria-pressed', 'false');
        if (statusEl) {
            statusEl.textContent = 'Signal stopped.';
            statusEl.style.color = '#64748b';
        }
    }

    btn.setAttribute('aria-pressed', 'false');
    btn.addEventListener('click', function () {
        if (_active) { deactivate(); } else { activate(); }
    });

    /* Clear interval on unload — the server flag expires naturally after 15 s
       so no explicit "stop" request is needed. */
    window.addEventListener('beforeunload', function () {
        if (_intervalId) clearInterval(_intervalId);
    });

}());
