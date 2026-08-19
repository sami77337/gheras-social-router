from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_is_deterministic(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "gheras-social-router",
        "environment": "test",
    }
