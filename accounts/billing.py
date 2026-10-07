"""Subscription reconciliation and Organisation membership helpers."""
from django.db import transaction

from .models import User
from .stripe_client import (
    StripeError,
    retrieve_subscription,
    unix_to_datetime,
)


ACTIVE_STATUSES = {'active', 'trialing'}


def plan_from_subscription(subscription):
    metadata = subscription.get('metadata') or {}
    plan = metadata.get('kwacart_plan') or metadata.get('plan')
    interval = metadata.get('billing_interval') or metadata.get('interval')
    item = ((subscription.get('items') or {}).get('data') or [{}])[0]
    price = item.get('price') or {}
    price_metadata = price.get('metadata') or {}
    plan = plan or price_metadata.get('kwacart_plan')
    interval = interval or price_metadata.get('billing_interval')
    interval = interval or (price.get('recurring') or {}).get('interval')
    if plan not in {'solo', 'organisation'}:
        return None, interval
    return plan, interval


@transaction.atomic
def apply_subscription(
    user, subscription, event_created=0, allow_replacement=False,
):
    """Apply Stripe's current subscription state to a local account."""
    incoming_id = subscription.get('id')
    if (
        user.stripe_subscription_id
        and incoming_id
        and incoming_id != user.stripe_subscription_id
        and not allow_replacement
    ):
        raise StripeError('This is not the account’s current subscription.')
    if event_created and event_created < user.stripe_event_created:
        return user
    plan, interval = plan_from_subscription(subscription)
    status = subscription.get('status', 'none')
    if status not in {
        'active', 'trialing', 'past_due', 'unpaid', 'incomplete',
        'incomplete_expired', 'canceled',
    }:
        status = 'none'
    if plan is None:
        plan = user.plan if user.plan in {'solo', 'organisation'} else 'free'
    user.plan = plan
    user.subscription_status = status
    user.billing_interval = interval or user.billing_interval
    user.stripe_subscription_id = subscription.get('id') or user.stripe_subscription_id
    user.stripe_price_id = (
        ((subscription.get('items') or {}).get('data') or [{}])[0]
        .get('price', {})
        .get('id')
        or user.stripe_price_id
    )
    user.subscription_current_period_end = unix_to_datetime(
        subscription.get('current_period_end')
    )
    user.subscription_cancel_at_period_end = bool(
        subscription.get('cancel_at_period_end')
    )
    user.stripe_event_created = max(user.stripe_event_created, event_created or 0)
    user.save(update_fields=[
        'plan', 'subscription_status', 'billing_interval',
        'stripe_subscription_id', 'stripe_price_id',
        'subscription_current_period_end', 'subscription_cancel_at_period_end',
        'stripe_event_created',
    ])
    if user.plan == 'organisation' and user.subscription_status in ACTIVE_STATUSES:
        user.link_organisation_members()
    elif user.subscription_status not in ACTIVE_STATUSES:
        user.unlink_organisation_members()
    return user


def sync_subscription(user, subscription_id=None, event_created=0):
    """Refresh a local account from Stripe, if it has a subscription."""
    subscription_id = subscription_id or user.stripe_subscription_id
    if not subscription_id:
        return user
    return apply_subscription(
        user,
        retrieve_subscription(subscription_id),
        event_created=event_created,
    )


def user_for_subscription(subscription):
    metadata = subscription.get('metadata') or {}
    user_id = metadata.get('user_id')
    if user_id:
        try:
            return User.objects.get(pk=user_id)
        except (User.DoesNotExist, ValueError):
            pass
    customer_id = subscription.get('customer')
    if customer_id:
        return User.objects.filter(stripe_customer_id=customer_id).first()
    return None


def reconcile_checkout(user, session):
    """Confirm a completed checkout belongs to this user before activating it."""
    reference = str(session.get('client_reference_id') or '')
    customer = session.get('customer')
    if reference != str(user.pk) and customer != user.stripe_customer_id:
        raise StripeError('That checkout session does not belong to this account.')
    subscription = session.get('subscription')
    if isinstance(subscription, dict):
        subscription_data = subscription
    elif subscription:
        subscription_data = retrieve_subscription(subscription)
    else:
        raise StripeError('Stripe has not created a subscription for this checkout yet.')
    return apply_subscription(user, subscription_data)


def handle_webhook_event(event):
    """Apply subscription lifecycle events; unknown events are acknowledged."""
    event_type = event.get('type', '')
    data = (event.get('data') or {}).get('object') or {}
    event_created = int(event.get('created') or 0)
    if event_type.startswith('customer.subscription.'):
        user = user_for_subscription(data)
        if user:
            apply_subscription(
                user,
                data,
                event_created=event_created,
                allow_replacement=True,
            )
    elif event_type == 'checkout.session.completed':
        user = None
        reference = str(data.get('client_reference_id') or '')
        if reference:
            try:
                user = User.objects.get(pk=reference)
            except (User.DoesNotExist, ValueError):
                pass
        user = user or user_for_subscription(data)
        if user and data.get('subscription'):
            sync_subscription(user, data['subscription'])
    elif event_type == 'invoice.payment_failed':
        customer_id = data.get('customer')
        user = User.objects.filter(stripe_customer_id=customer_id).first()
        if user and data.get('subscription'):
            sync_subscription(
                user, data['subscription'], event_created=event_created,
            )