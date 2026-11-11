#!/usr/bin/env bash
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Python 3 belum terpasang."; exit 1; }
[ -d .venv ] || python3 -m venv .venv || { echo "Gagal membuat venv"; exit 1; }
. .venv/bin/activate
python -m pip install -q -r requirements.txt || { echo "Gagal pip install"; exit 1; }
echo "Buka http://localhost:5000"
python run.py
