from fastapi import FastAPI
from fastapi.testclient import TestClient


class FakeRedis:
    def __init__(self):
        self.hashes = {}

    def hset(self, key, mapping):
        self.hashes.setdefault(key, {}).update(mapping)


def make_client():
    from leobot_router import leobot_main_router as routes

    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app), routes


def test_google_one_tap_persists_verified_profile(monkeypatch):
    client, routes = make_client()
    redis = FakeRedis()
    monkeypatch.setattr(routes, "GOOGLE_CLIENT_ID", "web-client-id")
    monkeypatch.setattr(routes, "REDIS_CLIENT", redis)
    monkeypatch.setattr(
        routes,
        "_verify_google_one_tap_credential",
        lambda credential: {
            "sub": "google-subject",
            "name": "Ada Lovelace",
            "email": "ada@example.com",
            "email_verified": True,
        },
    )

    response = client.post(
        "/_leoai/auth/google/one-tap",
        json={"credential": "signed-token", "visitor_id": "visitor-123"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "name": "Ada Lovelace",
        "email": "ada@example.com",
        "profile_id": "google:google-subject",
        "provider": "google",
    }
    assert redis.hashes["visitor-123"] == {
        "profile_id": "google:google-subject",
        "google_sub": "google-subject",
        "auth_provider": "google",
        "name": "Ada Lovelace",
        "email": "ada@example.com",
    }


def test_google_one_tap_rejects_invalid_credential(monkeypatch):
    client, routes = make_client()
    redis = FakeRedis()
    monkeypatch.setattr(routes, "GOOGLE_CLIENT_ID", "web-client-id")
    monkeypatch.setattr(routes, "REDIS_CLIENT", redis)

    def reject_credential(credential):
        raise ValueError("invalid token")

    monkeypatch.setattr(routes, "_verify_google_one_tap_credential", reject_credential)

    response = client.post(
        "/auth/google/one-tap",
        json={"credential": "invalid-token", "visitor_id": "visitor-123"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid Google sign-in credential."
    assert redis.hashes == {}


def test_google_one_tap_is_disabled_without_client_configuration(monkeypatch):
    client, routes = make_client()
    monkeypatch.setattr(routes, "GOOGLE_CLIENT_ID", "")

    response = client.post(
        "/auth/google/one-tap",
        json={"credential": "signed-token", "visitor_id": "visitor-123"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Google One Tap is not configured."
