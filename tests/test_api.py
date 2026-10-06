"""Tests for the HTTP endpoints, using Flask's test client."""


# ---- service endpoints ---------------------------------------------------
def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.get_json()["status"] == "ok"


def test_index_page_lists_programs(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"ACEest" in res.data and b"Muscle Gain" in res.data


def test_metrics(client):
    assert client.get("/api/metrics").get_json()["capacity_users"] == 150


def test_unknown_route_returns_json_404(client):
    res = client.get("/nope")
    assert res.status_code == 404 and "error" in res.get_json()


def test_wrong_method_returns_405(client):
    assert client.get("/api/calories").status_code == 405


# ---- programs ------------------------------------------------------------
def test_list_programs(client):
    assert set(client.get("/api/programs").get_json()) == {"FL", "MG", "BG"}


def test_program_detail(client):
    body = client.get("/api/programs/fl").get_json()
    assert body["code"] == "FL" and body["name"] == "Fat Loss"


def test_program_detail_not_found(client):
    assert client.get("/api/programs/XX").status_code == 404


# ---- calculators ---------------------------------------------------------
def test_calories_endpoint(client):
    res = client.post("/api/calories",
                      json={"weight_kg": 70, "program": "FL"})
    assert res.status_code == 200
    assert res.get_json()["calories"] == 1540


def test_calories_rejects_bad_input(client):
    res = client.post("/api/calories",
                      json={"weight_kg": -1, "program": "FL"})
    assert res.status_code == 400 and "weight_kg" in res.get_json()["error"]


def test_calories_rejects_non_json_body(client):
    assert client.post("/api/calories", data="hello").status_code == 400


def test_bmi_endpoint(client):
    res = client.post("/api/bmi", json={"weight_kg": 70, "height_cm": 175})
    assert res.get_json() == {"bmi": 22.9, "category": "Normal"}


# ---- clients -------------------------------------------------------------
def test_create_and_fetch_client(client, ravi):
    body = client.get("/api/clients/Ravi").get_json()
    assert body["program"] == "MG" and body["calories"] == 2800


def test_list_clients_sorted(client, ravi):
    client.post("/api/clients", json={"name": "Asha", "age": 30,
                                      "weight_kg": 60, "program": "FL"})
    names = [c["name"] for c in client.get("/api/clients").get_json()]
    assert names == ["Asha", "Ravi"]


def test_duplicate_client_conflict(client, ravi):
    assert client.post("/api/clients", json=ravi).status_code == 409


def test_create_client_validation_error(client):
    res = client.post("/api/clients", json={"name": "NoAge"})
    assert res.status_code == 400


def test_get_missing_client(client):
    assert client.get("/api/clients/Ghost").status_code == 404


def test_delete_client(client, ravi):
    assert client.delete("/api/clients/Ravi").status_code == 204
    assert client.get("/api/clients/Ravi").status_code == 404
    assert client.delete("/api/clients/Ravi").status_code == 404


# ---- progress ------------------------------------------------------------
def test_progress_flow(client, ravi):
    for week, adherence in (("Week 01", 80), ("Week 02", 95)):
        res = client.post("/api/clients/Ravi/progress",
                          json={"week": week, "adherence": adherence})
        assert res.status_code == 201
    body = client.get("/api/clients/Ravi/progress").get_json()
    assert [e["week"] for e in body["entries"]] == ["Week 01", "Week 02"]
    assert body["average_adherence"] == 87.5


def test_progress_defaults_week_label(client, ravi):
    res = client.post("/api/clients/Ravi/progress", json={"adherence": 70})
    assert res.get_json()["week"].startswith("Week ")


def test_progress_empty_history(client, ravi):
    body = client.get("/api/clients/Ravi/progress").get_json()
    assert body == {"client": "Ravi", "entries": [],
                    "average_adherence": None}


def test_progress_rejects_bad_adherence(client, ravi):
    res = client.post("/api/clients/Ravi/progress", json={"adherence": 150})
    assert res.status_code == 400


def test_progress_for_missing_client(client):
    res = client.post("/api/clients/Ghost/progress", json={"adherence": 50})
    assert res.status_code == 404


def test_deleting_client_removes_progress(client, ravi):
    client.post("/api/clients/Ravi/progress", json={"adherence": 90})
    client.delete("/api/clients/Ravi")
    client.post("/api/clients", json=ravi)
    body = client.get("/api/clients/Ravi/progress").get_json()
    assert body["entries"] == []
