from __future__ import annotations

import json

from app.api.schemas import DataUnderstandingResult, DataValidationReport
from app.infra.langfuse_prompts import get_text_prompt

PROMPT_NAME = "data_validator_agent_prompt"
PROMPT_TEMPLATE_FALLBACK = """
Ты агент валидации данных для построения графика.

ЗАДАЧА:
1. Проверь, достаточно ли DatasetSpec для построения рекомендованного графика (тип: {{target_chart_type}}).
2. Учитывай chart_intent и содержимое points.
3. Если данных достаточно:
   - is_valid=true
   - reason=""
   - correction_hint=""
4. Если данных недостаточно:
   - is_valid=false
   - кратко опиши проблему
   - дай практичную подсказку

ВАЖНО: отсутствие категорий/меток (label) в points НЕ является ошибкой — рендерер автоматически сгенерирует числовые метки "1", "2", "3". Ставь is_valid=true если есть хотя бы одна точка с числовым значением y.

INPUT_UNDERSTANDING:
{{understanding_json}}

JSON schema:
{{output_schema_text}}
""".strip()


def _format_target_chart_schema(target_plot_type: str | None) -> str:
    return str(target_plot_type).strip().lower() if target_plot_type else "unknown"


def data_validator_prompt(
    target_plot_type: str | None = None,
    context: DataUnderstandingResult | None = None,
) -> str:
    return get_text_prompt(
        name=PROMPT_NAME,
        fallback=PROMPT_TEMPLATE_FALLBACK,
        variables={
            "target_chart_type": _format_target_chart_schema(target_plot_type),
            "understanding_json": json.dumps(
                context.model_dump() if context else {},
                ensure_ascii=False,
                indent=2,
            ),
            "output_schema_text": json.dumps(
                DataValidationReport.model_json_schema(),
                ensure_ascii=False,
                indent=2,
            ),
        },
    )
