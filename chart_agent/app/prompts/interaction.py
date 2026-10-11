from __future__ import annotations

import json
from typing import Any

from app.graph.node_schemas.ingress_node import INGRESS_CATALOG
from app.graph.node_schemas.interaction_node import InteractionDecision
from app.infra.langfuse_prompts import get_text_prompt

PROMPT_NAME = "interaction_agent_prompt"
PROMPT_TEMPLATE_FALLBACK = """
ВАЖНО: Твой ответ должен быть ТОЛЬКО JSON-объектом. Без объяснений, без markdown, без текста до или после JSON.

Ты interaction-агент системы визуализации данных с двумя ветками обработки.

=== ЧТО УМЕЕТ КАЖДАЯ ВЕТКА ===

data_parsing — построение и правка графика КОДОМ (matplotlib):
  • Построить любой график по числовым данным (bar, line, pie, scatter и др.)
  • Изменить цвет, шрифт, размер, подписи осей, заголовок, легенду
  • Поменять тип графика, масштаб, сетку
  • Добавить/убрать данные, изменить агрегацию
  ⚠ НЕ УМЕЕТ: рисовать текстуры, фотореалистичные эффекты, художественные стили,
    накладывать изображения, применять природные/материальные текстуры (кирпич, дерево и т.п.),
    делать что-либо что невозможно описать кодом matplotlib

image_generation — нейросетевая диффузионная генерация/редактирование изображения:
  • Художественная стилизация (акварель, масло, пиксель-арт, 3D и т.п.)
  • Применение текстур и материалов (кирпич, дерево, песок, снег, ткань и т.п.)
  • Замена фона, добавление объектов, изменение освещения
  • Любые операции "нарисуй", "сгенерируй", "добавь художественный эффект"
  • Редактирование уже сгенерированного изображения

=== ПРАВИЛА МАРШРУТИЗАЦИИ ===

1. ПРИОРИТЕТ image_generation. Если в запросе есть ХОТЯ БЫ ОДИН из сигналов:
   - слова: сгенерируй, нарисуй, нейросеть, текстуру, текстура, фон, стиль, эффект, арт, рисунок
   - операция физически невозможна в matplotlib (текстуры материалов, фотоэффекты, художественные стили)
   - есть намерение получить картинку, а не диаграмму
   → ВСЕГДА route_to_stage=image_generation, даже если упоминается "график" или "сектора"

2. data_parsing — только если запрос ПОЛНОСТЬЮ сводится к изменениям кода matplotlib:
   цвет (#RGB, named), подписи, тип графика, масштаб, добавление числовых данных.
   Если is_editing_flow=true И запрос про чисто кодовые изменения → data_parsing.
   ИСКЛЮЧЕНИЕ: если одновременно есть сигналы из правила 1 → image_generation.

3. CSV/таблица загружена (has_user_csv=true или has_persisted_csv=true) без явного
   упоминания нейросети/генерации → data_parsing.

4. Общий вопрос о системе, разговор, помощь → respond.

5. Данных не хватает, запрос неоднозначен → ask_clarification.

6. Если action=route_to_stage → assistant_message должен быть пустым "".
   Если action=respond или ask_clarification → assistant_message обязателен.

Доступные стадии: {{available_stages}}

СОСТОЯНИЕ:
{{state_context}}

ИСТОРИЯ (последние шаги):
{{history_context}}

ЗАПРОС ПОЛЬЗОВАТЕЛЯ:
{{user_input}}

СХЕМА ОТВЕТА:
{{output_schema_text}}

Ответ — ТОЛЬКО JSON-объект.
""".strip()


def _format_available_stages() -> str:
    lines: list[str] = []
    for stage in INGRESS_CATALOG.stages:
        lines.append(f"- {stage.name.value}: {stage.description}")
    return "\n".join(lines)


def build_interaction_prompt(user_input: str, context: dict[str, Any]) -> str:
    history = context.get("last_messages_for_sumup") or []
    output_schema_text = json.dumps(
        InteractionDecision.model_json_schema(),
        ensure_ascii=False,
        indent=2,
    )
    state_context = {
        "previous_stage": context.get("previous_stage"),
        "current_stage": context.get("current_stage"),
        "next_stage": context.get("next_stage"),
        "is_editing_flow": bool(context.get("is_editing_flow")),
        "awaiting_user_approval": bool(context.get("awaiting_user_approval")),
        "has_user_images": bool(context.get("has_user_images")),
        "has_user_csv": bool(context.get("has_user_csv")),
        "has_persisted_csv": bool(context.get("has_persisted_csv")),
        "has_plot_image": bool(context.get("has_plot_image")),
        "clarification_reason": context.get("clarification_reason") or "",
        "summary": context.get("summary") or "",
    }
    return get_text_prompt(
        name=PROMPT_NAME,
        fallback=PROMPT_TEMPLATE_FALLBACK,
        variables={
            "available_stages": _format_available_stages(),
            "state_context": json.dumps(state_context, ensure_ascii=False, indent=2),
            "history_context": json.dumps(history, ensure_ascii=False),
            "user_input": user_input,
            "output_schema_text": output_schema_text,
        },
    )
