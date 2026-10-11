from app.agents.base_agent import BaseJsonAgent
from app.graph.node_schemas.edit_router_node import EditRouterDecision
from app.prompts.edit_router import build_edit_router_prompt


class EditRouterAgent(BaseJsonAgent):
    def __init__(self, llm, structured_llm=None):
        super().__init__(llm, structured_llm)

    async def run(self, user_input: str, context: dict | None = None) -> EditRouterDecision:
        prompt = build_edit_router_prompt(user_input=user_input, context=context or {})
        return await super().run(
            prompt=prompt,
            model_cls=EditRouterDecision,
            temperature=0.0,
            prefer_structured=True,
        )
