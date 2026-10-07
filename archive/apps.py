from django.apps import AppConfig


class ArchiveConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'archive'

    def ready(self):
        from . import signals  # noqa: F401
