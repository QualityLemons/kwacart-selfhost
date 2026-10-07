/* ── LS Pathway Finder ───────────────────────────────────────────────────── */
/* jshint laxbreak: true, -W097 */
/* global SpeechSynthesisUtterance */

'use strict';

// ── Wong colour-blind-safe palette (8 colours, cycling) ──────────────────
const PALETTE = [
    { bg: '#E69F00', fg: '#000' },
    { bg: '#56B4E9', fg: '#000' },
    { bg: '#009E73', fg: '#fff' },
    { bg: '#F0E442', fg: '#000' },
    { bg: '#0072B2', fg: '#fff' },
    { bg: '#D55E00', fg: '#fff' },
    { bg: '#CC79A7', fg: '#000' },
    { bg: '#888888', fg: '#fff' },
];

// ── 33 goal statements ────────────────────────────────────────────────────
const GOALS = [
    { id:  1, short: 'Meet new people fast',         full: 'Rapidly share challenges and expectations while building new connections',                                                tools: ['impromptu-networking'] },
    { id:  2, short: 'Know your why',                full: 'Make the purpose of your work together clear',                                                                           tools: ['nine-whys'] },
    { id:  3, short: 'Look back, move forward',      full: 'Together, look back on progress to date and decide what adjustments are needed',                                          tools: ['what-so-what-now-what'] },
    { id:  4, short: 'Clear what blocks you',        full: 'Stop counterproductive activities and behaviours to make space for innovation',                                           tools: ['triz'] },
    { id:  5, short: 'Find what works',              full: 'Discover and build on the root causes of success',                                                                       tools: ['appreciative-interviews'] },
    { id:  6, short: 'Everyone shares ideas',        full: 'Engage everyone simultaneously in generating questions, ideas, and suggestions',                                          tools: ['1-2-4-all'] },
    { id:  7, short: 'Learn from experience',        full: 'Share know-how gained from experience with a larger community',                                                          tools: ['user-experience-fishbowl', 'shift-and-share'] },
    { id:  8, short: 'Act on what you can',          full: 'Discover and focus on what each person has the freedom and resources to do now',                                          tools: ['15-percent-solutions'] },
    { id:  9, short: 'Pick your best ideas',         full: "Rapidly generate and sift a group's most powerful actionable ideas",                                                     tools: ['25-10-crowd-sourcing'] },
    { id: 10, short: 'Get help right now',           full: 'Get practical and imaginative help from colleagues immediately',                                                         tools: ['troika-consulting'] },
    { id: 11, short: 'Make sense together',          full: 'Engage everyone in making sense of profound challenges',                                                                 tools: ['conversation-cafe'] },
    { id: 12, short: 'Agree the rules',              full: "Specify only the absolute must-dos and must-not-dos for achieving a purpose",                                            tools: ['min-specs'] },
    { id: 13, short: 'Wisdom from the group',        full: 'Tap the wisdom of the whole group in rapid cycles',                                                                      tools: ['wise-crowds'] },
    { id: 14, short: 'Name the big tension',         full: 'Articulate the paradoxical challenges that a group must confront to succeed',                                            tools: ['wicked-questions'] },
    { id: 15, short: 'Draw your story',              full: 'Reveal insights and paths forward through non-verbal expression',                                                        tools: ['drawing-together'] },
    { id: 16, short: 'Act it out',                   full: 'Develop effective solutions to chronic challenges while having serious fun',                                             tools: ['improv-prototyping'] },
    { id: 17, short: 'Sort your challenges',         full: 'Sort challenges into simple, complicated and complex categories',                                                        tools: ['wicked-questions', 'what-so-what-now-what'] },
    { id: 18, short: 'Spread good ideas',            full: 'Spread good ideas and make informal connections with innovators',                                                        tools: ['shift-and-share'] },
    { id: 19, short: 'Listen more deeply',           full: 'Practise deeper listening and empathy with colleagues',                                                                  tools: ['helping-heuristics', 'conversation-cafe'] },
    { id: 20, short: 'Map your connections',         full: 'Map informal connections and decide how to strengthen the network to achieve a purpose',                                 tools: ['gen-rel-star'] },
    { id: 21, short: 'Plan step by step',            full: 'Define the step-by-step design elements for bringing initiatives or meetings to productive endpoints',                    tools: ['five-structural-elements', 'interocepter'] },
    { id: 22, short: 'Lead a large group',           full: 'Liberate inherent action and leadership in large groups',                                                                tools: ['wise-crowds-large-group'] },
    { id: 23, short: 'Find local solutions',         full: 'Discover, spark and unleash local solutions to chronic problems',                                                        tools: ['discovery-action-dialogue'] },
    { id: 24, short: 'Yes-and thinking',             full: 'Move from either-or to robust both-and solutions',                                                                       tools: ['wicked-questions'] },
    { id: 25, short: 'See your relationships',       full: 'Reveal and understand relationship patterns that create value or dysfunctions',                                          tools: ['gen-rel-star'] },
    { id: 26, short: 'Plan for the unknown',         full: 'Develop strategies for successfully operating in a range of plausible yet unpredictable futures',                        tools: ['wicked-questions', 'five-structural-elements'] },
    { id: 27, short: 'Build to last',                full: 'Define the 5 elements that are essential for a resilient and enduring initiative',                                       tools: ['five-structural-elements'] },
    { id: 28, short: 'See the big picture',          full: 'Analyse the full portfolio of activities and relationships to identify obstacles and opportunities for progress',         tools: ['gen-rel-star', '15-percent-solutions'] },
    { id: 29, short: 'Understand the system',        full: 'Understand how embedded systems interact, evolve, influence the spread of innovation, and transform',                    tools: ['gen-rel-star', 'wicked-questions'] },
    { id: 30, short: "Surface what's needed",        full: 'Surface most essential needs across functions and accept or reject requests for support',                                tools: ['wise-crowds', 'wise-crowds-large-group'] },
    { id: 31, short: 'Bridge leaders and frontline', full: 'Reconnect the experience of leaders and experts with the people closest to the challenge at hand',                      tools: ['user-experience-fishbowl', 'discovery-action-dialogue'] },
    { id: 32, short: 'Practise helping',             full: 'Practise progressive methods for helping others, receiving help and asking for help',                                    tools: ['helping-heuristics'] },
    { id: 33, short: 'Watch and learn',              full: 'Observe and record actual behaviours of users in the field',                                                             tools: ['discovery-action-dialogue'] },
];

