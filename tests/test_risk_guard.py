"""Risk guard tests. The first six are the bible's section 13 tests that must
pass before phase 6 is approved; the rest cover each of the eight rules."""

import asyncio

import pytest

from engine.core.models import OrderRequest, OrderType, Side
from engine.execution.broker import OrderRefused
from tests.trading_harness import Harness, prop_rules

ES = "DEMO:ES"   # $50 per point, 0.25 tick, 1 tick slippage, $2.50 fee per side


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


# ---------------------------------------------------------------------------
# Bible section 13: the six required guard tests
# ---------------------------------------------------------------------------

def test_connector_without_guard_stamp_refuses_the_order(h):
    account = h.account()
    h.price(ES, 5800)
    request = OrderRequest(account_id=account.id, symbol=ES, side=Side.BUY, quantity=1)
    with pytest.raises(OrderRefused):
        h.broker.place_order(request, None)
    with pytest.raises(OrderRefused):
        h.broker.place_order(request, "forged:9999999999:abc")
    assert h.broker.positions(account.id) == []


def test_at_100_percent_used_closing_and_tightening_still_go_through(h):
    # The usual way to reach 100%: a trailing floor rises during a winning trade,
    # then price falls back. Floor-move rules make this the real prop firm trap.
    account = h.account(**prop_rules(drawdown_lock=None, safety_buffer=100))
    h.price(ES, 5800)
    assert not h.order(account, stop=5780)["ok"]       # 20 points x $50 = $1,000 + costs: too big
    h.clock.advance(5)
    result = h.order(account, stop=5790)                # ~$530 worst case
    assert result["ok"], result["message"]
    h.price(ES, 5815)                                   # equity ~25,735: floor rises to ~24,735
    h.price(ES, 5796)                                   # equity ~24,785: below the guard's floor (floor + 100)
    numbers = h.guard.numbers(account)
    assert numbers["used"] >= 1.0
    assert not numbers["failed"]
    # New risk is blocked...
    h.clock.advance(5)
    h.prices["DEMO:NQ"] = 20500
    blocked = h.order(account, symbol="DEMO:NQ", stop=20495)
    assert not blocked["ok"]
    assert "Rule 6" in blocked["decision"]["rule"]
    # ...but tightening the stop and closing still go through.
    tighten = h.orders.move_stop(account.id, ES, 5792)
    assert tighten["ok"], tighten["message"]
    close = h.orders.close_position(account.id, ES)
    assert close["ok"], close["message"]
    assert h.broker.positions(account.id) == []


def test_new_order_blocked_when_feed_stops_for_10_seconds(h):
    account = h.account()
    h.price(ES, 5800)
    h.feeds[ES] = "stale"          # what the data service reports after 5+ quiet seconds
    h.clock.advance(10)
    result = h.order(account, stop=5790)
    assert not result["ok"]
    assert "Rule 3" in result["decision"]["rule"]


def test_bible_trailing_example_reproduces_the_same_floor_at_every_step(h):
    account = h.account(**prop_rules())
    h.price(ES, 5800)
    assert h.guard.numbers(account)["floor"] == 24000
    assert h.order(account, qty=1, stop=5790)["ok"]
    fees = 2.5
    entry = 5800.25                                  # one tick slippage
    # Move price so equity peaks at 25,600 (including the entry fee).
    peak = entry + (600 + fees) / 50
    h.price(ES, peak)
    assert h.guard.numbers(account)["floor"] == pytest.approx(24600)
    # Price comes back so equity is 25,300; the floor stays and room left is 700.
    back = entry + (300 + fees) / 50
    h.price(ES, back)
    numbers = h.guard.numbers(account)
    assert numbers["floor"] == pytest.approx(24600)
    assert numbers["room_left"] == pytest.approx(700)
    assert numbers["guard_floor"] == pytest.approx(24700)
    # Equity peaks at 26,000: the floor reaches 25,000 and locks.
    h.price(ES, entry + (1000 + fees) / 50)
    numbers = h.guard.numbers(account)
    assert numbers["floor"] == pytest.approx(25000)
    assert numbers["floor_locked"]


