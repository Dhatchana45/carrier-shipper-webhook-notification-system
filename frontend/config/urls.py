
from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    # Django Admin
    path("admin/", admin.site.urls),

    # Authentication
    path("auth/", include("core.urls")),

    # Dashboard
    path("", include("dashboard.urls")),

    # Webhook Management
    path("webhooks/", include("webhooks.urls")),

    # Event Management
    path("events/", include("events.urls")),

    # Delivery Management
    path("deliveries/", include("deliveries.urls")),

    # Monitoring
    path("monitoring/", include("monitoring.urls")),

    # Carrier, Shipper, Driver and Load Management
    path("", include("trucking_portal.urls")),
]
