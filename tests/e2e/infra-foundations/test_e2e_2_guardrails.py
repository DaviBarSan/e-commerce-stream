"""E2E-2: guardrails (wrong tool version is caught, local-only files stay out of git)."""
import os
import shutil
import subprocess

from conftest import run

WRONG_TF = "0.0.1"


def test_doctor_rejects_wrong_terraform(repo_root, base_env, tmp_path):
    stub_dir = tmp_path / "stub-bin"
    stub_dir.mkdir()
    stub = stub_dir / "terraform"
    stub.write_text(f'#!/usr/bin/env bash\necho "Terraform v{WRONG_TF}"\n', newline="\n")
    stub.chmod(0o755)
    env = dict(base_env, PATH=f"{stub_dir}{os.pathsep}{base_env['PATH']}")

    result = run(["make", "doctor"], cwd=repo_root, env=env)

    assert result.returncode != 0, result.stdout
    required = next(l.split("=", 1)[1].strip() for l in (repo_root / "versions.env").read_text().splitlines()
                    if l.startswith("TERRAFORM_VERSION="))
    tf_line = next(l for l in result.stdout.splitlines() if l.startswith("terraform"))
    assert required in tf_line and WRONG_TF in tf_line and tf_line.split()[-1] == "FAIL", tf_line


def test_local_only_files_are_ignored(repo_root):
    dummies = [
        repo_root / ".env.local",
        repo_root / "terraform/envs/local/10-platform/terraform.tfstate",
        repo_root / ".terraform/providers/dummy",
    ]
    dot_tf = repo_root / ".terraform"
    dot_tf_existed = dot_tf.exists()
    created = []
    try:
        for path in dummies:
            if path.exists():
                continue  # never touch a real local file
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("dummy\n")
            created.append(path)

        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=repo_root, capture_output=True, text=True, check=True,
        ).stdout
        for needle in [".env.local", "terraform.tfstate", ".terraform/"]:
            assert needle not in status, f"{needle} is not ignored:\n{status}"
    finally:
        for path in created:
            path.unlink()
        if not dot_tf_existed:
            shutil.rmtree(dot_tf, ignore_errors=True)
