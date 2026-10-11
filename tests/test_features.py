"""Tests for the features ported from baseline v2.2.4 - v3.2.4."""
import random
from datetime import date, timedelta

import pytest

from app import (ValidationError, create_app, generate_plan, membership_info,
                 validate_metrics, validate_workout, PROGRAM_TEMPLATES)


# ---- pure logic ----------------------------------------------------------
def test_validate_workout_defaults_and_exercises():
    workout = validate_workout({
        "workout_type": "strength", "date": "2026-10-01",
        "exercises": [{"name": "Squat", "sets": 5, "reps": 5,
                       "weight_kg": 100}],
    })
    assert workout["workout_type"] == "Strength"
    assert workout["duration_min"] == 60
    assert workout["exercises"][0]["weight_kg"] == 100.0


@pytest.mark.parametrize("payload", [
    {"workout_type": "Yoga"},
    {"workout_type": "Cardio", "duration_min": 0},
    {"workout_type": "Cardio", "date": "01-10-2026"},
    {"workout_type": "Cardio", "exercises": "squats"},
    {"workout_type": "Cardio", "exercises": [{"sets": 3, "reps": 10}]},
    {"workout_type": "Cardio", "exercises": [{"name": "Row", "sets": 0,
                                              "reps": 10}]},
])
def test_validate_workout_rejects_bad_input(payload):
    with pytest.raises(ValidationError):
        validate_workout(payload)


def test_validate_metrics_requires_a_measurement():
    with pytest.raises(ValidationError):
        validate_metrics({"date": "2026-10-01"})
    with pytest.raises(ValidationError):
        validate_metrics({"bodyfat": 120})
    assert validate_metrics({"waist_cm": 80})["waist_cm"] == 80.0


def test_generate_plan_uses_program_templates():
    plan = generate_plan("mg", random.Random(1))
    assert plan in PROGRAM_TEMPLATES["MG"]
    with pytest.raises(ValidationError):
        generate_plan("XX")


def test_membership_info_marks_past_end_dates_expired():
    today = date(2026, 10, 12)
    assert membership_info("Active", "2026-10-22", today) == {
        "status": "Active", "end": "2026-10-22", "days_remaining": 10}
    assert membership_info("Active", "2026-10-01", today)["status"] == "Expired"
    assert membership_info("Paused", None, today)["days_remaining"] is None


# ---- client profile ------------------------------------------------------
def test_create_client_with_profile_fields(client):
    res = client.post("/api/clients", json={
        "name": "Meera", "age": 35, "weight_kg": 70, "program": "FL",
        "height_cm": 165, "target_weight": 62, "target_adherence": 85,
        "membership_end": "2027-01-31"})
    body = res.get_json()
    assert res.status_code == 201
    assert body["height_cm"] == 165 and body["target_adherence"] == 85
    assert body["membership_status"] == "Active"


@pytest.mark.parametrize("extra", [
    {"height_cm": -5}, {"target_adherence": 150},
    {"membership_end": "tomorrow"}, {"membership_status": "Gold"},
])
def test_create_client_rejects_bad_profile_fields(client, extra):
    payload = {"name": "X", "age": 30, "weight_kg": 70, "program": "FL"}
    assert client.post("/api/clients", json={**payload, **extra}).status_code \
        == 400


def test_update_client_recomputes_calories(client, ravi):
    res = client.patch("/api/clients/Ravi",
                       json={"weight_kg": 90, "program": "FL", "height_cm": 180})
    body = res.get_json()
    assert res.status_code == 200
    assert body["calories"] == 1980 and body["height_cm"] == 180


def test_update_missing_client_404(client):
    assert client.patch("/api/clients/Ghost", json={"age": 30}).status_code \
        == 404


# ---- workouts ------------------------------------------------------------
def test_workout_logging_and_history(client, ravi):
    res = client.post("/api/clients/Ravi/workouts", json={
        "workout_type": "Hypertrophy", "date": "2026-10-10",
        "duration_min": 45, "notes": "Leg day",
        "exercises": [{"name": "Squat", "sets": 4, "reps": 8,
                       "weight_kg": 90}]})
    assert res.status_code == 201
    client.post("/api/clients/Ravi/workouts",
                json={"workout_type": "Cardio", "date": "2026-10-11",
                      "duration_min": 30})
    body = client.get("/api/clients/Ravi/workouts").get_json()
    assert [w["workout_type"] for w in body["workouts"]] == \
        ["Cardio", "Hypertrophy"]
    assert body["total_minutes"] == 75
    assert body["workouts"][1]["exercises"][0]["name"] == "Squat"


def test_workout_for_missing_client_404(client):
    res = client.post("/api/clients/Ghost/workouts",
                      json={"workout_type": "Cardio"})
    assert res.status_code == 404


# ---- body metrics --------------------------------------------------------
def test_metrics_and_weight_trend(client, ravi):
    client.post("/api/clients/Ravi/metrics",
                json={"date": "2026-10-01", "weight_kg": 81, "bodyfat": 18})
    client.post("/api/clients/Ravi/metrics",
                json={"date": "2026-10-08", "waist_cm": 84})
    client.post("/api/clients/Ravi/metrics",
                json={"date": "2026-10-15", "weight_kg": 80})
    body = client.get("/api/clients/Ravi/metrics").get_json()
    assert len(body["entries"]) == 3
    assert [p["weight_kg"] for p in body["weight_trend"]] == [81, 80]


