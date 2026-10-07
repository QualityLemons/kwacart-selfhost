"""Authentication and account management views for the accounts application.

Provides sign-up, login, logout, profile (read + update), and account deletion
using Django's built-in class-based views extended with project-specific
configuration (email-only sign-up form, authenticated-user redirect on the
login page, and a fixed post-logout URL).
"""
import json
import uuid
from urllib.parse import urlencode

from django.contrib import messages
from django.conf import settings
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST
from django.views.generic.edit import CreateView

from config.rate_limit import is_layered_rate_limited, is_rate_limited

from .billing import handle_webhook_event, reconcile_checkout, sync_subscription
from .forms import CustomUserCreationForm, OrganisationMemberPolicyForm, ProfileEmailForm
from .models import OrganisationDataTransferRequest, OrganisationMemberDataPolicy, User
from .organisation_data_ownership import (
    accept_transfer_request,
    create_transfer_request,
    decline_transfer_request,
    session_access_q,
    solo_records_for_user,
)
from .stripe_client import (
    StripeError,
    create_checkout_session,
    create_portal_session,
    find_price,
    retrieve_checkout_session,
    verify_webhook_signature,
    webhook_secret,
)


def _has_organisation_retained_work(user):
    """Whether deleting this creator would cascade-delete organisation data."""
    from archive.models import ToolInstance, ToolSession

    return (
        ToolInstance.objects.filter(user=user, session__isnull=True)
        .exclude(data_owner__isnull=True)
        .exclude(data_owner=user)
        .exists()
        or ToolSession.objects.filter(host=user)
        .exclude(data_owner__isnull=True)
        .exclude(data_owner=user)
        .exists()
    )

# The login form gives immediate success/failure feedback with no other
# server-side friction, so without a limit an attacker can password-spray
# any number of accounts. These limits throttle POSTs per client IP and lock
# out abusive clients for a cooldown period, independent of which email is
# being tried.
LOGIN_MAX_ATTEMPTS = 8
LOGIN_WINDOW_SECONDS = 5 * 60
LOGIN_LOCKOUT_SECONDS = 15 * 60


def _billing_rate_limited(request, scope, ip_limit, user_limit):
    return is_layered_rate_limited(
        request, scope, ip_limit=ip_limit, user_limit=user_limit,
        session_limit=user_limit, window_seconds=300, lockout_seconds=300,
    )


def _billing_throttled_response():
    response = HttpResponse('Too many billing requests. Please try again later.', status=429)
    response['Retry-After'] = '300'
    return response


