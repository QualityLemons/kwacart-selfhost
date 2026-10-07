/* ── Session buffer autosave ── */
/* Continuously saves in-progress form input to the server every few seconds
   so that text typed by a participant is not lost if the host closes the
   session while they are mid-sentence.

   Requires:
   - getCookie() to be defined before this script runs (provided by draft_init.js).
   - A #session-buffer element with data-buffer-url set to the buffer-save URL.
   - An optional #buffer-status element for user-facing save feedback.

   Exposes window.sessionBufferFlush — called by the poll scripts immediately
   when they detect the session has been closed, triggering a final flush and
   freezing all form fields before the page reloads. */

(function () {

    var SAVE_INTERVAL_MS = 3000;

    var bufferEl = document.getElementById('session-buffer');
    if (!bufferEl) return;

    var bufferUrl = bufferEl.dataset.bufferUrl;
    if (!bufferUrl) return;

    var statusEl = document.getElementById('buffer-status');
    var _flushed = false;

    /* ── Collect current state of every tool-input field ── */
    function collectFormData() {
        var data = {};
        document.querySelectorAll('.tool-input').forEach(function (input) {
            if (input.name && (input.type !== 'radio' || input.checked)) {
                data[input.name] = input.value;
            }
        });
        return data;
    }

    /* ── POST current buffer to the server ── */
    async function flush() {
        var formData = collectFormData();
        if (Object.keys(formData).length === 0) return;
        try {
            var response = await fetch(bufferUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    /* getCookie is defined in draft_init.js, loaded before
                       this script. */
                    'X-CSRFToken': getCookie('csrftoken'),
                },
                body: JSON.stringify({ form_data: formData }),
                credentials: 'same-origin',
            });
            if (!response.ok) return;
            var result = await response.json();
            if (statusEl && result.last_saved) {
                statusEl.textContent = 'Buffered at ' + result.last_saved;
                statusEl.style.color = '';
            }
        } catch (_) {
            if (statusEl) {
                statusEl.textContent = 'Buffer save unavailable \u2014 check your connection';
                statusEl.style.color = '#b45309';
            }
        }
    }

    /* ── Freeze all form inputs so the participant sees their text is locked ── */
    function freeze() {
        /* Text inputs and textareas: use readonly so values are still submitted
           with the form if the participant clicks Save manually. */
        document.querySelectorAll(
            'form textarea, form input[type="text"], form input[type="number"], ' +
            'form input[type="url"], form input[type="email"]'
        ).forEach(function (el) {
            el.setAttribute('readonly', 'readonly');
        });
        /* Selects, radios, and the submit button do not support readonly. */
        document.querySelectorAll('form select, form input[type="radio"]').forEach(function (el) {
            el.disabled = true;
        });
        var submitBtn = document.querySelector('form button[type="submit"]');
        if (submitBtn) submitBtn.disabled = true;

        if (statusEl) {
            statusEl.textContent = 'Session closed \u2014 your response has been captured.';
            statusEl.style.color = '#15803d';
            statusEl.style.fontWeight = '600';
        }
    }

    /* ── Called by poll scripts when status becomes "closed" ── */
    /* Performs a final flush and freezes inputs before the page reload. */
    window.sessionBufferFlush = async function () {
        if (_flushed) return;
        _flushed = true;
        await flush();
        freeze();
    };

    /* ── Start continuous background save ── */
    setInterval(flush, SAVE_INTERVAL_MS);

}());
