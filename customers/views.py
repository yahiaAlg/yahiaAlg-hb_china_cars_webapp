from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum, Count, Max, Subquery, DecimalField, OuterRef
from django.db.models.functions import Coalesce
from django.core.paginator import Paginator
from django.http import JsonResponse
from .models import Customer, CustomerNote
from .forms import CustomerForm, CustomerSearchForm, CustomerNoteForm, QuickCustomerForm
from core.decorators import trader_required


def _purchases_total_subquery():
    from sales.models import SaleLineItem

    return (
        SaleLineItem.objects.filter(sale__customer=OuterRef("pk"))
        .values("sale__customer")
        .annotate(total=Sum("sale_price"))
        .values("total")
    )


@login_required
def customer_list(request):
    customers = Customer.objects.all()
    search_form = CustomerSearchForm(request.GET)

    if search_form.is_valid():
        search = search_form.cleaned_data.get("search")
        if search:
            customers = customers.filter(
                Q(name__icontains=search)
                | Q(phone__icontains=search)
                | Q(email__icontains=search)
                | Q(nif_tax_id__icontains=search)
            )
        customer_type = search_form.cleaned_data.get("customer_type")
        if customer_type:
            customers = customers.filter(customer_type=customer_type)
        wilaya = search_form.cleaned_data.get("wilaya")
        if wilaya:
            customers = customers.filter(wilaya=wilaya)
        is_active = search_form.cleaned_data.get("is_active")
        if is_active == "true":
            customers = customers.filter(is_active=True)
        elif is_active == "false":
            customers = customers.filter(is_active=False)
        has_outstanding = search_form.cleaned_data.get("has_outstanding")
        if has_outstanding:
            customers = customers.filter(invoice__balance_due__gt=0).distinct()

    customers = customers.annotate(
        sales_count=Count("sale", distinct=True),
        last_sale_date=Max("sale__sale_date"),
        purchases_total=Coalesce(
            Subquery(_purchases_total_subquery(), output_field=DecimalField()),
            0,
            output_field=DecimalField(),
        ),
    )

    paginator = Paginator(customers, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "customers/list.html",
        {
            "page_obj": page_obj,
            "search_form": search_form,
            "total_count": customers.count(),
        },
    )


@trader_required
def customer_create(request):
    if request.method == "POST":
        form = CustomerForm(request.POST, request.FILES)
        if form.is_valid():
            customer = form.save(commit=False)
            customer.created_by = request.user
            customer.save()
            messages.success(
                request,
                f"Client '{customer.name}' créé avec succès. Créez maintenant sa première vente.",
            )
            # ── FLOW: customer → sale form pre-filled with this customer ────
            return redirect(f"/sales/create/?customer={customer.pk}")
    else:
        form = CustomerForm()
    return render(
        request, "customers/form.html", {"form": form, "title": "Nouveau Client"}
    )


@login_required
def customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk)

    sales = (
        customer.sale_set.prefetch_related("line_items__vehicle")
        .select_related("assigned_trader")
        .order_by("-sale_date")
    )

    invoices = customer.invoice_set.all().order_by("-invoice_date")
    outstanding_invoices = invoices.filter(balance_due__gt=0)

    total_purchases = sales.count()
    total_value = sum(sale.sale_price for sale in sales)
    total_outstanding = sum(inv.balance_due for inv in outstanding_invoices)

    recent_notes = customer.customer_notes.order_by("-created_at")[:5]
    note_form = CustomerNoteForm()

    return render(
        request,
        "customers/detail.html",
        {
            "customer": customer,
            "sales_history": sales,
            "total_purchases": total_purchases,
            "total_value": total_value,
            "total_outstanding": total_outstanding,
            "outstanding_invoices": outstanding_invoices,
            "recent_notes": recent_notes,
            "note_form": note_form,
        },
    )


@trader_required
def customer_edit(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == "POST":
        form = CustomerForm(request.POST, request.FILES, instance=customer)
        if form.is_valid():
            customer = form.save(commit=False)
            customer.updated_by = request.user
            customer.save()
            messages.success(request, f"Client '{customer.name}' modifié avec succès.")
            return redirect("customers:detail", pk=customer.pk)
    else:
        form = CustomerForm(instance=customer)
    return render(
        request,
        "customers/form.html",
        {"form": form, "customer": customer, "title": f"Modifier {customer.name}"},
    )


@login_required
def customer_add_note(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == "POST":
        form = CustomerNoteForm(request.POST)
        if form.is_valid():
            note = form.save(commit=False)
            note.customer = customer
            note.created_by = request.user
            note.save()
            messages.success(request, "Note ajoutée avec succès.")
    return redirect("customers:detail", pk=pk)


@login_required
def customer_ajax_search(request):
    term = request.GET.get("term", "")
    customers = Customer.objects.filter(is_active=True).filter(
        Q(name__icontains=term) | Q(phone__icontains=term)
    )[:10]
    return JsonResponse(
        {
            "results": [
                {
                    "id": c.id,
                    "text": f"{c.name} — {c.phone}",
                    "name": c.name,
                    "phone": c.phone,
                    "address": c.address,
                    "customer_type": c.customer_type,
                    "nif_tax_id": c.nif_tax_id,
                    "wilaya": c.wilaya,
                }
                for c in customers
            ]
        }
    )


@trader_required
def customer_quick_create(request):
    if request.method == "POST":
        form = QuickCustomerForm(request.POST)
        if form.is_valid():
            customer = form.save(commit=False)
            customer.created_by = request.user
            customer.save()
            return JsonResponse(
                {
                    "success": True,
                    "customer": {
                        "id": customer.id,
                        "name": customer.name,
                        "phone": customer.phone,
                        "address": customer.address,
                        "customer_type": customer.customer_type,
                        "nif_tax_id": customer.nif_tax_id,
                        "wilaya": customer.wilaya,
                    },
                }
            )
        return JsonResponse({"success": False, "errors": form.errors})
    return render(request, "customers/quick_form.html", {"form": QuickCustomerForm()})


@trader_required
def customer_toggle_status(request, pk):
    if request.method == "POST":
        customer = get_object_or_404(Customer, pk=pk)
        if customer.is_active and customer.outstanding_balance > 0:
            return JsonResponse(
                {
                    "success": False,
                    "message": "Impossible de désactiver un client avec un solde impayé.",
                }
            )
        customer.is_active = not customer.is_active
        customer.updated_by = request.user
        customer.save()
        status_text = "activé" if customer.is_active else "désactivé"
        return JsonResponse(
            {
                "success": True,
                "message": f"Client {status_text} avec succès.",
                "is_active": customer.is_active,
            }
        )
    return JsonResponse({"success": False, "message": "Méthode non autorisée."})
