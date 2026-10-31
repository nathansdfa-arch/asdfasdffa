"""Phase 9 "done when": an automation triggers on a scheduled time, and the kill
switch stops it along with all orders and positions."""

import asyncio

from engine.core.clock import FakeClock
from engine.core.models import Tick
from engine.runtime import Engine

# Wednesday 4 March 2026, 14:20 UTC = 09:20 in New York.
START = 1772634000.0

BUYER = '''
name = "Scheduled buyer"
schedule = "09:25 America/New_York"

def run(event):
    alert("Buying at the scheduled time")
    buy(1, stop=5800, target=5900)
'''


def test_scheduled_automation_runs_and_kill_switch_stops_everything(tmp_path):
    clock = FakeClock(START)
    engine = Engine(tmp_path / "test.db", clock=clock.now, providers={})
    paper = next(a for a in engine.accounts.all() if a.name == "Paper 25K")
    engine.data.on_tick("DEMO", Tick(symbol="ES", price=5850.0, time=clock.now()))

    script = engine.scripts.save(None, "Scheduled buyer", BUYER)
    run = engine.runner.create(script["id"], paper.id, "DEMO:ES", None, None)
    engine.runner.start(run["id"])

    async def scenario():
        engine.runner._loop = asyncio.get_running_loop()
        assert engine.runner.due_automations(clock.now()) == []          # 09:20: not yet
        clock.advance(5 * 60)                                             # 09:25
        engine.data.on_tick("DEMO", Tick(symbol="ES", price=5850.0, time=clock.now()))
        due = engine.runner.due_automations(clock.now())
        assert due == [run["id"]]
        outcomes = await engine.runner.run_automation(run["id"], {"type": "schedule"})
        assert outcomes and outcomes[0]["ok"], outcomes
        assert engine.runner.due_automations(clock.now() + 60) == []     # once a day only

        position = engine.paper.position(paper.id, "DEMO:ES")
        assert position.quantity == 1
        assert engine.paper.working_orders(paper.id)                      # its stop and target

        report = await engine.kill_switch.trigger("test")
        assert report["ok"], report
        return report

    asyncio.run(scenario())
    assert engine.runner.all()[0]["active"] is False
    assert engine.paper.position(paper.id, "DEMO:ES").quantity == 0
    assert engine.paper.working_orders(paper.id) == []
    assert engine.guard.trading_halted
