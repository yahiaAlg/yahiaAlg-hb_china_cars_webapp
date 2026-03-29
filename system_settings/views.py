from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Q
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.utils import timezone
from .models import (
    SystemConfiguration,
    ExchangeRateHistory,
    TaxRateHistory,
    SystemLog,
)
from .forms import (
    SystemConfigurationForm,
    ExchangeRateForm,
    TaxRateForm,
    ExchangeRateSearchForm,
    SystemLogFilterForm,
    UserCreateForm,
    UserEditForm,
    UserProfileForm,
    AdminSetPasswordForm,
)
from core.models import UserProfile
from core.decorators import manager_required


@manager_required
def system_configuration(request):
    config = SystemConfiguration.get_current()
    if request.method == "POST":
        form = SystemConfigurationForm(request.POST, instance=config)
        if form.is_valid():
            config = form.save(commit=False)
            config.updated_by = request.user
            config.save()
            SystemLog.log(
                level="info",
                action_type="update",
                message="Configuration système mise à jour",
                user=request.user,
                request=request,
            )
            messages.success(request, "Configuration système mise à jour avec succès.")
            return redirect("system_settings:configuration")
    else:
        form = SystemConfigurationForm(instance=config)
    return render(
        request, "system_settings/configuration.html", {"form": form, "config": config}
    )


@manager_required
def exchange_rates(request):
    search_form = ExchangeRateSearchForm(request.GET)
    rates = ExchangeRateHistory.objects.select_related("from_currency", "to_currency")
    if search_form.is_valid():
        if search_form.cleaned_data.get("from_currency"):
            rates = rates.filter(
                from_currency=search_form.cleaned_data["from_currency"]
            )
        if search_form.cleaned_data.get("to_currency"):
            rates = rates.filter(to_currency=search_form.cleaned_data["to_currency"])
        if search_form.cleaned_data.get("date_from"):
            rates = rates.filter(
                effective_date__gte=search_form.cleaned_data["date_from"]
            )
        if search_form.cleaned_data.get("date_to"):
            rates = rates.filter(
                effective_date__lte=search_form.cleaned_data["date_to"]
            )

    current_rates = {}
    for rate in rates:
        key = f"{rate.from_currency.code}_{rate.to_currency.code}"
        if (
            key not in current_rates
            or rate.effective_date > current_rates[key].effective_date
        ):
            current_rates[key] = rate

    paginator = Paginator(rates, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "system_settings/exchange_rates.html",
        {
            "page_obj": page_obj,
            "search_form": search_form,
            "current_rates": current_rates.values(),
            "total_count": rates.count(),
        },
    )


@manager_required
def exchange_rate_create(request):
    if request.method == "POST":
        form = ExchangeRateForm(request.POST)
        if form.is_valid():
            rate = form.save(commit=False)
            rate.created_by = request.user
            rate.save()
            SystemLog.log(
                level="info",
                action_type="create",
                message=f"Nouveau taux de change: {rate}",
                user=request.user,
                request=request,
            )
            messages.success(request, "Taux de change enregistré avec succès.")
            return redirect("system_settings:exchange_rates")
    else:
        form = ExchangeRateForm()
    return render(
        request,
        "system_settings/exchange_rate_form.html",
        {"form": form, "title": "Nouveau Taux de Change"},
    )


@manager_required
def exchange_rate_edit(request, pk):
    rate = get_object_or_404(ExchangeRateHistory, pk=pk)
    if request.method == "POST":
        form = ExchangeRateForm(request.POST, instance=rate)
        if form.is_valid():
            rate = form.save(commit=False)
            rate.updated_by = request.user
            rate.save()
            SystemLog.log(
                level="info",
                action_type="update",
                message=f"Taux de change modifié: {rate}",
                user=request.user,
                request=request,
            )
            messages.success(request, "Taux de change modifié avec succès.")
            return redirect("system_settings:exchange_rates")
    else:
        form = ExchangeRateForm(instance=rate)
    return render(
        request,
        "system_settings/exchange_rate_form.html",
        {"form": form, "rate": rate, "title": "Modifier Taux de Change"},
    )


@manager_required
def tax_rates(request):
    rates = TaxRateHistory.objects.all()
    current_rates = {}
    for rate in rates:
        if (
            rate.tax_type not in current_rates
            or rate.effective_date > current_rates[rate.tax_type].effective_date
        ):
            current_rates[rate.tax_type] = rate
    paginator = Paginator(rates, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "system_settings/tax_rates.html",
        {
            "page_obj": page_obj,
            "current_rates": current_rates.values(),
            "total_count": rates.count(),
        },
    )


