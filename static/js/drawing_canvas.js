/* ── Drawing canvas ── */
/* Handles all interactivity for the freehand drawing tool:
   colour selection, brush size, eraser, undo, clear, responsive
   resizing, save-on-submit, and touch/mouse event routing. */
(function () {

    /* ── Constants ── */
    var ANNOUNCE_DELAY_MS = 50;
    var MAX_HISTORY = 50;

    /* ── Element references ── */
    var _canvasAnnouncer = document.getElementById('canvas-announcer');
    var canvas           = document.getElementById('drawing-canvas');
    var ctx              = canvas.getContext('2d');
    var hiddenField      = document.querySelector('input[name="canvas_data"]');

    /* ── Drawing state ── */
    var drawing   = false;
    var color     = '#E69F00';
    var brushSize = 3;
    var erasing   = false;
    var history   = [];
    var canvasDirty = false;
    var canvasHasContent = Boolean(hiddenField && hiddenField.value);

    /* ── Announce to screen readers ── */
    function announce(msg) {
        if (!_canvasAnnouncer) return;
        _canvasAnnouncer.textContent = '';
        setTimeout(function () { _canvasAnnouncer.textContent = msg; }, ANNOUNCE_DELAY_MS);
    }

    /* ── Responsive sizing ── */
    function resizeCanvas() {
        var w = canvas.parentElement.clientWidth;
        if (w && w !== canvas.width) {
            var snapshot = ctx.getImageData(0, 0, canvas.width, canvas.height);
            canvas.width  = w;
            canvas.height = Math.round(w * 0.6);
            ctx.putImageData(snapshot, 0, 0);
        }
    }
    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);

    /* ── Restore saved canvas data ── */
    function restoreFromSrc(src) {
        var img = new Image();
        img.crossOrigin = 'anonymous';
        img.onload = function () {
            resizeCanvas();
            ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        };
        img.src = src;
    }
    if (hiddenField && hiddenField.value) {
        if (hiddenField.value.startsWith('data:') || hiddenField.value.startsWith('/media/')) {
            restoreFromSrc(hiddenField.value);
        }
    }

    /* ── Snapshot helpers (for undo) ── */
    function saveSnapshot() {
        history.push(ctx.getImageData(0, 0, canvas.width, canvas.height));
        if (history.length > MAX_HISTORY) history.shift();
    }

    function hasVisiblePixels() {
        try {
            var pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
            for (var i = 3; i < pixels.length; i += 4) {
                if (pixels[i] !== 0) return true;
            }
            return false;
        } catch (_) {
            return canvasHasContent;
        }
    }

    function syncHiddenField() {
        if (!hiddenField) return;
        hiddenField.value = canvasHasContent ? canvas.toDataURL('image/png') : '';
        hiddenField.dispatchEvent(new Event('input', { bubbles: true }));
    }

    /* ── Pointer position (mouse and touch) ── */
    function getPos(e) {
        var r   = canvas.getBoundingClientRect();
        var src = e.touches ? e.touches[0] : e;
        return {
            x: (src.clientX - r.left) * (canvas.width  / r.width),
            y: (src.clientY - r.top)  * (canvas.height / r.height),
        };
    }

    /* ── Drawing event handlers ── */
    function startDraw(e) {
        e.preventDefault();
        saveSnapshot();
        drawing = true;
        canvasDirty = true;
        canvasHasContent = true;
        var p = getPos(e);
        ctx.beginPath();
        ctx.moveTo(p.x, p.y);
    }

    function draw(e) {
        if (!drawing) return;
        e.preventDefault();
        var p = getPos(e);
        ctx.lineWidth   = erasing ? brushSize * 4 : brushSize;
        ctx.lineCap     = 'round';
        ctx.lineJoin    = 'round';
        ctx.strokeStyle = erasing ? '#ffffff' : color;
        ctx.globalCompositeOperation = erasing ? 'destination-out' : 'source-over';
        ctx.lineTo(p.x, p.y);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(p.x, p.y);
    }

    function endDraw() {
        if (!drawing) return;
        drawing = false;
        ctx.globalCompositeOperation = 'source-over';
        canvasHasContent = hasVisiblePixels();
        syncHiddenField();
    }

    canvas.addEventListener('mousedown',  startDraw);
    canvas.addEventListener('mousemove',  draw);
    canvas.addEventListener('mouseup',    endDraw);
    canvas.addEventListener('mouseleave', endDraw);
    canvas.addEventListener('touchstart', startDraw, { passive: false });
    canvas.addEventListener('touchmove',  draw,      { passive: false });
    canvas.addEventListener('touchend',   endDraw);

    /* ── Save canvas data when form is submitted ── */
    var form = canvas.closest('form');
    if (form && hiddenField) {
        form.addEventListener('submit', function () {
            if (!canvasHasContent) {
                hiddenField.value = '';
            } else if (canvasDirty) {
                hiddenField.value = canvas.toDataURL('image/png');
            }
        });
    }

    /* ── Colour swatch controls ── */
    document.querySelectorAll('.color-swatch').forEach(function (btn) {
        btn.addEventListener('click', function () {
            erasing = false;
            color   = btn.dataset.color;
            document.querySelectorAll('.color-swatch').forEach(function (b) {
                b.classList.remove('active');
                b.setAttribute('aria-pressed', 'false');
            });
            document.querySelectorAll('.eraser-btn').forEach(function (b) {
                b.classList.remove('active');
                b.setAttribute('aria-pressed', 'false');
            });
            btn.classList.add('active');
            btn.setAttribute('aria-pressed', 'true');
        });
    });

    /* ── Brush size controls ── */
    document.querySelectorAll('.size-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            brushSize = parseInt(btn.dataset.size, 10);
            document.querySelectorAll('.size-btn').forEach(function (b) {
                b.classList.remove('active');
                b.setAttribute('aria-pressed', 'false');
            });
            btn.classList.add('active');
            btn.setAttribute('aria-pressed', 'true');
        });
    });

    /* ── Eraser toggle ── */
    document.querySelectorAll('.eraser-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            erasing = !erasing;
            btn.classList.toggle('active', erasing);
            btn.setAttribute('aria-pressed', erasing ? 'true' : 'false');
            if (erasing) {
                document.querySelectorAll('.color-swatch').forEach(function (b) {
                    b.classList.remove('active');
                    b.setAttribute('aria-pressed', 'false');
                });
                announce('Eraser active');
            } else {
                announce('Drawing mode active');
            }
        });
    });

    /* ── Undo ── */
    document.querySelectorAll('.undo-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            if (history.length) {
                ctx.putImageData(history.pop(), 0, 0);
                canvasDirty = true;
                canvasHasContent = hasVisiblePixels();
                syncHiddenField();
                announce('Last stroke undone');
            } else {
                announce('Nothing to undo');
            }
        });
    });

    /* ── Clear canvas ── */
    document.querySelectorAll('.clear-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            if (!confirm('Clear the canvas? This cannot be undone.')) return;
            saveSnapshot();
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            canvasDirty = true;
            canvasHasContent = false;
            syncHiddenField();
            announce('Canvas cleared');
        });
    });

}());
