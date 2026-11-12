from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_calculate_shift_endpoint():
    payload = {
        "worker_id": "W001",
        "shifts": [
            {
                "shift_id": "SHIFT001",
                "employer_name": "ABC Supermarket",
                "shift_date": "2026-11-09",
                "start_time": "09:00",
                "end_time": "17:00",
                "break_minutes": 0,
                "hourly_rate": 25,
                "currency": "ZMW",
                "location": "Lusaka",
                "confirmation_status": "confirmed"
            }
        ]
    }

    response = client.post(
        "/api/v1/shifts/calculate",
        json=payload
    )

    assert response.status_code == 200

    result = response.json()

    assert result["worker_id"] == "W001"
    assert result["shifts"][0]["shift_id"] == "SHIFT001"
    assert result["shifts"][0]["paid_hours"] == 8.0
    assert result["shifts"][0]["gross_earnings"] == 200.0
    assert result["shifts"][0]["eligible_for_earnings"] is True


def test_calculate_shift_rejects_missing_worker_id():
    payload = {
        "shifts": []
    }

    response = client.post(
        "/api/v1/shifts/calculate",
        json=payload
    )

    assert response.status_code == 422
