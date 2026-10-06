import pytest

from app import create_app


@pytest.fixture
def app(tmp_path):
    """Fresh app with an isolated SQLite file for every test."""
    return create_app({"TESTING": True,
                       "DATABASE": str(tmp_path / "test.db")})


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def ravi(client):
    """A client that already exists in the database."""
    payload = {"name": "Ravi", "age": 28, "weight_kg": 80, "program": "MG"}
    assert client.post("/api/clients", json=payload).status_code == 201
    return payload
