from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal
from core.models import BaseModel
from inventory.models import Vehicle
from customers.models import Customer


class Sale(BaseModel):
    """Vehicle sale transaction — may include multiple vehicles (line items)."""

    PAYMENT_METHODS = [
        ("cash", "Espèces"),
        ("bank_transfer", "Virement Bancaire"),
        ("installment", "Paiement Échelonné"),
        ("check", "Chèque"),
    ]

    # Sale identification
    sale_number = models.CharField(
        max_length=20, unique=True, verbose_name="Numéro de vente"
    )
    sale_date = models.DateField(verbose_name="Date de vente")

    # Parties involved
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, verbose_name="Client"
    )
    assigned_trader = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="sales_as_trader",
        verbose_name="Trader assigné",
    )

    # Financial details (sale_price is now a property, summed from line items)
    payment_method = models.CharField(
        max_length=20, choices=PAYMENT_METHODS, verbose_name="Mode de paiement"
    )
    down_payment = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name="Acompte (DA)",
    )

    # Commission calculation
    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        verbose_name="Taux de commission (%)",
    )
    commission_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Montant commission (DA)",
    )

    # Status and notes
    is_finalized = models.BooleanField(default=False, verbose_name="Finalisée")
    notes = models.TextField(blank=True, verbose_name="Notes")

    class Meta:
        verbose_name = "Vente"
        verbose_name_plural = "Ventes"
        ordering = ["-sale_date", "-created_at"]

    def __str__(self):
        return f"Vente {self.sale_number} — {self.customer.name}"

    def clean(self):
        super().clean()
        if self.sale_date and self.sale_date > timezone.now().date():
            raise ValidationError(
                {"sale_date": "La date de vente ne peut pas être dans le futur."}
            )
        if self.assigned_trader and hasattr(self.assigned_trader, "userprofile"):
            if (
                not self.assigned_trader.userprofile.is_trader
                and not self.assigned_trader.userprofile.is_manager
            ):
                raise ValidationError(
                    {
                        "assigned_trader": "Seuls les traders et managers peuvent être assignés aux ventes."
                    }
                )

    def save(self, *args, **kwargs):
        if not self.sale_number:
            self.sale_number = self.generate_sale_number()
        super().save(*args, **kwargs)

    def generate_sale_number(self):
        from datetime import datetime

        today = datetime.now()
        prefix = f"VTE-{today.strftime('%Y%m%d')}"
        last = (
            Sale.objects.filter(sale_number__startswith=prefix)
            .order_by("-sale_number")
            .first()
        )
        if last:
            try:
                new_num = int(last.sale_number.split("-")[-1]) + 1
            except (ValueError, IndexError):
                new_num = 1
        else:
            new_num = 1
        return f"{prefix}-{new_num:03d}"

    def recalculate_commission(self):
        """Recalculate commission after line items are saved."""
        if self.commission_rate is not None:
            margin = self.calculate_margin()
            self.commission_amount = (
                margin * (self.commission_rate / 100) if margin > 0 else Decimal("0")
            )
            Sale.objects.filter(pk=self.pk).update(
                commission_amount=self.commission_amount
            )

    # ── Aggregated financial properties ───────────────────────────────────────

    @property
    def sale_price(self):
        """Total sale price = sum of all line items."""
        return sum((item.sale_price for item in self.line_items.all()), Decimal("0"))

    @property
    def landed_cost(self):
        """Total landed cost across all vehicles in this sale."""
        return sum(
            (item.vehicle.landed_cost for item in self.line_items.all()), Decimal("0")
        )

    def calculate_margin(self):
        return self.sale_price - self.landed_cost

    @property
    def margin_amount(self):
        return self.calculate_margin()

    @property
    def margin_percentage(self):
        lc = self.landed_cost
        if lc > 0:
            return (self.calculate_margin() / lc) * 100
        return Decimal("0")

    @property
    def remaining_balance(self):
        return self.sale_price - self.down_payment

    @property
    def vehicle_count(self):
        return self.line_items.count()

    @property
    def vehicles_display(self):
        """Short display string of vehicles."""
        items = self.line_items.select_related("vehicle").all()
        return (
            ", ".join(
                f"{i.vehicle.make} {i.vehicle.model} {i.vehicle.year}" for i in items
            )
            or "—"
        )


