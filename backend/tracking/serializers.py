"""Shelf API serializers. These check types and shape only; business rules are in services.py."""

from rest_framework import serializers

from catalog.serializers import SaveBookSerializer

from .models import ReadingLog, UserBook


class StrictFieldsMixin:
    """Reject unknown keys instead of silently ignoring them (DRF's default), so a typo
    like {"raiting": 5} or an attempt to change `book`/`user` gets a clear 400."""

    def to_internal_value(self, data):
        if hasattr(data, "keys"):
            unknown = set(data.keys()) - set(self.fields)
            if unknown:
                raise serializers.ValidationError(
                    {key: ["This field can't be set here."] for key in sorted(unknown)}
                )
        return super().to_internal_value(data)


class ShelfChangesSerializer(StrictFieldsMixin, serializers.Serializer):
    """The editable fields of a shelf entry, all optional (PATCH semantics)."""

    status = serializers.ChoiceField(choices=UserBook.Status.choices, required=False)
    rating = serializers.IntegerField(min_value=1, max_value=5, allow_null=True, required=False)
    review = serializers.CharField(allow_blank=True, max_length=10_000, required=False)
    started_at = serializers.DateField(allow_null=True, required=False)
    finished_at = serializers.DateField(allow_null=True, required=False)
    dnf_page = serializers.IntegerField(min_value=0, allow_null=True, required=False)
    dnf_at = serializers.DateField(allow_null=True, required=False)
    dnf_reason = serializers.ChoiceField(
        choices=UserBook.DnfReason.choices, allow_blank=True, required=False
    )
    dnf_note = serializers.CharField(allow_blank=True, max_length=2_000, required=False)


class AddToShelfSerializer(ShelfChangesSerializer):
    """POST body: a catalog `book_id`, or `source` + `source_id` to save from search first."""

    book_id = serializers.IntegerField(min_value=1, required=False)
    source = serializers.CharField(required=False)
    source_id = serializers.CharField(required=False)

    BOOK_FIELDS = ("book_id", "source", "source_id")

    def validate(self, attrs: dict) -> dict:
        has_id = "book_id" in attrs
        has_source = "source" in attrs or "source_id" in attrs
        if has_id == has_source:
            raise serializers.ValidationError(
                "Send either book_id, or source and source_id, but not both."
            )
        if has_source:
            # Same checks as POST /api/books/, including the strict source_id patterns.
            source = SaveBookSerializer(
                data={"source": attrs.get("source"), "source_id": attrs.get("source_id")}
            )
            source.is_valid(raise_exception=True)
            attrs.update(source.validated_data)
        return attrs

    def split(self) -> tuple[dict, dict]:
        """(book reference, shelf changes) from validated_data."""
        data = dict(self.validated_data)
        book_ref = {key: data.pop(key) for key in self.BOOK_FIELDS if key in data}
        return book_ref, data


class ShelfBookSerializer(serializers.Serializer):
    """The compact book shown on shelf entries. Full details are at /api/books/{id}/."""

    id = serializers.IntegerField()
    title = serializers.CharField()
    authors = serializers.SerializerMethodField()
    cover_url = serializers.CharField()
    page_count = serializers.IntegerField(allow_null=True)

    # [{id, name}] in credit order, for links to author pages (C-5).
    author_links = serializers.SerializerMethodField()

    def get_authors(self, book) -> list[str]:
        return [ba.author.name for ba in book.book_authors.all()]

    def get_author_links(self, book) -> list[dict]:
        return [{"id": ba.author_id, "name": ba.author.name} for ba in book.book_authors.all()]


class UserBookSerializer(serializers.ModelSerializer):
    book = ShelfBookSerializer(read_only=True)
    # Annotated by the view's queryset (no per-row queries).
    pages_logged = serializers.IntegerField(read_only=True)
    reading_log_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = UserBook
        fields = [
            "id",
            "book",
            "status",
            "rating",
            "review",
            "started_at",
            "finished_at",
            "dnf_page",
            "dnf_at",
            "dnf_reason",
            "dnf_note",
            "pages_logged",
            "reading_log_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


# --- Page logs (T-3) ----------------------------------------------------------


class LogCreateSerializer(StrictFieldsMixin, serializers.Serializer):
    book_id = serializers.IntegerField(min_value=1)
    # The per-day cap (MAX_PAGES_PER_DAY) is a business rule checked in reading_logs.py.
    pages_read = serializers.IntegerField(min_value=1)
    log_date = serializers.DateField(required=False)


class LogUpdateSerializer(StrictFieldsMixin, serializers.Serializer):
    pages_read = serializers.IntegerField(min_value=1, required=False)
    log_date = serializers.DateField(required=False)


class ReadingLogSerializer(serializers.ModelSerializer):
    book_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = ReadingLog
        fields = ["id", "book_id", "log_date", "pages_read", "created_at", "updated_at"]
        read_only_fields = fields


class LogShelfEntrySerializer(serializers.Serializer):
    """The bits of the shelf entry a log write can change, so the UI needn't refetch."""

    id = serializers.IntegerField()
    status = serializers.CharField()
    started_at = serializers.DateField(allow_null=True)
    pages_logged = serializers.IntegerField()
