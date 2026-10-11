#!/bin/bash
# Собирает три модели SQL-агента в Ollama из адаптеров репозитория (sql_agent/adapters/*.gguf).
# Нужен запущенный `ollama serve`. Повторный запуск пересоздаёт модели.
set -e
cd "$(dirname "$0")/../adapters"
ollama pull qwen2.5-coder:14b
for role in schema sql critic; do
  ollama create "nl2sql-$role" -f "Modelfile.$role"
done
ollama list | grep -E "nl2sql|qwen2.5-coder" 
