from app.prompts.summary import build_summary_prompt
from app.graph.node_schemas.summarizing_node import SummaryAnswer
from app.api.schemas import Summary
from app.agents.base_agent import BaseJsonAgent

class SumUpAgent(BaseJsonAgent):
    def __init__(self, llm, structured_llm=None):
        super().__init__(llm, structured_llm)

    async def run(self, summary: Summary):
        prompt = build_summary_prompt(summary)
        return await super().run(
            prompt=prompt,
            model_cls=SummaryAnswer,
            temperature=0.3,
            prefer_structured=True,
        )
