# =============================================================================
# INSTRUCTIONS — place each section in the corresponding app's signals.py
# Then register each signals.py in its app's AppConfig.ready() method:
#
#   class InventoryConfig(AppConfig):
#       def ready(self):
#           import inventory.signals  # noqa
#
# The SystemLog.log() helper (from system_settings.models) is used throughout.
# It is imported lazily inside each handler to avoid circular imports.
# =============================================================================


# ─────────────────────────────────────────────────────────────────────────────
# FILE: inventory/signals.py
# ─────────────────────────────────────────────────────────────────────────────
"""
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from .models import Vehicle, VehiclePhoto, StockAlert


def _log(level, action, message, instance):
    from system_settings.models import SystemLog
    user = getattr(instance, '_current_user', None)
    SystemLog.log(level=level, action_type=action, message=message, user=user)


# ── Vehicle ───────────────────────────────────────────────────────────────────

@receiver(pre_save, sender=Vehicle)
def vehicle_pre_save(sender, instance, **kwargs):
    \"\"\"Capture old status so we can log status transitions.\"\"\"
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
        _log('info', 'create',
             f"Véhicule ajouté : {instance.make} {instance.model} {instance.year} "
             f"[{instance.vin_chassis}]",
             instance)
    else:
        old = getattr(instance, '_old_status', None)
        if old and old != instance.status:
            _log('info', 'update',
                 f"Statut véhicule modifié : {instance.vin_chassis} "
                 f"{old} → {instance.status}",
                 instance)
        else:
            _log('info', 'update',
                 f"Véhicule modifié : {instance.make} {instance.model} [{instance.vin_chassis}]",
                 instance)


@receiver(post_delete, sender=Vehicle)
def vehicle_post_delete(sender, instance, **kwargs):
    _log('warning', 'delete',
         f"Véhicule supprimé : {instance.make} {instance.model} {instance.year} "
         f"[{instance.vin_chassis}]",
         instance)


# ── StockAlert ────────────────────────────────────────────────────────────────

@receiver(post_save, sender=StockAlert)
def stock_alert_post_save(sender, instance, created, **kwargs):
    if created:
        _log('warning', 'create',
             f"Alerte stock créée : {instance.get_alert_type_display()} — "
             f"{instance.vehicle or 'Général'}",
             instance)
    elif instance.is_resolved:
        _log('info', 'update',
             f"Alerte stock résolue : {instance.get_alert_type_display()} — "
             f"{instance.vehicle or 'Général'}",
             instance)
"""


# ─────────────────────────────────────────────────────────────────────────────
# FILE: purchases/signals.py
# ─────────────────────────────────────────────────────────────────────────────
"""
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Purchase, PurchaseLineItem, FreightCost, CustomsDeclaration


def _log(level, action, message, instance):
    from system_settings.models import SystemLog
    user = getattr(instance, '_current_user', None)
    SystemLog.log(level=level, action_type=action, message=message, user=user)


# ── Purchase (container) ──────────────────────────────────────────────────────

@receiver(post_save, sender=Purchase)
def purchase_post_save(sender, instance, created, **kwargs):
    if created:
        _log('info', 'create',
             f"Achat créé : {instance.supplier.name} — {instance.purchase_date} "
             f"({instance.currency.code}, taux {instance.exchange_rate_to_da})",
             instance)
    else:
        _log('info', 'update',
             f"Achat modifié : {instance.supplier.name} — {instance.purchase_date}",
             instance)


@receiver(post_delete, sender=Purchase)
def purchase_post_delete(sender, instance, **kwargs):
    _log('warning', 'delete',
         f"Achat supprimé : {instance.supplier.name} — {instance.purchase_date}",
         instance)


# ── PurchaseLineItem ──────────────────────────────────────────────────────────

@receiver(post_save, sender=PurchaseLineItem)
def line_item_post_save(sender, instance, created, **kwargs):
    if created:
        _log('info', 'create',
             f"Article achat ajouté : #{instance.line_number} {instance.make} "
             f"{instance.model} {instance.year} — FOB {instance.fob_price} "
             f"{instance.purchase.currency.code}",
             instance)
    else:
        _log('info', 'update',
             f"Article achat modifié : #{instance.line_number} {instance.make} "
             f"{instance.model} [{instance.purchase}]",
             instance)


@receiver(post_delete, sender=PurchaseLineItem)
def line_item_post_delete(sender, instance, **kwargs):
    _log('warning', 'delete',
         f"Article achat supprimé : #{instance.line_number} {instance.make} "
         f"{instance.model} — {instance.purchase}",
         instance)


# ── FreightCost ───────────────────────────────────────────────────────────────

@receiver(post_save, sender=FreightCost)
def freight_post_save(sender, instance, created, **kwargs):
    action = 'create' if created else 'update'
    _log('info', action,
         f"Frais de transport {'créés' if created else 'modifiés'} : "
         f"{instance.purchase} — total {instance.total_freight_cost_da} DA",
         instance)


# ── CustomsDeclaration ────────────────────────────────────────────────────────

@receiver(post_save, sender=CustomsDeclaration)
def customs_post_save(sender, instance, created, **kwargs):
    if created:
        _log('info', 'create',
             f"Déclaration douanière créée : {instance.declaration_number} — "
             f"{instance.purchase}",
             instance)
    else:
        cleared = " [DÉDOUANÉ]" if instance.is_cleared else ""
        _log('info', 'update',
             f"Déclaration douanière modifiée : {instance.declaration_number}{cleared}",
             instance)
"""


