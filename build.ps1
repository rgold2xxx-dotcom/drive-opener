<#
.SYNOPSIS
  ホストを exe 化（PyInstaller、onedir・窓なし）し、インストーラー（Inno Setup）を作る。
.DESCRIPTION
  出力:
    dist\drive_opener\drive_opener.exe     … ホスト本体（フォルダごと配布物に入る）
    dist\DriveOpenerSetup-<版>.exe         … 利用者に配るインストーラー
  バージョンは host\drive_opener.py の VERSION をそのまま使う（インストーラーと揃える）。
.PARAMETER SkipInstaller
  exe 化だけ行い、インストーラーは作らない。
.PARAMETER Iscc
  ISCC.exe のパス。省略時は PATH と標準の導入先（Inno Setup 7 / 6）から探す。
#>
param(
  [switch]$SkipInstaller,
  [string]$Iscc
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$m = Select-String -Path (Join-Path $root 'host\drive_opener.py') -Pattern '^VERSION = "([0-9.]+)"'
if (-not $m) { throw 'host\drive_opener.py から VERSION を読めませんでした' }
$version = $m.Matches[0].Groups[1].Value
Write-Host "ホストのバージョン: $version"

# ---- 1. exe 化（PyInstaller） ----
# --noconsole: コンソール窓を出さない（標準入出力のパイプはこの形式でも使えることを確認済み）
python -m PyInstaller --noconfirm --clean --onedir --noconsole `
  --name drive_opener `
  --icon (Join-Path $root 'installer\drive_opener.ico') `
  --distpath (Join-Path $root 'dist') `
  --workpath (Join-Path $root 'build\pyinstaller') `
  --specpath (Join-Path $root 'build') `
  (Join-Path $root 'host\drive_opener.py')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller が失敗しました（終了コード $LASTEXITCODE）" }
$exe = Join-Path $root 'dist\drive_opener\drive_opener.exe'
Write-Host "exe: $exe"

# ---- （署名する場合）ここでホストの exe に署名する ----
# signtool sign /fd sha256 /tr <タイムスタンプURL> /td sha256 /f <証明書> "$exe"

if ($SkipInstaller) { return }

# ---- 2. インストーラー（Inno Setup） ----
if (-not $Iscc) {
  $cands = @()
  $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
  if ($cmd) { $cands += $cmd.Source }
  $cands += @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
  )
  $Iscc = $cands | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
  if (-not $Iscc) { throw 'ISCC.exe が見つかりません。Inno Setup を入れるか、-Iscc でパスを指定してください。' }
}
& $Iscc "/DAppVersion=$version" (Join-Path $root 'installer\drive_opener.iss')
if ($LASTEXITCODE -ne 0) { throw "ISCC が失敗しました（終了コード $LASTEXITCODE）" }
$setup = Join-Path $root "dist\DriveOpenerSetup-$version.exe"
Write-Host "インストーラー: $setup"

# ---- （署名する場合）ここでインストーラーに署名する（SmartScreen の警告を減らすには主にこちら） ----
# signtool sign /fd sha256 /tr <タイムスタンプURL> /td sha256 /f <証明書> "$setup"
