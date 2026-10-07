"""Root URL configuration for the KwaCart project.

Mounts four application routers under their respective prefixes and
defines two lightweight inline views (``home`` and ``about``) that render
static marketing pages without requiring a dedicated views module.

URL map
-------
``/``                   → landing page (home)
``/about/``             → about page
``/pricing/``           → public pricing page
``/admin/``             → Django admin
``/accounts/``          → accounts app (login, logout, sign-up)
``/tools/``             → tools app (catalog, draft, session, guest flows)
``/archive/``           → archive app (dashboard, detail, downloads)
``/request-a-feature/`` → feature-request submission page
``/join/``              → companion-pairing entry (3-digit code)
``/join/<code>/``       → companion-pairing redirect to guest_join
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.shortcuts import redirect, render
from django.urls import include, path

from academy.views import academy_dashboard
from tools.views import pairing_entry, pairing_join
from archive.views import (
    contextual_feedback,
    feedback_portal,
    feedback_prompt_dismiss,
)


# home and about are simple template-only views.  Defining them inline here
# avoids creating a dedicated views.py just for two trivial render() calls.
def home(request):
    return render(request, 'landing.html')


def about(request):
    return render(request, 'about.html')


def accessibility(request):
    return render(request, 'accessibility.html')


def privacy(request):
    return render(request, 'privacy.html' if settings.BILLING_ENABLED else 'selfhost_privacy.html')


def learn(request):
    return academy_dashboard(request)


def pricing(request):
    if not settings.BILLING_ENABLED:
        return redirect('self_hosting', permanent=True)
    return render(request, 'pricing.html')


def self_hosting(request):
    return render(request, 'self_hosting.html')


def new_starter_case_study(request):
    return render(request, 'case_studies/new_starter.html')


def succession_case_study(request):
    return render(request, 'case_studies/succession.html')


def winning_grant_case_study(request):
    return render(request, 'case_studies/winning_grant.html')


def service_transformation_case_study(request):
    return render(request, 'case_studies/service_transformation.html')


def opposition_case_study(request):
    return render(request, 'case_studies/opposition.html')


def person_centred_plan_case_study(request):
    return render(request, 'case_studies/person_centred_plan.html')


def learning_plan_case_study(request):
    return render(request, 'case_studies/learning_plan.html')


def positive_behaviour_case_study(request):
    return render(request, 'case_studies/positive_behaviour.html')


def communication_plan_case_study(request):
    return render(request, 'case_studies/communication_plan.html')


urlpatterns = [
    path('', home, name='home'),
    path('about/', about, name='about'),
    path('accessibility/', accessibility, name='accessibility'),
    path('privacy/', privacy, name='privacy'),
    path('learn/', learn, name='learn'),
    path('academy/', include('academy.urls')),
    path('pricing/', pricing, name='pricing'),
    path('self-host/', self_hosting, name='self_hosting'),
    path(
        'case-studies/train-a-new-starter/',
        new_starter_case_study,
        name='new_starter_case_study',
    ),
    path(
        'case-studies/plan-for-succession/',
        succession_case_study,
        name='succession_case_study',
    ),
    path(
        'case-studies/write-a-winning-grant/',
        winning_grant_case_study,
        name='winning_grant_case_study',
    ),
    path(
        'case-studies/transform-a-service/',
        service_transformation_case_study,
        name='service_transformation_case_study',
    ),
    path(
        'case-studies/navigate-opposition/',
        opposition_case_study,
        name='opposition_case_study',
    ),
    path(
        'case-studies/build-a-person-centred-plan/',
        person_centred_plan_case_study,
        name='person_centred_plan_case_study',
    ),
    path(
        'case-studies/design-a-learning-plan/',
        learning_plan_case_study,
        name='learning_plan_case_study',
    ),
    path(
        'case-studies/support-positive-behaviour/',
        positive_behaviour_case_study,
        name='positive_behaviour_case_study',
    ),
    path(
        'case-studies/shape-a-communication-plan/',
        communication_plan_case_study,
        name='communication_plan_case_study',
    ),
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('tools/', include('tools.urls')),
    path('archive/', include('archive.urls')),
    path('feedback/', feedback_portal, name='feedback'),
    path('feedback/contextual/', contextual_feedback, name='contextual_feedback'),
    path('feedback/dismiss/', feedback_prompt_dismiss, name='feedback_prompt_dismiss'),
    path('request-a-feature/', include('archive.urls_feature_request')),
    # Companion pairing — short /join/<code>/ URLs for secondary-device entry.
    path('join/', pairing_entry, name='pairing_entry'),
    path('join/<str:code>/', pairing_join, name='pairing_join'),
    # static() returns [] in production (WhiteNoise serves files instead).
    # In development it adds a URL pattern so the dev server can serve uploads.
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
