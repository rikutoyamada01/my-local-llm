import os
import sys
import json
import datetime
import glob
import logging
import yaml
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
from collections import defaultdict
import ollama

# --- Configuration & Setup ---
if Path("/app").exists():
    BASE_DIR = Path("/app")
else:
    try:
        BASE_DIR = Path(__file__).resolve().parent.parent
    except NameError:
        BASE_DIR = Path.cwd()

DATA_DIR = BASE_DIR / "data"
LOGS_DIR = DATA_DIR / "logs"
CONFIG_PATH = BASE_DIR / "config" / "secrets.yaml"
CATEGORIES_PATH = BASE_DIR / "config" / "categories.yaml"
SAMPLES_DIR = DATA_DIR / "samples"
UNCATEGORIZED_LOG = LOGS_DIR / "uncategorized_activities.log"

LOGS_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ConfigLoader:
    def __init__(self):
        self.config = {}
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    self.config = yaml.safe_load(f) or {}
            except Exception as e:
                logger.warning(f"Failed to load secrets.yaml: {e}")
        
        self.host = os.environ.get("OLLAMA_HOST", "http://host.docker.internal:11434")
        self.model = self.config.get("ollama_model", "llama3")
        self.fallback_model = self.config.get("fallback_model")

        
        # Path Resolution
        env_path = os.environ.get("OBSIDIAN_MOUNT_PATH")
        secret_path = self.config.get("obsidian_vault_path_host") or self.config.get("obsidian_mount_path")
        
        if env_path:
            self.journals_dir = Path(env_path)
        elif secret_path:
            self.journals_dir = Path(secret_path)
        else:
            self.journals_dir = DATA_DIR / "journals"

cfg = ConfigLoader()
JOURNALS_DIR = cfg.journals_dir
JOURNALS_DIR.mkdir(parents=True, exist_ok=True)
client = ollama.Client(host=cfg.host)

PROMPT_SYSTEM = """
あなたはユーザーのデジタルツインとして、日次活動ログを深く分析し、日本語で洞察に満ちた振り返りを書くアシスタントです。

**絶対ルール**:
1. **ハルシネーション禁止**: ログにないことは絶対に書かない。
2. **情報の「連鎖」を抽出（最重要）**: 異なるデータソース間の論理的な繋がりを見つけてください。
   - **調査から実装への流れ**: ブラウザで特定の技術やエラーを調べていた時間と、その後の関連するコード修正（Gitコミット）を繋げてください。
   - **一貫したプロジェクト進捗**: 複数のアプリ（エディタ、ターミナル、ブラウザ）を跨いだ作業が、一つの成果（コミット）に結びついている様を描写してください。
3. **脱・定型文化（マンネリ防止）**: 
   - 「毎日同じようなアドバイス」を避け、その日特有のデータ（最も長く触れていたファイル、特定の検索クエリ、コミットの質）に焦点を当ててください。
   - 「集中しましょう」「休憩を取りましょう」といった汎用的な言葉ではなく、「今日の〇〇プロジェクトの進捗は、××の理由で加速/停滞していた」といった、その日だけの具体的な分析を行ってください。
4. **継続性の重視**: 「昨日のコンテキスト」を参照し、進行中のタスクが今日どこまで進んだか、課題は解消されたかを分析してください。
5. **客観的かつ建設的なフィードバック**: 
   - 「この時間は非常に集中できており、成果も伴っている」
   - 「調べ物の時間が長引いて実装が停滞している可能性がある」
   - 「頻繁なコンテキストスイッチ（数分おきのアプリ切り替え）が記録されており、深い集中を妨げているかもしれない」
   など、ユーザーが自分の作業習慣を改善できるような具体的なアドバイスを含めてください。
6. **日本語のみ**: 英語や他言語を一切混ぜないでください。
7. **直接出力**: 「## 🎯 今日の振り返り」から始めてください。

**用語定義**:
- 「Antigravity」「Antigravity.exe」= AIツール。
- 「floorp.exe」「chrome.exe」「msedge.exe」= ブラウザ。
"""

