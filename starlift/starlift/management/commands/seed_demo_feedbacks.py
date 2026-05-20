"""Создать случайные отзывы (демо-данные) для спикеров и мероприятий."""
from __future__ import annotations

import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from starlift.models import Event, Feedback, Speaker


RU_COMMENTS = [
    "Сильный доклад, структурно и по делу.",
    "Много практики, забрал пару идей в работу.",
    "Сложновато для новичков, но материал ценный.",
    "Отличная подача, удерживал внимание до конца.",
    "Хотелось бы больше живых примеров из продакшена.",
    "Вопросы из зала разобрал чётко.",
    "Слайды перегружены текстом, так себе.",
    "Лучший доклад дня по теме.",
    "Темп высокий, не всё успел осмыслить.",
    "Полезный разбор ошибок и их последствий.",
    "Рекомендую коллегам из смежных команд.",
    "Чуть затянутое введение, остальное ок.",
    "Архитектурные решения объяснены ясно.",
    "Ожидал большей глубины по API.",
    "Хороший баланс теории и демо.",
    "После доклада поменял подход к логированию.",
    "Не хватило времени на Q&A.",
    "Звук/микрофон мешали, иначе бы поставил выше.",
    "Открывающий тезис запомнился — редкость.",
    "Смешал в кучу несколько тем, разброд.",
    "",
]

# Оценки 0..10: детракторы (0–6) — редко; «семёрка» — иногда; 8–10 — основная масса (~80%+).
_SCORE_VALUES = list(range(11))
_SCORE_WEIGHTS = [0.5, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75] + [12] + [34, 38, 34]


def _random_feedback_score() -> int:
    return random.choices(_SCORE_VALUES, weights=_SCORE_WEIGHTS, k=1)[0]


class Command(BaseCommand):
    help = (
        "Генерирует случайные отзывы по парам спикер–мероприятие. "
        "Оценки смещены в сторону 8–10; низкие (0–6) встречаются редко. "
        "У спикеров без событий — по умолчанию привязка к 1–3 случайным мероприятиям."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Удалить все существующие отзывы и обнулить NPS у спикеров перед генерацией.",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=None,
            help="Фиксированный seed для random (воспроизводимость).",
        )
        parser.add_argument(
            "--min-per-speaker",
            type=int,
            default=3,
            help="Минимум отзывов на одного спикера (по умолчанию 3).",
        )
        parser.add_argument(
            "--max-per-speaker",
            type=int,
            default=10,
            help="Максимум отзывов на одного спикера (по умолчанию 10).",
        )
        parser.add_argument(
            "--no-link-events",
            action="store_true",
            help="Не добавлять M2M спикер↔событие; только там, где связь уже есть.",
        )

    def handle(self, *args, **opts):
        seed = opts["seed"]
        if seed is not None:
            random.seed(seed)

        n_min = max(0, opts["min_per_speaker"])
        n_max = max(n_min, opts["max_per_speaker"])
        no_link = opts["no_link_events"]

        speakers = list(Speaker.objects.all())
        all_events = list(Event.objects.all())

        if not speakers:
            self.stdout.write(self.style.WARNING("Нет спикеров — нечего заполнять."))
            return
        if not all_events:
            self.stdout.write(self.style.WARNING("Нет мероприятий — сначала добавьте события."))
            return

        deleted = 0
        created = 0
        linked = 0

        with transaction.atomic():
            if opts["clear"]:
                deleted = Feedback.objects.all().count()
                Feedback.objects.all().delete()
                Speaker.objects.all().update(nps=0)

            for sp in speakers:
                evs = list(sp.events.all())
                if not evs and not no_link:
                    k = min(len(all_events), random.randint(1, 3))
                    picked = random.sample(all_events, k=k) if k else []
                    for ev in picked:
                        ev.speakers.add(sp)
                    evs = list(sp.events.all())
                    linked += len(picked)
                if not evs:
                    continue

                n = random.randint(n_min, n_max) if n_max > 0 else 0
                for _ in range(n):
                    ev = random.choice(evs)
                    score = _random_feedback_score()
                    comment = random.choice(RU_COMMENTS)
                    fb = Feedback.objects.create(
                        speaker=sp,
                        event=ev,
                        score=score,
                        comment=comment if comment else None,
                    )
                    # Разброс дат — для аналитики и дашборда
                    delta_days = random.randint(0, 240)
                    delta_secs = random.randint(0, 86400 - 1)
                    when = timezone.now() - timedelta(days=delta_days, seconds=delta_secs)
                    Feedback.objects.filter(pk=fb.pk).update(created_at=when)
                    created += 1

                # Пересчитать NPS по всем отзывам спикера (после bulk дат)
                sp.nps = sp.calculate_nps()
                sp.save(update_fields=["nps"])

        if opts["clear"] and deleted:
            self.stdout.write(self.style.WARNING(f"Удалено отзывов: {deleted}, NPS спикеров обнулён."))

        self.stdout.write(
            self.style.SUCCESS(
                f"Готово: добавлено отзывов {created}, новых связей спикер↔событие {linked}."
            )
        )
