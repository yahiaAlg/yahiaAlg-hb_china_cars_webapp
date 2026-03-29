from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Count, Sum
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.urls import reverse
from .models import Supplier
from .forms import SupplierForm, SupplierSearchForm
from core.decorators import finance_required


@login_required
def supplier_list(request):
    suppliers = Supplier.objects.all().select_related("currency")
    search_form = SupplierSearchForm(request.GET)

    if search_form.is_valid():
        search = search_form.cleaned_data.get("search")
        if search:
            suppliers = suppliers.filter(
                Q(name__icontains=search)
                | Q(contact_person__icontains=search)
                | Q(email__icontains=search)
                | Q(phone__icontains=search)
            )
        country = search_form.cleaned_data.get("country")
        if country:
            suppliers = suppliers.filter(country__icontains=country)
        currency = search_form.cleaned_data.get("currency")
        if currency:
            suppliers = suppliers.filter(currency=currency)
        is_active = search_form.cleaned_data.get("is_active")
        if is_active == "true":
            suppliers = suppliers.filter(is_active=True)
        elif is_active == "false":
            suppliers = suppliers.filter(is_active=False)

    suppliers = suppliers.annotate(purchase_count=Count("purchase"))
    paginator = Paginator(suppliers, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "suppliers/list.html",
        {
            "page_obj": page_obj,
            "search_form": search_form,
            "total_count": suppliers.count(),
        },
    )


@finance_required
def supplier_create(request):
    """Create new supplier.
    On success → redirects to purchase creation with this supplier pre-selected
    (guided onboarding flow: supplier → purchase → freight → customs → stock).
    """
    if request.method == "POST":
        form = SupplierForm(request.POST)
        if form.is_valid():
            supplier = form.save(commit=False)
            supplier.created_by = request.user
            supplier.save()
            messages.success(
                request,
                f"Fournisseur « {supplier.name} » créé. "
                f"Enregistrez maintenant le premier achat.",
            )
            # ── Guided flow step 2: purchase form with supplier pre-filled ──
            return redirect(reverse("purchases:create") + f"?supplier={supplier.pk}")
    else:
        form = SupplierForm()

    return render(
        request,
        "suppliers/form.html",
        {
            "form": form,
            "title": "Nouveau Fournisseur",
        },
    )


@login_required
def supplier_detail(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    purchases = supplier.purchase_set.all().select_related("currency")
    total_purchases = purchases.count()
    total_value = sum(p.purchase_price_da for p in purchases if p.purchase_price_da)
    avg_value = total_value / total_purchases if total_purchases > 0 else 0

    return render(
        request,
        "suppliers/detail.html",
        {
            "supplier": supplier,
            "total_purchases": total_purchases,
            "total_value": total_value,
            "avg_value": avg_value,
            "recent_purchases": purchases.order_by("-purchase_date")[:5],
        },
    )


@finance_required
def supplier_edit(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    if request.method == "POST":
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            supplier = form.save(commit=False)
            supplier.updated_by = request.user
            supplier.save()
            messages.success(request, f"Fournisseur « {supplier.name} » modifié.")
            return redirect("suppliers:detail", pk=supplier.pk)
    else:
        form = SupplierForm(instance=supplier)

    return render(
        request,
        "suppliers/form.html",
        {
            "form": form,
            "supplier": supplier,
            "title": f"Modifier {supplier.name}",
        },
    )


@finance_required
def supplier_toggle_status(request, pk):
    if request.method == "POST":
        supplier = get_object_or_404(Supplier, pk=pk)
        if supplier.is_active and supplier.has_purchases:
            return JsonResponse(
                {
                    "success": False,
                    "message": "Impossible de désactiver un fournisseur avec des achats existants.",
                }
            )
        supplier.is_active = not supplier.is_active
        supplier.updated_by = request.user
        supplier.save()
        status_text = "activé" if supplier.is_active else "désactivé"
        return JsonResponse(
            {
                "success": True,
                "message": f"Fournisseur {status_text} avec succès.",
                "is_active": supplier.is_active,
            }
        )
    return JsonResponse({"success": False, "message": "Méthode non autorisée."})


@login_required
def supplier_ajax_search(request):
    term = request.GET.get("term", "")
    suppliers = Supplier.objects.filter(is_active=True, name__icontains=term)[:10]
    return JsonResponse(
        {
            "results": [
                {"id": s.id, "text": s.name, "currency": s.currency.code}
                for s in suppliers
            ]
        }
    )
