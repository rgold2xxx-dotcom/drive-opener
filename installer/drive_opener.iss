; Drive Opener ホストのインストーラー（Inno Setup 7）
; ビルドは build.ps1 から行う： ISCC /DAppVersion=<ホストのバージョン> installer\drive_opener.iss
;
; - 現在のユーザーだけに入れる（管理者権限不要）。導入先は %LOCALAPPDATA%\DriveOpener
; - Chrome 専用（2026-11-21 ユーザーの判断）。Chrome の HKCU に登録する
; - install.ps1（開発用、.bat＋Python）で入れた環境の上にも入れられる。古いファイルは消して exe に切り替える

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Drive Opener"
#define HostName "com.rgold.drive_opener"
; ホストを呼べる拡張のID（ストア登録後はストア版のIDもここに足す。カンマ区切りで "chrome-extension://<ID>/" を並べる）
#define AllowedOrigins '"chrome-extension://ljnhnecldkgkeoahiiaccikkklljecmf/"'

[Setup]
AppId={{6E0C3B8E-2F4A-4C7B-9D61-8A3F5E2B7C10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} ホスト {#AppVersion}
AppPublisher={#AppName}
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} ホストのインストーラー
UninstallDisplayName={#AppName} ホスト
UninstallDisplayIcon={app}\drive_opener.exe
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=
DefaultDirName={localappdata}\DriveOpener
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=DriveOpenerSetup-{#AppVersion}
SetupIconFile=drive_opener.ico
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
; コード署名をする場合は、ここに SignTool=... を足す（build.ps1 の「署名」の箇所も参照）

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Messages]
japanese.FinishedHeadingLabel=インストールが完了しました
japanese.FinishedLabelNoIcons=Drive Opener のホストをインストールしました。%n%nChrome で Drive Opener の設定画面を開き、「再確認」を押すと「導入済み」になります。%n%n認識されないときは、Chrome の窓をすべて閉じてから開き直してください。
japanese.FinishedLabel=Drive Opener のホストをインストールしました。%n%nChrome で Drive Opener の設定画面を開き、「再確認」を押すと「導入済み」になります。%n%n認識されないときは、Chrome の窓をすべて閉じてから開き直してください。

[InstallDelete]
; install.ps1 版（.bat＋Python）のファイルと、前のバージョンのライブラリを消す
Type: files; Name: "{app}\drive_opener.bat"
Type: files; Name: "{app}\drive_opener.py"
Type: files; Name: "{app}\drivefs.py"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\drive_opener\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Registry]
; 既定値に、導入先のマニフェストのフルパスを入れる。アンインストールでキーごと消す
Root: HKCU; Subkey: "Software\Google\Chrome\NativeMessagingHosts\{#HostName}"; ValueType: string; ValueName: ""; ValueData: "{app}\{#HostName}.json"; Flags: uninsdeletekey
; 以前の開発版は Edge にも登録していた。その登録が残っていれば消し、アンインストールでも消す（作り直さない）
Root: HKCU; Subkey: "Software\Microsoft\Edge\NativeMessagingHosts\{#HostName}"; ValueType: none; Flags: deletekey dontcreatekey uninsdeletekey

[UninstallDelete]
Type: files; Name: "{app}\{#HostName}.json"
Type: files; Name: "{app}\host.log"
Type: files; Name: "{app}\host.log.1"
Type: dirifempty; Name: "{app}"

[Code]
// ホストのマニフェスト（JSON）を書き出す。path は導入先の exe を指す
function JsonEscape(const S: String): String;
begin
  Result := S;
  StringChangeEx(Result, '\', '\\', True);
  StringChangeEx(Result, '"', '\"', True);
end;

procedure WriteHostManifest();
var
  Json: String;
begin
  Json :=
    '{' + #13#10 +
    '  "name": "{#HostName}",' + #13#10 +
    '  "description": "Drive Opener native host (opens Google Drive for desktop folders in Explorer)",' + #13#10 +
    '  "path": "' + JsonEscape(ExpandConstant('{app}\drive_opener.exe')) + '",' + #13#10 +
    '  "type": "stdio",' + #13#10 +
    '  "allowed_origins": [{#AllowedOrigins}]' + #13#10 +
    '}' + #13#10;
  if not SaveStringToFile(ExpandConstant('{app}\{#HostName}.json'), Json, False) then
    RaiseException('マニフェストを書き込めませんでした: ' + ExpandConstant('{app}\{#HostName}.json'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    WriteHostManifest();
end;
