from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('archive', '0010_increase_file_field_max_length'),
    ]

    operations = [
        migrations.AddField(
            model_name='toolinstance',
            name='composing_heartbeat_at',
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text=(
                    'Set by session_mark_composing when an AAC user signals they are '
                    'composing in external software. Expires after 15 seconds of inactivity.'
                ),
            ),
        ),
    ]
