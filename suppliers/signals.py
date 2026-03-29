from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Supplier


def _log(level, action, message, instance):
    from system_settings.models import SystemLog

    user = getattr(instance, "_current_user", None)
    SystemLog.log(level=level, action_type=action, message=message, user=user)


@receiver(post_save, sender=Supplier)
def supplier_post_save(sender, instance, created, **kwargs):
    if created:
        _log(
            "info",
            "create",
            f"Fournisseur créé : {instance.name} ({instance.country}) "
            f"— devise : {instance.currency.code}",
            instance,
        )
    else:
        _log("info", "update", f"Fournisseur modifié : {instance.name}", instance)


@receiver(post_delete, sender=Supplier)
def supplier_post_delete(sender, instance, **kwargs):
    _log(
        "warning",
        "delete",
        f"Fournisseur supprimé : {instance.name} ({instance.country})",
        instance,
    )
