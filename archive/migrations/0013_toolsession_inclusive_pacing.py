from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('archive', '0012_toolsession_pairing_code'),
    ]

    operations = [
        migrations.AddField(
            model_name='toolsession',
            name='inclusive_pacing',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'When true, participants see an option to activate a personal '
                    'extended countdown at inclusive_pacing_multiplier × the group time.'
                ),
            ),
        ),
        migrations.AddField(
            model_name='toolsession',
            name='inclusive_pacing_multiplier',
            field=models.IntegerField(
                choices=[(3, '3×'), (5, '5×')],
                default=3,
                help_text='Time multiplier offered to participants when inclusive pacing is active.',
            ),
        ),
    ]
