# 日記生成の改善内容

## 変更内容

### 1. **生産性スコアリング追加**
日記に1-10のスコアを追加し、その日の効果性を評価します：
- **Focus time** (集中作業時間)
- **Work-life balance** (仕事と休憩のバランス)
- **Goal alignment** (目標との整合性)

### 2. **Deep Work分析**
単なる時間の記録ではなく、働き方のパターンを分析：
- **Long focused sessions** → 高品質な深い作業
- **Frequent context switches** → 注意散漫、効率低下

### 3. **洞察（Insights）の追加**
事実の羅列ではなく、以下の問いに基づいた洞察：
- この作業で何を**達成した**のか？
- 非効率な部分はあったか？
- パターンから何を**学べる**か？

### 4. **Tomorrow's Focus**
今日の振り返りから、明日への具体的なアクション提案

## プロンプトの変更

### Before（旧プロンプト）
```
You are a daily journal assistant.
Your job is to read a structured timeline of the user's day and write a short, cohesive summary in English.

**OUTPUT**: A single paragraph summary (approx. 3-5 sentences).
```

**問題点**:
- 単なる要約だけ（"Today I did X, Y, Z"）
- スコアなし
- 洞察なし
- 行動提案なし

### After（新プロンプト）
```
You are a reflective daily journal assistant that helps users gain insights from their day.
Your job is to analyze a structured timeline and create a meaningful reflection with scores, insights, and actionable feedback.

**ANALYSIS FRAMEWORK**:
1. Productivity Scoring (1-10)
2. Deep Work Analysis (focus vs distraction)
3. Insights (achievements, inefficiencies, learnings)
4. Emotional Context (burnout, procrastination)
```

**出力フォーマット**:
```markdown
## 🎯 Daily Reflection

### Productivity Score: 8/10
[Justification based on focus time and achievements]

### Summary
[2-3 sentences about actual accomplishments and outcomes]

### 💡 Key Insights
- [Pattern observation]
- [Efficiency note]
- [Balance assessment]

### 🚀 Tomorrow's Focus
- [Actionable recommendation]
```

## 期待される効果

### Before Example:
> Today was focused on making significant progress on the Antigravity project. The majority of time, around 89.9%, was spent working on planning and coding for this project. Notably, a substantial block of time (39 minutes) was dedicated to updating the dashboard using update_dashboard.py, which suggests that the team is moving forward with implementing key features in MyLife. Overall, today's efforts aim to bring Antigravity closer to its goals.

**問題**: 
- スコアなし
- 単なる事実の羅列
- 洞察や改善提案なし

### After Example:
> ## 🎯 Daily Reflection
>
> ### Productivity Score: 8/10
> Strong focus on Antigravity with minimal distractions. The 89.9% work time allocation and sustained dashboard development session demonstrate deep work quality.
>
> ### Summary
> I made substantial progress on the Antigravity project's dashboard implementation, dedicating nearly 40 minutes to update_dashboard.py. The high work percentage (89.9%) reflects a focused day with minimal context switching. This suggests I'm building momentum on MyLife's core features.
>
> ### 💡 Key Insights
> - **Deep Work Success**: The 39-minute uninterrupted dashboard session indicates I entered a flow state, which is optimal for complex coding tasks
> - **Project Momentum**: Continued focus on Antigravity demonstrates consistent progress toward feature completion rather than task-hopping
> - **Balanced Day**: Despite high work percentage, the presence of planned breaks prevented burnout
>
> ### 🚀 Tomorrow's Focus
> - Continue the dashboard implementation while the mental model is fresh. Consider blocking a 2-hour deep work session for maximum efficiency.

**改善点**:
✅ **8/10スコア**で一日を定量評価  
✅ **洞察**が具体的（flow state、momentum、balanced）  
✅ **Tomorrow's Focus**で明日への明確なアクション  
✅ 単なる事実ではなく、**意味**と**パターン**を抽出

## 使用方法

新しいプロンプトはすでに`modules/cognizer.py`に適用されています。次回ログファイルを処理する際に自動的に使用されます：

```bash
# 新しいログを生成
python modules/sensor.py --hours 24

# 改善されたプロンプトで日記を生成
python modules/cognizer.py data/logs/sensor_log_*.json

# 生成された日記を確認
# （Obsidianディレクトリ内の *_daily.md ファイル）
```

## まとめ

この改善により、日記は**ただの記録**から**振り返りと成長のツール**に進化します：

- **評価**: スコアで一日を定量化
- **理解**: パターンと洞察で深い学び
- **改善**: 明日への具体的なアクション

これにより、日記が単なるログではなく、生産性向上と自己成長のための**実用的なツール**になります。
