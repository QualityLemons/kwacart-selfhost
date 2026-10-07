from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('archive', '0009_guest_support'),
    ]

    operations = [
        migrations.AlterField(
            model_name='toolsession',
            name='md_file',
            field=models.FileField(blank=True, null=True, upload_to='archives/md/', max_length=500),
        ),
        migrations.AlterField(
            model_name='toolsession',
            name='rtf_file',
            field=models.FileField(blank=True, null=True, upload_to='archives/rtf/', max_length=500),
        ),
        migrations.AlterField(
            model_name='toolinstance',
            name='html_file',
            field=models.FileField(blank=True, null=True, upload_to='archives/html/', max_length=500),
        ),
        migrations.AlterField(
            model_name='toolinstance',
            name='md_file',
            field=models.FileField(blank=True, null=True, upload_to='archives/md/', max_length=500),
        ),
        migrations.AlterField(
            model_name='toolinstance',
            name='rtf_file',
            field=models.FileField(blank=True, null=True, upload_to='archives/rtf/', max_length=500),
        ),
    ]
