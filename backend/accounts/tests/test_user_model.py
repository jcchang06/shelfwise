import pytest
from django.contrib.auth import get_user_model

pytestmark = pytest.mark.django_db


def test_create_user_uses_email_as_login():
    user = get_user_model().objects.create_user(email="Reader@Example.COM", password="pw-12345")
    assert user.email == "Reader@example.com"  # domain part normalized
    assert user.check_password("pw-12345")
    assert not user.is_staff
    assert str(user) == "Reader@example.com"


def test_create_user_requires_email():
    with pytest.raises(ValueError):
        get_user_model().objects.create_user(email="", password="pw")


def test_create_superuser_sets_flags():
    admin = get_user_model().objects.create_superuser(email="a@example.com", password="pw")
    assert admin.is_staff and admin.is_superuser
