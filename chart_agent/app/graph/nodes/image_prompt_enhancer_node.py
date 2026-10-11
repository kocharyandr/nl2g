import logging

from app.api.state_store import publish_ephemeral_status
from app.graph.state import AppState
from app.infra.llm.client import LLMServiceUnavailableError
from app.infra.tracing import node_span
from app.prompts.image_prompt_enhancer import polish_edit_prompt

logger = logging.getLogger(__name__)


async def image_prompt_enhancer_node(state: AppState, agents):
    with node_span(state.trace_id, "image_prompt_enhancer", input=state.user_input):
        try:
            raw_prompt = (state.user_input or "").strip()
            if not raw_prompt:
                raw_prompt = "Сгенерируй улучшенную версию изображения."
            image_artefacts = state.artefacts.image
            iteration_history = [
                {
                    "iteration": meta.iteration,
                    "prompt": meta.prompt,
                    "feedback": meta.errors_summary,
                    "score": meta.score,
                }
                for meta in image_artefacts.iterations
                if meta.score is not None
            ]
            img_ctx = {
                "source": image_artefacts.input_source or "unknown",
                "images_count": str(len(image_artefacts.input_images_base64)),
                "summary": state.summary.current_summary or "",
                "iteration_history": iteration_history,
            }

            source_image_b64 = (image_artefacts.input_images_base64 or [None])[0]

            publish_ephemeral_status(state, "Формулирую запрос для нейросети")

            raw_response = await agents.llm.chat(
                messages=polish_edit_prompt(raw_prompt, img_ctx, source_image_b64=source_image_b64),
                temperature=0.1,
            )
            enhanced_prompt = (raw_response or "").strip() or raw_prompt

            updated_image = image_artefacts.model_copy(
                update={
                    "source_prompt": raw_prompt,
                    "enhanced_prompt": enhanced_prompt,
                    "validation_feedback": "",
                }
            )
            artefacts = state.artefacts.model_copy(update={"image": updated_image})

            publish_ephemeral_status(state, "Запрос готов, отправляю на генерацию")
            return {
                "artefacts": artefacts,
                "summary": state.summary,
                "ephemeral_status": "Промпт для генерации готов.",
            }
        except LLMServiceUnavailableError:
            logger.exception(
                "LLM unavailable in image_prompt_enhancer_node, session=%s",
                state.session_id,
            )
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "image_prompt_enhancer_node failed, session=%s",
                state.session_id,
            )
            return {
                "errors": [*state.errors, f"image_prompt_enhancer_node: {exc}"],
                "ephemeral_status": "Не удалось улучшить промпт генерации.",
            }
