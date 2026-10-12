"""Fixture creation and HTTP authorization checks against the native server."""
import http.cookiejar
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request


def check_private_media(owner_opener, base, data, key):
    # Python on the runner seeds records only; all HTTP below reaches the
    # packaged executable, never a Python replacement for the native server.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    os.environ.update(
        DJANGO_SETTINGS_MODULE='config.settings.desktop',
        KWACART_DATA_DIR=str(data), SECRET_KEY=key.decode(),
    )
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from django.db import connections
    from archive.models import ToolInstance, ToolSession

    owner = get_user_model().objects.get(email='native@example.test')
    get_user_model().objects.create_user(
        email='other-native@example.test', password='Other-Native-947!x',
    )
    export = 'archives/md/private-export.md'
    export_file = data / 'media' / export
    export_file.parent.mkdir(parents=True, exist_ok=True)
    export_file.write_text('private workshop export', encoding='utf-8')
    record = ToolInstance.objects.create(
        user=owner, tool_slug='min-specs', tool_version='1.0',
        status='archived', md_file=export,
    )
    session = ToolSession.objects.create(
        host=owner, tool_slug='min-specs', tool_version='1.0',
    )
    attachment = f'kwacart/attachments/{session.pk}/retained.txt'
    attachment_file = data / 'media' / attachment
    attachment_file.parent.mkdir(parents=True)
    attachment_file.write_text('retain this upload', encoding='utf-8')
    ToolInstance.objects.create(
        session=session, user=owner, tool_slug='min-specs', tool_version='1.0',
        attachments=[{
            'storage_name': attachment, 'public_id': attachment,
            'url': '/media/' + attachment, 'type': 'audio',
        }],
    )
    connections.close_all()

    def denied(opener, path):
        try:
            opener.open(base + path)
        except urllib.error.HTTPError as exc:
            assert exc.code == 404, (path, exc.code)
        else:
            raise AssertionError('Private media authorization bypass: ' + path)

    jar = http.cookiejar.CookieJar()
    anonymous = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar),
    )
    for opener in (anonymous, owner_opener):
        denied(opener, '/media/' + export)
    denied(anonymous, '/media/' + attachment)
    download = f'/archive/download/{record.pk}/md/'
    with owner_opener.open(base + download) as response:
        assert response.read() == b'private workshop export'
    with owner_opener.open(base + '/media/' + attachment) as response:
        assert response.read() == b'retain this upload'
        assert 'no-store' in response.headers['Cache-Control']
        assert response.headers['X-Content-Type-Options'] == 'nosniff'
    with anonymous.open(base + download) as response:
        assert '/accounts/login/' in response.geturl()
        assert b'private workshop export' not in response.read()

    # Verify ownership as a genuinely signed-in second local account.
    with anonymous.open(base + '/accounts/login/') as response:
        response.read()
    token = next(c.value for c in jar if c.name == 'csrftoken')
    payload = urllib.parse.urlencode({
        'username': 'other-native@example.test', 'password': 'Other-Native-947!x',
        'csrfmiddlewaretoken': token,
    }).encode()
    with anonymous.open(urllib.request.Request(
        base + '/accounts/login/', data=payload,
        headers={'Referer': base + '/accounts/login/'},
    )) as response:
        assert '/accounts/login/' not in response.geturl(), 'second-account login failed'
    for path in (download, '/media/' + attachment, '/media/' + export):
        denied(anonymous, path)
    print('PASS: native private exports and attachments reject anonymous and unrelated accounts.')
    return attachment
