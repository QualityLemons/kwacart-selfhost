from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('archive', '0017_feature_request_feedback'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='featurerequest',
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(feedback_type='rating', rating__isnull=False)
                    | (
                        ~models.Q(feedback_type='rating')
                        & models.Q(rating__isnull=True)
                    )
                ),
                name='feedback_rating_matches_type',
            ),
        ),
    ]