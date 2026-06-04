from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_backfill_consent'),
    ]

    operations = [
        migrations.AlterField(
            model_name='invite',
            name='role',
            field=models.CharField(
                choices=[
                    ('admin', 'Администратор'),
                    ('devrel', 'DevRel'),
                    ('speaker', 'Спикер'),
                    ('guest', 'Гость'),
                ],
                default='speaker',
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name='userprofile',
            name='role',
            field=models.CharField(
                choices=[
                    ('admin', 'Администратор'),
                    ('devrel', 'DevRel'),
                    ('speaker', 'Спикер'),
                    ('guest', 'Гость'),
                ],
                default='speaker',
                max_length=16,
            ),
        ),
    ]
