#!/bin/bash
# Сводка прогресса замеров в терминал: bash scripts/status.sh   (или watch -n 30 bash scripts/status.sh)
cd "$(dirname "$0")/.." && .venv/bin/python scripts/progress.py --once
