"""Database-backed, multi-identity throttling for expensive endpoints."""
import hashlib
import ipaddress
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone


def _trusted_proxy_networks():
    configured = getattr(settings, 'RATE_LIMIT_TRUSTED_PROXY_NETWORKS', (
        '127.0.0.0/8',
        '::1/128',
        '10.0.0.0/8',
        '172.16.0.0/12',
        '192.168.0.0/16',
    ))
    return tuple(ipaddress.ip_network(value) for value in configured)


def _is_trusted_proxy(address):
    try:
        remote = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(remote in network for network in _trusted_proxy_networks())


def client_ip(request):
    """Return the client address supplied by a trusted reverse proxy.

    A public origin address cannot opt into X-Forwarded-For by sending the
    header itself. The trusted proxy appends the address it observed to the
    right side of the chain, so caller-controlled prefixes are ignored.
    """
    remote = request.META.get('REMOTE_ADDR', '')
    if not _is_trusted_proxy(remote):
        return remote

    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    chain = []
    for value in forwarded.split(','):
        value = value.strip()
        if not value:
            continue
        try:
            ipaddress.ip_address(value)
        except ValueError:
            continue
        chain.append(value)

    # Walk from the application back through known proxies. The first address
    # outside the trusted infrastructure is the client. This handles Replit or
    # CDN ingress chains without collapsing every visitor onto the nearest hop.
    for address in reversed(chain):
        if not _is_trusted_proxy(address):
            return address
    return chain[0] if chain else remote


def _bucket_key(scope, identity):
    value = f'{scope}\0{identity or "unknown"}'.encode('utf-8')
    return hashlib.sha256(value).hexdigest()


def _consume(key, max_attempts, window_seconds, lockout_seconds):
    from accounts.models import RequestRateLimit

    timestamp = timezone.now()
    # Concurrent first requests can both attempt an INSERT. Retrying after the
    # losing transaction rolls back makes bucket creation safe on PostgreSQL.
    for attempt in range(2):
        try:
            with transaction.atomic():
                bucket, _created = RequestRateLimit.objects.get_or_create(
                    key=key, defaults={'window_started': timestamp},
                )
                bucket = RequestRateLimit.objects.select_for_update().get(pk=bucket.pk)

                if bucket.locked_until and bucket.locked_until > timestamp:
                    return True

                if timestamp >= bucket.window_started + timedelta(seconds=window_seconds):
                    bucket.window_started = timestamp
                    bucket.attempts = 0
                    bucket.locked_until = None

                bucket.attempts += 1
                limited = bucket.attempts > max_attempts
                if limited:
                    bucket.locked_until = timestamp + timedelta(seconds=lockout_seconds)
                bucket.save(update_fields=[
                    'attempts', 'locked_until', 'window_started', 'updated_at',
                ])
                return limited
        except IntegrityError:
            if attempt:
                raise


def is_rate_limited(
    request, scope, max_attempts, window_seconds, lockout_seconds,
    *, identity=None,
):
    """Throttle requests per client IP within a named ``scope``.

    Once a client exceeds ``max_attempts`` requests within ``window_seconds``
    it is locked out for ``lockout_seconds``, during which every call for
    that scope/IP short-circuits to ``True`` without incrementing further.
    Each call that is not already locked out counts as one attempt — callers
    should call this once per request they want throttled (e.g. once per
    POST), not per validation branch.
    """
    bucket_identity = identity if identity is not None else f'ip:{client_ip(request)}'
    return _consume(
        _bucket_key(scope, bucket_identity),
        max_attempts, window_seconds, lockout_seconds,
    )


def is_layered_rate_limited(
    request, scope, *, ip_limit, user_limit=None, session_limit=None,
    session_id=None, window_seconds=60, lockout_seconds=60,
):
    """Consume IP, authenticated-user and logical-session buckets.

    Every applicable bucket is consumed even when an earlier layer is already
    over limit, preventing a caller from preserving another identity's budget.
    """
    identities = [(f'{scope}:ip', f'ip:{client_ip(request) or "unknown"}', ip_limit)]
    user = getattr(request, 'user', None)
    if user_limit is not None and getattr(user, 'is_authenticated', False):
        identities.append((f'{scope}:user', f'user:{user.pk}', user_limit))
    if session_limit is not None:
        sid = session_id or getattr(getattr(request, 'session', None), 'session_key', None)
        if not sid:
            from django.conf import settings
            sid = request.COOKIES.get(settings.SESSION_COOKIE_NAME)
        if sid:
            identities.append((f'{scope}:session', f'session:{sid}', session_limit))
    results = [
        _consume(_bucket_key(bucket_scope, identity), limit, window_seconds, lockout_seconds)
        for bucket_scope, identity, limit in identities
    ]
    return any(results)
