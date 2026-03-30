from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.utils import timezone
from .models import (
    Purchase,
    PurchaseLineItem,
    FreightCost,
    CustomsDeclaration,
    LineItemFreightCost,
    LineItemCustomsDeclaration,
)
from .forms import (
    PurchaseForm,
    PurchaseLineItemFormSet,
    FreightCostForm,
    CustomsDeclarationForm,
    LineItemFreightCostForm,
    LineItemCustomsDeclarationForm,
    PurchaseSearchForm,
)
from core.decorators import finance_required


@login_required
def purchase_list(request):
    purchases = Purchase.objects.select_related(
        "supplier", "currency", "freight_cost", "customs_declaration"
    ).prefetch_related(
        "line_items__freight_cost",
        "line_items__customs_declaration",
    )
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
            # Guided flow: per-vehicle mode goes to first line item freight
            if purchase.is_per_vehicle_mode:
                first_item = purchase.line_items.order_by("line_number").first()
                if first_item:
                    return redirect(
                        "purchases:line_item_add_freight",
                        purchase_pk=purchase.pk,
                        item_pk=first_item.pk,
                    )
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
        from inventory.models import Vehicle

        # ── Step 1: Delete all vehicles for this purchase in one query.
        # Vehicle.purchase_line_item is on_delete=PROTECT, so vehicles must go first.
        # Using a queryset delete bypasses the reverse-accessor issues that can
        # silently swallow errors when iterating item by item.
        Vehicle.objects.filter(purchase_line_item__purchase=purchase).delete()

        # ── Step 2: Delete per-vehicle freight & customs (in case they don't cascade).
        for item in purchase.line_items.all():
            try:
                item.customs_declaration.delete()
            except Exception:
                pass
            try:
                item.freight_cost.delete()
            except Exception:
                pass

        # ── Step 3: Delete container-level freight & customs.
        try:
            purchase.customs_declaration.delete()
        except Exception:
            pass
        try:
            purchase.freight_cost.delete()
        except Exception:
            pass

        # ── Step 4: Now safe — no more PROTECT references.
        purchase.line_items.all().delete()
        purchase.delete()

        messages.success(request, "Achat supprimé avec succès.")
        return redirect("purchases:list")

    return render(request, "purchases/confirm_delete.html", {"purchase": purchase})


@login_required
def purchase_detail(request, pk):
    purchase = get_object_or_404(
        Purchase.objects.select_related(
            "supplier", "currency", "freight_cost", "customs_declaration"
        ).prefetch_related(
            "line_items__vehicle",
            "line_items__freight_cost",
            "line_items__customs_declaration",
        ),
        pk=pk,
    )
    freight_cost = getattr(purchase, "freight_cost", None)
    customs = getattr(purchase, "customs_declaration", None)

    from decimal import Decimal

    # Aggregate per-vehicle freight and customs totals
    line_items_qs = purchase.line_items.prefetch_related(
        "freight_cost", "customs_declaration"
    ).all()

    total_line_freight_da = sum(
        (
            item.freight_cost.total_freight_cost_da
            for item in line_items_qs
            if hasattr(item, "freight_cost")
        ),
        Decimal("0"),
    )
    total_line_customs_da = sum(
        (
            item.customs_declaration.total_customs_cost_da
            for item in line_items_qs
            if hasattr(item, "customs_declaration")
        ),
        Decimal("0"),
    )

    # In per-vehicle mode use summed line-item costs; otherwise use container costs
    if purchase.is_per_vehicle_mode:
        effective_freight_da = total_line_freight_da
        effective_customs_da = total_line_customs_da
    else:
        effective_freight_da = (
            freight_cost.total_freight_cost_da if freight_cost else Decimal("0")
        )
        effective_customs_da = (
            customs.total_customs_cost_da if customs else Decimal("0")
        )

    landed_cost_components = {
        "total_fob": purchase.total_fob_da,
        "freight_cost": effective_freight_da,
        "customs_cost": effective_customs_da,
    }

    if customs and customs.is_cleared:
        status, status_display, status_class = (
            "cleared",
            "Dédouané — En Stock",
            "success",
        )
    elif customs:
        status, status_display, status_class = "at_customs", "En Douane", "warning"
    elif freight_cost or total_line_freight_da:
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
            "line_items": line_items_qs,
            "freight_cost": freight_cost,
            "customs": customs,
            "landed_cost_components": landed_cost_components,
            "total_landed_cost": sum(landed_cost_components.values()),
            "total_line_freight_da": total_line_freight_da,
            "total_line_customs_da": total_line_customs_da,
            "status": status,
            "status_display": status_display,
            "status_class": status_class,
        },
    )


