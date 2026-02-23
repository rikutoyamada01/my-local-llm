import sys
import json
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

# Add modules directory to path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(BASE_DIR / "modules"))

# Mock dependencies
sys.modules["ollama"] = MagicMock()
sys.modules["chromadb"] = MagicMock()
sys.modules["memory"] = MagicMock()

import cognizer

class TestFallbacks(unittest.TestCase):
    def setUp(self):
        self.test_journals = BASE_DIR / "data" / "journals_test_fallback"
        self.test_journals.mkdir(parents=True, exist_ok=True)
        cognizer.JOURNALS_DIR = self.test_journals
        
        self.test_log = BASE_DIR / "data" / "logs" / "test_fallback.json"

    def test_skeleton_journal_on_llm_failure(self):
        # 1. Setup sensor log with some errors
        log_data = {
            "date": "2026-02-23T23:59:59+09:00",
            "status": {
                "browser": "ok",
                "window": "ok",
                "git": "ok",
                "diagnostics": ["Git error in repo-x: Permission denied"]
            },
            "timeline": [
                {
                    "start_time": "2026-02-23T22:00:00+09:00",
                    "end_time": "2026-02-23T23:00:00+09:00",
                    "duration": 3600,
                    "app": "Test",
                    "titles": ["Test Title"]
                }
            ],
            "git_activity": []
        }
        
        with open(self.test_log, "w", encoding="utf-8") as f:
            json.dump(log_data, f)
            
        # 2. Mock LLM to fail
        cognizer.client.chat.side_effect = Exception("Ollama is offline")
        
        # 3. Run processing
        cognizer.process_logs(self.test_log)
        
        # 4. Verify journal exists and contains diagnostics + skeleton
        journal_file = self.test_journals / "2026-02-23_daily.md"
        self.assertTrue(journal_file.exists())
        
        with open(journal_file, "r", encoding="utf-8") as f:
            content = f.read()
            # Diagnostics should be there
            self.assertIn("> [!CAUTION]", content)
            self.assertIn("Git error in repo-x: Permission denied", content)
            # Static "Graceful Degradation" summary should be there with explicit disclaimer
            self.assertIn("## 🎯 活動概要 (Best-effort)", content)
            self.assertIn("AI要約失敗に伴う自動代替テキスト", content)
            self.assertIn("本日は合計 **1時間0分** の活動が記録されました。", content)

    @patch("cognizer.client.chat")
    def test_model_fallback_logic(self, mock_chat):
        # Setup: Primary fails, Fallback succeeds
        cognizer.cfg.fallback_model = "fallback-m"
        
        def chat_side_effect(model, **kwargs):
            if model == cognizer.cfg.model:
                raise Exception("Primary overloaded")
            return {"message": {"content": "Fallback summary"}}
        
        mock_chat.side_effect = chat_side_effect
        
        # Run
        log_data = {
            "date": "2026-02-23T23:59:59+09:00",
            "timeline": [{
                "start_time": "2026-02-23T22:00:00+09:00", 
                "end_time": "2026-02-23T23:00:00+09:00", 
                "duration": 3600, 
                "app": "Code", 
                "titles": ["Working on Test"]
            }]
        }
        with open(self.test_log, "w", encoding="utf-8") as f:
            json.dump(log_data, f)
            
        cognizer.process_logs(self.test_log)
        
        journal_file = self.test_journals / "2026-02-23_daily.md"
        with open(journal_file, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("メインモデルの不調により `fallback-m` を使用して生成されました。", content)
            self.assertIn("Fallback summary", content)

    @patch("cognizer.client.chat")
    def test_best_effort_pipeline_with_missing_data(self, mock_chat):
        # Scenario: Git activity missing, but window timeline exists
        log_data = {
            "date": "2026-02-23T23:59:59+09:00",
            "timeline": [{
                "start_time": "2026-02-23T22:00:00+09:00", 
                "end_time": "2026-02-23T23:00:00+09:00", 
                "duration": 3600, 
                "app": "Code", 
                "titles": ["main.py - Working locally"]
            }],
            "git_activity": [] # Missing
        }
        with open(self.test_log, "w", encoding="utf-8") as f:
            json.dump(log_data, f)
            
        mock_chat.return_value = {"message": {"content": "Success content"}}
        
        cognizer.process_logs(self.test_log)
        
        # Verify LLM was called with the available timeline even if git was missing
        args, kwargs = mock_chat.call_args
        prompt_content = kwargs['messages'][1]['content']
        self.assertIn("2026-02-23", prompt_content)
        self.assertIn("(No git activity recorded)", prompt_content)
        self.assertIn("Coding (60m)", prompt_content)

if __name__ == "__main__":
    unittest.main()
