"""One-time account bootstrap, available only to the launcher's browser."""
import secrets
import threading
from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from accounts.forms import CustomUserCreationForm

_creation_lock = threading.Lock()


class FirstAccountMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (not request.path.startswith(('/desktop/', '/static/'))
                and not get_user_model().objects.exists()):
            return redirect('desktop_setup')
        return self.get_response(request)


@never_cache
@require_http_methods(['GET', 'POST'])
def first_account(request):
    if get_user_model().objects.exists():
        return redirect('accounts:login')
    ticket = request.GET.get('ticket', '')
    if ticket and settings.SETUP_TICKET and secrets.compare_digest(ticket, settings.SETUP_TICKET):
        request.session['desktop_setup_allowed'] = True
        # Remove the launch ticket from the URL before displaying the form.
        response = redirect('desktop_setup')
        response['Referrer-Policy'] = 'no-referrer'
        return response
    if not request.session.get('desktop_setup_allowed'):
        return HttpResponseForbidden(
            'Open setup using the Open KwaCart button in the desktop window.',
        )
    form = CustomUserCreationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with _creation_lock, transaction.atomic():
            if get_user_model().objects.exists():
                return redirect('accounts:login')
            user = form.save(commit=False)
            user.is_staff = True
            user.is_superuser = True
            user.save()
        request.session.pop('desktop_setup_allowed', None)
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        return redirect('home')
    response = render(request, 'desktop/setup.html', {'form': form})
    response['Referrer-Policy'] = 'no-referrer'
    return response