# ── Container-level freight ────────────────────────────────────────────────────


@finance_required
def purchase_add_freight(request, pk):
    purchase = get_object_or_404(Purchase, pk=pk)

    # Guard: per-vehicle mode should not use container freight form
    if purchase.is_per_vehicle_mode:
        messages.info(
            request,
            "Ce lot est en mode par véhicule. "
            "Veuillez saisir les frais de transport pour chaque véhicule individuellement.",
        )
        first_item = purchase.line_items.order_by("line_number").first()
        if first_item:
            return redirect(
                "purchases:line_item_add_freight",
                purchase_pk=purchase.pk,
                item_pk=first_item.pk,
            )
        return redirect("purchases:detail", pk=pk)

    if hasattr(purchase, "freight_cost"):
        messages.warning(request, "Les frais de transport existent déjà.")
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
                "Ajoutez maintenant la déclaration douanière.",
            )
            return redirect("purchases:add_customs", pk=purchase.pk)
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


# ── Per-vehicle freight ────────────────────────────────────────────────────────


@finance_required
def line_item_add_freight(request, purchase_pk, item_pk):
    purchase = get_object_or_404(Purchase, pk=purchase_pk)
    line_item = get_object_or_404(PurchaseLineItem, pk=item_pk, purchase=purchase)

    # Guard: container mode should not use per-vehicle freight form
    if not purchase.is_per_vehicle_mode:
        messages.info(
            request,
            "Ce lot est en mode conteneur. "
            "Veuillez saisir les frais de transport pour l'ensemble du lot.",
        )
        return redirect("purchases:add_freight", pk=purchase_pk)

    if hasattr(line_item, "freight_cost"):
        messages.warning(
            request, "Les frais de transport existent déjà pour ce véhicule."
        )
        return redirect("purchases:detail", pk=purchase_pk)

    if request.method == "POST":
        form = LineItemFreightCostForm(request.POST)
        if form.is_valid():
            fc = form.save(commit=False)
            fc.line_item = line_item
            fc.created_by = request.user
            fc.save()
            messages.success(
                request,
                f"Frais de transport enregistrés pour "
                f"{line_item.make} {line_item.model} #{line_item.line_number}.",
            )
            return _redirect_after_line_item_freight(purchase, line_item)
    else:
        form = LineItemFreightCostForm()

    return render(
        request,
        "purchases/line_item_freight_form.html",
        {
            "form": form,
            "purchase": purchase,
            "line_item": line_item,
            "all_line_items": purchase.line_items.prefetch_related(
                "freight_cost", "customs_declaration"
            ).all(),
            "title": f"Frais de Transport — {line_item.make} {line_item.model} #{line_item.line_number}",
        },
    )


@finance_required
def line_item_edit_freight(request, purchase_pk, item_pk):
    purchase = get_object_or_404(Purchase, pk=purchase_pk)
    line_item = get_object_or_404(PurchaseLineItem, pk=item_pk, purchase=purchase)
    freight_cost = get_object_or_404(LineItemFreightCost, line_item=line_item)

    if request.method == "POST":
        form = LineItemFreightCostForm(request.POST, instance=freight_cost)
        if form.is_valid():
            fc = form.save(commit=False)
            fc.updated_by = request.user
            fc.save()
            messages.success(
                request,
                f"Frais de transport modifiés pour "
                f"{line_item.make} {line_item.model} #{line_item.line_number}.",
            )
            return redirect("purchases:detail", pk=purchase_pk)
    else:
        form = LineItemFreightCostForm(instance=freight_cost)

    return render(
        request,
        "purchases/line_item_freight_form.html",
        {
            "form": form,
            "purchase": purchase,
            "line_item": line_item,
            "freight_cost": freight_cost,
            "all_line_items": purchase.line_items.prefetch_related(
                "freight_cost", "customs_declaration"
            ).all(),
            "title": f"Modifier Frais de Transport — {line_item.make} {line_item.model} #{line_item.line_number}",
        },
    )


