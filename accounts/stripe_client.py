"""Small Stripe REST client backed by the connected Replit Stripe integration.

The Python connector package is not available in every Replit Python image, so
this module uses the same connection API as the official connector setup.  It
fetches a fresh credential for every request and never stores it in Django
settings or the database.
"""
import hashlib
import hmac
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings


class StripeError(Exception):
    """A safe, user-facing Stripe API error."""


def _connection_credentials():
    hostname = os.environ.get('REPLIT_CONNECTORS_HOSTNAME')
    identity = os.environ.get('REPLIT_IDENTITY')
    renewal = os.environ.get('WEB_REPL_RENEWAL')
    token = f'repl {identity}' if identity else f'depl {renewal}' if renewal else None
    if not hostname or not token:
        raise StripeError(
            'Stripe billing is not available yet. Connect Stripe to this Replit '
            'environment before taking payments.'
        )
    request = Request(
        f'https://{hostname}/api/v2/connection?include_secrets=true&connector_names=stripe',
        headers={'Accept': 'application/json', 'X_REPLIT_TOKEN': token},
    )
    try:
        with urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise StripeError('Stripe connection could not be reached.') from exc
    settings_data = (data.get('items') or [{}])[0].get('settings') or {}
    secret_key = settings_data.get('secret_key')
    if not secret_key:
        raise StripeError('Stripe is connected without a usable secret key.')
    return secret_key, settings_data.get('webhook_secret')


def _sdk_proxy_request(method, path, fields=None, extra_headers=None):
    body = urlencode(fields or {}) if method == 'POST' else None
    query_path = path
    if method == 'GET' and fields:
        query_path = f'{path}?{urlencode(fields)}'
    payload = json.dumps({
        'method': method,
        'path': query_path,
        'headers': {
            'Content-Type': 'application/x-www-form-urlencoded',
            **(extra_headers or {}),
        },
        'body': body,
    })
    try:
        result = subprocess.run(
            ['node', str(settings.BASE_DIR / 'scripts' / 'stripe_proxy.mjs')],
            input=payload,
            text=True,
            capture_output=True,
            timeout=20,
            check=True,
        )
        response = json.loads(result.stdout)
        data = json.loads(response['body'])
    except (subprocess.SubprocessError, ValueError, KeyError) as exc:
        raise StripeError('Stripe connection could not be reached.') from exc
    if not response['ok']:
        raise StripeError(data.get('error', {}).get('message', 'Stripe request failed.'))
    return data


def _request(method, path, fields=None, extra_headers=None):
    try:
        secret_key, _ = _connection_credentials()
    except StripeError:
        return _sdk_proxy_request(method, path, fields, extra_headers)
    body = urlencode(fields or {}).encode('utf-8') if method == 'POST' else None
    url = f'https://api.stripe.com{path}'
    if method == 'GET' and fields:
        url = f'{url}?{urlencode(fields)}'
    request = Request(
        url,
        data=body,
        method=method,
        headers={
            'Authorization': f'Bearer {secret_key}',
            'Content-Type': 'application/x-www-form-urlencoded',
            **(extra_headers or {}),
        },
    )
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode('utf-8'))
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode('utf-8'))
            message = payload.get('error', {}).get('message', 'Stripe request failed.')
        except (ValueError, UnicodeDecodeError):
            message = 'Stripe request failed.'
        raise StripeError(message) from exc
    except (URLError, TimeoutError, ValueError) as exc:
        raise StripeError('Stripe could not be reached. Please try again.') from exc


def get(path, fields=None):
    return _request('GET', path, fields)


def post(path, fields, idempotency_key=None):
    headers = {'Idempotency-Key': idempotency_key} if idempotency_key else None
    return _request('POST', path, fields, headers)


def _settings_price(plan, interval):
    prices = getattr(settings, 'STRIPE_PRICE_IDS', {})
    return prices.get(plan, {}).get(interval)


def find_price(plan, interval):
    """Find the active recurring price by metadata, with a configured fallback."""
    price_list = get('/v1/prices', {
        'active': 'true', 'type': 'recurring', 'limit': '100',
    }).get('data', [])
    for price in price_list:
        metadata = price.get('metadata') or {}
        recurring = price.get('recurring') or {}
        if (
            metadata.get('kwacart_plan') == plan
            and recurring.get('interval') == interval
            and price.get('currency') == 'gbp'
        ):
            return price['id']
    return _settings_price(plan, interval)


def get_or_create_customer(user):
    if user.stripe_customer_id:
        customer = get(f'/v1/customers/{user.stripe_customer_id}')
        if not customer.get('deleted'):
            return customer
    return post('/v1/customers', {
        'email': user.email,
        'metadata[user_id]': str(user.pk),
        'metadata[kwacart_plan]': user.plan,
    })


def create_checkout_session(
    user, price_id, success_url, cancel_url, plan, interval, idempotency_key,
):
    customer = get_or_create_customer(user)
    if customer.get('id') != user.stripe_customer_id:
        user.stripe_customer_id = customer['id']
        user.save(update_fields=['stripe_customer_id'])
    return post('/v1/checkout/sessions', {
        'customer': customer['id'],
        'mode': 'subscription',
        'line_items[0][price]': price_id,
        'line_items[0][quantity]': '1',
        'success_url': success_url,
        'cancel_url': cancel_url,
        'client_reference_id': str(user.pk),
        'metadata[plan]': plan,
        'metadata[interval]': interval,
        'subscription_data[metadata][user_id]': str(user.pk),
        'subscription_data[metadata][kwacart_plan]': plan,
        'subscription_data[metadata][billing_interval]': interval,
        'billing_address_collection': 'auto',
    }, idempotency_key=idempotency_key)


def create_portal_session(user, return_url):
    if not user.stripe_customer_id:
        raise StripeError('There is no Stripe billing account to manage yet.')
    return post('/v1/billing_portal/sessions', {
        'customer': user.stripe_customer_id,
        'return_url': return_url,
    })


def retrieve_checkout_session(session_id):
    return get(f'/v1/checkout/sessions/{session_id}', {'expand[]': 'subscription'})


def retrieve_subscription(subscription_id):
    return get(f'/v1/subscriptions/{subscription_id}', {'expand[]': 'items.data.price'})


def unix_to_datetime(value):
    return datetime.fromtimestamp(value, tz=timezone.utc) if value else None


def verify_webhook_signature(payload, header, secret):
    """Verify Stripe's signed timestamped payload without a third-party SDK."""
    if not header or not secret:
        return False
    values = dict(part.split('=', 1) for part in header.split(',') if '=' in part)
    timestamp = values.get('t')
    signature = values.get('v1')
    if not timestamp or not signature:
        return False
    try:
        if abs(time.time() - int(timestamp)) > 300:
            return False
    except ValueError:
        return False
    signed = f'{timestamp}.{payload.decode("utf-8")}'.encode('utf-8')
    digest = hmac.new(secret.encode('utf-8'), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature)


def webhook_secret():
    configured = os.environ.get('STRIPE_WEBHOOK_SECRET')
    if configured:
        return configured
    return _connection_credentials()[1]