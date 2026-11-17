from django.urls import path

from .views import (
    DismissRowView,
    ImportDetailView,
    ImportListCreateView,
    ImportProcessView,
    ImportRowListView,
    ResolveRowView,
)

app_name = "imports"

urlpatterns = [
    path("", ImportListCreateView.as_view(), name="import-list"),
    path("<int:pk>/", ImportDetailView.as_view(), name="import-detail"),
    path("<int:pk>/process/", ImportProcessView.as_view(), name="import-process"),
    path("<int:pk>/rows/", ImportRowListView.as_view(), name="import-rows"),
    path("<int:pk>/rows/<int:row_id>/resolve/", ResolveRowView.as_view(), name="row-resolve"),
    path("<int:pk>/rows/<int:row_id>/dismiss/", DismissRowView.as_view(), name="row-dismiss"),
]
