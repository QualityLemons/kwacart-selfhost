/* ── Pause reminder settings ── */
/* Saves the host's chosen pause-reminder threshold via AJAX.
   The save URL is read from data-save-url on #pause-reminder-save.
   The current threshold is read from data-current-threshold on the same element. */
(function () {

    var select  = document.getElementById('pause-reminder-select');
    var saveBtn = document.getElementById('pause-reminder-save');
    var status  = document.getElementById('pause-reminder-status');

    if (!select || !saveBtn) return;

    var url        = saveBtn.dataset.saveUrl;
    var csrfToken  = document.querySelector('[name=csrfmiddlewaretoken]').value;

    /* ── Initialise the select to the stored threshold value ── */
    (function initSelect() {
        var current = saveBtn.dataset.currentThreshold || '';
        if (current === '' || current === 'None') {
            select.value = '';
            return;
        }
        var opt = select.querySelector('option[value="' + current + '"]');
        if (opt) {
            select.value = current;
        } else {
            var extra = document.createElement('option');
            extra.value = current;
            var mins = Math.round(parseInt(current, 10) / 60);
            extra.textContent = mins + ' minute' + (mins !== 1 ? 's' : '') + ' (custom)';
            select.appendChild(extra);
            select.value = current;
        }
    }());

    /* ── Save on button click ── */
    saveBtn.addEventListener('click', function () {
        var body = new URLSearchParams();
        body.append('pause_reminder_threshold_sec', select.value);
        body.append('csrfmiddlewaretoken', csrfToken);
        saveBtn.disabled = true;

        fetch(url, { method: 'POST', body: body, credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.error) {
                    saveBtn.disabled = false;
                    status.textContent    = 'Error: ' + data.error;
                    status.style.color   = '#dc2626';
                    status.style.display = 'inline';
                    setTimeout(function () { status.style.display = 'none'; }, 4000);
                } else {
                    status.textContent    = 'Saved';
                    status.style.color   = '#15803d';
                    status.style.display = 'inline';
                    saveBtn.disabled     = false;
                    setTimeout(function () { status.style.display = 'none'; }, 3000);
                    /* Apply the new threshold immediately in the running timer widget */
                    var newVal = select.value === '' ? null : parseInt(select.value, 10);
                    if (typeof window.setTimerPauseReminderThreshold === 'function') {
                        window.setTimerPauseReminderThreshold(newVal);
                    }
                }
            })
            .catch(function () {
                saveBtn.disabled      = false;
                status.textContent    = 'Could not save \u2014 please try again.';
                status.style.color   = '#dc2626';
                status.style.display = 'inline';
                setTimeout(function () { status.style.display = 'none'; }, 4000);
            });
    });

}());
