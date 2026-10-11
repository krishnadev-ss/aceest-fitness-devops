"""Tests for the HTML dashboard and client pages."""
from app import line_chart


def test_line_chart_layout():
    chart = line_chart(["W1", "W2", "W3"], [50, 75, 100], 0, 100, target=80)
    assert len(chart["dots"]) == 3
    assert chart["dots"][0][1] > chart["dots"][2][1]  # higher value = higher up
    assert chart["target"] is not None and len(chart["grid"]) == 3
    assert line_chart([], [], 0, 100) is None


def test_line_chart_single_point_and_flat_range():
    chart = line_chart(["W1"], [70], 70, 70)
    assert chart["points"].count(",") == 1


def test_dashboard_empty_state(client):
    page = client.get("/").get_data(as_text=True)
    assert "No clients yet" in page and "Muscle Gain" in page


def test_dashboard_lists_clients_with_membership(client, ravi):
    client.patch("/api/clients/Ravi", json={"height_cm": 178})
    client.post("/api/clients/Ravi/progress", json={"adherence": 90})
    page = client.get("/").get_data(as_text=True)
    assert 'href="/clients/Ravi"' in page
    assert "25.2" in page and "badge Active" in page and "90%" in page


def test_client_page_shows_everything(client, ravi):
    client.patch("/api/clients/Ravi", json={
        "height_cm": 178, "target_weight": 75, "target_adherence": 85,
        "membership_end": "2099-01-01"})
    for value in (80, 88):
        client.post("/api/clients/Ravi/progress", json={"adherence": value})
    client.post("/api/clients/Ravi/metrics",
                json={"date": "2026-10-01", "weight_kg": 81})
    client.post("/api/clients/Ravi/metrics",
                json={"date": "2026-10-08", "weight_kg": 79.5, "waist_cm": 84})
    client.post("/api/clients/Ravi/workouts", json={
        "workout_type": "Strength", "duration_min": 50, "notes": "PR day",
        "exercises": [{"name": "Squat", "sets": 5, "reps": 5,
                       "weight_kg": 100}]})
    client.post("/api/clients/Ravi/program/generate", json={"seed": 1})
    res = client.get("/clients/Ravi")
    page = res.get_data(as_text=True)
    assert res.status_code == 200
    assert page.count("<polyline") == 2
    assert "Squat 5x5 @ 100.0 kg" in page and "PR day" in page
    assert "Overweight" in page and "days left" in page


def test_client_page_without_data_shows_empty_states(client, ravi):
    page = client.get("/clients/Ravi").get_data(as_text=True)
    assert "No weeks logged yet" in page and "No weight entries yet" in page
    assert "No workouts logged yet" in page and "No body metrics yet" in page


def test_client_page_missing_client(client):
    res = client.get("/clients/Ghost")
    assert res.status_code == 404 and "not found" in res.get_data(as_text=True)
