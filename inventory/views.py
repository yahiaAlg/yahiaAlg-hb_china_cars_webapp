from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Count, Sum, Avg
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.utils import timezone
from .models import Vehicle, VehiclePhoto, StockAlert
from .forms import VehicleForm, VehicleSearchForm, VehiclePhotoForm, ReservationForm
from core.decorators import finance_required, trader_required


@login_required
def vehicle_list(request):
    vehicles = Vehicle.objects.select_related(
        "purchase_line_item__purchase__supplier", "reserved_by"
    ).prefetch_related("photos")

    search_form = VehicleSearchForm(request.GET)
    if search_form.is_valid():
        search = search_form.cleaned_data.get("search")
        if search:
            vehicles = vehicles.filter(
                Q(vin_chassis__icontains=search)
                | Q(make__icontains=search)
                | Q(model__icontains=search)
                | Q(color__icontains=search)
            )
        status = search_form.cleaned_data.get("status")
        if status:
            vehicles = vehicles.filter(status=status)
        make = search_form.cleaned_data.get("make")
        if make:
            vehicles = vehicles.filter(make__icontains=make)
        year_from = search_form.cleaned_data.get("year_from")
        if year_from:
            vehicles = vehicles.filter(year__gte=year_from)
        year_to = search_form.cleaned_data.get("year_to")
        if year_to:
            vehicles = vehicles.filter(year__lte=year_to)
        trader = search_form.cleaned_data.get("trader")
        if trader:
            vehicles = vehicles.filter(reserved_by=trader)

    if hasattr(request.user, "userprofile") and request.user.userprofile.is_trader:
        vehicles = vehicles.filter(Q(status="available") | Q(reserved_by=request.user))

    expired_reservations = vehicles.filter(
        status="reserved", reservation_expires__lt=timezone.now()
    )
    for vehicle in expired_reservations:
        vehicle.release_reservation()
        StockAlert.objects.create(
            alert_type="reservation_expired",
            vehicle=vehicle,
            message=f"Réservation expirée pour {vehicle}",
            created_by=request.user,
        )

    stats = {
        "total": vehicles.count(),
        "available": vehicles.filter(status="available").count(),
        "reserved": vehicles.filter(status="reserved").count(),
        "sold": vehicles.filter(status="sold").count(),
        "in_transit": vehicles.filter(status="in_transit").count(),
        "at_customs": vehicles.filter(status="at_customs").count(),
    }

    paginator = Paginator(vehicles, 20)
    return render(
        request,
        "inventory/list.html",
        {
            "page_obj": paginator.get_page(request.GET.get("page")),
            "search_form": search_form,
            "stats": stats,
            "total_count": vehicles.count(),
        },
    )


@login_required
def vehicle_detail(request, pk):
    vehicle = get_object_or_404(
        Vehicle.objects.select_related(
            "purchase_line_item__purchase__supplier",
            "purchase_line_item__purchase__currency",
            "purchase_line_item__purchase__freight_cost",
            "purchase_line_item__purchase__customs_declaration",
            "reserved_by",
        ).prefetch_related("photos"),
        pk=pk,
    )

    purchase = vehicle.vehicle_purchase
    cost_breakdown = {
        "purchase_price": purchase.purchase_price_da or 0,
        "freight_cost": 0,
        "customs_cost": 0,
    }
    if hasattr(purchase, "freight_cost"):
        cost_breakdown["freight_cost"] = (
            purchase.freight_cost.total_freight_cost_da or 0
        )
    if hasattr(purchase, "customs_declaration"):
        cost_breakdown["customs_cost"] = (
            purchase.customs_declaration.total_customs_cost_da or 0
        )
    total_landed_cost = sum(cost_breakdown.values())

    can_reserve = (
        hasattr(request.user, "userprofile")
        and (request.user.userprofile.is_trader or request.user.userprofile.is_manager)
        and vehicle.status == "available"
    )
    can_release = vehicle.status == "reserved" and vehicle.reserved_by == request.user

    sibling_vehicles = []
    prev_vehicle = None
    next_vehicle = None

    if vehicle.purchase_line_item_id:
        siblings_qs = (
            Vehicle.objects.filter(purchase_line_item__purchase=purchase)
            .select_related("purchase_line_item")
            .order_by("purchase_line_item__line_number")
        )
        sibling_list = list(siblings_qs)
        sibling_vehicles = sibling_list

        for idx, sib in enumerate(sibling_list):
            if sib.pk == vehicle.pk:
                if idx > 0:
                    prev_vehicle = sibling_list[idx - 1]
                if idx < len(sibling_list) - 1:
                    next_vehicle = sibling_list[idx + 1]
                break

    # Status choices available for manual override (sold excluded — can't undo a sale)
    STATUS_CHOICES = [
        ("in_transit", "En Transit"),
        ("at_customs", "En Douane"),
        ("available", "Disponible"),
        ("reserved", "Réservé"),
    ]

    return render(
        request,
        "inventory/detail.html",
        {
            "vehicle": vehicle,
            "cost_breakdown": cost_breakdown,
            "total_landed_cost": total_landed_cost,
            "can_reserve": can_reserve,
            "can_release": can_release,
            "reservation_form": ReservationForm(),
            "sibling_vehicles": sibling_vehicles,
            "prev_vehicle": prev_vehicle,
            "next_vehicle": next_vehicle,
            "purchase": purchase,
            "status_choices": STATUS_CHOICES,
        },
    )