def test_end_of_day_profile_fails_account_on_mid_day_touch(h):
    account = h.account(**prop_rules(drawdown_method="end_of_day", safety_buffer=0, auto_flatten_at_limit=True))
    h.price(ES, 5800)
    assert h.order(account, qty=2, stop=5791)["ok"]   # $900 worst case + costs fits under the 1,000 room
    # Price drops so equity touches the 24,000 floor mid-day; the stop at 5791 hasn't been hit yet
    # because we jump straight past it in one move (a gap).
    h.prices[ES] = 5789
    h.guard.on_price(ES)              # guard sees equity before the broker processes the stop
    state = h.guard.state(account)
    assert state.failed
    assert any(t == "alert" and "failed" in m["message"] for t, m in h.events)


def test_kill_switch_leaves_zero_positions_and_orders(h):
    a1 = h.account("One")
    a2 = h.account("Two")
    h.price(ES, 5800)
    h.price("DEMO:EURUSD", 1.085)
    assert h.order(a1, stop=5790, target=5820)["ok"]
    assert h.order(a2, symbol="DEMO:EURUSD", side="sell", qty=0.1, stop=1.09)["ok"]
    h.clock.advance(3)
    assert h.order(a1, kind="limit", price=5790, stop=5780)["ok"]
    report = asyncio.run(h.kill.trigger())
    assert report["ok"], report
    for account in (a1, a2):
        assert h.broker.positions(account.id) == []
        assert h.broker.working_orders(account.id) == []
    # Trading stays halted until switched back on.
    h.clock.advance(5)
    assert not h.order(a1, stop=5790)["ok"]
    h.kill.resume()
    h.clock.advance(5)
    assert h.order(a1, stop=5790)["ok"]


# ---------------------------------------------------------------------------
# Each rule in more detail
# ---------------------------------------------------------------------------

def test_rule1_stamp_is_single_use_and_specific(h):
    account = h.account()
    h.price(ES, 5800)
    request = OrderRequest(account_id=account.id, symbol=ES, side=Side.BUY, quantity=1)
    decision = h.guard.review_order(request)
    assert decision.approved
    bigger = OrderRequest(account_id=account.id, symbol=ES, side=Side.BUY, quantity=5)
    with pytest.raises(OrderRefused):
        h.broker.place_order(bigger, decision.stamp)      # stamp is for 1 contract only
    h.broker.place_order(request, decision.stamp)
    with pytest.raises(OrderRefused):
        h.broker.place_order(request, decision.stamp)     # and only once


def test_rule1_stamp_expires(h):
    account = h.account()
    h.price(ES, 5800)
    request = OrderRequest(account_id=account.id, symbol=ES, side=Side.BUY, quantity=1)
    decision = h.guard.review_order(request)
    h.clock.advance(11)
    with pytest.raises(OrderRefused):
        h.broker.place_order(request, decision.stamp)


def test_rule2_moving_stop_further_away_is_checked(h):
    account = h.account(**prop_rules(safety_buffer=0))
    h.price(ES, 5800)
    assert h.order(account, stop=5790)["ok"]
    result = h.orders.move_stop(account.id, ES, 5770)      # 30 points = $1,500 risk > room
    assert not result["ok"]
    result = h.orders.move_stop(account.id, ES, 5795)      # tighter: always fine
    assert result["ok"]


def test_rule2_stop_loss_cannot_be_cancelled_while_position_open(h):
    account = h.account()
    h.price(ES, 5800)
    h.order(account, stop=5790)
    stop = next(o for o in h.broker.working_orders(account.id) if o.role == "stop_loss")
    assert not h.orders.cancel(account.id, stop.id)["ok"]


def test_rule3_unconfirmed_prop_profile_blocks(h):
    account = h.account(**prop_rules())
    h.guard.profile_problem = lambda acc: "The firm's numbers haven't been confirmed yet."
    h.price(ES, 5800)
    result = h.order(account, stop=5790)
    assert not result["ok"]
    assert "confirmed" in result["message"]


def test_rule3_no_price_blocks(h):
    account = h.account()
    result = h.order(account, stop=5790)
    assert not result["ok"]


def test_rule3_guard_crash_blocks(h):
    account = h.account()
    h.price(ES, 5800)
    h.guard.numbers = lambda acc: 1 / 0
    result = h.order(account, stop=5790)
    assert not result["ok"]
    assert "fail closed" in result["decision"]["rule"]


def test_rule4_prop_orders_need_a_stop(h):
    account = h.account(**prop_rules())
    h.price(ES, 5800)
    result = h.order(account)
    assert not result["ok"]
    assert "stop loss" in result["message"]


