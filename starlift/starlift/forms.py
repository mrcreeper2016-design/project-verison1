import os
import requests
from io import BytesIO
from PIL import Image
from django import forms
from django.conf import settings
from django.core.files.uploadedfile import InMemoryUploadedFile
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

    class Meta:
        model = Speaker
        # Whitelist-style: only fields explicitly listed are editable from this
        # admin-only form. `bio` is edited by speakers themselves via /profile/,
        # `user` is linked via the admin console, and `nps` is derived.
        fields = ['name', 'stack', 'city', 'img', 'recommended']
        labels = {
            'name': 'Имя и Фамилия',
            'stack': 'Стек (через запятую)',
            'city': 'Город',
            'status': 'Статус',
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
                rel_path = f"speakers/{filename}"
                abs_path = os.path.join(settings.MEDIA_ROOT, 'speakers')
                os.makedirs(abs_path, exist_ok=True)
                full_path = os.path.join(abs_path, filename)
                
                # Конвертируем в RGB если изображение с альфа-каналом и сохраняем
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')
                    
                img.save(full_path, format='WEBP')
                
                cleaned_data['img'] = f"{settings.MEDIA_URL}{rel_path}"

            except Exception as e:
                raise ValidationError(f"Ошибка при обработке изображения: {str(e)}")
        elif not img_field:
            import random
            cleaned_data['img'] = str(random.randint(1, 70))

        return cleaned_data


class SpeakerSelfEditForm(SpeakerForm):
    """Form for speaker-owned profile edits.

    The speaker can update profile details, but not ownership, NPS, feedback,
    or admin flags. Name is controlled from the linked auth user.
    """

    class Meta(SpeakerForm.Meta):
        fields = ['sub', 'stack', 'city', 'status', 'bio', 'img']
        labels = {
            'sub': 'Подзаголовок',
            'stack': 'Стек (через запятую)',
            'city': 'Город',
            'status': 'Статус',
            'bio': 'О себе',
        }
        widgets = {
            'sub': forms.TextInput(attrs={'class': 'search-box', 'style': 'width: 100%; border-radius: 12px; padding: 10px; border: 1px solid var(--glass-border);'}),
            'stack': forms.TextInput(attrs={'class': 'search-box', 'style': 'width: 100%; border-radius: 12px; padding: 10px; border: 1px solid var(--glass-border);'}),
            'city': forms.TextInput(attrs={'class': 'search-box', 'style': 'width: 100%; border-radius: 12px; padding: 10px; border: 1px solid var(--glass-border);'}),
            'status': forms.TextInput(attrs={'class': 'search-box', 'style': 'width: 100%; border-radius: 12px; padding: 10px; border: 1px solid var(--glass-border);'}),
            'bio': forms.Textarea(attrs={'class': 'search-box', 'style': 'width: 100%; border-radius: 12px; padding: 10px; border: 1px solid var(--glass-border); min-height: 120px;'}),
            'img': forms.HiddenInput(),
        }