@finance_required
def vehicle_create(request):
    if request.method == "POST":
        form = VehicleForm(request.POST)
        if form.is_valid():
            vehicle = form.save(commit=False)
            vehicle.created_by = request.user
            purchase = vehicle.vehicle_purchase
            if (
                hasattr(purchase, "customs_declaration")
                and purchase.customs_declaration.is_cleared
            ):
                vehicle.status = "available"
            elif hasattr(purchase, "customs_declaration") or hasattr(
                purchase, "freight_cost"
            ):
                vehicle.status = "at_customs"
            else:
                vehicle.status = "in_transit"
            vehicle.save()
            messages.success(request, f"Véhicule {vehicle} enregistré avec succès.")
            return redirect("inventory:detail", pk=vehicle.pk)
    else:
        form = VehicleForm()

    return render(
        request, "inventory/form.html", {"form": form, "title": "Nouveau Véhicule"}
    )


@finance_required
def vehicle_edit(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk)
    if vehicle.status == "sold":
        messages.error(request, "Impossible de modifier un véhicule vendu.")
        return redirect("inventory:detail", pk=pk)

    if request.method == "POST":
        form = VehicleForm(request.POST, instance=vehicle)
        if form.is_valid():
            vehicle = form.save(commit=False)
            vehicle.updated_by = request.user
            vehicle.save()
            messages.success(request, f"Véhicule {vehicle} modifié avec succès.")
            return redirect("inventory:detail", pk=pk)
    else:
        form = VehicleForm(instance=vehicle)

    return render(
        request,
        "inventory/form.html",
        {
            "form": form,
            "vehicle": vehicle,
            "title": f"Modifier {vehicle}",
        },
    )


@finance_required
def vehicle_change_status(request, pk):
    """AJAX: manually override a vehicle's status. Finance/manager only.
    Sold status cannot be set here — that is handled by the sale workflow.
    """
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Méthode non autorisée."})

    vehicle = get_object_or_404(Vehicle, pk=pk)

    if vehicle.status == "sold":
        return JsonResponse(
            {
                "success": False,
                "message": "Impossible de modifier le statut d'un véhicule vendu.",
            }
        )

    ALLOWED = ["in_transit", "at_customs", "available", "reserved"]
    new_status = request.POST.get("status", "").strip()

    if new_status not in ALLOWED:
        return JsonResponse(
            {
                "success": False,
                "message": f"Statut invalide. Valeurs acceptées : {', '.join(ALLOWED)}",
            }
        )

    old_label = vehicle.get_status_display()
    vehicle.status = new_status
    vehicle.updated_by = request.user

    # If demoting from reserved, clear reservation metadata so it doesn't linger
    if new_status != "reserved" and vehicle.reserved_by:
        vehicle.reserved_by = None
        vehicle.reservation_date = None
        vehicle.reservation_expires = None

    vehicle.save()

    return JsonResponse(
        {
            "success": True,
            "message": f"Statut mis à jour : {old_label} → {vehicle.get_status_display()}",
            "new_status": new_status,
            "new_status_display": vehicle.get_status_display(),
        }
    )