class SaleLineItem(BaseModel):
    """One vehicle line within a sale."""

    sale = models.ForeignKey(
        Sale, on_delete=models.CASCADE, related_name="line_items", verbose_name="Vente"
    )
    vehicle = models.OneToOneField(
        Vehicle,
        on_delete=models.PROTECT,
        related_name="sale_line_item",
        verbose_name="Véhicule",
    )
    sale_price = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name="Prix de vente (DA)",
    )
    line_number = models.PositiveIntegerField(blank=True, verbose_name="N° de ligne")
    notes = models.TextField(blank=True, verbose_name="Notes")

    class Meta:
        verbose_name = "Ligne de vente"
        verbose_name_plural = "Lignes de vente"
        ordering = ["line_number"]
        unique_together = [["sale", "line_number"]]

    def __str__(self):
        return f"#{self.line_number} — {self.vehicle} ({self.sale.sale_number})"

    def clean(self):
        super().clean()
        if self.vehicle_id:
            # When editing, exclude self from the availability check
            qs = Vehicle.objects.filter(pk=self.vehicle_id)
            vehicle = qs.first()
            if vehicle:
                if self.pk:
                    # Editing: vehicle is already 'sold' linked to this item — allow it
                    existing = SaleLineItem.objects.filter(pk=self.pk).first()
                    if existing and existing.vehicle_id == self.vehicle_id:
                        pass  # same vehicle, fine
                    elif vehicle.status not in ["available", "reserved"]:
                        raise ValidationError(
                            {"vehicle": "Ce véhicule n'est pas disponible à la vente."}
                        )
                else:
                    if vehicle.status not in ["available", "reserved"]:
                        raise ValidationError(
                            {"vehicle": "Ce véhicule n'est pas disponible à la vente."}
                        )

    def save(self, *args, **kwargs):
        # Auto line_number
        if not self.line_number:
            last = (
                SaleLineItem.objects.filter(sale=self.sale)
                .order_by("-line_number")
                .values_list("line_number", flat=True)
                .first()
            )
            self.line_number = (last or 0) + 1

        # Detect vehicle change on edit
        old_vehicle_id = None
        if self.pk:
            old = (
                SaleLineItem.objects.filter(pk=self.pk)
                .values_list("vehicle_id", flat=True)
                .first()
            )
            old_vehicle_id = old

        super().save(*args, **kwargs)

        # Restore old vehicle if it changed
        if old_vehicle_id and old_vehicle_id != self.vehicle_id:
            Vehicle.objects.filter(pk=old_vehicle_id).update(status="available")

        # Mark current vehicle as sold
        if self.vehicle_id:
            Vehicle.objects.filter(pk=self.vehicle_id).update(status="sold")

        # Recalculate commission
        self.sale.recalculate_commission()

    def delete(self, *args, **kwargs):
        vehicle_id = self.vehicle_id
        super().delete(*args, **kwargs)
        if vehicle_id:
            Vehicle.objects.filter(pk=vehicle_id).update(status="available")

    @property
    def margin_amount(self):
        return self.sale_price - self.vehicle.landed_cost

    @property
    def margin_percentage(self):
        lc = self.vehicle.landed_cost
        if lc > 0:
            return (self.margin_amount / lc) * 100
        return Decimal("0")


class Invoice(BaseModel):
    """Customer invoice for a vehicle sale (covers all line items)."""

    INVOICE_STATUS = [
        ("draft", "Brouillon"),
        ("issued", "Émise"),
        ("paid", "Payée"),
        ("cancelled", "Annulée"),
    ]

    invoice_number = models.CharField(
        max_length=20, unique=True, verbose_name="Numéro de facture"
    )
    invoice_date = models.DateField(verbose_name="Date de facture")
    due_date = models.DateField(verbose_name="Date d'échéance")

    sale = models.OneToOneField(Sale, on_delete=models.PROTECT, verbose_name="Vente")
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, verbose_name="Client"
    )

    subtotal_ht = models.DecimalField(
        max_digits=15, decimal_places=2, verbose_name="Sous-total HT (DA)"
    )
    tva_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=19.00,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        verbose_name="Taux TVA (%)",
    )
    tva_amount = models.DecimalField(
        max_digits=15, decimal_places=2, verbose_name="Montant TVA (DA)"
    )
    total_ttc = models.DecimalField(
        max_digits=15, decimal_places=2, verbose_name="Total TTC (DA)"
    )
    timbre_fiscal = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0,
        verbose_name="Timbre fiscal (DA)",
    )
    amount_paid = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name="Montant payé (DA)",
    )
    balance_due = models.DecimalField(
        max_digits=15, decimal_places=2, verbose_name="Solde dû (DA)"
    )
    status = models.CharField(
        max_length=20, choices=INVOICE_STATUS, default="draft", verbose_name="Statut"
    )
    notes = models.TextField(blank=True, verbose_name="Notes")

    class Meta:
        verbose_name = "Facture"
        verbose_name_plural = "Factures"
        ordering = ["-invoice_date", "-created_at"]

    def __str__(self):
        return f"Facture {self.invoice_number} — {self.customer.name}"

    def clean(self):
        super().clean()
        if self.due_date and self.invoice_date and self.due_date < self.invoice_date:
            raise ValidationError(
                {
                    "due_date": "La date d'échéance ne peut pas être antérieure à la date de facture."
                }
            )

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = self.generate_invoice_number()
        self.calculate_tax_amounts()
        self.balance_due = self.total_a_payer - self.amount_paid
        if self.balance_due <= 0:
            self.status = "paid"
        elif self.amount_paid > 0:
            self.status = "issued"
        super().save(*args, **kwargs)

    def generate_invoice_number(self):
        from datetime import datetime

        today = datetime.now()
        prefix = f"INV-{today.strftime('%Y%m%d')}"
        last = (
            Invoice.objects.filter(invoice_number__startswith=prefix)
            .order_by("-invoice_number")
            .first()
        )
        if last:
            try:
                new_num = int(last.invoice_number.split("-")[-1]) + 1
            except (ValueError, IndexError):
                new_num = 1
        else:
            new_num = 1
        return f"{prefix}-{new_num:03d}"

    def calculate_tax_amounts(self):
        """Calculate tax amounts from total sale price (all line items)."""
        if self.sale_id:
            self.total_ttc = self.sale.sale_price
            self.subtotal_ht = self.total_ttc / (1 + (self.tva_rate / 100))
            self.tva_amount = self.total_ttc - self.subtotal_ht
            # Timbre fiscal: 2% of TTC when payment method is cash
            if self.sale.payment_method == "cash":
                self.timbre_fiscal = (self.total_ttc * Decimal("0.02")).quantize(
                    Decimal("0.01")
                )
            else:
                self.timbre_fiscal = Decimal("0")

    @property
    def total_a_payer(self):
        """Total including timbre fiscal."""
        return self.total_ttc + self.timbre_fiscal

    @property
    def is_overdue(self):
        return (
            self.status in ["issued"]
            and self.due_date < timezone.now().date()
            and self.balance_due > 0
        )

    @property
    def days_overdue(self):
        if self.is_overdue:
            return (timezone.now().date() - self.due_date).days
        return 0
