from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, SetPasswordForm
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Row, Column, Submit, Fieldset
from .models import (
    SystemConfiguration,
    ExchangeRateHistory,
    TaxRateHistory,
    UserPreference,
    SystemLog,
)
from core.models import Currency, UserProfile


class SystemConfigurationForm(forms.ModelForm):

    class Meta:
        model = SystemConfiguration
        fields = [
            "company_name",
            "company_nif",
            "company_address",
            "company_phone",
            "company_email",
            "default_tva_rate",
            "default_tariff_rate",
            "default_commission_rate",
            "reservation_duration_days",
            "invoice_due_days",
            "enable_email_notifications",
            "enable_overdue_alerts",
            "overdue_alert_days",
        ]
        widgets = {
            "company_address": forms.Textarea(attrs={"rows": 3}),
            "default_tva_rate": forms.NumberInput(attrs={"step": "0.01"}),
            "default_tariff_rate": forms.NumberInput(attrs={"step": "0.01"}),
            "default_commission_rate": forms.NumberInput(attrs={"step": "0.01"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset(
                "Informations de l'Entreprise",
                "company_name",
                "company_nif",
                "company_address",
                Row(
                    Column("company_phone", css_class="form-group col-md-6"),
                    Column("company_email", css_class="form-group col-md-6"),
                ),
            ),
            Fieldset(
                "Taux par Défaut",
                Row(
                    Column("default_tva_rate", css_class="form-group col-md-4"),
                    Column("default_tariff_rate", css_class="form-group col-md-4"),
                    Column("default_commission_rate", css_class="form-group col-md-4"),
                ),
            ),
            Fieldset(
                "Paramètres Système",
                Row(
                    Column(
                        "reservation_duration_days", css_class="form-group col-md-6"
                    ),
                    Column("invoice_due_days", css_class="form-group col-md-6"),
                ),
            ),
            Fieldset(
                "Notifications",
                Row(
                    Column(
                        "enable_email_notifications", css_class="form-group col-md-4"
                    ),
                    Column("enable_overdue_alerts", css_class="form-group col-md-4"),
                    Column("overdue_alert_days", css_class="form-group col-md-4"),
                ),
            ),
            Submit(
                "submit", "Enregistrer la Configuration", css_class="btn btn-primary"
            ),
        )


class ExchangeRateForm(forms.ModelForm):

    class Meta:
        model = ExchangeRateHistory
        fields = [
            "from_currency",
            "to_currency",
            "rate",
            "effective_date",
            "source",
            "notes",
        ]
        widgets = {
            "effective_date": forms.DateInput(attrs={"type": "date"}),
            "rate": forms.NumberInput(attrs={"step": "0.000001"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(
                Column("from_currency", css_class="form-group col-md-6"),
                Column("to_currency", css_class="form-group col-md-6"),
            ),
            Row(
                Column("rate", css_class="form-group col-md-6"),
                Column("effective_date", css_class="form-group col-md-6"),
            ),
            "source",
            "notes",
            Submit("submit", "Enregistrer le Taux", css_class="btn btn-primary"),
        )
        if not self.instance.pk:
            from django.utils import timezone

            self.fields["effective_date"].initial = timezone.now().date()
            try:
                da_currency = Currency.objects.get(code="DA")
                self.fields["to_currency"].initial = da_currency
            except Currency.DoesNotExist:
                pass


class TaxRateForm(forms.ModelForm):

    class Meta:
        model = TaxRateHistory
        fields = ["tax_type", "rate", "effective_date", "description"]
        widgets = {
            "effective_date": forms.DateInput(attrs={"type": "date"}),
            "rate": forms.NumberInput(attrs={"step": "0.01"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(
                Column("tax_type", css_class="form-group col-md-6"),
                Column("rate", css_class="form-group col-md-6"),
            ),
            "effective_date",
            "description",
            Submit("submit", "Enregistrer le Taux", css_class="btn btn-primary"),
        )
        if not self.instance.pk:
            from django.utils import timezone

            self.fields["effective_date"].initial = timezone.now().date()


class ExchangeRateSearchForm(forms.Form):
    from_currency = forms.ModelChoiceField(
        queryset=Currency.objects.filter(is_active=True),
        required=False,
        empty_label="Toutes les devises source",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    to_currency = forms.ModelChoiceField(
        queryset=Currency.objects.filter(is_active=True),
        required=False,
        empty_label="Toutes les devises cible",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )


class SystemLogFilterForm(forms.Form):
    level = forms.ChoiceField(
        choices=[("", "Tous les niveaux")] + SystemLog.LOG_LEVELS,
        required=False,
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    action_type = forms.ChoiceField(
        choices=[("", "Toutes les actions")] + SystemLog.ACTION_TYPES,
        required=False,
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    user = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(
            attrs={"placeholder": "Nom d'utilisateur", "class": "form-control"}
        ),
    )
    date_from = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local", "class": "form-control"}
        ),
    )
    date_to = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local", "class": "form-control"}
        ),
    )
    search = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Rechercher dans les messages...",
                "class": "form-control",
            }
        ),
    )


# ─────────────────────────────────────────────────────────────
# User Management Forms
# ─────────────────────────────────────────────────────────────


class UserCreateForm(UserCreationForm):
    first_name = forms.CharField(max_length=150, required=True, label="Prénom")
    last_name = forms.CharField(max_length=150, required=True, label="Nom")
    email = forms.EmailField(required=False, label="Email")
    is_active = forms.BooleanField(required=False, initial=True, label="Compte actif")

    class Meta:
        model = User
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "is_active",
            "password1",
            "password2",
        ]


class UserEditForm(forms.ModelForm):
    first_name = forms.CharField(max_length=150, required=True, label="Prénom")
    last_name = forms.CharField(max_length=150, required=True, label="Nom")
    email = forms.EmailField(required=False, label="Email")
    is_active = forms.BooleanField(required=False, label="Compte actif")

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "is_active"]


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ["role", "phone", "default_commission_rate"]
        labels = {
            "role": "Rôle",
            "phone": "Téléphone / WhatsApp",
            "default_commission_rate": "Taux de commission par défaut (%)",
        }


class AdminSetPasswordForm(SetPasswordForm):
    """Password change form that does not require the old password."""

    pass
