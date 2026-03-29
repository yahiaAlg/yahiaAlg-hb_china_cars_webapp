from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum, Avg, Count
from django.core.paginator import Paginator
from django.http import JsonResponse
from .models import Sale, SaleLineItem, Invoice
from .forms import (
    SaleForm,
    SaleLineItemFormSet,
    InvoiceForm,
    SaleSearchForm,
    QuickSaleForm,
)
from inventory.models import Vehicle
from core.decorators import trader_required
from system_settings.models import SystemConfiguration


@login_required
def sale_list(request):
    sales = Sale.objects.select_related(
        "customer", "assigned_trader", "assigned_trader__userprofile"
    ).prefetch_related("line_items__vehicle", "invoice")

    search_form = SaleSearchForm(request.GET)

    if search_form.is_valid():
        search = search_form.cleaned_data.get("search")
        if search:
            sales = sales.filter(
                Q(sale_number__icontains=search)
                | Q(customer__name__icontains=search)
                | Q(line_items__vehicle__vin_chassis__icontains=search)
                | Q(line_items__vehicle__make__icontains=search)
                | Q(line_items__vehicle__model__icontains=search)
            ).distinct()

        trader = search_form.cleaned_data.get("trader")
        if trader:
            sales = sales.filter(assigned_trader=trader)

        customer = search_form.cleaned_data.get("customer")
        if customer:
            sales = sales.filter(customer=customer)

        date_from = search_form.cleaned_data.get("date_from")
        if date_from:
            sales = sales.filter(sale_date__gte=date_from)

        date_to = search_form.cleaned_data.get("date_to")
        if date_to:
            sales = sales.filter(sale_date__lte=date_to)

        payment_method = search_form.cleaned_data.get("payment_method")
        if payment_method:
            sales = sales.filter(payment_method=payment_method)

        is_finalized = search_form.cleaned_data.get("is_finalized")
        if is_finalized == "true":
            sales = sales.filter(is_finalized=True)
        elif is_finalized == "false":
            sales = sales.filter(is_finalized=False)

    if hasattr(request.user, "userprofile"):
        if request.user.userprofile.is_trader:
            sales = sales.filter(assigned_trader=request.user)

    sales = sales.annotate(vehicle_count_ann=Count("line_items"))

    stats = {
        "total_sales": sales.count(),
        "total_vehicles": SaleLineItem.objects.filter(sale__in=sales).count(),
        "total_commission": sales.aggregate(Sum("commission_amount"))[
            "commission_amount__sum"
        ]
        or 0,
    }

    paginator = Paginator(sales, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "sales/list.html",
        {
            "page_obj": page_obj,
            "search_form": search_form,
            "stats": stats,
            "total_count": sales.count(),
        },
    )


@trader_required
def sale_create(request):
    if request.method == "POST":
        form = SaleForm(request.POST, user=request.user)
        formset = SaleLineItemFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            sale = form.save(commit=False)
            sale.created_by = request.user
            # Always enforce commission rate from the assigned trader's profile
            if sale.assigned_trader and hasattr(sale.assigned_trader, "userprofile"):
                sale.commission_rate = (
                    sale.assigned_trader.userprofile.default_commission_rate
                )
            sale.save()
            formset.instance = sale
            items = formset.save(commit=False)
            for item in items:
                item.created_by = request.user
                item.save()
            for obj in formset.deleted_objects:
                obj.delete()
            sale.recalculate_commission()
            messages.success(
                request,
                f"Vente {sale.sale_number} créée avec succès. Veuillez maintenant générer la facture.",
            )
            # ── FLOW: sale → invoice creation ──────────────────────────────
            return redirect("sales:create_invoice", pk=sale.pk)
    else:
        # Pre-populate customer from query param (e.g., ?customer=42)
        initial = {}
        customer_id = request.GET.get("customer")
        if customer_id:
            try:
                from customers.models import Customer

                customer = Customer.objects.get(pk=customer_id, is_active=True)
                initial["customer"] = customer
            except Customer.DoesNotExist:
                pass

        form = SaleForm(user=request.user, initial=initial)
        formset = SaleLineItemFormSet()

    return render(
        request,
        "sales/form.html",
        {
            "form": form,
            "formset": formset,
            "title": "Nouvelle Vente",
        },
    )


@login_required
def sale_detail(request, pk):
    sale = get_object_or_404(
        Sale.objects.select_related(
            "customer",
            "assigned_trader__userprofile",
        ).prefetch_related(
            "line_items__vehicle__purchase_line_item__purchase__supplier",
            "invoice",
        ),
        pk=pk,
    )

    if hasattr(request.user, "userprofile"):
        if request.user.userprofile.is_trader and sale.assigned_trader != request.user:
            messages.error(request, "Vous ne pouvez voir que vos propres ventes.")
            return redirect("sales:list")

    return render(
        request,
        "sales/detail.html",
        {
            "sale": sale,
            "landed_cost": sale.landed_cost,
            "margin_amount": sale.margin_amount,
            "margin_percentage": sale.margin_percentage,
            "has_invoice": hasattr(sale, "invoice"),
        },
    )


