/* ── Try-it countdown timer ── */
/* Standalone countdown for the public tool-try page.
   Duration is read from data-duration on the #try-timer element. */
(function () {

    /* ── Config from HTML ── */
    var timerEl          = document.getElementById('try-timer');
    if (!timerEl) return;
    var TOTAL            = parseInt(timerEl.dataset.duration, 10);
    var ANNOUNCE_DELAY_MS = 50;

    /* ── State ── */
    var remaining  = TOTAL;
    var running    = false;
    var intervalId = null;
    var announced  = new Set();

    /* ── Element references ── */
    var display  = document.getElementById('try-timer-display');
    var btn      = document.getElementById('try-timer-btn');
    var resetBtn = document.getElementById('try-timer-reset');
    var bar      = document.getElementById('try-timer-bar');
    var complete = document.getElementById('try-timer-complete');
    var live     = document.getElementById('try-timer-announcer');

    /* ── Helpers ── */
    function fmt(s) {
        var m  = Math.floor(s / 60);
        var sc = s % 60;
        return String(m).padStart(2, '0') + ':' + String(sc).padStart(2, '0');
    }

    function announce(msg) {
        live.textContent = '';
        setTimeout(function () { live.textContent = msg; }, ANNOUNCE_DELAY_MS);
    }

    /* ── Render ── */
    function render() {
        var t = fmt(remaining);
        display.textContent = t;
        display.setAttribute('aria-label', t + ' remaining');
        bar.style.width = (TOTAL > 0 ? (remaining / TOTAL * 100) : 0) + '%';
    }

    /* ── Milestone announcements ── */
    function checkMilestones() {
        [300, 120, 60, 30, 10].forEach(function (m) {
            if (remaining === m && !announced.has(m)) {
                announced.add(m);
                var mins  = Math.floor(remaining / 60);
                var secs  = remaining % 60;
                var label = mins > 0 ?
                    mins + ' minute' + (mins !== 1 ? 's' : '') + (secs ? ' ' + secs + 's' : '') :
                    remaining + ' seconds';
                announce(label + ' remaining');
            }
        });
    }

    /* ── Finish ── */
    function finish() {
        running = false;
        clearInterval(intervalId);
        remaining = 0;
        render();
        btn.textContent   = 'Start';
        btn.disabled      = true;
        btn.style.opacity = '0.4';
        bar.style.background     = '#40B0A6';
        complete.style.display   = 'block';
        announce("Time is up. Complete your answer and submit whenever you're ready.");
    }

    /* ── Tick ── */
    function tick() {
        remaining -= 1;
        render();
        checkMilestones();
        if (remaining <= 0) finish();
    }

    /* ── Start / pause button ── */
    btn.addEventListener('click', function () {
        if (remaining <= 0) return;
        if (running) {
            running = false;
            clearInterval(intervalId);
            btn.textContent      = 'Resume';
            btn.style.background = '#40B0A6';
            announce('Timer paused \u2014 ' + fmt(remaining) + ' remaining');
        } else {
            running = true;
            btn.textContent      = 'Pause';
            btn.style.background = '#E66100';
            announce('Timer started \u2014 ' + fmt(remaining) + ' remaining');
            intervalId = setInterval(tick, 1000);
        }
    });

    /* ── Reset button ── */
    resetBtn.addEventListener('click', function () {
        running = false;
        clearInterval(intervalId);
        remaining            = TOTAL;
        announced            = new Set();
        btn.textContent      = 'Start';
        btn.disabled         = false;
        btn.style.opacity    = '1';
        btn.style.background = '#5D3A9B';
        bar.style.background = '#5D3A9B';
        complete.style.display = 'none';
        render();
        announce('Timer reset to ' + fmt(TOTAL));
    });

    render();

}());
