import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(probe: str) -> str:
    return subprocess.run([sys.executable, '-c', probe], capture_output=True, text=True, check=True, cwd=ROOT).stdout.strip()


def test_importing_the_app_does_not_pull_in_openai() -> None:
    assert run('import rqark_app.app, sys; print("openai" in sys.modules)') == 'False'


def test_importing_the_cloud_core_does_not_pull_in_openai() -> None:
    assert run('import rqark_app.cloud, sys; print("openai" in sys.modules)') == 'False'


def test_the_cloud_core_still_builds_a_client() -> None:
    assert run('from rqark_app.cloud.chat import CloudAgentCore; import sys; print("openai" in sys.modules)') == 'False'
