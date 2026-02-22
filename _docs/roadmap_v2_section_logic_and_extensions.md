# Roadmap v2: セクション名ロジック修正 & 機能拡張

**Version**: 2.0  
**Date**: 2026-02-22  
**Status**: Draft / 企画書  
**Scope**: `cognizer.py` のセクション名ロジック修正 + `sensor.py` への新データソース追加

---

## 背景と目的

本プロジェクト（Local Digital Twin）は、ユーザーの日次活動を自動収集し、ローカルLLMで要約・振り返りを生成するシステムである。現在、以下の課題がある：

1. **Ganttチャートのセクション名が不正確** — ブラウザタブのタイトルやファイル名がそのままセクション名に漏洩
2. **データソースがActivityWatch + ブラウザ履歴のみ** — 開発活動の実態（Git commit等）が日記に反映されていない

本ドキュメントは、これらを解決するための **ロードマップ兼軽量企画書** である。

---

## Part 1: セクション名ロジック修正

### 現状の問題（実例: 2026-02-22_daily.md より）

| 現在のセクション名 | 問題点 | 理想的なセクション名 |
|---|---|---|
| `📁 Qiita — Ablaze Floorp` | ブラウザタブのタイトルが丸ごとリーク | `💡 AtCoder / 競技プログラミング` |
| `📁 c.cpp` | ファイル名がプロジェクト名に | `💡 AtCoder` |
| `� Antigravity` | 絵文字のエンコーディング破損 | `🔧 Antigravity` |

### 根本原因

`cognizer.py` の `extract_project()` 関数（L317-396）に以下の問題がある：

1. **ブラウザ検出の優先度が低い** — Pattern 3（Browser grouping）到達前に Pattern 1（`' - '` split）で誤マッチ
2. **ファイル拡張子フィルタリングなし** — `c.cpp`, `main.py` 等がプロジェクト名として返る
3. **絵文字ハードコード時のエンコーディング問題** — L448, L451, L456 で直接リテラルの文字化けが発生
4. **`categories.yaml` の知識を活用していない** — Categorizer と extract_project が独立

### 改善タスク

#### Task 1.1: ブラウザタイトルから「プロジェクト/トピック」を抽出するロジック追加

**現在**: ブラウザ → `'🌐 Browser'` 一括グルーピング  
**提案**: ブラウザタイトルからトピックを推定してグルーピング

```
例: "C++ チートシート 灰〜茶まで #AtCoder - Qiita — Ablaze Floorp"
     → トピック: "AtCoder"（キーワード `#AtCoder` を検出 + categories.yaml 連携）
```

**ロジック**:
1. ブラウザアプリ判定を **最優先** に変更（Pattern 1 の前に移動）
2. タイトルから `categories.yaml` のキーワードでトピック抽出
3. マッチなしの場合 → ドメイン名ベースでグルーピング（`Qiita`, `GitHub`, `YouTube` 等）
4. それでもマッチなしの場合 → `🌐 Web` にフォールバック

#### Task 1.2: ツール名・ファイル名→プロジェクト名の誤認防止

**改善**:
- **ツール名の除外**: `Antigravity`, `Floorp`, `Code (VS Code)`, `Browser` 等のツール名は、プロジェクト名としてではなく「概念/ツール」として扱う。これらがセクション名として独立して表示されるのを防ぎ、上位カテゴリ（`💻 Coding`, `🌐 Web` 等）にフォールバックさせる。
- **拡張子パターンの拒否**: 拡張子パターン（`.py`, `.ts`, `.cpp`, `.md` 等）を持つ文字列をプロジェクト名として **拒否する**。
- **階層的抽出**: IDE系ツール（Code.exe, Antigravity.exe）の場合、ウィンドウタイトルから **最初の `' - '` セグメント** をプロジェクト名として優先的に抽出する。プロジェクト名が見つからない場合は、ツール名を表示せず `💻 coding` にフォールバックする。

#### Task 1.3: 絵文字のエンコーディング修正

**改善**:
- ハードコードされた絵文字リテラルを `config/categories.yaml` 側に移行
- または `emoji_map` 辞書で管理し、ASCII名 → 絵文字変換

```yaml
# categories.yaml に追加
section_emojis:
  coding: "💻"
  browser: "🌐"
  communication: "💬"
  entertainment: "🎮"
  default: "📁"
```

#### Task 1.4: Categorizer と extract_project の統合

**現状**: 2つの独立したロジック
- `Categorizer.classify()` — カテゴリ分類（categories.yaml ベース）
- `extract_project()` — Ganttセクション名（ハードコードルール）

**改善**: extract_project が classify 結果を受け取り、整合性のあるセクション名を生成

```python
# Before: 各ブロックを独立して処理
project = extract_project(block)   # app_name と title のみ考慮

