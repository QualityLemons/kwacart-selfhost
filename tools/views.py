"""View functions and class-based views for the tools application.

Covers three user journeys:
- **Public try-it** (``tool_try``) — unauthenticated preview for the two
  featured free tools (Min Specs and 15% Solutions).
- **Solo drafting** (``draft_editor``, ``autosave_endpoint``, ``submit_tool``)
  — an authenticated user works through a tool form, autosaving as they go,
  then submitting to produce an archived record and downloadable export files.
- **Collaborative session** (``session_create`` through ``guest_respond``) —
  a host opens a session, shares a link (and QR code) with participants, each
  person fills in the form, and the host closes the session to run the tool
  across all contributions simultaneously.
"""
import json
import random
import hashlib
import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.cache import cache
from django.core.exceptions import RequestDataTooBig, ValidationError
from django.db import transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from archive.models import ToolInstance, ToolSession
from archive.assets import delete_attachment_asset
from accounts.organisation_data_ownership import (
    create_owned_session,
    create_owned_solo_record,
    session_management_q,
    solo_records_for_user,
)
from exporters.pipeline import run_export_pipeline, run_session_export_pipeline
from config.rate_limit import client_ip, is_layered_rate_limited

from .registry import TOOL_CATALOG, get_tool_form_class, get_tool_instance
from .utils import (
    _normalize_meta,
    canvas_write_lock,
    extract_canvas_from_payload,
    get_tool_metadata,
)


# Only these slugs are accepted by the anonymous /try/ page.
# All other tool slugs require the user to be logged in.
FREE_TOOL_SLUGS = {'min-specs', '15-percent-solutions'}

# Hosting safeguards. Deployments may lower these values through Django
# settings, while conservative defaults keep a single workshop useful.
MAX_SESSION_PARTICIPANTS = getattr(settings, 'MAX_SESSION_PARTICIPANTS', 100)
MAX_ACTIVE_SESSIONS_PER_USER = getattr(settings, 'MAX_ACTIVE_SESSIONS_PER_USER', 10)
MAX_REQUEST_PAYLOAD_BYTES = getattr(settings, 'MAX_TOOL_PAYLOAD_BYTES', 8 * 1024 * 1024)
MAX_ATTACHMENTS_PER_PARTICIPANT = getattr(settings, 'MAX_ATTACHMENTS_PER_PARTICIPANT', 5)
MAX_ATTACHMENT_BYTES_PER_PARTICIPANT = getattr(
    settings, 'MAX_ATTACHMENT_BYTES_PER_PARTICIPANT', 50 * 1024 * 1024,
)


def _throttled(request, scope, session_id=None, *, limits=(120, 120, 600), window=60):
    return is_layered_rate_limited(
        request, scope, ip_limit=limits[0], user_limit=limits[1],
        session_limit=limits[2], session_id=session_id,
        window_seconds=window, lockout_seconds=window,
    )


def _too_many_json():
    response = JsonResponse({'error': 'too many requests'}, status=429)
    response['Retry-After'] = '60'
    return response


def _payload_too_large(request):
    try:
        declared = int(request.META.get('CONTENT_LENGTH') or 0)
    except (TypeError, ValueError):
        declared = 0
    if declared > MAX_REQUEST_PAYLOAD_BYTES:
        return True
    # WSGI normally supplies CONTENT_LENGTH, but do not let a missing or
    # malformed header bypass the cap. Accessing body here is safe before
    # request.POST and Django caches it for subsequent parsing.
    if declared <= 0:
        try:
            return len(request.body) > MAX_REQUEST_PAYLOAD_BYTES
        except RequestDataTooBig:
            return True
    return False


def tool_try(request, tool_slug):
    """Anonymous single-page try-it view for the two featured free tools.

    Uses Post/Redirect/Get: a valid submission computes the result, stores it
    in the server-side session, then redirects to a GET so that the browser
    history entry is the GET URL.  Pressing back/forward never triggers a
    "Confirm Form Resubmission" dialog.
    """
    if tool_slug not in FREE_TOOL_SLUGS:
        raise Http404

    tool_meta = get_tool_metadata(tool_slug)
    form_class = get_tool_form_class(tool_slug)
    result = None
    result_fields = []

    session_key = f'tool_try_result_{tool_slug}'

    if request.method == 'POST':
        if _payload_too_large(request):
            return HttpResponse('Request payload too large.', status=413)
        if _throttled(request, 'public-free-try', limits=(12, 12, 20), window=300):
            return HttpResponse('Too many requests. Please try again later.', status=429)
        form = form_class(request.POST)
        if form.is_valid():
            try:
                tool = get_tool_instance(tool_slug, form.cleaned_data)
                if tool:
                    result = tool.execute()
                    phases = getattr(tool, 'PHASES', ())
                    # Filter out phases whose output is empty so the result
                    # section does not render blank headings.
                    computed_fields = [
                        [label, result.get(field, '')]
                        for field, label in phases
                        if result.get(field, '').strip()
                    ]
                    request.session[session_key] = {
                        'result': result,
                        'result_fields': computed_fields,
                    }
                    return redirect(
                        reverse('tools:tool_try', args=[tool_slug]) + '?done=1'
                    )
            except Exception as exc:
                result = {'error': str(exc)}
                request.session[session_key] = {'result': result, 'result_fields': []}
                return redirect(
                    reverse('tools:tool_try', args=[tool_slug]) + '?done=1'
                )
    else:
        form = form_class()
        if request.GET.get('done') and session_key in request.session:
            # Keep the transient result available while the user remains on
            # the PRG result URL. This lets a no-JS feedback dismissal round
            # trip redraw the completed result instead of dropping it.
            stored = request.session[session_key]
            result = stored.get('result')
            result_fields = [tuple(pair) for pair in stored.get('result_fields', [])]
        elif session_key in request.session:
            # Returning to the blank form starts a fresh run and clears the
            # previous result from the browser session.
            request.session.pop(session_key)

    result_json = ''
    if result_fields:
        result_json = json.dumps({
            'tool_title': tool_meta.get('title', tool_slug),
            'date': timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M'),
            'result_fields': [[label, value] for label, value in result_fields],
            'filename': (
                f"{timezone.localtime(timezone.now()).strftime('%Y%m%d')}"
                f"_{tool_slug}.md"
            ),
        })

    return render(request, 'tools/tool_try.html', {
        'tool_meta': tool_meta,
        'form': form,
        'result': result,
        'result_fields': result_fields,
        'result_json': result_json,
        'tool_slug': tool_slug,
        'try_timer_seconds': tool_meta.get('try_timer_seconds', 0),
        'try_timer_label': tool_meta.get('try_timer_label', ''),
    })


