import base64
import io
import logging

import httpx
from PIL import Image, ImageDraw, ImageFont

from app.api.schemas import ImageIterationMeta
from app.api.state_store import publish_ephemeral_status
from app.core.config import settings
from app.domain import StageName
from app.graph.state import AppState
from app.infra.tracing import node_span

logger = logging.getLogger(__name__)


def _decode_base64_image(image_b64: str) -> Image.Image:
    raw = (image_b64 or "").strip()
    if raw.startswith("data:image/"):
        raw = raw.split(",", 1)[1]
    binary = base64.b64decode(raw)
    return Image.open(io.BytesIO(binary)).convert("RGB")


def _encode_png_base64(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _mock_generated_image(input_images_b64: list[str]) -> str:
    if input_images_b64:
        base = _decode_base64_image(input_images_b64[0]).copy()
    else:
        base = Image.new("RGB", (768, 768), (245, 245, 245))

    drawer = ImageDraw.Draw(base)
    text = "СГЕНЕРИРОВАНО"
    font = ImageFont.load_default()
    x = 16
    y = max(16, base.height // 2 - 10)
    drawer.rectangle(
        [(x - 8, y - 8), (x + 220, y + 24)],
        fill=(0, 0, 0),
    )
    drawer.text((x, y), text, fill=(255, 255, 255), font=font)
    return _encode_png_base64(base)


async def _call_diffusion_api(
    model_name: str,
    prompt: str,
    input_images_b64: list[str],
    seed: int | None = None,
) -> tuple[str, str]:
    if not input_images_b64:
        raise ValueError("At least one input image is required for diffusion generation")

    timeout = settings.diffusion_timeout_safe
    url = settings.edit_service_url_safe

    files = []
    for idx, image_b64 in enumerate(input_images_b64):
        image = _decode_base64_image(image_b64)
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        files.append(
            (
                f"image_{idx}",
                (f"image_{idx}.png", buf.getvalue(), "image/png"),
            )
        )

    data = {
        "model": model_name,
        "prompt": prompt,
    }
    if seed is not None:
        data["seed"] = str(seed)

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, data=data, files=files)
        response.raise_for_status()
        mime_type = response.headers.get("content-type", "image/png")
        image_base64 = base64.b64encode(response.content).decode("utf-8")
        return image_base64, mime_type


async def image_diffusion_node(state: AppState):
    with node_span(state.trace_id, "image_diffusion", input=state.user_input):
        try:
            model_name = settings.diffusion_model_name_safe
            image_artefacts = state.artefacts.image
            prompt = (image_artefacts.enhanced_prompt or "").strip() or (state.user_input or "").strip()
            input_images = list(image_artefacts.input_images_base64)
            iteration_index = len(image_artefacts.iterations)
            base_seed = state.image_generation_seed
            effective_seed = int(base_seed) + iteration_index if base_seed is not None else None

            if not prompt:
                return {
                    "errors": [*state.errors, "image_diffusion_node: empty generation prompt"],
                    "ephemeral_status": "Не указан промпт для генерации изображения.",
                }

            publish_ephemeral_status(state, "Нейросеть рисует изображение...")

            use_stub = settings.edit_use_stub
            if use_stub:
                image_base64 = _mock_generated_image(input_images)
                mime_type = "image/png"
                model_used = "mock"
            else:
                image_base64, mime_type = await _call_diffusion_api(
                    model_name=model_name,
                    prompt=prompt,
                    input_images_b64=input_images,
                    seed=effective_seed,
                )
                model_used = model_name

            # Store iteration metadata WITHOUT image bytes (validation node will handle scoring)
            iteration_meta = ImageIterationMeta(
                iteration=iteration_index + 1,
                seed=effective_seed,
                prompt=prompt,
                model=model_used,
                mime_type=mime_type,
            )
            updated_iterations = list(image_artefacts.iterations) + [iteration_meta]

            updated_image = image_artefacts.model_copy(
                update={
                    "current_image_b64": image_base64,
                    "mime_type": mime_type,
                    "mocked": use_stub,
                    "iterations": updated_iterations,
                }
            )
            artefacts = state.artefacts.model_copy(update={"image": updated_image})

            return {
                "artefacts": artefacts,
                "summary": state.summary,
                "previous_stage": state.current_stage,
                "current_stage": StageName.image_generation,
                "next_stage": None,
                "ephemeral_status": f"Генерация итерации {iteration_index + 1} завершена.",
            }
        except httpx.HTTPError:
            publish_ephemeral_status(state, "Сервис занят, жду и пробую снова")
            logger.exception("diffusion API request failed, session=%s", state.session_id)
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("image_diffusion_node failed, session=%s", state.session_id)
            return {
                "errors": [*state.errors, f"image_diffusion_node: {exc}"],
                "ephemeral_status": "Ошибка генерации изображения.",
                "assistant_message": "Не удалось сгенерировать изображение.",
            }
