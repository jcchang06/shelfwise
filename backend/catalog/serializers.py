from rest_framework import serializers

from .models import Book
from .services import google_books, open_library
from .services.types import BookResult, Source

# Source IDs are interpolated into API URL paths (volumes/{id}, works/{key}.json), so they
# are validated strictly: no slashes, dots or query characters can reach the request.
SOURCE_ID_PATTERNS = {
    Source.GOOGLE_BOOKS: r"^[A-Za-z0-9_-]{1,32}$",
    Source.OPEN_LIBRARY: r"^OL\d{1,12}W$",
}
MAX_SEARCH_PAGES = 10  # Google rarely returns useful results past ~200


class SearchQuerySerializer(serializers.Serializer):
    q = serializers.CharField(min_length=2, max_length=200, trim_whitespace=True)
    page = serializers.IntegerField(min_value=1, max_value=MAX_SEARCH_PAGES, default=1)


class SearchShelfSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.CharField()


class SearchResultSerializer(serializers.Serializer):
    """A search hit. `book_id` is the catalog book it would save to (null if new); `shelf`
    is the caller's shelf entry for that book (null if not shelved)."""

    source = serializers.CharField()
    source_id = serializers.CharField()
    title = serializers.CharField()
    authors = serializers.SerializerMethodField()
    description = serializers.CharField()
    genres = serializers.ListField(child=serializers.CharField())
    page_count = serializers.IntegerField(allow_null=True)
    published_date = serializers.CharField()
    isbn_13 = serializers.CharField()
    cover_url = serializers.CharField()
    book_id = serializers.IntegerField(allow_null=True)
    shelf = SearchShelfSerializer(allow_null=True)
    # [{id, name}] in credit order; id is the catalog author (C-5 author page), or null
    # for an author not in the catalog yet. `authors` stays plain names.
    author_links = serializers.SerializerMethodField()

    def get_authors(self, obj: dict) -> list[str]:
        return [author.name for author in obj["authors"]]

    def get_author_links(self, obj: dict) -> list[dict]:
        ids = obj.get("author_ids") or [None] * len(obj["authors"])
        return [
            {"id": author_id, "name": author.name}
            for author, author_id in zip(obj["authors"], ids, strict=True)
        ]


def search_result_data(
    result: BookResult,
    book_id: int | None,
    shelf: dict | None,
    author_ids: list[int | None] | None = None,
) -> dict:
    return {
        "source": result.source.value,
        "source_id": result.source_id,
        "title": result.title,
        "authors": result.authors,
        "description": result.description,
        "genres": list(result.genres),
        "page_count": result.page_count,
        "published_date": result.published_date,
        "isbn_13": result.isbn_13,
        "cover_url": result.cover_url,
        "book_id": book_id,
        "shelf": shelf,
        "author_ids": author_ids,
    }


class SaveBookSerializer(serializers.Serializer):
    source = serializers.ChoiceField(choices=[s.value for s in Source])
    source_id = serializers.CharField(max_length=32)

    def validate(self, attrs: dict) -> dict:
        source = Source(attrs["source"])
        field = serializers.RegexField(SOURCE_ID_PATTERNS[source])
        try:
            field.run_validation(attrs["source_id"])
        except serializers.ValidationError as exc:
            raise serializers.ValidationError(
                {"source_id": f"Not a valid {source.value} ID."}
            ) from exc
        attrs["source"] = source
        return attrs


class BookAuthorSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="author.id")
    name = serializers.CharField(source="author.name")


class BookSerializer(serializers.ModelSerializer):
    authors = BookAuthorSerializer(source="book_authors", many=True, read_only=True)
    published_date = serializers.CharField(source="published_date_display", read_only=True)

    class Meta:
        model = Book
        fields = [
            "id",
            "title",
            "authors",
            "description",
            "genres",
            "page_count",
            "published_date",
            "isbn_13",
            "cover_url",
            "series_name",
            "series_number",
            "google_books_id",
            "open_library_key",
        ]
        read_only_fields = fields


# Re-exported so the view can report page size without importing the clients.
PAGE_SIZES = {
    Source.GOOGLE_BOOKS: google_books.PAGE_SIZE,
    Source.OPEN_LIBRARY: open_library.PAGE_SIZE,
}