@login_required
def tool_catalog(request):
    """Lists all available tools, split into Solo and Live Session zones.

    Accepts an optional ``mode`` GET parameter (``solo`` | ``live``) that
    renders the page in a single-zone view with the appropriate action.
    Without a mode the page shows a prominent two-zone picker so hosts
    arriving to run a workshop are never presented with the solo catalog
    first.

    Extra context injected for authenticated users:
      recent_drafts   — last 3 solo archived submissions (solo zone)
      active_sessions — currently open sessions they host (live zone)
    """
    mode = request.GET.get('mode', '')
    if mode not in ('solo', 'live'):
        mode = ''

    categories = {}
    for slug, info in TOOL_CATALOG.items():
        cat = info.get('category', 'General')
        categories.setdefault(cat, []).append(_normalize_meta(slug, info))

    _order = ['Low-Risk Warm-ups', 'Facilitation', 'General']
    categories = dict(sorted(
        categories.items(),
        key=lambda kv: _order.index(kv[0]) if kv[0] in _order else 99,
    ))

    ctx = {'categories': categories, 'mode': mode}

    if request.user.is_authenticated:
        if mode in ('solo', ''):
            ctx['recent_drafts'] = list(
                solo_records_for_user(request.user)
                .filter(status='archived')
                .order_by('-submitted_at')[:3]
            )
        if mode in ('live', ''):
            ctx['active_sessions'] = list(
                ToolSession.objects
                .filter(host=request.user)
                .filter(status='open')
                .order_by('-created_at')[:3]
            )

    return render(request, 'tools/catalog.html', ctx)


# --- Solo flow ---------------------------------------------------------------

@login_required
def draft_editor(request, tool_slug, instance_id=None):
    """Render the drafting interface for a given tool and persist drafts on POST.

    When ``instance_id`` is omitted a new draft is created on the first POST.
    When ``instance_id`` is provided the existing draft is loaded for editing.
    """
    tool_meta = get_tool_metadata(tool_slug)
    if not tool_meta:
        return redirect('tools:catalog')

    instance = None
    if instance_id:
        instance = get_object_or_404(
            ToolInstance, id=instance_id, user=request.user,
            status='draft', session__isnull=True,
        )

    form_class = get_tool_form_class(tool_slug)
    form = None

    if form_class is not None:
        if request.method == 'POST':
            form = form_class(request.POST)
            if form.is_valid():
                try:
                    tool_class = get_tool_instance(tool_slug)
                    if instance is None:
                        instance = create_owned_solo_record(
                            request.user,
                            tool_slug=tool_slug,
                            tool_version=getattr(tool_class, 'version', '1.0'),
                            status='draft',
                        )
                    with canvas_write_lock(
                        form.cleaned_data, tool_slug, request.user.id,
                    ), transaction.atomic():
                        instance.payload_input = extract_canvas_from_payload(
                            form.cleaned_data, tool_slug, request.user.id,
                            existing_canvas=(instance.payload_input or {}).get('canvas_data', ''),
                        )
                        instance.save()
                    messages.success(request, 'Draft saved.')
                    return redirect('tools:draft_edit',
                                    tool_slug=tool_slug, instance_id=instance.id)
                except Exception:
                    messages.error(
                        request,
                        'Unable to save your draft — please try again.',
                    )
        else:
            initial = (instance.payload_input if instance else None) or {}
            form = form_class(initial=initial)

    return render(request, 'tools/draft_editor.html', {
        'tool_slug': tool_slug,
        'tool_meta': tool_meta,
        'instance': instance,
        'form': form,
    })


@login_required
@require_POST
def autosave_endpoint(request, tool_slug):
    """AJAX endpoint that persists in-progress draft input.

    If ``instance_id`` is present in the request body the draft already
    exists and is updated in place.  Otherwise a new draft is created and
    its ID is returned so the client can reference it on subsequent saves.
    """
    if _payload_too_large(request):
        return JsonResponse({'error': 'request payload too large'}, status=413)
    if _throttled(request, 'solo-autosave', limits=(100, 60, 60)):
        return _too_many_json()
    if tool_slug not in TOOL_CATALOG:
        return JsonResponse({'error': 'unknown tool'}, status=400)
    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'invalid request body'}, status=400)
    instance_id = data.get('instance_id')
    form_data = data.get('form_data') or {}
    if not isinstance(form_data, dict):
        return JsonResponse({'error': 'form_data must be an object'}, status=400)

    if instance_id:
        instance = get_object_or_404(
            ToolInstance, id=instance_id, user=request.user, status='draft',
        )
    else:
        tool_class = get_tool_instance(tool_slug)
        instance = create_owned_solo_record(
            request.user,
            tool_slug=tool_slug,
            tool_version=getattr(tool_class, 'version', '1.0'),
            status='draft',
        )

    try:
        with canvas_write_lock(
            form_data, tool_slug, request.user.id,
        ), transaction.atomic():
            form_data = extract_canvas_from_payload(
                form_data,
                tool_slug,
                request.user.id,
                existing_canvas=(instance.payload_input or {}).get('canvas_data', ''),
            )
            instance.payload_input = form_data
            instance.save()
    except ValidationError:
        return JsonResponse({'error': 'invalid canvas data'}, status=400)

    return JsonResponse({
        'status': 'success',
        'instance_id': instance.id,
        'last_saved': instance.updated_at.strftime('%H:%M:%S'),
    })


@login_required
@require_POST
def submit_tool(request, instance_id):
    """Run the tool's logic and transition the draft to an archived record.

    The ``session__isnull=True`` guard ensures this endpoint only handles solo
    submissions.  Session contributions are submitted by ``session_close``,
    not by this view.
    """
    if _payload_too_large(request):
        return HttpResponse('Request payload too large.', status=413)
    if _throttled(request, 'solo-submit-export', limits=(12, 6, 6), window=3600):
        response = HttpResponse(
            'Too many exports. Please try again later.', status=429,
        )
        response['Retry-After'] = '3600'
        return response
    instance = get_object_or_404(
        ToolInstance, id=instance_id, user=request.user,
        status='draft', session__isnull=True,
    )

    try:
        with transaction.atomic():
            tool_class = get_tool_instance(instance.tool_slug, instance.payload_input)
            if not tool_class:
                raise Exception('Tool definition not found in registry.')

            result_data = tool_class.execute()

            instance.payload_output = result_data
            instance.status = 'archived'
            instance.submitted_at = timezone.now()
            instance.save()

            run_export_pipeline(instance)

        messages.success(request, 'Tool execution successful. Files generated.')
        return redirect('archive:detail', pk=instance.id)

    except ValidationError as e:
        messages.error(request, f'Validation Error: {e.message}')
        return redirect('tools:draft_edit', tool_slug=instance.tool_slug,
                        instance_id=instance.id)
    except Exception as e:
        messages.error(request, f'System Error: {str(e)}')
        return redirect('tools:draft_edit', tool_slug=instance.tool_slug,
                        instance_id=instance.id)


