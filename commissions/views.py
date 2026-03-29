from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.utils import timezone
from datetime import timedelta
from .models import (
    CommissionTier,
    CommissionPeriod,
    CommissionSummary,
    CommissionAdjustment,
)
from .forms import (
    CommissionTierForm,
    CommissionAdjustmentForm,
    CommissionPaymentForm,
    CommissionReportForm,
    TraderPerformanceFilterForm,
)
from sales.models import Sale, SaleLineItem
from core.decorators import manager_required


def commission_index(request):
    """Route to the appropriate commissions page based on role."""
    if hasattr(request.user, "userprofile") and request.user.userprofile.is_trader:
        return redirect("commissions:my_commission")
    return redirect("commissions:overview")


@login_required
def my_commission(request):
    """Trader's own commission view"""

    if (
        not hasattr(request.user, "userprofile")
        or not request.user.userprofile.is_trader
    ):
        messages.error(request, "Accès réservé aux traders.")
        return redirect("core:dashboard")

    today = timezone.now().date()
    current_year = int(request.GET.get("year", today.year))
    current_month = int(request.GET.get("month", today.month))

    # Sales for this period
    sales_qs = Sale.objects.filter(
        assigned_trader=request.user,
        sale_date__year=current_year,
        sale_date__month=current_month,
        is_finalized=True,
    ).prefetch_related("line_items__vehicle", "customer")

    # Build flat list for template (one row per line item)
    sales_for_display = []
    for sale in sales_qs:
        for item in sale.line_items.all():
            sales_for_display.append(
                {
                    "vehicle": item.vehicle,
                    "customer": sale.customer,
                    "sale_date": sale.sale_date,
                    "commission_amount": sale.commission_amount or 0,
                    "sale": sale,
                }
            )

    total_commission = sum(s.commission_amount or 0 for s in sales_qs)
    total_margin = sum(s.margin_amount for s in sales_qs)

    # Get or create current period
    try:
        period = CommissionPeriod.objects.get(year=current_year, month=current_month)
    except CommissionPeriod.DoesNotExist:
        period = None

    # Commission summary for closed period
    summary = None
    if period:
        summary = CommissionSummary.objects.filter(
            trader=request.user, period=period
        ).first()

    # If no closed summary, build a live one
    if not summary:
        from types import SimpleNamespace

        summary = SimpleNamespace(
            sales_count=sales_qs.count(),
            total_commission=total_commission,
            total_margin=total_margin,
            total_sales_value=sum(s.sale_price for s in sales_qs),
            base_commission=total_commission,
            tier_bonus=0,
            payout_status="pending",
            payout_date=None,
            payout_reference=None,
            get_payout_status_display=lambda: "En attente",
        )

    adjustments = (
        CommissionAdjustment.objects.filter(trader=request.user, period=period)
        if period
        else []
    )

    tiers = CommissionTier.objects.filter(is_active=True).order_by("min_sales_count")

    past_summaries = (
        CommissionSummary.objects.filter(trader=request.user)
        .select_related("period")
        .order_by("-period__year", "-period__month")[:6]
    )

    context = {
        "summary": summary,
        "current_period": period,
        "sales": sales_for_display,
        "adjustments": adjustments,
        "tiers": tiers,
        "past_summaries": past_summaries,
        "current_year": current_year,
        "current_month": current_month,
    }

    return render(request, "commissions/my_commission.html", context)


@manager_required
def commission_overview(request):
    """Manager overview of all commissions"""

    filter_form = CommissionReportForm(request.GET or None)

    summaries = CommissionSummary.objects.select_related(
        "trader__userprofile", "period"
    ).prefetch_related("commission_payment")

    if filter_form.is_valid():
        year = filter_form.cleaned_data.get("year")
        if year:
            summaries = summaries.filter(period__year=year)
        month = filter_form.cleaned_data.get("month")
        if month:
            summaries = summaries.filter(period__month=month)
        trader = filter_form.cleaned_data.get("trader")
        if trader:
            summaries = summaries.filter(trader=trader)
        payout_status = filter_form.cleaned_data.get("payout_status")
        if payout_status:
            summaries = summaries.filter(payout_status=payout_status)
    else:
        # Default: current year
        summaries = summaries.filter(period__year=timezone.now().year)

    summaries = summaries.order_by("-period__year", "-period__month")

    total_commission = summaries.aggregate(t=Sum("total_commission"))["t"] or 0

    pending_amount = (
        summaries.filter(payout_status__in=["pending", "approved"]).aggregate(
            t=Sum("total_commission")
        )["t"]
        or 0
    )

    active_traders_count = summaries.values("trader").distinct().count()
    total_sales_count = summaries.aggregate(t=Sum("sales_count"))["t"] or 0

    today = timezone.now().date()
    try:
        current_period = CommissionPeriod.objects.get(
            year=today.year, month=today.month
        )
    except CommissionPeriod.DoesNotExist:
        current_period = CommissionPeriod.objects.order_by("-year", "-month").first()

    context = {
        "summaries": summaries,
        "filter_form": filter_form,
        "total_commission": total_commission,
        "pending_amount": pending_amount,
        "active_traders_count": active_traders_count,
        "total_sales_count": total_sales_count,
        "current_period": current_period,
    }

    return render(request, "commissions/overview.html", context)


