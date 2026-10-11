from __future__ import annotations

import json
from typing import Any

from app.graph.node_schemas.edit_router_node import EditRouterDecision
from app.infra.langfuse_prompts import get_text_prompt

EDIT_ROUTER_PROMPT_NAME = "edit_router_prompt"

EDIT_ROUTER_PROMPT_TEMPLATE = """
Ты классификатор правки. Определи, в какой пайплайн направить запрос.

=== ЧТО УМЕЕТ КАЖДЫЙ МАРШРУТ ===

"data_parsing" — изменения реализуемые КОДОМ matplotlib:
  • Цвет (hex, named), прозрачность
  • Подписи осей, заголовок, легенда, шрифт, размер текста
  • Тип графика (bar→line→pie и т.д.), масштаб, сетка
  • Добавить/удалить/изменить числовые данные точек
  ⚠ НЕ СЮДА: текстуры материалов, художественные стили, фотоэффекты, фон как изображение

"image_generation" — нейросетевая диффузионная обработка изображения:
  • Текстуры материалов: кирпич, дерево, металл, ткань, песок, снег, лёд и т.п.
  • Художественные стили: акварель, масло, карандаш, 3D-рендер, пиксель-арт
  • Замена/добавление фона, объектов, освещения
  • Любой эффект, который нельзя описать кодом matplotlib
  • Слова-сигналы: сгенерируй, нарисуй, текстуру, стиль, эффект, нейросеть, арт

=== ПРАВИЛА ===

1. ПРИОРИТЕТ image_generation: если правка требует текстуры материала, художественного стиля
   или любого визуального эффекта невозможного в matplotlib → "image_generation".
   Это правило действует ДАЖЕ ЕСЛИ речь идёт о секторах графика, столбцах и т.п.
   Пример: "замени цвет секторов на текстуру кирпича" → image_generation (текстура кирпича ≠ цвет)

2. Если правка исключительно кодовая (цвет, подпись, тип, данные) → "data_parsing".

3. При наличии оба артефакта (has_plot_image и has_diffusion_image) — смотри суть:
   текстура/стиль/эффект → image_generation; чисто кодовая правка → data_parsing.

СОСТОЯНИЕ:
{{state_context}}

ПРАВКА ПОЛЬЗОВАТЕЛЯ:
{{user_input}}

СХЕМА ОТВЕТА (только JSON, без текста вокруг):
{{output_schema}}
""".strip()


def build_edit_router_prompt(user_input: str, context: dict[str, Any]) -> str:
    state_context = {
        "has_plot_image": bool(context.get("has_plot_image")),
        "has_diffusion_image": bool(context.get("has_diffusion_image")),
        "previous_stage": context.get("previous_stage"),
        "summary": context.get("summary") or "",
    }
    output_schema = json.dumps(
        EditRouterDecision.model_json_schema(),
        ensure_ascii=False,
        indent=2,
    )
    return get_text_prompt(
        name=EDIT_ROUTER_PROMPT_NAME,
        fallback=EDIT_ROUTER_PROMPT_TEMPLATE,
        variables={
            "state_context": json.dumps(state_context, ensure_ascii=False, indent=2),
            "user_input": user_input,
            "output_schema": output_schema,
        },
    )
