from pathlib import Path
import shutil
import subprocess
import pytest

def test_experience_drafts_preferences_and_action_boundary():
    node=shutil.which("node")
    if not node:pytest.skip("Node required")
    result=subprocess.run([node,str(Path(__file__).with_name("frontend_experience_probe.cjs"))],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stdout+result.stderr
    assert "reading preferences passed" in result.stdout


def test_notes_offline_conflicts_and_owner_isolation():
    node=shutil.which('node')
    if not node:pytest.skip('Node required')
    result=subprocess.run([node,str(Path(__file__).with_name('frontend_notes_probe.cjs'))],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stdout+result.stderr
