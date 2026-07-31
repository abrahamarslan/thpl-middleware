#!/usr/bin/env bash
# One-shot dev helper: create the local venv and install backend deps.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -q -r requirements.txt -r requirements-dev.txt
.venv/bin/python -c 'import fastapi, sqlalchemy, celery, pytest; print("DEPS_OK")'