# After: カテゴリ情報も活用
project = extract_project(block, category=block['category'], activity=block['activity'])
```

---

## Part 2: 機能拡張 — 新データソースの追加

### 2.1 Git コミット履歴の取得

**目的**: 「今日何をコーディングしたか」の **事実ベース** データを日記に追加

#### 設計

```
[sensor.py] --git log--> [sensor_log.json に追加] --cognizer.py--> [日記に統合]
```

**新しいデータフロー**:

1. **sensor.py に `get_git_activity()` 関数を追加**
   - `secrets.yaml` に監視対象リポジトリリストを設定
   - 各リポジトリで `git log --since="yesterday" --format="%H|%s|%ai"` を実行
   - コミットメッセージ、タイムスタンプ、ブランチ名を収集

2. **sensor_log.json のスキーマ拡張**
   ```json
   {
     "date": "2026-02-22",
     "timeline": [...],
     "git_activity": [
       {
         "repo": "my-local-llm",
         "branch": "main",
         "commits": [
           {
             "hash": "abc1234",
             "message": "fix: extract_project のブラウザ判定を修正",
             "timestamp": "2026-02-22T23:00:00+09:00",
             "files_changed": 3
           }
         ]
       }
     ]
   }
   ```

3. **cognizer.py のプロンプトに Git コンテキストを注入**
   ```
   ---
   今日の Git コミット:
   - [my-local-llm] fix: extract_project のブラウザ判定を修正 (23:00)
   - [mojiban] feat: セル選択のUX改善 (21:15)
   ---
   ```

4. **Gantt チャートとの連携**
   - コーディング時間ブロック内にコミットメッセージをラベルとして表示可能に

#### secrets.yaml 設定例

```yaml
# 5. Git Activity Tracking
git_repos:
  - path: "C:/Users/yamadarikuto/Mycode/my-local-llm"
    name: "my-local-llm"
  - path: "C:/Users/yamadarikuto/Mycode/mojiban"
    name: "mojiban"
git_author: "yamadarikuto"  # optional: 自分のコミットのみフィルタ
```

---

### 2.2 他CLIツールからの活動取得

以下の拡張を **段階的に** 追加していく。

#### 2.2.3 GitHub Issues / PR 活動（オプション）

**目的**: 今日オープン/クローズした Issue や PR を日記に反映

**方法**:
- `gh` CLI（GitHub CLI）を利用
- `gh issue list --state all --json number,title,state,updatedAt --jq '.[] | select(.updatedAt >= "today")'`
- `gh pr list --state all --json number,title,state,updatedAt`

> [!NOTE]
> GitHub CLI はオプション機能。インストールされていない場合はスキップ。

---

### 2.3 日常生活データの統合 (Daily Life Data)

「デジタルツイン」としての完成度を高めるため、PC上の活動以外のライフログを統合する。

#### 2.3.1 スケジュールとタスク (Google Calendar / Todoist)

**目的**: 「予定していたこと」と「実際にやったこと」の乖離を分析。

**収集方法**:
- `gcalcli` を使用し、今日の予定（Events）を取得
- Todoist API や Notion API から「今日完了したタスク」を取得
- 日記にて「予定通り進んだか」の自己評価を自動生成

#### 2.3.2 環境データ (Weather / Location)

**目的**: 気象条件や作業場所が、集中力や気分に与える影響を可視化。

**収集方法**:
- `curl wttr.in` を利用し、その日の天気・気温・**気圧**を取得（気圧は体調管理に重要）
- `netsh wlan show interfaces` の SSID ログから「自宅・カフェ・学校/職場」の場所を推定

#### 2.3.3 消費メディア (Spotify / Kindle)

**目的**: 作業中のBGMや、夜のインプット（読書）を記録。

**収集方法**:
- Spotify API (Recently Played) から今日聴いた曲を収集
- ブラウザ上の Kindle / YouTube 視聴履歴を活用

---

## Part 3: 日記出力フォーマットと分析機能の拡張

### 3.1 日記セクションの追加

```
# Daily Log: YYYY-MM-DD
## 🎯 今日の振り返り         (LLM生成)
## 📊 Time Distribution       (自動計算)
## 📅 Timeline (Gantt)        (自動生成)
## ⏰ Detailed Activities     (自動生成)
```

### 提案: 新セクション追加

```
# Daily Log: YYYY-MM-DD
## 🎯 今日の振り返り         (LLM生成 - Git/CLI コンテキスト含む)
## 🔨 今日のコミット           ← NEW: Git コミット一覧
## 📊 Time Distribution       (自動計算)
## 📅 Timeline (Gantt)        (自動生成 - セクション名修正済み)
## ⏰ Detailed Activities     (自動生成)
## � 開発・生活ログ            ← NEW: Git/Docker/Weather/Tasks 等
```

---

### 3.2 生活・活動分析 (Converged Analytics) 🆕

収集した多角的なデータを掛け合わせ、LLMによる深い洞察を提供する。

#### 3.2.1 相関分析エンジン (Correlation Engine)
- **「睡眠 vs 生産性」**: 睡眠不足の日にコードの品質や集中時間（Deep Work）がどう変化したか。
- **「天気・気圧 vs 気分」**: 低気圧の日に作業効率が落ちる傾向があるか。
- **「作業場所 vs 集中力」**: 特定のカフェや場所での作業時に、最もフロー状態に入りやすいか。

#### 3.2.2 パーソナライズド・レコメンデーション
- 「今日はGitコミットが激しく、集中時間が長かったため、リラックスできる音楽（Spotify）を聴いて早めに休むことを推奨します」といったアドバイス。

---

### 3.3 便利な活用シナリオ (Usage Scenarios)

本プロジェクトが日常にどう組み込まれるかの具体例。

1. **セルフコンディショニング**: 「最近、火曜日の午後にパフォーマンスが落ちています。午前中の会議を減らすか、散歩を取り入れるのはどうでしょうか？」というフィードバック。
2. **記憶の外部化（Contextual Recall）**: 「このコードを書いた時、あなたは [カフェ名] で [曲名] を聴いていました。当時の思考プロセスは [Weekly Summary] に記録されています」という紐付け。
3. **長期成長の可視化**: 1ヶ月前の開発スキルと現在のGitコミットの複雑さを比較し、技術的な進歩を称賛する。

---

### 🔨 コミットセクションの例

```markdown
## 🔨 今日のコミット

