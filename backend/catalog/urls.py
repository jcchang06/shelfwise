from django.urls import path

from .views import BookDetailView, BookListCreateView, BookSearchView

app_name = "catalog"

urlpatterns = [
    path("", BookListCreateView.as_view(), name="book-list"),
    path("search/", BookSearchView.as_view(), name="book-search"),
    path("<int:pk>/", BookDetailView.as_view(), name="book-detail"),
]
