; Instalator Vidsumly (Inno Setup 6) — budowany w GitHub Actions z paczki „-python” (portable\Vidsumly).
; Instalacja bez uprawnień administratora do %LOCALAPPDATA%\Programs\Vidsumly; skrót w menu Start (i na pulpicie);
; odinstalowanie przez Ustawienia → Aplikacje. Dane użytkownika (Dokumenty\Vidsumly, %LOCALAPPDATA%\Vidsumly) zostają.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\portable\Vidsumly"
#endif

[Setup]
SetupIconFile=..\vidsum\web\vidsum.ico
UninstallDisplayIcon={app}\Vidsumly.ico
AppId={{6B1E2C4A-8F3D-4E7B-9C21-5A0D7F3E9B14}
AppName=Vidsumly
AppVersion={#AppVersion}
AppVerName=Vidsumly {#AppVersion}
AppPublisher=Vidsumly
DefaultDirName={localappdata}\Programs\Vidsumly
; 0.13.0: instalacje z folderu „VidSum” przenoszone do „Vidsumly”; stary folder programu kasowany po zamknięciu
; działającej z niego starej wersji (PrepareToInstall niżej). Dane użytkownika nie są w nim.
UsePreviousAppDir=no
DefaultGroupName=Vidsumly
UsePreviousGroup=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=Vidsumly-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
UninstallDisplayName=Vidsumly
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "pl"; MessagesFile: "compiler:Languages\Polish.isl"

[Tasks]
Name: "desktopicon"; Description: "Skrót na pulpicie"; GroupDescription: "Skróty:"

[InstallDelete]
; 0.13.0: stary folder programu „VidSum” (do 0.12.0) — program jest teraz w „Vidsumly”
Type: filesandordirs; Name: "{localappdata}\Programs\VidSum"
; stary kod usuwany przed instalacją nowego — bez nieaktualnych plików
Type: filesandordirs; Name: "{app}\vidsum"
Type: filesandordirs; Name: "{app}\vidsum.stare"
; 0.10.0: nowa nazwa — stare skróty „VidSum” usuwane
Type: filesandordirs; Name: "{userprograms}\VidSum"
Type: files; Name: "{userdesktop}\VidSum.lnk"
; 0.10.1: ostateczna nazwa Vidsumly — usuwane też skróty „Vidento” z 0.10.0
Type: filesandordirs; Name: "{userprograms}\Vidento"
Type: files; Name: "{userdesktop}\Vidento.lnk"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; 0.13.1: ikona poza folderem „vidsum” (aktualizacja kodu go podmienia) — skróty i przypięcia jej nie gubią
Source: "..\vidsum\web\vidsum.ico"; DestDir: "{app}"; DestName: "Vidsumly.ico"; Flags: ignoreversion

[Icons]
Name: "{group}\Vidsumly"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m vidsum --ui"; WorkingDir: "{app}"; IconFilename: "{app}\Vidsumly.ico"; AppUserModelID: "Vidsumly.Aplikacja"; Comment: "Analiza filmów"
Name: "{group}\Odinstaluj Vidsumly"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Vidsumly"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m vidsum --ui"; WorkingDir: "{app}"; IconFilename: "{app}\Vidsumly.ico"; AppUserModelID: "Vidsumly.Aplikacja"; Tasks: desktopicon

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: "-m vidsum --ui"; WorkingDir: "{app}"; Description: "Uruchom Vidsumly"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\Vidsumly.ico"
Type: filesandordirs; Name: "{app}\vidsum"
Type: filesandordirs; Name: "{app}\vidsum.stare"
; 0.10.0: nowa nazwa — stare skróty „VidSum” usuwane
Type: filesandordirs; Name: "{userprograms}\VidSum"
Type: files; Name: "{userdesktop}\VidSum.lnk"
; 0.10.1: ostateczna nazwa Vidsumly — usuwane też skróty „Vidento” z 0.10.0
Type: filesandordirs; Name: "{userprograms}\Vidento"
Type: files; Name: "{userdesktop}\Vidento.lnk"

[Code]
{ 0.13.0: przed instalacją zamknij Vidsumly uruchomiony ze STAREGO folderu (Programs\VidSum). Menedżer ponownego
  uruchamiania Windows zamyka tylko programy używające plików z NOWEGO folderu, a stara wersja działała ze starego.
  Zamykane są wyłącznie procesy, których plik leży w starym folderze programu — inne programy Pythona nie są ruszane. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Old, Cmd: String;
  Code: Integer;
begin
  Result := '';
  Old := ExpandConstant('{localappdata}\Programs\VidSum');
  if DirExists(Old) then
  begin
    Cmd := '-NoProfile -ExecutionPolicy Bypass -Command "Get-Process | Where-Object { $_.Path -like ''' + Old + '\*'' } | Stop-Process -Force -ErrorAction SilentlyContinue"';
    Exec('powershell.exe', Cmd, '', SW_HIDE, ewWaitUntilTerminated, Code);
    Sleep(1000);
  end;
end;