def test_rule4_worst_case_blocks_oversized_risk(h):
    account = h.account(**prop_rules())
    h.price(ES, 5800)
    # 18 points x $50 = $900 + slippage $25 + fees $5 = $930 > 900 room (1,000 - 100 buffer)
    result = h.order(account, stop=5782)
    assert not result["ok"]
    assert "Rule 4" in result["decision"]["rule"]
    h.clock.advance(5)
    assert h.order(account, stop=5785)["ok"]   # 15 points = $750 + costs fits


def test_rule4_counts_existing_positions(h):
    account = h.account(**prop_rules())
    h.price(ES, 5800)
    assert h.order(account, stop=5790)["ok"]          # ~$530 worst case
    h.clock.advance(5)
    result = h.order(account, symbol="DEMO:NQ", stop=None)
    assert not result["ok"]
    h.price("DEMO:NQ", 20500)
    result = h.order(account, symbol="DEMO:NQ", stop=20480)   # 20 pts x $20 = $400 more: over the room
    assert not result["ok"]


def test_rule4_stop_on_wrong_side_is_refused(h):
    account = h.account()
    h.price(ES, 5800)
    result = h.order(account, stop=5810)
    assert not result["ok"]


def test_rule5_buffer_tightens_the_daily_limit(h):
    account = h.account(max_daily_loss=500, safety_buffer=200)
    h.price(ES, 5800)
    # 6 points = $300 + costs ~$330 > 300 guard limit (500 - 200 buffer)
    assert not h.order(account, stop=5794)["ok"]
    h.clock.advance(5)
    assert h.order(account, stop=5795)["ok"]          # 5 points = $250 + costs fits


def test_rule6_warning_at_70_percent_and_auto_flatten_at_100(h):
    account = h.account(max_daily_loss=1000, safety_buffer=0, auto_flatten_at_limit=True)
    h.price(ES, 5800)
    assert h.order(account, stop=5781)["ok"]           # $950 + $30 costs fits in $1,000
    h.price(ES, 5786)              # ~ -$715
    assert any(t == "alert" and m["level"] == "warning" for t, m in h.events)
    h.prices[ES] = 5780.25         # ~ -$1,002 in a gap, before the stop fills
    h.guard.on_price(ES)
    state = h.guard.state(account)
    assert state.limit_hit and state.halted
    assert h.broker.positions(account.id) == []


def test_rule7_broker_without_real_stops_gets_no_orders(h):
    account = h.account()
    h.price(ES, 5800)
    h.broker.supports_broker_stops = False
    assert not h.order(account, stop=5790)["ok"]


def test_rule8_balance_mismatch_blocks_new_risk(h):
    account = h.account()
    h.price(ES, 5800)
    h.broker.books[account.id].balance -= 250          # broker says something different
    h.guard.reconcile_balances()
    assert not h.order(account, stop=5790)["ok"]
    h.guard.accept_broker_balance(account.id)
    h.clock.advance(5)
    assert h.order(account, stop=5790)["ok"]


def test_duplicate_order_within_2_seconds_is_blocked(h):
    account = h.account()
    h.price(ES, 5800)
    assert h.order(account, stop=5790)["ok"]
    h.clock.advance(1)
    assert not h.order(account, stop=5790)["ok"]
    h.clock.advance(2)
    assert h.order(account, stop=5790)["ok"]


def test_runaway_script_is_paused(h):
    account = h.account()
    h.price(ES, 5800)
    results = []
    for i in range(12):
        h.clock.advance(2.5)
        side = "buy" if i % 2 == 0 else "sell"
        results.append(h.order(account, side=side, source="script:ma_cross", stop=5790 if side == "buy" else 5810))
    assert not results[-1]["ok"]
    assert "script:ma_cross" in h.guard.paused_sources


def test_daily_trade_limit_and_allowed_hours(h):
    account = h.account(daily_trade_limit=1, allowed_hours="09:30-16:00")
    h.price(ES, 5800)
    assert h.order(account, stop=5790)["ok"]
    h.clock.advance(5)
    assert not h.order(account, stop=5790)["ok"]       # second trade today
    other = h.account("Night", allowed_hours="18:00-20:00")
    assert not h.order(other, stop=5790)["ok"]         # 10:00 New York is outside the hours


def test_guard_log_records_every_decision(h):
    account = h.account(**prop_rules())
    h.price(ES, 5800)
    h.order(account)                  # blocked: no stop
    h.clock.advance(5)
    h.order(account, stop=5790)       # approved
    log = h.journal.decisions()
    assert [row["approved"] for row in log[:2]] == [True, False]
    assert all(row["rule"] and row["reason"] for row in log)
    assert "equity" in log[0]["numbers"]
