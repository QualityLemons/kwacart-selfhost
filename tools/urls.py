"""URL configuration for the tools application.

Exposes three user journeys under the ``/tools/`` prefix:
- Public try-it pages (no login required): ``<slug>/try/``
- Solo drafting flow: ``<slug>/draft/``, autosave, and submit endpoints
- Collaborative session flow: session create/detail/close/status, timer
  controls, pause-reminder setting, and guest join/respond pages
"""
from django.urls import path

from . import views

app_name = 'tools'

urlpatterns = [
    path('', views.tool_catalog, name='catalog'),
    path('pathway/', views.pathway_finder, name='pathway_finder'),

    # Public try-it pages (no login required)
    path('<slug:tool_slug>/try/', views.tool_try, name='tool_try'),

    # Solo drafting flow
    path('<slug:tool_slug>/draft/', views.draft_editor, name='draft_new'),
    path('<slug:tool_slug>/draft/<int:instance_id>/', views.draft_editor, name='draft_edit'),
    path('<slug:tool_slug>/autosave/', views.autosave_endpoint, name='autosave'),
    path('submit/<int:instance_id>/', views.submit_tool, name='submit'),

    # Collaborative session flow
    path('<slug:tool_slug>/session/start/', views.session_create, name='session_create'),
    path('session/<uuid:session_id>/', views.session_detail, name='session_detail'),
    path('session/<uuid:session_id>/close/', views.session_close, name='session_close'),
    path('session/<uuid:session_id>/delete/', views.session_delete, name='session_delete'),
    path('session/<uuid:session_id>/status/', views.session_status, name='session_status'),
    path('session/<uuid:session_id>/buffer-save/', views.session_buffer_save, name='session_buffer_save'),
    path('session/<uuid:session_id>/composing/', views.session_mark_composing, name='session_mark_composing'),

    # Timer control — host only, POST required.
    # Host-only access is enforced in the view via get_object_or_404(host=request.user).
    path('session/<uuid:session_id>/timer/start/', views.timer_start, name='timer_start'),
    path('session/<uuid:session_id>/timer/reset/', views.timer_reset, name='timer_reset'),

    # Pause-reminder setting — separate from timer start/reset because it
    # persists a session-level preference, not a transient timer state.
    path('session/<uuid:session_id>/pause-reminder/',
         views.session_set_pause_reminder,
         name='session_set_pause_reminder'),

    # Inclusive Pacing — host enables a personal time multiplier for AAC users.
    path('session/<uuid:session_id>/inclusive-pacing/',
         views.session_set_inclusive_pacing,
         name='session_set_inclusive_pacing'),

    # Verbal Breakout — host signals the room to move to verbal discussion
    # while AAC participants continue composing digitally.
    path('session/<uuid:session_id>/verbal-breakout/',
         views.session_set_verbal_breakout,
         name='session_set_verbal_breakout'),

    # Facilitator Synthesis Workspace — transcription staging before export.
    path('session/<uuid:session_id>/synthesis/',
         views.synthesis_review,
         name='synthesis_review'),

    # Multimedia Input Bridge — audio/image attachments for AAC participants.
    # Upload accepts multipart/form-data; remove accepts a public_id field.
    path('session/<uuid:session_id>/attachment/upload/',
         views.session_attachment_upload,
         name='session_attachment_upload'),
    path('session/<uuid:session_id>/attachment/remove/',
         views.session_attachment_remove,
         name='session_attachment_remove'),

    # Guest participant flow — no login required; token in URL acts as access key
    path('session/<uuid:session_id>/guest/<uuid:guest_token>/', views.guest_join, name='guest_join'),
    path('session/<uuid:session_id>/guest/<uuid:guest_token>/respond/', views.guest_respond, name='guest_respond'),

    # Debug/test only — renders a bare timer widget for Playwright a11y tests
    path('_test/timer/', views.timer_test_page, name='timer_test_page'),
]
