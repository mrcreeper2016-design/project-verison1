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
        """Средняя оценка по всем отзывам зрителей + собственным оценкам мероприятий.

        Оценка спикера за событие (`SpeakerEventRating`) учитывается наравне с отзывом
        зрителя — это его взгляд на собственное участие/выступление.
        """
        fb_qs = self.feedbacks.all()
        sr_qs = self.event_ratings.all()
        if event_id:
            fb_qs = fb_qs.filter(event_id=event_id)
            sr_qs = sr_qs.filter(event_id=event_id)

        scores = list(fb_qs.values_list("score", flat=True)) + list(
            sr_qs.values_list("score", flat=True)
        )
        if not scores:
            return 0
        return round(sum(scores) / len(scores), 1)

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
    application_deadline = models.DateField(
        null=True,
        blank=True,
        verbose_name="Дедлайн подачи заявок",
        help_text="Если задан и не прошёл — спикеры могут подавать заявки сами. Иначе только через приглашение DevRel.",
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

    def can_self_submit(self) -> bool:
        """Спикер может сам подать заявку, только если дедлайн задан и не прошёл."""
        if self.application_deadline is None:
            return False
        from django.utils import timezone
        return self.application_deadline >= timezone.localdate()


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


class EventInvitation(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_ACCEPTED = 'accepted'
    STATUS_DECLINED = 'declined'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Ожидает ответа'),
        (STATUS_ACCEPTED, 'Принято'),
        (STATUS_DECLINED, 'Отклонено'),
        (STATUS_CANCELLED, 'Отменено DevRel'),
    ]

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='invitations')
    speaker = models.ForeignKey(Speaker, on_delete=models.CASCADE, related_name='invitations')
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='sent_event_invitations',
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    message = models.TextField(blank=True, default='')
    decline_reason = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'starlift_event_invitation'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', '-created_at'])]
        constraints = [
            models.UniqueConstraint(
                fields=['event', 'speaker'],
                condition=models.Q(status='pending'),
                name='uniq_pending_event_invitation',
            ),
        ]

    def __str__(self):
        return f"EventInvitation<{self.event_id}/{self.speaker_id}/{self.status}>"


class SpeakerApplication(models.Model):
    """Заявка пользователя-гостя на получение роли спикера.

    Создаётся после email-верификации, когда гость заполняет форму
    профиля. Маршрутизируется DevRel'у по `company` (см. notifications_api
    и event_requests_view). Approve → роль становится `speaker`, Speaker-
    карточка создаётся/привязывается. Reject → пользователь остаётся
    гостем и может переподать.
    """

    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'На рассмотрении'),
        (STATUS_APPROVED, 'Одобрено'),
        (STATUS_REJECTED, 'Отклонено'),
    ]

    applicant = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='speaker_application',
    )
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True,
    )
    company = models.CharField(max_length=200, blank=True, default='')
    city = models.CharField(max_length=100, blank=True, default='')
    stack = models.CharField(max_length=200, blank=True, default='')
    description = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='reviewed_speaker_applications',
    )
    rejection_reason = models.TextField(blank=True, default='')
    resulting_speaker = models.ForeignKey(
        Speaker,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+',
    )

    class Meta:
        db_table = 'starlift_speaker_application'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', '-created_at'])]

    def __str__(self):
        return f"SpeakerApplication<{self.applicant.username} / {self.status}>"


class SpeakerEventRating(models.Model):
    """Спикер ставит оценку прошедшему мероприятию, в котором участвовал.

    Не влияет на NPS спикеров (это отдельная метрика самого события глазами
    выступавших). Одна оценка на пару (speaker, event); повторный сабмит
    обновляет существующую запись.
    """

    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="speaker_ratings",
        verbose_name="Мероприятие",
    )
    speaker = models.ForeignKey(
        Speaker,
        on_delete=models.CASCADE,
        related_name="event_ratings",
        verbose_name="Спикер",
    )
    score = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(10)],
        verbose_name="Оценка (0–10)",
    )
    comment = models.TextField(blank=True, default="", verbose_name="Комментарий")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "starlift_speaker_event_rating"
        unique_together = [("event", "speaker")]
        indexes = [models.Index(fields=["event", "speaker"])]
        verbose_name = "Оценка мероприятия от спикера"
        verbose_name_plural = "Оценки мероприятий от спикеров"

    def __str__(self):
        return f"{self.speaker.name} → {self.event.title}: {self.score}/10"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        nps_value = self.speaker.calculate_nps()
        if nps_value is not None:
            self.speaker.nps = nps_value
            self.speaker.save(update_fields=["nps"])

    def delete(self, *args, **kwargs):
        speaker = self.speaker
        super().delete(*args, **kwargs)
        nps_value = speaker.calculate_nps()
        if nps_value is not None:
            speaker.nps = nps_value
            speaker.save(update_fields=["nps"])


class SpeakerLike(models.Model):
    """Per-user heart/favorite on a Speaker. Toggled from the speaker modal."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="speaker_likes",
    )
    speaker = models.ForeignKey(
        Speaker,
        on_delete=models.CASCADE,
        related_name="likes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "starlift_speaker_like"
        unique_together = [("user", "speaker")]
        indexes = [models.Index(fields=["user", "speaker"])]

    def __str__(self):
        return f"{self.user_id} ♥ {self.speaker_id}"
