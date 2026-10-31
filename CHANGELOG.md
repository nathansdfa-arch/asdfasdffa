# Changelog

Every change to the app, newest first, in plain language.

## 0.1.0 (31 October 2026): Phase 1, skeleton

- Folder structure for every layer in the design bible: engine core, data, scripting, strategy, risk guard, execution, storage, the desktop window, and the screens.
- The engine runs as its own background program with a local API. It only accepts connections from this computer.
- A desktop window (pywebview) opens the app and starts and stops the engine for you. `--browser` opens it in a web browser instead.
- Logging to the console and to `logs/app.log` in the data folder, in UTC, rotated at 5 MB and keeping the last 10 files.
- A SQLite database in the data folder, with numbered updates ("migrations") so later phases can add tables safely.
- Three settings to prove saving works: display time zone, glow strength and reduce motion. Bad values are refused with a plain English reason.
- The screen shows whether the engine is connected, and a red banner if it stops answering.
- 19 automated tests, including the phase 1 "done when" test: a saved setting survives an engine restart.