PROMPT_USER = """
【{date} の真実】
■ 活動タイムライン:
{timeline_text}

■ 時間統計:
{stats_text}

■ Git コミット:
{git_text}

■ 昨日のコンテキスト（継続性の確認）:
{yesterday_context}

■ 今日の思考・音声メモ (Voice Memos):
{voice_context}

■ 過去の知見 (RAG):
{rag_context}

---
【出力指示】
今日の「活動」と「成果」の間の**因果関係や繋がり**を明らかにする、詳細な振り返りを作成してください。
**マンネリ化した定型的なFBは不要です。** 今日のログからしか読み取れない「特筆すべきパターンや変化」を一つ以上見つけ出し、深く掘り下げてください。

## 🎯 今日の振り返り

### 生産性スコア: X/10
[集中度、成果の質、昨日からの進捗、作業の効率性を多角的に評価。]

### 要約
[活動と成果を糸で紡ぐような4-5文のストーリー。「〇〇の調査を経て、△△の実装を完了させた」といったプロセスの繋がりを具体的に記述してください。]

### 💡 洞察
[データから読み取れるユーザーの行動特性や、作業の「流れ」に関する深い分析を2つ。汎用的なアドバイスは避け、今日のデータに基づいた独自の気づきを記述してください。]

### 🚀 明日のフォーカス
- [今日の反省や成果を踏まえた、明日一番に取り組むべき具体的な1アクション。]
"""



# --- Core Logic: Categorization ---

class Categorizer:
    def __init__(self):
        self.rules = {}
        self.section_emojis = {}
        self.load_rules()
        self.unknown_cache = set()

    def load_rules(self):
        if CATEGORIES_PATH.exists():
            with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                self.rules = data.get("categories", {})
                self.section_emojis = data.get("section_emojis", {})
        else:
            logger.warning("categories.yaml not found! Using empty rules.")

    def classify(self, app_name: str, window_title: str) -> Tuple[str, str, str]:
        """
        Returns (CategoryLabel, ActivityName, Icon)
        e.g. ("💻 Work", "Coding", "💻")
        """
        app_lower = app_name.lower()
        title_lower = window_title.lower() if window_title else ""

        # 1. Iterate through categories by priority
        sorted_cats = sorted(self.rules.items(), key=lambda x: x[1].get('priority', 999))

        for cat_key, rule in sorted_cats:
            label = rule.get('label', cat_key)
            icon = label.split()[0] if " " in label else "❓"
            
            # A. Check Specific Activities (Keyword Match in ID/Title)
            if 'activities' in rule:
                for activity in rule['activities']:
                    act_name = activity['name']
                    # strict keyword matching on title or app
                    keywords = activity.get('keywords', [])
                    for kw in keywords:
                        kw_lower = kw.lower()
                        if kw_lower in title_lower: #or kw_lower in app_lower:
                            return label, act_name, icon
            
            # B. Check App Name match (Fallback for Category)
            if 'apps' in rule:
                for target_app in rule['apps']:
                    if target_app.lower() in app_lower:
                        # Default activity for this category if no specific keyword matched
                        return label, "General", icon

        # 2. Uncategorized
        self.log_uncategorized(app_name, window_title)
        return "❓ Uncategorized", app_name, "❓"

    def log_uncategorized(self, app: str, title: str):
        sig = f"{app}::{title}"
        if sig not in self.unknown_cache:
            self.unknown_cache.add(sig)
            try:
                with open(UNCATEGORIZED_LOG, "a", encoding="utf-8") as f:
                    # Use JST (Japan Standard Time, UTC+9) for logging
                    jst = datetime.timezone(datetime.timedelta(hours=9))
                    now_jst = datetime.datetime.now(jst)
                    timestamp = now_jst.isoformat()
                    f.write(f"[{timestamp}] App: '{app}', Title: '{title}'\n")
            except Exception as e:
                logger.error(f"Failed to log uncategorized: {e}")

# --- Core Logic: Visualization ---

