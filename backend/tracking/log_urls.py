from django.urls import path

from .log_views import LogDetailView, LogListCreateView

app_name = "logs"

urlpatterns = [
    path("", LogListCreateView.as_view(), name="log-list"),
    path("<int:pk>/", LogDetailView.as_view(), name="log-detail"),
]
