; sih_installer.iss - Inno Setup script for the Windows installer.
;
; Build (from the repository root, after the PyInstaller build has produced
; packaging\dist\SIH Forensic Tool\):
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\sih_installer.iss
;
; Produces packaging\Output\SIH-Forensic-Tool-Setup-<version>.exe - a normal Windows installer:
; welcome page, license (Terms and Conditions) page the user must accept, install-location page,
; Start Menu folder page, an optional Desktop shortcut, then installs and offers to launch.
;
; VERSION is read from the repository's own VERSION file, so it can never drift from the app's
; own version.
#define FileHandle
#define MyAppVersion "0.0.0"
#if FileHandle = FileOpen("..\VERSION")
  #define MyAppVersion Trim(FileRead(FileHandle))
  #expr FileClose(FileHandle)
#endif

#define MyAppName "SIH Forensic Tool"
#define MyAppPublisher "Team Espada - SIH26150"
#define MyAppExeName "SIH Forensic Tool.exe"
; Fixed GUID: keeps Windows treating future versions as upgrades of the same app, not a new one.
#define MyAppId "{{B4B6D1A0-6B7E-4E3E-9C1E-7B7B3B5A1D02}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=no
LicenseFile=TERMS.txt
OutputDir=Output
OutputBaseFilename=SIH-Forensic-Tool-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
; Asks up front, same as Autopsy/Wireshark: "install for everyone on this computer" (elevates,
; installs to Program Files) or "install just for me" (no admin prompt, installs to this user's
; own AppData instead - {autopf} resolves to the right one automatically for either choice).
; This app writes its own settings under the user's home folder (~/.sih_forensic_tool) either
; way, never into the install directory, so both modes work cleanly at runtime with no extra code.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "dist\SIH Forensic Tool\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} now"; Flags: nowait postinstall skipifsilent
