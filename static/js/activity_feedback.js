/* Small progressive enhancements for native activity controls.
   Forms remain fully usable when JavaScript is unavailable. */
(function () {
    var fields = document.querySelectorAll('.expressive-fieldset');
    fields.forEach(function (field) {
        var live = document.createElement('span');
        live.className = 'sr-only';
        live.setAttribute('aria-live', 'polite');
        field.appendChild(live);
        field.querySelectorAll('input[type="radio"]').forEach(function (radio) {
            radio.addEventListener('change', function () {
                live.textContent = 'Selected ' + radio.value;
                field.classList.add('is-updated');
                window.setTimeout(function () { field.classList.remove('is-updated'); }, 220);
            });
        });
    });
}());