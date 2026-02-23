import sys
import unittest
from pathlib import Path

# Add modules directory to path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(BASE_DIR / "modules"))

# Mock ollama to avoid import errors in local environment
import unittest.mock as mock
mock_ollama = mock.MagicMock()
sys.modules["ollama"] = mock_ollama

try:
    from cognizer import TimelineVisualizer, Categorizer
except ImportError as e:
    print(f"Could not import cognizer: {e}")
    sys.exit(1)

class TestExtractProject(unittest.TestCase):
    def setUp(self):
        self.viz = TimelineVisualizer([])
        self.categorizer = Categorizer()

    def test_browser_topic_extraction(self):
        # Task 1.1: Browser topic extraction
        test_cases = [
            {
                "input": {"app": "floorp.exe", "title": "C++ チートシート 灰〜茶まで #AtCoder - Qiita — Ablaze Floorp"},
                "expected": "AtCoder"
            },
            {
                "input": {"app": "chrome.exe", "title": "GitHub - rikutoyamada01/my-local-llm"},
                "expected": "GitHub"
            },
            {
                "input": {"app": "msedge.exe", "title": "Stack Overflow - How to fix emoji encoding"},
                "expected": "Stack Overflow"
            }
        ]
        
        for tc in test_cases:
            block = tc['input']
            # We need to classify first because Task 1.4 suggests using that info
            cat, act, icon = self.categorizer.classify(block['app'], block['title'])
            block.update({"category": cat, "activity": act, "icon": icon})
            
            result = self.viz.extract_project(block)
            self.assertIn(tc['expected'], result, f"Failed for {block['title']}. Expected '{tc['expected']}' to be in '{result}'")

    def test_tool_name_exclusion(self):
        # Task 1.2: Prevent tool name from being project name
        test_cases = [
            {
                "input": {"app": "Antigravity.exe", "title": "my-local-llm - Antigravity - modules/cognizer.py"},
                "expected": "my-local-llm"
            },
            {
                "input": {"app": "Code.exe", "title": "mojiban - Visual Studio Code - src/main.ts"},
                "expected": "mojiban"
            }
        ]
        
        for tc in test_cases:
            block = tc['input']
            cat, act, icon = self.categorizer.classify(block['app'], block['title'])
            block.update({"category": cat, "activity": act, "icon": icon})
            result = self.viz.extract_project(block)
            self.assertIn(tc['expected'], result, f"Failed for {block['title']}")
            self.assertNotIn("Antigravity", result) if "Antigravity" not in tc['expected'] else None

    def test_file_extension_filtering(self):
        # Task 1.2: Prevent filename from being project name
        test_cases = [
            {
                "input": {"app": "cmd.exe", "title": "c.cpp"},
                "expected": "Cmd" # Or whatever fallback
            }
        ]
        # In current code 'c.cpp' might be returned as 'c.cpp'
        for tc in test_cases:
            block = tc['input']
            cat, act, icon = self.categorizer.classify(block['app'], block['title'])
            block.update({"category": cat, "activity": act, "icon": icon})
            result = self.viz.extract_project(block)
            self.assertNotIn(".cpp", result)

if __name__ == "__main__":
    unittest.main()
