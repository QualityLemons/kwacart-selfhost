import html
import re

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.core import signing
from django.core.cache import cache
from django.template import Context, Template
from django.test import RequestFactory, TestCase
from django.urls import reverse

from archive.feedback_context import (
    CONTEXT_SALT,
    PROMPT_SUPPRESSION_COOKIE,
    create_feedback_context,
    read_feedback_context,
)
from archive.forms import FeedbackForm
from archive.models import FeatureRequest, ToolInstance
from archive.views import (
    CONTEXTUAL_FEEDBACK_MAX_ATTEMPTS,
    staff_feedback_context,
)
from accounts.models import RequestRateLimit
from accounts.organisation_data_ownership import (
    create_owned_session,
    create_owned_solo_record,
)
from tools.registry import TOOL_CATALOG
from config.rate_limit import is_rate_limited


User = get_user_model()


class FeedbackFormTests(TestCase):
    def test_historical_defaults_are_migration_safe(self):
        item = FeatureRequest.objects.create(title='Old idea', description='Details')
        self.assertEqual(item.feedback_type, 'feature')
        self.assertEqual(item.review_status, 'new')
        self.assertEqual(item.source, 'portal')
        self.assertIsNone(item.rating)
        self.assertIsNone(item.submitter)

    def test_each_non_rating_type_is_valid(self):
        for feedback_type in ('feature', 'bug', 'experience'):
            with self.subTest(feedback_type=feedback_type):
                form = FeedbackForm({
                    'feedback_type': feedback_type,
                    'title': 'A title',
                    'description': 'Useful detail',
                })
                self.assertTrue(form.is_valid(), form.errors)

    def test_rating_requires_a_one_to_five_value(self):
        missing = FeedbackForm({'feedback_type': 'rating'})
        invalid = FeedbackForm({'feedback_type': 'rating', 'rating': '6'})
        valid = FeedbackForm({'feedback_type': 'rating', 'rating': '5'})
        self.assertFalse(missing.is_valid())
        self.assertFalse(invalid.is_valid())
        self.assertTrue(valid.is_valid(), valid.errors)

    def test_non_rating_feedback_rejects_rating(self):
        form = FeedbackForm({
            'feedback_type': 'bug',
            'rating': '2',
            'title': 'Bug',
            'description': 'Details',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('rating', form.errors)

    def test_database_rating_type_constraint_rejects_mismatched_rows(self):
        """The invariant survives callers that bypass the public form."""
        for values in (
            {'feedback_type': 'rating', 'rating': None},
            {'feedback_type': 'bug', 'rating': 3},
        ):
            with self.subTest(values=values), self.assertRaises(IntegrityError):
                with transaction.atomic():
                    FeatureRequest.objects.create(
                        title='Constraint test',
                        description='Database must reject this.',
                        **values,
                    )


class PublicFeedbackTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_anonymous_and_authenticated_submitters(self):
        payload = {'title': 'Idea', 'description': 'Details'}
        self.client.post(reverse('feedback'), payload)
        anonymous = FeatureRequest.objects.get(title='Idea')
        self.assertIsNone(anonymous.submitter)

        user = User.objects.create_user(
            email='feedback@example.com', password='a-secure-password',
        )
        self.client.force_login(user)
        self.client.post(reverse('feedback'), {
            'feedback_type': 'bug',
            'title': 'Bug',
            'description': 'Details',
        })
        self.assertEqual(FeatureRequest.objects.get(title='Bug').submitter, user)

    def test_old_route_name_remains_usable(self):
        response = self.client.post(reverse('feature_request'), {
            'title': 'Legacy route',
            'description': 'Still works',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(FeatureRequest.objects.filter(title='Legacy route').exists())

    def test_portal_uses_feedback_template_with_types_and_privacy_copy(self):
        response = self.client.get(reverse('feedback'))
        self.assertTemplateUsed(response, 'feedback.html')
        for feedback_type in ('feature', 'bug', 'experience', 'rating'):
            self.assertContains(response, f'value="{feedback_type}"')
        self.assertContains(
            response,
            'Only staff with a reason to review feedback can access these responses.',
        )


class ContextualFeedbackTests(TestCase):
    def setUp(self):
        cache.clear()
        self.slug = next(iter(TOOL_CATALOG))
        self.token = create_feedback_context(
            'tool_completion', self.slug, 'solo',
        )

    def test_context_round_trip_and_tampering(self):
        self.assertEqual(read_feedback_context(self.token), {
            'source': 'tool_completion',
            'tool_slug': self.slug,
            'interaction_mode': 'solo',
        })
        with self.assertRaises(signing.BadSignature):
            read_feedback_context(self.token + 'tampered')

    def test_source_and_context_combinations_are_strict(self):
        knowledge_token = create_feedback_context('knowledge_bank')
        self.assertEqual(read_feedback_context(knowledge_token), {
            'source': 'knowledge_bank',
            'tool_slug': None,
            'interaction_mode': None,
        })
        with self.assertRaises(ValueError):
            create_feedback_context('tool_completion')
        with self.assertRaises(ValueError):
            create_feedback_context('session_end', 'not-a-real-tool')
        with self.assertRaises(ValueError):
            create_feedback_context('portal', self.slug)
        unsafe = signing.dumps(
            {
                'source': 'knowledge_bank',
                'tool_slug': None,
                'interaction_mode': None,
                'session_id': 'not-allowed',
            },
            salt=CONTEXT_SALT,
        )
        with self.assertRaises(signing.BadSignature):
            read_feedback_context(unsafe)

    def test_template_tag_returns_token_or_empty_string(self):
        rendered = Template(
            '{% load feedback_tags %}'
            '{% feedback_context_token source slug mode %}'
        ).render(Context({
            'source': 'session_end',
            'slug': self.slug,
            'mode': 'session',
        }))
        self.assertEqual(read_feedback_context(rendered)['source'], 'session_end')
        invalid = Template(
            '{% load feedback_tags %}'
            '{% feedback_context_token "tool_completion" "invalid" "solo" %}'
        ).render(Context())
        self.assertEqual(invalid, '')

    def test_context_is_derived_only_from_signed_token(self):
        response = self.client.post(reverse('contextual_feedback'), {
            'context_token': self.token,
            'feedback_type': 'experience',
            'title': 'Context',
            'description': 'Details',
            'source': 'anything',
            'tool_slug': 'attacker-controlled',
            'interaction_mode': 'guest',
            'url': 'https://example.invalid/private',
            'session_id': 'secret',
        })
        self.assertEqual(response.status_code, 302)
        item = FeatureRequest.objects.get(title='Context')
        self.assertEqual(item.source, 'tool_completion')
        self.assertEqual(item.tool_slug, self.slug)
        self.assertEqual(item.interaction_mode, 'solo')

    def test_tampered_context_is_rejected(self):
        response = self.client.post(reverse('contextual_feedback'), {
            'context_token': self.token + 'x',
            'feedback_type': 'rating',
            'rating': 4,
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(FeatureRequest.objects.exists())

    def test_invalid_rating_preserves_token_and_posts_back_to_contextual_url(self):
        url = reverse('contextual_feedback')
        response = self.client.post(url, {
            'context_token': self.token,
            'feedback_type': 'rating',
        })
        self.assertEqual(response.status_code, 400)
        self.assertTemplateUsed(response, 'feedback.html')
        self.assertEqual(response.context['context_token'], self.token)
        self.assertContains(
            response,
            f'name="context_token" value="{self.token}"',
            status_code=400,
        )
        # An action-less form posts back to its current contextual endpoint.
        self.assertEqual(response.request['PATH_INFO'], url)
        self.assertNotContains(response, 'action="', status_code=400)

    def test_contextual_endpoint_is_rate_limited(self):
        payload = {
            'context_token': self.token,
            'feedback_type': 'rating',
            'rating': 4,
        }
        for _ in range(CONTEXTUAL_FEEDBACK_MAX_ATTEMPTS):
            self.assertEqual(self.client.post(
                reverse('contextual_feedback'), payload,
            ).status_code, 302)
        self.assertEqual(self.client.post(
            reverse('contextual_feedback'), payload,
        ).status_code, 429)

    def test_successful_contextual_submission_suppresses_later_prompts(self):
        response = self.client.post(reverse('contextual_feedback'), {
            'context_token': self.token,
            'feedback_type': 'rating',
            'rating': 5,
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn(PROMPT_SUPPRESSION_COOKIE, response.cookies)
        self.assertEqual(
            response.cookies[PROMPT_SUPPRESSION_COOKIE].value, '1',
        )


class StaffFeedbackTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='user@example.com', password='a-secure-password',
        )
        self.staff = User.objects.create_user(
            email='staff@example.com', password='a-secure-password',
            is_staff=True,
        )
        self.item = FeatureRequest.objects.create(
            feedback_type='bug', title='Bug', description='Details',
        )

    def test_non_staff_receive_403(self):
        for user in (None, self.user):
            if user:
                self.client.force_login(user)
            else:
                self.client.logout()
            self.assertEqual(
                self.client.get(reverse('archive:feedback_inbox')).status_code,
                403,
            )
            self.assertEqual(self.client.post(
                reverse('archive:feedback_status', args=[self.item.pk]),
                {'status': 'resolved'},
            ).status_code, 403)

    def test_staff_navigation_links_new_feedback_count_to_filtered_inbox(self):
        FeatureRequest.objects.create(
            title='Another new item', description='Details',
        )
        FeatureRequest.objects.create(
            title='Already reviewed', description='Details',
            review_status='reviewing',
        )
        self.client.force_login(self.staff)

        response = self.client.get(reverse('feedback'))

        filtered_url = reverse('archive:feedback_inbox') + '?status=new'
        self.assertContains(response, f'href="{filtered_url}"')
        self.assertContains(response, 'class="staff-feedback-count"')
        self.assertContains(response, '>2</span>')
        self.assertContains(response, 'aria-label="Feedback inbox, 2 new items"')

        inbox = self.client.get(filtered_url)
        self.assertEqual(inbox.context['selected_status'], 'new')
        self.assertEqual(inbox.context['count'], 2)
        self.assertContains(inbox, '2 responses · private staff view')
        self.assertNotContains(inbox, 'Already reviewed')

    def test_non_staff_navigation_never_receives_feedback_count(self):
        for user in (None, self.user):
            if user:
                self.client.force_login(user)
            else:
                self.client.logout()
            response = self.client.get(reverse('feedback'))
            self.assertNotContains(response, 'staff-feedback-count')
            self.assertNotContains(response, 'Feedback inbox,')
            self.assertNotIn('staff_new_feedback_count', response.context)

    def test_non_staff_context_processor_does_not_query_feedback(self):
        for user in (self.user,):
            request = RequestFactory().get('/')
            request.user = user
            with self.assertNumQueries(0):
                self.assertEqual(staff_feedback_context(request), {})

    def test_staff_filter_status_and_delete(self):
        FeatureRequest.objects.create(
            feedback_type='feature', title='Idea', description='Details',
        )
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse('archive:feedback_inbox'), {'type': 'bug'},
        )
        self.assertEqual(list(response.context['requests']), [self.item])

        response = self.client.post(
            reverse('archive:feedback_status', args=[self.item.pk]),
            {'status': 'resolved'},
        )
        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.review_status, 'resolved')
        self.assertIsNotNone(self.item.reviewed_at)

        self.assertEqual(self.client.get(
            reverse('archive:feedback_delete', args=[self.item.pk]),
        ).status_code, 405)
        self.client.post(reverse('archive:feedback_delete', args=[self.item.pk]))
        self.assertFalse(FeatureRequest.objects.filter(pk=self.item.pk).exists())

    def test_planned_status_and_modern_detail_url(self):
        self.client.force_login(self.staff)
        self.assertEqual(
            reverse('archive:feedback_detail', args=[self.item.pk]),
            f'/archive/feedback/{self.item.pk}/',
        )
        response = self.client.post(
            reverse('archive:feedback_status', args=[self.item.pk]),
            {'status': 'planned'},
        )
        self.assertRedirects(
            response, reverse('archive:feedback_detail', args=[self.item.pk]),
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.review_status, 'planned')

    def test_search_filters_persist_and_dedicated_templates_escape_html(self):
        markup = '<script>alert("xss")</script>'
        matching = FeatureRequest.objects.create(
            feedback_type='experience',
            review_status='planned',
            source='knowledge_bank',
            title=markup,
            description='Findable private detail',
        )
        self.client.force_login(self.staff)
        response = self.client.get(reverse('archive:feedback_inbox'), {
            'q': 'Findable',
            'type': 'experience',
            'status': 'planned',
            'source': 'knowledge_bank',
        })
        self.assertTemplateUsed(response, 'archive/feedback_list.html')
        self.assertEqual(list(response.context['feedbacks']), [matching])
        self.assertEqual(response.context['query'], 'Findable')
        self.assertEqual(response.context['selected_type'], 'experience')
        self.assertEqual(response.context['selected_status'], 'planned')
        self.assertEqual(response.context['selected_source'], 'knowledge_bank')
        self.assertContains(response, '&lt;script&gt;')
        self.assertNotContains(response, markup)

        response = self.client.get(
            reverse('archive:feedback_detail', args=[matching.pk]),
        )
        self.assertTemplateUsed(response, 'archive/feedback_detail.html')
        self.assertContains(response, '&lt;script&gt;')
        self.assertNotContains(response, markup)


class FeedbackPromptIntegrationTests(TestCase):
    """Exercise prompt locations through real views and owned record fixtures."""

    def setUp(self):
        self.user = User.objects.create_user(
            email='prompt-owner@example.com', password='a-secure-password',
        )
        self.slug = 'min-specs'

    def _prompt_token(self, response):
        match = re.search(
            r'name="context_token" value="([^"]+)"',
            response.content.decode(),
        )
        self.assertIsNotNone(match, response.content.decode())
        return html.unescape(match.group(1))

    def _assert_prompt(self, response, source, tool_slug, interaction_mode, forbidden=()):
        self.assertContains(response, 'data-feedback-prompt')
        token = self._prompt_token(response)
        self.assertEqual(read_feedback_context(token), {
            'source': source,
            'tool_slug': tool_slug,
            'interaction_mode': interaction_mode,
        })
        for value in forbidden:
            self.assertNotIn(str(value), token)

    def test_prompts_render_only_for_valid_integrated_contexts(self):
        # Knowledge Bank root permits its deliberately tool-less context.
        self.client.force_login(self.user)
        response = self.client.get(reverse('archive:knowledge_bank'))
        self._assert_prompt(response, 'knowledge_bank', None, None)

        # Tool drill-in and solo archive detail use owned records so access
        # follows the same ownership helper paths as production.
        record = create_owned_solo_record(
            self.user,
            tool_slug=self.slug,
            tool_version='1.0',
            status='archived',
            payload_input={},
        )
        response = self.client.get(
            reverse('archive:knowledge_bank_tool', args=[self.slug]),
        )
        self._assert_prompt(response, 'knowledge_bank', self.slug, 'solo')
        response = self.client.get(reverse('archive:detail', args=[record.pk]))
        self._assert_prompt(response, 'tool_completion', self.slug, 'solo')

        # A completed signed-in session is accessible to the owning host.
        signed_in_session = create_owned_session(
            self.user, tool_slug=self.slug, tool_version='1.0', status='closed',
        )
        response = self.client.get(
            reverse('tools:session_detail', args=[signed_in_session.id]),
        )
        self._assert_prompt(
            response, 'session_end', self.slug, 'session',
            forbidden=(signed_in_session.id, signed_in_session.guest_token),
        )

        # A completed guest session needs the same browser-session marker that
        # guest_join creates; no ownership shortcut is used for guest access.
        guest_session = create_owned_session(
            self.user, tool_slug=self.slug, tool_version='1.0', status='closed',
        )
        guest = ToolInstance.objects.create(
            session=guest_session,
            tool_slug=self.slug,
            tool_version='1.0',
            guest_name='Guest',
            status='archived',
            payload_input={},
        )
        self.client.logout()
        session = self.client.session
        session[f'guest_instance_{guest_session.id}'] = guest.id
        session.save()
        response = self.client.get(reverse(
            'tools:guest_respond',
            args=[guest_session.id, guest_session.guest_token],
        ))
        self._assert_prompt(
            response, 'session_end', self.slug, 'guest',
            forbidden=(guest_session.id, guest_session.guest_token),
        )

        # The public try prompt only appears after a successful PRG result.
        response = self.client.post(reverse('tools:tool_try', args=[self.slug]), {
            'max_specs': 'Everything',
            'sifting_result': 'Keep essentials',
            'min_specs': 'One rule',
        }, follow=True)
        self._assert_prompt(response, 'tool_completion', self.slug, 'try')

    def test_invalid_prompt_context_renders_no_empty_token_form(self):
        rendered = Template(
            '{% include "feedback_prompt.html" with source="tool_completion" %}',
        ).render(Context())
        self.assertNotIn('data-feedback-prompt', rendered)
        self.assertNotIn('name="context_token"', rendered)
        self.assertNotIn('<form', rendered)

    def test_no_js_dismissal_form_is_csrf_post_form(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('archive:knowledge_bank'))
        self.assertContains(
            response,
            f'action="{reverse("feedback_prompt_dismiss")}"',
        )
        self.assertContains(response, '<form method="post"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, 'name="return_to" value="/archive/knowledge-bank/"')

    def test_dismissal_requires_context_rejects_external_redirect_and_suppresses(self):
        response = self.client.post(reverse('feedback_prompt_dismiss'), {
            'context_token': 'tampered',
            'return_to': '/archive/knowledge-bank/',
        })
        self.assertEqual(response.status_code, 400)

        token = create_feedback_context('knowledge_bank')
        response = self.client.post(reverse('feedback_prompt_dismiss'), {
            'context_token': token,
            'return_to': 'https://attacker.example/steal',
        })
        self.assertRedirects(response, '/')
        self.assertIn(PROMPT_SUPPRESSION_COOKIE, response.cookies)
        self.assertEqual(response.cookies[PROMPT_SUPPRESSION_COOKIE].value, '1')

        self.client.force_login(self.user)
        self.client.cookies[PROMPT_SUPPRESSION_COOKIE] = '1'
        response = self.client.get(reverse('archive:knowledge_bank'))
        self.assertNotContains(response, 'data-feedback-prompt')


class DatabaseRateLimitTests(TestCase):
    def setUp(self):
        RequestRateLimit.objects.all().delete()
        self.factory = RequestFactory()

    def test_attempts_persist_in_database_and_xff_prefix_cannot_evade_limit(self):
        first = self.factory.post(
            '/feedback/',
            HTTP_X_FORWARDED_FOR='spoofed-left, 198.51.100.44',
        )
        for _ in range(2):
            self.assertFalse(is_rate_limited(first, 'feedback-hardening', 2, 60, 60))
        self.assertTrue(is_rate_limited(first, 'feedback-hardening', 2, 60, 60))

        bucket = RequestRateLimit.objects.get()
        self.assertEqual(bucket.attempts, 3)
        self.assertIsNotNone(bucket.locked_until)

        changed_prefix = self.factory.post(
            '/feedback/',
            HTTP_X_FORWARDED_FOR='different-spoof, 198.51.100.44',
        )
        self.assertTrue(
            is_rate_limited(changed_prefix, 'feedback-hardening', 2, 60, 60),
        )
        self.assertEqual(RequestRateLimit.objects.count(), 1)