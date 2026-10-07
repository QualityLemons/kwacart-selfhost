/* ── Accessibility theme toggle ──────────────────────────────────────────────
   Manages the a11y-theme class on <html> and persists the user's choice in
   localStorage so it survives navigation.

   The class is *also* applied by an inline <script> in <head> before the
   stylesheet loads, so there is no flash of un-themed content on page load.
   This file is responsible only for the interactive toggle behaviour.
────────────────────────────────────────────────────────────────────────────*/
(function () {
    var STORAGE_KEY = 'kwacart_a11y_theme';
    var CLASS       = 'a11y-theme';

    var btn = document.getElementById('a11y-theme-toggle');
    if (!btn) return;

    /* Sync the button's aria-pressed and label to the current state. */
    function syncButton() {
        var active = document.documentElement.classList.contains(CLASS);
        btn.setAttribute('aria-pressed', String(active));
        btn.textContent = active ? '\u2713 Accessibility Mode' : 'Accessibility Mode';
    }

    /* Apply state on page load in case the class was set by the <head> script
       before this JS file executed. */
    syncButton();

    btn.addEventListener('click', function () {
        var willActivate = !document.documentElement.classList.contains(CLASS);
        if (willActivate) {
            document.documentElement.classList.add(CLASS);
            try { localStorage.setItem(STORAGE_KEY, '1'); } catch (_) {}
        } else {
            document.documentElement.classList.remove(CLASS);
            try { localStorage.removeItem(STORAGE_KEY); } catch (_) {}
        }
        syncButton();
    });
}());
