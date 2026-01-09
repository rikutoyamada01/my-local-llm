# Module Testing Guide

このドキュメントでは、各モジュールを個別にテスト・デバッグするためのスクリプトの使用方法を説明します。

## 📋 利用可能なテストスクリプト

| スクリプト | 対象モジュール | 実行環境 | 説明 |
|-----------|--------------|---------|------|
| `test_sensor.ps1` | `sensor.py` | Host | センサーログを収集 |
| `test_cognizer.ps1` | `cognizer.py` | Docker | ログをジャーナルに変換 |
| `test_memory.ps1` | `memory.py` | Docker | ChromaDBへの接続テスト |
| `test_archiver.ps1` | `archiver.py` | Docker | 週次サマリーの生成 |
| `test_all.ps1` | 全モジュール | Mixed | すべてのテストを実行 |

---

## 🚀 使用方法

### 個別モジュールのテスト

#### 1. Sensor (ホストで実行)
```powershell
# 基本実行
.\scripts\test\test_sensor.ps1

# 詳細ログ表示
.\scripts\test\test_sensor.ps1 -Verbose
```

**出力:**
- センサーログファイル: `data/logs/sensor_log_YYYYMMDD_HHMMSS.json`
- 最新ログファイル名とサイズを表示

---

#### 2. Cognizer (Dockerで実行)
```powershell
# すべての未処理ログを処理
.\scripts\test\test_cognizer.ps1

# 特定のログファイルを処理
.\scripts\test\test_cognizer.ps1 -LogFile "data\logs\sensor_log_20260107_132619.json"

# 詳細ログ表示（ジャーナル内容も表示）
.\scripts\test\test_cognizer.ps1 -Verbose
```

**出力:**
- ジャーナルファイル: `data/journals/YYYY-MM-DD_daily.md`
- 処理済みログ: `.json.processed`拡張子に変更

**トラブルシューティング:**
- Dockerが起動していない場合はエラーになります
- LLM (Ollama) が起動していることを確認してください

---

#### 3. Memory (Dockerで実行)
```powershell
# ChromaDB接続テスト
.\scripts\test\test_memory.ps1

# 詳細ログ表示
.\scripts\test\test_memory.ps1 -Verbose
```

**動作:**
1. ChromaDBコンテナを自動起動
2. MemoryManagerの初期化
3. テストデータの挿入
4. クエリのテスト

---

#### 4. Archiver (Dockerで実行)
```powershell
# 週次サマリー生成
.\scripts\test\test_archiver.ps1

# 詳細ログ表示
.\scripts\test\test_archiver.ps1 -Verbose
```

**出力:**
- 週次サマリーファイル: `data/journals/weekly_YYYY_WXX.md`

---

### すべてのモジュールをテスト

```powershell
# 全テスト実行
.\scripts\test\test_all.ps1

# 特定のモジュールをスキップ
.\scripts\test\test_all.ps1 -SkipSensor -SkipMemory

# 詳細ログ表示
.\scripts\test\test_all.ps1 -Verbose
```

**出力例:**
```
=====================================
  Module Test Suite
=====================================

Sensor  : ✓ PASS
Memory  : ✓ PASS
Cognizer: ✓ PASS
Archiver: ✓ PASS

=====================================
```

---

## 🔧 トラブルシューティング

### エラー: "Docker is not running"

**原因:** Docker Desktopが起動していない

**解決策:**
```powershell
# Docker Desktopを起動
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"

# 起動を待つ（約30秒〜1分）
Start-Sleep -Seconds 60

# 再度テスト実行
.\scripts\test\test_cognizer.ps1
```

---

### エラー: "ModuleNotFoundError: No module named 'ollama'"

**原因:** Pythonモジュールが直接実行されている（Dockerを使用していない）

**解決策:**
- `sensor.py`以外のモジュールは必ずDockerコンテナ内で実行してください
- `test_cognizer.ps1`などのスクリプトを使用してください

---

### エラー: "Failed to connect to ChromaDB"

**原因:** ChromaDBコンテナが起動していない

**解決策:**
```powershell
# ChromaDBを手動起動
docker compose up -d chromadb

# 起動を確認
docker compose ps

# 再度テスト実行
.\scripts\test\test_memory.ps1
```

---

### Cognizerのデバッグ

LLMの出力を確認したい場合:

```powershell
# パイプラインログを確認
Get-Content data\logs\pipeline.log -Tail 100

# Dockerコンテナのログを確認
docker compose logs core
```

---

## 📊 ログファイルの確認

### センサーログ
```powershell
# 最新のセンサーログを確認
$latest = Get-ChildItem data\logs\sensor_log_*.json | Sort LastWriteTime -Desc | Select -First 1
Get-Content $latest.FullName | ConvertFrom-Json | ConvertTo-Json -Depth 10
```

### ジャーナルファイル
```powershell
# 最新のジャーナルを確認
$latest = Get-ChildItem data\journals\*_daily.md | Sort LastWriteTime -Desc | Select -First 1
Get-Content $latest.FullName
```

---

## 🎯 開発ワークフロー

### 1. Cognizerのプロンプト改善をテスト

```powershell
# 1. cognizer.pyを編集
code modules\cognizer.py

# 2. 既存のログで再テスト（.processedを削除）
Rename-Item "data\logs\sensor_log_20260107_132619.json.processed" -NewName "sensor_log_20260107_132619.json"

# 3. テスト実行
.\scripts\test\test_cognizer.ps1 -LogFile "data\logs\sensor_log_20260107_132619.json" -Verbose

# 4. 結果を確認
Get-Content data\journals\2026-01-07_daily.md
```

### 2. フルパイプラインテスト

```powershell
# 1. センサーでデータ収集
.\scripts\test\test_sensor.ps1

# 2. Cognizerで処理
.\scripts\test\test_cognizer.ps1

# 3. 結果確認
.\scripts\test\test_all.ps1
```

---

## ⚠️ 注意事項

1. **sensor.py は直接実行可能**
   - ホストマシンのPython環境で実行されます
   - 必要なパッケージ: `pywin32`, `psutil`, `browser-history`

2. **その他のモジュールはDocker必須**
   - `ollama`, `chromadb`, `tiktoken`などの依存関係がDockerイメージに含まれています
   - 直接実行すると依存関係エラーになります

3. **テストデータの管理**
   - テストで生成されたログファイルは実際のデータと同じ場所に保存されます
   - 必要に応じてバックアップを取ってください

4. **並列実行は避ける**
   - 複数のテストスクリプトを同時に実行しないでください
   - Dockerコンテナの競合が発生する可能性があります
