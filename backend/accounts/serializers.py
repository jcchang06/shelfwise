from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User, UserManager


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = get_user_model()
        fields = ["id", "email", "date_joined"]
        read_only_fields = fields


class RegisterSerializer(serializers.Serializer):
    """Sign-up (T-1). Returns the new user plus a token pair, so the client is logged in."""

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate_email(self, value: str) -> str:
        email = UserManager.normalize_email(value)
        if User.objects.filter(email=email).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return email

    def validate(self, attrs: dict) -> dict:
        # Django's validators (length, common, numeric, similarity to the email).
        validate_password(attrs["password"], user=User(email=attrs["email"]))
        return attrs

    def create(self, validated_data: dict) -> User:
        return User.objects.create_user(**validated_data)

    def to_representation(self, instance: User) -> dict:
        refresh = RefreshToken.for_user(instance)
        return {
            "user": UserSerializer(instance).data,
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        }


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Login with a case-insensitive email."""

    def validate(self, attrs: dict) -> dict:
        attrs[self.username_field] = UserManager.normalize_email(attrs.get(self.username_field))
        return super().validate(attrs)
