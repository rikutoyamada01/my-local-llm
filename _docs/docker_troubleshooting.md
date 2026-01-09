# Docker Desktop トラブルシューティングガイド

## 問題: Docker Desktop が起動しない

### 症状
- `docker info` を実行すると `500 Internal Server Error` が表示される
- Docker Desktop のプロセスは動いているが、サービスが停止している
- `com.docker.service` のステータスが `Stopped`

---

## 解決方法

### 方法1: 自動修復スクリプト (推奨)

```powershell
# 基本的な修復
.\scripts\fix_docker.ps1

# 強制モード（データクリーンアップ含む）
.\scripts\fix_docker.ps1 -Force
```

このスクリプトは以下を実行します:
1. Docker状態チェック
2. 全Dockerプロセスの停止
3. Dockerサービスの停止
4. (-Force使用時) ロックファイルの削除
5. Docker Desktopの再起動
6. 初期化の待機と確認

---

### 方法2: 手動での修復

#### ステップ1: すべてのDockerプロセスを停止

```powershell
# Dockerプロセスを強制終了
Get-Process | Where-Object {$_.Name -like "*docker*"} | Stop-Process -Force

# 確認
Get-Process | Where-Object {$_.Name -like "*docker*"}
```

#### ステップ2: Docker Desktopを再起動

```powershell
# Docker Desktop を起動
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"

# 初期化を待つ（1-2分）
Start-Sleep -Seconds 60
```

#### ステップ3: 動作確認

```powershell
# Docker情報を取得
docker info

# バージョン確認  
docker version
```

---

### 方法3: サービスの再起動

```powershell
# 管理者権限で実行
net stop com.docker.service
net start com.docker.service

# または
Restart-Service -Name "com.docker.service"
```

---

## それでも解決しない場合

### オプション1: WSL2のリセット

Docker DesktopがWSL2バックエンドを使用している場合:

```powershell
# WSL2を再起動
wsl --shutdown

# Docker Desktopを再起動
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
```

### オプション2: Dockerデータのリセット

**警告: これにより全てのコンテナ、イメージ、ボリュームが削除されます**

1. Docker Desktopを完全に終了
2. 以下のフォルダを削除:
   ```
   %APPDATA%\Docker
   %LOCALAPPDATA%\Docker
   ```
3. Docker Desktopを再起動

### オプション3: Docker Desktopの再インストール

1. Docker Desktopをアンインストール
2. 再起動
3. 最新版をダウンロード: https://www.docker.com/products/docker-desktop
4. インストール

---

## テストスクリプトでの回避策

Docker Desktopが起動しない場合でも、一部のモジュールはテスト可能です:

### Sensor（Dockerなしで実行可能）

```powershell
# Sensorは直接実行できます
.\test_sensor.ps1
```

### その他のモジュール（Docker必須）

Cognizer、Memory、Archiverは現時点ではDockerが必要です。将来的には、ホスト環境で実行できるバージョンを検討できます。

---

## ログの確認

### Docker Desktopのログ

Windows: `%APPDATA%\Docker\log.txt`

### Windowsイベントログ

```powershell
Get-EventLog -LogName Application -Source Docker* -Newest 20
```

---

## 予防策

### 定期的なメンテナンス

```powershell
# Dockerのクリーンアップ（週1回推奨）
docker system prune -a --volumes
```

### 自動起動の設定

Docker Desktop → Settings → General → "Start Docker Desktop when you log in" にチェック

---

## サポート情報

- **Docker公式ドキュメント**: https://docs.docker.com/desktop/troubleshoot/overview/
- **GitHubイシュー**: https://github.com/docker/for-win/issues
- **ログファイル**: `%APPDATA%\Docker\log.txt`
