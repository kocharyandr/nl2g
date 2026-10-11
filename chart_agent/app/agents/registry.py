from app.agents.chart_coder_agent import ChartCoderAgent
from app.agents.contracts import AgentDependencies
from app.agents.data_parser_agent import DataParserAgent
from app.agents.image_edit_router_agent import ImageEditRouterAgent
from app.agents.image_generation_validator_agent import ImageGenerationValidatorAgent
from app.agents.interaction_agent import InteractionAgent
from app.agents.sumup_agent import SumUpAgent
from app.core.config import settings
from app.infra.llm.client import LLMClient


class AgentRegistry:
    def __init__(self):
        base_url = settings.openai_base_safe
        api_key = settings.openai_api_key
        model = settings.openai_model_safe

        llm = LLMClient(base_url=base_url, api_key=api_key, model=model)
        self.llm = llm

        # LangChain with_structured_output() is not supported by Qwen via LM Studio
        # (returns content='' with parsed=None). All agents use run_json_model path
        # with LLM_JSON_OUTPUT_ENABLED=true for json_schema enforcement at API level.
        self.roles = AgentDependencies(
            llm=llm,
            interaction=InteractionAgent(llm, None),
            image_edit_router=ImageEditRouterAgent(llm, None),
            summary=SumUpAgent(llm, None),
            data_understanding=DataParserAgent(llm, None),
            plot_planner=ChartCoderAgent(llm, None),
            image_critic=ImageGenerationValidatorAgent(llm),
        )

    def __getitem__(self, item: str):
        return self.roles[item]

    def __getattr__(self, item: str):
        try:
            return getattr(self.roles, item)
        except AttributeError as exc:
            raise AttributeError(item) from exc

    async def check_health(self) -> None:
        await self.llm.check_model_available()
