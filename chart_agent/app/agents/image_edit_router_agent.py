from app.agents.base_agent import BaseJsonAgent
from app.graph.node_schemas.image_edit_router_node import ImageEditRouterDecision
from app.prompts.image_edit_router import build_image_edit_router_prompt


class ImageEditRouterAgent(BaseJsonAgent):
    def __init__(self, llm, structured_llm=None):
        super().__init__(llm, structured_llm)

    async def run(self, user_input: str, context: dict | None = None) -> ImageEditRouterDecision:
        prompt = build_image_edit_router_prompt(user_input=user_input, context=context or {})
        return await super().run(
            prompt=prompt,
            model_cls=ImageEditRouterDecision,
            temperature=0.0,
            prefer_structured=True,
        )