### my-local-llm (`main`)
- `abc1234` fix: extract_project のブラウザ判定を修正 (23:00)
- `def5678` docs: roadmap v2 作成 (23:30)

### mojiban (`feature/cell-ux`)
- `789abcd` feat: セル選択時のフォーカス制御改善 (21:15)
```

---

## 実装優先度と工数見積もり

| 優先度 | タスク | 工数 | 影響範囲 |
|:---:|---|---|---|
| 🔴 P0 | Task 1.3: 絵文字エンコーディング修正 | 30min | `cognizer.py` |
| 🔴 P0 | Task 1.2: ファイル名→プロジェクト名の誤認防止 | 1h | `cognizer.py` |
| 🟠 P1 | Task 1.1: ブラウザタイトルからトピック抽出 | 2h | `cognizer.py`, `categories.yaml` |
| 🟠 P1 | Task 1.4: Categorizer ↔ extract_project 統合 | 2h | `cognizer.py` |
| 🟡 P2 | 2.1: Git コミット履歴取得 | 3h | `sensor.py`, `cognizer.py`, `secrets.yaml` |
| 🟡 P2 | 3.1: 日記フォーマット拡張（コミットセクション） | 1h | `cognizer.py` |
| 🟢 P2 | 2.3.1 - 2.3.3: 日常生活データの収集 | 4h | `sensor.py` |
| 🟢 P2 | 3.2: 相関分析ロジック (LLM Prompt) | 2h | `cognizer.py` |
| 🔵 P3 | 2.2.1: Shell 履歴解析 | 2h | `sensor.py` |
| 🔵 P3 | 2.2.2: Docker ログ収集 | 1h | `sensor.py` |
| ⚪ P4 | 2.2.3: GitHub Issues/PR | 2h | `sensor.py` |
| ⚪ P4 | 2.2.4: WSL アクティビティ | 3h | `sensor.py` |

---

## リスクと考慮事項

> [!WARNING]
> **Git リポジトリのパスはハードコードしない**。`secrets.yaml` で管理し、リポジトリが存在しない場合はスキップ。

> [!IMPORTANT]
> **プライバシー**: コミットメッセージに機密情報が含まれる可能性がある。既存の `sanitize_text()` パイプラインを通す。

- **パフォーマンス**: Git がインストールされていない環境では `subprocess` 呼び出しが失敗する → `shutil.which("git")` で事前チェック
- **文字コード**: Windows の `git log` 出力は CP932 の場合がある → `encoding="utf-8"` + `errors="replace"` で対応
- **大規模リポジトリ**: `--since` と `--author` で結果を絞り込み、大量のコミット取得を防ぐ

---

## 成功基準

1. ✅ Gantt チャートのセクション名がプロジェクト/トピック単位で正確に表示される
2. ✅ `Antigravity` や `Floorp` 等のツール名がセクション名として独立しない（概念レベルに集約される）
3. ✅ ブラウザでの活動がトピック別にグルーピングされる
4. ✅ 絵文字が正しくレンダリングされる
5. ✅ 日記に当日の Git コミット一覧が含まれる
6. ✅ LLM の振り返りが Git コミット内容を踏まえた洞察を含む
