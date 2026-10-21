#ifndef AppVersion
  #error AppVersion must be supplied by build_windows.py
#endif
#ifndef ProductId
  #define ProductId "Tera.Downloader.Personal"
#endif

[Setup]
AppId={#ProductId}
AppName=Tera
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}.0
DefaultDirName={localappdata}\Programs\Tera
DefaultGroupName=Tera
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
AppMutex=Local\Tera.Downloader.Application
SetupMutex=Local\Tera.Downloader.Installer
CloseApplications=no
RestartApplications=no
RestartIfNeededByRun=no
AlwaysRestart=no
UninstallDisplayIcon={app}\Tera.exe
SetupIconFile=build\Tera.ico
OutputDir=dist
OutputBaseFilename=Tera-{#AppVersion}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: desktopicon; Description: "Create a Desktop shortcut"; Flags: checkedonce

[Files]
Source: "dist\Tera\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\Tera"; Filename: "{app}\Tera.exe"; WorkingDir: "{app}"; IconFilename: "{app}\Tera.exe"; AppUserModelID: "Tera.Downloader.Personal"
Name: "{userdesktop}\Tera"; Filename: "{app}\Tera.exe"; WorkingDir: "{app}"; IconFilename: "{app}\Tera.exe"; Tasks: desktopicon; AppUserModelID: "Tera.Downloader.Personal"
