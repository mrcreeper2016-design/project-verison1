from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.hashers import check_password, make_password
from django.db.models import Q


# Cached dummy hash used to keep timing stable when the account is missing.
_DUMMY_PASSWORD_HASH = None


def _dummy_hash() -> str:
    global _DUMMY_PASSWORD_HASH
    if _DUMMY_PASSWORD_HASH is None:
        _DUMMY_PASSWORD_HASH = make_password("dummy-password-for-timing")
    return _DUMMY_PASSWORD_HASH


class UsernameOrEmailBackend(ModelBackend):
    """Authenticate against username OR email (case-insensitive).

    Mitigates user enumeration by performing a constant-time password
    comparison against a dummy hash when the account is missing.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get("username") or kwargs.get("email")
        if not username or not password:
            return None

        UserModel = get_user_model()
        identifier = username.strip()
        lookup = Q(username__iexact=identifier) | Q(email__iexact=identifier)

        try:
            user = UserModel.objects.filter(lookup).distinct().get()
        except UserModel.DoesNotExist:
            check_password(password, _dummy_hash())
            return None
        except UserModel.MultipleObjectsReturned:
            user = UserModel.objects.filter(lookup).order_by("id").first()
            if user is None:
                return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
