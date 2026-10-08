#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
.venv/bin/python -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10 or later is required"'
if [[ ! -f .venv/gch-installed.txt ]]; then
  .venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
  touch .venv/gch-installed.txt
fi
exec .venv/bin/python app.py
