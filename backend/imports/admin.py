from django.contrib import admin

from .models import GoodreadsImport, GoodreadsLink, ImportRow


@admin.register(GoodreadsImport)
class GoodreadsImportAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "status",
        "processed_rows",
        "total_rows",
        "created_count",
        "updated_count",
        "unmatched_count",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("user__email",)
    list_select_related = ("user",)


@admin.register(ImportRow)
class ImportRowAdmin(admin.ModelAdmin):
    list_display = ("row_number", "title", "author", "state", "match_method", "goodreads_import")
    list_filter = ("state", "match_method")
    search_fields = ("title", "author", "isbn_13", "goodreads_book_id")
    raw_id_fields = ("goodreads_import", "book", "user_book")


@admin.register(GoodreadsLink)
class GoodreadsLinkAdmin(admin.ModelAdmin):
    list_display = ("goodreads_book_id", "user", "user_book", "synced_at")
    search_fields = ("goodreads_book_id", "user__email")
    raw_id_fields = ("user_book",)
