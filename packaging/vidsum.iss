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
SetupIconFile=..\vidsum\web\vidsum.ico
UninstallDisplayIcon={app}\vidsum\web\vidsum.ico
AppId={{6B1E2C4A-8F3D-4E7B-9C21-5A0D7F3E9B14}
AppName=Vidento
AppVersion={#AppVersion}
AppVerName=Vidento {#AppVersion}
AppPublisher=Vidento
DefaultDirName={localappdata}\Programs\VidSum
DefaultGroupName=Vidento
UsePreviousGroup=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=VidSum-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
UninstallDisplayName=Vidento
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
; 0.10.0: nowa nazwa (Vidento) — stare skróty „VidSum” usuwane; folder programu i dane bez zmian
Type: filesandordirs; Name: "{userprograms}\VidSum"
Type: files; Name: "{userdesktop}\VidSum.lnk"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Vidento"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m vidsum --ui"; WorkingDir: "{app}"; IconFilename: "{app}\vidsum\web\vidsum.ico"; Comment: "Analiza filmów"
Name: "{group}\Odinstaluj Vidento"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Vidento"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m vidsum --ui"; WorkingDir: "{app}"; IconFilename: "{app}\vidsum\web\vidsum.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: "-m vidsum --ui"; WorkingDir: "{app}"; Description: "Uruchom Vidento"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\vidsum"
Type: filesandordirs; Name: "{app}\vidsum.stare"
; 0.10.0: nowa nazwa (Vidento) — stare skróty „VidSum” usuwane; folder programu i dane bez zmian
Type: filesandordirs; Name: "{userprograms}\VidSum"
Type: files; Name: "{userdesktop}\VidSum.lnk"
