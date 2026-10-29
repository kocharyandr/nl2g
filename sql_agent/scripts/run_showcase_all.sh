#!/bin/bash
# Примеры для презентации: графики (не столбцы) → правки диффузией → судья. Лог: ПРИМЕРЫ_ДЛЯ_ПРЕЗЕНТАЦИИ/run.log
set -u
cd "$(dirname "$0")/.."
OUT=ПРИМЕРЫ_ДЛЯ_ПРЕЗЕНТАЦИИ
log() { echo "=== $(date +%H:%M:%S) $*" >&2; }
unload() { for m in "$@"; do curl -s localhost:11434/api/generate -d "{\"model\":\"$m\",\"keep_alive\":0}" >/dev/null; done; }
stop_diffusion() { lsof -nP -iTCP:8001 -sTCP:LISTEN -t | xargs kill 2>/dev/null; sleep 3; }
log "фаза 1/3: графики"
stop_diffusion
.venv/bin/python scripts/run_showcase.py -o $OUT --phase chart
log "фаза 2/3: правки диффузией"
# оркестратор с настоящей диффузией, а не заглушкой
lsof -nP -iTCP:8010 -sTCP:LISTEN -t | xargs kill 2>/dev/null; sleep 2
(cd ../chart_agent && OPENAI_API_BASE=http://127.0.0.1:11434/v1 OPENAI_API_KEY=ollama OPENAI_MODEL_NAME=qwen2.5-coder:14b \
  SQL_AGENT_ENABLED=true SQL_AGENT_URL=http://127.0.0.1:8500 CODE_EXECUTOR_URL=http://127.0.0.1:8080 \
  STATE_STORE_REDIS_ENABLED=true STATE_STORE_REDIS_URL=redis://127.0.0.1:6379/0 LANGFUSE_ENABLED=false GUARDRAILS_ENABLED=false \
  EDIT_USE_STUB=false EDIT_SERVICE_URL=http://127.0.0.1:8001/edit DIFFUSION_HOST=127.0.0.1 DIFFUSION_PORT=8001 DIFFUSION_TIMEOUT_SEC=900 \
  nohup .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8010 > ../logs/chart_agent.log 2>&1 &)
for i in $(seq 1 30); do curl -s --max-time 3 localhost:8010/docs >/dev/null && break; sleep 2; done
unload nl2sql-schema nl2sql-sql nl2sql-critic qwen2.5vl:7b
(cd ../diffusion_service && env -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy -u HF_TOKEN HF_HUB_OFFLINE=1 nohup .venv/bin/python app.py > "$PWD/../sql_agent/$OUT/diffusion.log" 2>&1 &)
for i in $(seq 1 60); do curl -s --max-time 3 localhost:8001/health >/dev/null && break; sleep 3; done
.venv/bin/python scripts/run_showcase.py -o $OUT --phase edit
log "фаза 3/3: судья"
stop_diffusion
unload qwen2.5-coder:14b
../chart_agent/.venv/bin/python scripts/judge_edits.py $OUT --file showcase.json --key id --before typed_png --after edit_png --status-field edit_status --verdicts judge.json
log "готово"
