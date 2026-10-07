import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models.query import QuerySet
from django.test import TestCase
from django.urls import reverse

from accounts.models import OrganisationDataTransferRequest, OrganisationMemberDataPolicy
from accounts.organisation_data_ownership import (
    accept_transfer_request,
    create_transfer_request,
    decline_transfer_request,
    future_data_owner,
    sessions_for_user,
    solo_records_for_user,
)
from archive.models import ToolInstance, ToolSession


User = get_user_model()


class OrganisationDataOwnershipServiceTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            'owner@team.example', 'Correct-horse-battery-staple-1!',
            plan='organisation', subscription_status='active',
        )
        self.member = User.objects.create_user(
            'member@team.example', 'Correct-horse-battery-staple-1!',
            organisation_owner=self.owner, plan='free', subscription_status='none',
        )

    def request(self, policy=OrganisationMemberDataPolicy.ORGANISATION_OWNED):
        return create_transfer_request(self.owner, self.member, policy)

    def test_replaces_pending_request_and_keeps_history(self):
        first = self.request()
        second = self.request(OrganisationMemberDataPolicy.MEMBER_OWNED)
        first.refresh_from_db()
        self.assertEqual(first.status, OrganisationDataTransferRequest.CANCELLED)
        self.assertEqual(second.status, OrganisationDataTransferRequest.PENDING)
        self.assertEqual(
            OrganisationDataTransferRequest.objects.filter(status='pending').count(), 1
        )

    def test_rejects_self_cross_domain_and_independent_accounts(self):
        with self.assertRaises(ValidationError):
            create_transfer_request(self.owner, self.owner, 'organisation')
        outsider = User.objects.create_user(
            'person@other.example', 'Correct-horse-battery-staple-1!',
            organisation_owner=self.owner, plan='free', subscription_status='none',
        )
        with self.assertRaises(ValidationError):
            create_transfer_request(self.owner, outsider, 'organisation')
        self.member.stripe_subscription_id = 'sub_independent'
        self.member.save(update_fields=['stripe_subscription_id'])
        with self.assertRaises(ValidationError):
            self.request()

    def test_only_member_can_respond_and_decline_does_not_transfer(self):
        request = self.request()
        other = User.objects.create_user(
            'other@team.example', 'Correct-horse-battery-staple-1!',
        )
        with self.assertRaises(PermissionDenied):
            accept_transfer_request(other, request)
        solo = ToolInstance.objects.create(user=self.member, tool_slug='test', tool_version='1')
        decline_transfer_request(self.member, request)
        request.refresh_from_db()
        solo.refresh_from_db()
        self.assertEqual(request.status, OrganisationDataTransferRequest.DECLINED)
        self.assertIsNone(solo.data_owner)

    def test_acceptance_transfers_only_solo_and_member_hosted_work(self):
        solo = ToolInstance.objects.create(user=self.member, tool_slug='solo', tool_version='1')
        hosted = ToolSession.objects.create(host=self.member, tool_slug='hosted', tool_version='1')
        other = User.objects.create_user('other@team.example', 'Correct-horse-battery-staple-1!')
        others_session = ToolSession.objects.create(host=other, tool_slug='other', tool_version='1')
        contribution = ToolInstance.objects.create(
            user=self.member, session=others_session, tool_slug='joined', tool_version='1',
        )
        request = self.request()
        accept_transfer_request(self.member, request)
        solo.refresh_from_db()
        hosted.refresh_from_db()
        contribution.refresh_from_db()
        request.refresh_from_db()
        self.assertEqual(solo.data_owner, self.owner)
        self.assertEqual(hosted.data_owner, self.owner)
        self.assertIsNone(contribution.data_owner)
        self.assertEqual((request.transferred_solo_count, request.transferred_session_count), (1, 1))

    def test_member_owned_is_future_only_and_unlink_disables_future_policy_access(self):
        request = self.request(OrganisationMemberDataPolicy.MEMBER_OWNED)
        accept_transfer_request(self.member, request)
        self.assertEqual(future_data_owner(self.member), self.member)
        org_request = self.request()
        accept_transfer_request(self.member, org_request)
        solo = ToolInstance.objects.create(
            user=self.member, data_owner=self.owner, tool_slug='new', tool_version='1',
        )
        self.assertIn(solo, solo_records_for_user(self.member))
        self.member.organisation_owner = None
        self.member.save(update_fields=['organisation_owner'])
        self.member.refresh_from_db()
        self.assertEqual(future_data_owner(self.member), self.member)
        self.assertNotIn(solo, solo_records_for_user(self.member))
        self.assertIn(solo, solo_records_for_user(self.owner))
        self.assertFalse(sessions_for_user(self.member).filter(data_owner=self.owner).exists())

    def test_acceptance_does_not_retransfer_work_owned_by_another_organisation(self):
        previous_owner = User.objects.create_user(
            'previous@team.example', 'Correct-horse-battery-staple-1!',
            plan='organisation', subscription_status='active',
        )
        retained = ToolInstance.objects.create(
            user=self.member,
            data_owner=previous_owner,
            tool_slug='retained',
            tool_version='1',
        )
        request = self.request()

        accept_transfer_request(self.member, request)

        retained.refresh_from_db()
        self.assertEqual(retained.data_owner, previous_owner)
        request.refresh_from_db()
        self.assertEqual(request.transferred_solo_count, 0)

    def test_transfer_rolls_back_atomically_if_session_update_fails(self):
        solo = ToolInstance.objects.create(
            user=self.member, tool_slug='solo', tool_version='1',
        )
        request = self.request()
        original_update = QuerySet.update

        def fail_session_update(queryset, **kwargs):
            if queryset.model is ToolSession:
                raise RuntimeError('simulated session update failure')
            return original_update(queryset, **kwargs)

        with patch.object(QuerySet, 'update', new=fail_session_update):
            with self.assertRaises(RuntimeError):
                accept_transfer_request(self.member, request)

        solo.refresh_from_db()
        request.refresh_from_db()
        self.assertIsNone(solo.data_owner)
        self.assertEqual(request.status, OrganisationDataTransferRequest.PENDING)
        self.assertFalse(
            OrganisationMemberDataPolicy.objects.filter(member=self.member).exists()
        )

    def test_unlink_and_relink_requires_fresh_member_consent(self):
        request = self.request()
        accept_transfer_request(self.member, request)
        self.assertEqual(future_data_owner(self.member), self.owner)

        self.owner.unlink_organisation_members()
        policy = OrganisationMemberDataPolicy.objects.get(member=self.member)
        self.assertFalse(policy.active)
        self.owner.link_organisation_members()
        self.member.refresh_from_db()

        self.assertEqual(self.member.organisation_owner, self.owner)
        self.assertEqual(future_data_owner(self.member), self.member)

    def test_unlink_cancels_an_unresolved_request(self):
        request = self.request()

        self.owner.unlink_organisation_members()

        request.refresh_from_db()
        self.assertEqual(request.status, OrganisationDataTransferRequest.CANCELLED)
        self.assertIsNotNone(request.resolved_at)


