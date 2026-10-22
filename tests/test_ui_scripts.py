"""Run the browser-side UI scripts (tests/*.cjs) with Node, so they fail loudly instead of rotting.

The scripts read paths like 'app/web/app.js', so each one runs from a temporary folder holding
an 'app' link to this app folder; that works both here and in the release repo (no 'app/' prefix).
Skipped when Node is not installed.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
SCRIPTS = sorted((APP / "tests").glob("*.cjs"))
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node is not installed")
class UIScripts(unittest.TestCase):
    def test_scripts_exist(self):
        self.assertTrue(SCRIPTS)

    def test_each_script_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.symlink(APP, Path(tmp) / "app")
            for script in SCRIPTS:
                with self.subTest(script=script.name):
                    run = subprocess.run([NODE, "app/tests/" + script.name], cwd=tmp,
                                         capture_output=True, text=True, timeout=120)
                    self.assertEqual(run.returncode, 0, run.stdout[-2000:] + run.stderr[-2000:])
                    self.assertIn("PASS", run.stdout)


if __name__ == "__main__":
    unittest.main()
