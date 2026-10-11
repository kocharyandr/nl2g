from __future__ import annotations

import json
from typing import Any

from app.graph.node_schemas.chart_edit_router_node import ChartEditRouterDecision

CHART_EDIT_ROUTER_PROMPT_TEMPLATE = """
Ты классификатор типа правки для графика.
Пользователь редактирует уже построенный график. Определи: нужно ли менять данные/тип графика, или это визуальная правка.

ТЕКУЩИЙ ГРАФ:
{chart_context}

ПРАВКА ПОЛЬЗОВАТЕЛЯ:
{user_input}

МАРШРУТЫ:
- "plot_creator" — правка визуальная: цвет, шрифт, подписи, легенда, размер, сетка, прозрачность, стиль линий, ориентация (горизонтальный/вертикальный)
- "re_extract"   — правка затрагивает данные или тип: другие числа, новые точки, смена типа графика (bar→line), агрегация, фильтрация

ПРАВИЛА:
1. Изменение цвета, шрифта, размера, стиля, подписей, легенды, сетки, ориентации → "plot_creator"
2. Смена типа графика (например, "сделай линейный", "пирог") → "re_extract"
3. Изменение или добавление данных, значений, точек → "re_extract"
4. Изменение осей (label или масштаб без смены данных) → "plot_creator"
5. Изменение агрегации, фильтрации, группировки → "re_extract"
6. Неоднозначно — смотри, меняется ли смысл данных. Если нет → "plot_creator"

СХЕМА ОТВЕТА (только JSON, без текста вокруг):
{output_schema}
""".strip()


def build_chart_edit_router_prompt(user_input: str, context: dict[str, Any]) -> str:
    chart_context = {
        "chart_type": context.get("chart_type"),
        "title": context.get("title") or "",
        "fields": context.get("fields") or [],
        "point_count": context.get("point_count") or 0,
        "summary": context.get("summary") or "",
    }
    output_schema = json.dumps(
        ChartEditRouterDecision.model_json_schema(),
        ensure_ascii=False,
        indent=2,
    )
    return CHART_EDIT_ROUTER_PROMPT_TEMPLATE.format(
        chart_context=json.dumps(chart_context, ensure_ascii=False, indent=2),
        user_input=user_input,
        output_schema=output_schema,
    )