@trader_required
def vehicle_reserve(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk)
    if vehicle.status != "available":
        return JsonResponse(
            {
                "success": False,
                "message": "Ce véhicule n'est pas disponible pour réservation.",
            }
        )

    if request.method == "POST":
        form = ReservationForm(request.POST)
        if form.is_valid():
            duration_days = int(form.cleaned_data["duration_days"])
            try:
                vehicle.reserve_for_trader(request.user, duration_days)
                return JsonResponse(
                    {
                        "success": True,
                        "message": f"Véhicule réservé pour {duration_days} jours.",
                        "expires": vehicle.reservation_expires.strftime(
                            "%d/%m/%Y %H:%M"
                        ),
                    }
                )
            except ValueError as e:
                return JsonResponse({"success": False, "message": str(e)})

    return JsonResponse(
        {"success": False, "message": "Données de formulaire invalides."}
    )


@trader_required
def vehicle_release_reservation(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk)
    if vehicle.reserved_by != request.user and not request.user.userprofile.is_manager:
        return JsonResponse(
            {
                "success": False,
                "message": "Vous ne pouvez pas annuler cette réservation.",
            }
        )

    if request.method == "POST":
        vehicle.release_reservation()
        return JsonResponse(
            {
                "success": True,
                "message": "Réservation annulée. Le véhicule est maintenant disponible.",
            }
        )

    return JsonResponse({"success": False, "message": "Méthode non autorisée."})


@login_required
def vehicle_add_photo(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk)
    if request.method == "POST":
        form = VehiclePhotoForm(request.POST, request.FILES)
        if form.is_valid():
            photo = form.save(commit=False)
            photo.vehicle = vehicle
            photo.created_by = request.user
            photo.save()
            messages.success(request, "Photo ajoutée avec succès.")
            return redirect("inventory:detail", pk=pk)
    else:
        form = VehiclePhotoForm()

    return render(
        request,
        "inventory/photo_form.html",
        {
            "form": form,
            "vehicle": vehicle,
            "title": f"Ajouter Photo - {vehicle}",
        },
    )


@login_required
def stock_alerts(request):
    alerts = StockAlert.objects.filter(is_resolved=False).select_related(
        "vehicle", "created_by"
    )
    generate_automatic_alerts()
    return render(
        request,
        "inventory/alerts.html",
        {
            "alerts": alerts,
            "alert_count": alerts.count(),
        },
    )


@login_required
def resolve_alert(request, pk):
    if request.method == "POST":
        alert = get_object_or_404(StockAlert, pk=pk)
        alert.resolve(request.user)
        return JsonResponse({"success": True, "message": "Alerte résolue."})
    return JsonResponse({"success": False, "message": "Méthode non autorisée."})


def generate_automatic_alerts():
    slow_vehicles = Vehicle.objects.filter(status="available")
    for vehicle in slow_vehicles:
        if (
            vehicle.is_slow_moving
            and not StockAlert.objects.filter(
                alert_type="slow_moving", vehicle=vehicle, is_resolved=False
            ).exists()
        ):
            StockAlert.objects.create(
                alert_type="slow_moving",
                vehicle=vehicle,
                message=f"Véhicule {vehicle} en stock depuis {vehicle.days_in_stock} jours",
            )

    from datetime import timedelta

    customs_threshold = timezone.now().date() - timedelta(days=30)
    delayed_customs = Vehicle.objects.filter(
        status="at_customs",
        purchase_line_item__purchase__customs_declaration__declaration_date__lt=customs_threshold,
        purchase_line_item__purchase__customs_declaration__is_cleared=False,
    )
    for vehicle in delayed_customs:
        if not StockAlert.objects.filter(
            alert_type="customs_delayed", vehicle=vehicle, is_resolved=False
        ).exists():
            StockAlert.objects.create(
                alert_type="customs_delayed",
                vehicle=vehicle,
                message=f"Retard en douane pour {vehicle} - plus de 30 jours",
            )
