from rest_framework import serializers

from catalog.models import Book


class SuggestedBookSerializer(serializers.ModelSerializer):
    """The compact book on a pick or a "more like this" entry."""

    author_links = serializers.SerializerMethodField()
    published_date = serializers.CharField(source="published_date_display", read_only=True)

    class Meta:
        model = Book
        fields = ["id", "title", "author_links", "cover_url", "page_count", "published_date"]
        read_only_fields = fields

    def get_author_links(self, book) -> list[dict]:
        return [{"id": ba.author_id, "name": ba.author.name} for ba in book.book_authors.all()]
