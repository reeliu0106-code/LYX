#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  if command -v python3 >/dev/null 2>&1; then
    python3 -m venv .venv
  else
    echo 'Python 3.11+ required. Install Python from https://www.python.org/downloads/'
    exit 1
  fi
fi
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py
