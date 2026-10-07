/* ── Form submission handlers ── */
/* Prevents duplicate submissions and confirms destructive actions.
   Forms use data attributes to configure the behaviour:
     data-disable-on-submit  — disables the submit button on submit
     data-loading-text       — label shown on the submit button while loading
     data-confirm            — shows a confirm dialog before submitting;
                               also disables the button after the user confirms */
(function () {

    /* ── Disable-on-submit ── */
    document.querySelectorAll('form[data-disable-on-submit]').forEach(function (form) {
        form.addEventListener('submit', function () {
            var btn = form.querySelector('[type="submit"]');
            if (btn) {
                btn.disabled = true;
                btn.textContent = form.dataset.loadingText || 'Saving\u2026';
            }
        });
    });

    /* ── Confirm then disable ── */
    document.querySelectorAll('form[data-confirm]').forEach(function (form) {
        form.addEventListener('submit', function (e) {
            if (!confirm(form.dataset.confirm)) {
                e.preventDefault();
                return;
            }
            var btn = form.querySelector('[type="submit"]');
            if (btn) {
                btn.disabled = true;
                btn.textContent = form.dataset.loadingText || 'Closing\u2026';
            }
        });
    });

}());
