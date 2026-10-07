# App namespace: 'accounts'
# Named URLs exposed by this module:
#   accounts:signup   — user registration page
#   accounts:login    — login page (referenced by login_required redirects)
#   accounts:logout   — POST-only logout endpoint
#   accounts:profile  — authenticated user's profile (read + update)
#   accounts:delete   — POST-only permanent account deletion
from django.urls import path
from .views import (
    SignUpView,
    UserLoginView,
    UserLogoutView,
    account_delete,
    billing_portal,
    checkout_cancel,
    checkout_start,
    checkout_success,
    organisation_data_policy_request,
    organisation_data_policy_response,
    profile_view,
    stripe_webhook,
)

app_name = 'accounts'

urlpatterns = [
    path('signup/', SignUpView.as_view(), name='signup'),
    path('login/', UserLoginView.as_view(), name='login'),
    path('logout/', UserLogoutView.as_view(), name='logout'),
    path('profile/', profile_view, name='profile'),
    path('checkout/', checkout_start, name='checkout'),
    path('checkout/success/', checkout_success, name='checkout_success'),
    path('checkout/cancel/', checkout_cancel, name='checkout_cancel'),
    path('billing/portal/', billing_portal, name='billing_portal'),
    path('billing/webhook/', stripe_webhook, name='stripe_webhook'),
    path(
        'team/data-policy/',
        organisation_data_policy_request,
        name='organisation_data_policy_request',
    ),
    path(
        'team/data-policy/<int:request_id>/respond/',
        organisation_data_policy_response,
        name='organisation_data_policy_response',
    ),
    path('delete/', account_delete, name='delete'),
]
