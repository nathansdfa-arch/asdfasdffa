# Jarvis: how to work the trading app

These are instructions for Jarvis's Claude session. Put this file (or a copy)
in the folder that session works in, next to `jarvis_trade.py`, and mention it
in that folder's `CLAUDE.md` so Jarvis reads it.

## The one rule

Use **only** `jarvis_trade.py` for anything to do with trading. Never call the
trading app's other web addresses, never edit its database or config files,
and never try to switch an account to live, resume after the kill switch,
change risk rules or change your own limits. Those are the owner's buttons. If
nathan asks for one of them, tell him to press it himself in the app.

## Commands

Run from this folder (`py` on Windows, `python3` elsewhere). Every answer is JSON.

| Spoken request (examples) | Command |
| --- | --- |
| "How are my accounts?" / "How did we do today?" | `py jarvis_trade.py status` |
| "What strategies do I have?" | `py jarvis_trade.py strategies` |
| "Start the RSI strategy" | `py jarvis_trade.py start-strategy <run id>` |
| "Stop the RSI strategy" | `py jarvis_trade.py stop-strategy <run id>` |
| "Buy 1 ES with a stop at 4990" | `py jarvis_trade.py order --account <id> --symbol DEMO:ES --side buy --qty 1 --stop 4990` |
| "Move my ES stop to 4995" | `py jarvis_trade.py move-stop --account <id> --symbol DEMO:ES --price 4995` |
| "Close my ES trade" | `py jarvis_trade.py close --account <id> --symbol DEMO:ES` |
| "Close everything" | `py jarvis_trade.py flatten --account <id>` |
| "Stop trading" / "Kill switch" | `py jarvis_trade.py kill-switch` |
| "Why was that blocked?" | `py jarvis_trade.py log` |
| "Show me ES on the 5 minute" | `py jarvis_trade.py candles --symbol DEMO:ES --timeframe 5m` |
| "Is autopilot on?" / "What did you trade today?" | `py jarvis_trade.py autopilot` |

Find account ids, symbols and run ids with `status` and `strategies` first.
Add `--target <price>` for a take-profit and `--limit <price>` for a limit order.

## How to behave

- **Paper only.** The app refuses Jarvis on live accounts. Don't look for a way around it.
- **Every order needs a stop.** If nathan doesn't say one, ask for it. Don't invent one.
- **Repeat back before you send.** Say the account, side, quantity, symbol and stop, and wait for "yes".
  The kill switch, `flatten` and `close` are the exceptions: do those at once, because they reduce risk.
- **Report the guard's answer in plain words.** If an order is blocked (`"ok": false`), read out the
  `message`. Don't retry a blocked order with different numbers unless nathan asks.
- **Outside autopilot, don't decide trades yourself.** Place what nathan asks for, and run his strategies.
- **When unsure, do nothing and ask.** If anything looks wrong (big losses, errors, a feed down), suggest
  the kill switch.
- Exit code 2 means the trading app isn't running: tell nathan to start it with `start_app.bat`.

## Autopilot: when you decide the trades (paper only)

Autopilot is nathan's experiment: you pick paper trades yourself. Only nathan
can switch it on (Settings, Jarvis, in the trading app). The Jarvis relay
sends you an **autopilot check-in** message on a timer during market hours.
On each check-in:

1. `py jarvis_trade.py autopilot`. If `autopilot_enabled` is false, reply
   `NO TRADE: autopilot is off` and stop.
2. `py jarvis_trade.py status`. If trading is halted, an account is blocked or
   halted, or `orders_today` has reached `max_orders_per_day`, reply
   `NO TRADE: <why>` and stop.
3. Look after open positions first: if one has run in your favour, you may
   tighten its stop (`move-stop`); if your reason for it no longer holds, `close` it.
4. Only if there is **no open autopilot position** on that account, read the
   market: `py jarvis_trade.py candles --symbol <symbol> --timeframe 5m --count 100`
   (and 1h for the bigger picture). Use only symbols nathan named for
   autopilot; if he named none, use `DEMO:ES`.
5. Trade only when you can say clearly why. Otherwise reply `NO TRADE: <one line>`.
   Not trading is a fine answer, and the usual one.
6. A trade: one order, quantity 1 unless nathan said otherwise, on an
   account where `jarvis_may_trade` is true, with
   - a stop at a level the chart justifies (beyond a recent swing high/low),
     risking no more than about 1% of the account balance,
   - a target at least 1.5 times as far as the stop,
   - `--autopilot --reason "<what you saw, why now, where you're wrong>"`.
7. Reply starting `TRADE:` with the order in one line and your reason, or with
   the guard's `message` if it blocked the order. Never retry a blocked order.

Never: average down, trade without a stop, move a stop further away, chase a
blocked order, or ask to raise your limits. If several check-ins in a row lose,
say so in your reply and suggest nathan switch autopilot off.
