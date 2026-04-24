from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from accounts.password_validators import NotOnlySpecialCharsValidator


class NotOnlySpecialCharsValidatorTests(SimpleTestCase):
    def setUp(self):
        self.validator = NotOnlySpecialCharsValidator()

    def test_rejects_only_specials(self):
        for pw in ("!!!!", "@@@####", "~`!@#$%^&*()", "___---+++"):
            with self.assertRaises(ValidationError, msg=pw):
                self.validator.validate(pw)

    def test_rejects_empty(self):
        with self.assertRaises(ValidationError):
            self.validator.validate("")

    def test_accepts_with_letter(self):
        for pw in ("a!!!!!!!", "Password!", "Привет123"):
            self.validator.validate(pw)

    def test_accepts_with_digit(self):
        for pw in ("1!!!!!!!", "0@0@0@0"):
            self.validator.validate(pw)

    def test_help_text_is_string(self):
        self.assertTrue(str(self.validator.get_help_text()))
