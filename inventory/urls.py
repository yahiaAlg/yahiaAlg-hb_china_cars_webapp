from django.urls import path
from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.vehicle_list, name="list"),
    path("create/", views.vehicle_create, name="create"),
    path("<int:pk>/", views.vehicle_detail, name="detail"),
    path("<int:pk>/edit/", views.vehicle_edit, name="edit"),
    path("<int:pk>/reserve/", views.vehicle_reserve, name="reserve"),
    path(
        "<int:pk>/release-reservation/",
        views.vehicle_release_reservation,
        name="release_reservation",
    ),
    path("<int:pk>/add-photo/", views.vehicle_add_photo, name="add_photo"),
    path("<int:pk>/change-status/", views.vehicle_change_status, name="change_status"),
    path("alerts/", views.stock_alerts, name="alerts"),
    path("alerts/<int:pk>/resolve/", views.resolve_alert, name="resolve_alert"),
]
