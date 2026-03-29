from django.urls import path
from . import views

app_name = "system_settings"

urlpatterns = [
    # System
    path("", views.system_status, name="system_status"),
    path("configuration/", views.system_configuration, name="configuration"),
    # Exchange rates
    path("exchange-rates/", views.exchange_rates, name="exchange_rates"),
    path(
        "exchange-rates/create/",
        views.exchange_rate_create,
        name="exchange_rate_create",
    ),
    path(
        "exchange-rates/<int:pk>/edit/",
        views.exchange_rate_edit,
        name="exchange_rate_edit",
    ),
    # Tax rates
    path("tax-rates/", views.tax_rates, name="tax_rates"),
    path("tax-rates/create/", views.tax_rate_create, name="tax_rate_create"),
    path("tax-rates/<int:pk>/edit/", views.tax_rate_edit, name="tax_rate_edit"),
    # System logs
    path("system-logs/", views.system_logs, name="system_logs"),
    path("system-logs/clear/", views.clear_old_logs, name="clear_old_logs"),
    # AJAX
    path("ajax/latest-rate/", views.ajax_latest_exchange_rate, name="ajax_latest_rate"),
    # ── User management ──────────────────────────────────────
    path("users/", views.user_list, name="user_list"),
    path("users/create/", views.user_create, name="user_create"),
    path("users/<int:pk>/edit/", views.user_edit, name="user_edit"),
    path(
        "users/<int:pk>/password/",
        views.user_change_password,
        name="user_change_password",
    ),
    path("users/<int:pk>/toggle/", views.user_toggle_active, name="user_toggle_active"),
]