@trader_required
def sale_edit(request, pk):
    sale = get_object_or_404(Sale, pk=pk)

    if hasattr(request.user, "userprofile"):
        if request.user.userprofile.is_trader and sale.assigned_trader != request.user:
            messages.error(request, "Vous ne pouvez modifier que vos propres ventes.")
            return redirect("sales:list")

    if sale.is_finalized:
        messages.error(request, "Impossible de modifier une vente finalisée.")
        return redirect("sales:detail", pk=pk)

    if hasattr(sale, "invoice") and sale.invoice.status != "draft":
        messages.error(request, "Impossible de modifier une vente avec facture émise.")
        return redirect("sales:detail", pk=pk)

    if request.method == "POST":
        form = SaleForm(request.POST, instance=sale, user=request.user)
        formset = SaleLineItemFormSet(request.POST, instance=sale)
        if form.is_valid() and formset.is_valid():
            sale = form.save(commit=False)
            sale.updated_by = request.user
            if sale.assigned_trader and hasattr(sale.assigned_trader, "userprofile"):
                sale.commission_rate = (
                    sale.assigned_trader.userprofile.default_commission_rate
                )
            sale.save()
            items = formset.save(commit=False)
            for item in items:
                if not item.created_by_id:
                    item.created_by = request.user
                item.updated_by = request.user
                item.save()
            for obj in formset.deleted_objects:
                obj.delete()
            sale.recalculate_commission()
            messages.success(request, f"Vente {sale.sale_number} modifiée avec succès.")
            return redirect("sales:detail", pk=pk)
    else:
        form = SaleForm(instance=sale, user=request.user)
        formset = SaleLineItemFormSet(instance=sale)

    return render(
        request,
        "sales/form.html",
        {
            "form": form,
            "formset": formset,
            "sale": sale,
            "title": f"Modifier Vente {sale.sale_number}",
        },
    )


@trader_required
def sale_delete(request, pk):
    sale = get_object_or_404(Sale, pk=pk)

    if hasattr(request.user, "userprofile"):
        if not request.user.userprofile.is_manager:
            messages.error(request, "Seuls les managers peuvent supprimer une vente.")
            return redirect("sales:detail", pk=pk)

    if sale.is_finalized:
        messages.error(request, "Impossible de supprimer une vente finalisée.")
        return redirect("sales:detail", pk=pk)

    if request.method == "POST":
        sale_number = sale.sale_number
        for item in sale.line_items.all():
            item.delete()
        sale.delete()
        messages.success(request, f"Vente {sale_number} supprimée.")
        return redirect("sales:list")

    return redirect("sales:detail", pk=pk)


@trader_required
def sale_create_invoice(request, pk):
    sale = get_object_or_404(Sale, pk=pk)

    if hasattr(request.user, "userprofile"):
        if request.user.userprofile.is_trader and sale.assigned_trader != request.user:
            messages.error(
                request,
                "Vous ne pouvez créer des factures que pour vos propres ventes.",
            )
            return redirect("sales:list")

    if sale.line_items.count() == 0:
        messages.error(request, "Impossible de facturer une vente sans véhicule.")
        return redirect("sales:detail", pk=pk)

    if hasattr(sale, "invoice"):
        messages.warning(request, "Une facture existe déjà pour cette vente.")
        return redirect("sales:invoice_detail", pk=sale.invoice.pk)

    if request.method == "POST":
        form = InvoiceForm(request.POST)
        if form.is_valid():
            invoice = form.save(commit=False)
            invoice.sale = sale
            invoice.customer = sale.customer
            invoice.created_by = request.user
            if sale.down_payment > 0:
                invoice.amount_paid = sale.down_payment
            invoice.save()
            messages.success(
                request,
                f"Facture {invoice.invoice_number} créée. Veuillez maintenant enregistrer le paiement.",
            )
            # ── FLOW: invoice → quick payment ───────────────────────────────
            return redirect("payments:quick_payment", invoice_id=invoice.pk)
    else:
        form = InvoiceForm()

    return render(
        request,
        "sales/invoice_form.html",
        {
            "form": form,
            "sale": sale,
            "title": f"Créer Facture — Vente {sale.sale_number}",
        },
    )


@login_required
def invoice_detail(request, pk):
    invoice = get_object_or_404(
        Invoice.objects.select_related(
            "sale__assigned_trader", "customer"
        ).prefetch_related("sale__line_items__vehicle"),
        pk=pk,
    )

    if hasattr(request.user, "userprofile"):
        if (
            request.user.userprofile.is_trader
            and invoice.sale.assigned_trader != request.user
        ):
            messages.error(request, "Vous ne pouvez voir que vos propres factures.")
            return redirect("sales:list")

    return render(request, "sales/invoice_detail.html", {"invoice": invoice})


