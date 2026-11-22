"""Post-deployment smoke tests.

Run against a live deployment (inside the cluster as a Kubernetes Job, or
from the build agent):

    BASE_URL=http://aceest-rolling.aceest.svc pytest smoke -v

EXPECTED_VERSION (optional) asserts that the new release is the one serving.
Skipped entirely when BASE_URL is not set, so the unit-test run ignores them.
"""
import json
import os
import time
import urllib.error
import urllib.request

import pytest

BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")
EXPECTED_VERSION = os.environ.get("EXPECTED_VERSION", "")

pytestmark = pytest.mark.skipif(not BASE_URL, reason="BASE_URL not set")


def call(path, data=None, method=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        BASE_URL + path, data=body, method=method,
        headers={"Content-Type": "application/json"} if body else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.headers, resp.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, err.headers, err.read().decode()


@pytest.fixture(scope="module", autouse=True)
def wait_until_up():
    for _ in range(30):
        try:
            if call("/health")[0] == 200:
                return
        except OSError:
            pass
        time.sleep(2)
    pytest.fail(f"{BASE_URL} did not become healthy")


def test_health():
    status, _, body = call("/health")
    assert status == 200
    assert json.loads(body)["status"] == "ok"


def test_expected_version_is_serving():
    status, headers, body = call("/version")
    assert status == 200
    if EXPECTED_VERSION:
        assert json.loads(body)["version"] == EXPECTED_VERSION


def test_dashboard_renders():
    status, _, body = call("/")
    assert status == 200
    assert "ACEest" in body


def test_programs_api():
    status, _, body = call("/api/programs")
    assert status == 200
    assert {"FL", "MG", "BG"} <= set(json.loads(body))


def test_calorie_calculation():
    status, _, body = call("/api/calories",
                           {"program": "FL", "weight_kg": 70})
    assert status == 200
    assert json.loads(body)["calories"] == 70 * 22


def test_unknown_route_is_json_404():
    status, _, body = call("/definitely-not-here")
    assert status == 404
    assert "error" in json.loads(body)
