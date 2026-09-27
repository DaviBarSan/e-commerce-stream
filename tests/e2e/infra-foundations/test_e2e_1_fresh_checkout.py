"""E2E-1: a fresh checkout is ready (make doctor + make help)."""
import shutil
import subprocess

import pytest
from conftest import EXPECTED_TARGETS, run


@pytest.fixture
def fresh_checkout(repo_root, tmp_path):
    """Copy what a clone would contain: tracked files plus new, non-ignored files.

    Ignored local files (.env*, state, .venv) are left out, so the flow proves the
    checkout does not depend on them.
    """
    files = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=repo_root, capture_output=True, text=True, check=True,
    ).stdout.split("\0")
    dest = tmp_path / "checkout"
    for rel in filter(None, files):
        src = repo_root / rel
        if src.is_file():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / rel)
    return dest


def test_doctor_passes_on_fresh_checkout(fresh_checkout, base_env):
    result = run(["make", "doctor"], cwd=fresh_checkout, env=base_env)
    assert result.returncode == 0, result.stdout + result.stderr
    for tool in ["terraform", "docker", "make", "uv", "python"]:
        line = next((l for l in result.stdout.splitlines() if l.split() and l.split()[0] == tool), None)
        assert line is not None, f"{tool} missing from doctor output:\n{result.stdout}"
        cols = line.split()
        assert cols[-1] == "ok", line
        # tool, rule, required, found, status
        assert len(cols) == 5 and cols[2][0].isdigit() and cols[3][0].isdigit(), line


def test_help_lists_every_target(fresh_checkout, base_env):
    result = run(["make", "help"], cwd=fresh_checkout, env=base_env)
    assert result.returncode == 0, result.stderr
    listed = {l.split()[0] for l in result.stdout.splitlines() if l.startswith("  ")}
    assert set(EXPECTED_TARGETS) <= listed, f"missing: {set(EXPECTED_TARGETS) - listed}"
    assert "ENV defaults to local" in result.stdout
