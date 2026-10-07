"""Services and access helpers for Organisation member-data retention.

The billing relationship on ``User`` remains the source of truth for team
membership.  These functions add explicit, consented retention ownership
without changing a record's creator or session host.
"""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import OrganisationDataTransferRequest, OrganisationMemberDataPolicy
from accounts.utils import log_action


class OrganisationDataOwnershipError(ValidationError):
    """Raised when a requested ownership transition is not valid."""


def _active_organisation_owner(owner):
    return (
        owner.plan == 'organisation'
        and owner.has_paid_access
        and owner.organisation_owner_id is None
    )


def validate_member_for_data_policy(owner, member):
    """Validate that an owner may propose a policy for this included member."""
    if owner.pk == member.pk:
        raise OrganisationDataOwnershipError('An owner cannot request a policy for themselves.')
    if not _active_organisation_owner(owner):
        raise OrganisationDataOwnershipError('The organisation owner does not have active access.')
    if not owner.email_domain or owner.email_domain != member.email_domain:
        raise OrganisationDataOwnershipError('Organisation members must share the owner email domain.')
    if member.organisation_owner_id != owner.pk:
        raise OrganisationDataOwnershipError('The member is not linked to this organisation owner.')
    if (
        member.stripe_subscription_id
        or member.stripe_customer_id
        or (
            member.plan in {'solo', 'organisation'}
            and member.subscription_status in {'active', 'trialing'}
        )
    ):
        raise OrganisationDataOwnershipError(
            'An independently subscribed account cannot be taken over.'
        )


def _validate_target_policy(target_policy):
    valid = dict(OrganisationMemberDataPolicy.OWNERSHIP_CHOICES)
    if target_policy not in valid:
        raise OrganisationDataOwnershipError('Unknown data retention policy.')


@transaction.atomic
def create_transfer_request(owner, member, target_policy):
    """Create a consent request, cancelling any prior pending request.

    Locking the member serializes competing owner actions and complements the
    partial unique constraint on pending requests.
    """
    from accounts.models import User

    member = User.objects.select_for_update().get(pk=member.pk)
    owner = User.objects.select_for_update().get(pk=owner.pk)
    _validate_target_policy(target_policy)
    validate_member_for_data_policy(owner, member)
    OrganisationDataTransferRequest.objects.filter(
        member=member, status=OrganisationDataTransferRequest.PENDING,
    ).update(status=OrganisationDataTransferRequest.CANCELLED, resolved_at=timezone.now())
    request = OrganisationDataTransferRequest.objects.create(
        owner=owner, member=member, target_policy=target_policy,
    )
    log_action(
        owner,
        'organisation_transfer_requested',
        resource_id=request.pk,
        metadata={'member_id': member.pk, 'target_policy': target_policy},
    )
    return request


@transaction.atomic
def resolve_transfer_request(member, request, accepted):
    """Accept or decline a request as its intended member.

    Acceptance moves only the member's solo records and sessions that they
    host.  Participant contributions in other hosts' sessions are untouched.
    """
    from accounts.models import User
    from archive.models import ToolInstance, ToolSession

    member = User.objects.select_for_update().get(pk=member.pk)
    request = OrganisationDataTransferRequest.objects.select_for_update().get(pk=request.pk)
    if request.member_id != member.pk:
        raise PermissionDenied('Only the requested member may respond.')
    if request.status != OrganisationDataTransferRequest.PENDING:
        raise OrganisationDataOwnershipError('This transfer request is no longer pending.')

    owner = User.objects.select_for_update().get(pk=request.owner_id)
    validate_member_for_data_policy(owner, member)
    resolved_at = timezone.now()
    if not accepted:
        request.status = OrganisationDataTransferRequest.DECLINED
        request.resolved_at = resolved_at
        request.save(update_fields=['status', 'resolved_at'])
        log_action(
            member, 'organisation_transfer_declined', resource_id=request.pk,
            metadata={'owner_id': owner.pk, 'target_policy': request.target_policy},
        )
        return request

    policy, _ = OrganisationMemberDataPolicy.objects.update_or_create(
        member=member,
        defaults={'owner': owner, 'policy': request.target_policy, 'active': True},
    )
    # Member-owned consent controls future records only.  Do not use it to
    # reverse historical organisation transfers.
    solo_count = session_count = 0
    if request.target_policy == OrganisationMemberDataPolicy.ORGANISATION_OWNED:
        solo_count = ToolInstance.objects.filter(
            user=member, session__isnull=True,
        ).filter(
            Q(data_owner__isnull=True) | Q(data_owner=member),
        ).update(data_owner=owner)
        session_count = ToolSession.objects.filter(host=member).filter(
            Q(data_owner__isnull=True) | Q(data_owner=member),
        ).update(data_owner=owner)

    request.status = OrganisationDataTransferRequest.ACCEPTED
    request.resolved_at = resolved_at
    request.transferred_solo_count = solo_count
    request.transferred_session_count = session_count
    request.save(update_fields=[
        'status', 'resolved_at', 'transferred_solo_count', 'transferred_session_count',
    ])
    log_action(
        member, 'organisation_transfer_accepted', resource_id=request.pk,
        metadata={
            'owner_id': owner.pk,
            'target_policy': policy.policy,
            'solo_count': solo_count,
            'session_count': session_count,
        },
    )
    return request


