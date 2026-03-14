"""URL configuration for template tag tests."""

from django.contrib import admin
from django.http import HttpResponse
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", lambda r: HttpResponse("home"), name="home"),
    path("detail/<int:pk>/", lambda r, pk: HttpResponse(f"detail {pk}"), name="detail"),
]
