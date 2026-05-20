from django.db import migrations, models


class Migration(migrations.Migration):
    """Timestamps used by the Home dashboard.

    ``auto_now_add=True`` together with ``null=True`` lets us add the column
    without prompting for a manual default and keeps historical rows as NULL
    (they are correctly treated as "unknown" by the dashboard).
    """

    dependencies = [
        ('starlift', '0007_analytics_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='speaker',
            name='created_at',
            field=models.DateTimeField(
                auto_now_add=True,
                null=True,
                verbose_name='Создан',
                help_text='Время добавления спикера (для KPI новых спикеров и ленты активности).',
            ),
        ),
        migrations.AddField(
            model_name='event',
            name='created_at',
            field=models.DateTimeField(
                auto_now_add=True,
                null=True,
                verbose_name='Создано',
                help_text='Время создания записи о мероприятии (для ленты активности).',
            ),
        ),
    ]
