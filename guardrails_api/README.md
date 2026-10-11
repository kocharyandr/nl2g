# GuardRails API

REST API для классификации текста по безопасности на основе модели [GLiNER2](https://github.com/urchade/GLiNER). Определяет вредоносный контент, джейлбрейк-атаки, тональность, намерения и нарушения политик.

## Возможности

Один запрос возвращает результат по шести измерениям и финальный вердикт (`ok` / `reject`) с типом и сообщением отказа:

| Задача | Описание | Метки |
| --- | --- | --- |
| `safety` | Общая безопасность | `safe`, `unsafe` |
| `adversarial` | Тип атаки на модель | `none`, `instruction_override`, `jailbreak_persona`, `jailbreak_hypothetical`, `data_exfiltration`, `jailbreak_roleplay` |
| `harmful` | Категория вредоносного контента | `none`, `dangerous_instructions`, `harassment`, `sexual_content`, `violence`, `hate_speech`, `fraud`, `pii_exposure`, `discrimination`, `misinformation`, `weapons` |
| `intent` | Намерение пользователя | `informational`, `conversational`, `instructional`, `adversarial`, `creative`, `threatening` |
| `tone` | Тональность | `neutral`, `aggressive`, `manipulative`, `formal`, `distressed` |
| `policy` | Нарушение тематической политики | `weather`, `date_time`, `small_talk`, `personal_advice`, `entertainment`, `politics_news` |

## Быстрый старт

### Требования

- Docker (+ NVIDIA GPU + `nvidia-container-toolkit` для GPU-профиля)
- Или для локального запуска: Python 3.13+, [uv](https://github.com/astral-sh/uv)

GPU не обязателен. При отсутствии CUDA сервис автоматически переключается на CPU (с warning в логах).

### Локально

```bash
cp .env_template .env
# Заполнить .env (см. раздел конфигурации)

# CPU
uv sync --extra cpu
# или GPU
uv sync --extra gpu

uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Docker

Сборка и запуск выбирают вариант через `PROFILE` (`gpu` | `cpu`). Профиль определяет:

- какой сервис compose поднимать (`api-gpu` с `nvidia` резервацией / `api-cpu` без)
- какой torch ставить в образ (`+cu128` / `+cpu`)
- суффикс тега образа (`...-gpu` / `...-cpu`)

```bash
cp .env_template .env
# Заполнить .env, выставить PROFILE=gpu или PROFILE=cpu

make up                 # подхватит PROFILE из .env (default: gpu)
make up PROFILE=cpu     # явное переопределение
make logs
make down
```

## Конфигурация

Скопируйте `.env_template` в `.env` и заполните:

```env
API_CONTAINER_NAME=guardrails_api
# chart_agent ожидает сервис на 8600 с префиксом /api/v1
API_PORT=8600
API_VERSION=/api/v1
API_TITLE=GuardRails API
API_DESCRIPTION=Text safety classification service
PROJECT_VERSION=0.1.0

# Профиль docker-compose и сборки torch
PROFILE=gpu  # или cpu

# Опционально — по умолчанию используется это:
MODEL_NAME=fastino/gliner2-multi-v1
# DEVICE — авто-резолв через torch.cuda.is_available(). Раскомментируйте только для
# принудительного выбора (например, форсировать CPU на GPU-хосте):
# DEVICE=cpu
```

Пороги срабатывания отказа (опциональные, дефолты в `core/config.py`):

```env
THRESHOLD_SAFETY=0.2
THRESHOLD_ADVERSARIAL=0.5
THRESHOLD_HARMFUL=0.5
THRESHOLD_INTENT=0.5
THRESHOLD_TONE=0.6
THRESHOLD_POLICY=0.35
```

Дефолты рассчитаны на `gliner-guard-omni`. Для `gliner2-multi-v1` они дают
ложные срабатывания на нейтральном русском тексте, поэтому в поставляемом `.env`
пороги подняты (см. комментарии в нем).

При первом запуске модель скачивается с HuggingFace. В `docker-compose.yml`
выставлен `HF_HUB_OFFLINE=1`, поэтому в контейнере веса нужно положить в
смонтированный кеш заранее: `make download-model MODEL=fastino/gliner2-multi-v1`.

## API

### `POST {API_VERSION}/classify`

**Запрос:**

```json
{ "query": "текст для проверки" }
```

**Ответ (пропуск):**

```json
{
  "status": "ok",
  "type_reject": null,
  "message": null,
  "safety":      { "label": "safe", "confidence": 0.97 },
  "adversarial": [],
  "harmful":     [],
  "intent":      { "label": "informational", "confidence": 0.91 },
  "tone":        { "label": "neutral", "confidence": 0.88 },
  "policy":      []
}
```

**Ответ (отказ):**

```json
{
  "status": "reject",
  "type_reject": "harmful",
  "message": "К сожалению, ваш запрос содержит потенциально вредоносное содержимое...",
  "safety":      { "label": "unsafe", "confidence": 0.83 },
  "adversarial": [],
  "harmful":     [{ "label": "violence", "confidence": 0.76 }],
  "intent":      { "label": "instructional", "confidence": 0.69 },
  "tone":        { "label": "aggressive", "confidence": 0.71 },
  "policy":      []
}
```

### `POST {API_VERSION}/classify/custom`

Zero-shot классификация с произвольными метками — этим путем `chart_agent`
заменяет LLM-вызов при маршрутизации.

**Запрос:**

```json
{
  "text": "построй столбчатую диаграмму",
  "task": "intent",
  "labels": ["chart_request", "image_request", "general_question"],
  "label_descriptions": { "chart_request": "просьба построить график" },
  "multi_label": false
}
```

**Ответ:**

```json
{
  "task": "intent",
  "label": "chart_request",
  "labels": [],
  "confidence": 0.82,
  "all_scores": { "chart_request": 0.82, "image_request": 0.11, "general_question": 0.07 },
  "raw": null
}
```

Вызывающая сторона сама решает, доверять ли ответу: `chart_agent` сравнивает
`confidence` с `GUARDRAILS_CONFIDENCE_THRESHOLD` и при недоборе идет в LLM.

---

`type_reject` принимает одно из: `safety`, `adversarial`, `harmful`, `intent`, `tone`, `policy` — категория, по которой сработал отказ (правила проверяются в этом порядке). Тексты сообщений отказа настраиваются через `MSG_REJECT_*` в `.env`.

Интерактивная документация: `http://localhost:{API_PORT}/docs`

Метрики Prometheus: `http://localhost:{API_PORT}/metrics`

## Как устроен сервис

```text
main.py                          # app factory, lifespan, middleware, /metrics
core/
  config.py                      # pydantic-settings (читает .env)
  logger.py                      # singleton stdlib-логгера
src/
  routers/
    base_router.py               # монтирует v1-роутер под префиксом API_VERSION
    v1/router_guardrails.py      # POST /classify, POST /classify/custom
  schemas/guardrails.py          # pydantic-модели запроса/ответа
  services/guardrails.py         # GuardRailsService — загрузка модели и инференс
```

**Жизненный цикл**: `GuardRailsService` создаётся один раз в `lifespan` FastAPI и
кладётся в `app.state.guardrails`. Роутер берёт его через `request.app.state.guardrails` —
DI-фреймворка нет.

**Инференс**: `GuardRailsService._infer()` синхронный (CPU/GPU-bound), поэтому в
`classify()` он обёрнут в `asyncio.to_thread()`, чтобы не блокировать event loop.

**Схема модели** строится один раз в `_build_schema()`: шесть задач классификации из
таблицы выше (`safety`, `intent`, `tone` — single-label; `adversarial`, `harmful`,
`policy` — multi-label).

**Метрики**: Prometheus автоматически отдаётся на `/metrics` через
`prometheus-fastapi-instrumentator`.

## Разработка

```bash
make format   # ruff format
make lint     # ruff check --fix
```

Ruff: глобально игнорируются `D` (докстринги), `TC001`/`TC002` (импорты под
`TYPE_CHECKING`) и `B008` (FastAPI `Depends`). Длина строки — 88. Исключение `tests/`
в `pyproject.toml` рудиментарное: тестов в сервисе нет.