def accept_transfer_request(member, request):
    return resolve_transfer_request(member, request, accepted=True)


def decline_transfer_request(member, request):
    return resolve_transfer_request(member, request, accepted=False)


def future_data_owner(member):
    """Return the effective owner for new work, preserving member by default."""
    policy = (
        OrganisationMemberDataPolicy.objects.select_related('owner')
        .filter(
            member=member,
            owner_id=member.organisation_owner_id,
            active=True,
            policy=OrganisationMemberDataPolicy.ORGANISATION_OWNED,
        )
        .first()
    )
    if policy and _active_organisation_owner(policy.owner):
        return policy.owner
    return member


@transaction.atomic
def create_owned_solo_record(member, **fields):
    """Create solo work while serialized with policy acceptance."""
    from accounts.models import User
    from archive.models import ToolInstance

    locked_member = User.objects.select_for_update().get(pk=member.pk)
    return ToolInstance.objects.create(
        user=locked_member,
        data_owner=future_data_owner(locked_member),
        **fields,
    )


@transaction.atomic
def create_owned_session(member, **fields):
    """Create a hosted session while serialized with policy acceptance."""
    from accounts.models import User
    from archive.models import ToolSession

    locked_member = User.objects.select_for_update().get(pk=member.pk)
    return ToolSession.objects.create(
        host=locked_member,
        data_owner=future_data_owner(locked_member),
        **fields,
    )


def solo_record_access_q(user):
    """A Q predicate for solo records the user may see or manage."""
    predicate = Q(data_owner=user) | Q(user=user, data_owner__isnull=True)
    owner = getattr(user, 'organisation_owner', None)
    if owner and _active_organisation_owner(owner):
        predicate |= Q(
            user=user,
            data_owner=owner,
            user__organisation_data_policy__owner=owner,
            user__organisation_data_policy__active=True,
            user__organisation_data_policy__policy=OrganisationMemberDataPolicy.ORGANISATION_OWNED,
        )
    return predicate


def session_access_q(user):
    """A Q predicate for sessions the user may see or manage."""
    predicate = Q(data_owner=user) | Q(host=user, data_owner__isnull=True)
    owner = getattr(user, 'organisation_owner', None)
    if owner and _active_organisation_owner(owner):
        predicate |= Q(
            host=user,
            data_owner=owner,
            host__organisation_data_policy__owner=owner,
            host__organisation_data_policy__active=True,
            host__organisation_data_policy__policy=OrganisationMemberDataPolicy.ORGANISATION_OWNED,
        )
    return predicate


def solo_record_management_q(user):
    """Records this user owns and may permanently delete."""
    return Q(data_owner=user) | Q(user=user, data_owner__isnull=True)


def session_management_q(user):
    """Sessions this user owns and may permanently delete."""
    return Q(data_owner=user) | Q(host=user, data_owner__isnull=True)


def solo_records_for_user(user):
    from archive.models import ToolInstance
    return ToolInstance.objects.filter(session__isnull=True).filter(solo_record_access_q(user))


def sessions_for_user(user):
    from archive.models import ToolSession
    return ToolSession.objects.filter(session_access_q(user))