from rest_framework import serializers

from .models import GoodreadsImport, ImportRow


class GoodreadsImportSerializer(serializers.ModelSerializer):
    # How many imported DNFs still carry the placeholder reason (set by the view).
    placeholder_dnf_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = GoodreadsImport
        fields = [
            "id",
            "status",
            "total_rows",
            "processed_rows",
            "created_count",
            "updated_count",
            "skipped_count",
            "unmatched_count",
            "failed_count",
            "placeholder_dnf_count",
            "error",
            "created_at",
            "finished_at",
        ]
        read_only_fields = fields


class ImportRowSerializer(serializers.ModelSerializer):
    """A row as the reader saw it in Goodreads, plus why it needs attention."""

    # Pre-fills the search box when matching by hand: "title first-author".
    search_query = serializers.SerializerMethodField()

    class Meta:
        model = ImportRow
        fields = [
            "id",
            "row_number",
            "title",
            "author",
            "additional_authors",
            "isbn_13",
            "year_published",
            "status",
            "rating",
            "date_read",
            "state",
            "note",
            "search_query",
        ]
        read_only_fields = fields

    def get_search_query(self, row) -> str:
        first_author = row.author.split(",")[0].strip()
        return f"{row.title} {first_author}".strip()


class ResolveRowSerializer(serializers.Serializer):
    """The book the reader picked: a catalog book_id, or source + source_id from search."""

    book_id = serializers.IntegerField(min_value=1, required=False)
    source = serializers.CharField(required=False)
    source_id = serializers.CharField(required=False)

    def validate(self, attrs: dict) -> dict:
        from catalog.serializers import SaveBookSerializer

        unknown = set(self.initial_data) - {"book_id", "source", "source_id"}
        if unknown:
            raise serializers.ValidationError(
                {key: ["This field can't be set here."] for key in sorted(unknown)}
            )
        has_id = "book_id" in attrs
        has_source = "source" in attrs or "source_id" in attrs
        if has_id == has_source:
            raise serializers.ValidationError(
                "Send either book_id, or source and source_id, but not both."
            )
        if has_source:
            source = SaveBookSerializer(
                data={"source": attrs.get("source"), "source_id": attrs.get("source_id")}
            )
            source.is_valid(raise_exception=True)
            attrs.update(source.validated_data)
        return attrs
