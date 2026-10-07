/* ── Autosave ── */
/* Collects the current state of every `.tool-input` field on the draft
   editor page and POSTs it to the autosave endpoint two seconds after the
   user stops typing.  On a successful response it updates the save-status
   indicator and, when a new draft is created, rewrites the browser URL with
   the instance id so a reload re-opens the same draft. */

/* ── Debounce helper ── */
/* Delays execution of `func` until `timeout` ms have elapsed since the last
   call.  Prevents the autosave endpoint from being hit on every keystroke.
   This is a standard JavaScript debounce pattern; the clearTimeout/setTimeout
   approach is widely documented, e.g.:
   https://developer.mozilla.org/en-US/docs/Glossary/Debounce */
function debounce(func, timeout = 2000) {
    let timer;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => { func.apply(this, args); }, timeout);
    };
}

/* ── Save draft ── */
/* Gathers all `.tool-input` field values, reads the instance id and tool
   slug from hidden inputs, then POSTs the data as JSON to the autosave
   endpoint.  The endpoint returns `{instance_id, last_saved}` — the
   instance_id is written back to the hidden field so subsequent saves
   update the same draft record rather than creating a new one.

   Network failures and non-OK HTTP responses are caught and surfaced in the
   save-status element so the user knows the draft was not saved. */
const saveDraft = debounce(async () => {
    /* ── Collect form fields ── */
    const formData = {};
    document.querySelectorAll('.tool-input').forEach(input => {
        if (input.name && (input.type !== 'radio' || input.checked)) {
            formData[input.name] = input.value;
        }
    });

    /* ── Read context from hidden inputs ── */
    const instanceId = document.getElementById('instance-id').value;
    const toolSlug = document.getElementById('tool-slug').value;
    const statusEl = document.getElementById('save-status');

    try {
        /* ── POST to autosave endpoint ── */
        const response = await fetch(`/tools/${toolSlug}/autosave/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                /* getCookie reads the csrftoken cookie set by Django's
                   CsrfViewMiddleware.  Without it the POST is rejected with
                   HTTP 403 Forbidden.  getCookie must be defined by the page
                   before this script runs. */
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({
                instance_id: instanceId,
                form_data: formData
            })
        });

        /* ── Handle non-OK HTTP responses ── */
        /* The endpoint returns 400 for bad input and 404 if the draft record
           is no longer found.  Both cases surface a message so the user
           knows the save failed and can reload or re-submit manually. */
        if (!response.ok) {
            let serverMessage = '';
            try {
                const errData = await response.json();
                serverMessage = errData.error ? ` (${errData.error})` : '';
            } catch (_) {
                /* Response body was not JSON — ignore and use status code. */
            }
            if (statusEl) {
                statusEl.innerText = `Save failed${serverMessage} — please reload the page`;
                statusEl.style.color = '#b45309';
            }
            return;
        }

        /* ── Handle successful response ── */
        const data = await response.json();

        if (statusEl) {
            /* Restore default colour in case a previous save had failed. */
            statusEl.style.color = '';
            statusEl.innerText = `Autosaved at ${data.last_saved}`;
        }

        /* Write the returned instance id back to the hidden field so future
           saves target the same DB record. */
        const previousId = document.getElementById('instance-id').value;
        document.getElementById('instance-id').value = data.instance_id;

        /* When autosave creates a new draft the URL still lacks the instance
           id.  Replace it so that a page reload reopens the same draft
           instead of a blank new one. */
        if (!previousId && data.instance_id) {
            const newUrl = `/tools/${toolSlug}/draft/${data.instance_id}/`;
            history.replaceState(null, '', newUrl);
        }

    } catch (networkError) {
        /* ── Handle network-level failures ── */
        /* Catches offline events, DNS failures, and any other condition that
           prevents the fetch from completing.  The user is told the draft
           was not saved so they can take action (e.g. copy their text). */
        if (statusEl) {
            statusEl.innerText = 'Autosave unavailable — check your connection';
            statusEl.style.color = '#b45309';
        }
    }
});

/* ── Attach listeners ── */
/* Wire the debounced save to every tool-input field.  New fields added
   dynamically after page load would need to be wired separately, but the
   draft editor renders a fixed set of fields on initial load so this is
   sufficient. */
document.querySelectorAll('.tool-input').forEach(input => {
    input.addEventListener('input', saveDraft);
    if (input.type === 'radio') {
        input.addEventListener('change', saveDraft);
    }
});
