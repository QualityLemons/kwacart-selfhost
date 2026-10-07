/* ── Inline Archive Markdown Viewer ── */
/* jshint esversion: 11, laxbreak: true */
/* Intercepts clicks on .mdv-preview-btn elements, fetches the stored
   Markdown content from the Django preview endpoint, renders it with
   marked.js, and displays it in a focus-trapped modal without navigating
   away from the Archive Dashboard.                                        */
(function () {

    /* ── Build the modal shell once and attach to <body> ── */
    var backdrop = document.createElement('div');
    backdrop.className  = 'mdv-backdrop';
    backdrop.setAttribute('role', 'dialog');
    backdrop.setAttribute('aria-modal', 'true');
    backdrop.setAttribute('aria-labelledby', 'mdv-title');
    backdrop.hidden = true;
    backdrop.innerHTML =
        '<div class="mdv-dialog" role="document">' +
            '<div class="mdv-header">' +
                '<span id="mdv-title" class="mdv-title"></span>' +
                '<button type="button" class="mdv-close" aria-label="Close preview">' +
                    '&times;' +
                '</button>' +
            '</div>' +
            '<div class="mdv-toolbar">' +
                '<a class="mdv-download-link" href="#" target="_blank" rel="noopener noreferrer">' +
                    '&#8681; Download .md' +
                '</a>' +
            '</div>' +
            '<div class="mdv-body">' +
                '<div class="mdv-loading" aria-live="polite">Loading&hellip;</div>' +
                '<div class="mdv-error"   aria-live="polite" hidden></div>' +
                '<div class="mdv-content" aria-live="polite" hidden></div>' +
            '</div>' +
        '</div>';

    document.body.appendChild(backdrop);

    var dialog      = backdrop.querySelector('.mdv-dialog');
    var titleEl     = backdrop.querySelector('.mdv-title');
    var closeBtn    = backdrop.querySelector('.mdv-close');
    var dlLink      = backdrop.querySelector('.mdv-download-link');
    var loadingEl   = backdrop.querySelector('.mdv-loading');
    var errorEl     = backdrop.querySelector('.mdv-error');
    var contentEl   = backdrop.querySelector('.mdv-content');

    var _prevFocus  = null;   /* element that had focus before opening */
    var _abortCtrl  = null;   /* AbortController for in-flight fetch   */

    /* ── Focus trap ── */
    /* The getFocusable selector list and Tab/Shift+Tab wrapping logic follow
     * the WAI-ARIA Authoring Practices Guide (APG) dialog pattern:
     * https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/ */
    function getFocusable() {
        return Array.from(
            dialog.querySelectorAll(
                'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])'
            )
        ).filter(function (el) { return el.offsetParent !== null; });
    }

    function trapFocus(e) {
        var focusable = getFocusable();
        if (!focusable.length) { e.preventDefault(); return; }
        var first = focusable[0];
        var last  = focusable[focusable.length - 1];
        if (e.shiftKey) {
            if (document.activeElement === first) { e.preventDefault(); last.focus(); }
        } else {
            if (document.activeElement === last)  { e.preventDefault(); first.focus(); }
        }
    }

    /* ── Open / close ── */
    function openModal(title, previewUrl, downloadUrl) {
        if (_abortCtrl) _abortCtrl.abort();

        titleEl.textContent     = title;
        dlLink.href             = downloadUrl;

        loadingEl.hidden = false;
        errorEl.hidden   = true;
        contentEl.hidden = true;
        contentEl.innerHTML = '';

        _prevFocus = document.activeElement;
        backdrop.hidden = false;
        document.body.style.overflow = 'hidden';
        closeBtn.focus();

        document.addEventListener('keydown', handleKey);

        /* Fetch markdown content */
        _abortCtrl = new AbortController();
        fetch(previewUrl, {
            credentials: 'same-origin',
            signal: _abortCtrl.signal,
        })
        .then(function (resp) {
            if (!resp.ok) throw new Error('Server returned ' + resp.status);
            return resp.json();
        })
        .then(function (data) {
            if (!data.markdown) throw new Error('Empty response from server.');
            var html = marked.parse(data.markdown);
            var safeHtml = (typeof DOMPurify !== 'undefined')
                ? DOMPurify.sanitize(html, { USE_PROFILES: { html: true } })
                : '';
            if (!safeHtml && html) {
                /* DOMPurify missing or stripped everything unexpectedly; fail
                 * closed rather than injecting unsanitized markup. */
                throw new Error('Preview could not be rendered safely.');
            }
            contentEl.innerHTML = safeHtml;
            loadingEl.hidden = true;
            contentEl.hidden = false;
        })
        .catch(function (err) {
            if (err.name === 'AbortError') return;
            loadingEl.hidden = true;
            errorEl.textContent = 'Could not load preview: ' + err.message +
                '. Try the Download link above.';
            errorEl.hidden = false;
        });
    }

    function closeModal() {
        if (_abortCtrl) { _abortCtrl.abort(); _abortCtrl = null; }
        backdrop.hidden = true;
        document.body.style.overflow = '';
        document.removeEventListener('keydown', handleKey);
        if (_prevFocus && _prevFocus.focus) _prevFocus.focus();
    }

    function handleKey(e) {
        if (e.key === 'Escape') { closeModal(); return; }
        if (e.key === 'Tab')    { trapFocus(e); }
    }

    /* ── Button wiring ── */
    closeBtn.addEventListener('click', closeModal);

    /* Click on backdrop (outside dialog) → close */
    backdrop.addEventListener('click', function (e) {
        if (e.target === backdrop) closeModal();
    });

    /* Delegate: any .mdv-preview-btn anywhere on the page */
    document.addEventListener('click', function (e) {
        var btn = e.target.closest('.mdv-preview-btn');
        if (!btn) return;
        e.preventDefault();
        openModal(
            btn.dataset.title       || 'Preview',
            btn.dataset.previewUrl,
            btn.dataset.downloadUrl || '#'
        );
    });

}());