# --- Collaborative session flow ---------------------------------------------

def _generate_pairing_code():
    """Return a unique 3-digit zero-padded pairing code (e.g. '042').

    Picks at random from the pool of codes not currently held by any open
    session.  In the extremely unlikely event that all 1000 codes are taken
    an empty string is returned and the session opens without a code.
    """
    used = set(
        ToolSession.objects.filter(status='open', pairing_code__gt='')
        .values_list('pairing_code', flat=True)
    )
    available = [f'{n:03d}' for n in range(1000) if f'{n:03d}' not in used]
    return random.choice(available) if available else ''


@login_required
@require_POST
def session_create(request, tool_slug):
    """Create a new collaborative session for the given tool."""
    if tool_slug not in TOOL_CATALOG:
        return redirect('tools:catalog')

    if _throttled(request, 'session-create', limits=(20, 10, 10), window=3600):
        return HttpResponse('Too many sessions created. Please try again later.', status=429)
    tool_class = get_tool_instance(tool_slug)
    with transaction.atomic():
        # Locking the host serialises the count and insert across workers.
        get_user_model().objects.select_for_update().get(pk=request.user.pk)
        if ToolSession.objects.filter(host=request.user, status='open').count() >= MAX_ACTIVE_SESSIONS_PER_USER:
            return HttpResponse(
                'Close an active session before starting another.', status=429,
            )
        session = create_owned_session(
            request.user,
            tool_slug=tool_slug,
            tool_version=getattr(tool_class, 'version', '1.0'),
            pairing_code=_generate_pairing_code(),
        )
    messages.success(
        request, 'Session started. Share the link with participants.'
    )
    return redirect('tools:session_detail', session_id=session.id)


def _is_session_member(request, session):
    """True if the requester is the host or already has a participant instance.

    This is the same host-or-participant membership boundary already enforced
    by ``session_status`` and the archive views; ``session_detail`` must match
    it rather than granting access to any authenticated account.
    """
    return (
        session.host_id == request.user.id
        or session.data_owner_id == request.user.id
        or ToolInstance.objects.filter(session=session, user=request.user).exists()
    )


@login_required
def session_detail(request, session_id):
    """Render the session page (form while open, combined view when closed).

    Only the host and existing participants may view a session. A brand-new
    authenticated participant can be enrolled for the first time only by
    following the host's invite link, which carries the session's
    ``guest_token`` as a ``t`` query parameter — knowing the bare session UUID
    is not sufficient. Closed sessions never auto-enroll new participants.
    """
    session = get_object_or_404(ToolSession, id=session_id)
    if request.method == 'POST':
        if _payload_too_large(request):
            return HttpResponse('Request payload too large.', status=413)
        if _throttled(request, 'participant-respond', session_id, limits=(40, 30, 400), window=300):
            return HttpResponse('Too many requests. Please try again later.', status=429)
    tool_meta = get_tool_metadata(session.tool_slug)
    if not tool_meta:
        return redirect('tools:catalog')

    is_host = (session.host_id == request.user.id)
    is_member = _is_session_member(request, session)

    if not is_member:
        invite_token = request.GET.get('t', '')
        valid_invite = bool(invite_token) and invite_token == str(session.guest_token)
        if session.status != 'open' or not valid_invite:
            raise Http404
        # Valid one-time invite link for an open session: enroll now.

    if session.status == 'closed':
        instances = (
            ToolInstance.objects
            .filter(session=session)
            .select_related('user')
            .order_by('submitted_at')
        )
        return render(request, 'tools/session_closed.html', {
            'session': session,
            'tool_meta': tool_meta,
            'instances': instances,
            'is_host': is_host,
        })

    with transaction.atomic():
        session = ToolSession.objects.select_for_update().get(pk=session.pk)
        if session.status != 'open':
            raise Http404
        instance = ToolInstance.objects.filter(session=session, user=request.user).first()
        if instance is None:
            if _throttled(request, 'participant-join', session.id, limits=(30, 10, 120), window=300):
                return HttpResponse('Too many join attempts.', status=429)
            if ToolInstance.objects.filter(session=session).count() >= MAX_SESSION_PARTICIPANTS:
                return HttpResponse('This session has reached its participant limit.', status=409)
            instance = ToolInstance.objects.create(
                session=session, user=request.user, tool_slug=session.tool_slug,
                tool_version=session.tool_version, status='draft',
            )

    form_class = get_tool_form_class(session.tool_slug)
    form = None
    if form_class is not None:
        if request.method == 'POST':
            form = form_class(request.POST)
            if form.is_valid():
                try:
                    with canvas_write_lock(
                        form.cleaned_data, session.tool_slug, request.user.id,
                    ), transaction.atomic():
                        instance.payload_input = extract_canvas_from_payload(
                            form.cleaned_data, session.tool_slug, request.user.id,
                            existing_canvas=(instance.payload_input or {}).get('canvas_data', ''),
                        )
                        instance.save()
                    messages.success(request, 'Your response was saved.')
                    return redirect('tools:session_detail', session_id=session.id)
                except Exception:
                    messages.error(
                        request,
                        'Unable to save your response — please try again.',
                    )
        else:
            form = form_class(initial=instance.payload_input or {})

    participants = (
        ToolInstance.objects
        .filter(session=session)
        .select_related('user')
        .order_by('created_at')
    )
    # The invite link carries the session's guest_token as ?t=... so a brand
    # new authenticated participant can be enrolled the first time they visit
    # (see session_detail). Knowing the bare session UUID is not sufficient.
    share_url = (
        request.build_absolute_uri(
            reverse('tools:session_detail', args=[session.id])
        ).replace('http://', 'https://', 1)
        + f'?t={session.guest_token}'
    )
    guest_join_url = request.build_absolute_uri(
        reverse('tools:guest_join', args=[session.id, session.guest_token])
    ).replace('http://', 'https://', 1)
    # timer_started_at and timer_paused_at are serialised as ISO strings for
    # the JavaScript timer widget, which computes elapsed time client-side
    # using these as reference points rather than relying on its own clock.
    timer_started_at = (
        session.timer_started_at.isoformat()
        if session.timer_started_at else None
    )
    timer_paused_at = (
        session.timer_paused_at.isoformat()
        if session.timer_paused_at else None
    )

    threshold = session.pause_reminder_threshold_sec
    # JS literal for the timer widget: null disables the reminder, integer enables it.
    pause_reminder_threshold_js = 'null' if threshold is None else threshold

    initial_responder_names = [
        p.user.email if p.user_id else (p.guest_name or 'Guest')
        for p in participants
        if p.payload_input
    ]

    return render(request, 'tools/session_open.html', {
        'session': session,
        'tool_meta': tool_meta,
        'instance': instance,
        'form': form,
        'is_host': is_host,
        'participants': participants,
        'share_url': share_url,
        'guest_join_url': guest_join_url,
        'timer_started_at': timer_started_at,
        'timer_paused_at': timer_paused_at,
        'pause_reminder_threshold_sec': threshold,
        'pause_reminder_threshold_js': pause_reminder_threshold_js,
        'initial_responder_names': initial_responder_names,
        'inclusive_pacing': session.inclusive_pacing,
        'inclusive_pacing_multiplier': session.inclusive_pacing_multiplier,
    })


