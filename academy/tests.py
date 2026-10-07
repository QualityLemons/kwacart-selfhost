from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .content import LESSONS
from .models import AcademyLessonProgress


class AcademyTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email='learner@example.test',
            password='Academy-test-2026!',
        )

    def test_public_dashboard_describes_all_lessons(self):
        response = self.client.get(reverse('academy_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['authenticated'])
        self.assertEqual(response.context['total_count'], 10)
        self.assertContains(response, 'A steadier way to begin facilitating')
        self.assertContains(response, 'Register to save progress')
        self.assertContains(response, 'Log in to resume')
        for lesson in LESSONS:
            self.assertContains(response, lesson['title'])
            self.assertContains(response, f'Open {lesson["title"]}')

    def test_safeguarding_adaptive_and_care_are_lessons_two_to_four(self):
        response = self.client.get(reverse('academy_dashboard'))
        lessons = response.context['lessons']

        self.assertEqual(
            [lesson['slug'] for lesson in lessons[1:4]],
            [
                'safeguarding-children-and-adults-at-risk',
                'adapt-with-emergent-strategy',
                'prepare-for-vicarious-trauma',
            ],
        )
        self.assertEqual([lesson['number'] for lesson in lessons[1:4]], [2, 3, 4])

    def test_old_safeguarding_resource_redirects_to_lesson_two(self):
        response = self.client.get(reverse('academy_safeguarding'))

        self.assertRedirects(
            response,
            reverse(
                'academy_lesson',
                args=('safeguarding-children-and-adults-at-risk',),
            ),
            status_code=301,
        )

    def test_new_lessons_preserve_safety_and_role_boundaries(self):
        safeguarding = self.client.get(reverse(
            'academy_lesson',
            args=('safeguarding-children-and-adults-at-risk',),
        ))
        adaptive = self.client.get(reverse(
            'academy_lesson',
            args=('adapt-with-emergent-strategy',),
        ))
        care = self.client.get(reverse(
            'academy_lesson',
            args=('prepare-for-vicarious-trauma',),
        ))

        self.assertContains(safeguarding, 'in the UK, call 999')
        self.assertContains(safeguarding, 'do not investigate')
        self.assertContains(safeguarding, 'do not promise secrecy')
        self.assertContains(safeguarding, 'Use approved platforms and accounts')
        self.assertContains(safeguarding, 'unmoderated one-to-one messaging')
        self.assertContains(safeguarding, 'if a connection drops during a concern')
        self.assertContains(adaptive, 'Do not improvise around safeguarding')
        self.assertContains(care, 'cannot diagnose vicarious trauma')

    def test_public_lesson_invites_registration_instead_of_showing_completion_form(self):
        lesson = LESSONS[0]
        response = self.client.get(reverse('academy_lesson', args=(lesson['slug'],)))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Register to save progress')
        self.assertNotContains(response, 'Mark lesson complete')

    def test_authenticated_dashboard_resumes_first_incomplete_lesson(self):
        self.client.force_login(self.user)
        AcademyLessonProgress.objects.create(
            user=self.user,
            lesson_slug=LESSONS[0]['slug'],
        )

        response = self.client.get(reverse('academy_dashboard'))

        self.assertEqual(response.context['completed_count'], 1)
        self.assertEqual(response.context['next_lesson']['slug'], LESSONS[1]['slug'])
        self.assertContains(response, '1 of 10 lessons complete')

    def test_completion_is_login_required_idempotent_and_advances(self):
        first = LESSONS[0]
        complete_url = reverse('academy_complete', args=(first['slug'],))
        anonymous_response = self.client.post(complete_url)
        self.assertRedirects(
            anonymous_response,
            f'{reverse("accounts:login")}?next={complete_url}',
        )

        self.client.force_login(self.user)
        response = self.client.post(complete_url)
        self.assertRedirects(
            response,
            reverse('academy_lesson', args=(LESSONS[1]['slug'],)),
        )
        self.client.post(complete_url)
        self.assertEqual(
            AcademyLessonProgress.objects.filter(user=self.user).count(),
            1,
        )

    def test_progress_is_private_to_each_user(self):
        other = get_user_model().objects.create_user(
            email='other@example.test',
            password='Academy-test-2026!',
        )
        AcademyLessonProgress.objects.create(
            user=other,
            lesson_slug=LESSONS[0]['slug'],
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('academy_dashboard'))

        self.assertEqual(response.context['completed_count'], 0)
        self.assertFalse(response.context['lessons'][0]['completed'])

    def test_unknown_lesson_returns_404(self):
        self.assertEqual(
            self.client.get(reverse('academy_lesson', args=('unknown',))).status_code,
            404,
        )
        self.client.force_login(self.user)
        self.assertEqual(
            self.client.post(reverse('academy_complete', args=('unknown',))).status_code,
            404,
        )

    def test_completion_endpoint_is_post_only(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('academy_complete', args=(LESSONS[0]['slug'],)),
        )

        self.assertEqual(response.status_code, 405)
        self.assertFalse(AcademyLessonProgress.objects.exists())

    def test_completion_endpoint_requires_csrf(self):
        csrf_client = self.client_class(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)

        response = csrf_client.post(
            reverse('academy_complete', args=(LESSONS[0]['slug'],)),
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(AcademyLessonProgress.objects.exists())

    def test_legacy_learn_url_renders_academy(self):
        response = self.client.get(reverse('learn'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'academy/index.html')

    def test_registration_preserves_safe_academy_return_url(self):
        lesson_url = reverse('academy_lesson', args=(LESSONS[0]['slug'],))
        signup_url = f'{reverse("accounts:signup")}?next={lesson_url}'
        self.client.get(signup_url)

        response = self.client.post(signup_url, {
            'email': 'new-academy-user@example.test',
            'password1': 'Academy-new-user-2026!',
            'password2': 'Academy-new-user-2026!',
        })

        expected = f'{reverse("accounts:login")}?next={lesson_url}'
        self.assertRedirects(response, expected, fetch_redirect_response=False)

    def test_registration_rejects_external_return_url(self):
        signup_url = (
            f'{reverse("accounts:signup")}'
            '?next=https%3A%2F%2Fevil.example%2Fphishing'
        )
        self.client.get(signup_url)

        response = self.client.post(signup_url, {
            'email': 'safe-academy-user@example.test',
            'password1': 'Academy-safe-user-2026!',
            'password2': 'Academy-safe-user-2026!',
        })

        self.assertRedirects(
            response,
            reverse('accounts:login'),
            fetch_redirect_response=False,
        )