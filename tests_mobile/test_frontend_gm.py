"""Offline regression for the actual shipped bounded-assistant browser script."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_frontend_bounded_assistant_preserves_request_and_choice_authority():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the browser-script regression")
    probe = Path(__file__).with_name("frontend_gm_probe.cjs")
    result = subprocess.run([node, str(probe)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Bounded GM frontend scenarios passed" in result.stdout
