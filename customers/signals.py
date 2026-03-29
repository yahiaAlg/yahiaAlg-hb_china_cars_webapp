from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Customer


def _log(level, action, message, instance):
    from system_settings.models import SystemLog

    user = getattr(instance, "_current_user", None)
    SystemLog.log(level=level, action_type=action, message=message, user=user)


@receiver(post_save, sender=Customer)
def customer_post_save(sender, instance, created, **kwargs):
    if created:
        _log(
            "info",
            "create",
            f"Client créé : {instance.name} ({instance.get_customer_type_display()}) "
            f"— {instance.get_wilaya_display_name()}",
            instance,
        )
    else:
        _log("info", "update", f"Client modifié : {instance.name}", instance)


@receiver(post_delete, sender=Customer)
def customer_post_delete(sender, instance, **kwargs):
    _log(
        "warning",
        "delete",
        f"Client supprimé : {instance.name} ({instance.get_customer_type_display()})",
        instance,
    )
