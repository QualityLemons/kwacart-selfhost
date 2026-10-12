import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings


@pytest.mark.django_db
@override_settings(
    ROOT_URLCONF='desktop.urls', SETUP_TICKET='only-this-launch',
    AUTH_PASSWORD_VALIDATORS=[
        {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    ],
)
def test_first_account_requires_ticket_and_cannot_be_reused(client):
    assert client.get('/desktop/setup/').status_code == 403
    assert client.get('/desktop/setup/?ticket=wrong').status_code == 403
    response = client.get('/desktop/setup/?ticket=only-this-launch', follow=True)
    assert response.status_code == 200
    assert b'<label for="id_email">' in response.content
    assert b'only-this-launch' not in response.content
    bad = client.post('/desktop/setup/', {
        'email': 'first@example.test', 'password1': 'short', 'password2': 'short',
    })
    assert bad.status_code == 200
    assert b'role="alert"' in bad.content
    assert not get_user_model().objects.exists()
    result = client.post('/desktop/setup/', {
        'email': 'first@example.test', 'password1': 'Native-Only-Check-947!x',
        'password2': 'Native-Only-Check-947!x',
    })
    assert result.status_code == 302
    user = get_user_model().objects.get()
    assert user.is_superuser and user.is_staff
    assert int(client.session['_auth_user_id']) == user.pk
    assert 'desktop_setup_allowed' not in client.session
    assert client.get('/desktop/setup/?ticket=only-this-launch').url == '/accounts/login/'
    client.post('/desktop/setup/', {
        'email': 'second@example.test', 'password1': 'Native-Only-Check-947!x',
        'password2': 'Native-Only-Check-947!x',
    })
    assert get_user_model().objects.count() == 1


@pytest.mark.django_db
@override_settings(ROOT_URLCONF='desktop.urls', SETUP_TICKET='only-this-launch')
def test_ticket_does_not_bypass_csrf():
    from django.test import Client
    client = Client(enforce_csrf_checks=True)
    client.get('/desktop/setup/?ticket=only-this-launch', follow=True)
    assert client.post('/desktop/setup/', {
        'email': 'first@example.test', 'password1': 'Native-Only-Check-947!x',
        'password2': 'Native-Only-Check-947!x',
    }).status_code == 403
