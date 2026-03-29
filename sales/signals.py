from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Sale, SaleLineItem, Invoice


def _log(level, action, message, instance):
    from system_settings.models import SystemLog

    user = getattr(instance, "_current_user", None)
    SystemLog.log(level=level, action_type=action, message=message, user=user)


# ── Sale ──────────────────────────────────────────────────────────────────────


@receiver(post_save, sender=Sale)
def sale_post_save(sender, instance, created, **kwargs):
    if created:
        _log(
            "info",
            "create",
            f"Vente créée : {instance.sale_number} — {instance.customer.name} "
            f"(trader : {instance.assigned_trader.get_full_name() or instance.assigned_trader.username})",
            instance,
        )
    else:
        finalized = " [FINALISÉE]" if instance.is_finalized else ""
        _log(
            "info",
            "update",
            f"Vente modifiée : {instance.sale_number}{finalized}",
            instance,
        )


@receiver(post_delete, sender=Sale)
def sale_post_delete(sender, instance, **kwargs):
    _log(
        "warning",
        "delete",
        f"Vente supprimée : {instance.sale_number} — {instance.customer.name}",
        instance,
    )


# ── SaleLineItem ──────────────────────────────────────────────────────────────


@receiver(post_save, sender=SaleLineItem)
def sale_line_post_save(sender, instance, created, **kwargs):
    if created:
        _log(
            "info",
            "create",
            f"Ligne de vente ajoutée : {instance.vehicle.make} {instance.vehicle.model} "
            f"[{instance.vehicle.vin_chassis}] → vente {instance.sale.sale_number} "
            f"— {instance.sale_price:,.0f} DA",
            instance,
        )
    else:
        _log(
            "info",
            "update",
            f"Ligne de vente modifiée : {instance.sale.sale_number} "
            f"#{instance.line_number}",
            instance,
        )


@receiver(post_delete, sender=SaleLineItem)
def sale_line_post_delete(sender, instance, **kwargs):
    _log(
        "warning",
        "delete",
        f"Ligne de vente supprimée : {instance.vehicle.vin_chassis} "
        f"— vente {instance.sale.sale_number}",
        instance,
    )


# ── Invoice ───────────────────────────────────────────────────────────────────


@receiver(post_save, sender=Invoice)
def invoice_post_save(sender, instance, created, **kwargs):
    if created:
        _log(
            "info",
            "create",
            f"Facture créée : {instance.invoice_number} — {instance.customer.name} "
            f"— {instance.total_ttc:,.0f} DA",
            instance,
        )
    else:
        _log(
            "info",
            "update",
            f"Facture modifiée : {instance.invoice_number} — statut : {instance.status} "
            f"— solde dû : {instance.balance_due:,.0f} DA",
            instance,
        )
