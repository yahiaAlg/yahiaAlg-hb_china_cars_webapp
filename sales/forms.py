from django import forms
from django.forms import inlineformset_factory
from .models import Sale, SaleLineItem, Invoice
from inventory.models import Vehicle
from customers.models import Customer
from django.contrib.auth.models import User
from django.db.models import Q


class VehicleSelect(forms.Select):
    """Renders <option data-landed-cost="..."> so the JS markup calculator works."""

    def create_option(self, name, value, label, selected, index, **kwargs):
        option = super().create_option(name, value, label, selected, index, **kwargs)
        if value:
            try:
                from inventory.models import Vehicle

                v = (
                    Vehicle.objects.select_related("purchase_line_item")
                    .filter(pk=value)
                    .first()
                )
                lc = v.landed_cost if v else 0
                option["attrs"]["data-landed-cost"] = str(lc)
            except Exception:
                option["attrs"]["data-landed-cost"] = "0"
        return option


class SaleForm(forms.ModelForm):

    class Meta:
        model = Sale
        fields = [
            "sale_date",
            "customer",
            "assigned_trader",
            "payment_method",
            "down_payment",
            "commission_rate",
            "notes",
        ]
        widgets = {
            "sale_date": forms.DateInput(
                attrs={"type": "date", "class": "field-input"}
            ),
            "down_payment": forms.NumberInput(
                attrs={"step": "0.01", "class": "field-input"}
            ),
            "commission_rate": forms.NumberInput(
                attrs={"step": "0.01", "class": "field-input"}
            ),
            "notes": forms.Textarea(attrs={"rows": 3, "class": "field-input"}),
            "customer": forms.Select(attrs={"class": "field-input"}),
            "assigned_trader": forms.Select(attrs={"class": "field-input"}),
            "payment_method": forms.Select(attrs={"class": "field-input"}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        self.fields["customer"].queryset = Customer.objects.filter(is_active=True)
        self.fields["assigned_trader"].queryset = User.objects.filter(
            userprofile__role__in=["trader", "manager"], is_active=True
        )

        if not self.instance.pk:
            from django.utils import timezone
            from decimal import Decimal

            self.fields["sale_date"].initial = timezone.now().date()
            self.fields["commission_rate"].initial = Decimal("4.00")
            if self.user and hasattr(self.user, "userprofile"):
                if self.user.userprofile.is_trader:
                    self.fields["assigned_trader"].initial = self.user
                    self.fields["commission_rate"].initial = (
                        self.user.userprofile.default_commission_rate
                        if self.user.userprofile.default_commission_rate
                        else Decimal("4.00")
                    )


class SaleLineItemForm(forms.ModelForm):

    class Meta:
        model = SaleLineItem
        fields = ["vehicle", "sale_price", "notes"]
        widgets = {
            "vehicle": VehicleSelect(attrs={"class": "field-input vehicle-select"}),
            "sale_price": forms.NumberInput(
                attrs={
                    "step": "1",
                    "class": "field-input line-price",
                    "placeholder": "0",
                }
            ),
            "notes": forms.TextInput(
                attrs={
                    "class": "field-input",
                    "placeholder": "Notes (optionnel)…",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # On edit: include the already-assigned (sold) vehicle so it shows up
        if self.instance.pk and self.instance.vehicle_id:
            self.fields["vehicle"].queryset = Vehicle.objects.filter(
                Q(status__in=["available", "reserved"]) | Q(pk=self.instance.vehicle_id)
            ).select_related("purchase_line_item__purchase__supplier")
        else:
            self.fields["vehicle"].queryset = Vehicle.objects.filter(
                status__in=["available", "reserved"]
            ).select_related("purchase_line_item__purchase__supplier")

        self.fields["vehicle"].label = "Véhicule"
        self.fields["sale_price"].label = "Prix de vente (DA)"
        self.fields["notes"].label = "Notes"
        self.fields["notes"].required = False


SaleLineItemFormSet = inlineformset_factory(
    Sale,
    SaleLineItem,
    form=SaleLineItemForm,
    extra=1,
    can_delete=True,
    min_num=1,
    validate_min=True,
)


class InvoiceForm(forms.ModelForm):

    class Meta:
        model = Invoice
        fields = ["invoice_date", "due_date", "tva_rate", "notes"]
        widgets = {
            "invoice_date": forms.DateInput(
                attrs={"type": "date", "class": "field-input"}
            ),
            "due_date": forms.DateInput(attrs={"type": "date", "class": "field-input"}),
            "tva_rate": forms.NumberInput(
                attrs={"step": "0.01", "class": "field-input"}
            ),
            "notes": forms.Textarea(attrs={"rows": 3, "class": "field-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            from django.utils import timezone
            from datetime import timedelta

            today = timezone.now().date()
            self.fields["invoice_date"].initial = today
            self.fields["due_date"].initial = today + timedelta(days=30)


class SaleSearchForm(forms.Form):
    search = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Rechercher par numéro, client, véhicule…",
                "class": "field-input",
            }
        ),
    )
    trader = forms.ModelChoiceField(
        queryset=User.objects.filter(
            userprofile__role__in=["trader", "manager"], is_active=True
        ),
        required=False,
        empty_label="Tous les traders",
        widget=forms.Select(attrs={"class": "field-input"}),
    )
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.filter(is_active=True),
        required=False,
        empty_label="Tous les clients",
        widget=forms.Select(attrs={"class": "field-input"}),
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "field-input"}),
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "field-input"}),
    )
    payment_method = forms.ChoiceField(
        choices=[("", "Tous les modes")] + Sale.PAYMENT_METHODS,
        required=False,
        widget=forms.Select(attrs={"class": "field-input"}),
    )
    is_finalized = forms.ChoiceField(
        choices=[("", "Tous"), ("true", "Finalisées"), ("false", "Brouillons")],
        required=False,
        widget=forms.Select(attrs={"class": "field-input"}),
    )


class QuickSaleForm(forms.Form):
    """Single-vehicle quick sale — saved as one SaleLineItem."""

    vehicle = forms.ModelChoiceField(
        queryset=Vehicle.objects.filter(status="available"),
        widget=forms.Select(attrs={"class": "field-input"}),
        label="Véhicule",
    )
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.filter(is_active=True),
        widget=forms.Select(attrs={"class": "field-input"}),
        label="Client",
    )
    sale_price = forms.DecimalField(
        max_digits=15,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"step": "0.01", "class": "field-input"}),
        label="Prix de vente (DA)",
    )
    payment_method = forms.ChoiceField(
        choices=Sale.PAYMENT_METHODS,
        widget=forms.Select(attrs={"class": "field-input"}),
        label="Mode de paiement",
    )

    def save(self, user=None):
        from django.utils import timezone

        sale = Sale.objects.create(
            customer=self.cleaned_data["customer"],
            payment_method=self.cleaned_data["payment_method"],
            sale_date=timezone.now().date(),
            assigned_trader=user,
            commission_rate=(
                user.userprofile.default_commission_rate
                if user and hasattr(user, "userprofile")
                else 0
            ),
            created_by=user,
        )
        SaleLineItem.objects.create(
            sale=sale,
            vehicle=self.cleaned_data["vehicle"],
            sale_price=self.cleaned_data["sale_price"],
            line_number=1,
            created_by=user,
        )
        return sale
