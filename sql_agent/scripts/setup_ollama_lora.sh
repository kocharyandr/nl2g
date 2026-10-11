#!/usr/bin/env bash
# Build three Ollama models, one per pipeline role, each carrying its own LoRA.
#
# Ollama needs a GGUF adapter when the base is an existing Ollama model, while
# the adapters were trained with MLX. Hence the chain:
#
#   MLX (lora_a/lora_b) ──► PEFT (lora_A/lora_B, transposed) ──► GGUF ──► ollama create
#
# Result: three models — nl2sql-schema / nl2sql-sql / nl2sql-critic — served by
# one Ollama on one port. The roles differ only by model name, so sql_agent
# points all three endpoints at :11434 and varies *_MODEL_NAME.
set -euo pipefail

EDU_ROOT="${EDU_ROOT:-$HOME/education}"
GROUP="${GROUP:-Qwen2.5-Coder-14B}"
BASE_MODEL="${BASE_MODEL:-qwen2.5-coder:14b}"
HF_BASE="${HF_BASE:-$EDU_ROOT/local_models/Qwen2.5-Coder-14B-Instruct-4bit}"
WORK_DIR="${WORK_DIR:-$HOME/.cache/sql_agent_lora}"
PREFIX="${PREFIX:-nl2sql}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LCPP="$WORK_DIR/llama.cpp"
PY="$WORK_DIR/venv/bin/python"

adapter_for () {
  case "$1" in
    critic)
      local v2="$EDU_ROOT/spider_experiments_v2/$GROUP/4bit/critic_adapter"
      [ -d "$v2" ] && echo "$v2" || echo "$EDU_ROOT/spider_experiments/$GROUP/4bit/critic_adapter" ;;
    *) echo "$EDU_ROOT/spider_experiments/$GROUP/4bit/${1}_adapter" ;;
  esac
}

command -v ollama >/dev/null || { echo "ollama not found" >&2; exit 1; }
curl -sf --max-time 3 http://localhost:11434/api/tags >/dev/null \
  || { echo "ollama is not running — start it with: ollama serve" >&2; exit 1; }
ollama list | grep -q "^${BASE_MODEL%%:*}" \
  || { echo "base model $BASE_MODEL is missing — run: ollama pull $BASE_MODEL" >&2; exit 1; }

mkdir -p "$WORK_DIR"/{peft,gguf}

if [ ! -x "$PY" ]; then
  echo "▶ conversion venv"
  uv venv "$WORK_DIR/venv" --python 3.12 >/dev/null
  uv pip install -q --python "$PY" torch safetensors numpy transformers sentencepiece
fi

if [ ! -f "$LCPP/convert_lora_to_gguf.py" ]; then
  echo "▶ llama.cpp conversion scripts"
  git clone --depth 1 --filter=blob:none --sparse \
    https://github.com/ggml-org/llama.cpp.git "$LCPP" >/dev/null 2>&1
  git -C "$LCPP" sparse-checkout set --skip-checks \
    gguf-py conversion convert_hf_to_gguf.py convert_lora_to_gguf.py >/dev/null
fi

for role in schema sql critic; do
  src="$(adapter_for "$role")"
  [ -d "$src" ] || { echo "✗ $role: adapter not found at $src" >&2; exit 1; }

  echo "▶ $role"
  "$PY" "$SCRIPT_DIR/mlx_to_peft.py" "$src" "$WORK_DIR/peft/$role"

  PYTHONPATH="$LCPP/gguf-py" "$PY" "$LCPP/convert_lora_to_gguf.py" \
    --base "$HF_BASE" --outfile "$WORK_DIR/gguf/$role.gguf" --outtype f16 \
    "$WORK_DIR/peft/$role" 2>&1 | grep -E "n_tensors" || true

  printf 'FROM %s\nADAPTER %s\nPARAMETER temperature 0\n' \
    "$BASE_MODEL" "$WORK_DIR/gguf/$role.gguf" > "$WORK_DIR/Modelfile.$role"
  ollama create "$PREFIX-$role" -f "$WORK_DIR/Modelfile.$role" >/dev/null
  echo "  ✓ $PREFIX-$role"
done

cat <<EOF

Готово. Три модели: $PREFIX-schema, $PREFIX-sql, $PREFIX-critic

В .env:
  SCHEMA_API_BASE=http://localhost:11434/v1   SCHEMA_MODEL_NAME=$PREFIX-schema
  SQL_API_BASE=http://localhost:11434/v1      SQL_MODEL_NAME=$PREFIX-sql
  CRITIC_API_BASE=http://localhost:11434/v1   CRITIC_MODEL_NAME=$PREFIX-critic

Чтобы три модели не выгружали друг друга:
  OLLAMA_MAX_LOADED_MODELS=3 OLLAMA_KEEP_ALIVE=30m ollama serve
EOF
