from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('archive', '0011_toolinstance_composing_heartbeat_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='toolsession',
            name='pairing_code',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                help_text=(
                    'Three-digit companion-pairing code displayed alongside the QR code. '
                    'Valid while the session is open; cleared on close.'
                ),
                max_length=3,
            ),
            preserve_default=False,
        ),
    ]