// ── Tool context metadata ─────────────────────────────────────────────────
const TOOL_META = {
    'impromptu-networking':     { min: 15,  max: 30,  minP: 6,  maxP: null, modes: ['in-person', 'virtual', 'hybrid'] },
    'nine-whys':                { min: 15,  max: 30,  minP: 2,  maxP: 30,   modes: ['in-person', 'virtual', 'hybrid'] },
    'what-so-what-now-what':    { min: 30,  max: 60,  minP: 2,  maxP: null, modes: ['in-person', 'virtual', 'hybrid'] },
    'triz':                     { min: 30,  max: 45,  minP: 5,  maxP: null, modes: ['in-person', 'virtual', 'hybrid'] },
    'appreciative-interviews':  { min: 30,  max: 60,  minP: 4,  maxP: null, modes: ['in-person', 'virtual', 'hybrid'] },
    '1-2-4-all':                { min: 12,  max: 30,  minP: 4,  maxP: null, modes: ['in-person', 'virtual', 'hybrid'] },
    'user-experience-fishbowl': { min: 45,  max: 90,  minP: 8,  maxP: null, modes: ['in-person', 'virtual'] },
    'shift-and-share':          { min: 30,  max: 60,  minP: 12, maxP: null, modes: ['in-person'] },
    '15-percent-solutions':     { min: 20,  max: 40,  minP: 2,  maxP: null, modes: ['in-person', 'virtual', 'hybrid'] },
    '25-10-crowd-sourcing':     { min: 25,  max: 45,  minP: 10, maxP: null, modes: ['in-person'] },
    'troika-consulting':        { min: 15,  max: 30,  minP: 3,  maxP: 15,   modes: ['in-person', 'virtual', 'hybrid'] },
    'conversation-cafe':        { min: 40,  max: 90,  minP: 5,  maxP: 15,   modes: ['in-person', 'virtual', 'hybrid'] },
    'min-specs':                { min: 30,  max: 60,  minP: 4,  maxP: null, modes: ['in-person', 'virtual', 'hybrid'] },
    'wise-crowds':              { min: 15,  max: 30,  minP: 4,  maxP: 20,   modes: ['in-person', 'virtual', 'hybrid'] },
    'wise-crowds-large-group':  { min: 60,  max: 90,  minP: 20, maxP: null, modes: ['in-person', 'virtual'] },
    'wicked-questions':         { min: 20,  max: 45,  minP: 4,  maxP: null, modes: ['in-person', 'virtual', 'hybrid'] },
    'drawing-together':         { min: 30,  max: 60,  minP: 2,  maxP: 30,   modes: ['in-person', 'virtual'] },
    'improv-prototyping':       { min: 20,  max: 60,  minP: 6,  maxP: 30,   modes: ['in-person'] },
    'helping-heuristics':       { min: 15,  max: 30,  minP: 3,  maxP: 15,   modes: ['in-person', 'virtual', 'hybrid'] },
    'gen-rel-star':             { min: 20,  max: 45,  minP: 4,  maxP: 30,   modes: ['in-person', 'virtual', 'hybrid'] },
    'five-structural-elements': { min: 20,  max: 45,  minP: 4,  maxP: null, modes: ['in-person', 'virtual', 'hybrid'] },
    'interocepter':             { min: 25,  max: 45,  minP: 3,  maxP: 15,   modes: ['in-person', 'virtual', 'hybrid'] },
    'discovery-action-dialogue':{ min: 30,  max: 60,  minP: 5,  maxP: null, modes: ['in-person', 'virtual', 'hybrid'] },
    'i-am-and-i-like':          { min: 15,  max: 30,  minP: 4,  maxP: null, modes: ['in-person', 'virtual', 'hybrid'] },
    'idea-generation':          { min: 15,  max: 30,  minP: 2,  maxP: null, modes: ['in-person', 'virtual', 'hybrid'] },
};

