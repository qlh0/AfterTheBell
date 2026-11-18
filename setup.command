#!/bin/bash
set -e
cd "$(dirname "$0")"

if command -v python3.12 >/dev/null 2>&1; then
  exec python3.12 tools/setup_env.py
fi
exec python3 tools/setup_env.py
