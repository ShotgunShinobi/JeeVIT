"""
Tests for FastAPI webhook and inspection endpoints.
"""

from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)


def test_api_health():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "counts" in data


def test_api_webhook_lead():
    payload = {
        "id": "WEBHOOK-01",
        "name": "Sarah Connor",
        "email": "sarah@cyberdyne.org",
        "company": "Cyberdyne Systems",
        "message": "We need help automating our defense network this week. Budget is approved £50k.",
    }
    response = client.post("/webhook/lead", json=payload)
    assert response.status_code == 200
    res = response.json()
    assert res["status"] == "created"
    assert res["lead_id"].startswith("L-")


def test_api_get_leads():
    response = client.get("/leads")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_api_get_duplicates():
    response = client.get("/duplicates")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_api_get_errors():
    response = client.get("/errors")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_api_export():
    response = client.get("/export")
    assert response.status_code == 200
    assert "text/csv" in response.headers.get("content-type", "")
