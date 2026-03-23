#include "..\..\build\windows-app\assets\version.iss"

#define MyAppName "Vocal-Scriber"
#define MyAppPublisher "Alan Banks"
#define MyAppExeName "Vocal-Scriber.exe"
#define MyAppDistDir "..\..\dist\Vocal-Scriber"
#define MySetupOutputDir "..\..\dist\installer"
#define MyIconPath "..\..\build\windows-app\assets\vocal_scriber.ico"

[Setup]
AppId={{C3060A6F-822D-490C-A2CD-93D87C6E0058}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#MySetupOutputDir}
OutputBaseFilename=Vocal-Scriber-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile={#MyIconPath}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "{#MyAppDistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
