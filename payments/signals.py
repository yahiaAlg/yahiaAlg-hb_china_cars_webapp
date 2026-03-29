from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Payment, PaymentPlan, Installment


def _log(level, action, message, instance):
    from system_settings.models import SystemLog

    user = getattr(instance, "_current_user", None)
    SystemLog.log(level=level, action_type=action, message=message, user=user)


# ── Payment ───────────────────────────────────────────────────────────────────


@receiver(post_save, sender=Payment)
def payment_post_save(sender, instance, created, **kwargs):
    if created:
        _log(
            "info",
            "create",
            f"Paiement enregistré : {instance.payment_number} — "
            f"{instance.amount:,.0f} DA ({instance.get_payment_method_display()}) "
            f"— facture {instance.invoice.invoice_number}",
            instance,
        )
    else:
        _log(
            "info",
            "update",
            f"Paiement modifié : {instance.payment_number} — {instance.amount:,.0f} DA",
            instance,
        )


@receiver(post_delete, sender=Payment)
def payment_post_delete(sender, instance, **kwargs):
    _log(
        "warning",
        "delete",
        f"Paiement supprimé : {instance.payment_number} — {instance.amount:,.0f} DA "
        f"— facture {instance.invoice.invoice_number}",
        instance,
    )


# ── PaymentPlan ───────────────────────────────────────────────────────────────


@receiver(post_save, sender=PaymentPlan)
def payment_plan_post_save(sender, instance, created, **kwargs):
    action = "create" if created else "update"
    _log(
        "info",
        action,
        f"Plan de paiement {'créé' if created else 'modifié'} : "
        f"{instance.invoice.invoice_number} — {instance.number_of_installments} "
        f"échéances de {instance.installment_amount:,.0f} DA",
        instance,
    )


# ── Installment ───────────────────────────────────────────────────────────────


@receiver(post_save, sender=Installment)
def installment_post_save(sender, instance, created, **kwargs):
    # Only log status transitions on existing installments (not bulk creation)
    if not created and instance.status == "paid":
        _log(
            "info",
            "update",
            f"Échéance payée : #{instance.installment_number} "
            f"— {instance.payment_plan.invoice.invoice_number} "
            f"— {instance.amount:,.0f} DA",
            instance,
        )
    elif not created and instance.status == "overdue":
        _log(
            "warning",
            "update",
            f"Échéance en retard : #{instance.installment_number} "
            f"— {instance.payment_plan.invoice.invoice_number} "
            f"(échue le {instance.due_date})",
            instance,
        )