@login_required
def invoice_print(request, pk):
    invoice = get_object_or_404(
        Invoice.objects.select_related(
            "sale__assigned_trader",
            "customer",
        ).prefetch_related(
            "sale__line_items__vehicle__purchase_line_item__purchase__supplier"
        ),
        pk=pk,
    )

    if hasattr(request.user, "userprofile"):
        if (
            request.user.userprofile.is_trader
            and invoice.sale.assigned_trader != request.user
        ):
            messages.error(request, "Accès non autorisé.")
            return redirect("sales:list")

    return render(
        request,
        "sales/invoice_print.html",
        {
            "invoice": invoice,
            "config": SystemConfiguration.get_current(),
        },
    )


@trader_required
def sale_finalize(request, pk):
    if request.method == "POST":
        sale = get_object_or_404(Sale, pk=pk)

        if hasattr(request.user, "userprofile"):
            if (
                request.user.userprofile.is_trader
                and sale.assigned_trader != request.user
            ):
                return JsonResponse(
                    {
                        "success": False,
                        "message": "Vous ne pouvez finaliser que vos propres ventes.",
                    }
                )

        if sale.is_finalized:
            return JsonResponse(
                {"success": False, "message": "Cette vente est déjà finalisée."}
            )

        if sale.line_items.count() == 0:
            return JsonResponse(
                {
                    "success": False,
                    "message": "Impossible de finaliser une vente sans véhicule.",
                }
            )

        sale.is_finalized = True
        sale.updated_by = request.user
        sale.save()
        return JsonResponse(
            {"success": True, "message": f"Vente {sale.sale_number} finalisée."}
        )

    return JsonResponse({"success": False, "message": "Méthode non autorisée."})


@login_required
def ajax_vehicle_details(request):
    vehicle_id = request.GET.get("vehicle_id")
    if not vehicle_id:
        return JsonResponse({"error": "Vehicle ID required"})
    try:
        vehicle = Vehicle.objects.select_related(
            "purchase_line_item__purchase__supplier"
        ).get(pk=vehicle_id)
        return JsonResponse(
            {
                "success": True,
                "vehicle": {
                    "vin_chassis": vehicle.vin_chassis,
                    "make": vehicle.make,
                    "model": vehicle.model,
                    "year": vehicle.year,
                    "color": vehicle.color,
                    "landed_cost": float(vehicle.landed_cost),
                    "supplier": (
                        vehicle.vehicle_purchase.supplier.name
                        if vehicle.vehicle_purchase
                        else "—"
                    ),
                },
            }
        )
    except Vehicle.DoesNotExist:
        return JsonResponse({"error": "Vehicle not found"})


@login_required
def ajax_calculate_margin(request):
    if request.method == "POST":
        vehicle_id = request.POST.get("vehicle_id")
        sale_price = request.POST.get("sale_price")
        if not vehicle_id or not sale_price:
            return JsonResponse({"error": "Missing parameters"})
        try:
            vehicle = Vehicle.objects.get(pk=vehicle_id)
            sale_price = float(sale_price)
            landed_cost = float(vehicle.landed_cost)
            margin_amount = sale_price - landed_cost
            margin_pct = (margin_amount / landed_cost * 100) if landed_cost > 0 else 0
            return JsonResponse(
                {
                    "success": True,
                    "landed_cost": landed_cost,
                    "margin_amount": margin_amount,
                    "margin_percentage": round(margin_pct, 2),
                    "is_profitable": margin_amount > 0,
                }
            )
        except (Vehicle.DoesNotExist, ValueError):
            return JsonResponse({"error": "Invalid data"})
    return JsonResponse({"error": "Invalid request"})


@login_required
def ajax_trader_commission(request):
    """Return the default commission rate for a given trader (used by the sale form)."""
    trader_id = request.GET.get("trader_id")
    if not trader_id:
        return JsonResponse({"error": "Trader ID required"}, status=400)
    try:
        from django.contrib.auth.models import User

        trader = User.objects.select_related("userprofile").get(
            pk=trader_id, is_active=True
        )
        rate = (
            float(trader.userprofile.default_commission_rate)
            if hasattr(trader, "userprofile")
            else 0.0
        )
        return JsonResponse({"success": True, "commission_rate": rate})
    except User.DoesNotExist:
        return JsonResponse({"error": "Trader not found"}, status=404)


@trader_required
def quick_sale(request):
    if request.method == "POST":
        form = QuickSaleForm(request.POST)
        if form.is_valid():
            sale = form.save(user=request.user)
            return JsonResponse(
                {
                    "success": True,
                    "sale_id": sale.pk,
                    "sale_number": sale.sale_number,
                    "message": f"Vente {sale.sale_number} créée avec succès.",
                }
            )
        return JsonResponse({"success": False, "errors": form.errors})

    form = QuickSaleForm()
    return render(request, "sales/quick_sale_form.html", {"form": form})
