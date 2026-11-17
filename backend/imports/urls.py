from django.urls import path

from .views import ImportDetailView, ImportListCreateView, ImportProcessView

app_name = "imports"

urlpatterns = [
    path("", ImportListCreateView.as_view(), name="import-list"),
    path("<int:pk>/", ImportDetailView.as_view(), name="import-detail"),
    path("<int:pk>/process/", ImportProcessView.as_view(), name="import-process"),
]
