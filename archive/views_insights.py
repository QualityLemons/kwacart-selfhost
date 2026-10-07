"""Insights Dashboard for the archive application.

Surfaces cross-session keyword-frequency trends across all workshops hosted
by the authenticated user, giving facilitators a historical organisational
record of how themes and blockers shift over time.

Data scope
----------
  - Solo archived submissions owned by the requesting user.
  - ALL ToolInstances from sessions the user hosted — so the facilitator
    sees the entire team's responses, not just their own.

Text sources searched
---------------------
  payload_input, payload_output, and attachment transcriptions (added via
  the Multimedia Input Bridge / Synthesis Workspace).

Route:  GET /archive/insights/
Params: keyword (str), range (1m|3m|6m|12m), submitted as HTML form GET.
"""
import re
from collections import Counter
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from .models import ToolInstance

# ── Stop-word list ────────────────────────────────────────────────────────────
_STOP_WORDS = frozenset({
    'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
    'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
    'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
    'could', 'should', 'may', 'might', 'can', 'this', 'that', 'these',
    'those', 'i', 'we', 'you', 'he', 'she', 'it', 'they', 'me', 'us',
    'him', 'her', 'them', 'my', 'our', 'your', 'his', 'its', 'their',
    'what', 'which', 'who', 'when', 'where', 'how', 'why', 'not', 'no',
    'so', 'if', 'then', 'than', 'as', 'up', 'out', 'about', 'into',
    'through', 'during', 'before', 'after', 'each', 'other', 'some',
    'there', 'all', 'any', 'also', 'just', 'because', 'while', 'get',
    'got', 'use', 'used', 'need', 'needs', 'very', 'one', 'two', 'three',
    'many', 'more', 'most', 'much', 'well', 'own', 'new', 'good', 'make',
    'made', 'like', 'time', 'work', 'way', 'say', 'said', 'know', 'think',
    'see', 'come', 'want', 'look', 'give', 'take', 'put', 'here', 'now',
    'even', 'back', 'still', 'too', 'down', 'only', 'over', 'after',
})