def test_metrics_validation_error(client, ravi):
    assert client.post("/api/clients/Ravi/metrics", json={}).status_code == 400


# ---- membership ----------------------------------------------------------
def test_membership_update_and_expiry(client, ravi):
    future = (date.today() + timedelta(days=30)).isoformat()
    res = client.put("/api/clients/Ravi/membership",
                     json={"status": "active", "end": future})
    assert res.get_json()["days_remaining"] == 30
    client.put("/api/clients/Ravi/membership",
               json={"status": "Active", "end": "2020-01-01"})
    assert client.get("/api/clients/Ravi/membership").get_json()["status"] \
        == "Expired"


def test_membership_rejects_unknown_status(client, ravi):
    res = client.put("/api/clients/Ravi/membership", json={"status": "Gold"})
    assert res.status_code == 400


# ---- program generator ---------------------------------------------------
def test_generate_program_is_repeatable_with_seed(client, ravi):
    first = client.post("/api/clients/Ravi/program/generate",
                        json={"seed": 7}).get_json()
    second = client.post("/api/clients/Ravi/program/generate",
                         json={"seed": 7}).get_json()
    assert first["plan"] == second["plan"]
    assert first["plan"] in PROGRAM_TEMPLATES["MG"]
    assert client.get("/api/clients/Ravi").get_json()["plan"] == first["plan"]


def test_generate_program_without_body(client, ravi):
    res = client.post("/api/clients/Ravi/program/generate")
    assert res.status_code == 200 and res.get_json()["plan"]


# ---- report & CSV export -------------------------------------------------
def test_client_report_combines_everything(client, ravi):
    client.patch("/api/clients/Ravi", json={"height_cm": 178,
                                            "target_weight": 75})
    client.post("/api/clients/Ravi/progress", json={"adherence": 80})
    client.post("/api/clients/Ravi/progress", json={"adherence": 90})
    client.post("/api/clients/Ravi/workouts",
                json={"workout_type": "Strength", "duration_min": 50})
    client.post("/api/clients/Ravi/metrics", json={"weight_kg": 79})
    report = client.get("/api/clients/Ravi/report").get_json()
    assert report["program"] == "Muscle Gain"
    assert report["bmi"]["category"] == "Overweight"
    assert report["progress"] == {"weeks_logged": 2, "average_adherence": 85.0}
    assert report["workouts"] == {"sessions": 1, "total_minutes": 50}
    assert report["last_metrics"]["weight_kg"] == 79
    assert report["goals"]["target_weight"] == 75


def test_report_without_optional_data(client, ravi):
    report = client.get("/api/clients/Ravi/report").get_json()
    assert report["bmi"] is None and report["last_metrics"] is None
    assert report["progress"]["average_adherence"] is None


def test_csv_export(client, ravi):
    res = client.get("/api/export/clients.csv")
    lines = res.data.decode().strip().splitlines()
    assert res.mimetype == "text/csv"
    assert lines[0].startswith("name,age,weight_kg") and lines[1].startswith(
        "Ravi,28,80.0,MG,2800")


# ---- users & login -------------------------------------------------------
def test_default_admin_can_log_in(client):
    res = client.post("/api/login", json={"username": "admin",
                                          "password": "admin"})
    assert res.get_json() == {"username": "admin", "role": "Admin"}


def test_login_rejects_wrong_password(client):
    res = client.post("/api/login", json={"username": "admin",
                                          "password": "nope"})
    assert res.status_code == 401


def test_create_user_and_login(client):
    res = client.post("/api/users", json={"username": "coach",
                                          "password": "s3cret",
                                          "role": "trainer"})
    assert res.status_code == 201
    assert client.post("/api/users", json={"username": "coach",
                                           "password": "s3cret"}
                       ).status_code == 409
    login = client.post("/api/login", json={"username": "coach",
                                            "password": "s3cret"})
    assert login.get_json()["role"] == "Trainer"


@pytest.mark.parametrize("payload", [
    {"username": "", "password": "abcd"},
    {"username": "x", "password": "ab"},
    {"username": "x", "password": "abcd", "role": "Owner"},
])
def test_create_user_validation(client, payload):
    assert client.post("/api/users", json=payload).status_code == 400


def test_admin_password_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("ACEEST_ADMIN_PASSWORD", "changeme")
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "e.db")})
    c = app.test_client()
    assert c.post("/api/login", json={"username": "admin",
                                      "password": "changeme"}).status_code == 200


def test_v1_database_is_upgraded_in_place(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE clients (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " name TEXT UNIQUE NOT NULL, age INTEGER NOT NULL,"
        " weight_kg REAL NOT NULL, program TEXT NOT NULL,"
        " calories INTEGER NOT NULL);"
        "INSERT INTO clients (name, age, weight_kg, program, calories)"
        " VALUES ('Old', 40, 75, 'BG', 1950);")
    conn.commit()
    conn.close()
    c = create_app({"TESTING": True, "DATABASE": str(path)}).test_client()
    body = c.get("/api/clients/Old").get_json()
    assert body["membership_status"] == "Active" and body["height_cm"] is None


def test_app_starts_twice_on_same_database(tmp_path):
    """Gunicorn workers each call create_app() on one SQLite file."""
    config = {"TESTING": True, "DATABASE": str(tmp_path / "shared.db")}
    create_app(config)
    second = create_app(config).test_client()
    assert second.post("/api/login", json={"username": "admin",
                                           "password": "admin"}
                       ).status_code == 200
