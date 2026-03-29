from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Purchase, PurchaseLineItem, FreightCost, CustomsDeclaration


def _log(level, action, message, instance):
    from system_settings.models import SystemLog

    user = getattr(instance, "_current_user", None)
    SystemLog.log(level=level, action_type=action, message=message, user=user)


# ── Purchase (container) ──────────────────────────────────────────────────────


@receiver(post_save, sender=Purchase)
def purchase_post_save(sender, instance, created, **kwargs):
    if created:
        _log(
            "info",
            "create",
            f"Achat créé : {instance.supplier.name} — {instance.purchase_date} "
            f"({instance.currency.code}, taux {instance.exchange_rate_to_da})",
            instance,
        )
    else:
        _log(
            "info",
            "update",
            f"Achat modifié : {instance.supplier.name} — {instance.purchase_date}",
            instance,
        )


@receiver(post_delete, sender=Purchase)
def purchase_post_delete(sender, instance, **kwargs):
    _log(
        "warning",
        "delete",
        f"Achat supprimé : {instance.supplier.name} — {instance.purchase_date}",
        instance,
    )


# ── PurchaseLineItem ──────────────────────────────────────────────────────────


@receiver(post_save, sender=PurchaseLineItem)
def line_item_post_save(sender, instance, created, **kwargs):
    if created:
        _log(
            "info",
            "create",
            f"Article achat ajouté : #{instance.line_number} {instance.make} "
            f"{instance.model} {instance.year} — FOB {instance.fob_price} "
            f"{instance.purchase.currency.code}",
            instance,
        )
    else:
        _log(
            "info",
            "update",
            f"Article achat modifié : #{instance.line_number} {instance.make} "
            f"{instance.model} [{instance.purchase}]",
            instance,
        )


@receiver(post_delete, sender=PurchaseLineItem)
def line_item_post_delete(sender, instance, **kwargs):
    _log(
        "warning",
        "delete",
        f"Article achat supprimé : #{instance.line_number} {instance.make} "
        f"{instance.model} — {instance.purchase}",
        instance,
    )


# ── FreightCost ───────────────────────────────────────────────────────────────


@receiver(post_save, sender=FreightCost)
def freight_post_save(sender, instance, created, **kwargs):
    action = "create" if created else "update"
    _log(
        "info",
        action,
        f"Frais de transport {'créés' if created else 'modifiés'} : "
        f"{instance.purchase} — total {instance.total_freight_cost_da} DA",
        instance,
    )


# ── CustomsDeclaration ────────────────────────────────────────────────────────


@receiver(post_save, sender=CustomsDeclaration)
def customs_post_save(sender, instance, created, **kwargs):
    if created:
        _log(
            "info",
            "create",
            f"Déclaration douanière créée : {instance.declaration_number} — "
            f"{instance.purchase}",
            instance,
        )
    else:
        cleared = " [DÉDOUANÉ]" if instance.is_cleared else ""
        _log(
            "info",
            "update",
            f"Déclaration douanière modifiée : {instance.declaration_number}{cleared}",
            instance,
        )
