# Trading App

A desktop-first trading platform: fast charts, Python scripts for indicators and strategies, and automated trading with a risk guard that can't be bypassed. The plan for the whole app is the design bible (version 2), kept in the project's files.

**Current stage: Phase 1, the skeleton.** There are no charts or trading yet. This stage proves the foundation works: the engine runs, the window talks to it, and settings are saved.

## Opening the app on Windows

1. Install **Python 3.12 or newer** from [python.org](https://www.python.org/downloads/). During setup, tick **"Add python.exe to PATH"**.
2. Download this project (on GitHub: the green **Code** button, then **Download ZIP**) and unzip it.
3. Double-click **`start_app.bat`**. The first time it spends a minute or two installing what it needs. After that it opens straight away.

A window called "Trading App" opens. The pill in the top right says **Engine connected**.

To use a web browser instead of a window, open a command prompt in the folder and run `start_app.bat --browser`.

## Trying the phase 1 test yourself

1. Change the **Display time zone**, for example to America/Chicago. It says "Saved."
2. Close the window. This also stops the engine.
3. Double-click `start_app.bat` again. Your time zone is still selected, and "Running since" is shown in that time zone.

## Where your data lives

Everything the app saves is in one folder, kept apart from the code so updates never touch it:

- Windows: `%LOCALAPPDATA%\TradingApp` (paste that into the File Explorer address bar)
- `trading_app.db` is the database. `logs\app.log` is the log.

## How the code is organised

| Folder | What lives there |
| --- | --- |
| `engine/` | The engine: a standalone program holding all trading logic. |
| `engine/api/` | The local API, the only way screens talk to the engine. Only this computer can connect. |
| `engine/storage/` | The SQLite database and settings. |
| `engine/core`, `data`, `scripting`, `strategy`, `risk`, `execution` | Empty for now; each is filled by a later phase (see the note inside each). |
| `desktop/` | The Windows window. It starts the engine and shows the screens. |
| `ui/` | The screens. Phase 2 replaces these with the React chart interface. |
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
