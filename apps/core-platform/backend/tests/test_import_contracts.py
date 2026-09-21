"""Import contracts (.importlinter) — the Zoho platform's dependency rules.

There is no CI pipeline in this repo yet, so the contracts run with the test
suite: a feature importing the transport, the platform importing a feature,
or two features importing each other fails ``pytest``.
"""

import pathlib
import subprocess
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def test_import_contracts_are_kept():
    lint_imports = pathlib.Path(sys.executable).with_name("lint-imports")
    assert lint_imports.exists(), "import-linter missing: pip install -r requirements-dev.txt"
    result = subprocess.run([str(lint_imports), "--no-cache"], cwd=BACKEND, capture_output=True, text=True,
                            timeout=300)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-2000:]
    assert "0 broken" in result.stdout
