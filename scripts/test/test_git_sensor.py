import sys
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

# Add modules directory to path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(BASE_DIR / "modules"))

try:
    import sensor
except ImportError as e:
    print(f"Could not import sensor: {e}")
    sys.exit(1)

class TestGitSensor(unittest.TestCase):
    def setUp(self):
        # Mock config
        sensor.config.git_repos = []
        sensor.config.git_base_folders = ["C:/fake/base"]
        sensor.config.git_author = "yamadarikuto"

    @patch("shutil.which")
    @patch("sensor.Path")
    @patch("subprocess.run")
    def test_get_git_activity_discovery(self, mock_run, mock_path_class, mock_which):
        # Mock git existence
        mock_which.return_value = "/usr/bin/git"
        
        # Setup mock paths for C:/fake/base/repo_a and C:/fake/base/folder_1/repo_b
        base_mock = MagicMock()
        repo_a_mock = MagicMock()
        repo_a_git_mock = MagicMock()
        folder_1_mock = MagicMock()
        repo_b_mock = MagicMock()
        repo_b_git_mock = MagicMock()
        
        # Configure name and existence
        base_mock.name = "base"
        repo_a_mock.name = "repo_a"
        folder_1_mock.name = "folder_1"
        repo_b_mock.name = "repo_b"
        
        # Set exists() to False by default for all mocks
        for m in [base_mock, repo_a_mock, repo_a_git_mock, folder_1_mock, repo_b_mock, repo_b_git_mock]:
            m.exists.return_value = False
            
        base_mock.exists.return_value = True
        repo_a_mock.exists.return_value = True
        folder_1_mock.exists.return_value = True
        repo_b_mock.exists.return_value = True
        
        # Mocking Path(base)
        mock_path_class.side_effect = lambda p: base_mock if p == "C:/fake/base" else MagicMock()
        
        # Mocking / operator
        def base_div(x):
            if x == "repo_a": return repo_a_mock
            if x == "folder_1": return folder_1_mock
            res = MagicMock()
            res.exists.return_value = False
            return res
        base_mock.__truediv__.side_effect = base_div
        
        def repo_a_div(x):
            if x == ".git": return repo_a_git_mock
            res = MagicMock()
            res.exists.return_value = False
            return res
        repo_a_mock.__truediv__.side_effect = repo_a_div
        repo_a_git_mock.exists.return_value = True
        
        def folder_1_div(x):
            if x == "repo_b": return repo_b_mock
            res = MagicMock()
            res.exists.return_value = False
            return res
        folder_1_mock.__truediv__.side_effect = folder_1_div
        
        def repo_b_div(x):
            if x == ".git": return repo_b_git_mock
            res = MagicMock()
            res.exists.return_value = False
            return res
        repo_b_mock.__truediv__.side_effect = repo_b_div
        repo_b_git_mock.exists.return_value = True
        
        # Mock iterdir
        base_mock.iterdir.return_value = [repo_a_mock, folder_1_mock]
        folder_1_mock.iterdir.return_value = [repo_b_mock]
        repo_a_mock.iterdir.return_value = []
        repo_b_mock.iterdir.return_value = []
        
        # Mock is_dir
        repo_a_mock.is_dir.return_value = True
        folder_1_mock.is_dir.return_value = True
        repo_b_mock.is_dir.return_value = True
        
        # Mock git log output
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="hash1|msg|2026-02-23 10:00:00 +0900|author",
            stderr=""
        )
        
        activity = sensor.get_git_activity(hours=24)
        
        # Should discover repo_a and repo_b
        repos_found = [a["repo"] for a in activity]
        self.assertIn("repo_a", repos_found)
        self.assertIn("repo_b", repos_found)
        self.assertEqual(len(activity), 2)

    @patch("shutil.which")
    @patch("pathlib.Path.exists")
    @patch("subprocess.run")
    def test_git_author_flag(self, mock_run, mock_exists, mock_which):
        # Mock git existence and repo existence
        mock_which.return_value = "/usr/bin/git"
        mock_exists.return_value = True
        
        # Scenario 1: Author is configured
        sensor.config.git_author = "yamadarikuto"
        sensor.config.git_repos = [{"path": "C:/repo", "name": "repo"}]
        sensor.config.git_base_folders = []
        
        mock_run.return_value = MagicMock(returncode=0, stdout="h|m|t|a", stderr="")
        
        sensor.get_git_activity(hours=24)
        
        # Verify --author flag is present in the cmd list
        args, _ = mock_run.call_args
        cmd = args[0]
        self.assertIn("--author=yamadarikuto", cmd)
        
        # Scenario 2: Author is None
        sensor.config.git_author = None
        mock_run.reset_mock()
        
        sensor.get_git_activity(hours=24)
        args, _ = mock_run.call_args
        cmd = args[0]
        # Check that no --author flag is present
        author_flags = [arg for arg in cmd if arg.startswith("--author=")]
        self.assertEqual(len(author_flags), 0)

    @patch("shutil.which")
    @patch("pathlib.Path.exists")
    @patch("subprocess.run")
    def test_git_not_found(self, mock_run, mock_exists, mock_which):
        mock_which.return_value = None
        activity = sensor.get_git_activity(hours=24)
        self.assertEqual(activity, [])
        mock_run.assert_not_called()

if __name__ == "__main__":
    unittest.main()
