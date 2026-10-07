/* ── Verbal Breakout host toggle ── */
/* jshint esversion: 11 */
/* Drives the "Verbal Breakout" button inside the Inclusive Pacing panel on
   the host session page.  POSTs the active flag to session_set_verbal_breakout
   and updates the button label/state immediately.  Participants receive the
   updated state on the next session_status poll cycle (≤ 4 seconds).

   Also shows/hides the entire verbal-breakout-panel when the host checks or
   unchecks the Inclusive Pacing checkbox, since verbal breakout is a
   sub-feature of inclusive pacing. */
(function () {

    var btn    = document.getElementById('verbal-breakout-btn');
    var status = document.getElementById('verbal-breakout-status');
    var panel  = document.getElementById('verbal-breakout-panel');
    var ipTog  = document.getElementById('inclusive-pacing-toggle');

    if (!btn) return;

    var url    = btn.dataset.activateUrl;
    var active = btn.getAttribute('aria-pressed') === 'true';

    function getCsrf() {
        var val   = '; ' + document.cookie;
        var parts = val.split('; csrftoken=');
        if (parts.length === 2) return parts.pop().split(';').shift();
        return '';
    }

    function showStatus(msg, isError) {
        if (!status) return;
        status.textContent  = msg;
        status.style.color  = isError ? '#dc2626' : '#15803d';
        status.style.display = 'inline';
        setTimeout(function () { status.style.display = 'none'; }, isError ? 4000 : 3000);
    }

    btn.addEventListener('click', async function () {
        btn.disabled = true;
        var next = !active;
        try {
            var body = new URLSearchParams({ active: next ? 'true' : 'false' });
            var resp = await fetch(url, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'X-CSRFToken': getCsrf(),
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: body.toString(),
            });
            if (!resp.ok) throw new Error('non-ok');
            active = next;
            btn.setAttribute('aria-pressed', String(active));
            if (active) {
                btn.textContent = '\u9646\u9646 End verbal discussion';
                btn.classList.add('btn-primary');
                showStatus('Verbal discussion started \u2014 participants notified.');
            } else {
                btn.textContent = '\uD83D\uDCAC Start verbal discussion';
                btn.classList.remove('btn-primary');
                showStatus('Verbal discussion ended.');
            }
        } catch (e) {
            showStatus('Could not save \u2014 please try again.', true);
        } finally {
            btn.disabled = false;
        }
    });

    /* ── Show/hide the verbal-breakout panel when the IP checkbox changes ──
       Verbal breakout is a sub-feature of inclusive pacing: it only makes
       sense to offer it when IP is enabled (or about to be saved as enabled). */
    if (ipTog && panel) {
        ipTog.addEventListener('change', function () {
            if (ipTog.checked) {
                panel.removeAttribute('hidden');
            } else {
                panel.setAttribute('hidden', '');
            }
        });
    }

}());
