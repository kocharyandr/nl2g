#!/bin/bash
# Поднимает весь стек NL2G на одной машине. Логи — в ./logs, PID-ы — в ./logs/pids.
#   bash start_all.sh                 # Redis, Ollama, sql_agent, executor, chart_agent, чат
#   bash start_all.sh --diffusion     # + сервис диффузии FLUX (нужны скачанные веса, см. docs/ЗАПУСК.md)
#   bash start_all.sh --guardrails    # + guardrails на GLiNER2
#   bash start_all.sh --status        # только проверить, что отвечает
# Остановить: bash stop_all.sh
set -u
cd "$(dirname "$0")"
ROOT="$PWD"; LOGS="$ROOT/logs"; mkdir -p "$LOGS/pids"
WITH_DIFF=0; WITH_GUARD=0; STATUS_ONLY=0
for a in "$@"; do case "$a" in --diffusion) WITH_DIFF=1;; --guardrails) WITH_GUARD=1;; --status) STATUS_ONLY=1;; esac; done

# Оркестратор по умолчанию ищет .env в своей папке; переменные ниже задают локальные адреса.
export OPENAI_API_BASE=http://127.0.0.1:11434/v1 OPENAI_API_KEY=ollama OPENAI_MODEL_NAME=qwen2.5-coder:14b
export SQL_AGENT_ENABLED=true SQL_AGENT_URL=http://127.0.0.1:8500 CODE_EXECUTOR_URL=http://127.0.0.1:8080
export STATE_STORE_REDIS_ENABLED=true STATE_STORE_REDIS_URL=redis://127.0.0.1:6379/0 LANGFUSE_ENABLED=false
export DIFFUSION_HOST=127.0.0.1 DIFFUSION_PORT=8001 EDIT_SERVICE_URL=http://127.0.0.1:8001/edit DIFFUSION_TIMEOUT_SEC=900
export EDIT_USE_STUB=$([ $WITH_DIFF = 1 ] && echo false || echo true)
export GUARDRAILS_ENABLED=$([ $WITH_GUARD = 1 ] && echo true || echo false) GUARDRAILS_HOST=127.0.0.1 GUARDRAILS_PORT=8600
# На одной машине FLUX (≈33 ГБ) и LoRA-роли (27 ГБ) не помещаются вместе: с диффузией модели Ollama выгружаются сразу.
export OLLAMA_MAX_LOADED_MODELS=3 OLLAMA_KEEP_ALIVE=$([ $WITH_DIFF = 1 ] && echo 0 || echo 30m)

up() { curl -s --max-time 3 -o /dev/null "$1"; }
run() { # run <имя> <url-проверки> <каталог> <команда…>
  local name=$1 url=$2 dir=$3; shift 3
  if up "$url"; then echo "  $name: уже работает"; return; fi
  # полностью отвязываем процесс от терминала, иначе вызвавшая оболочка ждёт его вывода
  (cd "$dir" && nohup "$@" > "$LOGS/$name.log" 2>&1 < /dev/null & echo $! > "$LOGS/pids/$name.pid") > /dev/null 2>&1
  for _ in $(seq 1 60); do up "$url" && { echo "  $name: запущен"; return; }; sleep 2; done
  echo "  $name: НЕ ОТВЕЧАЕТ, смотрите $LOGS/$name.log"
}

if [ $STATUS_ONLY = 1 ]; then
  for s in "redis 6379" "ollama 11434/api/tags" "sql_agent 8500/health" "executor 8080/docs" "chart_agent 8010/docs" "diffusion 8001/health" "guardrails 8600/metrics" "chat 7861"; do
    set -- $s; if [ "$1" = redis ]; then r=$(redis-cli ping 2>/dev/null); [ "$r" = PONG ] && echo "  redis: ✓" || echo "  redis: ✗"
    else up "http://127.0.0.1:$2" && echo "  $1: ✓" || echo "  $1: ✗"; fi
  done; exit 0
fi

echo "Запуск NL2G (диффузия: $WITH_DIFF, guardrails: $WITH_GUARD)"
redis-cli ping >/dev/null 2>&1 || redis-server --daemonize yes --dir "$ROOT" --save "60 1" >/dev/null && echo "  redis: ✓"
run ollama      http://127.0.0.1:11434/api/tags "$ROOT" ollama serve
run sql_agent   http://127.0.0.1:8500/health  "$ROOT/sql_agent" .venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8500
run executor    http://127.0.0.1:8080/docs    "$ROOT/chart_agent/code_executor" .venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8080
[ $WITH_GUARD = 1 ] && run guardrails http://127.0.0.1:8600/metrics "$ROOT/guardrails_api" uv run uvicorn main:app --host 127.0.0.1 --port 8600
[ $WITH_DIFF = 1 ]  && run diffusion  http://127.0.0.1:8001/health  "$ROOT/diffusion_service" env HF_HUB_OFFLINE=1 .venv/bin/python app.py
run chart_agent http://127.0.0.1:8010/docs    "$ROOT/chart_agent" .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
run chat        http://127.0.0.1:7861         "$ROOT/chat" env CHART_AGENT_URL=http://127.0.0.1:8010 CHAT_REQUEST_TIMEOUT=900 \
    GRADIO_SERVER_NAME=127.0.0.1 GRADIO_SERVER_PORT=7861 GRADIO_ANALYTICS_ENABLED=False .venv/bin/python app.py
echo "Готово: чат — http://127.0.0.1:7861 · логи — $LOGS"
