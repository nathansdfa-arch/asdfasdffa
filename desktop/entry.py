"""The installed Windows app's starting point (TradingApp.exe).

One program does three jobs, picked by how it is started:

    TradingApp.exe              opens the app window (desktop/launcher.py)
    TradingApp.exe --browser    opens the app in the web browser instead
    TradingApp.exe --engine     runs the engine on its own (the launcher starts this)

Script workers (the sandbox) are started by Python's multiprocessing, which
also re-runs this program; freeze_support() hands those runs straight to the
worker. From source, use `python -m desktop.launcher` as before.
"""

import multiprocessing
import os
import sys


def _give_output_somewhere() -> None:
    """The installed app has no console window, so Python has nowhere to print.
    Point printing at nothing; the log file in the data folder still records everything."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def main() -> None:
    multiprocessing.freeze_support()
    _give_output_somewhere()
    if "--engine" in sys.argv[1:]:
        sys.argv.remove("--engine")
        from engine.__main__ import main as engine_main

        engine_main()
    else:
        from desktop.launcher import main as launcher_main

        launcher_main()


if __name__ == "__main__":
    main()
