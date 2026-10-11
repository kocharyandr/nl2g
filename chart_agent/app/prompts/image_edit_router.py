from __future__ import annotations

import json
from typing import Any

from app.graph.node_schemas.image_edit_router_node import ImageEditRouterDecision

IMAGE_EDIT_ROUTER_PROMPT_TEMPLATE = """
Ты классификатор правки для пайплайна диффузионной генерации изображений.
Пользователь редактирует уже сгенерированное изображение. Определи, нужен ли новый источник.

КОНТЕКСТ:
{state_context}

ПРАВКА ПОЛЬЗОВАТЕЛЯ:
{user_input}

МАРШРУТЫ:
- "image_prompt_enhancer" — оставить то же входное изображение, изменить только промпт/стиль/эффект
- "image_input_selector"  — нужно выбрать новое входное изображение перед генерацией

ПРАВИЛА:
1. Пользователь прикрепил новое изображение (has_user_images=true) → "image_input_selector"
2. Правка касается стиля, цвета, яркости, эффекта, объекта, текстуры — без замены источника → "image_prompt_enhancer"
3. Явный запрос на смену источника ("другое фото", "начни заново", "возьми этот") → "image_input_selector"
4. По умолчанию (неясно, источник уже есть) → "image_prompt_enhancer"

СХЕМА ОТВЕТА (только JSON, без текста вокруг):
{output_schema}
""".strip()


def build_image_edit_router_prompt(user_input: str, context: dict[str, Any]) -> str:
    state_context = {
        "has_user_images": bool(context.get("has_user_images")),
        "has_last_accepted_image": bool(context.get("has_last_accepted_image")),
        "input_source": context.get("input_source") or "",
        "summary": context.get("summary") or "",
    }
    output_schema = json.dumps(
        ImageEditRouterDecision.model_json_schema(),
        ensure_ascii=False,
        indent=2,
    )
    return IMAGE_EDIT_ROUTER_PROMPT_TEMPLATE.format(
        state_context=json.dumps(state_context, ensure_ascii=False, indent=2),
        user_input=user_input,
        output_schema=output_schema,
    )
