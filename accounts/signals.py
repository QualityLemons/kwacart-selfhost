from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from archive.models import AuditLog


# Fires on every successful login (including admin logins).
# Note: in production REMOTE_ADDR will be the load-balancer / proxy IP, not
# the end user's IP, unless the proxy is configured to forward it correctly.
@receiver(user_logged_in)
def log_user_login(sender, request, user, **kwargs):
    AuditLog.objects.create(
        user=user,
        action='login',
        ip_address=request.META.get('REMOTE_ADDR'),
        metadata={'user_agent': request.META.get('HTTP_USER_AGENT')}
    )
