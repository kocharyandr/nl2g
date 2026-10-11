# Как запустить и пощупать

Пошаговое знакомство со сборкой: NL2SQL-агент, оркестратор графиков и чат.
Справочники — в README сервисов; здесь только practical path от нуля до
работающего графика по данным из базы.

## 0. Что вообще происходит

```text
вы ──► чат :7861 ──► chart_agent :8000 ──► sql_agent :8500 ──► SQLite (243 базы)
                            │                     │
                            └──── LLM ────────────┴──► ollama :11434
                                                        три модели с LoRA
```

`sql_agent` отвечает на вопрос таблицей, `chart_agent` рисует по ней график.
Разделение жёсткое: сервис данных не решает, какой строить график, а
оркестратор не ходит в базу.

## 1. Поднять модели

```bash
ollama pull qwen2.5-coder:14b                       # ~9 ГБ, один раз
OLLAMA_MAX_LOADED_MODELS=3 OLLAMA_KEEP_ALIVE=30m ollama serve &

cd sql_agent
make ollama-lora                                    # ~2 минуты
ollama list | grep nl2sql                           # должно быть три модели
```

`make ollama-lora` конвертирует LoRA-адаптеры из ВКР (MLX → PEFT → GGUF) и
создаёт `nl2sql-schema`, `nl2sql-sql`, `nl2sql-critic`. Подробности — в
[sql_agent/README.md](sql_agent/README.md), п.4.

Проверить, что адаптер реально применён, можно сравнив с базовой моделью:
базовая игнорирует инструкцию про `<thinking>`, дообученная её соблюдает и
пишет SQL в стиле Spider (`country  =  'France'`).

## 2. Поднять сервис данных

```bash
cd sql_agent
make install
cp .env_template .env
```

В `.env` укажите, где лежат базы и профили:

```env
DB_ID=GeoNuclearData
DB_PATH=~/education/KaggleDBQA/databases/GeoNuclearData/GeoNuclearData.sqlite
DATASOURCE_ROOTS=~/education/KaggleDBQA/databases:~/education/datasets/spider_data/database:~/education/datasets/BIRD
PROFILES_DIR=~/education/datasets/BD_profiles

SCHEMA_API_BASE=http://localhost:11434/v1
SCHEMA_MODEL_NAME=nl2sql-schema
SQL_API_BASE=http://localhost:11434/v1
SQL_MODEL_NAME=nl2sql-sql
CRITIC_API_BASE=http://localhost:11434/v1
CRITIC_MODEL_NAME=nl2sql-critic
```

```bash
make run                                            # :8500
curl -s localhost:8500/health | python3 -m json.tool
```

В ответе `"status": "ok"`, `"datasources": 243` и три роли `reachable: true`.
Если `degraded` — смотрите, какая роль недоступна: обычно упал `ollama serve`.

## 3. Задать первые вопросы

Самый быстрый способ — CLI:

```bash
cd sql_agent

./scripts/ask.py --list                             # 243 базы
./scripts/ask.py --schema -d concert_singer         # таблицы, колонки, описания
./scripts/ask.py "сколько действующих энергоблоков во Франции"
./scripts/ask.py -d TheHistoryofBaseball "сколько игроков в таблице"
./scripts/ask.py -d car_1 "перечисли страны"
```

Ответ выглядит так:

```text
-- база: WorldSoccerDataBase  таблицы: ['betfront']  попыток критика: 1  19.4с
-- Топ-5 стран с наибольшим количеством матчей.
SELECT country , count(*) FROM betfront GROUP BY country ORDER BY count(*) DESC LIMIT 5;

COUNTRY    count(*)
---------  --------
england    3432
brazil     2859

строк: 5
```

Что смотреть в этой выдаче:

- **SQL** — то, что сгенерировала модель и что реально исполнилось;
- **таблицы** — что выбрал агент-схемотехник; по ним урезалась схема в промпте;
- **попыток критика** — сколько раз пришлось чинить запрос по ошибке движка.
  `1` значит, что первый вариант сразу отработал;
- **строк** — если добавилось «выборка обрезана по лимиту», данных было больше
  `max_rows`, и строить по ним агрегат нельзя без уточнения фильтра.

Сырой ответ сервиса — флаг `--json` (удобно пайпить в `jq`).

Через HTTP то же самое:

```bash
curl -s localhost:8500/query -H "Content-Type: application/json" -d '{
  "question": "топ-5 стран по числу энергоблоков",
  "datasource_id": "GeoNuclearData",
  "max_rows": 10
}' | python3 -m json.tool
```

