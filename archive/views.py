"""Views for the archive application.

Covers five areas:
- **Knowledge Bank** (``KnowledgeBankView``, ``KnowledgeBankToolView``) — the
  primary authenticated area; groups a user's activity by tool and drills into
  per-tool submissions and sessions.
- **Archive detail / delete** (``ArchiveDetailView``, ``archive_record_delete``)
  — shows a single submission and allows the owner to delete it.
- **Feature requests** (``feature_request``) — public page that stores
  free-text feature ideas with an optional contact email.

Legacy redirect
---------------
``ArchiveDashboardView`` is kept as a permanent redirect to the Knowledge Bank
so that any bookmarks or stored links continue to work.
"""
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.conf import settings
from django.core import signing
from django.db import transaction
from django.db.models import Count, Max, Q
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.timezone import now
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, RedirectView, TemplateView

from config.rate_limit import is_rate_limited
from accounts.organisation_data_ownership import (
    session_access_q,
    solo_record_access_q,
    solo_record_management_q,
    solo_records_for_user,
)
from tools.utils import get_tool_metadata

from .feedback_context import (
    PROMPT_SUPPRESSION_COOKIE,
    PROMPT_SUPPRESSION_SECONDS,
    read_feedback_context,
)
from .forms import FeedbackForm
from .models import FeatureRequest, ToolInstance, ToolSession

# The public feature-request form accepts unauthenticated writes. Without a
# limit a bot can flood the endpoint to spam staff review
# screens and grow the database indefinitely. These caps throttle
# submissions per client IP; legitimate visitors submitting once or twice
# never notice them.
PUBLIC_FORM_MAX_ATTEMPTS = 5
PUBLIC_FORM_WINDOW_SECONDS = 10 * 60
PUBLIC_FORM_LOCKOUT_SECONDS = 30 * 60
CONTEXTUAL_FEEDBACK_MAX_ATTEMPTS = 5
CONTEXTUAL_FEEDBACK_WINDOW_SECONDS = 10 * 60
CONTEXTUAL_FEEDBACK_LOCKOUT_SECONDS = 30 * 60


def _staff_only(request):
    """Return True if the request user is authenticated and is staff."""
    return request.user.is_authenticated and request.user.is_staff


def staff_feedback_context(request):
    """Expose the new-feedback count only to authenticated staff."""
    if not _staff_only(request):
        return {}
    return {
        'staff_new_feedback_count': FeatureRequest.objects.filter(
            review_status='new',
        ).count(),
    }


# ── Knowledge Bank ─────────────────────────────────────────────────────────

class KnowledgeBankView(LoginRequiredMixin, TemplateView):
    """Index page — one card per tool the user has interacted with.

    Each card shows the tool title, total solo submissions, total sessions, and
    the date the tool was last used.  Clicking a card opens the per-tool
    drill-in view.
    """

    template_name = 'archive/knowledge_bank.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user

        # Solo submissions grouped by tool slug
        solo_rows = {
            row['tool_slug']: row
            for row in solo_records_for_user(user).filter(
                status='archived',
            ).values('tool_slug').annotate(
                count=Count('id'),
                last_used=Max('submitted_at'),
            )
        }

        # Sessions the user hosted or participated in, grouped by tool slug
        session_rows = {
            row['tool_slug']: row
            for row in ToolSession.objects.filter(
                session_access_q(user) | Q(instances__user=user)
            ).distinct().values('tool_slug').annotate(
                count=Count('id', distinct=True),
                last_used=Max('created_at'),
            )
        }

        # Merge into one entry per slug, enriched from the tool registry
        tools_used = []
        for slug in set(solo_rows) | set(session_rows):
            solo = solo_rows.get(slug, {})
            sess = session_rows.get(slug, {})
            meta = get_tool_metadata(slug) or {}

            solo_last = solo.get('last_used')
            sess_last = sess.get('last_used')
            if solo_last and sess_last:
                last_used = max(solo_last, sess_last)
            else:
                last_used = solo_last or sess_last

            tools_used.append({
                'slug': slug,
                'title': meta.get('title') or slug.replace('-', ' ').title(),
                'tagline': meta.get('tagline', ''),
                'icon': meta.get('icon', ''),
                'category': meta.get('category', ''),
                'solo_count': solo.get('count', 0),
                'session_count': sess.get('count', 0),
                'last_used': last_used,
            })

        # Most recently used first
        tools_used.sort(key=lambda x: x['last_used'], reverse=True)

        ctx['tools_used'] = tools_used
        ctx['user'] = user

        return ctx


