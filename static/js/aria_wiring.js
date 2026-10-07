/* ── Aria wiring ── */
/* 1. Connect error message elements to their input fields.
      Error elements: id="{{ field_id }}-error"
      Sets aria-describedby on the input and marks it aria-invalid.
   2. Connect help text elements to their input fields.
      Help elements: id="{{ field_id }}-help"
      Appends the help element id to any existing aria-describedby. */
(function () {
    document.querySelectorAll('[id$="-error"]').forEach(function (errEl) {
        var inputId = errEl.id.replace(/-error$/, '');
        var input = document.getElementById(inputId);
        if (input) {
            input.setAttribute('aria-describedby', errEl.id);
            input.setAttribute('aria-invalid', 'true');
        }
    });

    document.querySelectorAll('[id$="-help"]').forEach(function (helpEl) {
        var inputId = helpEl.id.replace(/-help$/, '');
        var input = document.getElementById(inputId);
        if (input) {
            var existing = input.getAttribute('aria-describedby');
            input.setAttribute(
                'aria-describedby',
                existing ? existing + ' ' + helpEl.id : helpEl.id
            );
        }
    });
}());
