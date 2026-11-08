; Inno Setup recipe for the Trading App installer (TradingApp-Setup-<version>.exe).
;
; It installs the folder PyInstaller built (dist\TradingApp) for the current
; Windows user only, so it needs no administrator password, adds Start menu and
; (optional) desktop shortcuts, and registers an uninstaller in
; Settings > Apps. Your data in %LOCALAPPDATA%\TradingApp is never touched by
; installing, updating or uninstalling.
;
; Build:  iscc /DAppVersion=0.4.0 packaging\installer.iss   (build_windows.bat does this)

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; Never change AppId: Windows uses it to recognise updates of the same app.
AppId={{8C1F4E52-6B1D-4A57-9E1B-3F6B2A9D7C41}
AppName=Trading App
AppVersion={#AppVersion}
AppVerName=Trading App {#AppVersion}
AppPublisher=Trading App
DefaultDirName={localappdata}\Programs\TradingApp
DefaultGroupName=Trading App
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=TradingApp-Setup-{#AppVersion}
SetupIconFile=app_icon.ico
UninstallDisplayIcon={app}\TradingApp.exe
UninstallDisplayName=Trading App
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; Close a running copy of the app (window and engine) before updating its files.
CloseApplications=force
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Put a Trading App icon on the desktop"; GroupDescription: "Shortcuts:"

[InstallDelete]
; An update replaces the whole app folder so no old files linger.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\TradingApp\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Jarvis's helper, to copy into the folder the Jarvis worker session uses (NEEDS_NATHAN.md section 8).
Source: "..\jarvis\jarvis_trade.py"; DestDir: "{app}\jarvis"; Flags: ignoreversion
Source: "..\jarvis\JARVIS_TRADING.md"; DestDir: "{app}\jarvis"; Flags: ignoreversion

[Icons]
Name: "{group}\Trading App"; Filename: "{app}\TradingApp.exe"
Name: "{group}\Trading App (in web browser)"; Filename: "{app}\TradingApp.exe"; Parameters: "--browser"
Name: "{group}\Trading App data folder"; Filename: "{localappdata}\TradingApp"
Name: "{group}\Uninstall Trading App"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Trading App"; Filename: "{app}\TradingApp.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\TradingApp.exe"; Description: "Open Trading App now"; Flags: nowait postinstall skipifsilent

[Code]
{ The app window uses Microsoft Edge WebView2, which Windows 10 and 11 normally
  already have. If it is missing, say so and offer the free download. }
const
  WebView2Key = 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WebView2Key32 = 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function HasWebView2: Boolean;
var
  Version: String;
begin
  Result :=
    (RegQueryStringValue(HKLM, WebView2Key32, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKLM, WebView2Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKCU, WebView2Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ErrorCode: Integer;
begin
  if (CurStep = ssPostInstall) and (not HasWebView2) and (not WizardSilent) then
  begin
    if MsgBox('The app window needs the free Microsoft Edge WebView2 Runtime, which this PC does not seem to have.' + #13#10#13#10 +
              'Open the download page now? Choose "Evergreen Bootstrapper", run it, then start Trading App.' + #13#10#13#10 +
              'Until then the app opens in your web browser instead.',
              mbConfirmation, MB_YESNO) = IDYES then
      ShellExec('open', 'https://developer.microsoft.com/microsoft-edge/webview2/', '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
  end;
end;
