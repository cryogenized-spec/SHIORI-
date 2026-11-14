#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/apps/web"
python3 -m http.server 8765 --bind 127.0.0.1
