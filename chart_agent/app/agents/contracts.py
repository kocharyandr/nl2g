from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class InteractionAgentLike(Protocol):
    async def run(self, user_input: str, context: dict | None = None) -> Any: ...


class ImageEditRouterAgentLike(Protocol):
    async def run(self, user_input: str, context: dict | None = None) -> Any: ...


class DataUnderstandingAgentLike(Protocol):
    async def run(
        self,
        user_input: str,
        agent_type: str,
        context: Any = None,
        target_plot_type: str | None = None,
    ) -> Any: ...


class PlotPlanningAgentLike(Protocol):
    async def run(self, data: dict) -> dict: ...


class ImageCriticAgentLike(Protocol):
    async def run(self, **kwargs) -> Any: ...


class SummaryAgentLike(Protocol):
    async def run(self, summary: Any) -> Any: ...


@dataclass(slots=True)
class AgentDependencies:
    llm: Any
    interaction: InteractionAgentLike
    image_edit_router: ImageEditRouterAgentLike
    summary: SummaryAgentLike
    data_understanding: DataUnderstandingAgentLike
    plot_planner: PlotPlanningAgentLike
    image_critic: ImageCriticAgentLike

    def __getitem__(self, item: str) -> Any:
        roles = {
            "interaction": self.interaction,
            "image_edit_router": self.image_edit_router,
            "summary": self.summary,
            "data_understanding": self.data_understanding,
            "plot_planner": self.plot_planner,
            "image_critic": self.image_critic,
            "llm": self.llm,
        }
        return roles[item]
