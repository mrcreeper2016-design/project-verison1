import uuid
from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


class Speaker(models.Model):
    """Speaker card. Field ``status`` reflects account linkage only (see ``save``)."""

    STATUS_UNAUTHORIZED = "unauthorized"
    STATUS_AUTHORIZED = "authorized"
    STATUS_CHOICES = [
        (STATUS_UNAUTHORIZED, "Неавторизован"),
        (STATUS_AUTHORIZED, "Авторизован"),
    ]

    name = models.CharField(max_length=200)
    sub = models.CharField(max_length=200)
    stack = models.TextField(blank=True, default="")
    city = models.CharField(max_length=100)
    status = models.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        default=STATUS_UNAUTHORIZED,
        verbose_name="Статус",
        help_text="Неавторизован — нет привязки к аккаунту; Авторизован — связан с пользователем платформы.",
    )
    nps = models.FloatField(default=0.0)
    img = models.CharField(max_length=100)
    avatar = models.ImageField(upload_to="avatars/speakers/", null=True, blank=True)
    recommended = models.BooleanField(
        default=False,
        verbose_name="Рекомендую к выдвижению",
        help_text="Флаг, выставляемый DevRel для кандидатов на выдвижение",
    )
    bio = models.TextField(
        blank=True,
        default="",
        verbose_name="О себе",
        help_text="Редактируется самим спикером из личного кабинета.",
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="speaker",
        verbose_name="Привязанный пользователь",
        help_text="Связка устанавливается вручную администратором.",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        null=True,
        verbose_name="Создан",
        help_text="Время добавления спикера (для KPI новых спикеров и ленты активности).",
    )

    class Meta:
        db_table = 'starlift_speaker'

    def save(self, *args, **kwargs):
        self.status = self.STATUS_AUTHORIZED if self.user_id else self.STATUS_UNAUTHORIZED
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            update_fields = list(update_fields)
            if "status" not in update_fields:
                update_fields.append("status")
            kwargs["update_fields"] = update_fields
        super().save(*args, **kwargs)

    @property
    def link_status_display(self) -> str:
        """Статус для UI: только факт привязки к аккаунту (не сырое поле ``status``)."""
        labels = dict(self.STATUS_CHOICES)
        return labels[self.STATUS_AUTHORIZED] if self.user_id else labels[self.STATUS_UNAUTHORIZED]

    @property
    def card_avatar_url(self) -> str:
        """Photo stored on the speaker card only (ImageField + ``img``), not the linked account."""
        if self.avatar:
            try:
                return self.avatar.url
            except ValueError:
                pass
        if self.img:
            if self.img.startswith("/media/") or self.img.startswith("http"):
                return self.img
            return f"https://i.pravatar.cc/150?img={self.img}"
        return ""

    @property
    def avatar_url(self) -> str:
        if self.user_id:
            from django.apps import apps

            Profile = apps.get_model("accounts", "UserProfile")
            try:
                prof = Profile.objects.get(pk=self.user_id)
                if prof.avatar and getattr(prof.avatar, "name", ""):
                    try:
                        return prof.avatar.url
                    except ValueError:
                        pass
            except Profile.DoesNotExist:
                pass
        return self.card_avatar_url

    def calculate_nps(self, event_id=None):
        qs = self.feedbacks.all()
        if event_id:
            qs = qs.filter(event_id=event_id)

        from django.db.models import Avg
        result = qs.aggregate(avg=Avg('score'))
        avg = result['avg']
        if avg is None:
            return 0
        return round(avg, 1)

    def __str__(self):
        return self.name


class Event(models.Model):
    SOURCE_CHOICES = [
        ('internal', 'Внутренний отчёт'),
        ('self', 'Самовыдвижение'),
        ('external', 'Внешняя площадка'),
        ('parser', 'Автопарсинг'),
    ]

    STATUS_CHOICES = [
        ('past', 'Прошедшее'),
        ('future', 'Предстоящее'),
    ]

    title = models.CharField(max_length=200)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='future')
    date = models.CharField(max_length=100, null=True, blank=True)
    event_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Дата события (машиночитаемая)",
        help_text="Используется для расчётов периода. Если не заполнено — берётся дата отзывов.",
    )
    location = models.CharField(max_length=200, null=True, blank=True)
    link = models.CharField(max_length=500, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    schedule = models.TextField(null=True, blank=True)
    topic = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Тема/стек события",
    )
    is_external = models.BooleanField(
        default=False,
        verbose_name="Внешнее мероприятие",
        help_text="True — внешняя конференция/подкаст/митап вне периметра компании.",
    )
    source = models.CharField(
        max_length=32,
        choices=SOURCE_CHOICES,
        default='internal',
        verbose_name="Источник данных",
    )
    speakers = models.ManyToManyField(Speaker, related_name='events')
    created_at = models.DateTimeField(
        auto_now_add=True,
        null=True,
        verbose_name="Создано",
        help_text="Время создания записи о мероприятии (для ленты активности).",
    )

    class Meta:
        db_table = 'starlift_event'

    def __str__(self):
        return f"{self.title} ({self.status})"


class Feedback(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, verbose_name="ID")
    speaker = models.ForeignKey(Speaker, on_delete=models.CASCADE, related_name='feedbacks', verbose_name="Спикер")
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='feedbacks', verbose_name="Мероприятие")
    score = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(10)], verbose_name="Оценка")
    comment = models.TextField(blank=True, null=True, verbose_name="Комментарий")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP адрес")
    session_key = models.CharField(max_length=40, null=True, blank=True, verbose_name="Ключ сессии")

    class Meta:
        db_table = 'starlift_feedback'
        verbose_name = 'Обратная связь'
        verbose_name_plural = 'Обратная связь'
        constraints = [
            models.CheckConstraint(condition=models.Q(score__gte=0) & models.Q(score__lte=10), name='valid_score_range')
        ]

    def __str__(self):
        return f"Feedback for {self.speaker.name} at {self.event.title} - Score: {self.score}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        nps_value = self.speaker.calculate_nps()
        if nps_value is not None:
            self.speaker.nps = nps_value
            self.speaker.save(update_fields=['nps'])


class EventRequest(models.Model):
    KIND_CREATE = 'create'
    KIND_JOIN = 'join'
    KIND_CHOICES = [
        (KIND_CREATE, 'Создание мероприятия'),
        (KIND_JOIN, 'Заявка на участие'),
    ]

    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'На рассмотрении'),
        (STATUS_APPROVED, 'Одобрено'),
        (STATUS_REJECTED, 'Отклонено'),
    ]

    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    speaker = models.ForeignKey(Speaker, on_delete=models.CASCADE, related_name='event_requests')
    event = models.ForeignKey(Event, on_delete=models.SET_NULL, null=True, blank=True, related_name='join_requests')

    # Тема/описание доклада (для обоих типов заявок)
    topic = models.CharField(max_length=200, blank=True, default='')
    comment = models.TextField(blank=True, default='')

    # Поля для kind='create'
    proposed_title = models.CharField(max_length=200, blank=True, default='')
    proposed_description = models.TextField(blank=True, default='')
    proposed_event_date = models.DateField(null=True, blank=True)
    proposed_location = models.CharField(max_length=200, blank=True, default='')
    proposed_link = models.CharField(max_length=500, blank=True, default='')

    rejection_reason = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='reviewed_event_requests',
    )

    class Meta:
        db_table = 'starlift_event_request'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', '-created_at'])]

    def __str__(self):
        return f"{self.get_kind_display()} от {self.speaker.name} ({self.status})"
