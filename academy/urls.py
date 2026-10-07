from django.urls import path

from . import views


urlpatterns = [
    path('', views.academy_dashboard, name='academy_dashboard'),
    path(
        'safeguarding/',
        views.academy_safeguarding,
        name='academy_safeguarding',
    ),
    path('<slug:slug>/', views.academy_lesson, name='academy_lesson'),
    path('<slug:slug>/complete/', views.academy_complete, name='academy_complete'),
]