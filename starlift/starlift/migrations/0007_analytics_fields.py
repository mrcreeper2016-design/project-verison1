from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('starlift', '0006_alter_speaker_nps_feedback_valid_score_range'),
    ]

    operations = [
        migrations.AddField(
            model_name='speaker',
            name='recommended',
            field=models.BooleanField(
                default=False,
                help_text='Флаг, выставляемый DevRel для кандидатов на выдвижение',
                verbose_name='Рекомендую к выдвижению',
            ),
        ),
        migrations.AddField(
            model_name='event',
            name='event_date',
            field=models.DateField(
                blank=True,
                null=True,
                help_text='Используется для расчётов периода. Если не заполнено — берётся дата отзывов.',
                verbose_name='Дата события (машиночитаемая)',
            ),
        ),
        migrations.AddField(
            model_name='event',
            name='topic',
            field=models.CharField(
                blank=True,
                max_length=100,
                null=True,
                verbose_name='Тема/стек события',
            ),
        ),
        migrations.AddField(
            model_name='event',
            name='is_external',
            field=models.BooleanField(
                default=False,
                help_text='True — внешняя конференция/подкаст/митап вне периметра компании.',
                verbose_name='Внешнее мероприятие',
            ),
        ),
        migrations.AddField(
            model_name='event',
            name='source',
            field=models.CharField(
                choices=[
                    ('internal', 'Внутренний отчёт'),
                    ('self', 'Самовыдвижение'),
                    ('external', 'Внешняя площадка'),
                    ('parser', 'Автопарсинг'),
                ],
                default='internal',
                max_length=32,
                verbose_name='Источник данных',
            ),
        ),
    ]
