from django.contrib import admin

from .models import ReadingLog, UserBook


@admin.register(UserBook)
class UserBookAdmin(admin.ModelAdmin):
    list_display = ("book", "user", "status", "rating", "dnf_reason", "updated_at")
    list_filter = ("status", "dnf_reason")
    search_fields = ("book__title", "user__email")
    autocomplete_fields = ["book"]
    list_select_related = ("book", "user")


@admin.register(ReadingLog)
class ReadingLogAdmin(admin.ModelAdmin):
    list_display = ("log_date", "book", "user", "pages_read")
    list_filter = ("log_date",)
    search_fields = ("book__title", "user__email")
    autocomplete_fields = ["book"]
    date_hierarchy = "log_date"
    list_select_related = ("book", "user")