_RANGE_DAYS = {'1m': 30, '3m': 92, '6m': 183, '12m': 365}
_RANGE_LABELS = {
    '1m': 'last month',
    '3m': 'last 3 months',
    '6m': 'last 6 months',
    '12m': 'last year',
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_texts(inst):
    """Collect all searchable text strings from a ToolInstance."""
    texts = []
    if inst.payload_input:
        texts.extend(str(v) for v in inst.payload_input.values() if v)
    if inst.payload_output:
        texts.extend(str(v) for v in inst.payload_output.values() if v)
    if inst.attachments:
        for att in inst.attachments:
            t = (att.get('transcription') or '').strip()
            if t:
                texts.append(t)
    return texts


def _get_instances(user, since):
    """Return all ToolInstances in scope for the Insights Dashboard.

    Includes: the user's own solo archived submissions, and every instance
    from sessions the user hosted (the full team picture).
    """
    return (
        ToolInstance.objects
        .filter(
            Q(user=user, session__isnull=True, status='archived') |
            Q(session__host=user, status='archived'),
        )
        .filter(submitted_at__gte=since)
        .select_related('session')
        .order_by('submitted_at')
    )


def _keyword_trend(instances, keyword, granularity):
    """Return time-bucketed keyword frequency as chart-ready data.

    Returns ``None`` when the queryset is empty, or a dict with:
      periods   — list of {sort_key, label, count, pct}
      max_count — highest count in any single period
      total     — sum across all periods
    """
    kw_lower = keyword.lower()
    buckets = {}   # sort_key → {label, count}

    for inst in instances:
        full = ' '.join(_extract_texts(inst)).lower()
        n = full.count(kw_lower)

        dt = inst.submitted_at
        if granularity == 'week':
            d = dt.date()
            week_start = d - timedelta(days=d.weekday())
            sort_key = week_start.isoformat()
            label = week_start.strftime('%d %b')
        else:
            sort_key = dt.strftime('%Y-%m')
            label = dt.strftime('%b %Y')

        if sort_key not in buckets:
            buckets[sort_key] = {'label': label, 'count': 0}
        buckets[sort_key]['count'] += n

    sorted_items = sorted(buckets.items())
    if not sorted_items:
        return None

    max_count = max(d['count'] for _, d in sorted_items)
    total = sum(d['count'] for _, d in sorted_items)

    return {
        'periods': [
            {
                'sort_key': k,
                'label': d['label'],
                'count': d['count'],
                'pct': round(d['count'] / max_count * 100) if max_count else 0,
            }
            for k, d in sorted_items
        ],
        'max_count': max_count,
        'total': total,
    }


def _top_terms(instances, n=24):
    """Return the top-N content words from all instance texts.

    Each entry is a dict: {term, count, size} where ``size`` is a rem value
    (0.8–1.9) scaled to frequency for rendering as a word cloud.
    """
    counter = Counter()
    for inst in instances:
        words = re.findall(r'\b[a-z]{3,}\b', ' '.join(_extract_texts(inst)).lower())
        counter.update(w for w in words if w not in _STOP_WORDS)

    top = counter.most_common(n)
    if not top:
        return []

    max_freq = top[0][1]
    min_freq = top[-1][1] if len(top) > 1 else max_freq
    freq_range = max(max_freq - min_freq, 1)

    return [
        {
            'term': term,
            'count': count,
            'size': round(0.75 + (count - min_freq) / freq_range * 1.15, 2),
        }
        for term, count in top
    ]


def _matching_records(instances, keyword):
    """Return sessions/solos where the keyword appears, sorted most-recent first.

    Session instances are grouped by session so the facilitator sees one card
    per workshop (with the aggregate mention count) rather than one per person.
    """
    kw_lower = keyword.lower()
    sessions_seen = {}
    solos = []

    for inst in instances:
        texts = _extract_texts(inst)
        full = ' '.join(texts)
        count = full.lower().count(kw_lower)
        if count == 0:
            continue

        # Build a short context snippet around the first occurrence
        idx = full.lower().find(kw_lower)
        start = max(0, idx - 80)
        end = min(len(full), idx + len(keyword) + 80)
        snippet = full[start:end].strip()
        if start > 0:
            snippet = '\u2026' + snippet
        if end < len(full):
            snippet += '\u2026'

        if inst.session_id:
            sid = str(inst.session_id)
            if sid not in sessions_seen:
                sessions_seen[sid] = {
                    'type': 'session',
                    'session_id': inst.session_id,
                    'tool_slug': (inst.session.tool_slug if inst.session else inst.tool_slug),
                    'date': (inst.session.closed_at if inst.session else inst.submitted_at),
                    'count': 0,
                    'snippet': snippet,
                    'url': reverse('tools:session_detail', args=[inst.session_id]),
                }
            sessions_seen[sid]['count'] += count
        else:
            solos.append({
                'type': 'solo',
                'instance_id': inst.id,
                'tool_slug': inst.tool_slug,
                'date': inst.submitted_at,
                'count': count,
                'snippet': snippet,
                'url': reverse('archive:detail', args=[inst.id]),
            })

    all_matches = list(sessions_seen.values()) + solos
    return sorted(
        all_matches,
        key=lambda m: m['date'] or timezone.now(),
        reverse=True,
    )[:20]


# ── View ──────────────────────────────────────────────────────────────────────

@login_required
def insights_dashboard(request):
    """Render the Insights Dashboard.

    GET params
    ----------
    keyword : str  — term to track (empty → show word cloud of top terms)
    range   : str  — one of 1m | 3m | 6m | 12m  (default: 3m)
    """
    keyword    = request.GET.get('keyword', '').strip()
    date_range = request.GET.get('range', '3m')
    if date_range not in _RANGE_DAYS:
        date_range = '3m'

    days        = _RANGE_DAYS[date_range]
    granularity = 'week' if days <= 92 else 'month'
    since       = timezone.now() - timedelta(days=days)
    instances   = _get_instances(request.user, since)

    total_responses = instances.count()
    total_sessions  = (
        instances.exclude(session__isnull=True)
        .values_list('session_id', flat=True)
        .distinct()
        .count()
    )

    chart_data       = None
    matching_records = []
    top_terms        = []

    if keyword:
        chart_data       = _keyword_trend(instances, keyword, granularity)
        matching_records = _matching_records(instances, keyword)
    else:
        top_terms = _top_terms(instances)

    return render(request, 'archive/insights.html', {
        'keyword':          keyword,
        'date_range':       date_range,
        'range_label':      _RANGE_LABELS[date_range],
        'granularity':      granularity,
        'since':            since,
        'total_responses':  total_responses,
        'total_sessions':   total_sessions,
        'chart_data':       chart_data,
        'matching_records': matching_records,
        'top_terms':        top_terms,
        'range_options': [
            ('1m',  'Last month'),
            ('3m',  'Last quarter'),
            ('6m',  'Last 6 months'),
            ('12m', 'Last year'),
        ],
    })
