from django.conf import settings
from rest_framework import generics, permissions
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .serializers import EmailTokenObtainPairSerializer, RegisterSerializer, UserSerializer


class RegisterView(generics.CreateAPIView):
    """POST /api/auth/register/ — create an account and return a token pair (T-1)."""

    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []  # a stale token in the header shouldn't block sign-up
    throttle_scope = "auth"

    def create(self, request, *args, **kwargs):
        if not settings.ALLOW_SIGNUP:
            raise PermissionDenied("Sign-up is disabled.")
        return super().create(request, *args, **kwargs)


class LoginView(TokenObtainPairView):
    """POST /api/auth/token/ — exchange email + password for access and refresh tokens."""

    serializer_class = EmailTokenObtainPairSerializer
    throttle_scope = "auth"


class RefreshView(TokenRefreshView):
    """POST /api/auth/token/refresh/ — exchange a refresh token for a new access token."""

    throttle_scope = "auth"


class MeView(generics.RetrieveAPIView):
    """GET /api/auth/me/ — the logged-in user. Always request.user, never a lookup by ID."""

    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user
