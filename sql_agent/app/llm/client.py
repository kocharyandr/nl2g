"""OpenAI-compatible client, one endpoint per pipeline role.

Each role talks to its own server so that each can be pinned to its own LoRA
adapter (`mlx_lm.server --adapter-path ...`). Swapping adapters inside a single
server is possible via the request's `adapters` field, but that reloads the
whole base model on every switch, which a three-role pipeline cannot afford —
hence three processes and three base URLs.

Nothing here is MLX-specific. Pointing these URLs at vLLM with
`--enable-lora`, or at any other OpenAI-compatible server, requires no code
change.
"""
from __future__ import annotations

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMUnavailableError(RuntimeError):
    """Role endpoint could not be reached or returned an unusable response."""


class RoleLLMClient:
    def __init__(self, role: str) -> None:
        self.role = role
        self.base_url, self.model = settings.role_endpoint(role)
        self.timeout = settings.llm_timeout_sec

    async def ask(
        self,
        system: str,
        user: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        payload = {
            "model": self.model,
            "temperature": settings.llm_temperature if temperature is None else temperature,
            "max_tokens": max_tokens or settings.llm_max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        url = f"{self.base_url}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.warning("role=%s endpoint failed: %s", self.role, exc)
            raise LLMUnavailableError(
                f"Роль '{self.role}' недоступна ({self.base_url}): {exc}"
            ) from exc

        try:
            return (data["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailableError(
                f"Роль '{self.role}' вернула ответ неожиданной формы."
            ) from exc

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self.base_url}/models")
                return response.status_code == 200
        except httpx.HTTPError:
            return False


_clients: dict[str, RoleLLMClient] = {}


def get_role_client(role: str) -> RoleLLMClient:
    if role not in _clients:
        _clients[role] = RoleLLMClient(role)
    return _clients[role]
