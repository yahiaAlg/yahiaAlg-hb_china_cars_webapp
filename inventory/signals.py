from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from .models import Vehicle, VehiclePhoto, StockAlert


def _log(level, action, message, instance):
    from system_settings.models import SystemLog

    user = getattr(instance, "_current_user", None)
    SystemLog.log(level=level, action_type=action, message=message, user=user)


# ── Vehicle ───────────────────────────────────────────────────────────────────


@receiver(pre_save, sender=Vehicle)
def vehicle_pre_save(sender, instance, **kwargs):
    """Capture old status so we can log status transitions."""
    if instance.pk:
        try:
            instance._old_status = Vehicle.objects.get(pk=instance.pk).status
        except Vehicle.DoesNotExist:
            instance._old_status = None
    else:
        instance._old_status = None


@receiver(post_save, sender=Vehicle)
def vehicle_post_save(sender, instance, created, **kwargs):
    if created:
        _log(
            "info",
            "create",
            f"Véhicule ajouté : {instance.make} {instance.model} {instance.year} "
            f"[{instance.vin_chassis}]",
            instance,
        )
    else:
        old = getattr(instance, "_old_status", None)
        if old and old != instance.status:
            _log(
                "info",
                "update",
                f"Statut véhicule modifié : {instance.vin_chassis} "
                f"{old} → {instance.status}",
                instance,
            )
        else:
            _log(
                "info",
                "update",
                f"Véhicule modifié : {instance.make} {instance.model} [{instance.vin_chassis}]",
                instance,
            )


@receiver(post_delete, sender=Vehicle)
def vehicle_post_delete(sender, instance, **kwargs):
    _log(
        "warning",
        "delete",
        f"Véhicule supprimé : {instance.make} {instance.model} {instance.year} "
        f"[{instance.vin_chassis}]",
        instance,
    )


# ── StockAlert ────────────────────────────────────────────────────────────────


@receiver(post_save, sender=StockAlert)
def stock_alert_post_save(sender, instance, created, **kwargs):
    if created:
        _log(
            "warning",
            "create",
            f"Alerte stock créée : {instance.get_alert_type_display()} — "
            f"{instance.vehicle or 'Général'}",
            instance,
        )
    elif instance.is_resolved:
        _log(
            "info",
            "update",
            f"Alerte stock résolue : {instance.get_alert_type_display()} — "
            f"{instance.vehicle or 'Général'}",
            instance,
        )
