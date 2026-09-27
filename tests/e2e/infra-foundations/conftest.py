import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

# Targets required by spec 01 §9, plus e2e.
EXPECTED_TARGETS = ["help", "doctor", "init", "plan", "up", "down", "env", "smoke", "fmt", "validate", "e2e"]


def run(cmd, cwd, env=None):
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=120)


@pytest.fixture
def repo_root():
    return REPO_ROOT


@pytest.fixture
def base_env():
    return dict(os.environ)
