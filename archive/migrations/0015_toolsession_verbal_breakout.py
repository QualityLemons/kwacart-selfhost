from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('archive', '0014_toolinstance_attachments'),
    ]

    operations = [
        migrations.AddField(
            model_name='toolsession',
            name='verbal_breakout_active',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'When true, the host has signalled the room to start a verbal '
                    'breakout. Non-composing participants are prompted to join the '
                    'discussion; AAC-composing participants are reassured their '
                    'digital submission window remains open.'
                ),
            ),
        ),
    ]
