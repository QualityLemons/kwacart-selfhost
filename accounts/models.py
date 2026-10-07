"""Custom user model using email as the unique login identifier.

Django's default ``User`` requires a ``username``; this module replaces it
with an ``AbstractUser`` subclass where ``email`` is the ``USERNAME_FIELD``
and ``username`` is removed entirely.  A matching ``UserManager`` handles
account creation via ``create_user`` and ``create_superuser``.
"""
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.contrib.auth.password_validation import validate_password
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class UserManager(BaseUserManager):
    """Custom manager required because this project uses email as the unique
    identifier instead of a username.  Django's default manager calls
    ``_create_user`` with a ``username`` argument; this override removes that
    requirement and normalises the email address before saving.
    """

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError('Users must have an email address.')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        if password is not None:
            # Pass the user object so validators that inspect user attributes
            # (e.g. the similarity-to-name validator) have something to check against.
            validate_password(password, user)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        extra_fields.setdefault('plan', 'free')
        extra_fields.setdefault('subscription_status', 'none')
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        # setdefault only sets the value when the key is absent.  A caller who
        # explicitly passes is_staff=False or is_superuser=False would bypass
        # setdefault above, so these guards catch that misconfiguration.
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Custom user model that uses email as the unique identifier."""

    PLAN_CHOICES = [
        ('free', 'Free'),
        ('solo', 'Solo'),
        ('organisation', 'Organisation'),
    ]
    SUBSCRIPTION_STATUS_CHOICES = [
        ('none', 'No subscription'),
        ('active', 'Active'),
        ('trialing', 'Trialing'),
        ('past_due', 'Payment past due'),
        ('unpaid', 'Payment failed'),
        ('incomplete', 'Payment incomplete'),
        ('incomplete_expired', 'Payment incomplete and expired'),
        ('canceled', 'Canceled'),
    ]

    email = models.EmailField(unique=True)
    username = models.CharField(max_length=150, unique=False, blank=True, null=True)
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default='free')
    subscription_status = models.CharField(
        max_length=30, choices=SUBSCRIPTION_STATUS_CHOICES, default='none',
    )
    billing_interval = models.CharField(
        max_length=10, choices=[('month', 'Monthly'), ('year', 'Annual')],
        blank=True,
    )
    stripe_customer_id = models.CharField(max_length=100, blank=True, null=True, unique=True)
    stripe_subscription_id = models.CharField(max_length=100, blank=True, null=True, unique=True)
    stripe_price_id = models.CharField(max_length=100, blank=True, null=True)
    subscription_current_period_end = models.DateTimeField(null=True, blank=True)
    subscription_cancel_at_period_end = models.BooleanField(default=False)
    stripe_event_created = models.BigIntegerField(default=0)
    organisation_owner = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='organisation_members',
        help_text='The paid Organisation account that provides access to this member.',
    )

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = UserManager()

    @property
    def email_domain(self):
        """Return the normalised domain used for Organisation membership."""
        return self.email.rsplit('@', 1)[-1].lower() if '@' in self.email else ''

    @property
    def billing_account(self):
        """Return the user whose subscription controls this account."""
        return self.organisation_owner or self

    @property
    def has_paid_access(self):
        """Whether this user can use the paid KwaCart workspace."""
        if not settings.BILLING_ENABLED:
            return self.is_active
        account = self.billing_account
        return (
            account.plan in {'solo', 'organisation'}
            and account.subscription_status in {'active', 'trialing'}
        )

    @property
    def effective_plan(self):
        """Return the plan visible to this user, including Organisation members."""
        return self.billing_account.plan if self.has_paid_access else 'free'

    def link_organisation_members(self):
        """Link same-domain users to this active Organisation account.

        This intentionally only links existing accounts and never changes a
        user's own paid subscription.  New registrations call this method too,
        so members receive access without a per-user Stripe subscription.
        """
        if self.plan != 'organisation' or not self.has_paid_access or not self.email_domain:
            return 0
        return User.objects.filter(
            organisation_owner__isnull=True,
            plan='free',
            subscription_status='none',
            stripe_subscription_id__isnull=True,
        ).exclude(pk=self.pk).filter(
            email__iendswith=f'@{self.email_domain}',
        ).update(organisation_owner=self)

    def unlink_organisation_members(self):
        """End current team links and invalidate consent tied to this link."""
        member_ids = list(
            self.organisation_members.values_list('pk', flat=True)
        )
        if not member_ids:
            return 0
        OrganisationMemberDataPolicy.objects.filter(
            owner=self,
            member_id__in=member_ids,
            active=True,
        ).update(active=False)
        OrganisationDataTransferRequest.objects.filter(
            owner=self,
            member_id__in=member_ids,
            status=OrganisationDataTransferRequest.PENDING,
        ).update(
            status=OrganisationDataTransferRequest.CANCELLED,
            resolved_at=timezone.now(),
        )
        return User.objects.filter(pk__in=member_ids).update(
            organisation_owner=None,
        )

    def unlink_from_organisation(self):
        """End this member's current team link and invalidate its consent."""
        owner_id = self.organisation_owner_id
        if not owner_id:
            return False
        OrganisationMemberDataPolicy.objects.filter(
            owner_id=owner_id,
            member=self,
            active=True,
        ).update(active=False)
        OrganisationDataTransferRequest.objects.filter(
            owner_id=owner_id,
            member=self,
            status=OrganisationDataTransferRequest.PENDING,
        ).update(
            status=OrganisationDataTransferRequest.CANCELLED,
            resolved_at=timezone.now(),
        )
        self.organisation_owner = None
        self.save(update_fields=['organisation_owner'])
        return True

    def __str__(self):
        return self.email