@manager_required
def tax_rate_create(request):
    if request.method == "POST":
        form = TaxRateForm(request.POST)
        if form.is_valid():
            rate = form.save(commit=False)
            rate.created_by = request.user
            rate.save()
            SystemLog.log(
                level="info",
                action_type="create",
                message=f"Nouveau taux de taxe: {rate}",
                user=request.user,
                request=request,
            )
            messages.success(request, "Taux de taxe enregistré avec succès.")
            return redirect("system_settings:tax_rates")
    else:
        form = TaxRateForm()
    return render(
        request,
        "system_settings/tax_rate_form.html",
        {"form": form, "title": "Nouveau Taux de Taxe"},
    )


@manager_required
def tax_rate_edit(request, pk):
    rate = get_object_or_404(TaxRateHistory, pk=pk)
    if request.method == "POST":
        form = TaxRateForm(request.POST, instance=rate)
        if form.is_valid():
            rate = form.save(commit=False)
            rate.updated_by = request.user
            rate.save()
            SystemLog.log(
                level="info",
                action_type="update",
                message=f"Taux de taxe modifié: {rate}",
                user=request.user,
                request=request,
            )
            messages.success(request, "Taux de taxe modifié avec succès.")
            return redirect("system_settings:tax_rates")
    else:
        form = TaxRateForm(instance=rate)
    return render(
        request,
        "system_settings/tax_rate_form.html",
        {"form": form, "rate": rate, "title": "Modifier Taux de Taxe"},
    )


@manager_required
def system_logs(request):
    filter_form = SystemLogFilterForm(request.GET)
    logs = SystemLog.objects.select_related("user")
    if filter_form.is_valid():
        cd = filter_form.cleaned_data
        if cd.get("level"):
            logs = logs.filter(level=cd["level"])
        if cd.get("action_type"):
            logs = logs.filter(action_type=cd["action_type"])
        if cd.get("user"):
            logs = logs.filter(user__username__icontains=cd["user"])
        if cd.get("date_from"):
            logs = logs.filter(created_at__gte=cd["date_from"])
        if cd.get("date_to"):
            logs = logs.filter(created_at__lte=cd["date_to"])
        if cd.get("search"):
            logs = logs.filter(message__icontains=cd["search"])

    stats = {
        "total_logs": logs.count(),
        "error_count": logs.filter(level="error").count(),
        "warning_count": logs.filter(level="warning").count(),
        "info_count": logs.filter(level="info").count(),
    }
    critical_logs = logs.filter(level__in=["error", "critical"])[:10]
    paginator = Paginator(logs, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "system_settings/system_logs.html",
        {
            "page_obj": page_obj,
            "filter_form": filter_form,
            "stats": stats,
            "critical_logs": critical_logs,
            "total_count": logs.count(),
        },
    )


@manager_required
def clear_old_logs(request):
    if request.method == "POST":
        days = int(request.POST.get("days", 30))
        cutoff_date = timezone.now() - timezone.timedelta(days=days)
        deleted_count, _ = SystemLog.objects.filter(created_at__lt=cutoff_date).delete()
        SystemLog.log(
            level="info",
            action_type="system",
            message=f"Nettoyage des logs: {deleted_count} entrées supprimées",
            user=request.user,
            request=request,
        )
        return JsonResponse(
            {
                "success": True,
                "message": f"{deleted_count} entrées supprimées.",
                "deleted_count": deleted_count,
            }
        )
    return JsonResponse({"success": False, "message": "Méthode non autorisée."})


@login_required
def ajax_latest_exchange_rate(request):
    from_currency = request.GET.get("from_currency")
    to_currency = request.GET.get("to_currency", "DA")
    if not from_currency:
        return JsonResponse({"error": "From currency required"})
    try:
        rate = ExchangeRateHistory.get_latest_rate(from_currency, to_currency)
        if rate:
            return JsonResponse(
                {
                    "success": True,
                    "rate": float(rate.rate),
                    "effective_date": rate.effective_date.strftime("%Y-%m-%d"),
                    "source": rate.source,
                }
            )
        return JsonResponse(
            {
                "success": False,
                "message": f"Aucun taux pour {from_currency}→{to_currency}",
            }
        )
    except Exception as e:
        return JsonResponse({"error": str(e)})


@manager_required
def system_status(request):
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM django_session")
        active_sessions = cursor.fetchone()[0]

    recent_logs = SystemLog.objects.select_related("user")[:10]
    config = SystemConfiguration.get_current()
    current_rates = {}
    for code in ["USD", "CNY"]:
        rate = ExchangeRateHistory.get_latest_rate(code, "DA")
        if rate:
            current_rates[code] = rate

    return render(
        request,
        "system_settings/system_status.html",
        {
            "active_sessions": active_sessions,
            "recent_logs": recent_logs,
            "config": config,
            "current_rates": current_rates,
        },
    )


