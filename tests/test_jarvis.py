"""Jarvis, the owner's voice assistant: its own key, its own limits, paper only,
and the owner PIN that keeps owner-only buttons out of its reach."""

from fastapi.testclient import TestClient

from engine.api.app import create_app


def setup(tmp_path):
    client = TestClient(create_app(tmp_path / "test.db", allow_any_client=True, start_engine=False))
    key = client.post("/api/owner/jarvis/key").json()["key"]
    engine = client.app.state.engine
    paper = engine.accounts.all()[0]
    return client, {"X-Jarvis-Key": key}, engine, paper


def order(account_id, qty=1, **extra):
    return {"account_id": account_id, "symbol": "DEMO:ES", "side": "buy", "quantity": qty, "stop_loss": 4990.0} | extra


def test_jarvis_is_shut_out_without_its_key(tmp_path):
    client = TestClient(create_app(tmp_path / "test.db", allow_any_client=True, start_engine=False))
    assert client.get("/api/jarvis/status").status_code == 403
    client.post("/api/owner/jarvis/key")
    assert client.get("/api/jarvis/status", headers={"X-Jarvis-Key": "jv_guess"}).status_code == 403


def test_jarvis_can_read_status_with_its_key(tmp_path):
    client, key, engine, paper = setup(tmp_path)
    body = client.get("/api/jarvis/status", headers=key).json()
    assert {a["name"] for a in body["accounts"]} >= {paper.name}
    assert body["jarvis"]["max_quantity"] == 1.0


def test_a_new_key_replaces_the_old_one(tmp_path):
    client, key, engine, paper = setup(tmp_path)
    client.post("/api/owner/jarvis/key")
    assert client.get("/api/jarvis/status", headers=key).status_code == 403


def test_switching_jarvis_off_closes_the_door(tmp_path):
    client, key, engine, paper = setup(tmp_path)
    client.put("/api/owner/jarvis", json={"enabled": False})
    reply = client.get("/api/jarvis/status", headers=key)
    assert reply.status_code == 403
    assert "switched off" in reply.json()["error"]


def test_jarvis_orders_need_a_stop(tmp_path):
    client, key, engine, paper = setup(tmp_path)
    reply = client.post("/api/jarvis/orders", headers=key, json={"account_id": paper.id, "symbol": "DEMO:ES", "side": "buy", "quantity": 1})
    assert reply.status_code == 422


def test_jarvis_orders_are_capped_per_order_and_per_day(tmp_path):
    client, key, engine, paper = setup(tmp_path)
    reply = client.post("/api/jarvis/orders", headers=key, json=order(paper.id, qty=5))
    assert reply.status_code == 403 and "at most 1" in reply.json()["error"]
    client.put("/api/owner/jarvis", json={"max_orders_per_day": 2})
    client.post("/api/jarvis/orders", headers=key, json=order(paper.id))
    client.post("/api/jarvis/orders", headers=key, json=order(paper.id))
    reply = client.post("/api/jarvis/orders", headers=key, json=order(paper.id))
    assert reply.status_code == 403 and "for today" in reply.json()["error"]


def test_jarvis_orders_go_through_the_risk_guard_labelled_as_jarvis(tmp_path):
    client, key, engine, paper = setup(tmp_path)
    reply = client.post("/api/jarvis/orders", headers=key, json=order(paper.id))
    assert reply.status_code == 200
    assert "decision" in reply.json()            # the guard decided, approve or block
    latest = engine.journal.decisions(limit=1)[0]
    assert latest["source"] == "automation:jarvis"


def test_jarvis_cannot_trade_accounts_it_was_not_allowed(tmp_path):
    client, key, engine, paper = setup(tmp_path)
    other = engine.accounts.all()[1]
    client.put("/api/owner/jarvis", json={"allowed_account_ids": [paper.id]})
    reply = client.post("/api/jarvis/orders", headers=key, json=order(other.id))
    assert reply.status_code == 403 and "isn't allowed" in reply.json()["error"]


def test_jarvis_never_trades_a_live_account(tmp_path):
    client, key, engine, paper = setup(tmp_path)
    live = engine.accounts.create("Broker", broker="bybit", starting_balance=1000.0)
    live.live_enabled = True
    engine.accounts.save(live)
    reply = client.post("/api/jarvis/orders", headers=key, json=order(live.id))
    assert reply.status_code == 403 and "LIVE" in reply.json()["error"]


def test_jarvis_can_always_press_the_kill_switch_but_not_resume(tmp_path):
    client, key, engine, paper = setup(tmp_path)
    client.post("/api/owner/pin", json={"pin": "4826"})
    assert client.post("/api/jarvis/kill-switch", headers=key).status_code == 200
    assert engine.guard.trading_halted
    assert client.post("/api/trading/resume").status_code == 403
    assert engine.guard.trading_halted
    assert client.post("/api/trading/resume", headers={"X-Owner-Pin": "4826"}).status_code == 200
    assert not engine.guard.trading_halted


def test_owner_pin_guards_live_switch_and_jarvis_limits(tmp_path):
    client, key, engine, paper = setup(tmp_path)
    client.post("/api/owner/pin", json={"pin": "4826"})
    live = engine.accounts.create("Broker", broker="bybit", starting_balance=1000.0)
    reply = client.post(f"/api/accounts/{live.id}/enable-live", json={"confirm": "LIVE Broker"})
    assert reply.status_code == 403 and reply.json()["pin_required"]
    assert client.put("/api/owner/jarvis", json={"max_quantity": 50}).status_code == 403
    assert client.post("/api/owner/jarvis/key").status_code == 403
    assert client.post("/api/owner/pin", json={"pin": "0000"}).status_code == 403
    assert client.put("/api/owner/jarvis", headers={"X-Owner-Pin": "4826"}, json={"max_quantity": 2}).status_code == 200


def test_without_a_pin_owner_buttons_work_as_before(tmp_path):
    client, key, engine, paper = setup(tmp_path)
    assert client.post("/api/trading/resume").status_code == 200


def test_pin_locks_after_repeated_wrong_tries(tmp_path):
    client, key, engine, paper = setup(tmp_path)
    client.post("/api/owner/pin", json={"pin": "4826"})
    for _ in range(5):
        client.post("/api/trading/resume", headers={"X-Owner-Pin": "1111"})
    assert client.post("/api/trading/resume", headers={"X-Owner-Pin": "4826"}).status_code == 403


def test_jarvis_can_stop_but_not_unpause_a_runaway_strategy(tmp_path):
    client, key, engine, paper = setup(tmp_path)
    script = next(s for s in engine.scripts.all() if s["kind"] == "strategy")
    run = engine.runner.create(script["id"], paper.id, "DEMO:ES", "1m", None)
    engine.guard.paused_sources.add(engine.runner._source(run))
    reply = client.post(f"/api/jarvis/strategies/{run['id']}/start", headers=key)
    assert reply.status_code == 403 and "Only the owner" in reply.json()["error"]
    assert client.post(f"/api/jarvis/strategies/{run['id']}/stop", headers=key).json()["status"] == "stopped by Jarvis"