@login_required
@require_POST
def session_close(request, session_id):
    """Host closes the session: lock everyone's contribution and run the tool.

    If any participant submitted a multimedia attachment the facilitator is
    routed to the Synthesis Workspace (``synthesis_review``) so inline
    transcriptions can be added before the export is generated.  Sessions
    with no attachments go directly to the combined results page as before.
    """
    session = get_object_or_404(ToolSession, id=session_id, host=request.user)
    if _throttled(request, 'session-close-export', session_id, limits=(20, 10, 10), window=300):
        return HttpResponse('Too many requests. Please try again later.', status=429)
    if session.status == 'closed':
        return redirect('tools:session_detail', session_id=session.id)

    with transaction.atomic():
        session = ToolSession.objects.select_for_update().get(
            id=session_id, host=request.user,
        )
        if session.status == 'closed':
            return redirect('tools:session_detail', session_id=session.id)
        session.status = 'closed'
        session.closed_at = timezone.now()
        session.pairing_code = ''
        session.save()

        for instance in ToolInstance.objects.filter(session=session, status='draft'):
            # Errors are captured per-instance so that a broken tool definition
            # for one participant does not abort the close and leave all other
            # contributions un-archived.
            try:
                tool = get_tool_instance(session.tool_slug, instance.payload_input)
                instance.payload_output = tool.execute() if tool else {}
            except ValidationError as e:
                instance.payload_output = {
                    'error': e.message_dict if hasattr(e, 'message_dict') else e.messages
                }
            except Exception as e:
                instance.payload_output = {'error': str(e)}
            instance.status = 'archived'
            instance.submitted_at = timezone.now()
            instance.save()

    # After all instances are committed: check whether any participant uploaded
    # a multimedia attachment.  If so, route to the Synthesis Workspace for
    # transcription before the Markdown export is generated.
    any_attachments = ToolInstance.objects.filter(
        session=session,
    ).exclude(attachments=[]).exists()

    if any_attachments:
        messages.info(
            request,
            'Session closed. Add transcriptions for any multimedia contributions '
            'below, then generate the combined export.',
        )
        return redirect('tools:synthesis_review', session_id=session.id)

    try:
        run_session_export_pipeline(session)
    except Exception:
        messages.warning(
            request,
            'Session closed, but the combined export could not be generated.',
        )
        return redirect('tools:session_detail', session_id=session.id)

    messages.success(request, 'Session closed. Combined results are now visible.')
    return redirect('tools:session_detail', session_id=session.id)


@login_required
@require_POST
def session_delete(request, session_id):
    """The retention owner permanently deletes a session and its instances.

    A host cannot delete work retained by a different account. All related records
    and any generated export files cascade-delete via the database constraint.
    After deletion the user is returned to the tool's Knowledge Bank page.
    """
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=request.user.pk)
        session = get_object_or_404(
            ToolSession.objects.select_for_update().filter(
                session_management_q(request.user)
            ),
            id=session_id,
        )
        tool_slug = session.tool_slug
        session.delete()
    messages.success(request, 'Session deleted.')
    return redirect('archive:knowledge_bank_tool', tool_slug=tool_slug)


@login_required
def synthesis_review(request, session_id):
    """Facilitator Synthesis Workspace.

    Shown after ``session_close`` when at least one participant submitted a
    multimedia attachment (audio clip or symbol-board image).  The facilitator
    — or a support worker sitting alongside a non-verbal participant — can type
    an inline text transcription for each attachment before the combined
    Markdown export is generated.  Transcriptions are stored directly in the
    ``attachments`` JSON array on each ``ToolInstance`` so they are woven into
    the export as first-class data.

    GET  — render the staging review form.
    POST — save transcriptions into each ``attachments[n]['transcription']``,
           trigger ``run_session_export_pipeline``, then redirect to the
           combined results page.
    """
    session = get_object_or_404(ToolSession, id=session_id, host=request.user, status='closed')

    instances = (
        ToolInstance.objects
        .filter(session=session)
        .select_related('user')
        .order_by('submitted_at', 'created_at')
    )

    if request.method == 'POST':
        if _payload_too_large(request):
            return HttpResponse('Request payload too large.', status=413)
        if _throttled(request, 'session-synthesis-export', session_id, limits=(20, 10, 10), window=300):
            return HttpResponse('Too many requests. Please try again later.', status=429)
        for instance in instances:
            if not instance.attachments:
                continue
            changed = False
            for idx, att in enumerate(instance.attachments):
                key = f'transcript_{instance.id}_{idx}'
                new_val = request.POST.get(key, '').strip()
                if att.get('transcription', '') != new_val:
                    att['transcription'] = new_val
                    changed = True
            if changed:
                instance.save(update_fields=['attachments', 'updated_at'])

        try:
            run_session_export_pipeline(session)
            messages.success(request, 'Export generated successfully.')
        except Exception:
            messages.warning(
                request,
                'Transcriptions saved, but the export could not be generated.',
            )

        return redirect('tools:session_detail', session_id=session.id)

    review_instances = []
    for inst in instances:
        display = inst.user.email if inst.user_id else (inst.guest_name or 'Guest')
        review_instances.append({
            'instance': inst,
            'display': display,
            'is_host': inst.user_id == session.host_id,
        })

    return render(request, 'tools/synthesis_review.html', {
        'session': session,
        'tool_meta': get_tool_metadata(session.tool_slug),
        'review_instances': review_instances,
    })


@require_POST
def session_mark_composing(request, session_id):
    """AAC composition heartbeat endpoint.

    Called every ~8 seconds by session_composing.js when a participant has
    activated the "I'm Composing" flag.  Stamps ``composing_heartbeat_at``
    with the current time; session_status treats the flag as active while
    the timestamp is within the last 15 seconds.

    Accessible to authenticated participants and guests, matching the access
    pattern of session_buffer_save.
    """
    session = get_object_or_404(ToolSession, id=session_id)
    if _throttled(request, 'session-composing', session_id, limits=(180, 120, 1200)):
        return _too_many_json()

    if request.user.is_authenticated:
        instance = get_object_or_404(ToolInstance, session=session, user=request.user)
    else:
        guest_instance_id = request.session.get(f'guest_instance_{session_id}')
        if not guest_instance_id:
            return JsonResponse({'error': 'forbidden'}, status=403)
        instance = get_object_or_404(ToolInstance, id=guest_instance_id, session=session)

    # Use QuerySet.update() to avoid triggering auto_now on updated_at.
    ToolInstance.objects.filter(pk=instance.pk).update(
        composing_heartbeat_at=timezone.now()
    )
    return JsonResponse({'status': 'ok'})


