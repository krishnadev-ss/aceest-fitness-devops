"""v3.0.0 release endpoints used by the Kubernetes deployment strategies."""
import sqlite3

import app as app_module
from app import APP_VERSION, create_app


def test_version_endpoint_reports_version_track_and_host(client):
    body = client.get("/version").get_json()
    assert body["service"] == "aceest-fitness"
    assert body["version"] == APP_VERSION
    assert body["track"] == "local"
    assert body["host"]


def test_health_includes_track(client):
    body = client.get("/health").get_json()
    assert body == {"status": "ok", "service": "aceest-fitness",
                    "version": APP_VERSION, "track": "local"}


def test_track_comes_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("DEPLOY_TRACK", "canary")
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "t.db")})
    resp = app.test_client().get("/version")
    assert resp.get_json()["track"] == "canary"
    assert resp.headers["X-Deploy-Track"] == "canary"


def test_every_response_is_tagged_with_release_headers(client):
    for path in ("/", "/health", "/api/programs", "/no-such-page"):
        resp = client.get(path)
        assert resp.headers["X-App-Version"] == APP_VERSION
        assert resp.headers["X-Deploy-Track"] == "local"
        assert resp.headers["X-Served-By"]


def test_dashboard_shows_version_and_track(client):
    html = client.get("/").get_data(as_text=True)
    assert f"v{APP_VERSION}" in html
    assert "local" in html
    assert 'href="/version"' in html


def test_ready_when_database_answers(client):
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ready", "version": APP_VERSION}


def test_not_ready_when_database_fails(client, monkeypatch):
    def broken_connect(*_args, **_kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(app_module.sqlite3, "connect", broken_connect)
    resp = client.get("/ready")
    assert resp.status_code == 503
    assert resp.get_json()["status"] == "unavailable"


def test_version_is_semantic():
    parts = APP_VERSION.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)
