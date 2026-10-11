from __future__ import annotations

import json
from typing import Any

from app.api.schemas import TableAnalysisPlan
from app.infra.langfuse_prompts import get_text_prompt

PROMPT_NAME = "table_planner_agent_prompt"
PROMPT_TEMPLATE_FALLBACK = """
Ты агент планирования визуализации по таблице.

Твоя задача:
1. Понять запрос пользователя относительно загруженной таблицы.
2. Выбрать точные колонки таблицы для построения графика.
3. Определить, нужна ли агрегация, и если нужна — какая именно.
4. При необходимости выбрать временную гранулярность.
5. Вернуть ТОЛЬКО JSON-объект TableAnalysisPlan.

Основные правила:
1. Используй только колонки из TABLE_CONTEXT.columns.
2. Если пользователь явно назвал колонку, используй именно ее.
3. Не запрашивай уточнение только потому, что в таблице есть лишние колонки, не относящиеся к запросу.
4. Если пользователь просит histogram/box по одной числовой колонке, не требуй category/x-колонку.
5. Для row-level таблиц:
   - если просят сравнение по category/time + числовой метрике, обычно нужна aggregation=sum;
   - если просят "сколько"/"count", используй aggregation=count;
   - если просят среднее, используй aggregation=avg;
   - если просят min/max/median, используй соответствующую aggregation.
6. Для line/area по временной колонке выбирай time_granularity, если пользователь просит помесячно/по кварталам/по годам.
7. needs_clarification=true ставь только когда без дополнительного вопроса действительно нельзя выбрать корректный план.
8. clarification_question должен быть коротким и конкретным.
9. chart_type должен быть совместим с запросом пользователя и с выбранными колонками.
10. reasoning пиши кратко и предметно.

Подсказки:
- bar/line/area/stacked_bar/pie/doughnut обычно работают с x_column и агрегированной метрикой.
- scatter требует числовые x_column и y_columns[0].
- histogram и box работают по одной или нескольким числовым y_columns без x_column.
- Если нужно сравнить несколько метрик на общей оси, положи их в y_columns.
- Если нужна группировка по отдельной колонке, используй series_column.

TABLE_CONTEXT:
{{table_context_json}}

USER_REQUEST:
{{user_input}}

JSON schema:
{{output_schema_text}}
""".strip()


def table_planner_prompt(user_input: str, context: dict[str, Any] | None = None) -> str:
    return get_text_prompt(
        name=PROMPT_NAME,
        fallback=PROMPT_TEMPLATE_FALLBACK,
        variables={
            "table_context_json": json.dumps(context or {}, ensure_ascii=False, indent=2),
            "user_input": user_input,
            "output_schema_text": json.dumps(
                TableAnalysisPlan.model_json_schema(),
                ensure_ascii=False,
                indent=2,
            ),
        },
    )
