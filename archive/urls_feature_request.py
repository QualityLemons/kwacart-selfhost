from django.urls import path

from .views import feature_request

urlpatterns = [
    path('', feature_request, name='feature_request'),
]
