from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.utils import timezone
from .models import Purchase, PurchaseLineItem, FreightCost, CustomsDeclaration
from .forms import (
    PurchaseForm,
    PurchaseLineItemFormSet,
    FreightCostForm,
    CustomsDeclarationForm,
    PurchaseSearchForm,
)
from core.decorators import finance_required


@login_required
def purchase_list(request):
    purchases = Purchase.objects.select_related(
        "supplier", "currency", "customs_declaration"
    ).prefetch_related("line_items")
    search_form = PurchaseSearchForm(request.GET)
    if search_form.is_valid():
        s = search_form.cleaned_data.get("search")
        if s:
            purchases = purchases.filter(
                Q(supplier__name__icontains=s)
                | Q(customs_declaration__declaration_number__icontains=s)
                | Q(notes__icontains=s)
            )
        if search_form.cleaned_data.get("supplier"):
            purchases = purchases.filter(supplier=search_form.cleaned_data["supplier"])
        if search_form.cleaned_data.get("date_from"):
            purchases = purchases.filter(
                purchase_date__gte=search_form.cleaned_data["date_from"]
            )
        if search_form.cleaned_data.get("date_to"):
            purchases = purchases.filter(
                purchase_date__lte=search_form.cleaned_data["date_to"]
            )
        cs = search_form.cleaned_data.get("customs_status")
        if cs == "pending":
            purchases = purchases.filter(
                Q(customs_declaration__isnull=True)
                | Q(customs_declaration__is_cleared=False)
            )
        elif cs == "cleared":
            purchases = purchases.filter(customs_declaration__is_cleared=True)

    paginator = Paginator(purchases, 20)
    return render(
        request,
        "purchases/list.html",
        {
            "page_obj": paginator.get_page(request.GET.get("page")),
            "search_form": search_form,
            "total_count": purchases.count(),
        },
    )


@finance_required
def purchase_create(request):
    """Create a new container shipment.

    Guided flow entry point: accepts ?supplier=<pk> from the supplier creation
    step and pre-selects that supplier in the form.

    On success → redirects to freight cost entry (step 3 of guided flow).
    """
    # ── Pre-fill supplier from guided flow ──────────────────────────────────
    initial = {}
    preselected_supplier_pk = request.GET.get("supplier")
    if preselected_supplier_pk:
        initial["supplier"] = preselected_supplier_pk

    if request.method == "POST":
        form = PurchaseForm(request.POST)
        formset = PurchaseLineItemFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            purchase = form.save(commit=False)
            purchase.created_by = request.user
            purchase.save()

            formset.instance = purchase
            items = formset.save(commit=False)
            for idx, item in enumerate(items, 1):
                item.purchase = purchase
                item.line_number = idx
                item.created_by = request.user
                item.save()
            for obj in formset.deleted_objects:
                obj.delete()

            _create_vehicles_from_purchase(purchase, request.user)
            n = purchase.line_items.count()
            messages.success(
                request,
                f"Achat enregistré — {n} véhicule{'s' if n != 1 else ''} "
                f"ajouté{'s' if n != 1 else ''} en transit. "
                f"Ajoutez maintenant les frais de transport.",
            )
            # ── Guided flow step 3: freight form ──
            return redirect("purchases:add_freight", pk=purchase.pk)
    else:
        form = PurchaseForm(initial=initial)
        formset = PurchaseLineItemFormSet()

    return render(
        request,
        "purchases/form.html",
        {
            "form": form,
            "formset": formset,
            "title": "Nouvel Achat de Véhicule",
            # Pass supplier pk so template can keep it in a hidden field / back-link
            "preselected_supplier_pk": preselected_supplier_pk,
        },
    )


@finance_required
def purchase_edit(request, pk):
    purchase = get_object_or_404(Purchase, pk=pk)
    if request.method == "POST":
        form = PurchaseForm(request.POST, instance=purchase)
        formset = PurchaseLineItemFormSet(request.POST, instance=purchase)
        if form.is_valid() and formset.is_valid():
            purchase = form.save(commit=False)
            purchase.updated_by = request.user
            purchase.save()

            existing_nums = list(
                purchase.line_items.values_list("line_number", flat=True)
            )
            next_num = (max(existing_nums) + 1) if existing_nums else 1
            items = formset.save(commit=False)
            for item in items:
                if not item.line_number:
                    item.line_number = next_num
                    next_num += 1
                item.purchase = purchase
                item.updated_by = request.user if item.pk else None
                if not item.pk:
                    item.created_by = request.user
                item.save()
                if not hasattr(item, "vehicle"):
                    _create_vehicle_from_line_item(item, request.user)
            for obj in formset.deleted_objects:
                obj.delete()
            for item in purchase.line_items.all():
                item.save()

            messages.success(request, "Achat modifié avec succès.")
            return redirect("purchases:detail", pk=purchase.pk)
    else:
        form = PurchaseForm(instance=purchase)
        formset = PurchaseLineItemFormSet(instance=purchase)

    return render(
        request,
        "purchases/form.html",
        {
            "form": form,
            "formset": formset,
            "purchase": purchase,
            "title": f"Modifier Achat — {purchase}",
        },
    )


