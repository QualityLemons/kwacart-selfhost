from django.contrib import admin

from .models import AuditLog, FeatureRequest, ToolInstance, ToolSession


@admin.register(ToolSession)
class ToolSessionAdmin(admin.ModelAdmin):
    """Admin view for collaborative ToolSession records."""

    list_display = (
        'id', 'tool_slug', 'host', 'data_owner', 'status', 'created_at', 'closed_at',
    )
    list_filter = ('status', 'tool_slug')
    search_fields = ('tool_slug', 'host__email', 'data_owner__email')
    readonly_fields = ('id', 'created_at')


@admin.register(ToolInstance)
class ToolInstanceAdmin(admin.ModelAdmin):
    """Admin view for individual ToolInstance draft and archived records."""

    list_display = (
        'id', 'user', 'data_owner', 'tool_slug', 'tool_version', 'status',
        'session', 'created_at', 'submitted_at',
    )
    list_filter = ('status', 'tool_slug')
    search_fields = ('tool_slug', 'user__email', 'data_owner__email')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(FeatureRequest)
class FeatureRequestAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'feedback_type', 'rating', 'review_status', 'source',
        'tool_slug', 'submitter', 'submitted_at',
    )
    list_filter = ('feedback_type', 'review_status', 'source', 'interaction_mode')
    search_fields = (
        'title', 'description', 'name', 'email', 'tool_slug',
        'submitter__email',
    )
    readonly_fields = ('submitted_at', 'reviewed_at')


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-oriented admin view for the AuditLog security table.

    No custom delete action is registered here; the standard Django admin
    delete action remains available, which is intentional — administrators
    may need to purge logs for legal or data-retention reasons.  The
    ``timestamp`` field is read-only to prevent tampering via the admin UI.
    """

    list_display = ('timestamp', 'user', 'action', 'resource_id', 'ip_address')
    list_filter = ('action',)
    search_fields = ('user__email', 'resource_id')
    readonly_fields = ('timestamp',)
