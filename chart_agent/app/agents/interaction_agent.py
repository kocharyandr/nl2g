from app.agents.base_agent import BaseJsonAgent
from app.graph.node_schemas.interaction_node import InteractionDecision
from app.prompts.interaction import build_interaction_prompt


class InteractionAgent(BaseJsonAgent):
    def __init__(self, llm, structured_llm=None):
        super().__init__(llm, structured_llm)

    async def run(self, user_input: str, context: dict | None = None) -> InteractionDecision:
        prompt = build_interaction_prompt(user_input=user_input, context=context or {})
        return await super().run(
            prompt=prompt,
            model_cls=InteractionDecision,
            temperature=0.0,
            prefer_structured=True,
        )
