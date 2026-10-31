import asyncio

from engine.core.markets import MarketCatalog
from engine.data.demo import demo_candles
from engine.scripting.host import ScriptHost
from engine.scripting.pine import convert_pine

PINE = """//@version=5
indicator("My MA", overlay=true)
length = input.int(20, "Length")
fast = ta.sma(close, length)
slow = ta.ema(close, 50)
plot(fast, "Fast", color=color.blue)
plot(slow, title="Slow", color=color.red)
"""


def test_simple_pine_indicator_converts_and_runs():
    result = convert_pine(PINE)
    assert result["warnings"] == []
    assert 'name = "My MA"' in result["code"]
    assert "sma(data.close, inputs.length)" in result["code"]
    market = MarketCatalog().get("DEMO:ES")
    candles = demo_candles("ES", "5m", 1_700_000_000, 1_700_000_000 + 300 * 200, market.extra, market.tick_size)
    host = ScriptHost(MarketCatalog())
    try:
        run = asyncio.run(host.indicator(result["code"], candles, "DEMO:ES", "5m"))
    finally:
        host.close()
    assert run["ok"], run.get("error")
    assert [p["name"] for p in run["plots"]] == ["Fast", "Slow"]


def test_unknown_lines_are_kept_and_warned():
    result = convert_pine('indicator("X")\nif close > open\n    label.new(bar_index, high, "hi")\n')
    assert result["warnings"]
    assert "TODO" in result["code"]
