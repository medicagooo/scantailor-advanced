"""Real cross-process output ownership checks, on both Windows and POSIX CI."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from process_pdf_folder import directory_lock

CHILD = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from process_pdf_folder import directory_lock
try:
    with directory_lock(Path(sys.argv[2])):
        print('owned', flush=True)
        if sys.argv[3] == 'hold':
            sys.stdin.read()
except RuntimeError:
    sys.exit(7)
"""


class DirectoryLockTests(unittest.TestCase):
    def contender(self, folder):
        return subprocess.run([sys.executable, "-c", CHILD, str(SCRIPTS), str(folder), "once"],
                              capture_output=True, text=True, timeout=15)

    def test_exclusion_and_release_after_exception(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaisesRegex(ValueError, "work failed"):
                with directory_lock(root):
                    result = self.contender(root)
                    self.assertEqual(result.returncode, 7, result.stderr)
                    raise ValueError("work failed")
            result = self.contender(root)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_release_after_owner_termination(self):
        with tempfile.TemporaryDirectory() as folder:
            with subprocess.Popen([sys.executable, "-c", CHILD, str(SCRIPTS), folder, "hold"],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True) as owner:
                try:
                    # The child signals only after acquisition, avoiding timing-based races.
                    self.assertEqual(owner.stdout.readline().strip(), "owned")
                    self.assertEqual(self.contender(folder).returncode, 7)
                finally:
                    owner.terminate()
                    owner.communicate(timeout=15)
            result = self.contender(folder)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
