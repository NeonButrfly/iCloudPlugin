from fastapi.testclient import TestClient

from icloud_index_service.main import app


def test_health_endpoint_reports_ok():
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
