from django.contrib import admin

from .models import AcademyLessonProgress


@admin.register(AcademyLessonProgress)
class AcademyLessonProgressAdmin(admin.ModelAdmin):
    list_display = ('user', 'lesson_slug', 'completed_at')
    list_filter = ('lesson_slug',)
    search_fields = ('user__email', 'lesson_slug')
    readonly_fields = ('user', 'lesson_slug', 'completed_at')