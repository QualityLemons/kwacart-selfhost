from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.urls import reverse


class VoiceControlCompatibilityTests(SimpleTestCase):
    def test_shared_and_lesson_navigation_have_spoken_names(self):
        response = self.client.get(reverse('academy_lesson', args=(
            'safeguarding-children-and-adults-at-risk',
        )))

        self.assertContains(response, '<nav aria-label="Main navigation">')
        self.assertContains(
            response,
            '<nav class="academy-pagination" aria-label="Lesson navigation">',
        )
        self.assertContains(response, 'Back to Academy')
        self.assertContains(response, 'Previous:')
        self.assertContains(response, 'Next:')

    def test_pairing_code_uses_a_visible_matching_label(self):
        response = self.client.get(reverse('pairing_entry'))

        self.assertContains(
            response,
            '<label class="ps-question" for="pairing-code">',
        )
        self.assertContains(response, 'id="pairing-code"')
        self.assertContains(response, 'enterkeyhint="go"')
        self.assertContains(response, 'aria-describedby="pairing-code-hint"')

    def test_guest_name_uses_a_visible_matching_label(self):
        html = render_to_string('tools/guest_join.html', {
            'session': SimpleNamespace(id=1),
            'instance': SimpleNamespace(guest_name=''),
            'tool_meta': {'title': 'Example session'},
        })

        self.assertIn(
            '<label class="ns-question" for="guest_name">',
            html,
        )
        self.assertIn('id="guest_name"', html)
        self.assertIn('autocomplete="name"', html)
        self.assertIn('autocapitalize="words"', html)
        self.assertIn('enterkeyhint="go"', html)
        self.assertIn('aria-describedby="guest-name-hint"', html)

    def test_account_text_boxes_keep_persistent_visible_labels(self):
        signup = self.client.get(reverse('accounts:signup'))
        login = self.client.get(reverse('accounts:login'))

        self.assertContains(signup, '<label for="id_email">Email address</label>')
        self.assertContains(signup, 'autocomplete="email"')
        self.assertContains(signup, 'inputmode="email"')
        self.assertContains(signup, 'enterkeyhint="next"')
        self.assertContains(signup, 'enterkeyhint="done"')
        self.assertContains(signup, '<label for="id_password1">Password</label>')
        self.assertContains(
            signup,
            '<label for="id_password2">Confirm password</label>',
        )
        self.assertContains(login, '<label for="id_username">Email address</label>')
        self.assertContains(login, '<label for="id_password">Password</label>')