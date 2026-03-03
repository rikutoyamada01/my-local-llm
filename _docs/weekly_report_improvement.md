# 週次レポート生成の改善内容

## 課題
`archiver.py` によって生成される週次レポートが、本来の「週次レポート形式」ではなく、直近の日報（デイリーレポート）の形式（ガントチャートや Time Distribution など）になってしまう問題がありました。

これは LLM（`qwen2.5:7b`など）の「Recency Bias（最新効果・近接バイアス）」が原因です。旧プロンプトでは、大量の `Daily Summaries` がプロンプトの最後に配置されていたため、LLM は要求された構造への指示よりも、直前に見た日報のフォーマットを模倣してしまっていました。

## 変更内容

### `PROMPT_WEEKLY` の構造最適化

1. **インプットデータの先行配置**
   `[Daily Summaries]` と `[参考情報：過去の経緯]` (RAG コンテキスト) をプロンプトの先頭に移動しました。
   
2. **指示の明確化と後方配置**
   `**Required Output Structure in Japanese**`（出力フォーマット）をログデータの後ろに配置することで、LLM が指示を「最新の情報」として認識しやすくなりました。

3. **明示的な禁止制約の追加**
   LLM が日報フォーマットを引きずらないよう、明示的に以下の出力を禁止しました：
   - ガントチャート (Gantt chart)
   - タイムライン (Time Distribution)
   
4. **Few-Shot サンプルの強化**
   `CORRECT EXAMPLE` をプロンプトの最終行に配置することで、LLM が望ましいフォーマットを強く意識できるようにしました。

## プロンプトの変更前と変更後

### Before（旧プロンプト）
```text
You are a personal project manager analyzing the past week's logs ({start_date} to {end_date}).
Create a factual weekly summary. Do NOT invent metrics or mix up projects.

[各種指示・フォーマット]

Daily Summaries:
{summaries}

[参考情報：過去の経緯]
{rag_context}
```

### After（新プロンプト）
```text
Analyze the past week's logs ({start_date} to {end_date}) provided below. Create a factual weekly executive summary.

[Daily Summaries]
{summaries}

[参考情報：過去の経緯]
{rag_context}

---

**Analysis Instructions**:
[分析指示]

**Required Output Structure in Japanese**:
(Do NOT invent metrics, mix up projects, or include Gantt charts, Time Distribution tables, or Detailed Activities. Only follow this exact markdown structure:)
[各種フォーマット・禁止事項の追加]

**CORRECT EXAMPLE**:
{examples}
```

## 期待される効果
- 週次レポートが日報のフォーマット（タイムラインや細かいアクティビティログ）に汚染されるのを防ぎます。
- 指定したフォーマット (`## 📊 週次データ`, `## 🛠 プロジェクト別進捗` など) に厳格に従ったレポートが出力されるようになります。

## まとめ
プロンプト開発における配置順序の最適化と明示的な禁止ルールの追加により、Recency Bias を緩和し、安定した形式での高品質な週次レポート生成が可能になりました。
