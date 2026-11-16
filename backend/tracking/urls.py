from django.urls import path

from .views import ShelfDetailView, ShelfListCreateView

app_name = "tracking"

urlpatterns = [
    path("", ShelfListCreateView.as_view(), name="shelf-list"),
    path("<int:pk>/", ShelfDetailView.as_view(), name="shelf-detail"),
]
