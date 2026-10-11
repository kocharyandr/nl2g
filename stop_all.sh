#!/bin/bash
# Останавливает сервисы, запущенные start_all.sh (по PID-файлам и по портам). Redis и Ollama не трогает.
cd "$(dirname "$0")"
for f in logs/pids/*.pid; do [ -f "$f" ] || continue; kill "$(cat "$f")" 2>/dev/null; rm -f "$f"; done
for p in 8500 8080 8010 8001 8600 7861; do lsof -nP -iTCP:$p -sTCP:LISTEN -t 2>/dev/null | xargs kill 2>/dev/null; done
echo "сервисы остановлены (Redis и Ollama работают дальше; ollama stop / redis-cli shutdown — вручную)"
