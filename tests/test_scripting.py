"""The script engine: example scripts, plain English errors, and the sandbox limits."""

import asyncio
import time
from pathlib import Path

import pytest

from engine.core.markets import MarketCatalog
from engine.data.demo import demo_candles
from engine.scripting.host import ScriptHost

EXAMPLES = Path(__file__).resolve().parent.parent / "scripts" / "examples"
MARKET = MarketCatalog().get("DEMO:ES")
CANDLES = demo_candles("ES", "5m", 1_700_000_000, 1_700_000_000 + 300 * 600, MARKET.extra, MARKET.tick_size)


@pytest.fixture(scope="module")
def host():
    host = ScriptHost(MarketCatalog())
    yield host
    host.close()


def run(coroutine):
    return asyncio.run(coroutine)


def test_example_indicators_draw_on_the_chart(host):
    for name in ("volume_indicator.py", "sma_ribbon.py"):
        result = run(host.indicator((EXAMPLES / name).read_text(), CANDLES, "DEMO:ES", "5m"))
        assert result["ok"], result.get("error")
        assert result["plots"]
        for plot in result["plots"]:
            assert len(plot["values"]) == len(CANDLES)


def test_example_strategies_produce_backtest_reports(host):
    for name in ("ma_crossover.py", "rsi_strategy.py"):
        result = run(host.backtest((EXAMPLES / name).read_text(), CANDLES, "DEMO:ES", "5m", 25000))
        assert result["ok"], result.get("error")
        report = result["report"]
        for key in ("net_profit", "win_rate", "max_drawdown", "average_win", "average_loss", "equity_curve"):
            assert key in report
        assert report["total_trades"] > 0


def test_syntax_error_names_the_line_in_plain_english(host):
    code = "def calculate(data):\n    plot('x', sma(data.close, 5)\n"
    result = run(host.indicator(code, CANDLES, "DEMO:ES", "5m"))
    assert not result["ok"]
    assert result["error"]["message"].startswith("Line 2")
    assert "bracket" in result["error"]["message"]


def test_misspelled_name_suggests_the_right_one(host):
    code = "def calculate(data):\n    x = 1\n    plot('x', smaa(data.close, 5))\n"
    result = run(host.indicator(code, CANDLES, "DEMO:ES", "5m"))
    assert result["error"]["line"] == 3
    assert "Did you mean 'sma'" in result["error"]["message"]


def test_endless_loop_is_stopped_after_2_seconds_and_the_next_script_still_runs(host):
    started = time.monotonic()
    result = run(host.indicator("def calculate(data):\n    while True:\n        pass\n", CANDLES, "DEMO:ES", "5m"))
    elapsed = time.monotonic() - started
    assert not result["ok"]
    assert "longer than 2 seconds" in result["error"]["message"]
    assert elapsed < 4
    ok = run(host.indicator((EXAMPLES / "volume_indicator.py").read_text(), CANDLES, "DEMO:ES", "5m"))
    assert ok["ok"]


def test_scripts_cannot_touch_files_or_the_network(host):
    for code in (
        "def calculate(data):\n    open('secret.txt').read()\n",
        "import os\ndef calculate(data):\n    pass\n",
        "import socket\ndef calculate(data):\n    pass\n",
    ):
        result = run(host.indicator(code, CANDLES, "DEMO:ES", "5m"))
        assert not result["ok"], code


def test_backtest_cannot_peek_ahead(host):
    # A strategy that tries to look at the "next" candle only ever sees the last finished one.
    code = (
        "lookback = 50\n"
        "def on_bar(data, position):\n"
        "    if len(data.close) > 1 and data.time[-1] < data.time[-2]:\n"
        "        raise ValueError('saw the future')\n"
    )
    result = run(host.backtest(code, CANDLES, "DEMO:ES", "5m", 25000))
    assert result["ok"], result.get("error")
