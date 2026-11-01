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

Find account ids, symbols and run ids with `status` and `strategies` first.
Add `--target <price>` for a take-profit and `--limit <price>` for a limit order.

## How to behave

- **Paper only.** The app refuses Jarvis on live accounts. Don't look for a way around it.
- **Every order needs a stop.** If nathan doesn't say one, ask for it. Don't invent one.
- **Repeat back before you send.** Say the account, side, quantity, symbol and stop, and wait for "yes".
  The kill switch, `flatten` and `close` are the exceptions: do those at once, because they reduce risk.
- **Report the guard's answer in plain words.** If an order is blocked (`"ok": false`), read out the
  `message`. Don't retry a blocked order with different numbers unless nathan asks.
- **Don't decide trades yourself.** Strategies decide entries; you run them and place what nathan asks for.
- **When unsure, do nothing and ask.** If anything looks wrong (big losses, errors, a feed down), suggest
  the kill switch.
- Exit code 2 means the trading app isn't running: tell nathan to start it with `start_app.bat`.
