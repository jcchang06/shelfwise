import pytest
from django.contrib.auth import authenticate, get_user_model

from .factories import UserFactory

pytestmark = pytest.mark.django_db


def test_create_user_uses_email_as_login():
    user = get_user_model().objects.create_user(email=" Reader@Example.COM ", password="pw-12345")
    assert user.email == "reader@example.com"  # whole address lowercased and trimmed
    assert user.check_password("pw-12345")
    assert not user.is_staff
    assert str(user) == "reader@example.com"


def test_save_lowercases_email_outside_the_manager():
    # Admin forms and plain .save() skip create_user; the model normalizes anyway.
    user = UserFactory()
    user.email = "Changed@Example.com"
    user.save()
    user.refresh_from_db()
    assert user.email == "changed@example.com"


def test_authenticate_ignores_email_case():
    UserFactory(email="reader@example.com", password="pw-12345")
    assert authenticate(email="READER@example.com", password="pw-12345") is not None


def test_create_user_requires_email():
    with pytest.raises(ValueError):
        get_user_model().objects.create_user(email="", password="pw")


def test_create_superuser_sets_flags():
    admin = get_user_model().objects.create_superuser(email="a@example.com", password="pw")
    assert admin.is_staff and admin.is_superuser
