def test_health_round_trips_db_and_renders_page(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert "GripTrack" in response.text
    assert "ok" in response.text
