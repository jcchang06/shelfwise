from django.urls import path

from .views import AuthorDetailView

app_name = "authors"

urlpatterns = [
    path("<int:pk>/", AuthorDetailView.as_view(), name="author-detail"),
]