class KnowledgeBankToolView(LoginRequiredMixin, TemplateView):
    """Drill-in page for a single tool.

    Shows all solo submissions and all sessions for the requesting user that
    involve the given ``tool_slug``, preserving all archive actions (view,
    preview, download, delete).
    """

    template_name = 'archive/knowledge_bank_tool.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        tool_slug = self.kwargs['tool_slug']
        meta = get_tool_metadata(tool_slug) or {}

        ctx['tool_slug'] = tool_slug
        ctx['tool_title'] = meta.get('title') or tool_slug.replace('-', ' ').title()
        ctx['tool_tagline'] = meta.get('tagline', '')

        ctx['records'] = solo_records_for_user(user).filter(
            status='archived',
            tool_slug=tool_slug,
        ).order_by('-submitted_at')

        ctx['sessions'] = (
            ToolSession.objects
            .filter(
                session_access_q(user) | Q(instances__user=user),
                tool_slug=tool_slug,
            )
            .distinct()
            .order_by('-created_at')
        )

        ctx['user'] = user
        return ctx


# ── Legacy redirect ────────────────────────────────────────────────────────

class ArchiveDashboardView(RedirectView):
    """Redirect old /archive/dashboard/ bookmarks to the Knowledge Bank."""
    permanent = False
    url = reverse_lazy('archive:knowledge_bank')


# ── Archive detail / delete ────────────────────────────────────────────────

class ArchiveDetailView(LoginRequiredMixin, DetailView):
    """Detail view for a single ``ToolInstance`` record.

    The queryset is scoped to ``user=request.user`` so users cannot access
    each other's records by guessing or manipulating the primary key.
    """

    model = ToolInstance
    template_name = 'archive/detail.html'
    context_object_name = 'record'

    def get_queryset(self):
        return ToolInstance.objects.filter(
            session__isnull=True,
        ).filter(solo_record_access_q(self.request.user))


@login_required
@require_POST
def archive_record_delete(request, pk):
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=request.user.pk)
        instance = get_object_or_404(
            ToolInstance.objects.select_for_update()
            .filter(session__isnull=True)
            .filter(solo_record_management_q(request.user)),
            pk=pk,
        )
        tool_slug = instance.tool_slug
        instance.delete()
    messages.success(request, 'Record deleted successfully.')
    return redirect('archive:knowledge_bank_tool', tool_slug=tool_slug)


# ── Public pages ───────────────────────────────────────────────────────────

def feedback_portal(request):
    """Public portal for feature, bug, experience, and rating feedback."""
    success = request.GET.get('result') == 'success'
    form = FeedbackForm()

    if request.method == 'POST':
        if is_rate_limited(
            request, 'feature_request', PUBLIC_FORM_MAX_ATTEMPTS,
            PUBLIC_FORM_WINDOW_SECONDS, PUBLIC_FORM_LOCKOUT_SECONDS,
        ):
            messages.error(
                request,
                'Too many submissions from this connection. Please try again later.',
            )
            return render(request, 'feedback.html', {
                'form': form,
                'success': success,
            }, status=429)
        form = FeedbackForm(request.POST)
        if form.is_valid():
            try:
                feedback = form.save(commit=False)
                feedback.source = 'portal'
                if request.user.is_authenticated:
                    feedback.submitter = request.user
                feedback.save()
                return redirect(reverse('feedback') + '?result=success')
            except Exception:
                messages.error(
                    request,
                    'Something went wrong on our end — please try again.',
                )

    return render(request, 'feedback.html', {
        'form': form,
        'success': success,
    })


# Historical callable kept for imports and old URL configuration.
feature_request = feedback_portal