@manager_required
def trader_performance(request):
    """Trader performance comparison"""

    filter_form = TraderPerformanceFilterForm(request.GET or None)

    traders = User.objects.filter(
        userprofile__role__in=["trader", "manager"], is_active=True
    ).select_related("userprofile")

    traders_data = []

    for trader in traders:
        sales = Sale.objects.filter(
            assigned_trader=trader, is_finalized=True
        ).prefetch_related("line_items__vehicle")

        if filter_form.is_valid():
            period_from = filter_form.cleaned_data.get("period_from")
            if period_from:
                sales = sales.filter(sale_date__gte=period_from)
            period_to = filter_form.cleaned_data.get("period_to")
            if period_to:
                sales = sales.filter(sale_date__lte=period_to)

        sales_count = sales.count()
        if sales_count == 0:
            continue

        min_sales = (
            filter_form.cleaned_data.get("min_sales")
            if filter_form.is_valid()
            else None
        )
        if min_sales and sales_count < min_sales:
            continue

        # sale_price is a property — must iterate
        total_sales_value = sum(s.sale_price for s in sales)
        total_margin = sum(s.margin_amount for s in sales)
        total_commission = sales.aggregate(t=Sum("commission_amount"))["t"] or 0

        average_commission_rate = (
            (float(total_commission) / float(total_margin) * 100)
            if total_margin > 0
            else 0
        )

        traders_data.append(
            {
                "trader": trader,
                "sales_count": sales_count,
                "total_sales_value": total_sales_value,
                "total_margin": total_margin,
                "total_commission": total_commission,
                "average_commission_rate": average_commission_rate,
            }
        )

    sort_by = "total_commission"
    if filter_form.is_valid():
        sort_by = filter_form.cleaned_data.get("sort_by") or sort_by

    traders_data.sort(key=lambda x: x.get(sort_by, 0), reverse=True)

    max_sales = max((t["sales_count"] for t in traders_data), default=1)

    # Build period range label
    period_range = None
    if filter_form.is_valid():
        pf = filter_form.cleaned_data.get("period_from")
        pt = filter_form.cleaned_data.get("period_to")
        if pf and pt:
            period_range = f"{pf.strftime('%b %Y')} – {pt.strftime('%b %Y')}"
        elif pf:
            period_range = f"Depuis {pf.strftime('%b %Y')}"

    context = {
        "traders_data": traders_data,
        "filter_form": filter_form,
        "max_sales": max_sales,
        "period_range": period_range,
    }

    return render(request, "commissions/trader_performance.html", context)


@manager_required
def commission_tiers(request):
    tiers = CommissionTier.objects.all()
    return render(request, "commissions/tiers.html", {"tiers": tiers})


@manager_required
def commission_tier_create(request):
    if request.method == "POST":
        form = CommissionTierForm(request.POST)
        if form.is_valid():
            tier = form.save(commit=False)
            tier.created_by = request.user
            tier.save()
            messages.success(
                request, f"Niveau de commission '{tier.name}' créé avec succès."
            )
            return redirect("commissions:tiers")
    else:
        form = CommissionTierForm()
    return render(
        request,
        "commissions/tier_form.html",
        {"form": form, "title": "Nouveau Niveau de Commission"},
    )


@manager_required
def commission_tier_edit(request, pk):
    tier = get_object_or_404(CommissionTier, pk=pk)
    if request.method == "POST":
        form = CommissionTierForm(request.POST, instance=tier)
        if form.is_valid():
            tier = form.save(commit=False)
            tier.updated_by = request.user
            tier.save()
            messages.success(
                request, f"Niveau de commission '{tier.name}' modifié avec succès."
            )
            return redirect("commissions:tiers")
    else:
        form = CommissionTierForm(instance=tier)
    return render(
        request,
        "commissions/tier_form.html",
        {"form": form, "tier": tier, "title": f"Modifier {tier.name}"},
    )