# ─────────────────────────────────────────────────────────────────────────────
# FILE: sales/signals.py
# ─────────────────────────────────────────────────────────────────────────────
"""
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Sale, SaleLineItem, Invoice


def _log(level, action, message, instance):
    from system_settings.models import SystemLog
    user = getattr(instance, '_current_user', None)
    SystemLog.log(level=level, action_type=action, message=message, user=user)


# ── Sale ──────────────────────────────────────────────────────────────────────

@receiver(post_save, sender=Sale)
def sale_post_save(sender, instance, created, **kwargs):
    if created:
        _log('info', 'create',
             f"Vente créée : {instance.sale_number} — {instance.customer.name} "
             f"(trader : {instance.assigned_trader.get_full_name() or instance.assigned_trader.username})",
             instance)
    else:
        finalized = " [FINALISÉE]" if instance.is_finalized else ""
        _log('info', 'update',
             f"Vente modifiée : {instance.sale_number}{finalized}",
             instance)


@receiver(post_delete, sender=Sale)
def sale_post_delete(sender, instance, **kwargs):
    _log('warning', 'delete',
         f"Vente supprimée : {instance.sale_number} — {instance.customer.name}",
         instance)


# ── SaleLineItem ──────────────────────────────────────────────────────────────

@receiver(post_save, sender=SaleLineItem)
def sale_line_post_save(sender, instance, created, **kwargs):
    if created:
        _log('info', 'create',
             f"Ligne de vente ajoutée : {instance.vehicle.make} {instance.vehicle.model} "
             f"[{instance.vehicle.vin_chassis}] → vente {instance.sale.sale_number} "
             f"— {instance.sale_price:,.0f} DA",
             instance)
    else:
        _log('info', 'update',
             f"Ligne de vente modifiée : {instance.sale.sale_number} "
             f"#{instance.line_number}",
             instance)


@receiver(post_delete, sender=SaleLineItem)
def sale_line_post_delete(sender, instance, **kwargs):
    _log('warning', 'delete',
         f"Ligne de vente supprimée : {instance.vehicle.vin_chassis} "
         f"— vente {instance.sale.sale_number}",
         instance)


# ── Invoice ───────────────────────────────────────────────────────────────────

@receiver(post_save, sender=Invoice)
def invoice_post_save(sender, instance, created, **kwargs):
    if created:
        _log('info', 'create',
             f"Facture créée : {instance.invoice_number} — {instance.customer.name} "
             f"— {instance.total_ttc:,.0f} DA",
             instance)
    else:
        _log('info', 'update',
             f"Facture modifiée : {instance.invoice_number} — statut : {instance.status} "
             f"— solde dû : {instance.balance_due:,.0f} DA",
             instance)
"""


