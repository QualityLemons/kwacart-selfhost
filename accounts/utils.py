def log_action(user, action, resource_id=None, metadata=None):
    """Record a single event in the AuditLog table.

    Parameters
    ----------
    user:        The User instance performing the action (may be None for
                 anonymous events, though none are currently recorded).
    action:      One of the strings in ``AuditLog.ACTION_CHOICES``
                  ('login', 'submit', 'download', 'access_denied',
                  'organisation_transfer_requested',
                  'organisation_transfer_accepted', or
                  'organisation_transfer_declined').
    resource_id: Optional identifier of the affected object (e.g. a
                 ToolInstance pk or ToolSession UUID), stored as a string.
    metadata:    Optional dict of extra context (e.g. file_type, user_agent).

    ``AuditLog`` is imported inside this function to avoid a circular import:
    the ``archive`` app imports from ``accounts``, so a top-level import of
    ``archive.models`` here would create an import cycle at startup.
    """
    from archive.models import AuditLog
    AuditLog.objects.create(
        user=user,
        action=action,
        resource_id=str(resource_id) if resource_id else None,
        metadata=metadata or {}
    )
