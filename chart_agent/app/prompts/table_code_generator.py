from __future__ import annotations

import json
from typing import Any

from app.api.schemas import TableCodeSpec
from app.infra.langfuse_prompts import get_text_prompt

PROMPT_NAME = "table_code_generator_agent_prompt"
PROMPT_TEMPLATE_FALLBACK = """
[РАЗДЕЛ 1 — РОЛЬ И ЗАДАЧА]
Ты агент кодогенерации. Напиши pandas-код для трансформации таблицы df.
Результат сохрани в переменную result (pd.DataFrame).
Верни ТОЛЬКО JSON объект TableCodeSpec. Никакого текста вне JSON.

[РАЗДЕЛ 2 — КОНТРАКТ result]
Исходные данные доступны в переменной df: pd.DataFrame с оригинальными колонками таблицы пользователя.
В коде уже доступны pd и np. Не добавляй import.

result — pd.DataFrame со строго определенными колонками:
- y: обязательная числовая колонка для оси Y.
- x: необязательное значение оси X.
- label: необязательная текстовая метка категории, если отличается от x.
- series: необязательное имя серии или группы.

Допустимые формы:
- [x, y] — одна серия, ось X + значение.
- [x, y, series] — многосерийный график.
- [y] — без оси X, например histogram/box.
- [y, series] — распределение по группам.

Правила:
- Используй только pd и np.
- Не используй import, open, os, eval, exec, compile, __import__.
- Не мутируй исходный df: работай с df.copy() или цепочками методов.
- result должен содержать хотя бы одну строку без NaN в колонке y.
- Используй точные имена колонок из df_info и md_preview ниже.
- Если колонка имеет dtype object, но по смыслу числовая, используй pd.to_numeric(df['col'], errors='coerce') перед агрегацией.
- В JSON x_col/y_col/series_col укажи имена колонок именно в result, обычно "x", "y", "series".
- В JSON x_label укажи оригинальное имя колонки df, ставшей x (например "Region"). y_label — оригинальное имя колонки, ставшей y (например "Sales"). Это используется как подпись осей графика.
- title_hint заполняй ТОЛЬКО если пользователь явно попросил заголовок/название графика. Иначе оставляй пустую строку.
- При переименовании колонок ВСЕГДА используй rename(columns={...}), НЕ .columns = [...].
  Прямое присвоение .columns = [...] опасно: порядок колонок после groupby зависит от pandas и может отличаться от ожидаемого.

[РАЗДЕЛ 2а — КОГДА ИСПОЛЬЗОВАТЬ needs_clarification]
needs_clarification=true ТОЛЬКО если без ответа пользователя физически невозможно определить нужные колонки.
Например: в таблице три числовые колонки и пользователь не указал, какую строить.
НЕ использовать needs_clarification если:
- есть лишние колонки, не относящиеся к запросу — просто игнорируй их
- можно сделать разумное предположение по названию колонки
- пользователь явно назвал метрику или категорию

[РАЗДЕЛ 3 — FEW-SHOT ПРИМЕРЫ]
Пример 1 — простая агрегация:
Таблица: Region(object), Sales(float64), Quarter(object)
Запрос: "покажи суммарные продажи по регионам"
Ответ:
{
  "chart_type": "bar",
  "title_hint": "Суммарные продажи по регионам",
  "x_col": "x",
  "y_col": "y",
  "series_col": null,
  "x_label": "Region",
  "y_label": "Sales",
  "code": "result = df.groupby('Region')['Sales'].sum().reset_index().rename(columns={'Region': 'x', 'Sales': 'y'})",
  "reasoning": "агрегируем Sales по Region через sum",
  "needs_clarification": false,
  "clarification_question": ""
}

Пример 2 — многосерийный grouped/line:
Таблица: Month(str), Category(str), Revenue(float)
Запрос: "сравни выручку по категориям помесячно"
Ответ:
{
  "chart_type": "line",
  "title_hint": "Выручка по категориям по месяцам",
  "x_col": "x",
  "y_col": "y",
  "series_col": "series",
  "x_label": "Month",
  "y_label": "Revenue",
  "code": "a = df.groupby(['Month', 'Category'])['Revenue'].sum().reset_index()\\nresult = a.rename(columns={'Month': 'x', 'Category': 'series', 'Revenue': 'y'})",
  "reasoning": "группируем по двум осям, series = Category",
  "needs_clarification": false,
  "clarification_question": ""
}

Пример 3 — scatter без агрегации:
Таблица: Cost(float), Revenue(float), Region(str)
Запрос: "покажи зависимость выручки от затрат"
Ответ:
{
  "chart_type": "scatter",
  "title_hint": "Выручка vs Затраты",
  "x_col": "x",
  "y_col": "y",
  "series_col": "series",
  "x_label": "Cost",
  "y_label": "Revenue",
  "code": "result = df.rename(columns={'Cost':'x','Revenue':'y','Region':'series'})[['x','y','series']].dropna()",
  "reasoning": "scatter по двум числовым колонкам, группировка по Region",
  "needs_clarification": false,
  "clarification_question": ""
}

Пример 4 — retry с ошибкой:
Предыдущий код вызвал: KeyError: 'sales'
Исправление: использовать точное имя 'Sales' из df_info, а не 'sales'.

[РАЗДЕЛ 4 — TABLE_CONTEXT]
df.info():
{{df_info}}

Первые 5 строк df (markdown):
{{md_preview}}

[РАЗДЕЛ 5 — USER_REQUEST]
{{user_input}}

[РАЗДЕЛ 6 — EXECUTION_ERROR]
{{execution_error_section}}

[РАЗДЕЛ 7 — JSON SCHEMA]
{{output_schema_text}}
""".strip()


def table_code_generator_prompt(user_input: str, context: dict[str, Any] | None = None) -> str:
    payload = context or {}
    table = payload.get("table") or {}
    execution_error = payload.get("execution_error")
    previous_code = payload.get("previous_code")
    if execution_error:
        execution_error_section = (
            "Предыдущая попытка упала с ошибкой.\n"
            f"Код:\n{previous_code or ''}\n"
            f"Ошибка:\n{execution_error}\n"
            "Исправь код и верни новый JSON."
        )
    else:
        execution_error_section = "Нет ошибки предыдущего исполнения."

    return get_text_prompt(
        name=PROMPT_NAME,
        fallback=PROMPT_TEMPLATE_FALLBACK,
        variables={
            "df_info": table.get("df_info", ""),
            "md_preview": table.get("md_preview", ""),
            "user_input": user_input,
            "execution_error_section": execution_error_section,
            "output_schema_text": json.dumps(
                TableCodeSpec.model_json_schema(),
                ensure_ascii=False,
                indent=2,
            ),
        },
    )