# ─────────────────────────────────────────────────────────────────────────────
# FILE: payments/signals.py
# ─────────────────────────────────────────────────────────────────────────────
"""
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Payment, PaymentPlan, Installment


def _log(level, action, message, instance):
    from system_settings.models import SystemLog
    user = getattr(instance, '_current_user', None)
    SystemLog.log(level=level, action_type=action, message=message, user=user)


# ── Payment ───────────────────────────────────────────────────────────────────

@receiver(post_save, sender=Payment)
def payment_post_save(sender, instance, created, **kwargs):
    if created:
        _log('info', 'create',
             f"Paiement enregistré : {instance.payment_number} — "
             f"{instance.amount:,.0f} DA ({instance.get_payment_method_display()}) "
             f"— facture {instance.invoice.invoice_number}",
             instance)
    else:
        _log('info', 'update',
             f"Paiement modifié : {instance.payment_number} — {instance.amount:,.0f} DA",
             instance)


@receiver(post_delete, sender=Payment)
def payment_post_delete(sender, instance, **kwargs):
    _log('warning', 'delete',
         f"Paiement supprimé : {instance.payment_number} — {instance.amount:,.0f} DA "
         f"— facture {instance.invoice.invoice_number}",
         instance)


# ── PaymentPlan ───────────────────────────────────────────────────────────────

@receiver(post_save, sender=PaymentPlan)
def payment_plan_post_save(sender, instance, created, **kwargs):
    action = 'create' if created else 'update'
    _log('info', action,
         f"Plan de paiement {'créé' if created else 'modifié'} : "
         f"{instance.invoice.invoice_number} — {instance.number_of_installments} "
         f"échéances de {instance.installment_amount:,.0f} DA",
         instance)


# ── Installment ───────────────────────────────────────────────────────────────

@receiver(post_save, sender=Installment)
def installment_post_save(sender, instance, created, **kwargs):
    # Only log status transitions on existing installments (not bulk creation)
    if not created and instance.status == 'paid':
        _log('info', 'update',
             f"Échéance payée : #{instance.installment_number} "
             f"— {instance.payment_plan.invoice.invoice_number} "
             f"— {instance.amount:,.0f} DA",
             instance)
    elif not created and instance.status == 'overdue':
        _log('warning', 'update',
             f"Échéance en retard : #{instance.installment_number} "
             f"— {instance.payment_plan.invoice.invoice_number} "
             f"(échue le {instance.due_date})",
             instance)
"""


# ─────────────────────────────────────────────────────────────────────────────
# FILE: customers/signals.py
# ─────────────────────────────────────────────────────────────────────────────
"""
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Customer


def _log(level, action, message, instance):
    from system_settings.models import SystemLog
    user = getattr(instance, '_current_user', None)
    SystemLog.log(level=level, action_type=action, message=message, user=user)


@receiver(post_save, sender=Customer)
def customer_post_save(sender, instance, created, **kwargs):
    if created:
        _log('info', 'create',
             f"Client créé : {instance.name} ({instance.get_customer_type_display()}) "
             f"— {instance.get_wilaya_display_name()}",
             instance)
    else:
        _log('info', 'update',
             f"Client modifié : {instance.name}",
             instance)


@receiver(post_delete, sender=Customer)
def customer_post_delete(sender, instance, **kwargs):
    _log('warning', 'delete',
         f"Client supprimé : {instance.name} ({instance.get_customer_type_display()})",
         instance)
"""


# ─────────────────────────────────────────────────────────────────────────────
# FILE: suppliers/signals.py
# ─────────────────────────────────────────────────────────────────────────────
"""
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Supplier


def _log(level, action, message, instance):
    from system_settings.models import SystemLog
    user = getattr(instance, '_current_user', None)
    SystemLog.log(level=level, action_type=action, message=message, user=user)


@receiver(post_save, sender=Supplier)
def supplier_post_save(sender, instance, created, **kwargs):
    if created:
        _log('info', 'create',
             f"Fournisseur créé : {instance.name} ({instance.country}) "
             f"— devise : {instance.currency.code}",
             instance)
    else:
        _log('info', 'update',
             f"Fournisseur modifié : {instance.name}",
             instance)


@receiver(post_delete, sender=Supplier)
def supplier_post_delete(sender, instance, **kwargs):
    _log('warning', 'delete',
         f"Fournisseur supprimé : {instance.name} ({instance.country})",
         instance)
"""


# =============================================================================
# HOW TO ATTACH _current_user IN YOUR VIEWS
# =============================================================================
# Signals can only see what's on the model instance.
# To capture the logged-in user, set instance._current_user before save():
#
#   vehicle = form.save(commit=False)
#   vehicle._current_user = request.user   # ← attach user
#   vehicle.save()
#
# For a cleaner approach, use a middleware that stores the request on a thread-
# local, then read it inside _log().  Example middleware:
#
#   # core/middleware.py
#   import threading
#   _thread_local = threading.local()
#
#   class CurrentUserMiddleware:
#       def __init__(self, get_response):
#           self.get_response = get_response
#       def __call__(self, request):
#           _thread_local.current_user = getattr(request, 'user', None)
#           return self.get_response(request)
#
#   def get_current_user():
#       return getattr(_thread_local, 'current_user', None)
#
# Then in each signals.py replace:
#   user = getattr(instance, '_current_user', None)
# with:
#   from core.middleware import get_current_user
#   user = get_current_user()
#
# Add 'core.middleware.CurrentUserMiddleware' to MIDDLEWARE in settings.py.
# =============================================================================