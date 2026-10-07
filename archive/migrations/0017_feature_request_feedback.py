import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('archive', '0016_toolinstance_data_owner_toolsession_data_owner_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='featurerequest',
            name='title',
            field=models.CharField(blank=True, help_text='A short summary of the feature being requested.', max_length=300),
        ),
        migrations.AlterField(
            model_name='featurerequest',
            name='description',
            field=models.TextField(blank=True, help_text='More detail: what problem does it solve, how would it work?'),
        ),
        migrations.AddField(
            model_name='featurerequest',
            name='feedback_type',
            field=models.CharField(choices=[('feature', 'Feature request'), ('bug', 'Bug report'), ('experience', 'Experience feedback'), ('rating', 'Rating')], db_index=True, default='feature', max_length=20),
        ),
        migrations.AddField(
            model_name='featurerequest',
            name='interaction_mode',
            field=models.CharField(blank=True, choices=[('try', 'Try tool'), ('solo', 'Solo'), ('session', 'Session'), ('guest', 'Guest')], max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='featurerequest',
            name='rating',
            field=models.PositiveSmallIntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(5)]),
        ),
        migrations.AddField(
            model_name='featurerequest',
            name='review_status',
            field=models.CharField(choices=[('new', 'New'), ('reviewing', 'Reviewing'), ('planned', 'Planned'), ('resolved', 'Resolved'), ('closed', 'Closed')], db_index=True, default='new', max_length=20),
        ),
        migrations.AddField(
            model_name='featurerequest',
            name='reviewed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='featurerequest',
            name='source',
            field=models.CharField(choices=[('portal', 'Feedback portal'), ('tool_completion', 'Tool completion'), ('session_end', 'Session end'), ('knowledge_bank', 'Knowledge Bank')], db_index=True, default='portal', max_length=20),
        ),
        migrations.AddField(
            model_name='featurerequest',
            name='submitter',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='submitted_feedback', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='featurerequest',
            name='tool_slug',
            field=models.SlugField(blank=True, max_length=100, null=True),
        ),
        migrations.AlterModelOptions(
            name='featurerequest',
            options={'ordering': ['-submitted_at'], 'verbose_name': 'Feedback', 'verbose_name_plural': 'Feedback'},
        ),
        migrations.AddConstraint(
            model_name='featurerequest',
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(rating__isnull=True)
                    | models.Q(rating__gte=1, rating__lte=5)
                ),
                name='feedback_rating_between_1_and_5',
            ),
        ),
    ]