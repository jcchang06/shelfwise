from rest_framework import serializers

from .models import GoodreadsImport


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
