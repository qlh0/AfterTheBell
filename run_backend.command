#!/bin/bash
set -e
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "[ERROR] .venv not found. Run setup.command first."
  read -r -n 1 -s -p "Press any key to close..."
  echo
  exit 1
fi

cd backend
exec "../.venv/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port 8756
