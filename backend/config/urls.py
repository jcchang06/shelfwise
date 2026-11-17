from django.contrib import admin
from django.urls import include, path
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request: Request) -> Response:
    """Liveness check for Render and CI. Doesn't touch the DB, so it stays fast on cold start."""
    return Response({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/auth/", include("accounts.urls")),
    path("api/books/", include("catalog.urls")),
    path("api/shelf/", include("tracking.urls")),
    path("api/logs/", include("tracking.log_urls")),
    path("api/stats/", include("tracking.stats_urls")),
]
