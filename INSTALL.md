# Installing the Trading App on Windows

The Trading App is a normal Windows program: one installer, a Start menu icon,
and an uninstaller in Settings > Apps. You don't need Python or anything else.

## Install

1. **Get the installer** `TradingApp-Setup-<version>.exe`:
   - From the repository's **Releases** page (right side of the GitHub page), under the newest version, click the `.exe` file.
   - Or, for a version that isn't released yet: on GitHub open **Actions**, click the newest green **Windows app** run, scroll to **Artifacts** and click `TradingApp-Setup-<version>`. It downloads as a zip; open it and take the `.exe` out.
2. **Run it.** Windows may show a blue box "Windows protected your PC", because the installer isn't signed with a paid certificate yet. Click **More info**, then **Run anyway**.
3. Click **Next** through the steps. Tick "Put a Trading App icon on the desktop" if you want one. It installs for your Windows user only, so it doesn't ask for an administrator password.
4. Leave **Open Trading App now** ticked and click **Finish**.

From then on, open it from the Start menu (type "Trading App") or the desktop icon.

## Updating

Run the newer installer. It closes the app if it's open, replaces the program, and keeps everything you saved.

## Uninstalling

Settings > Apps > Installed apps > **Trading App** > Uninstall. Your data folder is kept, so reinstalling brings back your accounts, scripts, layouts and history. To remove that too, delete `%LOCALAPPDATA%\TradingApp` afterwards.

## Where things are

| What | Where |
| --- | --- |
| The program | `%LOCALAPPDATA%\Programs\TradingApp` |
| Your data (database, logs, backups) | `%LOCALAPPDATA%\TradingApp` (Start menu: "Trading App data folder") |
| Passwords and API keys | Windows Credential Manager |
| Jarvis's helper (`jarvis_trade.py`) | `%LOCALAPPDATA%\Programs\TradingApp\jarvis` |

The installed app uses the same data folder as `start_app.bat` did, so nothing needs moving.

## If something goes wrong

- **The app opens in your web browser instead of a window.** The PC is missing the free Microsoft Edge WebView2 Runtime (Windows 10 and 11 normally have it). Install the "Evergreen Bootstrapper" from https://developer.microsoft.com/microsoft-edge/webview2/ and open the app again.
- **"The trading engine did not start."** The reason is in `logs\app.log` in the data folder. Another copy of the app may already be running; check the taskbar.
- **The Start menu also has "Trading App (in web browser)"**, which opens the same app in your browser. Useful if the window misbehaves.

## Building the installer yourself (developers)

GitHub builds, tests and installs the app on a Windows machine on every push (`.github/workflows/windows-app.yml`). Pushing a tag such as `v0.4.0` also publishes the installer on the Releases page.

To build by hand on Windows: install Python 3.13 and [Inno Setup 6](https://jrsoftware.org/isdl.php), then double-click `packaging\build_windows.bat`. The installer appears in `dist\`.
