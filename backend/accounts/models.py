from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager["User"]):
    """Manager for an email-only user (no username field)."""

    use_in_migrations = True

    @classmethod
    def normalize_email(cls, email: str | None) -> str:
        """Lowercase the whole address, not just the domain like Django's default.

        Email logins should be case-insensitive in practice, so "Reader@x.com" and
        "reader@x.com" must not become two accounts or fail to log in.
        """
        return (email or "").strip().lower()

    def get_by_natural_key(self, username: str | None) -> "User":
        # Used by ModelBackend at login, so the address someone types is matched the same way.
        return self.get(**{self.model.USERNAME_FIELD: self.normalize_email(username)})

    def _create_user(self, email: str, password: str | None, **extra_fields) -> "User":
        if not email:
            raise ValueError("Email is required")
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields) -> "User":
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email: str, password: str | None = None, **extra_fields) -> "User":
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Shelfwise user. Logs in with email (T-1); username is removed entirely."""

    username = None
    email = models.EmailField("email address", unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    def save(self, *args, **kwargs) -> None:
        # Covers paths that skip the manager (admin forms, plain .save()).
        self.email = UserManager.normalize_email(self.email)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.email
