; Script generated for LocalShift Windows Packaging
; Inno Setup 6 Script

#define MyAppName "LocalShift"
#define MyAppVersion "0.14.0"
#define MyAppPublisher "LocalShift Team"
#define MyAppURL "https://github.com/localshift/localshift"
#define MyAppExeName "LocalShift.exe"

#ifndef LocalShiftSourceDir
#define LocalShiftSourceDir "..\dist\LocalShift"
#endif
#ifndef LocalShiftOutputDir
#define LocalShiftOutputDir "..\dist\installer"
#endif

[Setup]
AppId={{9D3C012B-5B74-4C2E-8E92-3FE0696E8751}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequiredOverridesAllowed=commandline dialog
OutputDir={#LocalShiftOutputDir}
OutputBaseFilename=LocalShift-Setup-{#MyAppVersion}
SetupIconFile=..\assets\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=LocalShift Windows Desktop Installer
VersionInfoCopyright=Copyright (C) 2026 LocalShift Team

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#LocalShiftSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autoprograms}\LocalShift CLI"; Filename: "{app}\localshift-cli.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