## 4. Поднять оркестратор и чат

```bash
cd chart_agent
uv venv .venv --python 3.12 && uv pip install -r requirements.txt

OPENAI_API_BASE=http://127.0.0.1:11434/v1 \
OPENAI_API_KEY=ollama OPENAI_MODEL_NAME=qwen2.5-coder:14b \
SQL_AGENT_ENABLED=true SQL_AGENT_URL=http://127.0.0.1:8500 \
STATE_STORE_REDIS_ENABLED=false LANGFUSE_ENABLED=false \
GUARDRAILS_ENABLED=false EDIT_USE_STUB=true \
.venv/bin/python -m uvicorn app.main:app --port 8000
```

```bash
cd chat
uv venv .venv --python 3.12 && uv pip install -r requirements.txt

CHART_AGENT_URL=http://127.0.0.1:8000 CHAT_REQUEST_TIMEOUT=900 \
GRADIO_SERVER_PORT=7861 GRADIO_ANALYTICS_ENABLED=False \
.venv/bin/python app.py
```

Откройте http://localhost:7861, поставьте галочку **«Данные из базы»** и
спросите, например: «построй столбчатую диаграмму: топ-6 стран по числу
энергоблоков».

Под графиком появится пояснение, число строк и раскрывающийся блок с SQL.
Это не украшение: график по данным, которых вы не видели, проверяем только
вместе с запросом.

Ответ занимает около минуты — три роли по очереди, потом генерация кода графика.

Какую базу использует чат, задаётся переменной оркестратора
`SQL_AGENT_DATASOURCE_ID`; пусто — база по умолчанию из `sql_agent`.

## 5. Что стоит попробовать специально

**Правка уже построенного графика.** Подтвердите график, потом напишите «а
теперь линией». В базу повторного запроса не будет — строки переиспользуются
из состояния сессии, поэтому цифры под графиком не поменяются.

**Обрезка выборки.** Спросите что-нибудь заведомо большое с маленьким
`max_rows`: `./scripts/ask.py -n 3 -d GreaterManchesterCrime "перечисли преступления"`.
Под таблицей появится «выборка обрезана по лимиту» — сервис не делает вид,
что показал всё.

**Защита от инъекции.** Валидация SQL стоит до исполнения и вырезает литералы
и комментарии, поэтому ни `'a;b'`, ни `-- ; DROP TABLE` не прячут второе
выражение. Соответствующие тесты — `sql_agent/tests/test_safety.py`.

**Отказ сервиса данных.** Остановите `sql_agent` и задайте вопрос с включённой
галочкой. Система не «деградирует тихо», а честно скажет, что источник
недоступен: без данных строить нечего.

## 6. Если что-то не так

| Симптом | Причина |
| --- | --- |
| `health` → `degraded`, роли `reachable: false` | не запущен `ollama serve` |
| `ошибка [llm_error]` | роль есть, но модель не создана — `make ollama-lora` |
| `ошибка [db_error]: неизвестный источник` | опечатка в `datasource_id`, см. `--list` |
| `ошибка [unsafe_sql]` | модель сгенерировала не-`SELECT`; запрос отклонён до базы |
| чат не стартует, порт занят | `GRADIO_SERVER_PORT=7861` |
| ответ дольше 2 минут | модель выгрузилась; `OLLAMA_KEEP_ALIVE=30m` |

Логи: `sql_agent` и `chart_agent` пишут в stdout. Полезные строки —
`query ok. session=... datasource=... rows=... attempts=...` и
`sql_source: ...` соответственно.

## 7. Границы текущей сборки

- **Только SQLite.** `DBConnector` — готовый шов для PostgreSQL, но критик
  обучался на текстах ошибок SQLite, и петлю нужно перепроверять.
- **`need_clarification` выключен** (`CLARIFICATION_ENABLED=false`) — первая
  версия отвечает только `ok`/`error`.
- **Ветку выбирает галочка, а не классификатор.** Метка
  `chart_from_database` заведена, но выключена: корректность не должна
  зависеть от точности классификации.
- **Нет аутентификации и кэширования.**
- **Guardrails и Redis** в инструкции выше выключены для простоты запуска;
  полная конфигурация — в [README.md](README.md).
- **Точность.** На KaggleDBQA конфигурация из ВКР давала 57.3% execution
  accuracy, причём Hard и Extra Hard вопросы — 0–12%. Поэтому SQL и
  показывается пользователю: доверять цифрам вслепую нельзя.
