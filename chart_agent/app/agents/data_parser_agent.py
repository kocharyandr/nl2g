from app.agents.base_agent import BaseJsonAgent
from app.api.schemas import (
    DataArtefacts,
    DataUnderstandingResult,
    DataValidationReport,
    TableAnalysisPlan,
    TableCodeSpec,
)
from app.prompts.data_parser import data_parser_prompt
from app.prompts.data_validator import data_validator_prompt
from app.prompts.table_code_generator import table_code_generator_prompt
from app.prompts.table_planner import table_planner_prompt


class DataParserAgent(BaseJsonAgent):
    def __init__(self, llm, structured_llm):
        super().__init__(llm, structured_llm)

    async def run(
        self,
        user_input: str,
        agent_type: str,
        context: DataArtefacts | dict[str, object] | None = None,
        target_plot_type: str | None = None,
    ):
        if agent_type == "parser":
            prompt = data_parser_prompt(user_input, context)
            try:
                return await super().run(
                    prompt=prompt,
                    model_cls=DataUnderstandingResult,
                    temperature=0.0,
                    prefer_structured=True,
                )
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"DataParserAgent failed to parse chart data: {exc}") from exc

        if agent_type == "validator":
            prompt = data_validator_prompt(
                target_plot_type=target_plot_type,
                context=context.understanding if isinstance(context, DataArtefacts) else None,
            )
            try:
                return await super().run(
                    prompt=prompt,
                    model_cls=DataValidationReport,
                    temperature=0.0,
                    prefer_structured=True,
                )
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"DataParserAgent failed to validate chart data: {exc}") from exc

        if agent_type == "table_planner":
            prompt = table_planner_prompt(user_input=user_input, context=context)
            try:
                return await super().run(
                    prompt=prompt,
                    model_cls=TableAnalysisPlan,
                    temperature=0.0,
                    prefer_structured=True,
                )
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"DataParserAgent failed to plan table visualization: {exc}") from exc

        if agent_type == "table_code_generator":
            prompt = table_code_generator_prompt(
                user_input=user_input,
                context=context or {},
            )
            try:
                return await super().run(
                    prompt=prompt,
                    model_cls=TableCodeSpec,
                    temperature=0.0,
                    prefer_structured=True,
                )
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"DataParserAgent failed to generate table code: {exc}") from exc

        raise ValueError(f"Unknown DataParserAgent agent_type: {agent_type}")
