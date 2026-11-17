from django.urls import path
from . import views

urlpatterns = [
    path("", views.delivery_list, name="delivery_list"),
    path("<str:delivery_id>/", views.delivery_detail, name="delivery_detail"),
]