/* ── Inclusive Pacing host controls ── */
/* jshint esversion: 11, laxbreak: true */
/* Drives the "Inclusive Pacing" <details> panel on the host session page.
   POSTs the enabled flag and multiplier choice to session_set_inclusive_pacing
   when the host clicks Save.  Participants receive the updated setting on the
   next session_status poll cycle (every 4 seconds) without needing a reload. */
(function () {
    const saveBtn = document.getElementById('inclusive-pacing-save');
    const toggle  = document.getElementById('inclusive-pacing-toggle');
    const select  = document.getElementById('inclusive-pacing-multiplier');
    const status  = document.getElementById('inclusive-pacing-status');
    if (!saveBtn || !toggle || !select) return;

    const saveUrl = saveBtn.dataset.saveUrl;

    function getCsrf() {
        const val   = '; ' + document.cookie;
        const parts = val.split('; csrftoken=');
        if (parts.length === 2) return parts.pop().split(';').shift();
        return '';
    }

    saveBtn.addEventListener('click', async function () {
        saveBtn.disabled = true;
        if (status) { status.style.display = 'none'; status.style.color = '#15803d'; }
        try {
            const body = new URLSearchParams({
                inclusive_pacing: toggle.checked ? 'true' : 'false',
                inclusive_pacing_multiplier: select.value,
            });
            const resp = await fetch(saveUrl, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'X-CSRFToken': getCsrf(),
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: body.toString(),
            });
            if (resp.ok) {
                if (status) {
                    status.textContent = toggle.checked
                        ? 'Saved \u2014 participants can now activate extended time.'
                        : 'Saved \u2014 inclusive pacing disabled.';
                    status.style.display = 'inline';
                    setTimeout(function () { status.style.display = 'none'; }, 4000);
                }
            } else {
                throw new Error('non-ok response');
            }
        } catch (e) {
            if (status) {
                status.textContent = 'Save failed \u2014 check your connection.';
                status.style.color = '#b91c1c';
                status.style.display = 'inline';
            }
        } finally {
            saveBtn.disabled = false;
        }
    });
}());