class TimelineVisualizer:
    def __init__(self, timeline_data: List[Dict]):
        self.raw_timeline = timeline_data
        self.categorizer = Categorizer()
        self.processed_blocks = []
        self.stats = defaultdict(int) # Duration by Category
        self.process()

    def process(self):
        """
        Refines the raw timeline:
        - Categorizes each event
        - Smooths short interruptions
        - Merges consecutive identical blocks
        """
        if not self.raw_timeline:
            return

        # 1. Initial Classification
        temp_blocks = []
        for event in self.raw_timeline:
            start = event.get("start_time")
            end = event.get("end_time")
            duration = event.get("duration", 0)
            app = event.get("app", "Unknown")
            titles = event.get("titles", [])
            main_title = titles[0] if titles else ""

            cat_label, activity, icon = self.categorizer.classify(app, main_title)
            
            temp_blocks.append({
                "start": start,
                "end": end,
                "duration": duration,
                "category": cat_label,
                "activity": activity,
                "icon": icon,
                "app": app,
                "title": main_title
            })

        # 2. Smoothing & Merging
        # Strategy: Merge block B into A if:
        # - B is very short (< 15s) AND
        # - A is "Focus" (Work/Coding) AND
        # - B is NOT a strong context switch (e.g. not Gaming)
        
        merged_blocks = []
        if not temp_blocks: return

        current = temp_blocks[0]

        for i in range(1, len(temp_blocks)):
            next_block = temp_blocks[i]
            
            # Time gap check (Important to prevent hallucination from idle apps)
            # If there is a gap > 30 minutes, do not merge even if same category
            try:
                curr_end = datetime.datetime.fromisoformat(current['end'].replace('Z', '+00:00'))
                next_start = datetime.datetime.fromisoformat(next_block['start'].replace('Z', '+00:00'))
                gap_seconds = (next_start - curr_end).total_seconds()
                is_large_gap = gap_seconds > 1800 # 30 minutes
            except:
                is_large_gap = False

            # Merge Condition 1: Same Activity AND no large gap
            if (current['category'] == next_block['category'] and 
                current['activity'] == next_block['activity'] and 
                not is_large_gap):
                current['end'] = next_block['end']
                current['duration'] += next_block['duration']
                # Append title if unique and important? Simplified for now.
                continue
            
            # Merge Condition 2: Noise Smoothing (Next block is short noise)
            is_noise = next_block['duration'] < 30 # 30 seconds threshold
            is_compatible = (current['category'] == "💻 Work") and (next_block['category'] != "🎮 Entertainment")
            
            if is_noise and is_compatible and not is_large_gap:
                # Absorb the noise
                current['end'] = next_block['end']
                current['duration'] += next_block['duration']
                continue

            # Else: Commit current and move to next
            merged_blocks.append(current)
            current = next_block
        
        merged_blocks.append(current)
        self.processed_blocks = merged_blocks

        # 3. Calculate Stats
        for b in self.processed_blocks:
            self.stats[b['category']] += b['duration']

    def generate_markdown(self) -> str:
        lines = []
        for b in self.processed_blocks:
            # Parse ISO timestamps to HH:MM in JST
            # Convert to JST (Japan Standard Time, UTC+9)
            jst = datetime.timezone(datetime.timedelta(hours=9))
            s_dt = datetime.datetime.fromisoformat(b['start'])
            e_dt = datetime.datetime.fromisoformat(b['end'])
            # Convert to JST if timestamp has timezone info
            if s_dt.tzinfo is not None:
                s_dt = s_dt.astimezone(jst)
            if e_dt.tzinfo is not None:
                e_dt = e_dt.astimezone(jst)
            s_str = s_dt.strftime("%H:%M")
            e_str = e_dt.strftime("%H:%M")
            
            duration_min = int(b['duration'] / 60)
            if duration_min < 5: continue # Skip short activities (less than 5 min)

            # Format: ### 💻 **Coding** (09:00 - 10:00) `60 min`
            #         - **App**: *Visual Studio Code*
            #         - **Detail**: Project - FileName
            
            title_clean = b['title'].replace('[', '(').replace(']', ')')
            
            lines.append(f"### {b['icon']} **{b['activity']}** ({s_str} - {e_str}) `{duration_min} min`")
            lines.append(f"- **App**: *{b['app']}*")
            lines.append(f"- **Detail**: {title_clean}")
            lines.append("") # Blank line to separate entries

        return "\n".join(lines)

    def generate_mermaid_gantt(self) -> str:
        """Generate Mermaid Gantt Chart grouped by project/app for better insights"""
        lines = ["```mermaid", "gantt", "title Activity Timeline", "dateFormat HH:mm", "axisFormat %H:%M"]
        
        # Convert to JST helper
        def to_jst(iso_str):
            jst = datetime.timezone(datetime.timedelta(hours=9))
            dt = datetime.datetime.fromisoformat(iso_str)
            if dt.tzinfo is not None:
                dt = dt.astimezone(jst)
            return dt

    def extract_project(self, block: Dict) -> str:
        """
        Extract project name from title or app dynamically.
        Improved with browser topic extraction and tool exclusion.
        """
        title = block.get('title', '')
        app = block.get('app', '')
        category = block.get('category', '')
        activity = block.get('activity', '')
        
        # 1. Browser Detection & Topic Extraction (Task 1.1)
        # Prioritize browser detection before general ' - ' split
        browsers = ['floorp.exe', 'chrome.exe', 'msedge.exe', 'firefox.exe', 'brave.exe', 'floorp', 'chrome', 'msedge', 'firefox', 'brave']
        is_browser = any(b in app.lower() for b in browsers) or "Browse" in category
        
        if is_browser:
            # Try to extract topic from title using keywords in categories.yaml
            # Sort categories by priority (Task 1.4 integration)
            sorted_cats = sorted(self.categorizer.rules.items(), key=lambda k_v: k_v[1].get('priority', 999))
            
            best_match = None
            for cat_key, rule in sorted_cats:
                if 'activities' in rule:
                    for act in rule['activities']:
                        keywords = act.get('keywords', [])
                        for kw in keywords:
                            # Use word boundary check or look for longest match to avoid "code" matching in "AtCoder"
                            if kw.lower() in title.lower() and len(kw) > 3:
                                if not best_match or len(kw) > len(best_match[0]):
                                    best_match = (kw, category)
            
            if best_match:
                return self.format_section(best_match[0], best_match[1])
            
            # Fallback to domain/site name
            if ' - ' in title:
                parts = [p.strip() for p in title.split(' - ')]
                # Usually "Title - Site - Browser" or "Title - Site"
                if len(parts) >= 2:
                    # Check if last part is browser name, if so take the one before it
                    if any(b in parts[-1].lower() for b in browsers):
                        if len(parts) >= 3: return self.format_section(parts[-2], category)
                        else: return self.format_section(parts[0], category)
                    return self.format_section(parts[-1], category)

            return self.format_section('Web', category)

        # 2. Tool name & File name exclusion (Task 1.2)
        app_clean = app.replace('.exe', '').strip()
        known_tools = [
            'Antigravity', 'Visual Studio', 'VS Code', 'Code', 'Obsidian', 'Notion',
            'PyCharm', 'IntelliJ', 'Terminal', 'PowerShell', 'Cmd', 'Floorp', 'Chrome'
        ]
        
        # Pattern: "Project - Tool - File" (common in IDEs)
        if ' - ' in title:
            parts = [p.strip() for p in title.split(' - ')]
            
            # Filter out filenames (Task 1.2: extension filtering)
            exts = ('.py', '.ts', '.js', '.cpp', '.h', '.md', '.json', '.yaml', '.yml', '.rs', '.go', '.java')
            
            for part in parts:
                # If part is not a tool name and doesn't look like a file/path
                is_tool = any(tool.lower() in part.lower() for tool in known_tools)
                is_file = part.lower().endswith(exts) or '/' in part or '\\' in part
                
                if not is_tool and not is_file and len(part) > 1:
                    return self.format_section(part, category)

        # 3. Fallback to activity or category
        if activity and activity != "General":
            return self.format_section(activity, category)
        
        return self.format_section(app_clean.title() if app_clean else "Other", category)

    def format_section(self, name: str, category: str) -> str:
        """Helper to format section name with consistent emoji (Task 1.3)"""
        # Map category label (e.g. "💻 Work") back to key (e.g. "work")
        cat_key = "default"
        for k, v in self.categorizer.rules.items():
            if v.get('label') == category:
                cat_key = k
                break
        
        emoji = self.categorizer.section_emojis.get(cat_key, self.categorizer.section_emojis.get("default", "📁"))
        return f"{emoji} {name}"

    def generate_static_summary(self) -> str:
        """Generate a factual summary based on statistics when LLM is unavailable (Part 3)"""
        total_sec = sum(self.stats.values())
        if total_sec == 0:
            return "> [!NOTE] 本日の活動記録はありませんでした。"
        
        # Sort categories by duration
        sorted_stats = sorted(self.stats.items(), key=lambda x: x[1], reverse=True)
        top_cat, top_sec = sorted_stats[0]
        
        # Calculate total hours/mins
        total_min = int(total_sec / 60)
        h, m = divmod(total_min, 60)
        total_str = f"{h}時間{m}分" if h > 0 else f"{m}分"
        
        # Calculate top category hours/mins
        top_min = int(top_sec / 60)
        th, tm = divmod(top_min, 60)
        top_str = f"{th}時間{tm}分" if th > 0 else f"{tm}分"
        
        summary = f"## 🎯 活動概要 (Best-effort)\n\n"
        summary += f"本日は合計 **{total_str}** の活動が記録されました。\n\n"
        summary += f"- 最も多くの時間を費やしたカテゴリ: **{top_cat}** ({top_str})\n"
        
        if len(sorted_stats) > 1:
            next_cat, next_sec = sorted_stats[1]
            nm = int(next_sec / 60)
            nh, nm = divmod(nm, 60)
            next_str = f"{nh}時間{nm}分" if nh > 0 else f"{nm}分"
            summary += f"- 次いで注目されたカテゴリ: **{next_cat}** ({next_str})\n"
            
        summary += "\n---\n> [!IMPORTANT]\n> **AI要約失敗に伴う自動代替テキスト:** 本日はAIモデルによる詳細な振り返り生成ができなかったため、収集された活動ログから統計に基づき、事実関係のみを抽出して概要を構成しました。"
        return summary

    def generate_mermaid_gantt(self) -> str:
        """Generate Mermaid Gantt Chart grouped by project/app for better insights"""
        lines = ["```mermaid", "gantt", "title Activity Timeline", "dateFormat HH:mm", "axisFormat %H:%M"]
        
        # Separate long tasks (>=5min) and short interruptions (<5min)
        long_tasks = []
        short_tasks = []
        
        for b in self.processed_blocks:
            s_dt = datetime.datetime.fromisoformat(b['start'])
            e_dt = datetime.datetime.fromisoformat(b['end'])
            # Convert to JST (Japan Standard Time, UTC+9)
            jst = datetime.timezone(datetime.timedelta(hours=9))
            if s_dt.tzinfo is not None: s_dt = s_dt.astimezone(jst)
            if e_dt.tzinfo is not None: e_dt = e_dt.astimezone(jst)
            
            duration_sec = (e_dt - s_dt).total_seconds()
            if duration_sec < 60: continue  # Skip <1min
            
            task = {
                'project': self.extract_project(b),
                'category': b['category'],
                'activity': b['activity'],
                'start': s_dt,
                'end': e_dt,
                'duration_min': int(duration_sec / 60),
                'title': b['title']
            }
            
            if task['duration_min'] >= 5:
                long_tasks.append(task)
            else:
                short_tasks.append(task)
        
        # Group long tasks by project
        project_tasks = defaultdict(list)
        for t in long_tasks:
            project_tasks[t['project']].append(t)
        
        # Sort projects by total time (descending)
        project_totals = {proj: sum(t['duration_min'] for t in tasks) 
                         for proj, tasks in project_tasks.items()}
        sorted_projects = sorted(project_totals.items(), key=lambda x: x[1], reverse=True)
        
        # Display long tasks by project
        for proj, total_min in sorted_projects:
            tasks = project_tasks[proj]
            lines.append(f"section {proj}")
            
            for t in tasks:
                label = t['activity']
                start = t['start'].strftime("%H:%M")
                end = t['end'].strftime("%H:%M")
                lines.append(f"{label} ({t['duration_min']}m) : {start}, {end}")
        
        # Display short interruptions as "Brief Switches" section
        if short_tasks:
            lines.append("section ⚡ Brief Switches")
            for t in short_tasks:
                label = f"{t['activity']}"
                start = t['start'].strftime("%H:%M")
                end = t['end'].strftime("%H:%M")
                # Use 'crit' to visually distinguish interruptions
                lines.append(f"{label} ({t['duration_min']}m) : crit, {start}, {end}")
        
        lines.append("```")
        return "\n".join(lines)

    def generate_stats_table(self) -> str:
        total_sec = sum(self.stats.values())
        if total_sec == 0: return ""
        
        lines = ["| Category | Time | % |", "|---|---|---|"]
        
        sorted_stats = sorted(self.stats.items(), key=lambda x: x[1], reverse=True)
        for cat, seconds in sorted_stats:
            m = int(seconds / 60)
            h = round(m / 60, 1)
            pct = round((seconds / total_sec) * 100, 1)
            lines.append(f"| {cat} | {h}h ({m}m) | {pct}% |")
            
        return "\n".join(lines)
        
    def get_text_for_llm(self) -> str:
        """Simplified text representation for the LLM prompt"""
        lines = []
        for b in self.processed_blocks:
            s_dt = datetime.datetime.fromisoformat(b['start'])
            e_dt = datetime.datetime.fromisoformat(b['end'])
            duration_min = int(b['duration'] / 60)
            if duration_min < 5: continue
            
            # Clarify app names to prevent LLM hallucination
            app_label = b['app']
            title = b['title']
            if 'antigravity' in app_label.lower():
                # Extract real project from title pattern: "ProjectName - Antigravity - FileName"
                parts = [p.strip() for p in title.split(' - ')]
                project = parts[0] if len(parts) >= 2 else "不明"
                app_label = f"Antigravity(AIアシスタント/エディタ) → プロジェクト: {project}"
            
            lines.append(f"[{b['category']}] {b['activity']} ({duration_min}m): {title} (ツール: {app_label})")
        return "\n".join(lines)