@require_POST
def contextual_feedback(request):
    """Accept feedback tied to a signed, server-created tool context."""
    if is_rate_limited(
        request, 'contextual_feedback', CONTEXTUAL_FEEDBACK_MAX_ATTEMPTS,
        CONTEXTUAL_FEEDBACK_WINDOW_SECONDS,
        CONTEXTUAL_FEEDBACK_LOCKOUT_SECONDS,
    ):
        return HttpResponseBadRequest(
            'Too many submissions from this connection. Please try again later.',
            status=429,
        )

    token = request.POST.get('context_token', '')
    try:
        context = read_feedback_context(token)
    except (signing.BadSignature, signing.SignatureExpired):
        return HttpResponseBadRequest('Invalid or expired feedback context.')

    form = FeedbackForm(request.POST)
    if not form.is_valid():
        return render(request, 'feedback.html', {
            'form': form,
            'success': False,
            'context_token': token,
        }, status=400)

    feedback = form.save(commit=False)
    feedback.source = context['source']
    feedback.tool_slug = context['tool_slug']
    feedback.interaction_mode = context['interaction_mode']
    if request.user.is_authenticated:
        feedback.submitter = request.user
    feedback.save()
    response = redirect(reverse('feedback') + '?result=success')
    response.set_cookie(
        PROMPT_SUPPRESSION_COOKIE,
        '1',
        max_age=PROMPT_SUPPRESSION_SECONDS,
        httponly=True,
        secure=not settings.DEBUG,
        samesite='Lax',
    )
    return response


@require_POST
def feedback_prompt_dismiss(request):
    """Dismiss contextual prompts for this browser without requiring JS."""
    token = request.POST.get('context_token', '')
    try:
        read_feedback_context(token)
    except (signing.BadSignature, signing.SignatureExpired):
        return HttpResponseBadRequest('Invalid or expired feedback context.')

    return_to = request.POST.get('return_to', '/')
    if not url_has_allowed_host_and_scheme(
        return_to,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return_to = '/'

    response = redirect(return_to)
    response.set_cookie(
        PROMPT_SUPPRESSION_COOKIE,
        '1',
        max_age=PROMPT_SUPPRESSION_SECONDS,
        httponly=True,
        secure=not settings.DEBUG,
        samesite='Lax',
    )
    return response


# ── Staff management — Feedback ────────────────────────────────────────────

def feature_request_list(request):
    """Staff-only, filterable feedback inbox."""
    if not _staff_only(request):
        return HttpResponseForbidden('Staff access required.')
    requests_qs = FeatureRequest.objects.all().order_by('-submitted_at')
    feedback_type = request.GET.get('type') or request.GET.get('feedback_type')
    review_status = request.GET.get('status') or request.GET.get('review_status')
    source = request.GET.get('source')
    query = request.GET.get('q', '').strip()
    if feedback_type in dict(FeatureRequest.FEEDBACK_TYPES):
        requests_qs = requests_qs.filter(feedback_type=feedback_type)
    if review_status in dict(FeatureRequest.REVIEW_STATUSES):
        requests_qs = requests_qs.filter(review_status=review_status)
    if source in dict(FeatureRequest.SOURCES):
        requests_qs = requests_qs.filter(source=source)
    if query:
        requests_qs = requests_qs.filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(name__icontains=query)
            | Q(email__icontains=query)
            | Q(tool_slug__icontains=query)
            | Q(submitter__email__icontains=query)
        )
    return render(request, 'archive/feedback_list.html', {
        'requests': requests_qs,
        'count': requests_qs.count(),
        'feedback': requests_qs,
        'feedbacks': requests_qs,
        'selected_type': feedback_type or '',
        'selected_status': review_status or '',
        'selected_source': source or '',
        'query': query,
    })


def feedback_detail(request, pk):
    """Staff-only feedback detail endpoint."""
    if not _staff_only(request):
        return HttpResponseForbidden('Staff access required.')
    feedback = get_object_or_404(FeatureRequest, pk=pk)
    return render(request, 'archive/feedback_detail.html', {
        'feedback': feedback,
    })


@require_POST
def feature_request_delete(request, pk):
    """Staff-only: permanently delete one feedback item."""
    if not _staff_only(request):
        return HttpResponseForbidden('Staff access required.')
    fr = get_object_or_404(FeatureRequest, pk=pk)
    label = str(fr)
    fr.delete()
    messages.success(request, f'Deleted feedback: "{label}".')
    return redirect('archive:feedback_inbox')


@require_POST
def feedback_status_update(request, pk):
    """Staff-only review workflow mutation."""
    if not _staff_only(request):
        return HttpResponseForbidden('Staff access required.')
    review_status = request.POST.get('review_status') or request.POST.get('status')
    if review_status not in dict(FeatureRequest.REVIEW_STATUSES):
        return HttpResponseBadRequest('Invalid review status.')
    feedback = get_object_or_404(FeatureRequest, pk=pk)
    feedback.review_status = review_status
    feedback.reviewed_at = None if review_status == 'new' else now()
    feedback.save(update_fields=['review_status', 'reviewed_at'])
    return redirect('archive:feedback_detail', pk=pk)
