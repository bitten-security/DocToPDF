; Build: iscc /DAppVersion=0.2.0 /DArch=x64 installer\DocToPDF.iss   (after `python build.py`)
; Arch = x64 | x86 (x86 build needs a 32-bit Python). The x86 installer runs on 32- and 64-bit Windows.
#ifndef Arch
  #define Arch "x64"
#endif
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{B7D2E6A4-5C1F-4E0B-9A63-0D0C2FDF0001}
AppName=DocToPDF
AppVersion={#AppVersion}
AppPublisher=Joao Bittencourt
DefaultDirName={autopf}\DocToPDF
DefaultGroupName=DocToPDF
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=DocToPDF-Setup-{#AppVersion}-{#Arch}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\DocToPDF.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
#if Arch == "x64"
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\{#Arch}\DocToPDF\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\DocToPDF"; Filename: "{app}\DocToPDF.exe"
Name: "{autodesktop}\DocToPDF"; Filename: "{app}\DocToPDF.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\DocToPDF.exe"; Description: "{cm:LaunchProgram,DocToPDF}"; Flags: nowait postinstall skipifsilent
