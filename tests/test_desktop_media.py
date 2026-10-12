import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from archive.models import ToolInstance, ToolSession


@pytest.mark.django_db
@override_settings(ROOT_URLCONF='desktop.urls')
def test_exports_never_use_raw_media_and_download_still_checks_owner(client, tmp_path):
    owner = get_user_model().objects.create_user(email='owner@example.test')
    other = get_user_model().objects.create_user(email='other@example.test')
    path = 'archives/md/private.md'
    file = tmp_path / path
    file.parent.mkdir(parents=True)
    file.write_text('private export')
    record = ToolInstance.objects.create(
        user=owner, tool_slug='min-specs', tool_version='1.0', md_file=path,
    )
    with override_settings(MEDIA_ROOT=tmp_path):
        for user in (None, other, owner):
            if user:
                client.force_login(user)
            else:
                client.logout()
            assert client.get('/media/' + path).status_code == 404
        response = client.get(f'/archive/download/{record.pk}/md/')
        assert response.status_code == 200
        assert b''.join(response.streaming_content) == b'private export'
        response.close()
        client.force_login(other)
        assert client.get(f'/archive/download/{record.pk}/md/').status_code == 404
        client.logout()
        assert client.get(f'/archive/download/{record.pk}/md/').status_code == 302


@pytest.mark.django_db
@override_settings(ROOT_URLCONF='desktop.urls')
def test_only_registered_session_attachments_are_available(client, tmp_path):
    owner = get_user_model().objects.create_user(email='owner@example.test')
    participant = get_user_model().objects.create_user(email='participant@example.test')
    outsider = get_user_model().objects.create_user(email='outsider@example.test')
    session = ToolSession.objects.create(host=owner, tool_slug='min-specs', tool_version='1.0')
    path = f'kwacart/attachments/{session.pk}/private.png'
    file = tmp_path / path
    file.parent.mkdir(parents=True)
    file.write_bytes(b'private image fixture')
    instance = ToolInstance.objects.create(
        session=session, user=participant, tool_slug='min-specs', tool_version='1.0',
        attachments=[{'storage_name': path, 'public_id': path}],
    )
    with override_settings(MEDIA_ROOT=tmp_path):
        assert client.get('/media/' + path).status_code == 404
        client.force_login(outsider)
        assert client.get('/media/' + path).status_code == 404
        for user in (owner, participant):
            client.force_login(user)
            response = client.get('/media/' + path)
            assert response.status_code == 200
            assert b''.join(response.streaming_content) == b'private image fixture'
            assert 'no-store' in response['Cache-Control']
            assert response['X-Content-Type-Options'] == 'nosniff'
            response.close()
        instance.attachments = []
        instance.save(update_fields=['attachments'])
        assert client.get('/media/' + path).status_code == 404


@pytest.mark.django_db
@override_settings(ROOT_URLCONF='desktop.urls')
def test_guest_attachment_access_is_bound_to_their_instance(client, tmp_path):
    owner = get_user_model().objects.create_user(email='owner@example.test')
    session = ToolSession.objects.create(host=owner, tool_slug='min-specs', tool_version='1.0')
    path = f'kwacart/attachments/{session.pk}/guest.png'
    file = tmp_path / path
    file.parent.mkdir(parents=True)
    file.write_bytes(b'guest fixture')
    guest = ToolInstance.objects.create(
        session=session, tool_slug='min-specs', tool_version='1.0',
        attachments=[{'storage_name': path, 'public_id': path}],
    )
    with override_settings(MEDIA_ROOT=tmp_path):
        assert client.get('/media/' + path).status_code == 404
        browser_session = client.session
        browser_session[f'guest_instance_{session.pk}'] = guest.pk
        browser_session.save()
        response = client.get('/media/' + path)
        assert response.status_code == 200
        response.close()
        browser_session[f'guest_instance_{session.pk}'] = guest.pk + 10000
        browser_session.save()
        assert client.get('/media/' + path).status_code == 404
