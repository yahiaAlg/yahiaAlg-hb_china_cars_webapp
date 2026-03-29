from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Sum, Count, Q, Avg
from datetime import datetime, timedelta
from decimal import Decimal
import json


@login_required
def index(request):
    """Index/home view with quick access cards"""
    return render(request, "core/index.html")


@login_required
def dashboard(request):
    """Main dashboard view with comprehensive metrics"""

    # Get user role for customized dashboard
    user_role = None
    if hasattr(request.user, "userprofile"):
        user_role = request.user.userprofile.role

    # Date ranges
    today = timezone.now().date()
    current_month_start = today.replace(day=1)
    last_month_start = (current_month_start - timedelta(days=1)).replace(day=1)
    last_month_end = current_month_start - timedelta(days=1)
    twelve_months_ago = today - timedelta(days=365)

    # Import models
    from inventory.models import Vehicle, StockAlert
    from sales.models import Sale, Invoice
    from purchases.models import Purchase
    from payments.models import Payment
    from customers.models import Customer
    from commissions.models import CommissionSummary
    from django.contrib.auth.models import User

    # ============================================
    # INVENTORY METRICS
    # ============================================

    # Total inventory value (only available vehicles)
    available_vehicles = Vehicle.objects.filter(status="available")
    total_inventory_value = sum(v.landed_cost or 0 for v in available_vehicles)

    # Vehicle counts by status
    vehicles_in_stock = available_vehicles.count()
    vehicles_reserved = Vehicle.objects.filter(status="reserved").count()
    vehicles_in_customs = Vehicle.objects.filter(status="at_customs").count()
    vehicles_in_transit = Vehicle.objects.filter(status="in_transit").count()

    # ============================================
    # SALES METRICS
    # ============================================

    # Current month sales
    current_month_sales = Sale.objects.filter(
        sale_date__gte=current_month_start, sale_date__lte=today, is_finalized=True
    )

    # Last month sales for comparison
    last_month_sales = Sale.objects.filter(
        sale_date__gte=last_month_start,
        sale_date__lte=last_month_end,
        is_finalized=True,
    )

    # Sales metrics
    monthly_sales_count = current_month_sales.count()
    monthly_revenue = sum(s.sale_price for s in current_month_sales)
    monthly_margin = sum(s.margin_amount for s in current_month_sales)

    # Calculate percentage change
    last_month_revenue = sum(s.sale_price for s in last_month_sales)
    if last_month_revenue > 0:
        revenue_change_pct = (
            (monthly_revenue - last_month_revenue) / last_month_revenue
        ) * 100
    else:
        revenue_change_pct = 0

    # Margin percentage
    if monthly_revenue > 0:
        margin_percentage = (monthly_margin / monthly_revenue) * 100
    else:
        margin_percentage = 0

    # ============================================
    # PAYMENT METRICS
    # ============================================

    # Outstanding invoices
    outstanding_invoices = Invoice.objects.filter(balance_due__gt=0)
    total_outstanding = sum(inv.balance_due for inv in outstanding_invoices)
    outstanding_count = outstanding_invoices.count()

    # Overdue invoices
    overdue_invoices = outstanding_invoices.filter(
        due_date__lt=today, status="issued"
    ).count()

    # ============================================
    # STOCK ALERTS
    # ============================================

    # Get unresolved alerts
    stock_alerts = StockAlert.objects.filter(is_resolved=False).order_by("-created_at")[
        :5
    ]

    # Create alert list with priority
    alerts_list = []
    for alert in stock_alerts:
        priority = (
            "high"
            if alert.alert_type in ["slow_moving", "customs_delayed"]
            else "medium"
        )
        alerts_list.append(
            {
                "priority": priority,
                "type": alert.get_alert_type_display(),
                "message": alert.message,
                "vehicle": alert.vehicle,
                "created": alert.created_at,
            }
        )

    # Add overdue invoice alerts
    overdue_inv_objects = Invoice.objects.filter(
        balance_due__gt=0, due_date__lt=today, status="issued"
    ).order_by("due_date")[:3]

    for inv in overdue_inv_objects:
        alerts_list.append(
            {
                "priority": "high",
                "type": "Overdue Invoice",
                "message": f"Invoice {inv.invoice_number} overdue by {inv.days_overdue} days - {inv.customer.name}",
                "invoice": inv,
                "created": inv.due_date,
            }
        )

    # ============================================
    # SALES TREND (Last 12 months)
    # ============================================

    sales_trend_labels = []
    sales_trend_data = []

    for i in range(11, -1, -1):
        month_date = today - timedelta(days=i * 30)
        month_start = month_date.replace(day=1)

        # Get next month start
        if month_date.month == 12:
            month_end = month_date.replace(
                year=month_date.year + 1, month=1, day=1
            ) - timedelta(days=1)
        else:
            month_end = month_date.replace(
                month=month_date.month + 1, day=1
            ) - timedelta(days=1)

        month_sales = Sale.objects.filter(
            sale_date__gte=month_start, sale_date__lte=month_end, is_finalized=True
        )

        total = sum(s.sale_price for s in month_sales) / 1000000  # Convert to millions

        sales_trend_labels.append(month_date.strftime("%b %Y"))
        sales_trend_data.append(float(total))

    # ============================================
    # TRADER PERFORMANCE
    # ============================================

    traders = User.objects.filter(
        userprofile__role="trader", userprofile__is_active=True
    )
    trader_names = []
    trader_revenues = []
    trader_sales_counts = []

    for trader in traders:
        trader_sales = current_month_sales.filter(assigned_trader=trader)
        trader_revenue = sum(s.sale_price for s in trader_sales) / 1000000  # Millions
        trader_count = trader_sales.count()

        trader_names.append(trader.get_full_name() or trader.username)
        trader_revenues.append(float(trader_revenue))
        trader_sales_counts.append(trader_count)

    # Sort all lists by revenue (descending)
    sorted_data = sorted(
        zip(trader_revenues, trader_names, trader_sales_counts), reverse=True
    )
    trader_revenues, trader_names, trader_sales_counts = (
        zip(*sorted_data) if sorted_data else ([], [], [])
    )

    # ============================================
    # USER-SPECIFIC DATA
    # ============================================

    user_commission = 0
    recent_sales = None

    if user_role == "trader":
        # Trader sees their own performance data
        user_sales = current_month_sales.filter(assigned_trader=request.user)
        user_commission = sum(s.commission_amount or 0 for s in user_sales)
        recent_sales = Sale.objects.filter(assigned_trader=request.user).order_by(
            "-sale_date"
        )[:5]

    elif user_role in ["manager", "finance"]:
        # Manager/Finance see overall recent activity
        recent_sales = Sale.objects.filter(is_finalized=True).order_by("-sale_date")[:5]

    # ============================================
    # INVENTORY PERCENTAGE CHANGE
    # ============================================

    # Get last month's inventory value for comparison
    last_month_vehicles = Vehicle.objects.filter(
        status="available", created_at__lte=last_month_end
    )
    last_month_inventory_value = sum(v.landed_cost or 0 for v in last_month_vehicles)

    if last_month_inventory_value > 0:
        inventory_change_pct = (
            (total_inventory_value - last_month_inventory_value)
            / last_month_inventory_value
        ) * 100
    else:
        inventory_change_pct = 0

    # ============================================
    # CONTEXT DATA
    # ============================================

    context = {
        "user_role": user_role,
        "current_date": today,
        # Inventory metrics
        "total_inventory_value": total_inventory_value,
        "inventory_change_pct": inventory_change_pct,
        "vehicles_in_stock": vehicles_in_stock,
        "vehicles_reserved": vehicles_reserved,
        "vehicles_in_customs": vehicles_in_customs,
        "vehicles_in_transit": vehicles_in_transit,
        # Sales metrics
        "monthly_sales_count": monthly_sales_count,
        "monthly_revenue": monthly_revenue,
        "revenue_change_pct": revenue_change_pct,
        "monthly_margin": monthly_margin,
        "margin_percentage": margin_percentage,
        # Payment metrics
        "outstanding_count": outstanding_count,
        "total_outstanding": total_outstanding,
        "overdue_count": overdue_invoices,
        # User-specific
        "user_commission": user_commission,
        "recent_sales": recent_sales,
        # Charts data - prepared for Chart.js
        "sales_trend_labels": json.dumps(sales_trend_labels),
        "sales_trend_data": json.dumps(sales_trend_data),
        "trader_names": json.dumps(list(trader_names)),
        "trader_revenues": json.dumps(list(trader_revenues)),
        "trader_sales_counts": json.dumps(list(trader_sales_counts)),
        # Alerts
        "alerts_list": sorted(
            alerts_list,
            key=lambda x: (
                0 if x["priority"] == "high" else 1,
                x["created"].date() if hasattr(x["created"], "date") else x["created"],
            ),
            reverse=True,
        )[:6],
    }

    return render(request, "core/dashboard.html", context)
