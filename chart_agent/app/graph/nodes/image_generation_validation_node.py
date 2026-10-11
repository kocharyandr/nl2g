import logging

from app.api.state_store import publish_ephemeral_status
from app.core.config import settings
from app.domain import StageName
from app.graph.state import AppState
from app.infra.llm.client import LLMServiceUnavailableError
from app.infra.tracing import node_span

logger = logging.getLogger(__name__)


async def image_generation_validation_node(state: AppState, agents):
    with node_span(state.trace_id, "image_generation_validation", input=state.user_input):
        try:
            image_artefacts = state.artefacts.image
            if not image_artefacts.iterations:
                return {
                    "errors": [*state.errors, "image_generation_validation: no iterations"],
                    "current_stage": StageName.error,
                    "ephemeral_status": "Нет итераций генерации для валидации.",
                    "assistant_message": "Не удалось провалидировать генерацию изображения.",
                }

            current_image = image_artefacts.current_image_b64
            if not current_image:
                return {
                    "errors": [*state.errors, "image_generation_validation: missing current image"],
                    "current_stage": StageName.error,
                    "ephemeral_status": "Нет сгенерированного изображения для валидации.",
                    "assistant_message": "Не удалось провалидировать генерацию изображения.",
                }

            latest_meta = image_artefacts.iterations[-1]
            source_image = image_artefacts.input_images_base64[0] if image_artefacts.input_images_base64 else ""
            prompt_used = latest_meta.prompt or image_artefacts.enhanced_prompt
            user_request = (state.user_input or "").strip()

            auto_enabled = bool(state.image_auto_validation_enabled)
            total_iterations = settings.image_auto_validation_iters_safe
            current_iteration = len(image_artefacts.iterations)

            if auto_enabled:
                publish_ephemeral_status(
                    state,
                    f"Оцениваю результат ({current_iteration} из {total_iterations})",
                )
                validation = await agents.image_critic.run(
                    source_image_b64=source_image,
                    generated_image_b64=current_image,
                    user_request=user_request,
                    prompt_used=prompt_used,
                    iteration=current_iteration,
                    total_iterations=total_iterations,
                )
                validation_dict = validation.model_dump()
                latest_score = float(validation_dict.get("score") or 0.0)
                feedback = validation.errors_summary
            else:
                latest_score = 1.0
                feedback = ""

            passed = latest_score >= settings.image_validation_pass_threshold_safe
            # Always run all iterations to find the best result; stop only when budget exhausted.
            need_next = auto_enabled and (current_iteration < total_iterations)

            # Update latest iteration metadata with scoring results
            updated_meta = latest_meta.model_copy(
                update={"score": latest_score, "passed": passed, "errors_summary": feedback}
            )
            updated_iterations = list(image_artefacts.iterations[:-1]) + [updated_meta]

            # Update best image if this iteration is better
            if latest_score > image_artefacts.best_score:
                best_image = current_image
                best_score = latest_score
            else:
                best_image = image_artefacts.image_base64
                best_score = image_artefacts.best_score

            updated_image = image_artefacts.model_copy(
                update={
                    "iterations": updated_iterations,
                    "current_image_b64": None,  # ephemeral, clear after scoring
                    "image_base64": best_image,
                    "best_score": best_score,
                    "validation_feedback": feedback if need_next else "",
                    "need_next_iteration": need_next,
                }
            )

            if not need_next:
                updated_image = updated_image.model_copy(
                    update={"last_accepted_image_base64": best_image}
                )

            artefacts = state.artefacts.model_copy(update={"image": updated_image})

            if need_next:
                state.summary.add_message_for_sumup(
                    f"image_generation: iteration={current_iteration} score={latest_score:.2f} retrying"
                )
                publish_ephemeral_status(
                    state,
                    "Не идеально, попробую улучшить и перегенерировать",
                )
                return {
                    "artefacts": artefacts,
                    "summary": state.summary,
                    "current_stage": StageName.image_generation,
                    "ephemeral_status": "Готовлю следующую итерацию генерации.",
                }

            state.summary.add_message_for_sumup(
                f"image_generation: done iterations={current_iteration} best_score={best_score:.2f}"
            )
            return {
                "artefacts": artefacts,
                "summary": state.summary,
                "previous_stage": state.current_stage,
                "current_stage": StageName.image_generation,
                "next_stage": None,
                "ephemeral_status": "Генерация и автовалидация завершены.",
            }
        except LLMServiceUnavailableError:
            logger.exception(
                "LLM unavailable in image_generation_validation_node, session=%s",
                state.session_id,
            )
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "image_generation_validation_node failed, session=%s",
                state.session_id,
            )
            return {
                "errors": [*state.errors, f"image_generation_validation_node: {exc}"],
                "current_stage": StageName.error,
                "ephemeral_status": "Ошибка валидации генерации.",
                "assistant_message": "Не удалось завершить валидацию генерации изображения.",
            }
