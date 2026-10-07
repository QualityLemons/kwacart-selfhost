from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .forms import CustomUserChangeForm, CustomUserCreationForm
from .models import OrganisationDataTransferRequest, OrganisationMemberDataPolicy, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """Admin class for the email-as-username custom User model.

    Extends Django's built-in ``UserAdmin`` to work with a model where
    ``USERNAME_FIELD = 'email'``.  Replaces the default username-centric
    fieldsets and forms with email-only equivalents.
    """

    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    model = User
    list_display = (
        'email', 'plan', 'subscription_status', 'is_staff', 'is_active',
        'date_joined',
    )
    list_filter = ('plan', 'subscription_status', 'is_staff', 'is_active')
    ordering = ('email',)
    search_fields = ('email',)

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Billing', {'fields': (
            'plan', 'subscription_status', 'billing_interval',
            'stripe_customer_id', 'stripe_subscription_id', 'stripe_price_id',
            'subscription_current_period_end',
            'subscription_cancel_at_period_end', 'stripe_event_created',
            'organisation_owner',
        )}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser',
                                    'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2',
                       'is_active', 'is_staff', 'is_superuser'),
        }),
    )


@admin.register(OrganisationMemberDataPolicy)
class OrganisationMemberDataPolicyAdmin(admin.ModelAdmin):
    list_display = ('member', 'owner', 'policy', 'active', 'updated_at')
    list_filter = ('policy', 'active')
    search_fields = ('member__email', 'owner__email')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(OrganisationDataTransferRequest)
class OrganisationDataTransferRequestAdmin(admin.ModelAdmin):
    list_display = (
        'member', 'owner', 'target_policy', 'status', 'requested_at', 'resolved_at',
    )
    list_filter = ('target_policy', 'status')
    search_fields = ('member__email', 'owner__email')
    readonly_fields = (
        'owner', 'member', 'target_policy', 'status', 'requested_at', 'resolved_at',
        'transferred_solo_count', 'transferred_session_count',
    )