// ── Fisher-Yates shuffle ──────────────────────────────────────────────────
// Knuth's in-place uniform shuffle (Durstenfeld's computer adaptation, 1964).
// Algorithm reference: https://en.wikipedia.org/wiki/Fisher%E2%80%93Yates_shuffle
function shuffle(arr) {
    const a = [...arr];
    for (let i = a.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
}

// ── Web Speech API ────────────────────────────────────────────────────────
const speechAvailable = ('speechSynthesis' in window);

function speak(text) {
    if (!speechAvailable) return;
    window.speechSynthesis.cancel();
    const utt = new SpeechSynthesisUtterance(text);
    utt.rate = 0.9;
    utt.lang = 'en-GB';
    window.speechSynthesis.speak(utt);
}

// ── Tool data (embedded safely by Django json_script) ────────────────────
const TOOLS_DATA = JSON.parse(document.getElementById('pathway-tools-data').textContent);

// ── State ─────────────────────────────────────────────────────────────────
let state = {
    step: 1,
    minutes: null,
    people: null,
    modality: null,
    selectedGoals: new Set(),
};

// ── DOM refs ──────────────────────────────────────────────────────────────
const panels      = document.querySelectorAll('.pathway-panel');
const stepDots    = document.querySelectorAll('.pathway-step-dot');
const stepLines   = document.querySelectorAll('.pathway-step-line');
const countBadge  = document.getElementById('pathway-circle-count');
const circlesGrid = document.getElementById('pathway-circles-grid');
const resultCards = document.getElementById('pathway-result-cards');

// ── Step display ──────────────────────────────────────────────────────────
function showStep(n) {
    state.step = n;
    panels.forEach((p, i) => p.classList.toggle('active', i + 1 === n));
    stepDots.forEach((d, i) => {
        d.classList.remove('active', 'done');
        if      (i + 1 === n) d.classList.add('active');
        else if (i + 1 <  n) d.classList.add('done');
    });
    stepLines.forEach((l, i) => l.classList.toggle('done', i + 1 < n));
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ── Steps 1 & 2: option pickers with auto-advance ────────────────────────
function bindAutoAdvance(containerSelector, stateKey, nextStep) {
    const container = document.querySelector(containerSelector);
    if (!container) return;
    container.querySelectorAll('.pathway-option').forEach(btn => {
        btn.addEventListener('click', () => {
            container.querySelectorAll('.pathway-option').forEach(b => b.classList.remove('selected'));
            btn.classList.add('selected');
            state[stateKey] = isNaN(Number(btn.dataset.value))
                ? btn.dataset.value
                : Number(btn.dataset.value);
            setTimeout(() => showStep(nextStep), 260);
        });
    });
}

// ── Step 3: modality — select only, Next button advances ─────────────────
function bindSelectOnly(containerSelector, stateKey) {
    const container = document.querySelector(containerSelector);
    if (!container) return;
    container.querySelectorAll('.pathway-option').forEach(btn => {
        btn.addEventListener('click', () => {
            container.querySelectorAll('.pathway-option').forEach(b => b.classList.remove('selected'));
            btn.classList.add('selected');
            state[stateKey] = btn.dataset.value;
            document.getElementById('btn-to-goals').removeAttribute('disabled');
        });
    });
}

// ── Step 4: build goal circles ────────────────────────────────────────────
function buildCircles() {
    state.selectedGoals.clear();
    countBadge.textContent = '0';
    countBadge.style.display = 'none';

    const shuffled = shuffle(GOALS);
    circlesGrid.innerHTML = '';

    shuffled.forEach((goal, idx) => {
        const col = PALETTE[idx % PALETTE.length];
        const div = document.createElement('div');
        div.className = 'goal-circle';
        div.dataset.id = goal.id;
        div.style.background = col.bg;
        div.style.color = col.fg;
        div.setAttribute('role', 'checkbox');
        div.setAttribute('aria-checked', 'false');
        div.setAttribute('tabindex', '0');
        div.setAttribute('aria-label', goal.full);

        const textSpan = document.createElement('span');
        textSpan.className = 'goal-circle-text';
        textSpan.textContent = goal.short;

        const audioBtn = document.createElement('button');
        audioBtn.className = 'goal-audio-btn';
        audioBtn.type = 'button';
        audioBtn.setAttribute('aria-label', 'Read aloud');
        audioBtn.dataset.text = goal.full;
        audioBtn.textContent = '🔊';
        if (!speechAvailable) audioBtn.style.display = 'none';

        div.appendChild(textSpan);
        div.appendChild(audioBtn);
        circlesGrid.appendChild(div);

        div.addEventListener('click', e => {
            if (e.target.closest('.goal-audio-btn')) return;
            const gid = Number(div.dataset.id);
            if (state.selectedGoals.has(gid)) {
                state.selectedGoals.delete(gid);
                div.classList.remove('selected');
                div.setAttribute('aria-checked', 'false');
            } else {
                state.selectedGoals.add(gid);
                div.classList.add('selected');
                div.setAttribute('aria-checked', 'true');
            }
            const count = state.selectedGoals.size;
            countBadge.textContent = count;
            countBadge.style.display = count ? '' : 'none';
        });

        div.addEventListener('keydown', e => {
            if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); div.click(); }
        });

        audioBtn.addEventListener('click', e => {
            e.stopPropagation();
            speak(audioBtn.dataset.text);
        });
    });
}