# ── Container-level customs ────────────────────────────────────────────────────


@finance_required
def purchase_add_customs(request, pk):
    purchase = get_object_or_404(Purchase, pk=pk)

    # Guard: per-vehicle mode should not use container customs form
    if purchase.is_per_vehicle_mode:
        messages.info(
            request,
            "Ce lot est en mode par véhicule. "
            "Veuillez saisir la douane pour chaque véhicule individuellement.",
        )
        first_item = purchase.line_items.order_by("line_number").first()
        if first_item:
            return redirect(
                "purchases:line_item_add_customs",
                purchase_pk=purchase.pk,
                item_pk=first_item.pk,
            )
        return redirect("purchases:detail", pk=pk)

    if hasattr(purchase, "customs_declaration"):
        messages.warning(request, "La déclaration douanière existe déjà.")
        return redirect("purchases:detail", pk=pk)

    if request.method == "POST":
        form = CustomsDeclarationForm(request.POST, purchase=purchase)
        if form.is_valid():
            customs = form.save(commit=False)
            customs.purchase = purchase
            customs.created_by = request.user
            customs.save()
            if customs.is_cleared:
                count = 0
                for item in purchase.line_items.all():
                    if hasattr(item, "vehicle"):
                        item.vehicle.status = "available"
                        item.vehicle.save()
                        count += 1
                messages.success(
                    request,
                    f"Déclaration enregistrée et dédouanée — "
                    f"{count} véhicule(s) ajouté(s) au stock.",
                )
            else:
                messages.success(request, "Déclaration douanière enregistrée.")
            return redirect("purchases:detail", pk=purchase.pk)
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
            customs.save()
            messages.success(request, "Déclaration douanière modifiée avec succès.")
            return redirect("purchases:detail", pk=pk)
    else:
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


# ── Per-vehicle customs ────────────────────────────────────────────────────────


@finance_required
def line_item_add_customs(request, purchase_pk, item_pk):
    purchase = get_object_or_404(Purchase, pk=purchase_pk)
    line_item = get_object_or_404(PurchaseLineItem, pk=item_pk, purchase=purchase)

    # Guard: container mode should not use per-vehicle customs form
    if not purchase.is_per_vehicle_mode:
        messages.info(
            request,
            "Ce lot est en mode conteneur. "
            "Veuillez saisir la douane pour l'ensemble du lot.",
        )
        return redirect("purchases:add_customs", pk=purchase_pk)

    if hasattr(line_item, "customs_declaration"):
        messages.warning(
            request, "La déclaration douanière existe déjà pour ce véhicule."
        )
        return redirect("purchases:detail", pk=purchase_pk)

    if request.method == "POST":
        form = LineItemCustomsDeclarationForm(request.POST, line_item=line_item)
        if form.is_valid():
            customs = form.save(commit=False)
            customs.line_item = line_item
            customs.created_by = request.user
            customs.save()
            if customs.is_cleared and hasattr(line_item, "vehicle"):
                line_item.vehicle.status = "available"
                line_item.vehicle.save()
                messages.success(
                    request,
                    f"Déclaration enregistrée — "
                    f"{line_item.make} {line_item.model} #{line_item.line_number} "
                    f"dédouané et ajouté au stock.",
                )
            else:
                messages.success(
                    request,
                    f"Déclaration douanière enregistrée pour "
                    f"{line_item.make} {line_item.model} #{line_item.line_number}.",
                )
            return _redirect_after_line_item_customs(purchase, line_item, request.user)
    else:
        form = LineItemCustomsDeclarationForm(line_item=line_item)

    return render(
        request,
        "purchases/line_item_customs_form.html",
        {
            "form": form,
            "purchase": purchase,
            "line_item": line_item,
            "all_line_items": purchase.line_items.prefetch_related(
                "freight_cost", "customs_declaration"
            ).all(),
            "title": f"Déclaration Douanière — {line_item.make} {line_item.model} #{line_item.line_number}",
        },
    )


