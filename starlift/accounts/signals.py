from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=get_user_model())
def ensure_user_profile(sender, instance, created, **kwargs):
    """Create a UserProfile for every new User.

    Role heuristic: superusers and staff map to admin, the rest to speaker.
    This also catches `createsuperuser` which bypasses our invite flow.
    """
    from .models import UserProfile

    if not created:
        return
    # Default role for any fresh User is `guest` (safe-by-default: no access
    # to member-only areas). Superusers/staff — admins. The invite-accept
    # and self-register flows explicitly override this right after create.
    role = UserProfile.ROLE_ADMIN if (instance.is_superuser or instance.is_staff) else UserProfile.ROLE_GUEST
    UserProfile.objects.get_or_create(
        user=instance,
        defaults={
            "role": role,
            "email_verified": True if instance.is_superuser else False,
        },
    )