@finance_required
def purchase_delete(request, pk):
    purchase = get_object_or_404(Purchase, pk=pk)
    if request.method == "POST":
        purchase.delete()
        messages.success(request, "Achat supprimé avec succès.")
        return redirect("purchases:list")
    return render(request, "purchases/confirm_delete.html", {"purchase": purchase})


@login_required
def purchase_detail(request, pk):
    purchase = get_object_or_404(
        Purchase.objects.select_related(
            "supplier", "currency", "freight_cost", "customs_declaration"
        ).prefetch_related("line_items__vehicle"),
        pk=pk,
    )
    freight_cost = getattr(purchase, "freight_cost", None)
    customs = getattr(purchase, "customs_declaration", None)
    landed_cost_components = {
        "total_fob": purchase.total_fob_da,
        "freight_cost": freight_cost.total_freight_cost_da if freight_cost else 0,
        "customs_cost": customs.total_customs_cost_da if customs else 0,
    }
    if customs and customs.is_cleared:
        status, status_display, status_class = (
            "cleared",
            "Dédouané — En Stock",
            "success",
        )
    elif customs:
        status, status_display, status_class = "at_customs", "En Douane", "warning"
    elif freight_cost:
        status, status_display, status_class = (
            "at_customs",
            "Transport enregistré — Attente Douane",
            "info",
        )
    else:
        status, status_display, status_class = "in_transit", "En Transit", "secondary"

    return render(
        request,
        "purchases/detail.html",
        {
            "purchase": purchase,
            "line_items": purchase.line_items.all(),
            "freight_cost": freight_cost,
            "customs": customs,
            "landed_cost_components": landed_cost_components,
            "total_landed_cost": sum(landed_cost_components.values()),
            "status": status,
            "status_display": status_display,
            "status_class": status_class,
        },
    )


@finance_required
def purchase_add_freight(request, pk):
    """Add freight costs.  On success → customs entry (guided flow step 4)."""
    purchase = get_object_or_404(Purchase, pk=pk)
    if hasattr(purchase, "freight_cost"):
        messages.warning(request, "Les frais de transport sont déjà enregistrés.")
        return redirect("purchases:detail", pk=pk)

    if request.method == "POST":
        form = FreightCostForm(request.POST)
        if form.is_valid():
            fc = form.save(commit=False)
            fc.purchase = purchase
            fc.created_by = request.user
            fc.save()
            messages.success(
                request,
                "Frais de transport enregistrés. "
                "Saisissez maintenant la déclaration en douane.",
            )
            # ── Guided flow step 4: customs form ──
            return redirect("purchases:add_customs", pk=pk)
    else:
        form = FreightCostForm()

    return render(
        request,
        "purchases/freight_form.html",
        {
            "form": form,
            "purchase": purchase,
            "title": f"Frais de Transport — {purchase}",
        },
    )


@finance_required
def purchase_edit_freight(request, pk):
    purchase = get_object_or_404(Purchase, pk=pk)
    freight_cost = get_object_or_404(FreightCost, purchase=purchase)
    if request.method == "POST":
        form = FreightCostForm(request.POST, instance=freight_cost)
        if form.is_valid():
            fc = form.save(commit=False)
            fc.updated_by = request.user
            fc.save()
            messages.success(request, "Frais de transport modifiés avec succès.")
            return redirect("purchases:detail", pk=pk)
    else:
        form = FreightCostForm(instance=freight_cost)

    return render(
        request,
        "purchases/freight_form.html",
        {
            "form": form,
            "purchase": purchase,
            "freight_cost": freight_cost,
            "title": f"Modifier Frais de Transport — {purchase}",
        },
    )


@finance_required
def purchase_add_customs(request, pk):
    """Add customs declaration.
    On success → first vehicle's detail page (guided flow step 5).
    """
    purchase = get_object_or_404(Purchase, pk=pk)
    if hasattr(purchase, "customs_declaration"):
        messages.warning(request, "La déclaration douanière existe déjà.")
        return redirect("purchases:detail", pk=pk)
    if not hasattr(purchase, "freight_cost"):
        messages.error(request, "Veuillez d'abord enregistrer les frais de transport.")
        return redirect("purchases:add_freight", pk=pk)

    if request.method == "POST":
        form = CustomsDeclarationForm(request.POST, purchase=purchase)
        if form.is_valid():
            customs = form.save(commit=False)
            customs.purchase = purchase
            customs.created_by = request.user
            customs.cif_value_da = customs.calculate_cif_value()
            customs.save()
            messages.success(
                request,
                "Déclaration douanière enregistrée. "
                "Vérifiez les détails de chaque véhicule ci-dessous.",
            )
            # ── Guided flow step 5: first vehicle's detail page ──
            first_vehicle = _get_first_vehicle(purchase)
            if first_vehicle:
                return redirect("inventory:detail", pk=first_vehicle.pk)
            return redirect("purchases:detail", pk=pk)
    else:
        form = CustomsDeclarationForm(purchase=purchase)

    return render(
        request,
        "purchases/customs_form.html",
        {
            "form": form,
            "purchase": purchase,
            "title": f"Déclaration Douanière — {purchase}",
        },
    )