@require_POST
def session_buffer_save(request, session_id):
    """Background buffer-capture endpoint for live session participants.

    Called by session_autosave.js on a fixed interval and again the moment
    the poll detects the session has been closed.  Persists the current form
    state to ``payload_input`` so the host's close transaction uses the latest
    text even if the participant had not yet clicked "Save my response".

    Accessible to authenticated users and to unauthenticated guests who hold
    a valid ``guest_instance_id`` in their browser session.
    """
    if _payload_too_large(request):
        return JsonResponse({'error': 'request payload too large'}, status=413)
    session = get_object_or_404(ToolSession, id=session_id)
    if _throttled(request, 'session-buffer', session_id, limits=(120, 90, 900)):
        return _too_many_json()

    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'invalid request body'}, status=400)

    form_data = data.get('form_data') or {}
    if not isinstance(form_data, dict):
        return JsonResponse({'error': 'form_data must be an object'}, status=400)

    if request.user.is_authenticated:
        instance = get_object_or_404(ToolInstance, session=session, user=request.user)
    else:
        guest_instance_id = request.session.get(f'guest_instance_{session_id}')
        if not guest_instance_id:
            return JsonResponse({'error': 'forbidden'}, status=403)
        instance = get_object_or_404(ToolInstance, id=guest_instance_id, session=session)

    # Merge new values into existing payload so keys not present in this
    # partial save (e.g. canvas_data) are preserved from the last full save.
    current = dict(instance.payload_input or {})
    if 'canvas_data' in form_data:
        identifier = request.user.id if request.user.is_authenticated else f'guest-{instance.pk}'
        try:
            with canvas_write_lock(
                form_data, session.tool_slug, identifier,
            ), transaction.atomic():
                form_data = extract_canvas_from_payload(
                    form_data,
                    session.tool_slug,
                    identifier,
                    existing_canvas=current.get('canvas_data', ''),
                )
                current.update(form_data)
                instance.payload_input = current
                instance.save(update_fields=['payload_input', 'updated_at'])
        except ValidationError:
            return JsonResponse({'error': 'invalid canvas data'}, status=400)
    else:
        current.update(form_data)
        instance.payload_input = current
        instance.save(update_fields=['payload_input', 'updated_at'])

    return JsonResponse({
        'status': 'saved',
        'last_saved': instance.updated_at.strftime('%H:%M:%S'),
    })


def session_status(request, session_id):
    """Lightweight JSON endpoint for participant-list / status polling.

    Accessible to authenticated participants and to unauthenticated guests who
    hold a valid guest_instance_id in their browser session for this session.
    """
    session = get_object_or_404(ToolSession, id=session_id)
    if _throttled(request, 'session-status', session_id, limits=(300, 180, 3000)):
        return _too_many_json()

    if request.user.is_authenticated:
        is_participant = (
            session.host_id == request.user.id
            or ToolInstance.objects.filter(session=session, user=request.user).exists()
        )
        if not is_participant:
            return JsonResponse({'error': 'forbidden'}, status=403)
    else:
        guest_instance_id = request.session.get(f'guest_instance_{session_id}')
        if not guest_instance_id:
            return redirect_to_login(request.get_full_path())
        if not ToolInstance.objects.filter(id=guest_instance_id, session=session).exists():
            return JsonResponse({'error': 'forbidden'}, status=403)

    response_now = timezone.now().replace(microsecond=0)
    participants = (
        ToolInstance.objects
        .filter(session=session)
        .select_related('user')
        .order_by('created_at')
    )
    timer_started_at = (
        session.timer_started_at.isoformat()
        if session.timer_started_at else None
    )
    tool_meta = get_tool_metadata(session.tool_slug) or {}
    payload = {
        'status': session.status,
        'server_now': response_now.isoformat(),
        'timer_started_at': timer_started_at,
        # timer_phases and timer_seconds are returned so that participants who
        # join mid-session (or poll after a page reload) can initialise their
        # timer widget without needing a full page reload.
        'timer_phases': tool_meta.get('phases') or None,
        'timer_seconds': tool_meta.get('timer_seconds') or 0,
        # Inclusive Pacing — broadcast to all participants on every poll so
        # they react immediately when the host enables or adjusts it.
        'inclusive_pacing': session.inclusive_pacing,
        'inclusive_pacing_multiplier': session.inclusive_pacing_multiplier,
        # Verbal Breakout — host has moved the group to verbal discussion;
        # AAC-composing participants are reassured their window is still open.
        'verbal_breakout': session.verbal_breakout_active,
        'participants': [
            {
                'display_name': p.user.email if p.user_id else (p.guest_name or 'Guest'),
                'is_host': p.user_id is not None and p.user_id == session.host_id,
                'has_response': bool(p.payload_input),
                # True while the participant's AAC composing heartbeat is fresh
                # (within the last 15 seconds).
                'is_composing': bool(
                    p.composing_heartbeat_at and
                    (response_now - p.composing_heartbeat_at).total_seconds() < 15
                ),
            }
            for p in participants
        ],
    }
    # Include every representation field in the validator. ``server_now`` is
    # stable for one second so coalesced/duplicate requests can receive a valid
    # 304 without claiming that a changed clock value is unchanged.
    etag_source = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    etag = f'"{hashlib.sha256(etag_source.encode()).hexdigest()}"'
    if request.headers.get('If-None-Match') == etag:
        response = HttpResponse(status=304)
    else:
        response = JsonResponse(payload)
    response['ETag'] = etag
    response['Cache-Control'] = 'private, no-cache'
    return response


# Timer control — host only, POST required.
# Host-only enforcement is done via get_object_or_404(host=request.user)
# so non-hosts receive a 404 rather than a 403.

@login_required
@require_POST
def timer_start(request, session_id):
    """Host records the timer start time on the server so all clients can sync."""
    session = get_object_or_404(ToolSession, id=session_id, host=request.user)
    if session.status != 'open':
        return JsonResponse({'error': 'session not open'}, status=400)
    session.timer_started_at = timezone.now()
    session.save(update_fields=['timer_started_at'])
    return JsonResponse({'timer_started_at': session.timer_started_at.isoformat()})


@login_required
@require_POST
def timer_reset(request, session_id):
    """Host clears the server-side timer start time so the timer can restart."""
    session = get_object_or_404(ToolSession, id=session_id, host=request.user)
    if session.status != 'open':
        return JsonResponse({'error': 'session not open'}, status=400)
    session.timer_started_at = None
    session.save(update_fields=['timer_started_at'])
    return JsonResponse({'timer_started_at': None})


