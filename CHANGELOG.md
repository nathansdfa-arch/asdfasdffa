# Changelog

Every change to the app, newest first, in plain language.

## 0.3.0 (1 November 2026): Jarvis can work the app

- **Jarvis door.** Your voice assistant Jarvis gets its own key and its own addresses (`/api/jarvis/...`): status, strategies start/stop, orders, move stop, close, close all, kill switch, log. Every Jarvis order goes through the risk guard, labelled "automation:jarvis", so the guard log shows which trades were Jarvis's and the runaway-order limit applies.
- **Jarvis limits.** Paper accounts only, a stop on every order, contracts per order and orders per day caps, an allowed-accounts list, and an on/off switch in Settings.
- **Owner PIN.** Once set, switching to live, resuming after the kill switch, changing account rules, security settings and Jarvis's own settings need the PIN, so no program on the PC can press them.
- **Jarvis autopilot (paper only).** A separate owner switch lets Jarvis pick its own trades. Every autopilot order must carry a written reason, saved in the guard log as "automation:jarvis-ai", and obeys the same paper-only rule, caps and risk guard. Jarvis can read recent candles through its door.
- **`jarvis/jarvis_trade.py` and `jarvis/JARVIS_TRADING.md`.** The helper Jarvis runs and the instructions it follows.

## 0.2.0 (31 October 2026): the full first build (phases 2 to 14)

Built overnight at the owner's request. See NEEDS_NATHAN.md for what needs a decision or a test.

- **Charts (phase 2).** Multi-chart grid with 1, 2, 3, 4 or 6 charts, resizable dividers, maximize, and layouts that save themselves; named workspaces. Watchlist with market tabs, search, your own lists, live prices and daily change, collapse and switch sides. Candles, hollow candles, bars and line. Drawing tools: trend line, horizontal line, rectangle, Fibonacci, text. Gaps in the data are shaded. Five theme proposals with accent, candle colors, glow and effects. Bybit history plus offline DEMO practice prices; candles are cached so 30 days of 1-minute candles reopen in about 0.3 seconds.
- **Indicators (phase 3).** Python scripts run in a locked sandbox (no files, no network, stopped after 2 seconds). Helper library (sma, ema, rsi, atr, bollinger, macd, vwap and more). Code editor with plain-English errors that name the line and suggest fixes. Example scripts included.
- **Backtesting (phase 4).** Same fill model as paper trading, no peeking ahead, full report: net profit, win rate, max drawdown, average win and loss, profit factor, fees, equity curve and trade list, with trades shown on the chart.
- **Live data (phase 5).** Bybit live stream with reconnects; yellow stale and red disconnect banners; orders blocked when a feed is down.
- **Paper trading and the risk guard (phase 6).** Paper broker, order ticket, orders and draggable stops on the chart, all eight guard rules, trailing drawdown (intraday, end of day, static, with lock), duplicate and runaway-script checks, allowed hours, daily trade limit, and the kill switch. Every decision is logged.
- **Prop firm profiles (phase 7).** Rule profiles per firm and plan, evaluation progress, and signup buttons. Firm numbers are left empty until the owner confirms them; unconfirmed profiles block trading.
- **Rithmic (phase 8).** Placeholder only, waiting for Rithmic API access.
- **Strategies and automations (phase 9).** Run strategies live on an account; automations on a weekday schedule or on events. The kill switch stops them all.
- **MetaTrader 5 (phase 10) and Bybit trading (phase 11).** Connectors written, untested on real accounts. Bybit uses testnet by default. Every broker account stays on paper until switched to LIVE with a typed confirmation.
- **Remote access (phase 12).** Off by default. Password plus two-factor login, lockout after 5 wrong tries, encrypted HTTPS with its own certificate.
- **Phone (phase 13).** The same screens adapt to a phone: one chart, positions, basic orders, alerts and the kill switch.
- **Polish (phase 14).** Pine Script conversion helper, daily database backups, automatic effects pause if the screen drops below 50 frames a second.
- 72 automated tests, including every risk guard test in bible section 13.

## 0.1.0 (31 October 2026): Phase 1, skeleton

- Folder structure for every layer in the design bible: engine core, data, scripting, strategy, risk guard, execution, storage, the desktop window, and the screens.
- The engine runs as its own background program with a local API. It only accepts connections from this computer.
- A desktop window (pywebview) opens the app and starts and stops the engine for you. `--browser` opens it in a web browser instead.
- Logging to the console and to `logs/app.log` in the data folder, in UTC, rotated at 5 MB and keeping the last 10 files.
- A SQLite database in the data folder, with numbered updates ("migrations") so later phases can add tables safely.
- Three settings to prove saving works: display time zone, glow strength and reduce motion. Bad values are refused with a plain English reason.
- The screen shows whether the engine is connected, and a red banner if it stops answering.
- 19 automated tests, including the phase 1 "done when" test: a saved setting survives an engine restart.
