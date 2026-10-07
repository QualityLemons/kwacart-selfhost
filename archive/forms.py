"""Forms for the archive application.

These are kept here rather than inside the view functions so that they follow
Django's convention of defining forms in a dedicated ``forms.py`` module.
"""
from django import forms

from .models import FeatureRequest


class FeedbackForm(forms.ModelForm):
    """Public feedback form with type-dependent server-side validation."""

    feedback_type = forms.ChoiceField(
        choices=FeatureRequest.FEEDBACK_TYPES, required=False, initial='feature',
    )
    name = forms.CharField(
        label='Your name (optional)', max_length=200, required=False,
        widget=forms.TextInput(attrs={'placeholder': 'e.g. Sarah'}),
    )
    email = forms.EmailField(
        label='Your email (optional)',
        required=False,
        widget=forms.EmailInput(attrs={'placeholder': 'you@example.com'}),
        help_text="We'll only use this if we need to follow up about your feedback.",
    )
    title = forms.CharField(
        label='Title',
        max_length=300,
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'e.g. Export session results as PDF',
        }),
    )
    description = forms.CharField(
        label='Tell us more',
        max_length=4000,
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 5,
            'maxlength': 4000,
            'placeholder': (
                'What problem would this solve? '
                'How do you imagine it working?'
            ),
        }),
    )
    rating = forms.TypedChoiceField(
        choices=[('', 'Select a rating')] + [(number, str(number)) for number in range(1, 6)],
        coerce=int,
        empty_value=None,
        required=False,
    )

    class Meta:
        model = FeatureRequest
        fields = ('feedback_type', 'rating', 'name', 'email', 'title', 'description')

    def clean(self):
        cleaned = super().clean()
        feedback_type = cleaned.get('feedback_type') or 'feature'
        cleaned['feedback_type'] = feedback_type

        if feedback_type == 'rating':
            if cleaned.get('rating') is None:
                self.add_error('rating', 'Please choose a rating from 1 to 5.')
        else:
            if cleaned.get('rating') is not None:
                self.add_error('rating', 'A rating can only be submitted as rating feedback.')
            if not (cleaned.get('title') or '').strip():
                self.add_error('title', 'Please provide a short title.')

        if feedback_type in {'feature', 'bug', 'experience'}:
            if not (cleaned.get('description') or '').strip():
                self.add_error('description', 'Please tell us more.')
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.name = (instance.name or '').strip()
        instance.email = (instance.email or '').strip().lower()
        instance.title = (instance.title or '').strip()
        instance.description = (instance.description or '').strip()
        if instance.feedback_type == 'rating':
            instance.title = instance.title or 'Rating feedback'
        if commit:
            instance.save()
        return instance


# Historical import kept for callers and tests using the old form name.
FeatureRequestForm = FeedbackForm