@finance_required
def purchase_edit_customs(request, pk):
    purchase = get_object_or_404(Purchase, pk=pk)
    customs = get_object_or_404(CustomsDeclaration, purchase=purchase)
    if request.method == "POST":
        form = CustomsDeclarationForm(request.POST, instance=customs, purchase=purchase)
        if form.is_valid():
            customs = form.save(commit=False)
            customs.updated_by = request.user
            customs.cif_value_da = customs.calculate_cif_value()
            customs.save()
            messages.success(request, "Déclaration douanière modifiée avec succès.")
            return redirect("purchases:detail", pk=pk)
    else:
        customs.cif_value_da = customs.calculate_cif_value()
        form = CustomsDeclarationForm(instance=customs, purchase=purchase)

    return render(
        request,
        "purchases/customs_form.html",
        {
            "form": form,
            "purchase": purchase,
            "customs": customs,
            "title": f"Modifier Déclaration Douanière — {purchase}",
        },
    )


@login_required
def ajax_calculate_customs(request):
    if request.method == "POST":
        cif = float(request.POST.get("cif_value", 0))
        tariff = float(request.POST.get("tariff_rate", 0))
        tva_r = float(request.POST.get("tva_rate", 0))
        other = float(request.POST.get("other_fees", 0))
        duty = cif * (tariff / 100)
        tva = (cif + duty) * (tva_r / 100)
        return JsonResponse(
            {
                "import_duty": round(duty, 2),
                "tva_amount": round(tva, 2),
                "total_customs_cost": round(duty + tva + other, 2),
            }
        )
    return JsonResponse({"error": "Invalid request"})


@finance_required
def customs_mark_cleared(request, pk):
    if request.method == "POST":
        customs = get_object_or_404(CustomsDeclaration, pk=pk)
        customs.is_cleared = True
        customs.clearance_date = timezone.now().date()
        customs.updated_by = request.user
        customs.save()
        count = 0
        for item in customs.purchase.line_items.all():
            if hasattr(item, "vehicle"):
                item.vehicle.status = "available"
                item.vehicle.save()
                count += 1
        return JsonResponse(
            {
                "success": True,
                "message": f"{count} véhicule(s) dédouané(s) et ajouté(s) au stock.",
                "clearance_date": customs.clearance_date.strftime("%d/%m/%Y"),
            }
        )
    return JsonResponse({"success": False, "message": "Méthode non autorisée."})


@finance_required
def purchase_mark_arrived(request, pk):
    """Mark all in-transit vehicles in this container as arrived (→ at_customs)."""
    purchase = get_object_or_404(Purchase, pk=pk)
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Méthode non autorisée."})

    from inventory.models import Vehicle

    updated = 0
    for item in purchase.line_items.all():
        if hasattr(item, "vehicle") and item.vehicle.status == "in_transit":
            item.vehicle.status = "at_customs"
            item.vehicle.updated_by = request.user
            item.vehicle.save()
            updated += 1

    if updated == 0:
        return JsonResponse(
            {
                "success": False,
                "message": "Aucun véhicule en transit dans ce lot.",
            }
        )

    return JsonResponse(
        {
            "success": True,
            "message": f"{updated} véhicule(s) marqué(s) comme arrivé(s) — statut : En Douane.",
            "updated": updated,
        }
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_first_vehicle(purchase):
    """Return the Vehicle linked to the first PurchaseLineItem of a purchase."""
    first_item = purchase.line_items.order_by("line_number").first()
    if first_item and hasattr(first_item, "vehicle"):
        return first_item.vehicle
    return None


def _create_vehicle_from_line_item(item, user):
    from inventory.models import Vehicle

    purchase = item.purchase
    if (
        hasattr(purchase, "customs_declaration")
        and purchase.customs_declaration.is_cleared
    ):
        status = "available"
    elif hasattr(purchase, "customs_declaration") or hasattr(purchase, "freight_cost"):
        status = "at_customs"
    else:
        status = "in_transit"
    vin = item.vin_chassis or f"TBD-{purchase.pk}-{item.line_number}"
    Vehicle.objects.create(
        purchase_line_item=item,
        vin_chassis=vin,
        make=item.make,
        model=item.model,
        year=item.year,
        color=item.color,
        engine_type=item.engine_type or "",
        status=status,
        created_by=user,
    )


def _create_vehicles_from_purchase(purchase, user):
    for item in purchase.line_items.all():
        if not hasattr(item, "vehicle"):
            _create_vehicle_from_line_item(item, user)
