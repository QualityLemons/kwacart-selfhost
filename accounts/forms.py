from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm

from .models import OrganisationMemberDataPolicy, User


class CustomUserCreationForm(UserCreationForm):
    """User creation form for the email-as-username model.

    Inherits from Django's built-in ``UserCreationForm`` but restricts the
    fields to ``email`` only — there is no username field on this model.
    """

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('email',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].widget.attrs.update({
            'autocomplete': 'email',
            'inputmode': 'email',
            'enterkeyhint': 'next',
        })
        self.fields['password1'].widget.attrs['enterkeyhint'] = 'next'
        self.fields['password2'].widget.attrs['enterkeyhint'] = 'done'

    def save(self, commit=True):
        """Public registrations start locked until Stripe confirms payment."""
        user = super().save(commit=False)
        user.plan = 'free'
        user.subscription_status = 'none'
        if commit:
            user.save()
        return user


class CustomUserChangeForm(UserChangeForm):
    """User change form for the admin edit view.

    Mirrors ``CustomUserCreationForm``: exposes only the ``email`` field,
    matching the email-as-username model used throughout the project.
    """

    class Meta:
        model = User
        fields = ('email',)


class ProfileEmailForm(forms.ModelForm):
    """Form that lets an authenticated user update their own email address.

    Validates that the new address is not already registered to a different
    account before saving.
    """

    class Meta:
        model = User
        fields = ('email',)
        widgets = {
            'email': forms.EmailInput(attrs={
                'autocomplete': 'email',
                'placeholder': 'you@example.com',
            }),
        }

    def clean_email(self):
        email = self.cleaned_data['email'].lower().strip()
        if User.objects.exclude(pk=self.instance.pk).filter(email=email).exists():
            raise forms.ValidationError(
                'That email address is already registered to another account.'
            )
        return email


class OrganisationMemberPolicyForm(forms.Form):
    """Select an existing same-domain account and propose its data policy."""

    email = forms.EmailField(
        label='Team member email',
        widget=forms.EmailInput(attrs={
            'autocomplete': 'email',
            'placeholder': 'colleague@your-organisation.org',
        }),
    )
    policy = forms.ChoiceField(
        label='Where should their KwaCart work be retained?',
        choices=OrganisationMemberDataPolicy.OWNERSHIP_CHOICES,
        widget=forms.RadioSelect,
    )

    def __init__(self, *args, owner, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner
        self.member = None

    def clean_email(self):
        email = self.cleaned_data['email'].lower().strip()
        try:
            member = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            raise forms.ValidationError(
                'That person needs to create a KwaCart account before you can add them.'
            )
        if member.pk == self.owner.pk:
            raise forms.ValidationError('Use a different team member account.')
        if not self.owner.email_domain or member.email_domain != self.owner.email_domain:
            raise forms.ValidationError(
                'Team members must use the same email domain as the Organisation account.'
            )
        if member.organisation_owner_id not in {None, self.owner.pk}:
            raise forms.ValidationError(
                'That account already belongs to another Organisation account.'
            )
        if (
            member.stripe_subscription_id
            or member.stripe_customer_id
            or (
                member.plan in {'solo', 'organisation'}
                and member.subscription_status in {'active', 'trialing'}
            )
        ):
            raise forms.ValidationError(
                'That account has its own paid subscription and cannot be added.'
            )
        self.member = member
        return email
