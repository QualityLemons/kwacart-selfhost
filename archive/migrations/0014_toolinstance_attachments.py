from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('archive', '0013_toolsession_inclusive_pacing'),
    ]

    operations = [
        migrations.AddField(
            model_name='toolinstance',
            name='attachments',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text=(
                    'Multimedia attachments added by this participant (audio clips, '
                    'symbol-board images, etc.). Each entry is a dict with keys: '
                    'type ("audio" | "image"), url (Cloudinary secure_url), '
                    'public_id, name.'
                ),
            ),
        ),
    ]
