from django.conf import settings
from django.http import HttpResponse
from django.urls import include, path, re_path
from django.views.static import serve
from .setup import first_account

urlpatterns = [
    path('desktop/health/', lambda request: HttpResponse('KwaCart ready')),
    path('desktop/setup/', first_account, name='desktop_setup'),
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
    path('', include('config.urls')),
]
