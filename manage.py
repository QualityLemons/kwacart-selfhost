import os
import sys


def main():
    # On Heroku every dyno has a DYNO env var set (e.g. "web.1", "run.1").
    # Default to production settings there so that management commands
    # (migrate, collectstatic, shell, etc.) always target the Postgres
    # database without needing an explicit --settings flag.
    # Locally the DYNO var is absent, so config.settings.local is used.
    if os.environ.get('DYNO'):
        default_settings = 'config.settings.production'
    else:
        default_settings = 'config.settings.local'

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', default_settings)

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError("Django not found.") from exc

    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
