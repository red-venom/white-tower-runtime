"""Exercise the shipped script's retry flow without live services or credentials."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_frontend_preserves_owner_and_exact_pending_request():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the browser-script regression")
    probe = Path(__file__).with_name("frontend_owner_probe.cjs")
    result = subprocess.run([node, str(probe)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Owner-bound frontend retry scenarios passed." in result.stdout