# --- Main Pipeline ---

def process_logs(log_file: Path):
    logger.info(f"Processing {log_file}...")
    
    with open(log_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    date_str = data.get("date", str(datetime.date.today()))
    safe_date = date_str.split("T")[0]
    
    # 0. Extract Git Activity (Task 2.1)
    git_activity = data.get("git_activity", [])
    git_text = ""       # For LLM prompt
    git_md_footer = ""   # For markdown display at bottom
    
    if git_activity:
        git_lines_for_llm = []
        git_footer_lines = []
        
        for repo_data in git_activity:
            repo_name = repo_data.get("repo", "Unknown")
            commits = repo_data.get("commits", [])
            
            if commits:
                if git_footer_lines:
                    git_footer_lines.append("") 
                git_footer_lines.append(f"### 🔨 {repo_name}")
                for c in commits:
                    msg = c.get("message", "")
                    ts = c.get("timestamp", "")
                    time_str = ts.split(" ")[1][:5] if " " in ts else ""
                    
                    git_lines_for_llm.append(f"[{repo_name}] {msg} ({time_str})")
                    git_footer_lines.append(f"- {msg} ({time_str})")
        
        git_text = "\n".join(git_lines_for_llm) if git_lines_for_llm else "(No commits today)"
        git_md_footer = "\n".join(git_footer_lines)
    else:
        git_text = "(No git activity recorded)"
        git_md_footer = "> [!NOTE] 本日の Git コミットはありません。"

    # 1. Visualize & Categorize
    timeline_raw = data.get("timeline", [])
    viz = TimelineVisualizer(timeline_raw)
    
    # 2. Get Yesterday's Journal (for context)
    yesterday_context = ""
    try:
        # Calculate yesterday's date
        current_dt = datetime.datetime.strptime(safe_date, "%Y-%m-%d")
        yesterday_dt = current_dt - datetime.timedelta(days=1)
        yesterday_str = yesterday_dt.strftime("%Y-%m-%d")
        yesterday_file = JOURNALS_DIR / f"{yesterday_str}_daily.md"
        
        if yesterday_file.exists():
            with open(yesterday_file, 'r', encoding='utf-8') as f:
                yesterday_content = f.read()
                # Extract only the reflection section (skip detailed activities)
                if "## 🎯 Daily Reflection" in yesterday_content:
                    reflection_start = yesterday_content.find("## 🎯 Daily Reflection")
                    reflection_end = yesterday_content.find("## 📊 Time Distribution")
                    if reflection_end > reflection_start:
                        yesterday_context = yesterday_content[reflection_start:reflection_end].strip()
                    else:
                        yesterday_context = yesterday_content[reflection_start:].strip()
                else:
                    # Fallback: take first 500 chars
                    yesterday_context = yesterday_content[:500]
                logger.info(f"Loaded yesterday's journal: {yesterday_file}")
        else:
            yesterday_context = "(No journal from yesterday)"
            logger.info("No journal found from yesterday")
    except Exception as e:
        logger.warning(f"Failed to load yesterday's journal: {e}")
        yesterday_context = "(Unable to load yesterday's journal)"
        
    # 2.5. Get Today's Voice Transcripts
    voice_context = ""
    try:
        voice_file = DATA_DIR / "audio" / "transcripts" / f"{safe_date}_voice.txt"
        if voice_file.exists():
            with open(voice_file, 'r', encoding='utf-8') as f:
                voice_content = f.read().strip()
                if voice_content:
                    voice_context = voice_content
                else:
                    voice_context = "(No voice memos recorded today)"
        else:
            voice_context = "(No voice memos recorded today)"
    except Exception as e:
        logger.warning(f"Failed to load voice transcripts: {e}")
        voice_context = "(Unable to load voice transcripts)"
    
    # 3. RAG: Retrieve Historical Insights
    rag_context = ""
    try:
        from memory import MemoryManager
        memory = MemoryManager()
        
        # Dynamic query based on today's stats and activities
        top_activities = []
        for block in viz.processed_blocks:
            if block['duration'] > 300: # Over 5m
                top_activities.append(block['activity'])
                if block['title']:
                    # Extract keywords from title
                    words = re.findall(r'\w+', block['title'].lower())
                    top_activities.extend([w for w in words if len(w) > 3])
        
        query_text = " ".join(list(set(top_activities))[:5])
        if not query_text:
            query_text = "productivity insights patterns"
        
        logger.info(f"RAG Query: {query_text}")
        
        current_dt = datetime.datetime.strptime(safe_date, "%Y-%m-%d")
        current_ts = current_dt.timestamp()
        
        past_insights = memory.query(
            query_text,
            n_results=3,
            where={"timestamp": {"$lt": current_ts}}
        )
        
        if past_insights:
            rag_lines = []
            for idx, insight in enumerate(past_insights, 1):
                # Include insights above minimum relevance threshold
                if insight.get('score', 0) > 0.3: # Lowered: old 1.2 was unreachable for older data
                    date = insight['metadata'].get('date', 'Unknown')
                    content = insight['content']
                    rag_lines.append(f"- ({date}): {content}")
            
            rag_context = "\n".join(rag_lines) if rag_lines else "(No relevant historical insights found)"
            logger.info(f"Retrieved {len(rag_lines)} relevant historical insights")
        else:
            rag_context = "(No historical insights found)"
    except Exception as e:
        logger.warning(f"RAG retrieval failed: {e}")
        rag_context = "(RAG unavailable)"
    
    # 0.1 Sensor Status & Diagnostics (Part 3)
    status_info = data.get("status", {})
    diagnostics = status_info.get("diagnostics", [])
    diag_md = ""
    if diagnostics:
        diag_lines = ["\n> [!CAUTION]", "> **センサー診断情報:** データの収集過程で以下のエラーが発生しました。一部の情報が欠落している可能性があります。"]
        for diag in diagnostics:
            diag_lines.append(f"> - {diag}")
        diag_md = "\n".join(diag_lines) + "\n"
    
    # 4. LLM Summary with context
    timeline_text = viz.get_text_for_llm()
    stats_text = viz.generate_stats_table()
    
    def clear_ollama_memory():
        """Unload all models from Ollama memory"""
        try:
            # Setting keep_alive to 0 for a non-existent request effectively unloads all models 
            # or we can send a dedicated request with keep_alive=0
            logger.info("Requesting Ollama to unload models...")
            client.generate(model=cfg.model, prompt="", keep_alive=0)
        except Exception as e:
            logger.warning(f"Failed to clear Ollama memory: {e}")

    summary = ""
    try:
        # Pre-clear memory before primary attempt
        # clear_ollama_memory() 
        
        response = client.chat(model=cfg.model, messages=[
            {"role": "system", "content": PROMPT_SYSTEM},
            {"role": "user", "content": PROMPT_USER.format(
                date=safe_date,
                timeline_text=timeline_text,
                stats_text=stats_text,
                git_text=git_text,
                yesterday_context=yesterday_context,
                voice_context=voice_context,
                rag_context=rag_context
            )}
        ], options={"num_ctx": 8192, "num_predict": 2048}, keep_alive=0)
        summary = response['message']['content']
        # Post-process: strip <thinking> blocks that leak into output
        summary = re.sub(r'<thinking>.*?</thinking>', '', summary, flags=re.DOTALL).strip()
    except Exception as e:
        error_msg = str(e).lower()
        # Fallback on memory issues OR general request failures if a fallback model exists
        should_fallback = cfg.fallback_model and (
            "memory" in error_msg or "overloaded" in error_msg or 
            "failed to load" in error_msg or "timeout" in error_msg or 
            "connection" in error_msg or "error" in error_msg
        )
        
        if should_fallback:
            logger.warning(f"Primary model failed ({error_msg}). Falling back to {cfg.fallback_model}...")
            clear_ollama_memory()
            try:
                response = client.chat(model=cfg.fallback_model, messages=[
                    {"role": "system", "content": PROMPT_SYSTEM},
                    {"role": "user", "content": PROMPT_USER.format(
                        date=safe_date,
                        timeline_text=timeline_text,
                        stats_text=stats_text,
                        git_text=git_text,
                        yesterday_context=yesterday_context,
                        voice_context=voice_context,
                        rag_context=rag_context
                    )}
                ], options={"num_ctx": 8192, "num_predict": 1024}, keep_alive=0)
                summary = response['message']['content']
                summary = f"> [!WARNING] メインモデルの不調により `{cfg.fallback_model}` を使用して生成されました。\n\n" + summary
            except Exception as fe:
                logger.error(f"Fallback LLM Error: {fe}")
                summary = "" # Trigger static summary
        else:
            logger.error(f"LLM Error (no fallback): {e}")
            summary = "" # Trigger static summary

    # 3. Final Fallback: Rule-based Static Summary (Task 3.2: Graceful Degradation)
    if not summary or "[!ERROR]" in summary:
        summary = viz.generate_static_summary()

    # 4. Assemble Markdown
    md_path = JOURNALS_DIR / f"{safe_date}_daily.md"
    
    # Ensure summary is at least a placeholder
    if not summary:
        summary = "> [!WARNING] AI要約が空です。"

    markdown_content = f"""---
date: {safe_date}
tags: [daily, digital_twin]
---
# Daily Log: {safe_date}
{diag_md}
{summary}

## 📊 Time Distribution
{viz.generate_stats_table()}

## 📅 Timeline (Gantt)
{viz.generate_mermaid_gantt()}

## ⏰ Detailed Activities
{viz.generate_markdown()}

## 🛠️ Git Activity
{git_md_footer}
"""

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown_content)
    
    logger.info(f"Saved Journal: {md_path}")
    
    # 5. Save insights to Memory (Self-Improvement Loop)
    if summary and "AI summarization failed" not in summary:
        try:
            from memory import MemoryManager
            memory = MemoryManager()
            # Extract bullet points from Key Insights section
            insight_match = re.search(r"### 💡 (?:Key Insights|洞察)\n(.*?)(?=\n\n|\n#|---|$)", summary, re.DOTALL)
            if insight_match:
                insights = insight_match.group(1).strip().split("\n")
                for insight in insights:
                    clean_insight = insight.strip("- ").strip()
                    if clean_insight:
                        memory.ingest_fact(
                            fact=clean_insight,
                            date_str=safe_date,
                            metadata={"source": "daily_journal", "type": "insight"}
                        )
                logger.info(f"Ingested {len(insights)} insights to memory.")
        except Exception as e:
            logger.warning(f"Failed to ingest insights to memory: {e}")

    # Rename processed file (Task 3: Robustness)
    new_name = log_file.with_suffix('.json.processed')
    try:
        if new_name.exists():
            new_name.unlink()
        log_file.rename(new_name)
    except Exception as e:
        logger.warning(f"Failed to rename log file {log_file} to {new_name}: {e}")
    logger.info("Done.")

def main():
    if len(sys.argv) > 1:
        log_path = Path(sys.argv[1])
        if log_path.exists():
            process_logs(log_path)
            return
        else:
            logger.error(f"File not found: {log_path}")
    else:
        # Auto-process logs
        logs = glob.glob(str(LOGS_DIR / "sensor_log_*.json"))
        for log in logs:
            process_logs(Path(log))

if __name__ == "__main__":
    main()
