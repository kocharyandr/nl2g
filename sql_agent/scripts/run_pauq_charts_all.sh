#!/bin/bash
# Полный прогон PAUQ → график → правка «в стиле МТС» → судья, с переключением моделей между фазами.
# Лог: PAUQ_ГРАФИКИ_ПРОГОН/run.log, прогресс: PAUQ_ГРАФИКИ_ПРОГОН/ПРОГРЕСС.html. Повторный запуск продолжает с места остановки.
set -u
cd "$(dirname "$0")/.."
OUT=PAUQ_ГРАФИКИ_ПРОГОН
SYS=..
log() { echo "=== $(date +%H:%M:%S) $*" >&2; }
unload() { for m in "$@"; do curl -s localhost:11434/api/generate -d "{\"model\":\"$m\",\"keep_alive\":0}" >/dev/null; done; }
stop_diffusion() { lsof -nP -iTCP:8001 -sTCP:LISTEN -t | xargs kill 2>/dev/null; sleep 3; }

log "фаза 1/3: вопрос → SQL → график"
stop_diffusion
.venv/bin/python scripts/run_pauq_charts.py -n 100 -o $OUT --phase chart

log "фаза 2/3: правки диффузией (FLUX)"
unload nl2sql-schema nl2sql-sql nl2sql-critic qwen2.5vl:7b
(cd $SYS/diffusion_service && env -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy -u HF_TOKEN HF_HUB_OFFLINE=1 nohup .venv/bin/python app.py > "$PWD/../sql_agent/$OUT/diffusion.log" 2>&1 &)
for i in $(seq 1 60); do curl -s --max-time 3 localhost:8001/health >/dev/null && break; sleep 3; done
.venv/bin/python scripts/run_pauq_charts.py -n 100 -o $OUT --phase edit

log "фаза 3/3: судья (Qwen2.5-VL-7b)"
stop_diffusion
unload qwen2.5-coder:14b
../chart_agent/.venv/bin/python scripts/judge_edits.py $OUT --file runs.json --key id --before chart_png --after edit_png \
  --status-field edit_status --verdicts judge.json

log "отчёт"
../chart_agent/.venv/bin/python scripts/make_pauq_charts_review.py $OUT -o PAUQ_ГРАФИКИ_ПРОГОН.html
log "готово"
