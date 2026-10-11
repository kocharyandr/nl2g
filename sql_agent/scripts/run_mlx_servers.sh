#!/usr/bin/env bash
# Start one OpenAI-compatible server per pipeline role, each pinned to its own
# LoRA adapter.
#
# Why three processes and not one: mlx_lm.server does accept an `adapters`
# field per request, but switching it reloads the whole base model (see
# ModelProvider.load — model_key includes adapter_path). A three-role pipeline
# would reload on every hop. Three processes keep one base model resident each.
#
# Memory: Qwen2.5-Coder-14B-Instruct-4bit is ~7.7 GB per process (~23 GB total).
# Use the 7B base (~4 GB, ~12 GB total) on a smaller machine.
set -euo pipefail

EDU_ROOT="${EDU_ROOT:-$HOME/education}"
MODEL="${MODEL:-$EDU_ROOT/local_models/Qwen2.5-Coder-14B-Instruct-4bit}"
GROUP="${GROUP:-Qwen2.5-Coder-14B}"
PYTHON="${PYTHON:-python3.13}"
LOG_DIR="${LOG_DIR:-/tmp/sql_agent_mlx}"

SCHEMA_ADAPTER="${SCHEMA_ADAPTER:-$EDU_ROOT/spider_experiments/$GROUP/4bit/schema_adapter}"
SQL_ADAPTER="${SQL_ADAPTER:-$EDU_ROOT/spider_experiments/$GROUP/4bit/sql_adapter}"
# Critic v2 is the retrained one; fall back to v1 when it is absent.
CRITIC_ADAPTER="${CRITIC_ADAPTER:-$EDU_ROOT/spider_experiments_v2/$GROUP/4bit/critic_adapter}"
[ -d "$CRITIC_ADAPTER" ] || CRITIC_ADAPTER="$EDU_ROOT/spider_experiments/$GROUP/4bit/critic_adapter"

mkdir -p "$LOG_DIR"

start_role () {
  local role="$1" port="$2" adapter="$3"
  if [ ! -d "$adapter" ]; then
    echo "✗ $role: adapter not found at $adapter" >&2
    return 1
  fi
  if lsof -ti tcp:"$port" >/dev/null 2>&1; then
    echo "• $role: port $port already in use, skipping"
    return 0
  fi
  echo "▶ $role  port=$port  adapter=$(basename "$adapter")"
  nohup "$PYTHON" -m mlx_lm.server \
    --model "$MODEL" \
    --adapter-path "$adapter" \
    --host 0.0.0.0 --port "$port" \
    > "$LOG_DIR/$role.log" 2>&1 &
  echo "$!" > "$LOG_DIR/$role.pid"
}

case "${1:-start}" in
  start)
    start_role schema 8071 "$SCHEMA_ADAPTER"
    start_role sql    8072 "$SQL_ADAPTER"
    start_role critic 8073 "$CRITIC_ADAPTER"
    echo
    echo "Logs: $LOG_DIR/*.log"
    echo "First request per role loads the model — expect a slow first call."
    echo "Check readiness: curl -s localhost:8071/v1/models"
    ;;
  stop)
    for role in schema sql critic; do
      pidfile="$LOG_DIR/$role.pid"
      if [ -f "$pidfile" ]; then
        kill "$(cat "$pidfile")" 2>/dev/null && echo "stopped $role" || true
        rm -f "$pidfile"
      fi
    done
    ;;
  status)
    for port in 8071 8072 8073; do
      if curl -sf "http://localhost:$port/v1/models" >/dev/null 2>&1; then
        echo "✓ port $port up"
      else
        echo "✗ port $port down"
      fi
    done
    ;;
  *)
    echo "usage: $0 {start|stop|status}" >&2
    exit 1
    ;;
esac
