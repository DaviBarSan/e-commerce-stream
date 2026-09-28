"""Fail if a cloud SDK is imported outside the modules allowed to use it (spec 04 §10.4, CLAUDE.md §5).

Usage: python scripts/check_sdk_imports.py [repo_root]
"""
import ast
import sys
from fnmatch import fnmatch
from pathlib import Path

SDKS = ("confluent_kafka", "google.cloud", "boto3")
ALLOWED = (
    "telemetry/*_driver.py",
    "services/*/*/sources/*",
    "services/*/*/sinks/*",
    "scripts/*",
    "tests/*",
)
SKIP_DIRS = {".venv", ".git", "node_modules", "target", "__pycache__", ".terraform"}


def sdk_imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]
        for name in names:
            if any(name == sdk or name.startswith(sdk + ".") for sdk in SDKS):
                yield node.lineno, name


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    violations = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if SKIP_DIRS & set(path.relative_to(root).parts) or any(fnmatch(rel, pattern) for pattern in ALLOWED):
            continue
        violations += [f"{rel}:{line}: imports {name}" for line, name in sdk_imports(path)]
    if violations:
        print("Cloud SDK imports outside driver/source/sink modules:", *violations, sep="\n  ")
        sys.exit(1)
    print("check_sdk_imports: ok")


if __name__ == "__main__":
    main()
