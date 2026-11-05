; Instalator VidSum (Inno Setup 6) — budowany w GitHub Actions z paczki „-python” (portable\VidSum).
; Instalacja bez uprawnień administratora do %LOCALAPPDATA%\Programs\VidSum; skrót w menu Start (i na pulpicie);
; odinstalowanie przez Ustawienia → Aplikacje. Dane użytkownika (Dokumenty\VidSum, %LOCALAPPDATA%\VidSum) zostają.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\portable\VidSum"
#endif

[Setup]
AppId={{6B1E2C4A-8F3D-4E7B-9C21-5A0D7F3E9B14}
AppName=VidSum
AppVersion={#AppVersion}
AppVerName=VidSum {#AppVersion}
AppPublisher=VidSum
DefaultDirName={localappdata}\Programs\VidSum
DefaultGroupName=VidSum
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=VidSum-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
UninstallDisplayName=VidSum
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "pl"; MessagesFile: "compiler:Languages\Polish.isl"

[Tasks]
Name: "desktopicon"; Description: "Skrót na pulpicie"; GroupDescription: "Skróty:"

[InstallDelete]
; stary kod usuwany przed instalacją nowego — bez nieaktualnych plików
Type: filesandordirs; Name: "{app}\vidsum"
Type: filesandordirs; Name: "{app}\vidsum.stare"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\VidSum"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m vidsum --ui"; WorkingDir: "{app}"; Comment: "Analiza filmów"
Name: "{group}\Odinstaluj VidSum"; Filename: "{uninstallexe}"
Name: "{userdesktop}\VidSum"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m vidsum --ui"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: "-m vidsum --ui"; WorkingDir: "{app}"; Description: "Uruchom VidSum"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\vidsum"
Type: filesandordirs; Name: "{app}\vidsum.stare"
