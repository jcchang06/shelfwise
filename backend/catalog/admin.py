from django.contrib import admin

from .models import Author, Book, BookAuthor


class BookAuthorInline(admin.TabularInline):
    model = BookAuthor
    extra = 1
    autocomplete_fields = ["author"]


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("title", "isbn_13", "published_date", "series_name", "series_number")
    search_fields = ("title", "isbn_13", "google_books_id", "open_library_key")
    list_filter = ("published_date_precision",)
    inlines = [BookAuthorInline]


@admin.register(Author)
class AuthorAdmin(admin.ModelAdmin):
    list_display = ("name", "open_library_key")
    search_fields = ("name", "open_library_key")
