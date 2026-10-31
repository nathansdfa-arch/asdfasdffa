from fastapi.testclient import TestClient

from engine import __version__
from engine.api.app import create_app


def make_client(tmp_path, allow_any_client=True):
    return TestClient(create_app(tmp_path / "test.db", allow_any_client=allow_any_client))


def test_health_reports_ok(tmp_path):
    reply = make_client(tmp_path).get("/api/health")
    assert reply.status_code == 200
    assert reply.json()["status"] == "ok"
    assert reply.json()["version"] == __version__


def test_settings_can_be_changed_through_the_api(tmp_path):
    client = make_client(tmp_path)
    assert client.put("/api/settings/glow_strength", json={"value": 20}).status_code == 200
    assert client.get("/api/settings").json()["glow_strength"]["value"] == 20


def test_bad_setting_gets_a_plain_english_error(tmp_path):
    reply = make_client(tmp_path).put("/api/settings/glow_strength", json={"value": 500})
    assert reply.status_code == 400
    assert "0 (off) to 100" in reply.json()["error"]


def test_connections_from_other_computers_are_refused(tmp_path):
    # The test client pretends to be a computer called "testclient", not this computer.
    client = make_client(tmp_path, allow_any_client=False)
    reply = client.get("/api/health")
    assert reply.status_code == 403
    assert "Remote access is switched off" in reply.json()["error"]


def test_the_screen_is_served(tmp_path):
    reply = make_client(tmp_path).get("/")
    assert reply.status_code == 200
    assert "Trading App" in reply.text
