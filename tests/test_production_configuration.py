"""Deployment-safety checks for production settings."""

import os
import subprocess
import sys

import pytest


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
VALID_DATABASE_URL = "postgresql://user:password@db.example.test:5432/app"
VALID_CLOUDINARY_URL = "cloudinary://key:secret@example"


def load_production_settings(**overrides):
    env = os.environ.copy()
    env.update(
        {
            "DJANGO_SETTINGS_MODULE": "config.settings.production",
            "SECRET_KEY": "test-only-secret-key",
            "DATABASE_URL": VALID_DATABASE_URL,
            "CLOUDINARY_URL": VALID_CLOUDINARY_URL,
        }
    )
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value

    return subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from django.conf import settings; "
                "print(settings.DATABASES['default']['ENGINE']); "
                "print(settings.STORAGES['default']['BACKEND']); "
                "print(settings.FILE_UPLOAD_MAX_MEMORY_SIZE); "
                "print(settings.DATA_UPLOAD_MAX_MEMORY_SIZE)"
            ),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"DATABASE_URL": None}, "DATABASE_URL is required"),
        ({"DATABASE_URL": "sqlite:///production.sqlite3"}, "must point to PostgreSQL"),
        ({"CLOUDINARY_URL": None}, "CLOUDINARY_URL is required"),
        (
            {"CLOUDINARY_URL": "https://example.test/media"},
            "must contain a Cloudinary API key, secret, and cloud name",
        ),
        (
            {"CLOUDINARY_URL": "cloudinary://example"},
            "must contain a Cloudinary API key, secret, and cloud name",
        ),
    ],
)
def test_production_refuses_unsafe_durable_storage(overrides, message):
    result = load_production_settings(**overrides)

    assert result.returncode != 0
    assert message in result.stderr


def test_production_uses_durable_backends_and_explicit_request_limits():
    result = load_production_settings()

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "django.db.backends.postgresql",
        "cloudinary_storage.storage.RawMediaCloudinaryStorage",
        str(2 * 1024 * 1024),
        str(10 * 1024 * 1024),
    ]


def test_replit_deployment_is_autoscale_gunicorn_with_production_settings():
    replit_config = os.path.join(PROJECT_ROOT, ".replit")
    with open(replit_config, encoding="utf-8") as config_file:
        config = config_file.read()

    assert 'deploymentTarget = "autoscale"' in config
    assert (
        'run = ["gunicorn", "--bind=0.0.0.0:5000", "--reuse-port", '
        '"config.wsgi:application"]'
    ) in config
    assert 'DJANGO_SETTINGS_MODULE = "config.settings.production"' in config
    assert "cloudinary://" not in config