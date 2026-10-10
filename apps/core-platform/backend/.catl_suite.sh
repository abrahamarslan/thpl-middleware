#!/usr/bin/env bash
# Run the backend suite in chunks (one pytest process per chunk) against the catalogue scratch DB.
# Usage: bash .catl_suite.sh   → summary in /tmp/catl_suite.txt, per-chunk logs in /tmp/catl_suite_*.log
source /home/a2/projects/th-middleware/apps/core-platform/backend/.catl_env.sh
: > /tmp/catl_suite.txt
mapfile -t files < <(ls tests/test_*.py | sort)
files+=("tests/zoho_core" "tests/zoho_sync")
chunk=10
for ((i = 0; i < ${#files[@]}; i += chunk)); do
    part=("${files[@]:i:chunk}")
    n=$((i / chunk))
    timeout 1200 .venv/bin/python -m pytest -p no:cacheprovider -o faulthandler_timeout=300 -q "${part[@]}" \
        > "/tmp/catl_suite_${n}.log" 2>&1
    echo "chunk ${n} (exit $?): $(tail -1 /tmp/catl_suite_${n}.log)" >> /tmp/catl_suite.txt
    grep -E '^(FAILED|ERROR)' "/tmp/catl_suite_${n}.log" >> /tmp/catl_suite.txt
done
echo "DONE" >> /tmp/catl_suite.txt
