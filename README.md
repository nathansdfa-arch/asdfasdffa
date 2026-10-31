# Trading App

A desktop-first trading platform: fast charts, Python scripts for indicators and strategies, backtests, paper trading, and automated trading behind a risk guard that can't be bypassed. The plan for the whole app is the design bible (version 2), kept in the project's files.

**Current stage: version 0.2.0, the full first build.** Everything in the bible's 14 phases is in place for paper trading. Real brokers (Rithmic, MetaTrader 5, Bybit) are written but need your accounts and testing. **Start with [NEEDS_NATHAN.md](NEEDS_NATHAN.md).**

## Opening the app on Windows

1. Install **Python 3.12 or newer** from [python.org](https://www.python.org/downloads/). During setup, tick **"Add python.exe to PATH"**.
2. Download this project (on GitHub: the green **Code** button, then **Download ZIP**) and unzip it.
3. Double-click **`start_app.bat`**. The first time it spends a minute or two installing what it needs. After that it opens straight away.

To use a web browser instead of a window, run `start_app.bat --browser`.

## A five-minute tour

Everything starts in **PAPER** mode with practice money. The blue PAPER badge is on every chart and on the order ticket.

1. **Charts.** Pick a layout (1 to 6 charts) with the buttons at the top. Click a chart to make it active, then click a symbol in the watchlist (or drag it onto a chart). Double-click a chart to fill the screen; double-click or Escape to go back. Drag the dividers to resize. Your layout saves itself.
2. **Drawing.** The ╱ — ▭ ƒ T buttons draw trend lines, horizontal lines, rectangles, Fibonacci levels and notes. Right-click a chart for more.
3. **Indicators.** "+ Indicator" on a chart adds a script, for example "Averages and RSI".
4. **Paper trade.** In **Trade** on the right, choose Buy or Sell, a size and a stop, and press Send order. The stop and target appear on the chart; drag them to move them. The **B** and **S** buttons on a chart send a quick market order.
5. **Risk guard.** Every order is checked first. Open **Log** to see every decision, which rule made it and the numbers used. The strip at the top shows balance, today's result and how much of your allowed loss is used.
6. **Kill switch.** The red button stops every script, cancels every order and closes every position. No confirmation. Trading stays halted until you press "Resume trading".
7. **Scripts.** In **Scripts**, open an example, change it and save. "Check" finds mistakes and explains them in plain English. The Pine Script helper converts simple TradingView indicators.
8. **Backtest.** Choose a strategy, symbol and timeframe, and press Run backtest. "Show trades on the active chart" marks every trade.
9. **Accounts.** Create paper or broker accounts, set risk rules, attach a prop firm profile and watch evaluation progress. The prop firm buttons open each firm's website.
10. **Settings.** Themes, colors, effects, time zone, sounds, phone access and backups.

## Where your data lives

Everything the app saves is in one folder, kept apart from the code so updates never touch it:

- Windows: `%LOCALAPPDATA%\TradingApp` (paste that into the File Explorer address bar)
- `trading_app.db` is the database, `logs\app.log` is the log, `backups\` has a daily copy of the database (last 30 kept).
- Passwords and API keys are in Windows Credential Manager, never in these files.

## How the code is organised

| Folder | What lives there |
| --- | --- |
| `engine/` | The engine: a standalone program holding all trading logic. |
| `engine/api/` | The local API and live updates, the only way screens talk to the engine. |
| `engine/core/` | Shared building blocks: candles, orders, markets, the clock and the message bus. |
| `engine/data/` | Price feeds (Bybit, demo prices, MT5) and the candle cache. |
| `engine/scripting/` | The Python script sandbox, helper library, plain-English errors and the Pine Script helper. |
| `engine/strategy/` | Backtests and the runner for live strategies and automations. |
| `engine/risk/` | The risk guard, trailing drawdown, prop firm profiles and the kill switch. |
| `engine/execution/` | Accounts, the paper broker, and the Rithmic, MT5 and Bybit connectors. |
| `engine/security/` | Credential storage, login and two-factor for remote access. |
| `engine/storage/` | The SQLite database, settings, workspaces, journal and backups. |
| `config/` | Markets, prop firm rule profiles and signup links. Edit these without touching code. |
| `scripts/examples/` | The example scripts loaded on first start. |
| `desktop/` | The Windows window. It starts the engine and shows the screens. |
| `ui/` | The screens (plain JavaScript, no build step). |
| `tests/` | Automated tests. Double-click `run_tests.bat` to run them. |
| `docs/` | Notes for the owner, including the Rithmic and prop firm questions to send. |

## For developers

```
python -m venv .venv
.venv\Scripts\activate          (Windows)   or   source .venv/bin/activate
pip install -r requirements-dev.txt
pytest                          run the tests
python -m engine                run the engine alone, then open http://127.0.0.1:8765
python -m desktop.launcher      run the engine and the desktop window
```

Set `TRADING_APP_DATA_DIR` to keep data somewhere other than the default folder.
