"""The TJR Boot Camp strategy and chart view: the building blocks follow the write-up's rules."""

import asyncio
from pathlib import Path

import pytest

from engine.core.markets import MarketCatalog
from engine.data.demo import demo_candles
from engine.scripting import library
from engine.scripting.host import ScriptHost
from engine.scripting.sandbox import make_namespace
from engine.scripting.worker_jobs import Inputs

EXAMPLES = Path(__file__).resolve().parent.parent / "scripts" / "examples"
STRATEGY = (EXAMPLES / "tjr_bootcamp_strategy.py").read_text()
CHART = (EXAMPLES / "tjr_bootcamp_chart.py").read_text()
MARKET = MarketCatalog().get("DEMO:ES")
START = 1_767_225_600  # 2026-01-01 00:00 UTC
CANDLES = demo_candles("ES", "5m", START, START + 86400 * 20, MARKET.extra, MARKET.tick_size)


def script(code=STRATEGY):
    namespace = make_namespace(library)
    exec(code, namespace)
    namespace["inputs"] = Inputs(namespace["inputs"])
    return namespace


def feed(structure, candles, start=0, step=300):
    for i, (o, h, l, c) in enumerate(candles):
        structure.add(start + i * step, o, h, l, c)


@pytest.fixture(scope="module")
def host():
    host = ScriptHost(MarketCatalog())
    yield host
    host.close()


def test_strategy_backtests_in_the_sandbox(host):
    result = asyncio.run(host.backtest(STRATEGY, CANDLES, "DEMO:ES", "5m", 25000))
    assert result["ok"], result.get("error")
    report = result["report"]
    assert report["script"]["type"] == "strategy"
    for trade in report["trades"]:
        assert trade["quantity"] > 0


def test_chart_view_draws_one_value_per_candle(host):
    result = asyncio.run(host.indicator(CHART, CANDLES, "DEMO:ES", "5m"))
    assert result["ok"], result.get("error")
    names = {p["name"] for p in result["plots"]}
    assert {"5m swing high", "5m swing low", "Daily trend", "Trading window"} <= names
    for plot in result["plots"]:
        assert len(plot["values"]) == len(CANDLES)
    window = next(p for p in result["plots"] if p["name"] == "Trading window")["values"]
    assert 0 < sum(window) < len(window)


def test_new_york_time_follows_daylight_saving():
    ns = script()
    winter = 1_767_277_800  # 2026-01-01 14:30 UTC = 09:30 New York (EST)
    summer = 1_782_394_200  # 2026-06-25 13:30 UTC = 09:30 New York (EDT)
    for moment in (winter, summer):
        assert (ns["ny_time"](moment) % 86400) // 60 == 9 * 60 + 30


def test_swing_is_up_candle_then_down_candle_at_the_higher_wick():
    ns = script()
    s = ns["Structure"](300, 300)
    feed(s, [(100, 103, 99, 102), (102, 105, 100, 101)])
    assert s.swing_high[0] == 105
    feed(s, [(101, 102, 97, 98), (98, 101, 96, 100)], start=600)
    assert s.swing_low[0] == 96


def test_a_wick_through_is_not_a_break_but_a_body_close_is():
    ns = script()
    s = ns["Structure"](300, 300)
    # Up then down makes a swing high at 105, down then up makes a swing low at 96.
    feed(s, [(100, 103, 99, 102), (102, 105, 100, 101), (101, 102, 97, 98), (98, 101, 96, 100)])
    feed(s, [(100, 107, 99, 106)], start=1200)          # closes above 105: first break sets an uptrend
    assert s.trend == 1
    feed(s, [(106, 106.5, 95, 97.5)], start=1500)      # wicks under the 96 low but closes above it
    assert s.trend == 1
    feed(s, [(97.5, 98, 94, 95)], start=1800)          # body closes under 96: break of structure down
    assert s.trend == -1
    assert s.ob is not None and s.ob[0] == -1


def test_fair_value_gap_needs_wicks_that_do_not_overlap():
    ns = script()
    s = ns["Structure"](300, 300)
    feed(s, [(100, 101, 99, 100.5), (100.5, 106, 100.5, 105.5), (105.5, 107, 102, 106)])
    assert [g[:3] for g in s.fvgs] == [[1, 101, 102]]
    t = ns["Structure"](300, 300)
    feed(t, [(100, 103, 99, 100.5), (100.5, 106, 100.5, 105.5), (105.5, 107, 102, 106)])
    assert t.fvgs == []


def test_higher_timeframe_candles_are_built_from_five_minute_ones():
    ns = script()
    hour = ns["Structure"](3600, 300)
    for i in range(12):
        hour.add(START + i * 300, 100 + i, 101 + i, 99 + i, 100.5 + i)
    assert len(hour.bars) == 1
    t, o, h, l, c, _ = hour.bars[0]
    assert (o, h, l, c) == (100, 112, 99, 111.5)


def test_half_comes_off_at_the_first_target_with_stop_to_break_even():
    ns = script()
    ns["_reset"](300)
    ns["_state"]["trade"] = {"direction": 1, "stop": 95, "tp1": 110, "final": 130, "quantity": 4, "risk": 5, "partial_done": False}
    library._outputs = library.Outputs()
    moment = 1_767_281_400  # 10:30 New York
    data = library.Data([moment - 300, moment], [100, 105], [106, 111], [99, 104], [105, 109], [1, 1])
    ns["_manage"](data, library.PositionView(4, 100))
    assert library._outputs.signals == [{"action": "sell", "quantity": 2.0, "stop": 100.0, "target": None, "limit": None}]


def test_position_closes_before_the_session_ends():
    ns = script()
    ns["_reset"](300)
    library._outputs = library.Outputs()
    moment = 1_767_301_200  # 16:00 New York
    data = library.Data([moment - 300, moment], [100, 100], [101, 101], [99, 99], [100, 100], [1, 1])
    ns["_manage"](data, library.PositionView(1, 100))
    assert library._outputs.signals == [{"action": "close"}]


def test_size_comes_from_risk_dollars_and_stop_distance():
    ns = script()
    ns["inputs"] = Inputs({**ns["inputs"], "risk_dollars": 250, "point_value": 50, "quantity_step": 1})
    assert ns["_size"](2.0) == 2      # 250 / (2 points x 50) = 2.5, rounded down
    assert ns["_size"](10.0) == 0     # too wide for the risk: no trade


def test_new_examples_reach_an_existing_install(tmp_path):
    from engine.scripting.store import ScriptStore
    from engine.storage import database

    db = tmp_path / "app.db"
    database.initialize(db)
    store = ScriptStore(db)
    store.save(None, "My own script", "def calculate(data):\n    pass\n", script_id="mine")
    store.save(None, "Edited", "# my edit\ndef calculate(data):\n    pass\n", script_id="example_sma_ribbon")
    store.seed_examples()
    ids = {row["id"] for row in store.all()}
    assert {"mine", "example_tjr_bootcamp_strategy", "example_tjr_bootcamp_chart"} <= ids
    assert store.get("example_sma_ribbon")["code"].startswith("# my edit")
