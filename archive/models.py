"""Database models for the archive application.

``ToolSession``  — a collaborative session hosted by one user; stores timer
                   state, guest-access token, and references to its export files.
``ToolInstance`` — a single user's draft or archived contribution, linked
                   either to a solo submission or to a ``ToolSession``.
``WaitingListEntry`` — legacy records retained after the collection feature was retired.
``FeatureRequest``   — feature ideas submitted from the public request page.
``AuditLog``         — append-only log of security-relevant user actions.
"""
import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.timezone import now


class ToolSession(models.Model):
    """A collaborative session of a tool, hosted by one user.

    Other logged-in users join via the session's URL. Each participant's
    contribution is captured as its own ``ToolInstance`` linked back to the
    session. Closing the session locks every contribution and triggers the
    tool's processing logic so a combined view can be shown.
    """

    STATUS_CHOICES = [
        ('open', 'Open'),
        ('closed', 'Closed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    host = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='hosted_sessions',
    )
    data_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='owned_sessions',
        null=True,
        blank=True,
        help_text='Retention owner; host attribution is kept separately.',
    )
    tool_slug = models.CharField(max_length=100)
    tool_version = models.CharField(max_length=20)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='open')
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    timer_started_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Set when the host starts the phase timer so all clients stay in sync.',
    )
    timer_paused_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Set when the host pauses the timer; cleared on resume or reset.',
    )
    timer_elapsed_before_pause = models.FloatField(
        default=0,
        help_text='Cumulative elapsed seconds before the current (or last) pause.',
    )
    pause_reminder_threshold_sec = models.IntegerField(
        default=300,
        null=True,
        blank=True,
        help_text=(
            'How many seconds of pause before a long-pause reminder appears. '
            'Null disables the reminder entirely. Default is 300 (5 minutes).'
        ),
    )

    inclusive_pacing = models.BooleanField(
        default=False,
        help_text=(
            'When true, participants see an option to activate a personal '
            'extended countdown at inclusive_pacing_multiplier × the group time.'
        ),
    )
    inclusive_pacing_multiplier = models.IntegerField(
        default=3,
        choices=[(3, '3×'), (5, '5×')],
        help_text='Time multiplier offered to participants when inclusive pacing is active.',
    )

    verbal_breakout_active = models.BooleanField(
        default=False,
        help_text=(
            'When true, the host has signalled the room to start a verbal '
            'breakout. Non-composing participants are prompted to join the '
            'discussion; AAC-composing participants are reassured their '
            'digital submission window remains open.'
        ),
    )

    guest_token = models.UUIDField(
        default=uuid.uuid4,
        help_text=(
            'Token embedded in the guest QR code URL. '
            'Anyone with this token can join as an unauthenticated guest.'
        ),
    )

    pairing_code = models.CharField(
        max_length=3,
        blank=True,
        db_index=True,
        help_text=(
            'Three-digit companion-pairing code displayed alongside the QR code. '
            'Valid while the session is open; cleared on close.'
        ),
    )

    md_file = models.FileField(upload_to='archives/md/', null=True, blank=True, max_length=500)
    rtf_file = models.FileField(upload_to='archives/rtf/', null=True, blank=True, max_length=500)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.tool_slug} session ({self.status}) hosted by {self.host}'


