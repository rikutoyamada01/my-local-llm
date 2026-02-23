import sys
import json
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

# Add modules directory to path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(BASE_DIR / "modules"))

# Mock ollama
sys.modules["ollama"] = MagicMock()
# Mock chromadb and memory
sys.modules["chromadb"] = MagicMock()
sys.modules["memory"] = MagicMock()

try:
    from cognizer import process_logs
    import cognizer
except ImportError as e:
    print(f"Could not import cognizer: {e}")
    sys.exit(1)

class TestCognizerGit(unittest.TestCase):
    def setUp(self):
        self.test_log = BASE_DIR / "data" / "logs" / "test_git_activity.json"
        
        # Mock journals dir
        self.test_journals = BASE_DIR / "data" / "journals_test"
        self.test_journals.mkdir(parents=True, exist_ok=True)
        cognizer.JOURNALS_DIR = self.test_journals
        
        # Mock ollama client
        cognizer.client = MagicMock()
        cognizer.client.chat.return_value = {
            'message': {'content': '### 要約\nテスト要約'}
        }

    @patch("memory.MemoryManager")
    def test_git_section_generation(self, mock_memory):
        # Ensure the test log exists
        with open(self.test_log, "w", encoding="utf-8") as f:
            json.dump({
                "date": "2026-02-23T23:59:59+09:00",
                "timeline": [],
                "git_activity": [
                    {
                        "repo": "my-local-llm",
                        "commits": [
                            {
                                "hash": "abc1234",
                                "message": "feat: test commit",
                                "timestamp": "2026-02-23 23:00:00 +0900",
                                "author": "tester"
                            }
                        ]
                    }
                ]
            }, f)
            
        process_logs(self.test_log)
        
        # Check generated file
        journal_file = self.test_journals / "2026-02-23_daily.md"
        self.assertTrue(journal_file.exists())
        
        with open(journal_file, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("## 🔨 今日のコミット", content)
            self.assertIn("### my-local-llm", content)
            self.assertIn("`abc1234` feat: test commit", content)

if __name__ == "__main__":
    unittest.main()
