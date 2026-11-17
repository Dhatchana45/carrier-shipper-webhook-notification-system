
from django.urls import path
from . import views

urlpatterns = [
    # Carriers
    path("carriers/", views.carrier_list, name="carrier_list"),
    path("carriers/create/", views.carrier_create, name="carrier_create"),

    # Shippers
    path("shippers/", views.shipper_list, name="shipper_list"),
    path("shippers/create/", views.shipper_create, name="shipper_create"),

    # Drivers
    path("drivers/", views.driver_list, name="driver_list"),
    path("drivers/create/", views.driver_create, name="driver_create"),

    # Loads
    path("loads/", views.load_list, name="load_list"),
    path("loads/create/", views.load_create, name="load_create"),

     # Load assignment and status updates
    path(
        "loads/<uuid:load_id>/assign/",
        views.load_assign,
        name="load_assign",
    ),
    path(
        "loads/<uuid:load_id>/status/",
        views.load_update_status,
        name="load_update_status",
    ),
]
