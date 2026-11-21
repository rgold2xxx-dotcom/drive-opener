# Drive Opener（ホスト）

Web版の Google ドライブで開いているフォルダやファイルを、**Windows のエクスプローラーでワンクリックで開く** Chrome 拡張「Drive Opener」のための、パソコン側のプログラム（ホスト）です。

- 拡張は Chrome ウェブストアで配布します（準備中。このリポジトリには含みません）
- このリポジトリは、拡張から呼ばれてエクスプローラーを開くホストと、そのインストーラーです

## 必要なもの

- Windows 10 / 11（64ビット）
- Google Chrome
- [パソコン版ドライブ（Google Drive for desktop）](https://www.google.com/drive/download/)：インストールしてログインしておく
- Chrome 拡張「Drive Opener」

## ダウンロード

**[DriveOpenerSetup.exe をダウンロード](../../releases/latest/download/DriveOpenerSetup.exe)**（最新版）

過去の版と SHA-256 は [リリースの一覧](../../releases) にあります。

## インストール

1. 上のリンクから `DriveOpenerSetup.exe` をダウンロードする
2. ダウンロードしたファイルを開く（ダブルクリック）
3. 画面の案内に従って進める（**管理者権限は不要**です）
4. Chrome で Drive Opener の設定画面を開き、「再確認」を押す →「導入済み」になれば完了
   - 認識されないときは、Chrome のウィンドウをすべて閉じてから開き直し、もう一度「再確認」を押してください

### Windows の警告が出たとき

このインストーラーには、まだ**コード署名がありません**。そのため、ダウンロードや実行のときに Windows や Chrome の警告が出ることがあります。

#### Chrome でダウンロードしたときの警告

ダウンロードの一覧に「一般的にダウンロードされていないファイルです」などと出た場合は、その項目のメニューから **「保存」**（または「危険性を確認したうえで保存」）を選びます。

<!-- 画像：docs/images/chrome-download-warning.png（Chrome のダウンロード警告と「保存」の位置） -->

#### 「Windows によって PC が保護されました」と出たとき

1. 青い画面の **「詳細情報」** を押す

   <!-- 画像：docs/images/smartscreen-1.png（「Windows によって PC が保護されました」と「詳細情報」） -->

2. 表示された **「実行」** を押す

   <!-- 画像：docs/images/smartscreen-2.png（発行元「不明な発行元」と「実行」ボタン） -->

## アンインストール

Windows の「設定」→「アプリ」→「インストールされているアプリ」で **「Drive Opener ホスト」** を選び、「アンインストール」を押します。プログラムのファイルと、Chrome への登録（レジストリ）をすべて削除します。

## プライバシー

- このプログラムは、**Google ドライブのデータやファイル名を外部に送りません**。インターネットへの通信はしません
- フォルダの場所を調べるため、パソコン版ドライブがパソコン内に持っているデータベース（`%LOCALAPPDATA%\Google\DriveFS\…\metadata_sqlite_db`）を**読み取り専用**で参照します。書き換えはしません
- 動きとして行うのは、拡張から受け取った ID に対応するフォルダを調べて、エクスプローラーで開くことだけです

## しくみ

```
Chrome 拡張（ドライブのページから ID を取得）
  → Native Messaging → このホスト（%LOCALAPPDATA%\DriveOpener\drive_opener.exe）
      パソコン版ドライブのデータベースで ID → ローカルのパス（例 G:\マイドライブ\…）を求める
      → 実在を確かめて explorer.exe で開く
```

- 受け付ける要求は `ping` / `open` / `resolve` の3種類だけです。拡張からは ID だけを受け取り、パスはホストが組み立てます
- インストーラーは、現在のユーザーの範囲（`%LOCALAPPDATA%` と `HKEY_CURRENT_USER`）だけに書き込みます

## コード署名について

現在、配布しているインストーラーにはコード署名がありません。コード署名への申請を検討しています。

## 開発者向け

### ビルド

準備：Python 3.11、`python -m pip install pyinstaller`、[Inno Setup](https://jrsoftware.org/isinfo.php)（6 または 7）

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

出力：`dist\drive_opener\`（ホスト本体）と `dist\DriveOpenerSetup-<版>.exe`（インストーラー）

### テスト

```powershell
python -m unittest discover -s tests
```

### リリース

1. `host/drive_opener.py` の `VERSION` を上げてコミットする
2. タグ `host-v<版>`（例 `host-v1.0.0`）を付けて push する
3. GitHub Actions がビルドし、リリースの**下書き**にインストーラー（版付きと `DriveOpenerSetup.exe`）と `SHA256SUMS.txt` を添付する
4. 下書きの中身を確認してから公開する

## ライセンス

[MIT License](LICENSE)
