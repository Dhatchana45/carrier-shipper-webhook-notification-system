from django.urls import path
from . import views

urlpatterns = [
    path("", views.webhook_list, name="webhook_list"),
    path("create/", views.webhook_create, name="webhook_create"),
    path("<str:webhook_id>/edit/", views.webhook_edit, name="webhook_edit"),
    path("<str:webhook_id>/delete/", views.webhook_delete, name="webhook_delete"),
]