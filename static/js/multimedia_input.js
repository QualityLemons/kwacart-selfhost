/* ── Multimedia Input Bridge ── */
/* jshint esversion: 11, laxbreak: true */
/* Three input modes for live session response fields:
     Text  — focuses the existing textarea (default)
     Audio — browser MediaRecorder → Cloudinary via Django upload endpoint
     Image — <input type=file> → Cloudinary via Django upload endpoint
   Uploads go to the server, which proxies to Cloudinary.  Nothing is
   written to Heroku's ephemeral filesystem; only a Cloudinary secure_url
   is stored in ToolInstance.attachments.                                  */
(function () {

    const panel = document.querySelector('.mmi-panel');
    if (!panel) return;

    const uploadUrl = panel.dataset.uploadUrl;
    const removeUrl = panel.dataset.removeUrl;

    const modeButtons    = panel.querySelectorAll('.mmi-mode-btn');
    const audioControls  = panel.querySelector('.mmi-audio-controls');
    const imageControls  = panel.querySelector('.mmi-image-controls');
    const recordBtn      = panel.querySelector('.mmi-record-btn');
    const recordTimerEl  = panel.querySelector('.mmi-record-timer');
    const imageInput     = panel.querySelector('.mmi-image-input');
    const uploadingEl    = panel.querySelector('.mmi-uploading');
    const attachmentList = panel.querySelector('.mmi-attachments');
    const errorEl        = panel.querySelector('.mmi-error');

    let currentMode    = 'text';
    let mediaRecorder  = null;
    let recordedChunks = [];
    let recordTickId   = null;
    let recordingSec   = 0;

    /* ── CSRF helper ── */
    function getCsrf() {
        const val   = '; ' + document.cookie;
        const parts = val.split('; csrftoken=');
        if (parts.length === 2) return parts.pop().split(';').shift();
        return '';
    }

    /* ── Error display ── */
    function showError(msg) {
        if (!errorEl) { alert(msg); return; }
        errorEl.textContent = msg;
        errorEl.hidden = false;
        setTimeout(function () { errorEl.hidden = true; }, 6000);
    }

    /* ── Mode switcher ── */
    function setMode(mode) {
        currentMode = mode;
        modeButtons.forEach(function (btn) {
            btn.setAttribute('aria-pressed', btn.dataset.mode === mode ? 'true' : 'false');
        });
        if (audioControls) audioControls.hidden = mode !== 'audio';
        if (imageControls) imageControls.hidden = mode !== 'image';

        if (mode === 'text') {
            var ta = document.querySelector('textarea.tool-input, form textarea');
            if (ta) ta.focus();
        }
        /* Stop any active recording when leaving audio mode */
        if (mode !== 'audio' && mediaRecorder && mediaRecorder.state === 'recording') {
            mediaRecorder.stop();
        }
    }

    modeButtons.forEach(function (btn) {
        btn.addEventListener('click', function () { setMode(btn.dataset.mode); });
    });

    /* ── Upload a Blob/File to the Django endpoint ── */
    async function uploadFile(blob, filename) {
        if (uploadingEl) uploadingEl.hidden = false;
        const fd = new FormData();
        fd.append('file', blob, filename);
        try {
            const resp = await fetch(uploadUrl, {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'X-CSRFToken': getCsrf() },
                body: fd,
            });
            const json = await resp.json().catch(function () { return {}; });
            if (!resp.ok) throw new Error(json.error || 'Upload failed (' + resp.status + ')');
            return json;
        } finally {
            if (uploadingEl) uploadingEl.hidden = true;
        }
    }

    /* ── Attachment preview card ── */
    function addAttachmentCard(att) {
        if (!attachmentList) return;
        const li = document.createElement('li');
        li.className = 'mmi-attachment-card';
        li.dataset.publicId = att.public_id || '';

        var inner = '';
        if (att.type === 'image') {
            inner += '<img class="mmi-attachment-img" src="' + att.url +
                     '" alt="Symbol board or image attachment" loading="lazy">';
        } else {
            inner += '<audio class="mmi-attachment-audio" controls preload="metadata"' +
                     ' src="' + att.url + '"></audio>';
        }
        inner += '<button type="button" class="btn mmi-remove-btn"' +
                 ' aria-label="Remove this attachment">Remove</button>';
        li.innerHTML = inner;

        li.querySelector('.mmi-remove-btn').addEventListener('click', function () {
            removeAttachment(att.public_id, li);
        });
        attachmentList.appendChild(li);
    }

    /* ── Remove an attachment ── */
    async function removeAttachment(publicId, listItem) {
        listItem.style.opacity = '0.4';
        try {
            const body = new URLSearchParams({ public_id: publicId });
            const resp = await fetch(removeUrl, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'X-CSRFToken': getCsrf(),
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: body.toString(),
            });
            if (resp.ok || resp.status === 404) {
                listItem.remove();
            } else {
                listItem.style.opacity = '';
            }
        } catch (e) {
            listItem.style.opacity = '';
        }
    }

    /* ── Record timer display ── */
    function fmtRecordTime(s) {
        return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
    }

    /* ── Audio recording ── */
    async function startRecording() {
        var stream;
        try {
            stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        } catch (e) {
            showError(
                'Microphone not available. Please allow microphone access in your ' +
                'browser settings and try again.'
            );
            return;
        }

        recordedChunks = [];

        /* Pick the best supported MIME type */
        var mimeType = (
            MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus'
            : MediaRecorder.isTypeSupported('audio/ogg;codecs=opus') ? 'audio/ogg;codecs=opus'
            : MediaRecorder.isTypeSupported('audio/webm')            ? 'audio/webm'
            : ''
        );

        var options = mimeType ? { mimeType: mimeType } : {};
        mediaRecorder = new MediaRecorder(stream, options);

        mediaRecorder.addEventListener('dataavailable', function (e) {
            if (e.data && e.data.size > 0) recordedChunks.push(e.data);
        });

        mediaRecorder.addEventListener('stop', async function () {
            stream.getTracks().forEach(function (t) { t.stop(); });
            clearInterval(recordTickId); recordTickId = null;
            recordingSec = 0;
            if (recordBtn) {
                recordBtn.textContent = '\u25cf Start Recording';
                recordBtn.classList.remove('recording');
            }
            if (recordTimerEl) recordTimerEl.hidden = true;

            if (recordedChunks.length === 0) return;
            var ext  = (mimeType.includes('ogg')) ? 'ogg' : 'webm';
            var blob = new Blob(recordedChunks, { type: mimeType || 'audio/webm' });
            try {
                var result = await uploadFile(blob, 'recording.' + ext);
                addAttachmentCard(result);
            } catch (e) {
                showError('Audio upload failed: ' + e.message);
            }
        });

        mediaRecorder.start();
        recordingSec = 0;
        if (recordTimerEl) {
            recordTimerEl.textContent = fmtRecordTime(0);
            recordTimerEl.hidden = false;
        }
        if (recordBtn) {
            recordBtn.textContent = '\u25a0 Stop Recording';
            recordBtn.classList.add('recording');
        }
        recordTickId = setInterval(function () {
            recordingSec += 1;
            if (recordTimerEl) recordTimerEl.textContent = fmtRecordTime(recordingSec);
        }, 1000);
    }

    if (recordBtn) {
        recordBtn.addEventListener('click', function () {
            if (!mediaRecorder || mediaRecorder.state === 'inactive') {
                startRecording();
            } else if (mediaRecorder.state === 'recording') {
                mediaRecorder.stop();
            }
        });
    }

    /* ── Image upload ── */
    if (imageInput) {
        imageInput.addEventListener('change', async function () {
            var file = imageInput.files[0];
            if (!file) return;
            if (file.size > 10 * 1024 * 1024) {
                showError('Image too large. Please choose a file under 10 MB.');
                imageInput.value = '';
                return;
            }
            try {
                var result = await uploadFile(file, file.name);
                addAttachmentCard(result);
                imageInput.value = '';
            } catch (e) {
                showError('Image upload failed: ' + e.message);
            }
        });
    }

    /* ── Restore attachments saved in previous buffer saves ── */
    var existingEl = document.getElementById('mmi-existing-attachments');
    if (existingEl) {
        try {
            var existing = JSON.parse(existingEl.textContent);
            if (Array.isArray(existing)) {
                existing.forEach(function (att) { addAttachmentCard(att); });
            }
        } catch (e) { /* malformed JSON — ignore */ }
    }

}());
