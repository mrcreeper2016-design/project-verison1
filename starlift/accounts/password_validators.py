import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


_ALNUM_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]")


class NotOnlySpecialCharsValidator:
    """Reject passwords that consist only of punctuation/whitespace.

    A password is acceptable if it contains at least one alphanumeric
    character (latin/cyrillic letter or digit). The built-in
    `NumericPasswordValidator` already rejects all-digits passwords; this
    validator complements it by rejecting all-punctuation passwords.
    """

    def validate(self, password, user=None):
        if not _ALNUM_RE.search(password or ""):
            raise ValidationError(
                _("Пароль не может состоять только из специальных символов."),
                code="password_only_special_chars",
            )

    def get_help_text(self):
        return _("Пароль должен содержать хотя бы одну букву или цифру.")