@login_required
@require_POST
def session_set_pause_reminder(request, session_id):
    """Host updates the pause-reminder threshold for the session.

    This persists a session-level setting (separate from timer start/reset,
    which manage transient state).
    """
    session = get_object_or_404(ToolSession, id=session_id, host=request.user)
    if session.status != 'open':
        return JsonResponse({'error': 'session not open'}, status=400)
    raw = request.POST.get('pause_reminder_threshold_sec', '')
    if raw == '' or raw is None:
        session.pause_reminder_threshold_sec = None
    else:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return JsonResponse({'error': 'invalid value'}, status=400)
        if value < 0:
            return JsonResponse({'error': 'value must be >= 0'}, status=400)
        # Zero is treated the same as None (disables the reminder) because a
        # 0-second threshold is not a meaningful configuration.
        session.pause_reminder_threshold_sec = value if value > 0 else None
    session.save(update_fields=['pause_reminder_threshold_sec'])
    return JsonResponse({
        'pause_reminder_threshold_sec': session.pause_reminder_threshold_sec
    })


@login_required
@require_POST
def session_set_inclusive_pacing(request, session_id):
    """Host enables or adjusts the Inclusive Pacing multiplier for this session.

    When inclusive_pacing is true, each non-host participant's status-poll
    response includes the flag and multiplier so their timer.js can show the
    extended personal countdown panel without requiring a page reload.
    """
    session = get_object_or_404(ToolSession, id=session_id, host=request.user)
    if session.status != 'open':
        return JsonResponse({'error': 'session not open'}, status=400)
    enabled = request.POST.get('inclusive_pacing', 'false') == 'true'
    try:
        multiplier = int(request.POST.get('inclusive_pacing_multiplier', 3))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'invalid multiplier'}, status=400)
    if multiplier not in (3, 5):
        return JsonResponse({'error': 'multiplier must be 3 or 5'}, status=400)
    session.inclusive_pacing = enabled
    session.inclusive_pacing_multiplier = multiplier
    session.save(update_fields=['inclusive_pacing', 'inclusive_pacing_multiplier'])
    return JsonResponse({
        'inclusive_pacing': session.inclusive_pacing,
        'inclusive_pacing_multiplier': session.inclusive_pacing_multiplier,
    })


@login_required
@require_POST
def session_set_verbal_breakout(request, session_id):
    """Host toggles verbal-breakout mode for an open session.

    When active, participants who have not flagged themselves as AAC-composing
    see a banner prompting them to join a verbal discussion; those who did flag
    themselves are reassured their digital submission window is still open.

    The state is broadcast on every session_status poll so all participants
    react within ≤ 4 seconds without requiring a page reload.
    """
    session = get_object_or_404(ToolSession, id=session_id, host=request.user)
    if session.status != 'open':
        return JsonResponse({'error': 'session not open'}, status=400)
    active = request.POST.get('active') == 'true'
    session.verbal_breakout_active = active
    session.save(update_fields=['verbal_breakout_active'])
    return JsonResponse({'verbal_breakout_active': session.verbal_breakout_active})


# --- Guest participant flow --------------------------------------------------
# These views allow unauthenticated participants to join a session via a QR
# code URL that embeds the session's guest_token.  The guest is identified for
# the duration of their visit by a key stored in the Django browser session.

def guest_join(request, session_id, guest_token):
    """Show a name-entry form so unauthenticated users can join as guests.

    On POST a ToolInstance is created with user=None and the supplied name, and
    the instance ID is stored in the browser session so subsequent requests can
    identify the guest without requiring authentication.
    """
    session = get_object_or_404(ToolSession, id=session_id, guest_token=guest_token)

    if session.status == 'closed':
        return redirect('tools:guest_respond', session_id=session_id, guest_token=guest_token)

    # If this browser already joined, skip straight to the form.
    existing_id = request.session.get(f'guest_instance_{session_id}')
    if existing_id and ToolInstance.objects.filter(id=existing_id, session=session).exists():
        return redirect('tools:guest_respond', session_id=session_id, guest_token=guest_token)

    error = None
    if request.method == 'POST':
        if _payload_too_large(request):
            return HttpResponse('Request payload too large.', status=413)
        if _throttled(request, 'guest-join', session_id, limits=(20, 20, 150), window=300):
            return HttpResponse('Too many join attempts.', status=429)
        name = request.POST.get('guest_name', '').strip()
        if not name:
            error = 'Please enter a name so the host can see who you are.'
        elif len(name) > 100:
            error = 'Name must be 100 characters or fewer.'
        else:
            tool_class = get_tool_instance(session.tool_slug)
            with transaction.atomic():
                session = ToolSession.objects.select_for_update().get(pk=session.pk)
                if session.status != 'open':
                    return redirect(
                        'tools:guest_respond',
                        session_id=session_id,
                        guest_token=guest_token,
                    )
                if ToolInstance.objects.filter(session=session).count() >= MAX_SESSION_PARTICIPANTS:
                    return HttpResponse(
                        'This session has reached its participant limit.', status=409,
                    )
                instance = ToolInstance.objects.create(
                    user=None, guest_name=name, session=session,
                    tool_slug=session.tool_slug,
                    tool_version=getattr(tool_class, 'version', session.tool_version),
                    status='draft',
                )
            request.session[f'guest_instance_{session_id}'] = instance.id
            return redirect('tools:guest_respond', session_id=session_id, guest_token=guest_token)

    tool_meta = get_tool_metadata(session.tool_slug)
    return render(request, 'tools/guest_join.html', {
        'session': session,
        'tool_meta': tool_meta,
        'error': error,
    })


