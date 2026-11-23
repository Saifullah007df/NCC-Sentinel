#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
[ -f .env ] || { echo 'Create .env from .env.example'; exit 1; }
set -a; source .env; set +a
exec uvicorn app:app --host 127.0.0.1 --port 8000