// ── Scoring ───────────────────────────────────────────────────────────────
function computeScores() {
    const scores = {};
    for (const gid of state.selectedGoals) {
        const goal = GOALS.find(g => g.id === gid);
        if (!goal) continue;
        for (const slug of goal.tools) {
            scores[slug] = (scores[slug] || 0) + 3;
        }
    }
    for (const [slug, meta] of Object.entries(TOOL_META)) {
        if (!scores[slug]) continue;
        if (state.minutes  !== null && meta.min <= state.minutes)  scores[slug] += 2;
        if (state.people   !== null && meta.minP <= state.people && (meta.maxP === null || state.people <= meta.maxP)) scores[slug] += 2;
        if (state.modality !== null && meta.modes.includes(state.modality)) scores[slug] += 1;
    }
    return scores;
}

function getTopTools(limit = 6) {
    const scores = computeScores();
    return Object.entries(scores)
        .sort(([, a], [, b]) => b - a)
        .slice(0, limit)
        .map(([slug, score]) => ({ slug, score }));
}

// ── CSRF token (read from cookie so POST forms work) ─────────────────────
function getCsrfToken() {
    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? match[1] : '';
}

// ── Results ───────────────────────────────────────────────────────────────
function renderResults() {
    const top = getTopTools();
    resultCards.innerHTML = '';

    if (top.length === 0) {
        resultCards.innerHTML = '<p class="pathway-no-results">No goals were selected — please go back and choose at least one circle.</p>';
        return;
    }

    const rankLabels = ['1st', '2nd', '3rd', '4th', '5th', '6th'];
    top.forEach(({ slug }, idx) => {
        const info = TOOLS_DATA[slug];
        if (!info) return;
        const card = document.createElement('div');
        card.className = 'pathway-result-card';
        const csrf = getCsrfToken();
        card.innerHTML = `
            <div class="pathway-result-rank">${rankLabels[idx] || (idx + 1) + 'th'}</div>
            <div class="pathway-result-body">
                <h3>${info.title}</h3>
                <p>${info.tagline}</p>
                <div class="pathway-result-actions">
                    <a href="/tools/${slug}/draft/">Work Solo</a>
                    <form method="post" action="/tools/${slug}/session/start/" style="display:inline;margin:0;">
                        <input type="hidden" name="csrfmiddlewaretoken" value="${csrf}">
                        <button type="submit" class="pathway-session-btn">Start a Session</button>
                    </form>
                </div>
            </div>`;
        resultCards.appendChild(card);
    });
}

// ── Button wiring ─────────────────────────────────────────────────────────
bindAutoAdvance('#pathway-time-options',   'minutes',  2);
bindAutoAdvance('#pathway-people-options', 'people',   3);
bindSelectOnly('#pathway-modality-options', 'modality');

document.getElementById('btn-to-goals').addEventListener('click', () => {
    buildCircles();
    showStep(4);
});

document.getElementById('btn-goals-back').addEventListener('click', () => showStep(3));

document.getElementById('btn-find-pathway').addEventListener('click', () => {
    renderResults();
    showStep(5);
});

document.getElementById('btn-results-back').addEventListener('click', () => showStep(4));

document.getElementById('btn-start-over').addEventListener('click', () => {
    state = { step: 1, minutes: null, people: null, modality: null, selectedGoals: new Set() };
    document.querySelectorAll('.pathway-option').forEach(b => b.classList.remove('selected'));
    document.getElementById('btn-to-goals').setAttribute('disabled', '');
    showStep(1);
});

// ── Back button in step 3 (inline onclick in template calls this) ─────────
window.showStep = showStep;

// ── Init ──────────────────────────────────────────────────────────────────
document.getElementById('btn-to-goals').setAttribute('disabled', '');
showStep(1);