def guest_respond(request, session_id, guest_token):
    """Show and save the tool form for a guest participant.

    The guest is identified via the browser session key set by guest_join.
    If the session has been closed this view renders the combined results.
    """
    session = get_object_or_404(ToolSession, id=session_id, guest_token=guest_token)
    tool_meta = get_tool_metadata(session.tool_slug)

    # Re-identify the guest via their browser session.
    instance_id = request.session.get(f'guest_instance_{session_id}')
    if not instance_id:
        return redirect('tools:guest_join', session_id=session_id, guest_token=guest_token)
    instance = get_object_or_404(ToolInstance, id=instance_id, session=session)

    if session.status == 'closed':
        instances = (
            ToolInstance.objects
            .filter(session=session)
            .select_related('user')
            .order_by('submitted_at')
        )
        return render(request, 'tools/guest_session_closed.html', {
            'session': session,
            'tool_meta': tool_meta,
            'instances': instances,
            'guest_instance': instance,
        })

    form_class = get_tool_form_class(session.tool_slug)
    form = None
    if form_class is not None:
        if request.method == 'POST':
            if _payload_too_large(request):
                return HttpResponse('Request payload too large.', status=413)
            if _throttled(request, 'guest-respond', session_id, limits=(30, 30, 300), window=300):
                return HttpResponse('Too many requests. Please try again later.', status=429)
            form = form_class(request.POST)
            if form.is_valid():
                try:
                    # Never use a guest's name in a drawing filename.  The
                    # instance primary key is stable for this browser/session
                    # participant and contains no personally identifying data.
                    guest_identifier = f'guest-{instance.pk}'
                    with canvas_write_lock(
                        form.cleaned_data, session.tool_slug, guest_identifier,
                    ), transaction.atomic():
                        instance.payload_input = extract_canvas_from_payload(
                            form.cleaned_data, session.tool_slug, guest_identifier,
                            existing_canvas=(instance.payload_input or {}).get('canvas_data', ''),
                        )
                        instance.save()
                    messages.success(request, 'Your response was saved.')
                    return redirect('tools:guest_respond', session_id=session_id, guest_token=guest_token)
                except Exception:
                    messages.error(
                        request,
                        'Unable to save your response — please try again.',
                    )
        else:
            form = form_class(initial=instance.payload_input or {})

    timer_started_at = (
        session.timer_started_at.isoformat()
        if session.timer_started_at else None
    )
    timer_paused_at = (
        session.timer_paused_at.isoformat()
        if session.timer_paused_at else None
    )
    threshold = session.pause_reminder_threshold_sec
    pause_reminder_threshold_js = 'null' if threshold is None else threshold

    return render(request, 'tools/guest_respond.html', {
        'session': session,
        'tool_meta': tool_meta,
        'instance': instance,
        'form': form,
        'guest_token': guest_token,
        'timer_started_at': timer_started_at,
        'timer_paused_at': timer_paused_at,
        'pause_reminder_threshold_sec': threshold,
        'pause_reminder_threshold_js': pause_reminder_threshold_js,
        'inclusive_pacing': session.inclusive_pacing,
        'inclusive_pacing_multiplier': session.inclusive_pacing_multiplier,
    })


def timer_test_page(request):
    """
    Render a bare timer widget for browser-based accessibility testing.
    Only available when DEBUG is True.
    """
    if not settings.DEBUG:
        raise Http404
    from types import SimpleNamespace
    phases = [
        {"label": "Alpha", "seconds": 3},
        {"label": "Beta", "seconds": 3},
        {"label": "Gamma", "seconds": 3},
    ]
    # The SimpleNamespace must carry phases, timer_seconds, and title to match
    # what the _timer.html template expects from the tool_meta object.
    tool_meta = SimpleNamespace(phases=phases, timer_seconds=9, title="Test Timer")
    return render(request, "tools/timer_test_page.html", {"tool_meta": tool_meta, "timer_session_id": None})


# --- Companion pairing -------------------------------------------------------

def pairing_entry(request):
    """Render the 3-digit code entry form at /join/.

    On POST, redirect to /join/<code>/ which performs the actual lookup.
    This keeps the lookup logic in one place and makes direct-URL entry
    (e.g. typing /join/742 straight into the address bar) also work.
    """
    error = None
    if request.method == 'POST':
        code = request.POST.get('code', '').strip().zfill(3)
        if not code.isdigit() or len(code) != 3:
            error = 'Please enter exactly 3 digits.'
        else:
            return redirect('pairing_join', code=code)
    return render(request, 'tools/pairing_entry.html', {'error': error})


# The pairing code space is only 1000 values (000-999), so without a limit an
# attacker could enumerate every code in seconds. These limits throttle guess
# rate per client and lock out abusive clients for a cooldown period.
PAIRING_MAX_ATTEMPTS = 8
PAIRING_WINDOW_SECONDS = 5 * 60
PAIRING_LOCKOUT_SECONDS = 15 * 60


def _pairing_rate_limited(request):
    """Throttle pairing-code guesses per client IP using the cache backend.

    Once a client exceeds ``PAIRING_MAX_ATTEMPTS`` requests within
    ``PAIRING_WINDOW_SECONDS`` it is locked out for ``PAIRING_LOCKOUT_SECONDS``,
    during which no further guesses are even evaluated against the database.
    """
    ip = client_ip(request) or 'unknown'
    lockout_key = f'pairing_lockout:{ip}'
    if cache.get(lockout_key):
        return True

    attempts_key = f'pairing_attempts:{ip}'
    attempts = cache.get(attempts_key, 0) + 1
    cache.set(attempts_key, attempts, PAIRING_WINDOW_SECONDS)
    if attempts > PAIRING_MAX_ATTEMPTS:
        cache.set(lockout_key, True, PAIRING_LOCKOUT_SECONDS)
        return True
    return False


def pairing_join(request, code):
    """Look up an open session by its 3-digit pairing code and redirect.

    Redirects to the guest_join page so the companion device skips straight
    to the nickname screen without the participant needing to type a UUID URL.
    Returns 404 with a friendly explanation if the code is unknown or stale,
    and 429 once the client has exceeded the guess-rate budget.
    """
    code = code.strip().zfill(3)
    if not code.isdigit() or len(code) != 3:
        return render(
            request,
            'tools/pairing_not_found.html',
            {'code': code},
            status=404,
        )

    if _pairing_rate_limited(request):
        return render(
            request,
            'tools/pairing_not_found.html',
            {'code': code, 'rate_limited': True},
            status=429,
        )

    session = ToolSession.objects.filter(
        status='open', pairing_code=code
    ).first()
    if not session:
        return render(
            request,
            'tools/pairing_not_found.html',
            {'code': code},
            status=404,
        )
    return redirect(
        'tools:guest_join',
        session_id=session.id,
        guest_token=session.guest_token,
    )


# ── Multimedia Input Bridge ──────────────────────────────────────────────────

