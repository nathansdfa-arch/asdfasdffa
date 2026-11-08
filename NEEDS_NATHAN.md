# Needs nathan

Everything below was built overnight on 31 October 2026 but needs a decision, a
number, an account or a test only you can do. Until you act, each item has a
**safe placeholder**: the app stays in PAPER mode, unconfirmed firm rules block
trading, and nothing is sent anywhere.

Work through these roughly in order. Each one says what to do and where.

## 1. Look at it and pick a theme (5 minutes)

- Double-click `start_app.bat`. Open **Settings** on the right.
- Five theme proposals are there: Lilac Nocturne (current), Rose Quartz, Champagne Graphite, Sea Glass, Ice Opal. Click one to try it. Tell us which you like, or what to change. None use black-and-orange or navy with neon colors.
- Accent color, candle colors, glow, effects and chart background are all adjustable in the same panel.

## 2. Prop firm numbers (needed before any prop firm account can trade)

`config/prop_firms.json` has Tradeify, Lucid, HyroTrader and Breakout with **every number left empty** and `confirmed_by_owner: false`. We did not guess them. While a profile is unconfirmed, the risk guard blocks every order on that account (rule 3, fail closed).

To do:
- Pick the plan you'll start with (bible open question: Tradeify or Lucid first?).
- Copy the exact numbers from the firm's current rule page into that plan: drawdown amount, drawdown method (intraday / end of day / static), lock level, daily loss limit, profit target, max contracts, minimum trading days, reset time and time zone.
- Set `confirmed_by_owner` to `true`. Or send us the rule page link and we'll fill it in for you to check.
- Choose your **safety buffer** in dollars (the gap the app keeps below the firm's limit). The default is $100.
- Phase 7's "done when" test (a paper evaluation on your real plan) can only be run after this.

Meanwhile, the **"Prop practice (example rules)"** account uses the bible's illustrative numbers so you can see how the drawdown floor, evaluation progress and blocks behave.

## 3. Send the Rithmic and prop firm questions

`docs/rithmic_and_firm_questions.md` has the emails ready to send. The answers decide whether a self-built app may connect to your firm's Rithmic account, what market data costs, and whether Tradeify or Lucid allow automated trading (and on which plans).

## 4. Rithmic (futures): blocked on Rithmic

The Rithmic connector is a placeholder that refuses to connect. Rithmic requires developer API access and a conformance test before any app can connect. Once you have access, we build and test it on the firm's demo or evaluation environment first, never on a funded account.

## 5. Tests only you can run on Windows

These parts are written but could not be tested from the build machine:

- **Bybit live prices and history.** The build machine's network blocks Bybit, so Bybit was tested against recorded sample replies only. On your PC the Bybit charts should fill in. If they say "Could not reach Bybit", Bybit may be blocked where you are (it is not available in some countries, including the US). Tell us and we'll switch the crypto feed.
- **MetaTrader 5 (phase 10).** Install MT5, log into a **demo** account, then in **Accounts** create an "MetaTrader 5" account, enter login, server and password, and press "Test connection". Place and close a small order with a stop on the demo.
- **Bybit trading (phase 11).** Create API keys on **Bybit testnet** (testnet.bybit.com), add a Bybit account in the app (testnet is on by default), save the keys, test the connection and place an order with a stop.
- **Smoothness.** The bible's target is 60 frames a second with 4 charts and 10 indicators. If effects make it stutter the app turns them off by itself, but tell us how it feels.

Passwords and API keys are stored in Windows Credential Manager, never in the database, logs or code.

## 6. Before any real money goes through a broker

- **Balance check (guard rule 8) only works for paper so far.** Real connectors don't stream their fills to the app yet, so the app can't yet compare its balance to the broker's on every fill. This must be finished, and a full paper session run end to end, before you switch any broker account to LIVE.
- Switching an account to LIVE asks you to type `LIVE <account name>`. Don't do this until the item above is done and you've reviewed a paper session together with us.

## 7. Phone and remote access (phase 12 and 13)

- Remote access is **off**. To use the app from your phone, set a password and two-factor in **Settings → Phone and remote access**, then turn remote access on and restart.
- Decide where the always-on engine runs: your own Windows PC, or a rented Windows cloud server (bible open question).
- The app makes its own security certificate, so phones show a "not secure" warning the first time. Our recommendation is **Tailscale** (free for personal use): it gives your phone a private, encrypted link to your PC without opening anything to the internet. That is a third-party service, so we didn't set it up without asking.

## 8. Jarvis (voice trading, added 1 November 2026)

Jarvis can now work the trading app: check accounts, start and stop strategies, place orders you ask for out loud, close positions and press the kill switch. It can only trade **paper** accounts, every order needs a stop, and every order still goes through the risk guard.

To switch it on:
1. In the app, open **Settings, Jarvis** and press **Create Jarvis key**. Copy the key.
2. Copy the `jarvis` folder from this app (`jarvis_trade.py` and `JARVIS_TRADING.md`) into the folder Jarvis's Claude session works in. Save the key in a file called `jarvis_key.txt` next to `jarvis_trade.py`.
3. Add a line to that folder's `CLAUDE.md`: "For anything about trading, follow JARVIS_TRADING.md."
4. **Set an owner PIN** in the same Settings section. Without it, any program on your PC could press owner-only buttons such as switching an account to live. With it, those buttons ask for the PIN.
5. Set Jarvis's limits there too: contracts per order (default 1), orders per day (default 20) and which paper accounts it may use.

**Autopilot (you chose this on 1 November):** Jarvis can also pick its own paper trades. It is off until you press **Switch autopilot on** in Settings, Jarvis, and set `trading_autopilot.enabled` to `true` in the Jarvis relay's `config.json` (see the relay README). Jarvis then checks the market every 15 minutes in market hours, trades only with a stop and a written reason, and every reason is in the Log. It obeys the same paper-only rule, limits and risk guard. Tell Jarvis which symbols to watch; it uses DEMO:ES if you don't. Review its trades with us after a week before trusting it with anything more.

## 9. Smaller decisions

- **Keyboard shortcuts:** which matter most? (None are set yet except Escape to leave a maximized chart.)
- **Sounds:** alert sounds are off by default. Turn them on in Settings if you want a sound for the 70% warning, blocks and disconnects.
- **Light theme:** add one later, or stay dark only?
- **HyroTrader, Breakout, or both** for crypto, and in what order?

## 10. Changes from the bible we made on our own (please approve or overrule)

- **Screens are plain JavaScript, not React.** Same Lightweight Charts library, but no build step, so nothing extra (like Node.js) has to be installed on your PC and the app starts straight from the folder. Easy to switch later if needed.
- **Demo prices.** Futures, forex and stocks have no free live feed until Rithmic or MT5 is connected, so the app includes clearly labelled "DEMO" symbols with practice prices that work offline. They let you try charts, scripts, backtests and paper trading now. They are not real market prices.
- **Windows memory limit for scripts.** On Windows, scripts are limited by the 2-second timeout but not by a memory cap (that part only works on Mac/Linux). A script that tries to use huge amounts of memory could slow the PC. Low risk, on the list to improve.
- **Approval per phase was skipped** because you asked us to build everything overnight. Every phase can still be reviewed and changed.

## 10. TJR Boot Camp strategy (new)

Two new scripts are in the Scripts panel: **TJR Boot Camp strategy** and **TJR Boot Camp chart view**. The rules come from the write-up in `docs/TJR_STRATEGY.md`. It runs on practice money only, like every other strategy.

- **Use it on a 5 minute chart.** It builds the 15 minute, 1 hour, 4 hour and daily candles itself. In paper trading it needs a few days of candles before the daily trend is known, so it may sit out the first days.
- **Set `point_value` for your market** before testing (ES = 50, MES = 5, most CFDs = 1). Size comes from `risk_dollars` (default $250, 1% of 25K).
- **News days:** the app has no economic calendar yet, so type CPI, PPI, FOMC, NFP, Fed Chair and bank holiday dates into `skip_dates`. A built-in calendar would be a later update.
- **It trades rarely, on purpose.** It needs the daily, 4 hour and 1 hour to agree, a touch of a 1 hour or 4 hour zone, then a sweep and break on the 5 minute inside 9:30 to 11:00, then a pullback, and at least 1:1 to the first target. On 120 days of practice prices it took 2 trades. Practice prices aren't real market behaviour, so judge it on real history.
- **Choices I made where TJR doesn't say** (all can be changed in the inputs or the code): which highs count as liquidity (the latest 5 minute and 15 minute swings), entering at market after the pullback instead of a resting limit order, the last target (1 hour liquidity, or 3R if there is none), and closing everything at 15:50 New York time.
- **Not in yet:** the London 30 minute box strategy (never taught in the videos), the "4 hour against the daily" exception (rule 16), and the optional time stop (rule 35).
