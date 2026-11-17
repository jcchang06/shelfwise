"""T-1: email + password sign-up, login and JWT auth."""

import datetime as dt

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from .factories import UserFactory

pytestmark = pytest.mark.django_db

PASSWORD = "correct-horse-battery"


def register(client, email="reader@example.com", password=PASSWORD):
    return client.post(reverse("accounts:register"), {"email": email, "password": password})


def login(client, email="reader@example.com", password=PASSWORD):
    return client.post(reverse("accounts:token"), {"email": email, "password": password})


class TestRegister:
    def test_creates_user_and_returns_tokens(self, api_client):
        response = register(api_client, email="New.Reader@Example.com")

        assert response.status_code == 201
        body = response.json()
        assert body["user"]["email"] == "new.reader@example.com"
        assert set(body["user"]) == {"id", "email", "date_joined"}  # never the password hash
        assert body["access"] and body["refresh"]

        user = get_user_model().objects.get(email="new.reader@example.com")
        assert user.check_password(PASSWORD)

    def test_returned_access_token_works(self, api_client):
        access = register(api_client).json()["access"]
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        assert api_client.get(reverse("accounts:me")).status_code == 200

    def test_duplicate_email_rejected_case_insensitively(self, api_client):
        UserFactory(email="reader@example.com")
        response = register(api_client, email="READER@example.com")
        assert response.status_code == 400
        assert "email" in response.json()

    @pytest.mark.parametrize(
        "password",
        ["short1", "password123", "12345678901", "reader@example.com"],
        ids=["too-short", "common", "numeric", "same-as-email"],
    )
    def test_weak_passwords_rejected(self, api_client, password):
        response = register(api_client, password=password)
        assert response.status_code == 400
        assert not get_user_model().objects.exists()

    def test_invalid_email_rejected(self, api_client):
        assert register(api_client, email="not-an-email").status_code == 400

    def test_disabled_by_setting(self, api_client, settings):
        settings.ALLOW_SIGNUP = False
        response = register(api_client)
        assert response.status_code == 403
        assert not get_user_model().objects.exists()


class TestLogin:
    def test_returns_token_pair(self, api_client):
        UserFactory(email="reader@example.com", password=PASSWORD)
        response = login(api_client)
        assert response.status_code == 200
        assert set(response.json()) == {"access", "refresh"}

    def test_email_is_case_insensitive(self, api_client):
        UserFactory(email="reader@example.com", password=PASSWORD)
        assert login(api_client, email="Reader@EXAMPLE.com").status_code == 200

    def test_records_last_login(self, api_client):
        user = UserFactory(email="reader@example.com", password=PASSWORD)
        login(api_client)
        user.refresh_from_db()
        assert user.last_login is not None

    @pytest.mark.parametrize(
        ("email", "password"),
        [("reader@example.com", "wrong-password"), ("nobody@example.com", PASSWORD)],
        ids=["wrong-password", "unknown-email"],
    )
    def test_bad_credentials_get_401(self, api_client, email, password):
        UserFactory(email="reader@example.com", password=PASSWORD)
        assert login(api_client, email=email, password=password).status_code == 401

    def test_inactive_user_cannot_log_in(self, api_client):
        UserFactory(email="reader@example.com", password=PASSWORD, is_active=False)
        assert login(api_client).status_code == 401


class TestRefresh:
    def test_refresh_returns_new_access_token(self, api_client):
        UserFactory(email="reader@example.com", password=PASSWORD)
        refresh = login(api_client).json()["refresh"]
        response = api_client.post(reverse("accounts:token-refresh"), {"refresh": refresh})
        assert response.status_code == 200
        assert response.json()["access"]

    def test_refresh_rotates_the_refresh_token(self, api_client):
        UserFactory(email="reader@example.com", password=PASSWORD)
        first = login(api_client).json()["refresh"]
        body = api_client.post(reverse("accounts:token-refresh"), {"refresh": first}).json()
        assert body["refresh"] and body["refresh"] != first
        # The new one works...
        again = api_client.post(reverse("accounts:token-refresh"), {"refresh": body["refresh"]})
        assert again.status_code == 200

    def test_old_refresh_token_stays_valid_without_blacklist(self, api_client):
        # Documented v1 trade-off: rotation without a blacklist doesn't revoke old tokens.
        UserFactory(email="reader@example.com", password=PASSWORD)
        first = login(api_client).json()["refresh"]
        api_client.post(reverse("accounts:token-refresh"), {"refresh": first})
        reused = api_client.post(reverse("accounts:token-refresh"), {"refresh": first})
        assert reused.status_code == 200

    def test_garbage_refresh_token_rejected(self, api_client):
        response = api_client.post(reverse("accounts:token-refresh"), {"refresh": "nope"})
        assert response.status_code == 401


class TestMe:
    def test_requires_auth(self, api_client):
        assert api_client.get(reverse("accounts:me")).status_code == 401

    def test_returns_only_the_caller(self, api_client):
        UserFactory(email="someone-else@example.com")
        user = UserFactory(email="reader@example.com")
        api_client.force_authenticate(user)
        assert api_client.get(reverse("accounts:me")).json()["email"] == "reader@example.com"

    def test_expired_access_token_rejected(self, api_client):
        token = AccessToken.for_user(UserFactory())
        token.set_exp(lifetime=-dt.timedelta(seconds=1))
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        assert api_client.get(reverse("accounts:me")).status_code == 401

    def test_refresh_token_not_accepted_as_access_token(self, api_client):
        refresh = RefreshToken.for_user(UserFactory())
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh}")
        assert api_client.get(reverse("accounts:me")).status_code == 401


def test_login_is_throttled(api_client, monkeypatch):
    # THROTTLE_RATES is read once at import, so patch the class attribute directly.
    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", {"auth": "3/minute"})
    UserFactory(email="reader@example.com", password=PASSWORD)
    statuses = [login(api_client, password="wrong").status_code for _ in range(4)]
    assert statuses == [401, 401, 401, 429]