@finance_required
def line_item_edit_customs(request, purchase_pk, item_pk):
    purchase = get_object_or_404(Purchase, pk=purchase_pk)
    line_item = get_object_or_404(PurchaseLineItem, pk=item_pk, purchase=purchase)
    customs = get_object_or_404(LineItemCustomsDeclaration, line_item=line_item)

    if request.method == "POST":
        form = LineItemCustomsDeclarationForm(
            request.POST, instance=customs, line_item=line_item
        )
        if form.is_valid():
            customs = form.save(commit=False)
            customs.updated_by = request.user
            customs.save()
            messages.success(
                request,
                f"Déclaration modifiée pour "
                f"{line_item.make} {line_item.model} #{line_item.line_number}.",
            )
            return redirect("purchases:detail", pk=purchase_pk)
    else:
        form = LineItemCustomsDeclarationForm(instance=customs, line_item=line_item)

    return render(
        request,
        "purchases/line_item_customs_form.html",
        {
            "form": form,
            "purchase": purchase,
            "line_item": line_item,
            "customs": customs,
            "all_line_items": purchase.line_items.prefetch_related(
                "freight_cost", "customs_declaration"
            ).all(),
            "title": f"Modifier Déclaration Douanière — {line_item.make} {line_item.model} #{line_item.line_number}",
        },
    )


# ── Shared AJAX + actions ──────────────────────────────────────────────────────


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
    """Mark a container-level customs declaration as cleared."""
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
def line_item_customs_mark_cleared(request, pk):
    """Mark a per-vehicle customs declaration as cleared."""
    if request.method == "POST":
        customs = get_object_or_404(LineItemCustomsDeclaration, pk=pk)
        customs.is_cleared = True
        customs.clearance_date = timezone.now().date()
        customs.updated_by = request.user
        customs.save()

        # Update the linked vehicle status
        line_item = customs.line_item
        msg = f"Véhicule {line_item.make} {line_item.model} #{line_item.line_number} dédouané."
        if hasattr(line_item, "vehicle"):
            line_item.vehicle.status = "available"
            line_item.vehicle.save()
            msg += " Ajouté au stock."

        return JsonResponse(
            {
                "success": True,
                "message": msg,
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
    elif hasattr(item, "customs_declaration") and item.customs_declaration.is_cleared:
        status = "available"
    elif hasattr(purchase, "customs_declaration") or hasattr(purchase, "freight_cost"):
        status = "at_customs"
    elif hasattr(item, "customs_declaration") or hasattr(item, "freight_cost"):
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


def _redirect_after_line_item_freight(purchase, current_item):
    """
    After saving per-vehicle freight, redirect to:
    1. Next vehicle in the container that still needs freight, or
    2. First vehicle needing customs (if all freight done), or
    3. Purchase detail.
    """
    items_without_freight = (
        purchase.line_items.filter(freight_cost__isnull=True)
        .exclude(pk=current_item.pk)
        .order_by("line_number")
    )
    next_item = items_without_freight.first()
    if next_item:
        return redirect(
            "purchases:line_item_add_freight",
            purchase_pk=purchase.pk,
            item_pk=next_item.pk,
        )
    # All freight done — move to customs for the first vehicle
    items_without_customs = purchase.line_items.filter(
        customs_declaration__isnull=True
    ).order_by("line_number")
    first_customs = items_without_customs.first()
    if first_customs:
        return redirect(
            "purchases:line_item_add_customs",
            purchase_pk=purchase.pk,
            item_pk=first_customs.pk,
        )
    return redirect("purchases:detail", pk=purchase.pk)


def _redirect_after_line_item_customs(purchase, current_item, user):
    """
    After saving per-vehicle customs, redirect to:
    1. Next vehicle needing customs, or
    2. First vehicle's detail page (if all complete), or
    3. Purchase detail.
    """
    items_without_customs = (
        purchase.line_items.filter(customs_declaration__isnull=True)
        .exclude(pk=current_item.pk)
        .order_by("line_number")
    )
    next_item = items_without_customs.first()
    if next_item:
        return redirect(
            "purchases:line_item_add_customs",
            purchase_pk=purchase.pk,
            item_pk=next_item.pk,
        )
    # All complete — navigate to first vehicle detail
    first_vehicle = _get_first_vehicle(purchase)
    if first_vehicle:
        return redirect("inventory:detail", pk=first_vehicle.pk)
    return redirect("purchases:detail", pk=purchase.pk)
