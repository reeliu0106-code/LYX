#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if ! test -x .venv_compatible/bin/python; then
  python3 -m venv .venv_compatible
fi
.venv_compatible/bin/python -m pip install -r requirements.txt
.venv_compatible/bin/python -m streamlit run app.py
