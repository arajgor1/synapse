"""Smoke tests for the starter app — should pass before any agent runs."""
from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal, init_db
from app.models import User, Subscription


def setup_module():
    init_db()
    db = SessionLocal()
    if not db.query(User).filter(User.email == "alice@example.com").first():
        db.add(User(email="alice@example.com", is_admin=0))
        db.add(User(email="admin@example.com", is_admin=1))
        db.commit()
    db.close()


def test_health():
    client = TestClient(app)
    assert client.get("/health").status_code == 200


def test_create_and_list_subscription():
    client = TestClient(app)
    r = client.post(
        "/subscriptions/",
        json={"plan": "pro", "seats": 2},
        headers={"Authorization": "Bearer user:1"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["plan"] == "pro"
    assert data["seats"] == 2

    r2 = client.get("/subscriptions/", headers={"Authorization": "Bearer user:1"})
    assert r2.status_code == 200
    assert any(s["id"] == data["id"] for s in r2.json())