@manager_required
def commission_adjustment_create(request, summary_id):
    summary = get_object_or_404(CommissionSummary, pk=summary_id)
    if request.method == "POST":
        form = CommissionAdjustmentForm(request.POST, period=summary.period)
        if form.is_valid():
            adjustment = form.save(commit=False)
            adjustment.approved_by = request.user
            adjustment.created_by = request.user
            adjustment.save()
            messages.success(
                request, "Ajustement de commission enregistré avec succès."
            )
            return redirect("commissions:overview")
    else:
        form = CommissionAdjustmentForm(period=summary.period)
        form.fields["trader"].initial = summary.trader
    return render(
        request,
        "commissions/adjustment_form.html",
        {
            "form": form,
            "summary": summary,
            "title": f"Ajustement - {summary.trader.get_full_name()}",
        },
    )


@manager_required
def commission_payment_create(request, summary_id):
    summary = get_object_or_404(CommissionSummary, pk=summary_id)
    if hasattr(summary, "commission_payment"):
        messages.warning(request, "Cette commission a déjà été payée.")
        return redirect("commissions:overview")
    if request.method == "POST":
        form = CommissionPaymentForm(request.POST, summary=summary)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.paid_by = request.user
            payment.created_by = request.user
            payment.save()
            messages.success(
                request,
                f"Paiement de commission enregistré pour {summary.trader.get_full_name()}.",
            )
            return redirect("commissions:overview")
    else:
        form = CommissionPaymentForm(summary=summary)
    return render(
        request,
        "commissions/payment_form.html",
        {
            "form": form,
            "summary": summary,
            "title": f"Paiement Commission - {summary.trader.get_full_name()}",
        },
    )


@manager_required
def close_commission_period(request, year, month):
    """Close commission period — accepts both GET (with confirm dialog) and POST."""
    period, _ = CommissionPeriod.objects.get_or_create(
        year=year, month=month, defaults={"created_by": request.user}
    )
    if period.is_closed:
        messages.warning(request, "Cette période est déjà fermée.")
    else:
        period.close_period(request.user)
        messages.success(request, f"Période {period} fermée et commissions calculées.")
    return redirect("commissions:overview")


@manager_required
def approve_commission(request, summary_id):
    """Approve commission — accepts both GET and POST."""
    summary = get_object_or_404(CommissionSummary, pk=summary_id)
    if summary.payout_status == "pending":
        summary.payout_status = "approved"
        summary.updated_by = request.user
        summary.save()
        messages.success(
            request, f"Commission approuvée pour {summary.trader.get_full_name()}."
        )
    else:
        messages.warning(request, "Cette commission ne peut pas être approuvée.")
    return redirect("commissions:overview")


@login_required
def ajax_commission_calculation(request):
    trader_id = request.GET.get("trader_id")
    year = request.GET.get("year")
    month = request.GET.get("month")

    if not all([trader_id, year, month]):
        return JsonResponse({"error": "Missing parameters"})

    try:
        trader = User.objects.get(pk=trader_id)
        year, month = int(year), int(month)

        sales = Sale.objects.filter(
            assigned_trader=trader,
            sale_date__year=year,
            sale_date__month=month,
            is_finalized=True,
        ).prefetch_related("line_items__vehicle")

        sales_count = sales.count()
        total_commission = sales.aggregate(t=Sum("commission_amount"))["t"] or 0
        total_margin = sum(s.margin_amount for s in sales)
        total_sales_value = sum(s.sale_price for s in sales)

        applicable_tier = None
        tier_bonus = 0
        if sales_count > 0:
            applicable_tier = (
                CommissionTier.objects.filter(
                    is_active=True, min_sales_count__lte=sales_count
                )
                .filter(
                    Q(max_sales_count__gte=sales_count)
                    | Q(max_sales_count__isnull=True)
                )
                .first()
            )
            if applicable_tier and applicable_tier.commission_rate > 10:
                tier_bonus = float(total_margin) * (
                    float(applicable_tier.commission_rate - 10) / 100
                )

        return JsonResponse(
            {
                "success": True,
                "sales_count": sales_count,
                "total_sales_value": float(total_sales_value),
                "total_margin": float(total_margin),
                "base_commission": float(total_commission),
                "tier_bonus": float(tier_bonus),
                "total_commission": float(total_commission) + tier_bonus,
                "applicable_tier": applicable_tier.name if applicable_tier else None,
            }
        )
    except (User.DoesNotExist, ValueError):
        return JsonResponse({"error": "Invalid data"})
