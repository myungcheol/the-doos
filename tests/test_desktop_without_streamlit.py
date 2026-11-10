"""The desktop entry point must load without the retired web UI dependency."""

import os
import subprocess
import sys
import unittest
from pathlib import Path


class DesktopDependencyTests(unittest.TestCase):
    def test_desktop_import_does_not_require_streamlit(self):
        script = """
import builtins
original_import = builtins.__import__
def reject_streamlit(name, *args, **kwargs):
    if name == 'streamlit' or name.startswith('streamlit.'):
        raise AssertionError('desktop app imported Streamlit')
    return original_import(name, *args, **kwargs)
builtins.__import__ = reject_streamlit
import desktop_review
import review_core
"""
        environment = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1],
            env=environment, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