class OrganisationMemberDataPolicy(models.Model):
    """The current retention policy for one Organisation member.

    This is intentionally distinct from ``User.organisation_owner``: the
    latter grants subscription access, while this model controls where new
    work is retained.
    """

    MEMBER_OWNED = 'member'
    ORGANISATION_OWNED = 'organisation'
    OWNERSHIP_CHOICES = [
        (MEMBER_OWNED, 'Keep with member'),
        (ORGANISATION_OWNED, 'Retain in organisation account'),
    ]

    owner = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='member_data_policies',
    )
    member = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='organisation_data_policy',
    )
    policy = models.CharField(
        max_length=20, choices=OWNERSHIP_CHOICES, default=MEMBER_OWNED,
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~Q(owner=models.F('member')),
                name='organisation_policy_owner_not_member',
            ),
        ]

    def __str__(self):
        return f'{self.member} retained by {self.get_policy_display()}'


class OrganisationDataTransferRequest(models.Model):
    """A durable consent record for a proposed member-data retention change."""

    PENDING = 'pending'
    ACCEPTED = 'accepted'
    DECLINED = 'declined'
    CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (PENDING, 'Pending'),
        (ACCEPTED, 'Accepted'),
        (DECLINED, 'Declined'),
        (CANCELLED, 'Cancelled'),
    ]

    owner = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='sent_data_transfer_requests',
    )
    member = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='received_data_transfer_requests',
    )
    target_policy = models.CharField(
        max_length=20, choices=OrganisationMemberDataPolicy.OWNERSHIP_CHOICES,
    )
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=PENDING)
    requested_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    transferred_solo_count = models.PositiveIntegerField(default=0)
    transferred_session_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-requested_at']
        constraints = [
            models.CheckConstraint(
                condition=~Q(owner=models.F('member')),
                name='organisation_transfer_owner_not_member',
            ),
            models.UniqueConstraint(
                fields=['member'],
                condition=Q(status='pending'),
                name='one_pending_organisation_transfer_per_member',
            ),
        ]

    def __str__(self):
        return (
            f'{self.get_target_policy_display()} request for {self.member} '
            f'({self.status})'
        )


class RequestRateLimit(models.Model):
    """Shared request throttle state for public endpoints.

    Keys are one-way hashes of a scope and network address, so the table does
    not retain raw visitor IP addresses.
    """

    key = models.CharField(max_length=64, unique=True)
    window_started = models.DateTimeField(default=timezone.now)
    attempts = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Request rate limit'
        verbose_name_plural = 'Request rate limits'
