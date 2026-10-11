from __future__ import annotations

import json

from app.api.schemas import DataArtefacts, DataUnderstandingResult
from app.infra.langfuse_prompts import get_text_prompt

PROMPT_NAME = "data_parser_agent_prompt"
PROMPT_TEMPLATE_FALLBACK = """
Ты агент понимания данных для построения графика.

ЗАДАЧА:
1. Прочитай пользовательский запрос.
2. Извлеки данные в структурированный DatasetSpec.
3. Определи аналитическую цель визуализации.
4. Предложи рекомендуемый тип графика.
5. Не выдумывай данные, которых нет во входе.
6. Если пользователь редактирует существующий результат, используй PREVIOUS_CONTEXT только как базу.

ПРАВИЛА:
1. Верни только JSON-объект.
2. Без markdown.
3. DatasetSpec.points должен содержать реальные точки данных, если их можно извлечь.
4. Для запросов вида "A=10 B=20 C=15" формируй points с label и y.
5. Для запросов вида "10 5 15" без явных меток формируй points с автоматическими метками "1", "2", "3" и т.д. — label обязателен.
6. `chart_intent.recommended_chart_type` должен быть одним из поддерживаемых типов.

JSON schema:
{{output_schema_text}}

{{prev_context}}

USER INPUT:
{{user_input}}
""".strip()


def data_parser_prompt(user_input: str, context: DataArtefacts | None = None) -> str:
    prev_context = ""
    if context:
        prev_context = json.dumps(
            {
                "user_intent": context.user_intent.model_dump(),
                "understanding": context.understanding.model_dump(),
                "validation": context.validation.model_dump(),
            },
            ensure_ascii=False,
            indent=2,
        )
        prev_context = f"PREVIOUS_CONTEXT:\n{prev_context}"

    return get_text_prompt(
        name=PROMPT_NAME,
        fallback=PROMPT_TEMPLATE_FALLBACK,
        variables={
            "output_schema_text": json.dumps(
                DataUnderstandingResult.model_json_schema(),
                ensure_ascii=False,
                indent=2,
            ),
            "prev_context": prev_context,
            "user_input": user_input,
        },
    )
