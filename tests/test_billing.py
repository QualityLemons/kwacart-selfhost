import hashlib
import hmac
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.billing import apply_subscription
from accounts.forms import CustomUserCreationForm
from accounts.stripe_client import StripeError, verify_webhook_signature


User = get_user_model()


def subscription(plan='solo', status='active', interval='month'):
    return {
        'id': f'sub_{plan}',
        'customer': f'cus_{plan}',
        'status': status,
        'current_period_end': 1800000000,
        'cancel_at_period_end': False,
        'metadata': {
            'kwacart_plan': plan,
            'billing_interval': interval,
        },
        'items': {
            'data': [{
                'price': {
                    'id': f'price_{plan}_{interval}',
                    'metadata': {'kwacart_plan': plan},
                    'recurring': {'interval': interval},
                },
            }],
        },
    }


@override_settings(BILLING_ENABLED=True)
class PublicBillingJourneyTests(TestCase):
    def test_pricing_offers_all_four_subscription_choices(self):
        response = self.client.get(reverse('pricing'))
        self.assertContains(response, 'plan=solo&amp;interval=month')
        self.assertContains(response, 'plan=solo&amp;interval=year')
        self.assertContains(response, 'plan=organisation&amp;interval=month')
        self.assertContains(response, 'plan=organisation&amp;interval=year')

    def test_public_registration_starts_without_paid_access(self):
        form = CustomUserCreationForm({
            'email': 'new@example.com',
            'password1': 'A-valid-passphrase-129!',
            'password2': 'A-valid-passphrase-129!',
        })
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertEqual(user.plan, 'free')
        self.assertEqual(user.subscription_status, 'none')
        self.assertFalse(user.has_paid_access)

    def test_plan_choice_survives_registration_redirect(self):
        response = self.client.post(
            reverse('accounts:signup') + '?plan=solo&interval=year',
            {
                'email': 'annual@example.com',
                'password1': 'A-valid-passphrase-129!',
                'password2': 'A-valid-passphrase-129!',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('next=', response['Location'])
        self.assertIn('plan%3Dsolo', response['Location'])
        self.assertIn('interval%3Dyear', response['Location'])


@override_settings(BILLING_ENABLED=True)
class CheckoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='checkout@example.com',
            password='A-valid-passphrase-129!',
            plan='free',
            subscription_status='none',
        )
        self.client.force_login(self.user)

    @patch('accounts.views.create_checkout_session')
    @patch('accounts.views.find_price', return_value='price_allowed')
    def test_checkout_uses_allow_list_and_hosted_url(self, find_price, create):
        create.return_value = {'url': 'https://checkout.stripe.com/test'}
        response = self.client.post(reverse('accounts:checkout'), {
            'plan': 'organisation',
            'interval': 'year',
        })
        self.assertRedirects(
            response,
            'https://checkout.stripe.com/test',
            fetch_redirect_response=False,
        )
        find_price.assert_called_once_with('organisation', 'year')
        self.assertEqual(
            create.call_args.args[-3:-1], ('organisation', 'year')
        )
        self.assertTrue(create.call_args.args[-1].startswith('kwacart-'))

    @patch('accounts.views.create_checkout_session')
    @patch('accounts.views.find_price', return_value='price_allowed')
    def test_repeated_checkout_uses_same_idempotency_key(self, find_price, create):
        create.return_value = {'url': 'https://checkout.stripe.com/test'}
        payload = {'plan': 'solo', 'interval': 'month'}
        self.client.post(reverse('accounts:checkout'), payload)
        first_key = create.call_args.args[-1]
        self.client.post(reverse('accounts:checkout'), payload)
        self.assertEqual(create.call_args.args[-1], first_key)

    def test_invalid_price_selection_is_rejected_before_stripe(self):
        response = self.client.post(reverse('accounts:checkout'), {
            'plan': 'enterprise',
            'interval': 'week',
        })
        self.assertRedirects(response, reverse('pricing'))

    @patch('accounts.views.retrieve_checkout_session')
    def test_completed_checkout_activates_access(self, retrieve):
        data = subscription('solo')
        retrieve.return_value = {
            'id': 'cs_test',
            'status': 'complete',
            'payment_status': 'paid',
            'client_reference_id': str(self.user.pk),
            'customer': 'cus_solo',
            'subscription': data,
        }
        response = self.client.get(
            reverse('accounts:checkout_success') + '?session_id=cs_test'
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.has_paid_access)
        self.assertEqual(self.user.plan, 'solo')

    @patch('accounts.views.retrieve_checkout_session')
    def test_unpaid_checkout_has_accessible_pending_state(self, retrieve):
        retrieve.return_value = {
            'status': 'open',
            'payment_status': 'unpaid',
        }
        response = self.client.get(
            reverse('accounts:checkout_success') + '?session_id=cs_pending'
        )
        self.assertContains(response, 'Payment still processing')
        self.assertContains(response, 'aria-labelledby="checkout-title"')

    @patch('accounts.views.retrieve_checkout_session')
    def test_old_checkout_cannot_replace_current_subscription(self, retrieve):
        self.user.stripe_subscription_id = 'sub_current'
        self.user.save(update_fields=['stripe_subscription_id'])
        old = subscription('solo')
        old['id'] = 'sub_old'
        retrieve.return_value = {
            'status': 'complete',
            'payment_status': 'paid',
            'client_reference_id': str(self.user.pk),
            'customer': self.user.stripe_customer_id,
            'subscription': old,
        }
        response = self.client.get(
            reverse('accounts:checkout_success') + '?session_id=cs_old'
        )
        self.assertEqual(response.status_code, 502)
        self.user.refresh_from_db()
        self.assertEqual(self.user.stripe_subscription_id, 'sub_current')

    def test_cancelled_checkout_explains_no_payment_was_taken(self):
        response = self.client.get(reverse('accounts:checkout_cancel'))
        self.assertContains(response, 'No payment was taken')
        self.assertContains(response, 'Return to pricing')


@override_settings(BILLING_ENABLED=True)
class BillingPortalTests(TestCase):
    @patch('accounts.views.create_portal_session')
    def test_organisation_owner_can_create_billing_portal_session(self, create):
        owner = User.objects.create_user(
            email='owner@portal.example',
            password='A-valid-passphrase-129!',
            plan='organisation',
            subscription_status='active',
            stripe_customer_id='cus_owner_portal',
        )
        create.return_value = {'url': 'https://billing.stripe.com/owner'}
        self.client.force_login(owner)

        response = self.client.post(reverse('accounts:billing_portal'))

        self.assertRedirects(
            response,
            'https://billing.stripe.com/owner',
            fetch_redirect_response=False,
        )
        create.assert_called_once()
        self.assertEqual(create.call_args.args[0], owner)

    @patch('accounts.views.create_portal_session')
    def test_solo_subscriber_can_create_billing_portal_session(self, create):
        subscriber = User.objects.create_user(
            email='solo@portal.example',
            password='A-valid-passphrase-129!',
            plan='solo',
            subscription_status='active',
            stripe_customer_id='cus_solo_portal',
        )
        create.return_value = {'url': 'https://billing.stripe.com/solo'}
        self.client.force_login(subscriber)

        response = self.client.post(reverse('accounts:billing_portal'))

        self.assertRedirects(
            response,
            'https://billing.stripe.com/solo',
            fetch_redirect_response=False,
        )
        create.assert_called_once()
        self.assertEqual(create.call_args.args[0], subscriber)

    @patch('accounts.views.create_portal_session')
    def test_included_member_cannot_create_owner_billing_portal_session(self, create):
        owner = User.objects.create_user(
            email='owner@included.example',
            password='A-valid-passphrase-129!',
            plan='organisation',
            subscription_status='active',
            stripe_customer_id='cus_included_owner',
        )
        member = User.objects.create_user(
            email='member@included.example',
            password='A-valid-passphrase-129!',
            organisation_owner=owner,
        )
        self.client.force_login(member)

        response = self.client.post(reverse('accounts:billing_portal'))

        self.assertEqual(response.status_code, 403)
        create.assert_not_called()


@override_settings(BILLING_ENABLED=True)
class SubscriptionAccessTests(TestCase):
    def test_organisation_subscription_links_existing_same_domain_users(self):
        owner = User.objects.create_user(
            email='owner@collective.example',
            password='A-valid-passphrase-129!',
            plan='free',
            subscription_status='none',
        )
        member = User.objects.create_user(
            email='member@collective.example',
            password='A-valid-passphrase-129!',
            plan='free',
            subscription_status='none',
        )
        outsider = User.objects.create_user(
            email='person@elsewhere.example',
            password='A-valid-passphrase-129!',
            plan='free',
            subscription_status='none',
        )
        apply_subscription(owner, subscription('organisation'))
        member.refresh_from_db()
        outsider.refresh_from_db()
        self.assertEqual(member.organisation_owner, owner)
        self.assertTrue(member.has_paid_access)
        self.assertIsNone(outsider.organisation_owner)

    def test_failed_payment_removes_organisation_member_access(self):
        owner = User.objects.create_user(
            email='owner@team.example',
            password='A-valid-passphrase-129!',
            plan='organisation',
            subscription_status='active',
        )
        member = User.objects.create_user(
            email='member@team.example',
            password='A-valid-passphrase-129!',
            plan='free',
            subscription_status='none',
            organisation_owner=owner,
        )
        apply_subscription(owner, subscription('organisation', status='past_due'))
        member.refresh_from_db()
        self.assertIsNone(member.organisation_owner)
        self.assertFalse(member.has_paid_access)

    def test_organisation_does_not_absorb_independently_billed_user(self):
        owner = User.objects.create_user(
            email='owner@independent.example',
            password='A-valid-passphrase-129!',
            plan='organisation',
            subscription_status='active',
        )
        paid_user = User.objects.create_user(
            email='solo@independent.example',
            password='A-valid-passphrase-129!',
            plan='solo',
            subscription_status='active',
            stripe_subscription_id='sub_personal',
        )
        owner.link_organisation_members()
        paid_user.refresh_from_db()
        self.assertIsNone(paid_user.organisation_owner)

    def test_older_webhook_cannot_overwrite_newer_subscription_state(self):
        user = User.objects.create_user(
            email='ordered@example.com',
            password='A-valid-passphrase-129!',
            plan='free',
            subscription_status='none',
        )
        apply_subscription(user, subscription('solo'), event_created=200)
        apply_subscription(
            user, subscription('solo', status='past_due'), event_created=100
        )
        user.refresh_from_db()
        self.assertEqual(user.subscription_status, 'active')
        self.assertEqual(user.stripe_event_created, 200)

    def test_unpaid_user_is_redirected_from_paid_workspace(self):
        user = User.objects.create_user(
            email='locked@example.com',
            password='A-valid-passphrase-129!',
            plan='free',
            subscription_status='none',
        )
        self.client.force_login(user)
        response = self.client.get(reverse('tools:catalog'))
        self.assertRedirects(
            response,
            reverse('pricing') + '?billing=required',
            fetch_redirect_response=False,
        )

    def test_unpaid_authenticated_user_can_still_use_public_try_page(self):
        user = User.objects.create_user(
            email='preview@example.com',
            password='A-valid-passphrase-129!',
            plan='free',
            subscription_status='none',
        )
        self.client.force_login(user)
        response = self.client.get(
            reverse('tools:tool_try', kwargs={'tool_slug': 'min-specs'})
        )
        self.assertEqual(response.status_code, 200)

    @patch('accounts.views.sync_subscription')
    def test_deletion_fails_closed_when_stripe_cannot_be_confirmed(self, sync):
        sync.side_effect = StripeError('temporary outage')
        user = User.objects.create_user(
            email='delete@example.com',
            password='A-valid-passphrase-129!',
            plan='solo',
            subscription_status='none',
            stripe_subscription_id='sub_stale',
        )
        self.client.force_login(user)
        response = self.client.post(
            reverse('accounts:delete'), {'confirm': 'DELETE'}
        )
        self.assertRedirects(response, reverse('accounts:profile'))
        self.assertTrue(User.objects.filter(pk=user.pk).exists())


class StripeSignatureTests(TestCase):
    @override_settings()
    def test_valid_signature_is_accepted_and_tampering_is_rejected(self):
        payload = b'{"id":"evt_test"}'
        timestamp = 1800000000
        secret = 'whsec_test_value'
        signed = f'{timestamp}.{payload.decode()}'.encode()
        signature = hmac.new(
            secret.encode(), signed, hashlib.sha256
        ).hexdigest()
        header = f't={timestamp},v1={signature}'
        with patch('accounts.stripe_client.time.time', return_value=timestamp):
            self.assertTrue(
                verify_webhook_signature(payload, header, secret)
            )
            self.assertFalse(
                verify_webhook_signature(b'{"id":"changed"}', header, secret)
            )