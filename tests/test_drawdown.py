"""The trailing drawdown engine, including the bible's illustrative example step by step."""

from engine.risk.drawdown import DrawdownConfig, TrailingDrawdown


def bible_example():
    return TrailingDrawdown(DrawdownConfig(starting_balance=25000, amount=1000, floor_method="intraday", lock_level=25000))


def test_bible_example_reproduces_every_step():
    dd = bible_example()
    # "The floor starts at 24,000."
    assert dd.state.floor == 24000
    # "Equity peaks at 25,600 during a trade, so the floor rises to 24,600..."
    dd.on_equity(25300)
    dd.on_equity(25600)
    assert dd.state.floor == 24600
    # "...and stays there even after the trade closes at 25,300. Room left is 700."
    dd.on_equity(25300)
    assert dd.state.floor == 24600
    assert dd.room_left(25300) == 700
    # "Once equity has peaked at 26,000, the floor reaches 25,000 and locks."
    dd.on_equity(26000)
    assert dd.state.floor == 25000
    assert dd.state.locked
    dd.on_equity(27000)
    assert dd.state.floor == 25000  # locked: does not rise further
    assert not dd.state.failed


def test_touching_the_floor_fails_the_account():
    dd = bible_example()
    dd.on_equity(24000.01)
    assert not dd.state.failed
    dd.on_equity(24000)
    assert dd.state.failed
    assert dd.state.failed_at_equity == 24000


def test_end_of_day_floor_moves_only_at_reset():
    dd = TrailingDrawdown(DrawdownConfig(25000, 1000, "end_of_day", 25000))
    dd.on_equity(25800)              # intraday peak does not move the floor
    assert dd.state.floor == 24000
    dd.on_daily_reset(25500)         # closed balance at reset does
    assert dd.state.floor == 24500


def test_end_of_day_profile_fails_on_mid_day_touch():
    """Bible section 13: an end-of-day profile fails the account when equity touches the floor mid-day."""
    dd = TrailingDrawdown(DrawdownConfig(25000, 1000, "end_of_day", 25000))
    dd.on_daily_reset(25500)         # floor 24,500
    dd.on_equity(24800)
    assert not dd.state.failed
    dd.on_equity(24499)              # mid-day touch, before any reset
    assert dd.state.failed


def test_static_floor_never_moves():
    dd = TrailingDrawdown(DrawdownConfig(25000, 1500, "static"))
    dd.on_equity(30000)
    dd.on_daily_reset(30000)
    assert dd.state.floor == 23500


def test_floor_never_moves_down():
    dd = TrailingDrawdown(DrawdownConfig(25000, 1000, "intraday", None))
    dd.on_equity(25500)
    dd.on_equity(25100)
    assert dd.state.floor == 24500
