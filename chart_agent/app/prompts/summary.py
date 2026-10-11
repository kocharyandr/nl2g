from __future__ import annotations

import json

from app.api.schemas import Summary
from app.graph.node_schemas.summarizing_node import SummaryAnswer
from app.infra.langfuse_prompts import get_text_prompt

PROMPT_NAME = "summary_agent_prompt"
PROMPT_TEMPLATE_FALLBACK = """
Ты обновляешь SYSTEM_CONTEXT для мультиагентной системы.

Твоя задача:
Собрать краткое и актуальное состояние системы после LAST_HISTORY_STEPS.
Это не пересказ диалога, а рабочий контекст для следующих шагов графа.

Входные данные:
1. SYSTEM_CONTEXT — предыдущая краткая суммаризация.
2. LAST_HISTORY_STEPS — новые события после последнего обновления.

В LAST_HISTORY_STEPS приходят только ключевые события:
- goal_set / goal_update
- edit_requested / edit_applied
- clarification_needed
- error
- approved / result_ready / chart_built

Что нужно сохранить в summary:
- текущую активную задачу;
- смену цели, если она произошла;
- последние правки пользователя, если они были;
- критичные ошибки и что именно нужно уточнить у пользователя;
- финальный статус по задаче (например: график построен/подтвержден, результат image готов).

Что не нужно сохранять:
- служебные логи, ретраи, промежуточные технические шаги;
- дубли и лишнюю хронологию;
- устаревшие детали старой цели;
- предположения, которых нет во входе.

Правила:
1. Используй только факты из SYSTEM_CONTEXT и LAST_HISTORY_STEPS.
2. Оставляй только актуальное состояние задачи.
3. Если новый факт противоречит старому, оставь более новый.
4. Если началась новая цель, очисти нерелевантный контекст старой.
5. Если нужно уточнение, явно укажи что именно нужно от пользователя.
6. Пиши кратко, плотно, без воды.
7. Не придумывай значения полей, которых не было во входе.
8. Если LAST_HISTORY_STEPS пуст, верни SYSTEM_CONTEXT в нормализованном виде по схеме.

Формат ответа:
1. Верни строго один JSON.
2. Без markdown.
3. Без пояснений вне JSON.
4. Строго по схеме:
{{output_schema_text}}

SYSTEM_CONTEXT:
{{system_context}}

LAST_HISTORY_STEPS (JSON):
{{last_history_steps}}
""".strip()


def _format_output_schema() -> str:
    schema = SummaryAnswer.model_json_schema()
    return json.dumps(schema, ensure_ascii=False, indent=2)


def build_summary_prompt(summary: Summary) -> str:
    return get_text_prompt(
        name=PROMPT_NAME,
        fallback=PROMPT_TEMPLATE_FALLBACK,
        variables={
            "output_schema_text": _format_output_schema(),
            "system_context": (summary.current_summary or "").strip(),
            "last_history_steps": json.dumps(list(summary.last_messeges_for_sumup), ensure_ascii=False),
        },
    )
