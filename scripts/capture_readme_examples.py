"""Create documentation screenshots and exports using an isolated demo database.

Requires Playwright's Chromium browser: python -m playwright install chromium.
No real accounts, sessions, media or application databases are read or changed.
"""
import os
from pathlib import Path
import runpy
import secrets
import shutil
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler, make_server

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings.local'


def main():
    from django.conf import settings

    with tempfile.TemporaryDirectory(prefix='kwacart-documentation-') as directory:
        settings.DATABASES = {'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': str(Path(directory) / 'demo.sqlite3'),
        }}
        settings.MEDIA_ROOT = Path(directory) / 'media'
        settings.SECRET_KEY = secrets.token_urlsafe(48)
        settings.DEBUG = True
        settings.ALLOWED_HOSTS = ['127.0.0.1', 'testserver']
        settings.STORAGES = {
            'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
            'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
        }
        settings.CACHES = {'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }}
        settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
        # Reuse the bounded Nix dependency discovery for Chromium on Replit.
        if os.environ.get('REPLIT_LD_LIBRARY_PATH'):
            runpy.run_path(str(ROOT / 'tests' / 'conftest.py'))

        import django
        django.setup()
        from django.contrib.auth import get_user_model
        from django.contrib.staticfiles.handlers import StaticFilesHandler
        from django.core.management import call_command
        from django.core.wsgi import get_wsgi_application
        from django.db import connections
        from django.test import Client
        from django.urls import reverse
        from archive.models import ToolInstance, ToolSession
        from exporters.pipeline import run_export_pipeline, run_session_export_pipeline
        from tools.registry import get_tool_instance
        from playwright.sync_api import sync_playwright

        call_command('migrate', verbosity=0)
        user = get_user_model().objects.create_user(email='demo@example.test')
        participant = get_user_model().objects.create_user(email='participant@example.test')
        stamp = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
        payload = {
            'max_specs': 'Start every meeting at 9am.\nUse slides for every update.\n'
                         'Offer a way to contribute without speaking.\nAgree one next action.',
            'sifting_result': 'Drop the fixed start time and mandatory slides: neither is '
                              'essential to making decisions together.',
            'min_specs': 'Offer a way to contribute without speaking.\n'
                         'Agree one next action and who will take it.',
        }
        output = get_tool_instance('min-specs', payload).execute()
        solo = ToolInstance.objects.create(
            user=user, data_owner=user, tool_slug='min-specs', tool_version='1.0',
            status='archived', payload_input=payload, payload_output=output,
            submitted_at=stamp,
        )
        run_export_pipeline(solo)
        session = ToolSession.objects.create(
            host=user, data_owner=user, tool_slug='min-specs', tool_version='1.0',
            status='closed', closed_at=stamp,
        )
        ToolSession.objects.filter(pk=session.pk).update(
            created_at=stamp - timedelta(minutes=30),
        )
        session.refresh_from_db()
        for contributor in (user, participant):
            ToolInstance.objects.create(
                user=contributor, data_owner=user, session=session,
                tool_slug='min-specs', tool_version='1.0', status='archived',
                payload_input=payload, payload_output=output, submitted_at=stamp,
            )
        run_session_export_pipeline(session)
        examples = ROOT / 'docs' / 'examples'
        screenshots = ROOT / 'docs' / 'screenshots'
        examples.mkdir(parents=True, exist_ok=True)
        screenshots.mkdir(parents=True, exist_ok=True)
        for name, record in [('min-specs-solo', solo), ('min-specs-session', session)]:
            for extension in ('md', 'rtf'):
                stored = getattr(record, f'{extension}_file')
                if not stored:
                    raise RuntimeError(f'Demo {extension} export generation failed')
                shutil.copyfile(
                    settings.MEDIA_ROOT / str(stored),
                    examples / f'{name}.{extension}',
                )

        client = Client()
        client.force_login(user)

        class ThreadedServer(ThreadingMixIn, WSGIServer):
            daemon_threads = True

        class QuietHandler(WSGIRequestHandler):
            def log_message(self, *args):
                pass

        server = make_server(
            '127.0.0.1', 0, StaticFilesHandler(get_wsgi_application()),
            server_class=ThreadedServer, handler_class=QuietHandler,
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, args=['--no-sandbox'])
                context = browser.new_context(viewport={'width': 1100, 'height': 800})
                context.add_cookies([{
                    'name': settings.SESSION_COOKIE_NAME,
                    'value': client.cookies[settings.SESSION_COOKIE_NAME].value,
                    'url': base,
                }])
                page = context.new_page()
                page.goto(base + reverse('archive:knowledge_bank_tool',
                                         kwargs={'tool_slug': 'min-specs'}))
                page.get_by_role('heading', name='Solo submissions', exact=True).wait_for()
                page.screenshot(path=str(screenshots / 'archive-list.png'), full_page=True)
                page.goto(base + reverse('archive:detail', kwargs={'pk': solo.pk}))
                page.get_by_role('heading', name='Results', exact=True).wait_for()
                page.screenshot(path=str(screenshots / 'archived-result.png'), full_page=True)
                page.get_by_role('button', name='Preview Markdown', exact=True).click()
                dialog = page.get_by_role('dialog')
                dialog.wait_for()
                dialog.locator('.mdv-body h1').wait_for()
                page.screenshot(path=str(screenshots / 'markdown-preview.png'))
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            connections.close_all()
        print('Created 3 real-interface screenshots and 4 synthetic example exports.')


if __name__ == '__main__':
    main()
