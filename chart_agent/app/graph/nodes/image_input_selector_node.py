import logging

from app.api.schemas import ImageArtefacts
from app.api.state_store import publish_ephemeral_status
from app.graph.state import AppState
from app.infra.tracing import node_span

logger = logging.getLogger(__name__)


async def image_input_selector_node(state: AppState):
    with node_span(state.trace_id, "image_input_selector"):
        user_images = list(state.user_images_base64 or [])
        image_artefacts = state.artefacts.image
        last_accepted = (image_artefacts.last_accepted_image_base64 or "").strip()
        plot_image = (state.artefacts.plot.image_base64 or "").strip()

        selected_images: list[str] = []
        input_source = ""
        if user_images:
            selected_images = user_images
            input_source = "user"
        elif last_accepted:
            selected_images = [last_accepted]
            input_source = "last_generated"
        elif plot_image:
            selected_images = [plot_image]
            input_source = "plot"

        if not selected_images:
            return {
                "errors": [*state.errors, "image_input_selector_node: no input image available"],
                "assistant_message": (
                    "Не найдено входное изображение. Прикрепите изображение или сначала постройте график."
                ),
                "ephemeral_status": "Нет изображения для генерации.",
            }

        updated_image = image_artefacts.model_copy(
            update={
                "input_images_base64": selected_images,
                "input_source": input_source,
            }
        )
        artefacts = state.artefacts.model_copy(update={"image": updated_image})

        publish_ephemeral_status(state, "Взял изображение за основу")
        state.summary.add_message_for_sumup(
            f"image_generation: input_source={input_source}"
        )
        return {
            "artefacts": artefacts,
            "summary": state.summary,
            "ephemeral_status": "Входное изображение выбрано.",
        }