class ToolInstance(models.Model):
    """A user-scoped record of a tool draft / submission.

    ``user`` is nullable to support guest participants who join a session via
    the QR-code guest link without creating an account.  For guest instances
    ``guest_name`` holds the name the participant entered on the join page.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='tool_instances',
        null=True,
        blank=True,
        help_text='Null for unauthenticated guest participants.',
    )
    data_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='owned_tool_instances',
        null=True,
        blank=True,
        help_text='Retention owner; creator attribution is kept separately.',
    )
    guest_name = models.CharField(
        max_length=100,
        blank=True,
        help_text='Display name entered by a guest participant (user is null).',
    )

    session = models.ForeignKey(
        ToolSession,
        on_delete=models.CASCADE,
        related_name='instances',
        null=True,
        blank=True,
        help_text='Set when this instance is part of a collaborative session.',
    )

    tool_slug = models.CharField(max_length=100)
    tool_version = models.CharField(max_length=20)

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('archived', 'Archived'),
    ]
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')

    payload_input = models.JSONField(default=dict, help_text='The raw user inputs.')
    payload_output = models.JSONField(
        default=dict, null=True, blank=True, help_text="The tool's result."
    )

    html_file = models.FileField(upload_to='archives/html/', null=True, blank=True, max_length=500)
    md_file = models.FileField(upload_to='archives/md/', null=True, blank=True, max_length=500)
    rtf_file = models.FileField(upload_to='archives/rtf/', null=True, blank=True, max_length=500)

    attachments = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            'Multimedia attachments added by this participant (audio clips, '
            'symbol-board images, etc.). Each entry is a dict with keys: '
            'type ("audio" | "image"), url (Cloudinary secure_url), '
            'public_id, name.'
        ),
    )

    composing_heartbeat_at = models.DateTimeField(
        null=True, blank=True,
        help_text=(
            'Set by session_mark_composing when an AAC user signals they are '
            'composing in external software. Expires after 15 seconds of inactivity.'
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-updated_at']
        constraints = [
            models.UniqueConstraint(
                fields=['session', 'user'],
                name='unique_session_user_instance',
                condition=models.Q(session__isnull=False),
            ),
        ]

    def __str__(self):
        identity = self.user if self.user_id else (self.guest_name or 'Guest')
        return f'{identity} - {self.tool_slug} ({self.status})'

    def archive_record(self):
        """Transition this draft to 'archived' status.

        Convenience method for direct use in views or management commands.
        The session-close flow (``session_close`` view) bypasses this method
        and sets fields directly for performance, since it processes many
        instances in a single transaction.
        """
        if self.status == 'draft':
            self.status = 'archived'
            self.submitted_at = now()
            self.save()


class WaitingListEntry(models.Model):
    """Historical signup records retained without an active collection UI."""

    email = models.EmailField(unique=True)
    name = models.CharField(
        max_length=200, blank=True,
        help_text='Optional — filled in voluntarily by the visitor.',
    )
    signed_up_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-signed_up_at']
        verbose_name = 'Waiting list entry'
        verbose_name_plural = 'Waiting list entries'

    def __str__(self):
        return self.email


class FeatureRequest(models.Model):
    """Feedback submitted through the public and contextual feedback forms.

    The historical name is retained deliberately so existing database rows and
    integrations continue to work.
    """

    FEEDBACK_TYPES = [
        ('feature', 'Feature request'),
        ('bug', 'Bug report'),
        ('experience', 'Experience feedback'),
        ('rating', 'Rating'),
    ]
    REVIEW_STATUSES = [
        ('new', 'New'),
        ('reviewing', 'Reviewing'),
        ('planned', 'Planned'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
    ]
    SOURCES = [
        ('portal', 'Feedback portal'),
        ('tool_completion', 'Tool completion'),
        ('session_end', 'Session end'),
        ('knowledge_bank', 'Knowledge Bank'),
    ]
    INTERACTION_MODES = [
        ('try', 'Try tool'),
        ('solo', 'Solo'),
        ('session', 'Session'),
        ('guest', 'Guest'),
    ]

    name = models.CharField(
        max_length=200, blank=True,
        help_text='Optional — filled in voluntarily by the visitor.',
    )
    email = models.EmailField(
        blank=True,
        help_text='Optional — so they can be notified when the feature ships.',
    )
    title = models.CharField(
        max_length=300,
        blank=True,
        help_text='A short summary of the feature being requested.',
    )
    description = models.TextField(
        blank=True,
        help_text='More detail: what problem does it solve, how would it work?',
    )
    feedback_type = models.CharField(
        max_length=20, choices=FEEDBACK_TYPES, default='feature', db_index=True,
    )
    rating = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    review_status = models.CharField(
        max_length=20, choices=REVIEW_STATUSES, default='new', db_index=True,
    )
    source = models.CharField(
        max_length=20, choices=SOURCES, default='portal', db_index=True,
    )
    tool_slug = models.SlugField(max_length=100, null=True, blank=True)
    interaction_mode = models.CharField(
        max_length=20, choices=INTERACTION_MODES, null=True, blank=True,
    )
    submitter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='submitted_feedback',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-submitted_at']
        verbose_name = 'Feedback'
        verbose_name_plural = 'Feedback'
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(rating__isnull=True)
                    | models.Q(rating__gte=1, rating__lte=5)
                ),
                name='feedback_rating_between_1_and_5',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(feedback_type='rating', rating__isnull=False)
                    | (
                        ~models.Q(feedback_type='rating')
                        & models.Q(rating__isnull=True)
                    )
                ),
                name='feedback_rating_matches_type',
            ),
        ]

    def __str__(self):
        if self.title:
            return self.title
        if self.rating:
            return f'Usefulness rating: {self.rating}/5'
        return self.get_feedback_type_display()


class AuditLog(models.Model):
    """Append-only security log for significant user actions.

    Rows are never updated after creation.  New entries are created
    exclusively via ``accounts.utils.log_action``; direct ``AuditLog.objects.create``
    calls are used only in ``accounts.signals`` to avoid an import of
    ``log_action`` from within the ``archive`` app itself.
    """

    # When each action is recorded:
    #   'login'        — by the user_logged_in signal in accounts/signals.py
    #   'submit'       — not currently triggered (reserved for future use)
    #   'download'     — by secure_download and secure_session_download in views_downloads.py
    #   'access_denied'— not currently triggered (reserved for future use)
    ACTION_CHOICES = [
        ('login', 'User Login'),
        ('submit', 'Tool Submission'),
        ('download', 'File Download'),
        ('access_denied', 'Unauthorized Access Attempt'),
        ('organisation_transfer_requested', 'Organisation Data Transfer Requested'),
        ('organisation_transfer_accepted', 'Organisation Data Transfer Accepted'),
        ('organisation_transfer_declined', 'Organisation Data Transfer Declined'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    action = models.CharField(max_length=40, choices=ACTION_CHOICES)
    resource_id = models.CharField(max_length=100, null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f'{self.action} @ {self.timestamp:%Y-%m-%d %H:%M}'
