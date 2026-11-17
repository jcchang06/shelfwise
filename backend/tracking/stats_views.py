"""Dashboard stats endpoint (T-5). All numbers are for request.user only."""

from django.utils import timezone
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .stats import stats_for

MIN_YEAR = 1900


class StatsView(APIView):
    """GET /api/stats/?year=2026 — every dashboard section in one response.

    One request rather than one per chart: on the free tier, separate requests would each
    queue behind a cold start. `year` defaults to the current year in TIME_ZONE.
    """

    def get(self, request: Request) -> Response:
        current_year = timezone.localdate().year
        raw = request.query_params.get("year")
        if raw is None or raw == "":
            year = current_year
        else:
            if not raw.isdigit() or not MIN_YEAR <= int(raw) <= current_year:
                raise serializers.ValidationError(
                    {"year": [f"Must be a year from {MIN_YEAR} to {current_year}."]}
                )
            year = int(raw)
        return Response(stats_for(request.user, year))
