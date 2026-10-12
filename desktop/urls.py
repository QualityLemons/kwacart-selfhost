from django.http import HttpResponse
from django.urls import include, path, re_path
from .media import session_attachment, unavailable_media
from .setup import first_account

urlpatterns = [
    path('desktop/health/', lambda request: HttpResponse('KwaCart ready')),
    path('desktop/setup/', first_account, name='desktop_setup'),
    # Exports must use archive's existing ownership-checked download routes.
    # Only registered session attachments have an inline media endpoint.
    re_path(
        r'^media/(?P<storage_path>kwacart/attachments/(?P<session_id>[0-9a-f-]{36})/[^/]+)$',
        session_attachment,
    ),
    re_path(r'^media/.*$', unavailable_media),
    path('', include('config.urls')),
]
