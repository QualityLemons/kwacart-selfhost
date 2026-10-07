from django.conf import settings
from django.db import models


class AcademyLessonProgress(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='academy_progress',
    )
    lesson_slug = models.SlugField(max_length=80)
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('completed_at',)
        constraints = [
            models.UniqueConstraint(
                fields=('user', 'lesson_slug'),
                name='unique_academy_lesson_progress',
            ),
        ]

    def __str__(self):
        return f'{self.user} completed {self.lesson_slug}'