import requests
from io import BytesIO
from PIL import Image
from django import forms
from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError
from .models import Speaker, Feedback

class FeedbackForm(forms.ModelForm):
    class Meta:
        model = Feedback
        fields = ['score', 'comment']
        widgets = {
            'score': forms.HiddenInput(),
            'comment': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Оставьте свой комментарий (необязательно)',
                'style': 'width: 100%; border-radius: 12px; padding: 12px; background: rgba(255, 255, 255, 0.05); color: #fff; border: 1px solid rgba(255, 255, 255, 0.1); min-height: 100px; resize: vertical; margin-top: 20px;'
            }),
        }

class SpeakerForm(forms.ModelForm):
    upload_image = forms.ImageField(required=False)
    image_url = forms.URLField(required=False, widget=forms.URLInput(attrs={'placeholder': 'Или вставьте ссылку на изображение'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['img'].required = False
        self._processed_avatar_file = None

    class Meta:
        model = Speaker
        # Whitelist-style: only fields explicitly listed are editable from this
        # admin-only form. `bio` is edited by speakers themselves via /profile/,
        # `user` is linked via the admin console, and `nps` is derived.
        fields = ['name', 'stack', 'city', 'img', 'recommended']
        labels = {
            'name': 'Имя и Фамилия',
            'stack': 'Описание',
            'city': 'Город',
        }
        widgets = {
            'name': forms.TextInput(attrs={'class': 'search-box', 'style': 'width: 100%; border-radius: 12px; padding: 10px; border: 1px solid var(--glass-border);'}),
            'stack': forms.TextInput(attrs={'class': 'search-box', 'style': 'width: 100%; border-radius: 12px; padding: 10px; border: 1px solid var(--glass-border);'}),
            'city': forms.TextInput(attrs={'class': 'search-box', 'style': 'width: 100%; border-radius: 12px; padding: 10px; border: 1px solid var(--glass-border);'}),
            'img': forms.HiddenInput(),
        }

    def clean(self):
        cleaned_data = super().clean()
        upload_image = cleaned_data.get('upload_image')
        image_url = cleaned_data.get('image_url')
        img_field = cleaned_data.get('img')

        image_data = None

        if upload_image:
            if upload_image.size > 10 * 1024 * 1024:
                raise ValidationError("Размер файла не должен превышать 10 МБ.")
            
            ext = upload_image.name.split('.')[-1].lower()
            if ext not in ['jpg', 'jpeg', 'png', 'webp']:
                raise ValidationError("Допустимые форматы: JPG, PNG, WEBP.")
            
            image_data = upload_image.read()
        
        elif image_url:
            try:
                response = requests.get(image_url, timeout=10)
                if response.status_code == 200:
                    image_data = response.content
                else:
                    raise ValidationError("Не удалось скачать изображение по ссылке.")
            except Exception:
                raise ValidationError("Недействительная ссылка на изображение.")

        if image_data:
            try:
                img = Image.open(BytesIO(image_data))
                
                # Обрезка до квадрата (aspect fill)
                width, height = img.size
                min_dim = min(width, height)
                left = (width - min_dim) / 2
                top = (height - min_dim) / 2
                right = (width + min_dim) / 2
                bottom = (height + min_dim) / 2
                img = img.crop((left, top, right, bottom))
                
                # Ресайз до 800x800
                img = img.resize((800, 800), Image.Resampling.LANCZOS)
                
                # Сохранение в webp
                import uuid
                filename = f"avatar_{uuid.uuid4().hex[:8]}.webp"

                # Конвертируем в RGB если изображение с альфа-каналом и сохраняем
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')

                buffer = BytesIO()
                img.save(buffer, format='WEBP')
                buffer.seek(0)
                self._processed_avatar_file = ContentFile(buffer.read(), name=filename)
                if not img_field and not getattr(self.instance, "img", ""):
                    cleaned_data['img'] = "uploaded"

            except Exception as e:
                raise ValidationError(f"Ошибка при обработке изображения: {str(e)}")
        elif not img_field and not getattr(self.instance, "img", "") and not getattr(self.instance, "avatar", None):
            import random
            cleaned_data['img'] = str(random.randint(1, 70))

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self._processed_avatar_file is not None:
            instance.avatar.save(self._processed_avatar_file.name, self._processed_avatar_file, save=False)
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class SpeakerSelfEditForm(SpeakerForm):
    """Form for speaker-owned profile edits.

    The speaker can update profile details, but not ownership, NPS, feedback,
    or admin flags. Name is controlled from the linked auth user.
    """

    class Meta(SpeakerForm.Meta):
        fields = ['sub', 'stack', 'city', 'bio', 'img']
        labels = {
            'sub': 'Подзаголовок',
            'stack': 'Описание',
            'city': 'Город',
            'bio': 'О себе',
        }
        widgets = {
            'sub': forms.TextInput(attrs={'class': 'search-box', 'style': 'width: 100%; border-radius: 12px; padding: 10px; border: 1px solid var(--glass-border);'}),
            'stack': forms.TextInput(attrs={'class': 'search-box', 'style': 'width: 100%; border-radius: 12px; padding: 10px; border: 1px solid var(--glass-border);'}),
            'city': forms.TextInput(attrs={'class': 'search-box', 'style': 'width: 100%; border-radius: 12px; padding: 10px; border: 1px solid var(--glass-border);'}),
            'bio': forms.Textarea(attrs={'class': 'search-box', 'style': 'width: 100%; border-radius: 12px; padding: 10px; border: 1px solid var(--glass-border); min-height: 120px;'}),
            'img': forms.HiddenInput(),
        }


# ─────────────────────────────────────────────────────────────────────
# Self-submitted past event (portfolio entry) — verified by DevRel.
# ─────────────────────────────────────────────────────────────────────

import re
from datetime import date as _date_cls

from django.utils import timezone


_VIDEO_HOST_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:youtube\.com|youtu\.be|vk\.com|vkvideo\.ru|rutube\.ru)/",
    re.IGNORECASE,
)
_PRESENTATION_EXTS = ('.pdf', '.ppt', '.pptx')
_PRESENTATION_TYPES = {
    'application/pdf',
    'application/vnd.ms-powerpoint',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
}
_PHOTO_TYPES = {'image/jpeg', 'image/png', 'image/webp'}

MAX_PRESENTATION_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_PHOTO_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_PHOTOS = 10


class SpeakerEventUploadForm(forms.Form):
    """Форма «загрузить мероприятие» в личном кабинете спикера.

    Сценарий — портфолио: спикер заполняет прошедшее выступление, опционально
    прикрепляет слайды, фото и ссылку на видео. После submit Event создаётся
    в статусе `verification_status='pending'` и ждёт одобрения DevRel.
    """

    title = forms.CharField(label="Название", max_length=200, required=True)
    event_date = forms.DateField(label="Дата", required=True)
    location = forms.CharField(label="Место", max_length=200, required=False)
    link = forms.URLField(label="Ссылка на анонс / страницу", max_length=500, required=False)
    topic = forms.CharField(label="Тема доклада", max_length=100, required=False)
    format = forms.ChoiceField(
        label="Формат",
        required=False,
        choices=[
            ('', 'Не выбрано'),
            ('online', 'Онлайн'),
            ('offline', 'Офлайн'),
            ('hybrid', 'Гибрид'),
        ],
    )
    tags = forms.CharField(
        label="Теги / стек",
        max_length=300,
        required=False,
        help_text="Через запятую: python, django, ml",
    )
    description = forms.CharField(
        label="Описание выступления",
        required=True,
        widget=forms.Textarea(attrs={'rows': 5}),
    )
    video_url = forms.URLField(
        label="Ссылка на видео",
        max_length=500,
        required=False,
        help_text="YouTube, VK Video, RuTube",
    )
    presentation = forms.FileField(label="Презентация (PDF/PPTX, ≤50 МБ)", required=False)

    def clean_event_date(self):
        d = self.cleaned_data.get('event_date')
        if d and d > timezone.localdate():
            raise ValidationError("Можно загружать только прошедшие мероприятия.")
        return d

    def clean_presentation(self):
        f = self.cleaned_data.get('presentation')
        if not f:
            return f
        if f.size > MAX_PRESENTATION_BYTES:
            raise ValidationError("Презентация не должна превышать 50 МБ.")
        name_lower = (getattr(f, 'name', '') or '').lower()
        if not name_lower.endswith(_PRESENTATION_EXTS):
            raise ValidationError("Допустимые форматы: PDF, PPT, PPTX.")
        ct = getattr(f, 'content_type', '')
        if ct and ct not in _PRESENTATION_TYPES:
            # Браузеры иногда отдают пустой content_type, поэтому extension — приоритет.
            pass
        return f

    def clean_video_url(self):
        url = (self.cleaned_data.get('video_url') or '').strip()
        if not url:
            return url
        if not _VIDEO_HOST_RE.match(url):
            raise ValidationError("Только YouTube, VK Video или RuTube.")
        return url

    def clean_tags(self):
        return (self.cleaned_data.get('tags') or '').strip()

    @classmethod
    def validate_photos(cls, files):
        """Валидируем список фото (`request.FILES.getlist('photos')`)."""
        files = list(files or [])
        if len(files) > MAX_PHOTOS:
            raise ValidationError(f"Можно загрузить не более {MAX_PHOTOS} фотографий.")
        for f in files:
            if f.size > MAX_PHOTO_BYTES:
                raise ValidationError(f"Фото «{f.name}» больше 10 МБ.")
            ct = getattr(f, 'content_type', '')
            if ct and ct not in _PHOTO_TYPES:
                raise ValidationError(f"Фото «{f.name}»: допустимы JPEG, PNG, WebP.")
        return files

