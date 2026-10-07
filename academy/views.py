from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .content import LESSONS, LESSONS_BY_SLUG
from .models import AcademyLessonProgress


def _lesson_url(slug):
    return reverse('academy_lesson', args=(slug,))


def _lesson_view_data(lesson, completed_slugs=frozenset()):
    item = dict(lesson)
    item['url'] = _lesson_url(lesson['slug'])
    item['completed'] = lesson['slug'] in completed_slugs
    return item


def _action_url(lesson):
    route = lesson.get('action_route')
    if not route:
        return ''
    url = reverse(route, args=lesson.get('action_args', ()))
    return url + lesson.get('action_query', '')


def academy_dashboard(request):
    completed_slugs = set()
    if request.user.is_authenticated:
        completed_slugs = set(
            AcademyLessonProgress.objects.filter(user=request.user)
            .values_list('lesson_slug', flat=True)
        )
    lessons = [
        _lesson_view_data({**lesson, 'number': index}, completed_slugs)
        for index, lesson in enumerate(LESSONS, start=1)
    ]
    completed_count = sum(item['completed'] for item in lessons)
    total_count = len(lessons)
    next_lesson = next((item for item in lessons if not item['completed']), None)
    return render(request, 'academy/index.html', {
        'lessons': lessons,
        'completed_count': completed_count,
        'total_count': total_count,
        'percent': round(completed_count / total_count * 100),
        'next_lesson': next_lesson,
        'is_complete': completed_count == total_count,
        'authenticated': request.user.is_authenticated,
    })


def academy_safeguarding(request):
    return redirect(
        'academy_lesson',
        slug='safeguarding-children-and-adults-at-risk',
        permanent=True,
    )


def academy_lesson(request, slug):
    lesson_source = LESSONS_BY_SLUG.get(slug)
    if lesson_source is None:
        raise Http404('Academy lesson not found')
    completed_slugs = set()
    if request.user.is_authenticated:
        completed_slugs = set(
            AcademyLessonProgress.objects.filter(user=request.user)
            .values_list('lesson_slug', flat=True)
        )
    position = next(index for index, item in enumerate(LESSONS) if item['slug'] == slug)
    lesson = _lesson_view_data(
        {**lesson_source, 'number': position + 1},
        completed_slugs,
    )
    lesson['action_url'] = _action_url(lesson_source)
    previous_lesson = (
        _lesson_view_data({**LESSONS[position - 1], 'number': position})
        if position > 0 else None
    )
    next_lesson = (
        _lesson_view_data({**LESSONS[position + 1], 'number': position + 2})
        if position + 1 < len(LESSONS) else None
    )
    completed_count = len(completed_slugs.intersection(LESSONS_BY_SLUG))
    return render(request, 'academy/lesson.html', {
        'lesson': lesson,
        'completed': slug in completed_slugs,
        'authenticated': request.user.is_authenticated,
        'previous_lesson': previous_lesson,
        'next_lesson': next_lesson,
        'completed_count': completed_count,
        'total_count': len(LESSONS),
        'percent': round(completed_count / len(LESSONS) * 100),
    })


@login_required
@require_POST
def academy_complete(request, slug):
    if slug not in LESSONS_BY_SLUG:
        raise Http404('Academy lesson not found')
    AcademyLessonProgress.objects.get_or_create(
        user=request.user,
        lesson_slug=slug,
    )
    position = next(index for index, item in enumerate(LESSONS) if item['slug'] == slug)
    if position + 1 < len(LESSONS):
        return redirect('academy_lesson', slug=LESSONS[position + 1]['slug'])
    return redirect('academy_dashboard')