class OrganisationDataOwnershipViewTests(TestCase):
    def setUp(self):
        self.password = 'Correct-horse-battery-staple-1!'
        self.owner = User.objects.create_user(
            'owner@team.example',
            self.password,
            plan='organisation',
            subscription_status='active',
        )
        self.member = User.objects.create_user(
            'member@team.example',
            self.password,
            organisation_owner=self.owner,
            plan='free',
            subscription_status='none',
        )

    def send_request(self, policy='organisation'):
        self.client.force_login(self.owner)
        return self.client.post(
            reverse('accounts:organisation_data_policy_request'),
            {'team-email': self.member.email, 'team-policy': policy},
        )

    def accept_request(self):
        transfer = OrganisationDataTransferRequest.objects.get(status='pending')
        self.client.force_login(self.member)
        response = self.client.post(
            reverse(
                'accounts:organisation_data_policy_response',
                args=[transfer.pk],
            ),
            {'action': 'accept'},
        )
        return transfer, response

    def test_owner_can_propose_and_member_can_review_policy(self):
        response = self.send_request()
        self.assertRedirects(response, reverse('accounts:profile'))
        transfer = OrganisationDataTransferRequest.objects.get()
        self.assertEqual(transfer.member, self.member)
        self.assertEqual(transfer.status, 'pending')

        self.client.force_login(self.member)
        profile = self.client.get(reverse('accounts:profile'))
        self.assertContains(profile, 'A data-retention request needs your decision')
        self.assertContains(profile, 'Your contributions in other people’s')
        self.assertContains(profile, reverse(
            'accounts:organisation_data_policy_response', args=[transfer.pk],
        ))

    def test_owner_can_add_an_unlinked_same_domain_account(self):
        self.member.organisation_owner = None
        self.member.save(update_fields=['organisation_owner'])

        self.send_request('member')

        self.member.refresh_from_db()
        self.assertEqual(self.member.organisation_owner, self.owner)
        self.assertTrue(
            OrganisationDataTransferRequest.objects.filter(
                member=self.member, target_policy='member', status='pending',
            ).exists()
        )

    def test_cross_domain_and_non_owner_requests_fail_safely(self):
        outsider = User.objects.create_user(
            'outsider@other.example',
            self.password,
            plan='free',
            subscription_status='none',
        )
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse('accounts:organisation_data_policy_request'),
            {'team-email': outsider.email, 'team-policy': 'organisation'},
        )
        self.assertRedirects(response, reverse('accounts:profile'))
        outsider.refresh_from_db()
        self.assertIsNone(outsider.organisation_owner)
        self.assertFalse(
            OrganisationDataTransferRequest.objects.filter(member=outsider).exists()
        )

        self.client.force_login(self.member)
        denied = self.client.post(
            reverse('accounts:organisation_data_policy_request'),
            {'team-email': outsider.email, 'team-policy': 'organisation'},
        )
        self.assertEqual(denied.status_code, 403)

    def test_other_user_cannot_respond_to_request(self):
        self.send_request()
        transfer = OrganisationDataTransferRequest.objects.get()
        other = User.objects.create_user('other@team.example', self.password)
        self.client.force_login(other)

        response = self.client.post(
            reverse(
                'accounts:organisation_data_policy_response',
                args=[transfer.pk],
            ),
            {'action': 'accept'},
        )

        self.assertEqual(response.status_code, 404)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, 'pending')

    def test_acceptance_transfers_archive_access_and_future_work(self):
        solo = ToolInstance.objects.create(
            user=self.member,
            tool_slug='min-specs',
            tool_version='1.0',
            status='archived',
        )
        solo.md_file.save('member.md', ContentFile(b'# Member work'), save=True)
        hosted = ToolSession.objects.create(
            host=self.member,
            tool_slug='min-specs',
            tool_version='1.0',
            status='closed',
        )
        self.send_request()
        transfer, response = self.accept_request()
        self.assertRedirects(response, reverse('accounts:profile'))
        transfer.refresh_from_db()
        self.assertEqual(
            (transfer.transferred_solo_count, transfer.transferred_session_count),
            (1, 1),
        )

        self.client.force_login(self.owner)
        knowledge_bank = self.client.get(reverse('archive:knowledge_bank'))
        self.assertContains(knowledge_bank, 'Min Specs')
        detail = self.client.get(reverse('archive:detail', args=[solo.pk]))
        self.assertEqual(detail.status_code, 200)
        download = self.client.get(
            reverse('archive:download', args=[solo.pk, 'md']),
        )
        self.assertEqual(download.status_code, 200)
        session_page = self.client.get(
            reverse('tools:session_detail', args=[hosted.pk]),
        )
        self.assertEqual(session_page.status_code, 200)

        self.client.force_login(self.member)
        created = self.client.post(
            reverse('tools:session_create', args=['min-specs']),
        )
        self.assertEqual(created.status_code, 302)
        self.assertEqual(
            ToolSession.objects.exclude(pk=hosted.pk).get().data_owner,
            self.owner,
        )
        autosaved = self.client.post(
            reverse('tools:autosave', args=['min-specs']),
            data=json.dumps({'form_data': {}}),
            content_type='application/json',
        )
        self.assertEqual(autosaved.status_code, 200)
        new_instance = ToolInstance.objects.get(pk=autosaved.json()['instance_id'])
        self.assertEqual(new_instance.user, self.member)
        self.assertEqual(new_instance.data_owner, self.owner)

    def test_member_cannot_delete_account_while_retained_work_needs_attribution(self):
        ToolInstance.objects.create(
            user=self.member,
            data_owner=self.owner,
            tool_slug='min-specs',
            tool_version='1.0',
        )
        self.client.force_login(self.member)

        response = self.client.post(
            reverse('accounts:delete'),
            {'confirm': 'DELETE'},
        )

        self.assertRedirects(response, reverse('accounts:profile'))
        self.assertTrue(User.objects.filter(pk=self.member.pk).exists())

    def test_member_cannot_delete_organisation_owned_record_or_session(self):
        solo = ToolInstance.objects.create(
            user=self.member,
            data_owner=self.owner,
            tool_slug='min-specs',
            tool_version='1.0',
        )
        session = ToolSession.objects.create(
            host=self.member,
            data_owner=self.owner,
            tool_slug='min-specs',
            tool_version='1.0',
            status='closed',
        )
        self.client.force_login(self.member)

        solo_response = self.client.post(
            reverse('archive:delete', args=[solo.pk]),
        )
        session_response = self.client.post(
            reverse('tools:session_delete', args=[session.pk]),
        )

        self.assertEqual(solo_response.status_code, 404)
        self.assertEqual(session_response.status_code, 404)
        self.assertTrue(ToolInstance.objects.filter(pk=solo.pk).exists())
        self.assertTrue(ToolSession.objects.filter(pk=session.pk).exists())

    def test_organisation_owner_can_delete_retained_record_and_session(self):
        solo = ToolInstance.objects.create(
            user=self.member,
            data_owner=self.owner,
            tool_slug='min-specs',
            tool_version='1.0',
        )
        session = ToolSession.objects.create(
            host=self.member,
            data_owner=self.owner,
            tool_slug='min-specs',
            tool_version='1.0',
            status='closed',
        )
        self.client.force_login(self.owner)

        solo_response = self.client.post(
            reverse('archive:delete', args=[solo.pk]),
        )
        session_response = self.client.post(
            reverse('tools:session_delete', args=[session.pk]),
        )

        self.assertRedirects(
            solo_response,
            reverse('archive:knowledge_bank_tool', args=['min-specs']),
        )
        self.assertRedirects(
            session_response,
            reverse('archive:knowledge_bank_tool', args=['min-specs']),
        )
        self.assertFalse(ToolInstance.objects.filter(pk=solo.pk).exists())
        self.assertFalse(ToolSession.objects.filter(pk=session.pk).exists())