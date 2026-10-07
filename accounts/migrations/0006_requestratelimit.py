from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0005_organisationdatatransferrequest_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='RequestRateLimit',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                ('key', models.CharField(max_length=64, unique=True)),
                (
                    'window_started',
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                ('attempts', models.PositiveIntegerField(default=0)),
                (
                    'locked_until',
                    models.DateTimeField(blank=True, null=True),
                ),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Request rate limit',
                'verbose_name_plural': 'Request rate limits',
            },
        ),
    ]