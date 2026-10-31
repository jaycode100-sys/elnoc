; ELNOC Installer script for Inno Setup (https://jrsoftware.org)
; To use: install Inno Setup, then compile this file (ISCC or the GUI)
;   iscc build_elnoc_installer.iss
; Output: ELNOC-Setup.exe  (single setup file, like Spotify/Telegram)

#define MyAppName "ELNOC"
#define MyAppPublisher "ELNOC"
#define MyAppURL "https://github.com/elnoc"
#define MyAppExeName "ELNOC.exe"

[Setup]
AppId={{E1A2B3C4-D5E6-4F7A-8B9C-0D1E2F3A4B5C}
AppName={#MyAppName}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
AppVersion=0.1.0
AppCopyright=Copyright © ELNOC
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
SetupIconFile=ELNOC.ico
UninstallDisplayName={#MyAppName}
LicenseFile=
PrivilegesRequired=lowest
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ChangesEnvironment=true
OutputBaseFilename=ELNOC-Setup
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible

[Dirs]
Name: "{app}"; Permissions: users-full

[Files]
; The single-file PyInstaller executable
Source: "dist\ELNOC.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\ELNOC"; Filename: "{app}\{#MyAppExeName}"
Name: "{commondesktop}\ELNOC"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, "&", "&&")}}"; Flags: nowait postinstall skipifsilent

; On first run, the app seeds its writable database into %LOCALAPPDATA%\ELNOC\elnoc.db
; (handled inside run_desktop.py). No [Code] section needed.
