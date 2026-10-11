# Роль «sql» SQL-агента: базовая Qwen2.5-Coder-14B (Q4_K_M из Ollama) + LoRA-адаптер из диплома.
# Шаблон чата и системный промпт наследуются от базовой модели.
FROM qwen2.5-coder:14b
ADAPTER ./nl2sql-sql.gguf
PARAMETER temperature 0