# ─────────────────────────────────────────────────────────────
# User Management Views
# ─────────────────────────────────────────────────────────────


@manager_required
def user_list(request):
    qs = User.objects.select_related("userprofile").order_by("-date_joined")

    q = request.GET.get("q", "").strip()
    role = request.GET.get("role", "")
    status = request.GET.get("status", "")

    if q:
        qs = qs.filter(
            Q(username__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(email__icontains=q)
        )
    if role:
        qs = qs.filter(userprofile__role=role)
    if status == "active":
        qs = qs.filter(is_active=True)
    elif status == "inactive":
        qs = qs.filter(is_active=False)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "system_settings/user_list.html",
        {
            "page_obj": page_obj,
            "total_count": qs.count(),
            "trader_count": User.objects.filter(userprofile__role="trader").count(),
            "manager_count": User.objects.filter(userprofile__role="manager").count(),
            "active_count": User.objects.filter(is_active=True).count(),
            "inactive_count": User.objects.filter(is_active=False).count(),
        },
    )


@manager_required
def user_create(request):
    if request.method == "POST":
        form = UserCreateForm(request.POST)
        profile_form = UserProfileForm(request.POST)
        if form.is_valid() and profile_form.is_valid():
            user = form.save()
            # The signal already creates a UserProfile with role='trader';
            # update it with the submitted values instead of creating a duplicate.
            profile = user.userprofile
            profile.role = profile_form.cleaned_data["role"]
            profile.phone = profile_form.cleaned_data.get("phone", "")
            profile.default_commission_rate = profile_form.cleaned_data.get(
                "default_commission_rate", 10
            )
            profile.save()
            SystemLog.log(
                level="info",
                action_type="create",
                message=f"Utilisateur créé : {user.username} (rôle : {profile.role})",
                user=request.user,
                request=request,
            )
            messages.success(
                request, f"Utilisateur '{user.username}' créé avec succès."
            )
            return redirect("system_settings:user_list")
    else:
        form = UserCreateForm()
        profile_form = UserProfileForm()

    return render(
        request,
        "system_settings/user_form.html",
        {
            "title": "Créer un Utilisateur",
            "form": form,
            "profile_form": profile_form,
        },
    )


@manager_required
def user_edit(request, pk):
    target_user = get_object_or_404(User, pk=pk)
    profile, _ = UserProfile.objects.get_or_create(user=target_user)

    if request.method == "POST":
        form = UserEditForm(request.POST, instance=target_user)
        profile_form = UserProfileForm(request.POST, instance=profile)
        if form.is_valid() and profile_form.is_valid():
            form.save()
            profile_form.save()
            SystemLog.log(
                level="info",
                action_type="update",
                message=f"Profil utilisateur modifié : {target_user.username}",
                user=request.user,
                request=request,
            )
            messages.success(request, "Utilisateur mis à jour avec succès.")
            return redirect("system_settings:user_list")
    else:
        form = UserEditForm(instance=target_user)
        profile_form = UserProfileForm(instance=profile)

    return render(
        request,
        "system_settings/user_form.html",
        {
            "title": f"Modifier — {target_user.get_full_name() or target_user.username}",
            "form": form,
            "profile_form": profile_form,
            "object": target_user,
        },
    )


@manager_required
def user_change_password(request, pk):
    target_user = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        form = AdminSetPasswordForm(target_user, request.POST)
        if form.is_valid():
            form.save()
            SystemLog.log(
                level="info",
                action_type="update",
                message=f"Mot de passe changé pour : {target_user.username}",
                user=request.user,
                request=request,
            )
            messages.success(
                request, f"Mot de passe mis à jour pour '{target_user.username}'."
            )
            return redirect("system_settings:user_edit", pk=pk)
    else:
        form = AdminSetPasswordForm(target_user)

    return render(
        request,
        "system_settings/user_change_password.html",
        {
            "form": form,
            "target_user": target_user,
        },
    )


@manager_required
def user_toggle_active(request, pk):
    target_user = get_object_or_404(User, pk=pk)
    if target_user == request.user:
        messages.error(request, "Vous ne pouvez pas désactiver votre propre compte.")
    else:
        target_user.is_active = not target_user.is_active
        target_user.save(update_fields=["is_active"])
        state = "activé" if target_user.is_active else "désactivé"
        SystemLog.log(
            level="info",
            action_type="update",
            message=f"Compte {state} : {target_user.username}",
            user=request.user,
            request=request,
        )
        messages.success(request, f"Compte '{target_user.username}' {state}.")
    return redirect("system_settings:user_list")