class SignUpView(CreateView):
    """Registration form view.

    On successful submission Django creates the user and redirects to the
    login page so the new user can immediately sign in.
    """

    form_class = CustomUserCreationForm
    success_url = reverse_lazy('accounts:login')
    template_name = 'registration/signup.html'

    def dispatch(self, request, *args, **kwargs):
        plan = request.GET.get('plan')
        interval = request.GET.get('interval')
        if settings.BILLING_ENABLED and plan in {'solo', 'organisation'} and interval in {'month', 'year'}:
            request.session['selected_plan'] = plan
            request.session['selected_interval'] = interval
        next_url = request.GET.get('next', '')
        if next_url and url_has_allowed_host_and_scheme(
            url=next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            request.session['signup_next'] = next_url
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        """Preserve a pricing choice through registration and login."""
        plan = self.request.session.pop('selected_plan', '')
        interval = self.request.session.pop('selected_interval', '')
        if settings.BILLING_ENABLED and plan in {'solo', 'organisation'} and interval in {'month', 'year'}:
            checkout = reverse_lazy('accounts:checkout')
            next_url = f'{checkout}?plan={plan}&interval={interval}'
            return f'{reverse_lazy("accounts:login")}?{urlencode({"next": next_url})}'
        next_url = self.request.session.pop('signup_next', '')
        if next_url:
            return f'{reverse_lazy("accounts:login")}?{urlencode({"next": next_url})}'
        return super().get_success_url()

    def form_valid(self, form):
        response = super().form_valid(form)
        domain = self.object.email_domain
        if settings.BILLING_ENABLED and domain:
            owner = User.objects.filter(
                plan='organisation',
                subscription_status__in={'active', 'trialing'},
                organisation_owner__isnull=True,
                stripe_subscription_id__isnull=False,
                email__iendswith=f'@{domain}',
            ).exclude(pk=self.object.pk).first()
            if owner:
                self.object.organisation_owner = owner
                self.object.save(update_fields=['organisation_owner'])
        return response


class UserLoginView(LoginView):
    """Email + password login form.

    ``redirect_authenticated_user`` sends already-logged-in visitors straight
    to their post-login destination instead of showing the form again.
    """

    template_name = 'registration/login.html'
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        """Throttle login POSTs per client IP before touching auth at all.

        Once the per-IP attempt budget is exceeded within the window, further
        POSTs are rejected with 429 without evaluating credentials against
        the database, blunting both single-account brute force and
        multi-account password spraying from one source.
        """
        if is_rate_limited(
            request, 'login', LOGIN_MAX_ATTEMPTS,
            LOGIN_WINDOW_SECONDS, LOGIN_LOCKOUT_SECONDS,
        ):
            messages.error(
                request,
                'Too many login attempts. Please wait a few minutes and try again.',
            )
            form = self.get_form_class()(request=request)
            return self.render_to_response(
                self.get_context_data(form=form), status=429
            )
        return super().post(request, *args, **kwargs)


class UserLogoutView(LogoutView):
    """Log the user out and send them to the login page.

    Overrides Django's default ``next_page`` so users always land on the
    login page after logging out.
    """

    next_page = reverse_lazy('accounts:login')


@login_required
@require_http_methods(['GET', 'POST'])
def checkout_start(request):
    """Create a hosted subscription Checkout session for an allow-listed plan."""
    if not settings.BILLING_ENABLED:
        return HttpResponse('Billing is not available in the self-hosted edition.', status=404)
    if _billing_rate_limited(request, 'billing-checkout-start', 20, 8):
        return _billing_throttled_response()
    plan = request.GET.get('plan') or request.POST.get('plan')
    interval = request.GET.get('interval') or request.POST.get('interval')
    if plan not in {'solo', 'organisation'} or interval not in {'month', 'year'}:
        messages.error(request, 'Choose a valid plan and billing interval.')
        return redirect('pricing')
    user = request.user
    if user.has_paid_access:
        messages.info(request, 'Your account already has an active subscription.')
        return redirect('accounts:profile')
    try:
        price_id = find_price(plan, interval)
        if not price_id:
            raise StripeError('This plan is not available for checkout yet.')
        session = create_checkout_session(
            user,
            price_id,
            request.build_absolute_uri(
                reverse_lazy('accounts:checkout_success')
            ) + '?session_id={CHECKOUT_SESSION_ID}',
            request.build_absolute_uri(
                reverse_lazy('accounts:checkout_cancel')
            ) + f'?plan={plan}&interval={interval}',
            plan,
            interval,
            request.session.setdefault(
                f'checkout_key_{plan}_{interval}',
                f'kwacart-{user.pk}-{plan}-{interval}-{uuid.uuid4()}',
            ),
        )
    except StripeError as exc:
        messages.error(request, str(exc))
        return redirect('/pricing/?billing=unavailable')
    return redirect(session['url'])


@login_required
def checkout_success(request):
    """Verify a completed session belongs to this user before granting access."""
    if not settings.BILLING_ENABLED:
        return HttpResponse('Billing is not available in the self-hosted edition.', status=404)
    if _billing_rate_limited(request, 'billing-checkout-success', 30, 12):
        return _billing_throttled_response()
    session_id = request.GET.get('session_id')
    if not session_id:
        messages.error(request, 'The checkout confirmation link is incomplete.')
        return redirect('accounts:profile')
    try:
        session = retrieve_checkout_session(session_id)
        if session.get('status') != 'complete' or session.get('payment_status') != 'paid':
            return render(request, 'accounts/checkout_status.html', {
                'status': 'pending',
                'title': 'Payment still processing',
                'message': (
                    'Stripe has not confirmed the payment yet. Your workspace '
                    'will unlock automatically once it does.'
                ),
            })
        reconcile_checkout(request.user, session)
        for key in list(request.session.keys()):
            if key.startswith('checkout_key_'):
                del request.session[key]
    except StripeError as exc:
        return render(request, 'accounts/checkout_status.html', {
            'status': 'error',
            'title': 'We could not confirm that payment',
            'message': str(exc),
        }, status=502)
    return render(request, 'accounts/checkout_status.html', {
        'status': 'success',
        'title': 'Your KwaCart workspace is ready',
        'message': (
            'Payment confirmed. Your plan is active, and your full workspace '
            'access is now available.'
        ),
    })


def checkout_cancel(request):
    """Explain a cancelled checkout and offer a direct retry."""
    if not settings.BILLING_ENABLED:
        return HttpResponse('Billing is not available in the self-hosted edition.', status=404)
    plan = request.GET.get('plan', 'solo')
    interval = request.GET.get('interval', 'month')
    return render(request, 'accounts/checkout_status.html', {
        'status': 'cancelled',
        'title': 'Checkout cancelled',
        'message': (
            'No payment was taken. You can return to the plan you selected and '
            'try again whenever you are ready.'
        ),
        'retry_url': (
            f'{reverse_lazy("pricing")}?retry_plan={plan}&retry_interval={interval}'
        ),
    })


@login_required
@require_POST
def billing_portal(request):
    """Send a paying customer to Stripe's authenticated billing portal."""
    if not settings.BILLING_ENABLED:
        return HttpResponse('Billing is not available in the self-hosted edition.', status=404)
    if _billing_rate_limited(request, 'billing-portal', 20, 8):
        return _billing_throttled_response()
    if request.user.organisation_owner_id is not None:
        raise PermissionDenied
    try:
        session = create_portal_session(
            request.user,
            request.build_absolute_uri(reverse_lazy('accounts:profile')),
        )
    except StripeError as exc:
        messages.error(request, str(exc))
        return redirect('accounts:profile')
    return redirect(session['url'])


@csrf_exempt
@require_POST
def stripe_webhook(request):
    """Apply only Stripe-signed subscription lifecycle events."""
    if not settings.BILLING_ENABLED:
        return HttpResponse('Billing is not available in the self-hosted edition.', status=404)
    if is_layered_rate_limited(
        request, 'billing-webhook', ip_limit=600,
        window_seconds=60, lockout_seconds=60,
    ):
        response = HttpResponse('Too many requests.', status=429)
        response['Retry-After'] = '60'
        return response
    signature = request.META.get('HTTP_STRIPE_SIGNATURE', '')
    try:
        if not verify_webhook_signature(request.body, signature, webhook_secret()):
            return HttpResponse('Invalid Stripe signature.', status=400)
        handle_webhook_event(json.loads(request.body.decode('utf-8')))
    except (StripeError, ValueError, UnicodeDecodeError):
        return HttpResponse('Webhook could not be processed.', status=400)
    return HttpResponse('received', status=200)


@login_required
def profile_view(request):
    """Read and update the authenticated user's profile.

    Two independent forms are handled by inspecting a hidden ``action`` field:
    - ``update_email``    — saves a new email address (ProfileEmailForm)
    - ``change_password`` — updates the password (Django's PasswordChangeForm)
      and re-signs the session so the user is not immediately logged out.
    """
    user = request.user
    billing_account = user.billing_account
    if settings.BILLING_ENABLED and billing_account.stripe_subscription_id:
        try:
            sync_subscription(billing_account)
        except StripeError:
            # Billing outages must not hide the profile. The signed webhook or
            # the next successful load will reconcile the status.
            pass
    email_form = ProfileEmailForm(instance=user)
    password_form = PasswordChangeForm(user)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_email':
            email_form = ProfileEmailForm(request.POST, instance=user)
            if email_form.is_valid():
                old_domain = user.email_domain
                updated_user = email_form.save()
                if (
                    updated_user.organisation_owner
                    and updated_user.email_domain
                    != updated_user.organisation_owner.email_domain
                ):
                    updated_user.unlink_from_organisation()
                if (
                    updated_user.plan == 'organisation'
                    and old_domain != updated_user.email_domain
                ):
                    updated_user.unlink_organisation_members()
                    updated_user.link_organisation_members()
                messages.success(request, 'Email address updated.')
                return redirect('accounts:profile')

        elif action == 'change_password':
            password_form = PasswordChangeForm(user, request.POST)
            if password_form.is_valid():
                updated_user = password_form.save()
                update_session_auth_hash(request, updated_user)
                messages.success(request, 'Password updated.')
                return redirect('accounts:profile')

    from archive.models import ToolSession
    from django.db.models import Q
    solo_count = solo_records_for_user(user).filter(status='archived').count()
    session_count = ToolSession.objects.filter(
        session_access_q(user) | Q(instances__user=user)
    ).distinct().count()

    is_organisation_owner = (
        user.organisation_owner_id is None
        and user.plan == 'organisation'
        and user.has_paid_access
    )
    team_policy_form = (
        OrganisationMemberPolicyForm(owner=user, prefix='team')
        if is_organisation_owner else None
    )
    team_members = []
    if is_organisation_owner:
        policies = {
            policy.member_id: policy
            for policy in OrganisationMemberDataPolicy.objects.filter(
                owner=user,
                active=True,
            )
        }
        pending_by_member = {
            pending.member_id: pending
            for pending in OrganisationDataTransferRequest.objects.filter(
                owner=user,
                status=OrganisationDataTransferRequest.PENDING,
            )
        }
        team_members = [
            {
                'user': member,
                'policy': policies.get(member.pk),
                'pending': pending_by_member.get(member.pk),
            }
            for member in user.organisation_members.order_by('email')
        ]
    pending_transfer_requests = (
        user.received_data_transfer_requests
        .filter(status=OrganisationDataTransferRequest.PENDING)
        .select_related('owner')
    )
    current_data_policy = (
        OrganisationMemberDataPolicy.objects
        .filter(member=user, active=True)
        .select_related('owner')
        .first()
    )

    return render(request, 'accounts/profile.html', {
        'email_form': email_form,
        'password_form': password_form,
        'solo_count': solo_count,
        'session_count': session_count,
        'billing_account': billing_account,
        'is_organisation_owner': is_organisation_owner,
        'team_policy_form': team_policy_form,
        'team_members': team_members,
        'pending_transfer_requests': pending_transfer_requests,
        'current_data_policy': current_data_policy,
        'has_organisation_retained_work': _has_organisation_retained_work(user),
    })


@login_required
@require_POST
def organisation_data_policy_request(request):
    """Let an Organisation owner propose a retention policy to a member."""
    owner = request.user
    if (
        owner.organisation_owner_id is not None
        or owner.plan != 'organisation'
        or not owner.has_paid_access
    ):
        raise PermissionDenied
    form = OrganisationMemberPolicyForm(request.POST, owner=owner, prefix='team')
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect('accounts:profile')
    try:
        with transaction.atomic():
            member = User.objects.select_for_update().get(pk=form.member.pk)
            if member.organisation_owner_id is None:
                member.organisation_owner = owner
                member.save(update_fields=['organisation_owner'])
            transfer_request = create_transfer_request(
                owner, member, form.cleaned_data['policy'],
            )
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
        return redirect('accounts:profile')
    messages.success(
        request,
        f'{member.email} can now review the {transfer_request.get_target_policy_display()} request.',
    )
    return redirect('accounts:profile')


@login_required
@require_POST
def organisation_data_policy_response(request, request_id):
    """Accept or decline a pending data-retention request as its member."""
    transfer_request = get_object_or_404(
        OrganisationDataTransferRequest, pk=request_id, member=request.user,
    )
    action = request.POST.get('action')
    try:
        if action == 'accept':
            accept_transfer_request(request.user, transfer_request)
            messages.success(request, 'Your team data-retention choice is now active.')
        elif action == 'decline':
            decline_transfer_request(request.user, transfer_request)
            messages.success(request, 'The data-retention request was declined.')
        else:
            messages.error(request, 'Choose accept or decline.')
    except (ValidationError, PermissionDenied) as exc:
        detail = exc.messages if isinstance(exc, ValidationError) else [str(exc)]
        messages.error(request, '; '.join(detail))
    return redirect('accounts:profile')


@login_required
@require_POST
def account_delete(request):
    """Permanently delete the authenticated user's account.

    Requires the hidden field ``confirm`` to equal the string ``'DELETE'``
    to guard against accidental form submissions or CSRF-style misfires.
    Deleting the user cascades to all their ``ToolSession`` and
    ``ToolInstance`` records via the database-level CASCADE constraint.
    """
    user = request.user
    if _has_organisation_retained_work(user):
        messages.error(
            request,
            'This account is the recorded creator of work retained by your '
            'organisation, so it cannot be deleted. You can update your email '
            'or ask the Organisation account holder to change future retention.',
        )
        return redirect('accounts:profile')
    if settings.BILLING_ENABLED and not user.organisation_owner and user.stripe_subscription_id:
        try:
            sync_subscription(user)
            user.refresh_from_db()
        except StripeError:
            messages.error(
                request,
                'We could not confirm that Stripe billing has ended. '
                'Please try again before deleting this account.',
            )
            return redirect('accounts:profile')
    if (
        settings.BILLING_ENABLED
        and not user.organisation_owner
        and user.stripe_subscription_id
        and user.subscription_status not in {'canceled', 'incomplete_expired'}
    ):
        messages.error(
            request,
            'Manage and end your Stripe subscription before deleting this account.',
        )
        return redirect('accounts:profile')
    if request.POST.get('confirm') == 'DELETE':
        with transaction.atomic():
            locked_user = User.objects.select_for_update().get(pk=user.pk)
            if _has_organisation_retained_work(locked_user):
                messages.error(
                    request,
                    'Organisation-retained work was found, so this account was not deleted.',
                )
                return redirect('accounts:profile')
            locked_user.delete()
        messages.success(request, 'Your account has been permanently deleted.')
        return redirect('home')
    messages.error(request, 'Account deletion was not confirmed.')
    return redirect('accounts:profile')