@require_POST
def session_attachment_upload(request, session_id):
    """Upload a multimedia attachment (audio or image) for a session participant.

    Accepts ``multipart/form-data`` with a single ``file`` field.  The file is
    saved to local storage in a self-hosted instance, or to Cloudinary when that
    storage backend is configured. Its URL and owning storage key are recorded
    together so account/session deletion can remove the asset safely.

    Accessible to authenticated users and to unauthenticated guests who hold a
    valid ``guest_instance_id`` in their browser session (same auth pattern as
    ``session_buffer_save``).

    Supported types:
        image/*  — PNG, JPEG, WebP, GIF — max 10 MB
        audio/*  — WebM, OGG, MP3, MP4 audio — max 25 MB
    """
    raw_upload_length = request.META.get('CONTENT_LENGTH')
    try:
        upload_length = int(raw_upload_length)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'content length required'}, status=411)
    if upload_length < 0:
        return JsonResponse({'error': 'invalid content length'}, status=400)
    if upload_length > (25 * 1024 * 1024 + 1024 * 1024):
        return JsonResponse({'error': 'request payload too large'}, status=413)
    session = get_object_or_404(ToolSession, id=session_id, status='open')
    if _throttled(request, 'attachment-upload', session_id, limits=(20, 12, 120), window=300):
        return _too_many_json()

    if request.user.is_authenticated:
        instance = get_object_or_404(ToolInstance, session=session, user=request.user)
    else:
        guest_instance_id = request.session.get(f'guest_instance_{session_id}')
        if not guest_instance_id:
            return JsonResponse({'error': 'forbidden'}, status=403)
        instance = get_object_or_404(ToolInstance, id=guest_instance_id, session=session)

    uploaded_file = request.FILES.get('file')
    if not uploaded_file:
        return JsonResponse({'error': 'no file provided'}, status=400)

    content_type = (uploaded_file.content_type or '').split(';')[0].strip()
    if content_type.startswith('image/'):
        attach_type   = 'image'
        resource_type = 'image'
        max_bytes     = 10 * 1024 * 1024
    elif content_type.startswith('audio/') or content_type.startswith('video/'):
        attach_type   = 'audio'
        resource_type = 'video'
        max_bytes     = 25 * 1024 * 1024
    else:
        return JsonResponse({'error': 'unsupported file type'}, status=400)

    if uploaded_file.size > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        return JsonResponse({'error': f'file too large (max {limit_mb} MB)'}, status=400)

    # Lock before sending bytes to storage. This serialises concurrent uploads
    # for one participant so count and aggregate-byte checks cannot be raced.
    with transaction.atomic():
        locked_instance = ToolInstance.objects.select_for_update().get(pk=instance.pk)
        attachments = list(locked_instance.attachments or [])
        if len(attachments) >= MAX_ATTACHMENTS_PER_PARTICIPANT:
            return JsonResponse({'error': 'attachment limit reached'}, status=409)
        used_bytes = sum(
            int(item.get('size', 0)) for item in attachments
            if isinstance(item, dict)
        )
        if used_bytes + uploaded_file.size > MAX_ATTACHMENT_BYTES_PER_PARTICIPANT:
            return JsonResponse({'error': 'attachment storage limit reached'}, status=409)

        from django.utils.timezone import now as tz_now
        from django.core.files.storage import default_storage
        from tools.utils import _uses_cloudinary_storage

        timestamp = tz_now().strftime('%Y%m%d%H%M%S')
        public_id = (
            f'kwacart/attachments/{session_id}/'
            f'{instance.id}_{attach_type}_{timestamp}'
        )

        uploaded_entry = None
        try:
            if _uses_cloudinary_storage():
                import cloudinary.uploader
                result = cloudinary.uploader.upload(
                    uploaded_file.read(),
                    resource_type=resource_type,
                    public_id=public_id,
                    overwrite=False,
                )
                storage_name = None
            else:
                # Do not use a submitted filename as a filesystem path.
                import mimetypes
                suffix = mimetypes.guess_extension(content_type) or '.bin'
                public_id = f'kwacart/attachments/{session_id}/{uuid.uuid4().hex}{suffix}'
                storage_name = default_storage.save(public_id, uploaded_file)
                public_id = storage_name
                result = {
                    'secure_url': default_storage.url(storage_name),
                    'public_id': storage_name,
                }
        except Exception:
            return JsonResponse({'error': 'upload to storage failed'}, status=500)

        secure_url = result.get('secure_url', '')
        returned_public_id = result.get('public_id', public_id)
        entry = {
            'type': attach_type,
            'url': secure_url,
            'public_id': returned_public_id,
            'name': uploaded_file.name or f'{attach_type}_{timestamp}',
            'size': uploaded_file.size,
        }
        if storage_name:
            entry['storage_name'] = storage_name
        uploaded_entry = entry
        if returned_public_id != public_id or not secure_url:
            delete_attachment_asset(entry, session_id)
            return JsonResponse({'error': 'invalid storage response'}, status=500)
        try:
            attachments.append(entry)
            locked_instance.attachments = attachments
            locked_instance.save(update_fields=['attachments', 'updated_at'])
        except Exception:
            # The provider upload succeeded but the database write did not.
            # Destroying here prevents an asset with no owning attachment row.
            delete_attachment_asset(uploaded_entry, session_id)
            raise

    return JsonResponse(entry)


@require_POST
def session_attachment_remove(request, session_id):
    """Remove a previously uploaded attachment from the participant's instance.

    Accepts ``application/x-www-form-urlencoded`` with a ``public_id`` field
    matching an entry in ``ToolInstance.attachments``.  The Cloudinary asset is
    not deleted (cleanup can be handled server-side later); only the database
    record is updated.
    """
    session = get_object_or_404(ToolSession, id=session_id, status='open')
    if _throttled(request, 'attachment-remove', session_id, limits=(40, 30, 200), window=300):
        return _too_many_json()

    if request.user.is_authenticated:
        instance = get_object_or_404(ToolInstance, session=session, user=request.user)
    else:
        guest_instance_id = request.session.get(f'guest_instance_{session_id}')
        if not guest_instance_id:
            return JsonResponse({'error': 'forbidden'}, status=403)
        instance = get_object_or_404(ToolInstance, id=guest_instance_id, session=session)

    public_id = request.POST.get('public_id', '').strip()
    if not public_id:
        return JsonResponse({'error': 'public_id required'}, status=400)

    # Lock and persist first. The lifecycle signal destroys the exact matched
    # owned asset only after this transaction commits successfully.
    with transaction.atomic():
        instance = ToolInstance.objects.select_for_update().get(pk=instance.pk)
        attachments = list(instance.attachments or [])
        match_index = next(
            (
                index for index, attachment in enumerate(attachments)
                if isinstance(attachment, dict)
                and attachment.get('public_id') == public_id
            ),
            None,
        )
        if match_index is None:
            return JsonResponse({'error': 'attachment not found'}, status=404)
        attachments.pop(match_index)
        instance.attachments = attachments
        instance.save(update_fields=['attachments', 'updated_at'])
    return JsonResponse({'status': 'removed'})


@login_required
def pathway_finder(request):
    """Authenticated LS Pathway Finder wizard.

    Renders a multi-step recommendation wizard: three fixed context questions
    (time available, group size, modality) followed by a randomised grid of
    33 goal circles.  All recommendation logic runs client-side; this view
    only passes the tool catalog as JSON so the results step can display
    titles and taglines without an extra round-trip.
    """
    tools_data = {
        slug: {
            'title': info['title'],
            'tagline': info.get('tagline', ''),
        }
        for slug, info in TOOL_CATALOG.items()
    }
    return render(request, 'tools/pathway_finder.html', {'tools_data': tools_data})
