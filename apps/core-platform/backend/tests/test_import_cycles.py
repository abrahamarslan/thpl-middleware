"""Every Zoho module must import cleanly as the FIRST module of a fresh process.

The test suite imports modules in one order; a CLI command or a worker can
import them in another. A cycle (ERRORS E33: switches → core.errors →
core/__init__ → transport → switches) only shows when the "wrong" module is
imported first — so each one gets its own interpreter.
"""

import pathlib
import subprocess
import sys

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
ROOTS = ["app/modules/zoho", "app/modules/organizations", "app/modules/currencies", "app/modules/taxes",
         "app/modules/locations", "app/modules/zoho_users", "app/modules/tenants", "app/modules/roles",
         "app/database", "app/tasks"]


def _modules() -> list[str]:
    found = []
    for root in ROOTS:
        for path in sorted((BACKEND / root).rglob("*.py")):
            rel = path.relative_to(BACKEND).with_suffix("")
            parts = list(rel.parts)
            if parts[-1] == "__init__":
                parts = parts[:-1]
            found.append(".".join(parts))
    return found


def test_each_module_imports_first_in_a_fresh_interpreter():
    # One subprocess importing each module in its own child keeps this fast.
    script = (
        "import subprocess, sys\n"
        "failed = []\n"
        f"for m in {_modules()!r}:\n"
        "    r = subprocess.run([sys.executable, '-c', f'import {m}'], capture_output=True, text=True)\n"
        "    if r.returncode:\n"
        "        failed.append((m, r.stderr.strip().splitlines()[-1] if r.stderr.strip() else '?'))\n"
        "print(failed)\n"
        "sys.exit(1 if failed else 0)\n"
    )
    result = subprocess.run([sys.executable, "-c", script], cwd=BACKEND, capture_output=True, text=True,
                            timeout=600)
    if result.returncode:
        pytest.fail(f"modules that fail as first import: {result.stdout[-4000:]}")
