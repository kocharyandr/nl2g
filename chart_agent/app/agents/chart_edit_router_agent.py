from app.agents.base_agent import BaseJsonAgent
from app.graph.node_schemas.chart_edit_router_node import ChartEditRouterDecision
from app.prompts.chart_edit_router import build_chart_edit_router_prompt


class ChartEditRouterAgent(BaseJsonAgent):
    def __init__(self, llm, structured_llm=None):
        super().__init__(llm, structured_llm)

    async def run(self, user_input: str, context: dict | None = None) -> ChartEditRouterDecision:
        prompt = build_chart_edit_router_prompt(user_input=user_input, context=context or {})
        return await super().run(
            prompt=prompt,
            model_cls=ChartEditRouterDecision,
            temperature=0.0,
            prefer_structured=True,
        )
