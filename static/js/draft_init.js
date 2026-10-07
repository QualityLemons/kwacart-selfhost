/* ── Draft editor initialisation ── */
/* Defines the getCookie helper required by autosave.js and adds the
   .tool-input class to all form fields that autosave should monitor.
   Must be loaded before autosave.js. */

/* getCookie — reads a named cookie value from document.cookie.
 * The string-splitting technique below is taken directly from the
 * Django CSRF documentation:
 * https://docs.djangoproject.com/en/stable/howto/csrf/
 * (section "Acquiring the token if CSRF_USE_SESSIONS and
 * CSRF_COOKIE_HTTPONLY are False") */
function getCookie(name) {
    var value = '; ' + document.cookie;
    var parts = value.split('; ' + name + '=');
    if (parts.length === 2) return parts.pop().split(';').shift();
    return '';
}

document.querySelectorAll(
    'form textarea, form input[type="text"], form input[type="number"], ' +
    'form input[type="url"], form input[type="email"], form input[type="radio"], ' +
    'form input[type="hidden"][name="canvas_data"], form select'
).forEach(function (el) {
    el.classList.add('tool-input');
});
