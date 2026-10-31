"""The paper broker and the shared fill model."""

import pytest

from engine.core.markets import MarketCatalog
from engine.core.models import Candle, OrderType, Side
from engine.execution import fill_model
from tests.trading_harness import Harness

ES = "DEMO:ES"


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


def test_market_order_fills_at_price_plus_slippage_and_pays_fees(h):
    account = h.account()
    h.price(ES, 5800)
    h.order(account)
    position = h.broker.positions(account.id)[0]
    assert position.quantity == 1
    assert position.average_price == 5800.25          # one tick of slippage against us
    assert h.broker.books[account.id].balance == 25000 - 2.5


def test_limit_fills_only_when_price_trades_through(h):
    account = h.account()
    h.price(ES, 5800)
    h.order(account, kind="limit", price=5795)
    h.price(ES, 5795)                                  # touch only: no fill
    assert h.broker.positions(account.id) == []
    h.price(ES, 5794.75)                               # through: fills at the limit
    assert h.broker.positions(account.id)[0].average_price == 5795


def test_stop_becomes_market_when_touched(h):
    account = h.account()
    h.price(ES, 5800)
    h.order(account, kind="stop", price=5805)
    h.price(ES, 5805)
    assert h.broker.positions(account.id)[0].average_price == 5805.25


def test_stop_and_target_cancel_each_other_and_profit_is_booked(h):
    account = h.account()
    h.price(ES, 5800)
    h.order(account, stop=5790, target=5810)
    roles = sorted(o.role for o in h.broker.working_orders(account.id))
    assert roles == ["stop_loss", "take_profit"]
    h.price(ES, 5810.25)                               # target fills at 5810
    assert h.broker.positions(account.id) == []
    assert h.broker.working_orders(account.id) == []
    # (5810 - 5800.25) x $50 = 487.50, minus two $2.50 fees
    assert h.broker.books[account.id].balance == pytest.approx(25000 + 487.5 - 5)


def test_short_position_profit(h):
    account = h.account()
    h.price(ES, 5800)
    h.order(account, side="sell", stop=5810)
    h.clock.advance(5)
    h.price(ES, 5790)
    h.orders.close_position(account.id, ES)
    # entry 5799.75, exit 5790.25: 9.5 points x $50 = 475, minus fees
    assert h.broker.books[account.id].balance == pytest.approx(25000 + 475 - 5)


def test_books_survive_a_restart(h, tmp_path):
    account = h.account()
    h.price(ES, 5800)
    h.order(account, stop=5790)
    again = Harness(tmp_path)
    again.broker.open_account(account.id, 25000)
    assert again.broker.positions(account.id)[0].quantity == 1
    assert len(again.broker.working_orders(account.id)) == 1


def test_candle_fill_model_for_backtests():
    market = MarketCatalog().get(ES)
    candle = Candle(0, 5800, 5810, 5790, 5805, 100)
    assert fill_model.fill_on_candle(OrderType.MARKET, Side.BUY, None, candle, market) == 5800.25
    assert fill_model.fill_on_candle(OrderType.LIMIT, Side.BUY, 5790, candle, market) is None     # touch only
    assert fill_model.fill_on_candle(OrderType.LIMIT, Side.BUY, 5795, candle, market) == 5795
    assert fill_model.fill_on_candle(OrderType.STOP, Side.SELL, 5795, candle, market) == 5794.75
    gap = Candle(0, 5780, 5785, 5775, 5782, 100)
    assert fill_model.fill_on_candle(OrderType.STOP, Side.SELL, 5795, gap, market) == 5779.75   # gapped past the stop
